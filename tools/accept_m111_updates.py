"""M111-T02 isolated regressions; never connects tests to the application DB."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
PG = Path(r"D:\PostgreSQL\bin")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--postgres', action='store_true')
    parser.add_argument('--pattern', action='append')
    args = parser.parse_args()
    (ROOT / '.tmp').mkdir(exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix='m111-updates-', dir=ROOT / '.tmp')).resolve()
    env = os.environ.copy()
    env.update(DATABASE_URL='', RUN_POSTGRES_TESTS='0', PYTHONUTF8='1')
    result = {'startedAt': datetime.now(timezone.utc).isoformat(), 'runtime': str(runtime),
              'isolatedPostgresql': args.postgres, 'tests': []}
    started, port, data = False, None, runtime / 'pg-data'
    try:
        if args.postgres:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            url = f'postgresql+psycopg://aiyolo_app@127.0.0.1:{port}/postgres'
            assert data.parent == runtime and runtime.parent == (ROOT / '.tmp').resolve()
            with (runtime / 'runner.log').open('w', encoding='utf-8') as log:
                subprocess.run([str(PG/'initdb.exe'), '-D', str(data), '-U', 'aiyolo_app',
                    '--auth-local=trust', '--auth-host=trust', '--encoding=UTF8', '--locale=C'],
                    check=True, stdout=log, stderr=log)
                subprocess.run([str(PG/'pg_ctl.exe'), '-D', str(data), '-l', str(runtime/'postgres.log'),
                    '-o', f'-h 127.0.0.1 -p {port}', '-w', 'start'], check=True, stdout=log, stderr=log)
            started = True
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    assert Path(connection.execute(text('SHOW data_directory')).scalar_one()).resolve() == data
                    assert connection.execute(text('SELECT current_user')).scalar_one() == 'aiyolo_app'
            finally:
                engine.dispose()
            env.update(DATABASE_URL=url, RUN_POSTGRES_TESTS='1')
            result.update(host='127.0.0.1', port=port, dataDirectory=str(data))
        patterns = args.pattern or ['test_model_updates.py', 'test_model_update_concurrency.py', 'test_model_update_auth.py',
            'test_model_update_delivery.py', 'test_model_update_migration.py', 'test_model_update_projection.py',
            'test_model_update_api.py', 'test_model_download.py', 'test_resource_lifecycle.py',
            'test_assignment_targets.py', 'test_project_scenes.py', 'test_project_scene_installation.py',
            'test_database.py', 'test_metrics_api.py']
        for pattern in patterns:
            target = runtime / (pattern + '.log')
            with target.open('w', encoding='utf-8') as output:
                test = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
                    '-p', pattern, '-v'], cwd=ROOT, env=env, stdout=output, stderr=output)
            result['tests'].append({'pattern': pattern, 'exitCode': test.returncode, 'log': str(target)})
            print(f'{pattern}: exit {test.returncode}; {target}', flush=True)
        if args.postgres:
            engine = create_engine(url)
            try:
                with engine.connect() as connection:
                    schemas = connection.execute(text("SELECT nspname FROM pg_namespace WHERE "
                        "nspname NOT LIKE 'pg_%' AND nspname NOT IN ('public','information_schema')")).scalars().all()
                    result['remainingTestSchemas'] = schemas
                    assert not schemas, 'isolated schema cleanup failed'
            finally:
                engine.dispose()
        result['testsCompleted'] = True
    finally:
        if started:
            subprocess.run([str(PG/'pg_ctl.exe'), '-D', str(data), '-m', 'fast', '-w', 'stop'], check=True)
        if port:
            with socket.socket() as sock:
                sock.settimeout(2); result['portClosed'] = sock.connect_ex(('127.0.0.1', port)) != 0
        result['completedAt'] = datetime.now(timezone.utc).isoformat()
        result['passed'] = bool(result.get('testsCompleted') and result['tests']
            and all(row['exitCode'] == 0 for row in result['tests']) and result.get('portClosed', True))
        evidence = ROOT/'harness/evidence/M111/T02'
        evidence.mkdir(parents=True, exist_ok=True)
        archive = evidence/'runs'/runtime.name
        archive.mkdir(parents=True, exist_ok=True)
        for row in result['tests']:
            original = Path(row['log'])
            if original.exists():
                saved = archive/original.name
                shutil.copy2(original, saved)
                row['archivedLog'] = str(saved.relative_to(ROOT))
        result['archivedResult'] = str((archive/'result.json').relative_to(ROOT))
        name = 'postgres-result.json' if args.postgres else 'backend-result.json'
        (evidence/name).write_text(json.dumps(result, indent=2), encoding='utf-8')
        (archive/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        (runtime/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
