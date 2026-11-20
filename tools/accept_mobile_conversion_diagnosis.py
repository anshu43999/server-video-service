"""Read-only evidence checks for M27-T06; not a production accuracy gate."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.resolve().relative_to(root / 'evidence' / 'M27')
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = {}
    checks = []
    def read(name, filename):
        path = root / 'evidence' / 'M27' / ('T06-20261110-' + name) / filename
        data = path.read_bytes()
        inputs[str(path.relative_to(root))] = hashlib.sha256(data).hexdigest()
        return json.loads(data)
    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
    ab = read('user-ab-wsl-01', 'comparison.json')
    win = read('user-ab-windows-01', 'comparison.json')
    old = read('reexport-84123-audit-01', 'reproduction.json')
    bad = read('reexport-84138-audit-01', 'reproduction.json')
    fixed = read('reexport-84138-retain-audit-01', 'reproduction.json')
    fixed2 = read('reexport-84138-retain-01', 'reproduction.json')
    aliases = read('user-weight-aliases-01', 'weights.json')
    suspect, normal = ab['artifacts']
    check('Both supplied artifacts match Manifest sizes and hashes', all(
        a['actualSha256'] == a['manifest']['modelFile']['sha256'] and
        a['actualSizeBytes'] == a['manifest']['modelFile']['sizeBytes'] for a in ab['artifacts']))
    check('Source linkage matches actual local PT in all experiments', all(
        x['sourceSha256'] == ab['source']['sha256'] for x in (old, bad, fixed, fixed2)) and
        all(a['manifest']['source']['revision'] == ab['source']['sha256'] for a in ab['artifacts']))
    check('Supplied failure reproduces across desktop runtimes and delegates', all(
        a[d]['allClasses']['nmsCount'] == 0 for a in (suspect, win['artifacts'][0])
        for d in ('defaultDelegate', 'withoutDefaultDelegates')))
    check('Normal supplied model and PT remain nonempty on the same input',
          normal['defaultDelegate']['allClasses']['nmsCount'] == ab['pt']['nmsCount'] == 5)
    check('Desktop runtimes have identical default-delegate abnormal scores',
          suspect['defaultDelegate']['allClasses']['classMax'] == win['artifacts'][0]['defaultDelegate']['allClasses']['classMax'])
    check('Fixed comparison uses same image tensor in every experiment',
          len({x['sample']['inputSha256'] for x in (ab, old, bad, fixed, fixed2)}) == 1)
    check('Lower-level package versions identical in controlled exports',
          all({k:v for k,v in x['versions'].items() if k != 'ultralyticsImported'} ==
              {k:v for k,v in old['versions'].items() if k != 'ultralyticsImported'} for x in (bad, fixed, fixed2)))
    check('8.4.138 package source identical in failing and intervention runs',
          bad['packageSourceHashes'] == fixed['packageSourceHashes'] == fixed2['packageSourceHashes'])
    calibration = lambda x: [(Path(v['files'][0]).name, v['shape'], v['sha256']) for v in x['calibrationBatches']]
    check('Exact four calibration tensors and order identical', len(calibration(old)) == 4 and
          all(calibration(x) == calibration(old) for x in (bad, fixed, fixed2)))
    check('Failing exporter receives correct eager scores before conversion',
          bad['eagerBeforeConvert']['classMax']['helmet'] > .8 and bad['eagerBeforeConvert']['nmsCount'] == 5)
    check('Failure already appears before INT8 quantization',
          bad['artifacts']['fp32BeforeQuantization']['defaultDelegate']['allClasses']['classMax']['helmet'] < .35)
    check('Pointer-key collision captured in failing exporter', len(bad['constantFingerprintCollisions']) > 0)
    check('Retaining constant storage removes observed key collisions', fixed['retainedConstantCount'] > 0 and
          not fixed['constantFingerprintCollisions'] and not old['constantFingerprintCollisions'])
    check('Two isolated interventions produce the exact normal graph bytes', all(
        x['artifacts']['int8']['flatbufferPrefixSha256'] == normal['flatbufferPrefixSha256']
        for x in (old, fixed, fixed2)))
    check('Two isolated interventions reproduce exact normal raw outputs', all(
        x['artifacts']['int8']['defaultDelegate']['allClasses']['rawSha256'] == normal['defaultDelegate']['allClasses']['rawSha256']
        for x in (old, fixed, fixed2)))
    check('Supplied abnormal model has independently found cross-layer weight aliases',
          aliases['convCount'] == 81 and aliases['mismatchCount'] == 17 and aliases['aliasMatches'] == 14 and
          aliases['baseline']['sha256'] == normal['actualSha256'] and aliases['suspect']['sha256'] == suspect['actualSha256'])
    for name, folder in [('comparison-tests', 'tests'), ('harness-tests', 'harness/tests')]:
        pattern = 'test_mobile_model_comparison.py' if folder == 'tests' else 'test_*.py'
        proc = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', folder, '-p', pattern, '-v'],
                              cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace')
        (args.output / (name + '.log')).write_text(proc.stdout + proc.stderr, encoding='utf-8')
        check(name, proc.returncode == 0)
    result = {'scope': 'M27-T06 diagnostic evidence and regression only; NOT production repair, deployment or business accuracy approval',
              'passed': all(c['passed'] for c in checks), 'checks': checks, 'inputEvidenceSha256': inputs}
    (args.output / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
