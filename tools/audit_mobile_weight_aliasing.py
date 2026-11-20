"""Compare convolution constants in two TFLite files, including external buffers."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
try:
    from .compare_mobile_model_outputs import buffer_bytes, digest, graph_summary
except ImportError:
    from compare_mobile_model_outputs import buffer_bytes, digest, graph_summary


def convolutions(data):
    from ai_edge_litert import schema_py_generated as schema
    model = schema.Model.GetRootAsModel(data, 0)
    graph = model.Subgraphs(0)
    result = []
    for i in range(graph.OperatorsLength()):
        op = graph.Operators(i)
        if model.OperatorCodes(op.OpcodeIndex()).BuiltinCode() != schema.BuiltinOperator.CONV_2D:
            continue
        tensor = graph.Tensors(op.Inputs(1))
        quantization = tensor.Quantization()
        result.append({'ordinal': len(result), 'operatorIndex': i, 'name': tensor.Name().decode(),
            'shape': tensor.ShapeAsNumpy().tolist(), 'type': tensor.Type(),
            'sha256': digest(buffer_bytes(model.Buffers(tensor.Buffer()), data)),
            'scales': quantization.ScaleAsNumpy().tolist() if quantization and quantization.ScaleLength() else [],
            'zeros': quantization.ZeroPointAsNumpy().tolist() if quantization and quantization.ZeroPointLength() else []})
    return result


def same_weight(a, b):
    return (a['shape'] == b['shape'] and a['type'] == b['type'] and a['sha256'] == b['sha256']
            and a['zeros'] == b['zeros'] and len(a['scales']) == len(b['scales'])
            and np.allclose(a['scales'], b['scales'], rtol=2e-6, atol=1e-9))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--suspect', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.resolve().relative_to(root / 'evidence' / 'M27')
    args.output.mkdir(parents=True, exist_ok=False)
    baseline_bytes, suspect_bytes = args.baseline.read_bytes(), args.suspect.read_bytes()
    baseline, suspect = convolutions(baseline_bytes), convolutions(suspect_bytes)
    if len(baseline) != len(suspect):
        raise ValueError('different convolution count; ordinal comparison is not valid')
    rows = []
    for a, b in zip(baseline, suspect):
        if a['shape'] != b['shape']:
            raise ValueError('different convolution shapes; ordinal comparison is not valid')
        if not same_weight(a, b):
            rows.append({'ordinal': a['ordinal'], 'expectedName': a['name'], 'actualName': b['name'],
                         'matchesOtherBaselineOrdinals': [x['ordinal'] for x in baseline if same_weight(x, b)],
                         'expected': a, 'actual': b})
    report = {'baseline': {'path': str(args.baseline), 'sha256': digest(baseline_bytes), 'graph': graph_summary(baseline_bytes)},
              'suspect': {'path': str(args.suspect), 'sha256': digest(suspect_bytes), 'graph': graph_summary(suspect_bytes)},
              'convCount': len(baseline), 'mismatchCount': len(rows),
              'aliasMatches': sum(bool(x['matchesOtherBaselineOrdinals']) for x in rows),
              'mismatches': rows,
              'method': 'Ordered CONV_2D tensors, matching count/shapes; constant bytes exact, per-channel scales rtol=2e-6 atol=1e-9. Layer names included for manual alignment. Not production process tracing.'}
    (args.output / 'weights.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(args.output / 'weights.json'), 'convCount': len(baseline),
                      'mismatches': len(rows), 'aliasMatches': report['aliasMatches'],
                      'mapping': {x['ordinal']: x['matchesOtherBaselineOrdinals'] for x in rows}}))


if __name__ == '__main__':
    main()
