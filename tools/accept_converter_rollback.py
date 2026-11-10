"""Local-only real worker regression for the converter rollback candidate.

Only writes a new evidence/M27 directory. No registration or deployment.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def child(directory, worker):
    import resource
    import socket
    def denied(*args, **kwargs):
        raise RuntimeError('Network disabled in rollback regression')
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    os.chdir(directory)
    # Font lookup does not affect calibration pixels; worker/export unchanged.
    import ultralytics.data.utils as data_utils
    data_utils.check_font = lambda *a, **kw: None
    # Prefer the installed image worker when explicitly testing a container.
    sys.path.insert(0, str(worker.parent))
    from conversion_worker import execute
    import conversion_worker
    if Path(conversion_worker.__file__).resolve() != worker:
        raise RuntimeError('Imported worker is not the requested verified worker')
    started = time.monotonic()
    result = execute('mobile', directory)
    result['elapsedSeconds'] = time.monotonic() - started
    result['peakRssKiB'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result['workerPath'] = str(worker)
    result['workerSha256'] = sha(worker)
    (directory / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result.get('ok') else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', type=Path)
    parser.add_argument('--worker', type=Path, help='Installed image worker; must match checked-out source bytes')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--normal-manifest', type=Path)
    parser.add_argument('--normal-model', type=Path)
    parser.add_argument('--abnormal-manifest', type=Path)
    parser.add_argument('--abnormal-model', type=Path)
    parser.add_argument('--image', action='append', type=Path, default=[])
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--require-target-profile', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    worker = (args.worker or root / 'tools/conversion_worker.py').resolve()
    if sha(worker) != sha(root / 'tools/conversion_worker.py'):
        raise RuntimeError('Requested worker differs from checked-out release source')
    if args.child:
        args.child.resolve().relative_to(root / 'evidence' / 'M27')
        return child(args.child.resolve(), worker)
    if not all((args.source, args.normal_manifest, args.normal_model, args.abnormal_manifest, args.abnormal_model, args.output)) or not args.image or not 2 <= args.runs <= 5:
        parser.error('all model paths, images, output and 2..5 runs are required')
    output = args.output.resolve()
    output.relative_to(root / 'evidence' / 'M27')
    output.mkdir(parents=True, exist_ok=False)
    config = output / 'runtime-config'
    config.mkdir()
    os.environ.update(YOLO_CONFIG_DIR=str(config), YOLO_AUTOINSTALL='false',
                      YOLO_OFFLINE='true', CUDA_VISIBLE_DEVICES='', JAX_PLATFORMS='cpu',
                      PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1')
    from check_converter_runtime import pinned_versions
    expected = pinned_versions(root / 'constraints-converter.txt')
    actual = {n: importlib.metadata.version(n) for n in expected}
    if actual['ultralytics'] != '8.4.123':
        raise RuntimeError('rollback regression requires actual Ultralytics 8.4.123')
    mismatches = {n: {'expected': v, 'actual': actual[n]} for n, v in expected.items() if actual[n] != v}
    if args.require_target_profile and mismatches:
        raise RuntimeError('Target dependency profile mismatch: ' + json.dumps(mismatches))
    from compare_mobile_model_outputs import android_input, digest, graph_bytes_hash, run_tflite, summarize, verify_identity
    normal = args.normal_model.read_bytes()
    abnormal = args.abnormal_model.read_bytes()
    manifest = json.loads(args.normal_manifest.read_text(encoding='utf-8'))
    bad_manifest = json.loads(args.abnormal_manifest.read_text(encoding='utf-8'))
    source_hash = sha(args.source)
    verify_identity(normal, manifest, source_hash)
    verify_identity(abnormal, bad_manifest, source_hash)
    labels = manifest['labels']
    if labels != bad_manifest['labels']:
        raise RuntimeError('label mismatch')
    report = {'scope': 'Local rollback candidate regression, not production deployment/accuracy approval',
              'python': platform.python_version(), 'versions': actual, 'targetProfile': expected,
              'targetDependencyMismatches': mismatches, 'sourceSha256': source_hash,
              'normalSha256': digest(normal), 'abnormalSha256': digest(abnormal),
              'normalGraphSha256': graph_bytes_hash(normal), 'runs': [], 'samples': [],
              'codeHashes': {n: sha(root / n) for n in ('Dockerfile.converter', 'constraints-converter.txt',
                  'constraints-cpu.txt', 'tools/check_converter_runtime.py', 'tools/conversion_worker.py',
                  'tools/accept_converter_rollback.py', 'tools/compare_mobile_model_outputs.py')}}
    calibration = output / 'calibration'
    shutil.copytree(root / 'calibration/builtin/dev8', calibration)
    yaml = calibration / 'dataset.yaml'
    yaml.write_text(yaml.read_text(encoding='utf-8').replace('__AIYOLO_BUILTIN_CALIBRATION_ROOT__', str(calibration)), encoding='utf-8')
    for i in range(args.runs):
        folder = output / f'run-{i + 1}'
        folder.mkdir()
        shutil.copyfile(args.source, folder / 'source.pt')
        (folder / 'request.json').write_text(json.dumps({'input_size': 640, 'calibration_data': str(yaml)}), encoding='utf-8')
        with (folder / 'worker.log').open('x', encoding='utf-8') as log:
            completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--child', str(folder), '--worker', str(worker)],
                                       stdout=log, stderr=subprocess.STDOUT, timeout=900, check=False)
        if completed.returncode:
            raise RuntimeError(f'worker run {i + 1} failed; inspect {folder / "worker.log"}')
        result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
        artifact = folder / 'android.tflite'
        graph_hash = graph_bytes_hash(artifact.read_bytes())
        report['runs'].append({'path': str(artifact), 'sha256': sha(artifact), 'graphSha256': graph_hash,
                              'matchesNormalGraph': graph_hash == report['normalGraphSha256'], 'result': result})
        print(json.dumps({'run': i + 1, 'matchesNormalGraph': graph_hash == report['normalGraphSha256'],
                          'seconds': result['elapsedSeconds'], 'peakRssMiB': result['peakRssKiB'] / 1024}), flush=True)
    from PIL import Image
    import numpy as np
    import torch
    import torchvision
    from ultralytics import YOLO
    report['importedRuntime'] = {'torch': torch.__version__, 'torchPath': torch.__file__,
                                'torchvision': torchvision.__version__, 'torchvisionPath': torchvision.__file__}
    if torch.__version__ != actual['torch'] or torchvision.__version__ != actual['torchvision']:
        raise RuntimeError('Imported Torch/TorchVision differ from recorded distribution metadata')
    torch.set_num_threads(1)
    model = YOLO(str(args.source))
    model.model.eval()
    if labels != [str(model.names[i]) for i in range(len(model.names))]:
        raise RuntimeError('PT labels mismatch')
    candidates = [Path(x['path']).read_bytes() for x in report['runs']]
    for image in args.image:
        tensor, transform = android_input(np.asarray(Image.open(image).convert('RGB')))
        with torch.inference_mode():
            value = model.model(torch.from_numpy(tensor))
        raw = (value[0] if isinstance(value, tuple) else value).detach().cpu().numpy().copy()
        raw[:, :4] /= np.float32(640)
        row = {'image': str(image), 'sha256': sha(image), 'inputSha256': digest(tensor.tobytes()),
               'transform': transform, 'pt': summarize(raw, labels), 'runtimes': []}
        for no_delegate in (False, True):
            baseline = run_tflite(normal, tensor, labels, .35, no_delegate)
            failure = run_tflite(abnormal, tensor, labels, .35, no_delegate)
            results = [run_tflite(data, tensor, labels, .35, no_delegate) for data in candidates]
            row['runtimes'].append({'withoutDefaultDelegates': no_delegate, 'normal': baseline, 'abnormal': failure,
                                   'candidates': results, 'allRawOutputsEqualNormal': all(
                                       x['allClasses']['rawSha256'] == baseline['allClasses']['rawSha256'] for x in results)})
        report['samples'].append(row)
        print(json.dumps({'sample': image.name, 'allRunsEqualNormal': all(x['allRawOutputsEqualNormal'] for x in row['runtimes'])}), flush=True)
    report['localRegressionPassed'] = all(x['matchesNormalGraph'] for x in report['runs']) and all(
        item['allRawOutputsEqualNormal'] for row in report['samples'] for item in row['runtimes'])
    report['limitations'] = ['This tool does not deploy, publish models, mutate phones or connect to services',
        'Existing normal artifact is a consistency reference, not accuracy ground truth',
        'Only supplied helmet model covered; other model families and labelled accuracy unverified',
        'Worker function is real, font-check only bypassed; child Python socket networking disabled',
        'Peak RSS measured locally per worker; production container resource limits not validated',
        'Target Python is Docker python:3.11; compare actual Python and dependency mismatches explicitly']
    (output / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output / 'acceptance.json'), 'passed': report['localRegressionPassed'],
                      'targetDependencyMismatches': mismatches}), flush=True)
    return 0 if report['localRegressionPassed'] else 1


if __name__ == '__main__':
    sys.exit(main())
