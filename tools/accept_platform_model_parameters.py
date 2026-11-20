"""Run model parameter contracts against an owned disposable PostgreSQL cluster."""
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, text
from test_report_retention import atomic_markdown, check_owned_runtime, summarize_log, version_context

ROOT = Path(__file__).resolve().parents[1]
PG = Path(r'D:\PostgreSQL\bin')
REPORT = ROOT / 'harness/acceptance/M36-model-capabilities-scenes.md'


def main():
    runtime = Path(tempfile.mkdtemp(prefix='platform-parameters-pg-', dir=ROOT / '.tmp')).resolve()
    data = runtime / 'pg-data'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'postgresql+psycopg://aiyolo_app@127.0.0.1:{port}/postgres'
    env = {**os.environ, 'DATABASE_URL': url, 'RUN_POSTGRES_TESTS': '1'}
    context = version_context(ROOT)
    started = False
    stopped = False
    passed = False
    summary = {}
    error = None
    schemas = None
    modules = [
        'test_platform_model_parameters', 'test_project_model_assignment_storage',
        'test_scene_execution_parameters.SceneParameterPostgresTests',
        'test_scene_snapshot_approval.SceneSnapshotApprovalPostgresTests',
        'test_model_update_projection.UpdateProjectionPostgreSqlTests',
    ]
    try:
        with (runtime / 'postgres.log').open('w', encoding='utf-8') as log:
            subprocess.run([str(PG / 'initdb.exe'), '-D', str(data), '-U', 'aiyolo_app',
                '--auth-local=trust', '--auth-host=trust', '--encoding=UTF8', '--locale=C'],
                check=True, stdout=log, stderr=log)
            subprocess.run([str(PG / 'pg_ctl.exe'), '-D', str(data), '-l', str(runtime / 'server.log'),
                '-o', f'-h 127.0.0.1 -p {port}', '-w', 'start'], check=True, stdout=log, stderr=log)
        started = True
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                assert Path(connection.execute(text('SHOW data_directory')).scalar_one()).resolve() == data
                assert connection.execute(text('SELECT current_user')).scalar_one() == 'aiyolo_app'
        finally:
            engine.dispose()
        print(f'Verified isolated PostgreSQL: aiyolo_app@127.0.0.1:{port}/postgres; {data}', flush=True)
        program = ('import sys,logging,unittest; logging.disable(logging.CRITICAL); sys.path.insert(0,"tests"); '
                   f'suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(m) for m in {modules!r}); '
                   'r=unittest.TextTestRunner(verbosity=2).run(suite); sys.exit(not r.wasSuccessful())')
        with (runtime / 'tests.log').open('w', encoding='utf-8') as log:
            run = subprocess.run([sys.executable, '-c', program], cwd=ROOT, env=env, stdout=log, stderr=log)
        summary = summarize_log(runtime / 'tests.log')
        print(summary, flush=True)
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                schemas = connection.execute(text("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname NOT IN ('public','information_schema')")).scalars().all()
        finally:
            engine.dispose()
        passed = run.returncode == 0 and bool(summary['ran']) and not schemas
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        print(error, flush=True)
    finally:
        if started:
            stop = subprocess.run([str(PG / 'pg_ctl.exe'), '-D', str(data), '-m', 'fast', '-w', 'stop'], capture_output=True)
            stopped = stop.returncode == 0
        else:
            stopped = not (data / 'postmaster.pid').exists()
        with socket.socket() as sock:
            sock.settimeout(2)
            closed = sock.connect_ex(('127.0.0.1', port)) != 0
        passed = passed and stopped and closed
        lines = ['', f'### M36-T32 隔离PG运行 {runtime.name}', '',
            f'- 时间：{datetime.now(timezone.utc).isoformat()}；版本：{context}',
            '- 命令：`.venv/Scripts/python.exe tools/accept_platform_model_parameters.py`。仅临时PG实例，无业务数据库连接。',
            f'- 范围：{modules}', f'- 结果：passed={passed}；汇总：{summary}',
            f'- 资源：{data}；端口={port}；停止={stopped}；端口关闭={closed}；剩余schema={schemas}；异常={error}',
            '- 未验证：真实模型推理、Android设备及生产迁移。', '']
        content = REPORT.read_text(encoding='utf-8') + '\n'.join(lines)
        atomic_markdown(REPORT, content)
        if stopped and closed:
            try:
                owned = check_owned_runtime(ROOT, runtime, 'platform-parameters-pg-')
                shutil.rmtree(owned)
                cleanup = '本次临时PG数据与诊断日志已清理；MD保留失败事实及最终结果。'
            except (ValueError, OSError) as exc:
                cleanup = f'清理未完成：{exc}'
                passed = False
        else:
            cleanup = '进程状态未确认，不清理临时材料。'
        atomic_markdown(REPORT, content + '\n- ' + cleanup + '\n')
        print(f'passed={passed}; {cleanup}; report={REPORT}', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
