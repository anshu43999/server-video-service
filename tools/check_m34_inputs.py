"""Read-only model/video probe for M34-T06; never production acceptance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = 'uploaded-c8dffd82f6a24deca8d03afdae24956f'
VIDEOS = [ROOT.parent / 'information/rtsp-test-videos' / name
          for name in ('test.mp4', 'sucai1.mp4')]


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def child(destination):
    # Permit no remote resource downloads or accidental remote calls.
    def audit(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            raise RuntimeError('input preflight does not permit network access')
    sys.addaudithook(audit)
    sys.path.insert(0, str(ROOT))
    import cv2
    from app.detector import YoloDetector

    registry_path = ROOT / 'models/registry.json'
    original_hash = sha(registry_path)
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    model = next(m for m in registry['models'] if m['modelId'] == MODEL_ID and m['version'] == '1.0.0')
    artifact = next(a for a in model['artifacts'] if a['platform'] == 'server' and a['format'] == 'pt')
    model_path = (ROOT / artifact['path']).resolve()
    if not model_path.is_relative_to(ROOT / 'models') or not model_path.is_file():
        raise ValueError('model artifact is missing or outside model directory')
    digest = sha(model_path)
    if digest.lower() != artifact['sha256'].lower() or model_path.stat().st_size != artifact['sizeBytes']:
        raise ValueError('model artifact identity mismatch')
    if model.get('status') != 'PUBLISHED' or not model.get('releaseEligible') or 'pc' not in model.get('publishedTargets', []):
        raise ValueError('existing local model is not eligible for PC tests')
    report = {'task': 'M34-T06', 'time': datetime.now(timezone.utc).isoformat(),
              'scope': 'real local input preflight only; NOT three-end or production acceptance',
              'model': {'modelId': MODEL_ID, 'version': model['version'], 'sha256': digest,
                        'path': str(model_path), 'labels': model['labels']}, 'videos': []}
    detector = YoloDetector(str(model_path), confidence=.25, imgsz=640,
                            classes=model['labels'], model_id=MODEL_ID)
    for path in VIDEOS:
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError('local video could not be opened: ' + path.name)
        try:
            count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            entry = {'path': str(path), 'sha256': sha(path), 'frames': count, 'fps': fps, 'samples': []}
            for number in sorted(set([0, max(0, count // 4), max(0, count // 2)])):
                capture.set(cv2.CAP_PROP_POS_FRAMES, number)
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError('video frame decode failed')
                result = detector.infer(frame)
                if detector.load_error:
                    raise RuntimeError(detector.load_error)
                sample = {'frame': number, 'shape': list(frame.shape), 'inferenceMs': result.inference_ms,
                          'detections': [{'label': d.label, 'confidence': d.confidence}
                                         for d in result.detections]}
                entry['samples'].append(sample)
                if result.detections and not (destination / 'detected-input.jpg').exists():
                    if not cv2.imwrite(str(destination / 'detected-input.jpg'), frame):
                        raise RuntimeError('cannot save input evidence')
            report['videos'].append(entry)
        finally:
            capture.release()
    report['registryUnchanged'] = sha(registry_path) == original_hash
    if not report['registryUnchanged']:
        raise RuntimeError('source registry changed during probe')
    report['realInferencePassed'] = any(s['detections'] for v in report['videos'] for s in v['samples'])
    (destination / 'inputs.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['realInferencePassed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', type=Path)
    args = parser.parse_args()
    if args.child:
        return child(args.child)
    evidence = ROOT / 'evidence/M34/M34-T06'
    evidence.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='input-', dir=evidence)).resolve()
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE'}}
    env.update(YOLO_OFFLINE='true', YOLO_CONFIG_DIR=str(destination / 'yolo-settings'),
               PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    with (destination / 'probe.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--child', str(destination)],
                                cwd=destination, env=env, stdout=log, stderr=log, timeout=180)
    print(json.dumps({'exitCode': result.returncode, 'evidence': str(destination)}))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
