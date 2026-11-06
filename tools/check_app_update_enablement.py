"""Bounded checks for current local upgrade enablement; never publishes a release."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from sqlalchemy import text
from app.config import Settings
from app.database import DatabaseManager
from app.app_updates.api import configured_updates
from app.app_updates.external_api import configured_external

REPORT_ROOT = ROOT / 'evidence/M42/M42-T13'
BASE = 'http://127.0.0.1:8080'

def snapshot(db):
    protected = ['accounts', 'projects', 'project_memberships', 'project_model_assignments',
        'project_scenes', 'project_scene_members']
    upgrades = ['app_update_identities', 'app_artifacts', 'app_artifact_sources', 'app_releases',
        'app_update_policies', 'app_update_policy_revisions', 'app_rollback_operations',
        'app_update_device_states', 'app_update_receipts', 'app_update_audit_events', 'app_apk_uploads']
    result = {}
    with db.engine.connect() as c:
        with c.begin():
            c.execute(text('SET TRANSACTION READ ONLY'))
            for table in protected + upgrades:
                rows = c.execute(text(f'SELECT to_jsonb(t)::text FROM public.{table} t ORDER BY 1')).scalars()
                digest, count = hashlib.sha256(), 0
                for row in rows:
                    digest.update(row.encode()); digest.update(b'\n'); count += 1
                result[table] = {'count': count, 'sha256': digest.hexdigest()}
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['preflight', 'live'])
    p.add_argument('--base-url', choices=[BASE, 'http://127.0.0.1:5173'], default=BASE)
    args = p.parse_args()
    s = Settings()
    if s.deployment_env != 'development':
        raise RuntimeError('Expected existing development environment')
    db = DatabaseManager(s.database_url, connect_timeout_seconds=5)
    try:
        db.verify_schema()
        candidate = s.model_copy(update={'app_updates_enabled': True, 'app_apk_external_enabled': True,
            'app_apk_worker_enabled': False, 'app_apk_compatibility_path': str(ROOT.parent / 'config/app-updates/compatibility-http-trial.json')})
        service = configured_updates(db, candidate)
        worker = configured_external(db, candidate)
        if (worker.compatibility.server_contract_min, worker.compatibility.server_contract_max,
            worker.compatibility.data_schema_version, worker.compatibility.readable_schema_min,
            worker.compatibility.readable_schema_max) != (1, 1, 20, 20, 20):
            raise RuntimeError('Unexpected compatibility declaration')
        trust = json.loads((ROOT.parent / 'config/app-updates/app-trust-http-test.json').read_text(encoding='utf-8'))['services'][0]
        public = base64.urlsafe_b64encode(service.publisher.key.public_key().public_bytes_raw()).decode().rstrip('=')
        if trust['metadataKeys'].get(service.publisher.key_id) != public:
            raise RuntimeError('Metadata key mismatch with packaged trust')
        envelope = service.publisher.sign({'purpose': 'local-configuration-self-check', 'notAnInstallAuthorization': True})
        from app.app_updates.contract import SIGNATURE_DOMAIN
        decode = lambda v: base64.urlsafe_b64decode(v + '=' * (-len(v) % 4))
        service.publisher.key.public_key().verify(decode(envelope['signatureBase64Url']), SIGNATURE_DOMAIN + decode(envelope['payloadBase64Url']))
        result = {'mode': args.mode, 'baseUrl': args.base_url, 'at': datetime.now(timezone.utc).isoformat(), 'factoriesReady': True, 'publicKeyMatchesApkTrust': True}
        if args.mode == 'preflight':
            manifest = json.loads((ROOT.parent / 'releases/20261106-http-upgrade-test-M164/package-manifest.json').read_text(encoding='utf-8'))
            checked = []
            for item in manifest['artifacts']:
                apk = Path(item['path'])
                with apk.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != item['sha256'] or apk.stat().st_size != item['size_bytes']:
                    raise RuntimeError('Candidate bytes changed')
                signed = subprocess.run([s.app_apk_java_path, '-jar', s.app_apk_apksigner_jar_path, 'verify', '--verbose', '--print-certs', str(apk)], capture_output=True, text=True, timeout=45)
                if signed.returncode or 'Verified using v2 scheme (APK Signature Scheme v2): true' not in signed.stdout or item['signer_sha256'] not in signed.stdout:
                    raise RuntimeError('Candidate signature failed')
                checked.append({'versionCode': item['version_code'], 'sha256': digest})
            result['candidates'] = checked
            result['snapshot'] = snapshot(db)
            if result['snapshot']['app_apk_uploads']['count'] != 0:
                raise RuntimeError('Existing APK jobs require explicit review before enabling worker')
            health = httpx.get(BASE + '/healthz', timeout=10).json()
            if health.get('status') != 'ok' or health.get('streams') != 0:
                raise RuntimeError('Service must be healthy and idle before restart')
            result['health'] = health
        else:
            if not s.app_updates_enabled or not s.app_apk_external_enabled or s.app_apk_worker_enabled:
                raise RuntimeError('Enablement switches differ from approved scope')
            doc = (ROOT.parent / 'harness/TEST_ACCOUNTS.md').read_text(encoding='utf-8-sig')
            credential = re.search(r'\|\s*`admin`\s*\|\s*`([^`]+)`', doc)
            if not credential:
                raise RuntimeError('Documented local admin credential missing')
            with httpx.Client(base_url=args.base_url, timeout=15) as client:
                response = client.get('/aiyoloapi/admin/app-updates/configuration')
                if response.status_code != 401:
                    raise RuntimeError('Anonymous administrator access must remain denied')
                login = client.post('/aiyoloapi/auth/login', json={'username': 'admin', 'password': credential.group(1)})
                if login.status_code != 200:
                    raise RuntimeError('Admin authentication failed')
                client.headers['Authorization'] = 'Bearer ' + login.json()['accessToken']
                try:
                    response = client.get('/aiyoloapi/admin/app-updates/configuration')
                    if response.status_code != 200:
                        raise RuntimeError('Configuration API unavailable')
                    config = response.json()
                    if config['externalEnabled'] is not True or config['uploadEnabled'] is not False or not config['scopes']:
                        raise RuntimeError('Unexpected feature configuration')
                    result['configuration'] = config
                    for kind in ['artifacts', 'releases']:
                        response = client.get('/aiyoloapi/admin/app-updates/' + kind)
                        if response.status_code != 200:
                            raise RuntimeError('Admin list unavailable')
                        result[kind + 'ApiStatus'] = response.status_code
                    # Malformed JSON cannot create an artifact or consume a version slot.
                    response = client.post('/aiyoloapi/admin/app-updates/external-artifacts', json={})
                    if response.status_code != 422:
                        raise RuntimeError('Invalid registration must remain rejected')
                    result['invalidRegistrationRejected'] = True
                finally:
                    logout = client.post('/aiyoloapi/auth/logout')
                    if logout.status_code != 200:
                        raise RuntimeError('Verification session logout failed')
            before = json.loads((REPORT_ROOT / 'preflight.json').read_text())['snapshot']
            after = snapshot(db)
            result['unchangedTables'] = [name for name in before if before[name] == after[name]]
            if len(result['unchangedTables']) != len(before):
                raise RuntimeError('Protected business or upgrade records changed; review snapshots')
            result['health'] = httpx.get(BASE + '/healthz', timeout=10).json()
            old_environment = (ROOT / 'backups/M42-T13-enablement-20261106/environment-before.env').read_text(encoding='utf-8')
            new_environment = (ROOT / '.env').read_text(encoding='utf-8')
            changed_keys = {'APP_UPDATES_ENABLED', 'APP_APK_EXTERNAL_ENABLED', 'APP_APK_COMPATIBILITY_PATH'}
            unchanged_lines = lambda value: [line for line in value.splitlines() if line.split('=', 1)[0] not in changed_keys]
            if unchanged_lines(old_environment) != unchanged_lines(new_environment):
                raise RuntimeError('Unrelated environment configuration changed')
            result['unrelatedEnvironmentUnchanged'] = True
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        report_name = 'frontend-proxy' if args.base_url.endswith(':5173') else args.mode
        (REPORT_ROOT / (report_name + '.json')).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({k: v for k, v in result.items() if k != 'snapshot'}, ensure_ascii=False))
    finally:
        db.close()

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Enablement verification failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
