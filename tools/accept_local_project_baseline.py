"""Partial T18: native PostgreSQL, unmodified full app and real built browser UI.

Uses only new synthetic data. Never reads .env, online DB or existing model data.
This is NOT Android/media/model/object-store or deployment acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def isolated_environment():
    keys = ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC',
            'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'PROGRAMFILES', 'PROGRAMFILES(X86)')
    return {key: value for key, value in os.environ.items() if key.upper() in keys}


def require(response, status):
    if response.status_code != status:
        raise RuntimeError(f'HTTP {response.request.method} {response.request.url.path}: '
                           f'expected {status}, got {response.status_code}')
    return response.json() if response.content else None


def wait_ready(process, base):
    deadline = time.monotonic() + 45
    with httpx.Client(base_url=base, trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('isolated service exited before readiness')
            try:
                health = require(client.get('/healthz'), 200)
                if health['database']['backend'] == 'postgresql' and health['database']['schema'] == 'ready':
                    return
            except (httpx.HTTPError, RuntimeError):
                pass
            time.sleep(0.2)
    raise RuntimeError('isolated service readiness timed out')


def probe(client):
    password = 'local-acceptance-only-password'
    setup = require(client.post('/aiyoloapi/auth/setup', json={
        'username': 'local-admin', 'password': password}), 200)
    admin = {'Authorization': 'Bearer ' + setup['accessToken']}
    client.cookies.clear()
    projects, users, memberships = [], [], []
    for suffix in ('a', 'b'):
        accounts = []
        for role in ('owner', 'user'):
            accounts.append(require(client.post('/aiyoloapi/platform/accounts', headers=admin, json={
                'username': f'local-{role}-{suffix}', 'password': password, 'platformRole': 'NORMAL_USER'}), 201))
        project = require(client.post('/aiyoloapi/platform/projects', headers=admin, json={
            'projectCode': f'local-site-{suffix}', 'displayName': f'本地验收项目 {suffix.upper()}',
            'ownerAccountId': accounts[0]['accountId']}), 201)
        base = '/aiyoloapi/projects/' + project['projectId']
        membership = require(client.post(base + '/members', headers=admin, json={
            'accountId': accounts[1]['accountId'], 'projectRole': 'PROJECT_USER'}), 201)
        session = require(client.post('/aiyoloapi/auth/login', json={
            'username': accounts[1]['username'], 'password': password}), 200)
        client.cookies.clear()
        users.append({'Authorization': 'Bearer ' + session['accessToken']})
        memberships.append((accounts[1]['accountId'], membership['revision']))
        projects.append(project)
    for index, user in enumerate(users):
        mine, other = projects[index]['projectId'], projects[1-index]['projectId']
        me = require(client.get('/aiyoloapi/auth/me', headers=user), 200)
        if not me['accountId'] or me['contractVersion'] != 'm33-v1' or me['platformRole'] != 'NORMAL_USER':
            raise RuntimeError('identity contract mismatch')
        visible = require(client.get('/aiyoloapi/auth/projects', headers=user), 200)['projects']
        if [p['projectId'] for p in visible] != [mine]:
            raise RuntimeError('project directory leaked another project')
        base = '/aiyoloapi/projects/' + mine
        require(client.get(base, headers=user), 200)
        require(client.get('/aiyoloapi/projects/' + other, headers=user), 404)
        require(client.get('/aiyoloapi/platform/accounts', headers=user), 403)
        for path in ('streams', 'alerts', 'models', 'rules', 'dashboard/stats'):
            require(client.get(base + '/' + path, headers=user), 200)
            require(client.get('/aiyoloapi/projects/' + other + '/' + path, headers=user), 404)
        require(client.post(base + '/members', headers=user, json={
            'accountId': memberships[1-index][0], 'projectRole': 'PROJECT_USER'}), 403)
        require(client.post(base + '/streams', headers=user, json={'stream_id': 'forbidden'}), 403)
    return admin, projects, users, memberships


def run(pg_bin: Path, chrome: Path):
    for name in ('initdb.exe', 'pg_ctl.exe'):
        if not (pg_bin / name).is_file():
            raise ValueError('native PostgreSQL binary missing: ' + name)
    if not (ROOT / 'admin-web/dist/index.html').is_file():
        raise ValueError('build admin-web before running local acceptance')
    if not chrome.is_file():
        raise ValueError('browser executable is missing')
    parent = (ROOT / '.test-db').resolve()
    parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='m33-t18-', dir=parent)).resolve()
    data, runtime = work / 'cluster', work / 'service'
    env = isolated_environment()
    pg_started, server, log = False, None, None
    report = {'scope': 'partial local identity/project baseline; NOT joint acceptance',
              'database': 'native PostgreSQL', 'containerRequired': False,
              'liveDatabaseAccessed': False, 'checks': {}}

    def pg(name, *args):
        subprocess.run([str(pg_bin / (name + '.exe')), *args], check=True,
                       env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=60)

    def stop_server():
        nonlocal server
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        server = None

    try:
        runtime.mkdir()
        shutil.copytree(ROOT / 'app', runtime / 'app', ignore=shutil.ignore_patterns('__pycache__', 'static'))
        shutil.copytree(ROOT / 'alembic', runtime / 'alembic', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / 'alembic.ini', runtime / 'alembic.ini')
        shutil.copytree(ROOT / 'admin-web/dist', runtime / 'admin-web/dist')
        (runtime / 'models').mkdir()
        (runtime / 'models/registry.json').write_text(json.dumps({'models': [], 'activeModelId': None}), encoding='utf-8')
        pg('initdb', '-D', str(data), '-U', 'local_acceptance', '-E', 'UTF8', '--no-locale',
           '--auth-local=trust', '--auth-host=trust', '--no-instructions')
        pg_port, port = free_port(), free_port()
        while port == pg_port:
            port = free_port()
        pg_started = True
        pg('pg_ctl', '-D', str(data), '-l', str(work / 'postgres.log'),
           '-o', f'-h 127.0.0.1 -p {pg_port}', '-w', '-t', '45', 'start')
        env.update(DATABASE_URL=f'postgresql+psycopg://local_acceptance@127.0.0.1:{pg_port}/postgres',
                   DEPLOYMENT_ENV='production', PYTHONIOENCODING='utf-8')
        log = (work / 'service.log').open('w', encoding='utf-8')
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=runtime, env=env,
                       check=True, stdout=log, stderr=log, timeout=60)
        base = f'http://127.0.0.1:{port}'

        def start_server():
            return subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                '--host', '127.0.0.1', '--port', str(port), '--no-access-log', '--log-level', 'warning'],
                cwd=runtime, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

        server = start_server()
        wait_ready(server, base)
        with httpx.Client(base_url=base, trust_env=False, timeout=20) as client:
            admin, projects, users, memberships = probe(client)
            report['checks']['realHttpIdentityAndTwoProjectIsolation'] = True
            browser = subprocess.run(['node', str(ROOT / 'tools/local_project_browser.mjs')],
                cwd=ROOT / 'admin-web', env={**env, 'LOCAL_ACCEPTANCE_URL': base,
                    'LOCAL_ACCEPTANCE_CHROME': str(chrome)},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', timeout=120)
            if browser.returncode:
                raise RuntimeError('real browser baseline failed: ' + browser.stderr[-1800:])
            report['checks']['browser'] = json.loads(browser.stdout)
            stop_server()
            pg('pg_ctl', '-D', str(data), '-m', 'fast', '-w', '-t', '45', 'stop')
            pg('pg_ctl', '-D', str(data), '-l', str(work / 'postgres.log'),
               '-o', f'-h 127.0.0.1 -p {pg_port}', '-w', '-t', '45', 'start')
            server = start_server()
            wait_ready(server, base)
            for project, user in zip(projects, users):
                require(client.get('/aiyoloapi/projects/' + project['projectId'], headers=user), 200)
            report['checks']['sessionsSurviveServiceAndDatabaseRestart'] = True
            base_a = '/aiyoloapi/projects/' + projects[0]['projectId']
            account_id, revision = memberships[0]
            require(client.delete(base_a + '/members/' + account_id, headers=admin,
                                  params={'expectedRevision': revision}), 204)
            require(client.get(base_a, headers=users[0]), 404)
            if require(client.get('/aiyoloapi/auth/projects', headers=users[0]), 200)['projects']:
                raise RuntimeError('revoked membership retained project access')
            base_b = '/aiyoloapi/projects/' + projects[1]['projectId']
            require(client.post(base_b + '/archive', headers=admin,
                                json={'expectedRevision': projects[1]['revision']}), 200)
            require(client.post(base_b + '/streams', headers=admin, json={'stream_id': 'archived-write'}), 403)
            report['checks']['immediateRevocationAndArchiveWriteDenial'] = True
        report['result'] = 'passed-partial'
    except Exception as error:
        report.update(result='failed', errorType=type(error).__name__, error=str(error))
        report['diagnosticDirectory'] = str(work)
    finally:
        stop_server()
        if log:
            log.close()
        if pg_started:
            status = subprocess.run([str(pg_bin / 'pg_ctl.exe'), '-D', str(data), 'status'],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if status.returncode == 0:
                pg('pg_ctl', '-D', str(data), '-m', 'fast', '-w', '-t', '45', 'stop')
            elif (data / 'postmaster.pid').exists():
                raise RuntimeError('temporary cluster state uncertain; retained ' + str(work))
        report['temporaryProcessesStopped'] = True
        if report.get('result') == 'passed-partial' and work.parent == parent and work.name.startswith('m33-t18-'):
            shutil.rmtree(work)
            report['temporaryDataRemoved'] = True
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin', type=Path, required=True)
    parser.add_argument('--chrome', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.postgres_bin.resolve(), args.chrome.resolve())
    (ROOT / 'evidence/M33/M33-T18-local-baseline.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['result'] == 'passed-partial' else 1)
