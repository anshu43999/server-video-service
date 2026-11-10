"""Fail converter image builds when the resolved rollback stack drifts.

This supplements check_cpu_runtime.py; it is not a model-accuracy check.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REQUIRED = frozenset(('torch', 'torchvision', 'ultralytics', 'litert-torch',
                      'ai-edge-litert', 'ai-edge-quantizer', 'litert-converter'))


def pinned_versions(path, environment=None):
    expected = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        if req.marker and not req.marker.evaluate(environment):
            continue
        name = canonicalize_name(req.name)
        pins = list(req.specifier)
        if len(pins) != 1 or pins[0].operator != '==' or '*' in pins[0].version or req.url:
            raise ValueError(f'Converter profile requires an exact version: {name}')
        if name in expected:
            raise ValueError(f'Duplicate active converter pin: {name}')
        expected[name] = pins[0].version
    missing = REQUIRED - expected.keys()
    if missing:
        raise ValueError('Missing converter pins: ' + ', '.join(sorted(missing)))
    return expected


def check_versions(expected, get_version=importlib.metadata.version):
    actual = {}
    errors = []
    for name, pin in sorted(expected.items()):
        try:
            actual[name] = get_version(name)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f'{name}: missing (expected {pin})')
            continue
        if actual[name] != pin:
            errors.append(f'{name}: {actual[name]} (expected {pin})')
    if errors:
        raise RuntimeError('Converter dependency mismatch: ' + '; '.join(errors))
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--constraints', type=Path, required=True)
    args = parser.parse_args()
    actual = check_versions(pinned_versions(args.constraints))
    print(json.dumps({'converterProfile': str(args.constraints), 'versions': actual, 'status': 'passed'}, sort_keys=True))


if __name__ == '__main__':
    main()
