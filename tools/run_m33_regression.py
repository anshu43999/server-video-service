"""M33-T26: disposable source/data copy and loopback PostgreSQL regression."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def child(pattern):
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'tests'))
    # No .env exists in the disposable copy. Also block accidental remote calls.
    def audit(event, args):
        if event == 'socket.connect':
            address = args[1]
            if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
                raise RuntimeError('regression blocked non-loopback network destination')
        if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', 'localhost', '::1', None):
            raise RuntimeError('regression blocked non-loopback name resolution')
    sys.addaudithook(audit)
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=item)
        for item in pattern.split(',')
    )
    class DiagnosticResult(unittest.TextTestResult):
        def addError(self, test, err):
            super().addError(test, err)
            self.stream.writeln(self.errors[-1][1])

        def addFailure(self, test, err):
            super().addFailure(test, err)
            self.stream.writeln(self.failures[-1][1])

    result = unittest.TextTestRunner(verbosity=2, resultclass=DiagnosticResult).run(suite)
    report = {'tests': result.testsRun, 'passed': result.wasSuccessful(),
              'failures': [{'test': str(t), 'trace': trace} for t, trace in result.failures],
              'errors': [{'test': str(t), 'trace': trace} for t, trace in result.errors],
              'skipped': [{'test': str(t), 'reason': reason} for t, reason in result.skipped]}
    (ROOT.parent / 'tests-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


def run(pattern, label):
    pg = Path('D:/PostgreSQL/bin')
    runtime = Path(tempfile.mkdtemp(prefix='m33-t26-', dir=ROOT / '.tmp')).resolve()
    source, data = runtime / 'source', runtime / 'pg-data'
    source.mkdir()
    allowed = {'app', 'tests', 'tools', 'alembic', 'converter_service', 'deploy', 'calibration', 'docs'}
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split(chr(0))
    extra = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z',
                                     'app', 'tests', 'tools', 'deploy', 'Dockerfile.app-updates'],
                                    cwd=ROOT).decode().split(chr(0))
    hashes = {}
    fixture_files = {'harness/task-state.json', 'models/converted/yolo11n_640_manifest.json',
                     'admin-web/package.json', 'admin-web/package-lock.json'}
    for name in sorted(set(tracked + extra + ['tools/run_m33_regression.py'])):
        if not name:
            continue
        path = Path(name)
        if path.parts[0] not in allowed and len(path.parts) != 1 and name not in fixture_files:
            continue
        if any(p in ('__pycache__', 'node_modules', '.git') or p.startswith('tmp') for p in path.parts):
            continue
        if (path.name.startswith('.env') and path.name != '.env.example') or path.suffix in ('.key', '.pem'):
            continue
        original = ROOT / path
        if not original.is_file() or original.is_symlink():
            continue
        dest = source / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, dest)
        if path.suffix in ('.py', '.ini'):
            hashes[name] = hashlib.sha256(dest.read_bytes()).hexdigest()
    # Static browser sources/build outputs are used by API/static-contract tests.
    for name in ('dist', 'dist-preview', 'src'):
        if (ROOT / 'admin-web' / name).is_dir():
            shutil.copytree(ROOT / 'admin-web' / name, source / 'admin-web' / name,
                            ignore=shutil.ignore_patterns('node_modules', '__pycache__'))
    (source / '.tmp').mkdir(exist_ok=True)
    # User-uploaded model files are mutable application data, not test fixtures.
    # Exercise real startup validation against a valid empty test registry;
    # model-specific tests create and validate their own artifacts.
    (source / 'models').mkdir(exist_ok=True)
    (source / 'models/registry.json').write_text(
        json.dumps({'models': [], 'activeServerModel': None}), encoding='utf-8')
    # Read-only cross-repository contracts; never copy app code or credentials.
    for name in ('docs/schemas/mobile-model-update-v1.schema.json',
                 'app/src/test/resources/contracts/m111-model-update-v1-golden.json',
                 'app/src/test/resources/contracts/m112-lifecycle-v1-golden.json'):
        original = ROOT.parent / 'mobile-app' / name
        destination = runtime / 'mobile-app' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        hashes['mobile-app/' + name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    base_keys = {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'PROGRAMFILES', 'PROGRAMFILES(X86)'}
    env = {k: v for k, v in os.environ.items() if k.upper() in base_keys}
    env.update(DATABASE_URL=f'postgresql+psycopg://aiyolo_test@127.0.0.1:{port}/postgres',
               RUN_POSTGRES_TESTS='1', RUN_POSTGRES_MIGRATION_TESTS='1', PYTHONIOENCODING='utf-8',
               PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1',
               CALIBRATION_ROOT=str(source / 'calibration'), MINIO_ENDPOINT='',
               CONVERSION_AUTO_CONVERT='false', APP_UPDATES_ENABLED='false',
               APP_APK_EXTERNAL_ENABLED='false', APP_APK_WORKER_ENABLED='false')
    env.update(YOLO_OFFLINE='true', YOLO_CONFIG_DIR=str(runtime / 'yolo-settings'))
    report = {'task': 'M33-T26', 'label': label, 'pattern': pattern,
              'runtime': str(runtime), 'dataDirectory': str(data), 'port': port,
              'sourceHashes': hashes, 'startedAt': datetime.now(timezone.utc).isoformat()}
    report['modelFixture'] = 'empty disposable registry; original model files untouched'
    started = False
    print('ISOLATED_RUNTIME=' + str(runtime), flush=True)
    try:
        with (runtime / 'setup.log').open('w', encoding='utf-8') as log:
            subprocess.run([str(pg / 'initdb.exe'), '-D', str(data), '-U', 'aiyolo_test',
                            '--auth-local=trust', '--auth-host=trust', '--encoding=UTF8', '--locale=C'],
                           env=env, stdout=log, stderr=log, check=True, timeout=60)
            started = True  # Stop only this exact data directory even if startup fails.
            subprocess.run([str(pg / 'pg_ctl.exe'), '-D', str(data), '-l', str(runtime / 'postgres.log'),
                            '-o', f'-h 127.0.0.1 -p {port}', '-w', '-t', '45', 'start'],
                           env=env, stdout=log, stderr=log, check=True, timeout=60)
            import psycopg
            with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='aiyolo_test') as con:
                actual = con.execute('show data_directory').fetchone()[0]
                assert Path(actual).resolve() == data
                assert con.execute('select current_user').fetchone()[0] == 'aiyolo_test'
            report['identityVerified'] = True
            report['pid'] = int((data / 'postmaster.pid').read_text().splitlines()[0])
            subprocess.run([sys.executable, '-B', '-m', 'alembic', 'upgrade', 'head'], cwd=source,
                           env=env, stdout=log, stderr=log, check=True, timeout=90)
        print(f'ISOLATED_DATABASE=127.0.0.1:{port}/postgres role=aiyolo_test VERIFIED', flush=True)
        with (runtime / 'tests.log').open('w', encoding='utf-8') as log:
            process = subprocess.run([sys.executable, '-B', str(source / 'tools/run_m33_regression.py'),
                                      '--child', '--pattern', pattern], cwd=source, env=env,
                                     stdout=log, stderr=log, timeout=1800)
        report['exitCode'] = process.returncode
        if (runtime / 'tests-result.json').exists():
            outcome = json.loads((runtime / 'tests-result.json').read_text(encoding='utf-8'))
            report.update(tests=outcome['tests'], failures=len(outcome['failures']), errors=len(outcome['errors']),
                          skipped=len(outcome['skipped']), passed=outcome['passed'])
        with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='aiyolo_test') as con:
            report['remainingSchemas'] = [r[0] for r in con.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname NOT IN ('public','information_schema')")]
    except Exception as error:
        report.update(passed=False, errorType=type(error).__name__, error=str(error))
    finally:
        if started:
            try:
                stop = subprocess.run([str(pg / 'pg_ctl.exe'), '-D', str(data), '-m', 'fast', '-w', '-t', '30', 'stop'],
                                      env=env, capture_output=True, text=True, timeout=40)
                report['stopExitCode'] = stop.returncode
            except subprocess.TimeoutExpired:
                report['stopExitCode'] = None
                report['stopError'] = 'isolated database stop timed out'
        with socket.socket() as connection:
            connection.settimeout(2)
            report['portClosed'] = connection.connect_ex(('127.0.0.1', port)) != 0
        report['completedAt'] = datetime.now(timezone.utc).isoformat()
        report['passed'] = (bool(report.get('passed')) and report.get('exitCode') == 0
                            and report.get('stopExitCode') == 0 and report['portClosed']
                            and report.get('remainingSchemas') == [])
        evidence = ROOT / 'evidence/M33/M33-T26'
        evidence.mkdir(parents=True, exist_ok=True)
        report['artifacts'] = {}
        for filename in ('tests-result.json', 'tests.log', 'setup.log', 'postgres.log'):
            origin = runtime / filename
            if origin.is_file():
                destination = evidence / (runtime.name + '-' + label + '-' + filename)
                shutil.copyfile(origin, destination)
                report['artifacts'][filename] = str(destination.relative_to(ROOT))
        target = evidence / (runtime.name + '-' + label + '.json')
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k != 'sourceHashes'}, ensure_ascii=False), flush=True)
        print('EVIDENCE=' + str(target), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', default='test_*.py')
    parser.add_argument('--label', default='regression')
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    raise SystemExit(child(args.pattern) if args.child else run(args.pattern, args.label))
