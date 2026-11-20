"""M34-T06 partial real media acceptance; never a production/joint sign-off.

Uses copied real model artifacts, decoded local video, an owned PostgreSQL cluster,
and the unmodified HTTP application. No mock detector, route or database.
"""
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
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'uploaded-c8dffd82f6a24deca8d03afdae24956f'
VIDEO = ROOT.parent / 'information/rtsp-test-videos/test.mp4'
PG = Path('D:/PostgreSQL/bin')
PASSWORD = 'm34-disposable-test-only-password'


def clean_environment():
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'LOCALAPPDATA',
               'APPDATA', 'USERPROFILE', 'PROGRAMFILES', 'PROGRAMFILES(X86)'}
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


def owned_work(path):
    resolved = path.resolve()
    if path.is_symlink() or resolved.parent != (ROOT / '.tmp').resolve() or not resolved.name.startswith('m34-real-'):
        raise ValueError('owned local runtime required')
    return resolved


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def port():
    with socket.socket() as handle:
        handle.bind(('127.0.0.1', 0))
        return handle.getsockname()[1]


def loopback_only(event, args):
    if event == 'socket.connect' and isinstance(args[1], tuple):
        if args[1][0] not in ('127.0.0.1', '::1', 'localhost'):
            raise RuntimeError('M34 acceptance forbids non-loopback socket connections')
    if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', '::1', 'localhost', None):
        raise RuntimeError('M34 acceptance forbids external DNS')


def require(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f'{response.request.method} {response.request.url.path}: '
                           f'expected {status}, got {response.status_code}: {response.text[:700]}')
    return response.json() if response.content else None


class Replay:
    """Real MP4 replay via the protected input, not a live RTSP camera."""
    def __init__(self, url, headers):
        self.url, self.headers = url, headers
        self.stop_event = threading.Event()
        self.frames = 0
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        import cv2
        from websockets.sync.client import connect
        capture = cv2.VideoCapture(str(VIDEO))
        try:
            if not capture.isOpened():
                raise RuntimeError('real video could not be decoded')
            with connect(self.url, additional_headers=self.headers, proxy=None,
                         open_timeout=10, close_timeout=3, max_size=1024**2) as connection:
                while not self.stop_event.is_set():
                    started = time.monotonic()
                    # Sample every fifth original frame, at five input frames/second.
                    for _ in range(5):
                        ok, frame = capture.read()
                        if not ok:
                            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ok, frame = capture.read()
                        if not ok:
                            raise RuntimeError('video replay failed')
                    frame = cv2.resize(frame, (1280, 720))
                    ok, encoded = cv2.imencode('.jpg', frame)
                    if not ok:
                        raise RuntimeError('real input JPEG encoding failed')
                    connection.send(encoded.tobytes())
                    connection.send('barrier')
                    if json.loads(connection.recv(timeout=10)) != {'ok': True}:
                        raise RuntimeError('input barrier failed')
                    self.frames += 1
                    self.stop_event.wait(max(0, .2 - (time.monotonic() - started)))
        except Exception as error:
            self.error = repr(error)
        finally:
            capture.release()

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()
        self.thread.join(15)
        if self.thread.is_alive() or self.error:
            raise RuntimeError(self.error or 'input replay did not stop')


def run(work):
    import httpx
    import psycopg
    import psutil
    from websockets.sync.client import connect
    from websockets.exceptions import ConnectionClosed, InvalidStatus

    sys.addaudithook(loopback_only)
    runtime, data = work / 'service', work / 'cluster'
    report = {
        'task': 'M34-T06', 'scope': 'partial real backend/PC acceptance; NOT Android or production acceptance',
        'startedAt': datetime.now(timezone.utc).isoformat(), 'runtime': str(work),
        'source': 'actual local MP4 decoded and paced through authenticated WebSocket input; NOT RTSP',
        'unverified': ['API27 device acceptance', 'physical RTSP source/reconnect',
                       'long-duration soak', 'production/object-store acceptance'],
        'checks': {}, 'liveDatabaseAccessed': False, 'productionChanged': False,
    }
    checks = report['checks']
    env = clean_environment()
    env.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    pg_port, http_port = port(), port()
    while pg_port == http_port:
        http_port = port()
    report['ports'] = {'postgres': pg_port, 'http': http_port}
    base = f'http://127.0.0.1:{http_port}'
    dbargs = dict(host='127.0.0.1', port=pg_port, dbname='postgres', user='m34_acceptance')
    server, replay, pg_started = None, None, False
    handles = []
    hashes = {}
    registry_hash = digest(ROOT / 'models/registry.json')
    report['runnerHashes'] = {name: digest(ROOT / 'tools' / name) for name in
                              ('accept_m34_local.py', 'm34_real_browser.mjs')}

    def pg(name, *args):
        with (work / 'postgres-commands.log').open('a', encoding='utf-8') as log:
            subprocess.run([str(PG / (name + '.exe')), *args], env=env, cwd=work,
                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=65, check=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def stop_server():
        nonlocal server
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        server = None

    def start_server():
        nonlocal server
        log = (work / 'service.log').open('a', encoding='utf-8')
        handles.append(log)
        server = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                                   '--serve', str(http_port)], cwd=runtime, env=env,
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        with httpx.Client(base_url=base, trust_env=False, timeout=2) as client:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError('isolated server exited before readiness; see service.log')
                try:
                    health = require(client.get('/healthz'))
                    if health['database']['schema'] == 'ready' and health['database']['backend'] == 'postgresql':
                        return
                except (httpx.HTTPError, RuntimeError):
                    pass
                time.sleep(.3)
        raise RuntimeError('isolated server readiness timed out')

    def sample_processes():
        process = psutil.Process(server.pid)
        children = [{'pid': p.pid, 'name': p.name()} for p in process.children(recursive=True)]
        peers = [{'status': c.status, 'local': list(c.laddr), 'remote': list(c.raddr)}
                 for c in process.net_connections(kind='inet')]
        if any(c['remote'] and c['remote'][0] not in ('127.0.0.1', '::1') for c in peers):
            raise RuntimeError('unexpected non-local server connection')
        if any(any(n in p['name'].lower() for n in ('ffmpeg', 'mediamtx', 'gst-launch')) for p in children):
            raise RuntimeError('unexpected publisher process')
        return {'pid': server.pid, 'children': children, 'sockets': peers}

    try:
        runtime.mkdir()
        for name in ('app', 'alembic', 'admin-web/dist'):
            shutil.copytree(ROOT / name, runtime / name, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / 'alembic.ini', runtime / 'alembic.ini')
        for path in (runtime / 'app').rglob('*.py'):
            hashes[str(path.relative_to(runtime))] = digest(path)
        registry = json.loads((ROOT / 'models/registry.json').read_text(encoding='utf-8'))
        model = next(m for m in registry['models'] if m['modelId'] == MODEL and m['version'] == '1.0.0')
        if model.get('status') != 'PUBLISHED' or not model.get('releaseEligible') or 'pc' not in model.get('publishedTargets', []):
            raise RuntimeError('existing model lacks local PC publication eligibility')
        for artifact in model['artifacts']:
            source = (ROOT / artifact['path']).resolve()
            if not source.is_relative_to(ROOT / 'models') or source.is_symlink():
                raise RuntimeError('unexpected artifact path')
            if digest(source).lower() != artifact['sha256'].lower() or source.stat().st_size != artifact['sizeBytes']:
                raise RuntimeError('model artifact hash/size mismatch')
            relative = source.relative_to(ROOT)
            destination = runtime / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            hashes[str(relative)] = digest(source)
        (runtime / 'models/registry.json').write_text(json.dumps({
            'models': [model], 'activeServerModel': MODEL + '@1.0.0'}), encoding='utf-8')
        report['videoSha256'] = digest(VIDEO)
        report['copiedSourceHashes'] = hashes
        env.update(DATABASE_URL=f'postgresql+psycopg://m34_acceptance@127.0.0.1:{pg_port}/postgres',
                   DEPLOYMENT_ENV='production', MINIO_ENDPOINT='', CONVERSION_AUTO_CONVERT='false',
                   APP_UPDATES_ENABLED='false', APP_APK_EXTERNAL_ENABLED='false', APP_APK_WORKER_ENABLED='false',
                   YOLO_MODEL_PATH=model['path'], YOLO_DEVICE='cpu', YOLO_OFFLINE='true',
                   YOLO_CONFIG_DIR=str(work / 'yolo-settings'), CALIBRATION_ROOT=str(runtime / 'calibration'))
        report['appUpdatesTestFixtureOnly'] = 'disabled only in disposable fixture; production stays unchanged/enabled'
        pg('initdb', '-D', str(data), '-U', 'm34_acceptance', '--auth-local=trust',
           '--auth-host=trust', '--encoding=UTF8', '--locale=C')
        pg_started = True
        pg('pg_ctl', '-D', str(data), '-l', str(work / 'postgres.log'), '-o',
           f'-h 127.0.0.1 -p {pg_port}', '-w', '-t', '45', 'start')
        with psycopg.connect(**dbargs) as connection:
            if Path(connection.execute('show data_directory').fetchone()[0]).resolve() != data:
                raise RuntimeError('owned PostgreSQL data directory mismatch')
            if connection.execute('select current_user').fetchone()[0] != 'm34_acceptance':
                raise RuntimeError('owned PostgreSQL identity mismatch')
        checks['isolatedPostgresIdentity'] = True
        with (work / 'migration.log').open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable, '-B', '-m', 'alembic', 'upgrade', 'head'],
                           cwd=runtime, env=env, stdout=log, stderr=log, timeout=90, check=True)
        start_server()
        print('M34_LOCAL_SERVER_READY', flush=True)
        with httpx.Client(base_url=base, trust_env=False, timeout=25) as client:
            setup = require(client.post('/aiyoloapi/auth/setup', json={'username': 'm34-admin', 'password': PASSWORD}))
            admin = {'Authorization': 'Bearer ' + setup['accessToken']}
            client.cookies.clear()
            projects, users = [], []
            for suffix in ('a', 'b'):
                account = require(client.post('/aiyoloapi/platform/accounts', headers=admin, json={
                    'username': 'm34-owner-' + suffix, 'password': PASSWORD, 'platformRole': 'NORMAL_USER'}), 201)
                project = require(client.post('/aiyoloapi/platform/projects', headers=admin, json={
                    'projectCode': 'm34-site-' + suffix, 'displayName': 'M34 real video ' + suffix,
                    'ownerAccountId': account['accountId']}), 201)
                session = require(client.post('/aiyoloapi/auth/login', json={'username': account['username'], 'password': PASSWORD}))
                client.cookies.clear()
                projects.append(project)
                users.append({'Authorization': 'Bearer ' + session['accessToken']})
            project_path = '/aiyoloapi/projects/' + projects[0]['projectId']
            member = require(client.post('/aiyoloapi/platform/accounts', headers=admin, json={
                'username': 'm34-viewer', 'password': PASSWORD, 'platformRole': 'NORMAL_USER'}), 201)
            membership = require(client.post(project_path + '/members', headers=admin, json={
                'accountId': member['accountId'], 'projectRole': 'PROJECT_USER'}), 201)
            profile_path = '/aiyoloapi/platform/models/' + MODEL + '/parameters'
            profile = require(client.get(profile_path, headers=admin, params={'platform': 'server', 'version': '1.0.0'}))
            for rule in profile['alertRules']:
                rule['enabled'] = rule['rawLabel'] == 'helmet'
                if rule['enabled']:
                    rule['camera'].update(minimumConfidence=.5, minimumConsecutiveFrames=3, minimumDwellTimeMs=400, cooldownMs=60000)
            profile = require(client.put(profile_path, headers=admin, params={'platform': 'server', 'version': '1.0.0'}, json={
                'schemaVersion': 2, 'expectedRevision': profile['revision'],
                'detection': profile['detection'], 'alertRules': profile['alertRules']}))
            report['testRule'] = 'isolated helmet PRESENCE positive control; NOT a safety violation policy'
            assigned = require(client.put(project_path + '/model-assignments', headers=admin, json={
                # Fresh project has no override: revision 0 inherits the saved platform profile.
                'modelId': MODEL, 'modelVersion': '1.0.0', 'target': 'pc', 'parameterRevision': 0,
                'enabled': True, 'expectedRevision': 0}))
            scene = require(client.post(project_path + '/scenes', headers=admin, json={
                'sceneId': 'real-video', 'name': 'M34 isolated real inference', 'inputTypes': ['video'],
                'expectedRevision': 0, 'models': [{'projectModelId': assigned['projectModelId'], 'position': 0, 'execution': 'single'}]}), 201)
            approved = require(client.post(project_path + '/scenes/real-video/approval', headers=admin, json={
                'approved': True, 'expectedRevision': scene['revision'], 'reason': 'Local isolated positive-control acceptance only'}))
            stream_path = project_path + '/streams/real-input'
            require(client.post(project_path + '/streams', headers=admin, json={
                'stream_id': 'real-input', 'display_name': 'M34 decoded local video', 'source_type': 'websocket',
                'sceneId': 'real-video', 'planId': 'default', 'sceneRevision': approved['revision']}), 201)
            require(client.post(stream_path + '/yolo', headers=admin, json={'enabled': True}))
            wsbase = base.replace('http:', 'ws:')
            with connect(wsbase + project_path + '/alerts/ws', additional_headers=users[0], proxy=None) as management, \
                 connect(wsbase + project_path + '/alerts/notifications', additional_headers=users[0], proxy=None) as notifications:
                replay = Replay(wsbase + stream_path + '/ingest', users[0]).start()
                message = json.loads(management.recv(timeout=40))
                notification = json.loads(notifications.recv(timeout=15))
                event = message['event']
                if message['type'] != 'alert' or notification['event']['eventId'] != event['eventId']:
                    raise RuntimeError('formal event/notification identity mismatch')
                report['eventId'] = event['eventId']
                checks['noPreviewRealInferenceAlertAndTwoNotificationChannels'] = True
            event_path = project_path + '/alerts/' + event['eventId']
            saved = require(client.get(event_path, headers=users[0]))
            evidence = client.get(event_path + '/evidence', headers=users[0])
            if evidence.status_code != 200 or not evidence.content.startswith(b'\xff\xd8'):
                raise RuntimeError('durable JPEG evidence unavailable')
            (work / 'alert-evidence.jpg').write_bytes(evidence.content)
            report['evidenceSha256'] = hashlib.sha256(evidence.content).hexdigest()
            with psycopg.connect(**dbargs) as connection:
                row = connection.execute('select source_id, disposition_status from alert_events where project_id=%s and event_id=%s',
                                         (projects[0]['projectId'], event['eventId'])).fetchone()
                if row != ('real-input', 'OPEN'):
                    raise RuntimeError('actual PostgreSQL alert row mismatch')
            checks['postgresEventAndLocalEvidence'] = True
            require(client.get(event_path, headers=users[1]), 404)
            require(client.get(event_path + '/evidence', headers=users[1]), 404)
            require(client.get(stream_path + '/preview', headers=users[0]), 403)
            checks['crossProjectAlertEvidenceAndBearerPreviewDenied'] = True
            require(client.post('/aiyoloapi/auth/login', json={'username': 'm34-viewer', 'password': PASSWORD}))

            def preview(mode):
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    response = client.get(stream_path + '/preview')
                    if response.status_code == 200 and response.headers.get('x-preview-mode') == mode:
                        if not response.content.startswith(b'\xff\xd8'):
                            raise RuntimeError('invalid PC preview JPEG')
                        (work / ('preview-' + mode + '.jpg')).write_bytes(response.content)
                        return
                    time.sleep(.15)
                raise RuntimeError('PC preview mode unavailable: ' + mode)

            preview('yolo')
            require(client.post(stream_path + '/yolo', headers=admin, json={'enabled': False}))
            preview('raw')
            require(client.post(stream_path + '/yolo', headers=admin, json={'enabled': True}))
            preview('yolo')
            checks['sameOriginCookieRawAndYoloPreview'] = True
            for route in ('mjpeg', 'playback'):
                require(client.get(stream_path + '/' + route), 410)
            checks['retiredHttpRoutes'] = True
            for route in ('ws', 'detections'):
                try:
                    with connect(wsbase + stream_path + '/' + route, additional_headers=users[0],
                                 proxy=None, open_timeout=5):
                        raise RuntimeError('retired stream socket accepted')
                except InvalidStatus as error:
                    if error.response.status_code != 403:
                        raise
            checks['retiredWebSocketHandshakesDenied'] = True
            print('M34_REAL_ALERT_EVIDENCE_PREVIEW_PASS', flush=True)
            report['processSamples'] = [sample_processes()]
            replay.stop()
            report['firstReplayFrames'] = replay.frames
            replay = None
            time.sleep(3.3)
            require(client.get(stream_path + '/preview'), 204)
            replay = Replay(wsbase + stream_path + '/ingest', users[0]).start()
            preview('yolo')
            checks['inputDisconnectClearsPreviewAndReconnectRecovers'] = True
            disposed = require(client.post(event_path + '/acknowledge', headers=users[0], json={
                'note': 'M34 real inference isolated acceptance', 'expectedRevision': saved.get('dispositionRevision', 0)}))
            if disposed['disposition']['status'] != 'ACKNOWLEDGED':
                raise RuntimeError('human disposition failed')
            checks['realHumanDisposition'] = True
            browser_env = {**env, 'M34_BASE_URL': base, 'M34_PROJECT': projects[0]['projectId'],
                           'M34_EVIDENCE': str(work), 'M34_PASSWORD': PASSWORD}
            with (work / 'browser.log').open('w', encoding='utf-8') as browser_log:
                subprocess.run(['node', str(ROOT / 'tools/m34_real_browser.mjs')], cwd=ROOT,
                               env=browser_env, stdout=browser_log, stderr=browser_log,
                               timeout=90, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            checks['realBuiltBrowserPreviewAndPageExit'] = True
            # Bounded continuous run. A minute is evidence, not a long-soak claim.
            started = time.monotonic()
            metrics = []
            while time.monotonic() - started < 60:
                values = require(client.get(project_path + '/streams', headers=admin))[0]
                if values.get('last_error') or values.get('alert_error') or values['frames_fallback']:
                    raise RuntimeError('real stream reports runtime failure: ' + json.dumps(values))
                metrics.append({k: values[k] for k in ('frames_received', 'frames_processed', 'detections_last', 'publish_state', 'frames_published')})
                if replay.error:
                    raise RuntimeError(replay.error)
                time.sleep(5)
            if metrics[-1]['frames_processed'] <= metrics[0]['frames_processed'] + 100:
                raise RuntimeError('insufficient real inference progress during bounded run')
            report['boundedContinuous'] = {'seconds': round(time.monotonic() - started, 2), 'metrics': metrics}
            report['processSamples'].append(sample_processes())
            checks['boundedRealInferenceWithoutPreview'] = True
            replay.stop()
            replay = None
            before_restart = require(client.get(project_path + '/alerts', headers=users[0]))['events']
            before_ids = {item['eventId'] for item in before_restart}
            stop_server()
            pg('pg_ctl', '-D', str(data), '-m', 'fast', '-w', '-t', '45', 'stop')
            pg('pg_ctl', '-D', str(data), '-l', str(work / 'postgres.log'), '-o',
               f'-h 127.0.0.1 -p {pg_port}', '-w', '-t', '45', 'start')
            start_server()
            restored = require(client.get(event_path, headers=users[0]))
            if restored['disposition']['status'] != 'ACKNOWLEDGED':
                raise RuntimeError('disposition lost on restart')
            response = client.get(event_path + '/evidence', headers=users[0])
            if response.status_code != 200 or hashlib.sha256(response.content).hexdigest() != report['evidenceSha256']:
                raise RuntimeError('evidence lost on restart')
            replay = Replay(wsbase + stream_path + '/ingest', users[0]).start()
            preview('yolo')
            time.sleep(2)
            after_restart = require(client.get(project_path + '/alerts', headers=users[0]))['events']
            if {item['eventId'] for item in after_restart} != before_ids:
                raise RuntimeError('restart duplicated or lost sustained real alert events')
            report['alertsBeforeAndAfterRestart'] = len(before_ids)
            checks['restartNoDuplicateSustainedAlerts'] = True
            checks['serviceDatabaseRestartPreservesSessionAlertEvidenceAndInput'] = True
            cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
            with connect(wsbase + project_path + '/alerts/notifications',
                         additional_headers={'Cookie': cookie}, proxy=None) as revoked_socket:
                require(client.delete(project_path + '/members/' + member['accountId'], headers=admin,
                                      params={'expectedRevision': membership['revision']}), 204)
                try:
                    revoked_socket.recv(timeout=5)
                    raise RuntimeError('revoked notification socket stayed usable')
                except ConnectionClosed as error:
                    if error.rcvd is None or error.rcvd.code not in (4403, 4404):
                        raise
            checks['idleNotificationRevocation'] = True
            require(client.get(stream_path + '/preview'), 404)
            require(client.get(event_path), 404)
            checks['cookieMemberRevocationImmediate'] = True
            report['finalStream'] = require(client.get(project_path + '/streams', headers=admin))[0]
        report['result'] = 'passed-partial'
    except Exception as error:
        report.update(result='failed', errorType=type(error).__name__, error=str(error))
        try:
            (work / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        except OSError:
            report['failureLogWriteBlocked'] = True
    finally:
        cleanup_errors = []
        if replay:
            try:
                replay.stop()
            except Exception as error:
                cleanup_errors.append(str(error))
        stop_server()
        for handle in handles:
            handle.close()
        if pg_started:
            try:
                pg('pg_ctl', '-D', str(data), '-m', 'fast', '-w', '-t', '45', 'stop')
            except Exception as error:
                cleanup_errors.append(str(error))
        for label, number in report['ports'].items():
            with socket.socket() as connection:
                connection.settimeout(2)
                checks[label + 'PortClosed'] = connection.connect_ex(('127.0.0.1', number)) != 0
        checks['originalModelRegistryUnchanged'] = digest(ROOT / 'models/registry.json') == registry_hash
        checks['copiedOriginalFilesUnchanged'] = all(digest(ROOT / name) == value for name, value in hashes.items())
        report['cleanupErrors'] = cleanup_errors
        if cleanup_errors or not all(checks.values()):
            report['result'] = 'failed'
        report['completedAt'] = datetime.now(timezone.utc).isoformat()
        evidence = ROOT / 'evidence/M34/M34-T06'
        evidence.mkdir(parents=True, exist_ok=True)
        artifact_root = evidence / work.name
        artifact_root.mkdir(exist_ok=True)
        report['artifacts'] = {}
        for name in ('alert-evidence.jpg', 'preview-yolo.jpg', 'preview-raw.jpg', 'pc-yolo-preview.png',
                     'pc-raw-preview.png', 'pc-failure.png', 'pc-browser.json', 'browser.log',
                     'failure.log', 'migration.log', 'postgres.log'):
            original = work / name
            if original.is_file():
                target = artifact_root / name
                shutil.copy2(original, target)
                report['artifacts'][name] = {'path': str(target.relative_to(ROOT)), 'sha256': digest(target)}
        destination = evidence / (work.name + '.json')
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'result': report['result'], 'checks': checks, 'error': report.get('error'),
                          'report': str(destination), 'retainedRuntime': str(work)}, ensure_ascii=False), flush=True)
    return 0 if report['result'] == 'passed-partial' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--serve', type=int)
    args = parser.parse_args()
    if args.serve:
        runtime = Path.cwd().resolve()
        owned_work(runtime.parent)
        if runtime.name != 'service' or (runtime / '.env').exists():
            raise ValueError('server may only run from an owned environment-free service copy')
        sys.addaudithook(loopback_only)
        sys.path.insert(0, str(Path.cwd()))
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=args.serve, access_log=False, log_level='warning')
        return 0
    if args.worker:
        work = owned_work(args.worker)
        return run(work)
    parent = ROOT / '.tmp'
    parent.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='m34-real-', dir=parent)).resolve()
    env = clean_environment()
    env.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    print('M34_OWNED_RUNTIME=' + str(work), flush=True)
    return subprocess.call([sys.executable, '-B', str(Path(__file__).resolve()), '--worker', str(work)], cwd=work, env=env)


if __name__ == '__main__':
    raise SystemExit(main())
