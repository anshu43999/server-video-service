"""Isolated diagnostic export, never a service worker or deployable signed artifact.

Copies all writable model/calibration/package inputs to a new evidence directory.
No registry, shared environment package installation, phone or database access.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import socket
import sys
from datetime import datetime, timezone


def block_network(*args, **kwargs):
    raise RuntimeError('network disabled in isolated export diagnostic')


class FingerprintAudit:
    """Detect identical pointer keys reused for different constant bytes."""
    def __init__(self):
        self.seen = {}
        self.collisions = []

    def observe(self, key, content_hash):
        previous = self.seen.get(key)
        if previous is not None and previous != content_hash:
            self.collisions.append({'key': str(key), 'previousSha256': previous, 'newSha256': content_hash})
        self.seen[key] = content_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--ultralytics-package', type=Path)
    parser.add_argument('--skip-index-select-lowering', action='store_true',
                        help='Diagnostic only: suppress new LiteRT index_select rewrite registration')
    parser.add_argument('--retain-constant-tensors', action='store_true',
                        help='Diagnostic only: keep temporary constant storage alive throughout lowering')
    parser.add_argument('--audit-constant-collisions', action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.relative_to(root / 'evidence' / 'M27')
    output.mkdir(parents=True, exist_ok=False)
    config = output / 'runtime-config'
    config.mkdir()
    os.environ.update(YOLO_CONFIG_DIR=str(config), YOLO_AUTOINSTALL='false',
                      YOLO_OFFLINE='true', CUDA_VISIBLE_DEVICES='',
                      PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1')
    socket.socket.connect = block_network
    socket.socket.connect_ex = block_network
    socket.create_connection = block_network
    if args.ultralytics_package:
        package = args.ultralytics_package.resolve()
        if package.name != 'ultralytics' or not (package / '__init__.py').is_file():
            raise ValueError('expected existing ultralytics package directory')
        isolated = output / 'package'
        shutil.copytree(package, isolated / 'ultralytics', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        sys.path.insert(0, str(isolated))
    source = output / 'source.pt'
    shutil.copyfile(args.source, source)
    calibration = output / 'calibration'
    shutil.copytree(root / 'calibration' / 'builtin' / 'dev8', calibration)
    yaml = calibration / 'dataset.yaml'
    yaml.write_text(yaml.read_text(encoding='utf-8').replace('__AIYOLO_BUILTIN_CALIBRATION_ROOT__', str(calibration)), encoding='utf-8')
    report = {'createdAt': datetime.now(timezone.utc).isoformat(),
              'scope': 'local isolated experiment, NOT actual production environment reconstruction',
              'sourceOriginal': str(args.source), 'packageOriginal': str(args.ultralytics_package),
              'calibrationBatches': [], 'artifacts': {}}
    with (output / 'export.log').open('x', encoding='utf-8') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        import numpy as np
        import torch
        import ultralytics
        import litert_torch
        from ai_edge_quantizer import quantizer
        from PIL import Image
        from ultralytics import YOLO
        from ultralytics.engine.exporter import Exporter
        import ultralytics.data.utils as data_utils
        # No plots are generated. Dataset validation otherwise downloads a font
        # even with YOLO_OFFLINE set; it is unrelated to calibration pixels.
        data_utils.check_font = lambda *a, **kw: None
        from compare_mobile_model_outputs import android_input, digest, embedded_metadata, graph_bytes_hash, graph_summary, run_tflite, summarize
        torch.set_num_threads(1)
        torch.manual_seed(0)
        report['versions'] = {n: importlib.metadata.version(n) for n in
            ('torch', 'litert-torch', 'ai-edge-litert', 'ai-edge-quantizer', 'litert-converter', 'numpy', 'pillow')}
        report['versions']['ultralyticsImported'] = ultralytics.__version__
        report['ultralyticsImportedPath'] = ultralytics.__file__
        report['sourceSha256'] = digest(source.read_bytes())
        report['packageSourceHashes'] = {str(p.relative_to(Path(ultralytics.__file__).parent)): digest(p.read_bytes())
            for p in sorted(Path(ultralytics.__file__).parent.rglob('*.py'))}
        report['calibrationImageHashes'] = {str(p.relative_to(calibration)): digest(p.read_bytes())
            for p in sorted((calibration / 'images').rglob('*')) if p.is_file()}
        original_loader = Exporter.get_int8_calibration_dataloader
        def traced_loader(self, *a, **kw):
            loader = original_loader(self, *a, **kw)
            report['calibrationSplit'] = self.args.split or 'val'
            batches = []
            for batch in loader:
                tensor = (batch['img'].cpu().float() / 255.0).numpy()
                report['calibrationBatches'].append({'files': [str(x) for x in batch.get('im_file', [])],
                    'shape': list(tensor.shape), 'sha256': digest(tensor.tobytes()),
                    'min': float(tensor.min()), 'max': float(tensor.max())})
                batches.append(batch)
            return batches
        Exporter.get_int8_calibration_dataloader = traced_loader
        original_quantizer = quantizer.Quantizer.__init__
        def traced_quantizer(self, model_path, *a, **kw):
            shutil.copyfile(model_path, output / 'pre_quant_fp32.tflite')
            return original_quantizer(self, model_path, *a, **kw)
        quantizer.Quantizer.__init__ = traced_quantizer
        tensor, transform = android_input(np.asarray(Image.open(args.image).convert('RGB')))
        model = YOLO(str(source))
        labels = [str(model.names[i]) for i in range(len(model.names))]
        def eager_probe(module, normalized):
            probe = copy.deepcopy(module)
            with torch.inference_mode():
                values = probe(torch.from_numpy(tensor))
            raw = (values[0] if isinstance(values, tuple) else values).detach().cpu().numpy().copy()
            if not normalized:
                raw[:, :4] /= np.float32(640)
            return summarize(raw, labels)
        report['eagerBeforeWarmup'] = eager_probe(model.model, False)
        model.predict(np.zeros((640, 640, 3), dtype=np.uint8), imgsz=640, device='cpu', verbose=False)
        report['eagerAfterWarmup'] = eager_probe(model.model, False)
        original_convert = litert_torch.convert
        def traced_convert(module, *a, **kw):
            report['convertModuleTraining'] = [(name, m.training) for name, m in module.named_modules() if m.training]
            report['eagerBeforeConvert'] = eager_probe(module, True)
            return original_convert(module, *a, **kw)
        litert_torch.convert = traced_convert
        report['retainConstantTensors'] = args.retain_constant_tensors
        if args.retain_constant_tensors or args.audit_constant_collisions:
            from litert_torch.backend import inline_consts
            original_fingerprint = inline_consts._ConstantFingerprint.from_tensor.__func__
            retained = []
            fingerprint_audit = FingerprintAudit()
            def retaining_fingerprint(cls, value):
                if args.retain_constant_tensors:
                    retained.append(value)
                key = original_fingerprint(cls, value)
                if args.audit_constant_collisions:
                    fingerprint_audit.observe(key, digest(value.numpy().tobytes()))
                return key
            inline_consts._ConstantFingerprint.from_tensor = classmethod(retaining_fingerprint)
            report['constantLoweringSourceSha256'] = digest(Path(inline_consts.__file__).read_bytes())
        report['skipIndexSelectLowering'] = args.skip_index_select_lowering
        if args.skip_index_select_lowering:
            original_registration = litert_torch.fx_infra.decomp.add_pre_lower_decomp
            def traced_registration(operation, fn):
                if operation == torch.ops.aten.index_select.default:
                    report['indexSelectLoweringSuppressed'] = True
                    return None
                return original_registration(operation, fn)
            litert_torch.fx_infra.decomp.add_pre_lower_decomp = traced_registration
        report['exportArguments'] = dict(format='litert', imgsz=640, quantize='int8', data=str(yaml), nms=False, batch=1, device='cpu')
        result = Path(model.export(**report['exportArguments']))
        if args.retain_constant_tensors:
            report['retainedConstantCount'] = len(retained)
        if args.audit_constant_collisions:
            report['constantFingerprintCollisions'] = fingerprint_audit.collisions
        report['sample'] = {'path': str(args.image), 'sha256': digest(args.image.read_bytes()),
                            'inputSha256': digest(tensor.tobytes()), 'transform': transform}
        for key, path in [('int8', result), ('fp32BeforeQuantization', output / 'pre_quant_fp32.tflite')]:
            data = path.read_bytes()
            report['artifacts'][key] = {'path': str(path), 'sha256': digest(data), 'bytes': len(data),
                'flatbufferPrefixSha256': graph_bytes_hash(data), 'graph': graph_summary(data),
                'metadata': embedded_metadata(data),
                'defaultDelegate': run_tflite(data, tensor, labels, .35, False),
                'withoutDefaultDelegates': run_tflite(data, tensor, labels, .35, True)}
        report['limitations'] = ['Single image, no business accuracy acceptance',
            'Package isolated without replacing shared venv; imported package version recorded explicitly',
            'Calibration instrumented to record exact tensors, unlike historical exports',
            'No production source-byte or complete environment proof; no signed/released candidate']
        (output / 'reproduction.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'report': str(output / 'reproduction.json'),
        'ultralytics': report['versions']['ultralyticsImported'],
        'int8Max': report['artifacts']['int8']['defaultDelegate']['allClasses']['classMax'],
        'fp32Max': report['artifacts']['fp32BeforeQuantization']['defaultDelegate']['allClasses']['classMax']}))


if __name__ == '__main__':
    main()
