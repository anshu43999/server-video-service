"""Optional FCM HTTP v1 data-only wakeup. No model or account metadata."""
import base64
from datetime import timedelta
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import select

from .models import Device, PushOutbox
from .protocol import UpdateError, now, utc


class PushResult:
    def __init__(self, state, retry_after=30):
        self.state, self.retry_after = state, max(1, retry_after)


def _https_json(url, data, headers):
    request = urllib.request.Request(url, data=data, headers=headers, method='POST')
    # Redirects must never disclose Authorization or device registration tokens.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=10) as result:
            content = result.read(65537)
            if len(content) > 65536:
                return 503, {}, {}
            return result.status, json.loads(content), dict(result.headers)
    except urllib.error.HTTPError as exc:
        try:
            content = json.loads(exc.read(65536))
        except (ValueError, UnicodeError):
            content = {}
        return exc.code, content, dict(exc.headers)


class FcmSender:
    """Credentials stay server-side; exact configured project is mandatory."""
    def __init__(self, project_id=None, credentials_path=None, *, transport=_https_json):
        self.project_id, self.credentials_path, self.transport = project_id, credentials_path, transport
        self._token, self._until, self._lock = None, 0, threading.Lock()

    @property
    def enabled(self):
        return bool(self.project_id and self.credentials_path)

    @staticmethod
    def _b64(value):
        return base64.urlsafe_b64encode(value).rstrip(b'=')

    def _access_token(self):
        with self._lock:
            if self._token and time.time() < self._until:
                return self._token
            credentials = json.loads(Path(self.credentials_path).read_text(encoding='utf-8'))
            if (credentials.get('project_id') != self.project_id or credentials.get('type') != 'service_account'
                    or not re.fullmatch(r'[a-z][a-z0-9-]{4,62}', self.project_id)
                    or credentials.get('token_uri') != 'https://oauth2.googleapis.com/token'):
                raise ValueError('FCM configuration project mismatch')
            issued = int(time.time())
            header = self._b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
            claims = self._b64(json.dumps({'iss': credentials['client_email'],
                'scope': 'https://www.googleapis.com/auth/firebase.messaging',
                'aud': 'https://oauth2.googleapis.com/token', 'iat': issued, 'exp': issued + 3600}, separators=(',', ':')).encode())
            signed = header + b'.' + claims
            key = serialization.load_pem_private_key(credentials['private_key'].encode(), password=None)
            assertion = signed + b'.' + self._b64(key.sign(signed, padding.PKCS1v15(), hashes.SHA256()))
            code, content, _ = self.transport('https://oauth2.googleapis.com/token',
                urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                        'assertion': assertion.decode()}).encode(),
                {'Content-Type': 'application/x-www-form-urlencoded'})
            if code != 200 or not isinstance(content, dict) or not isinstance(content.get('access_token'), str):
                raise OSError('FCM OAuth unavailable')
            self._token = content['access_token']
            self._until = issued + max(1, int(content.get('expires_in', 3600)) - 60)
            return self._token

    def send(self, registration_token):
        if not self.enabled:
            return PushResult('disabled')
        try:
            token = self._access_token()
            payload = {'message': {'token': registration_token,
                'data': {'type': 'model_updates_changed', 'contractVersion': '1', 'eventId': str(uuid4())},
                'android': {'priority': 'normal', 'ttl': '86400s', 'collapse_key': 'model_updates_changed_v1'}}}
            status, content, headers = self.transport(
                f'https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send',
                json.dumps(payload, separators=(',', ':')).encode(),
                {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
            if not isinstance(content, dict):
                return PushResult('retry')
            if status == 200 and isinstance(content.get('name'), str):
                return PushResult('accepted')
            error_body = content.get('error')
            errors = error_body.get('details', []) if isinstance(error_body, dict) else []
            if not isinstance(errors, list):
                errors = []
            if any(isinstance(error, dict) and error.get('@type') == 'type.googleapis.com/google.firebase.fcm.v1.FcmError' and
                   error.get('errorCode') == 'UNREGISTERED' for error in errors):
                return PushResult('invalid_token')
            if status == 401:
                self._token, self._until = None, 0
            if status in {401, 403, 404}:
                return PushResult('configuration_error', 300)
            try:
                hint = next((v for k, v in headers.items() if isinstance(k, str) and k.lower() == 'retry-after'), '30')
                try:
                    retry = int(hint)
                except (TypeError, ValueError):
                    retry = max(1, int((parsedate_to_datetime(hint) - now()).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                retry = 30
            return PushResult('retry', retry)
        except ValueError:
            return PushResult('configuration_error', 300)
        except (OSError, KeyError, TypeError):
            return PushResult('retry')


class PushDispatcher:
    def __init__(self, store, sender, *, should_stop=lambda: False):
        self.store, self.sender, self.should_stop = store, sender, should_stop

    def claim(self, device_id):
        with self.store.database.session() as session:
            device = session.scalar(select(Device).where(Device.device_id == device_id).with_for_update())
            row = session.get(PushOutbox, device_id)
            if device is None or row is None or device.revoked or row.sent_sequence >= row.dirty_sequence:
                return None
            from ..database import AccountRecord
            account = session.get(AccountRecord, device.account_id, populate_existing=True)
            if account is None or not account.enabled:
                row.disabled_reason = 'account_disabled'
                return None
            if utc(row.next_attempt) > now() or row.lease_until and utc(row.lease_until) > now():
                return None
            if not self.sender.enabled or device.push_provider != 'fcm' or not device.push_token:
                row.disabled_reason = 'configuration_missing' if not self.sender.enabled else 'provider_none'
                return None
            row.disabled_reason = None
            row.lease_sequence, row.lease_id, row.lease_until = row.dirty_sequence, str(uuid4()), now() + timedelta(seconds=60)
            session.flush()
            return dict(deviceId=device_id, leaseId=row.lease_id, sequence=row.lease_sequence,
                        token=device.push_token, generation=device.token_generation)

    def finish(self, lease, result):
        with self.store.database.session() as session:
            device = session.scalar(select(Device).where(Device.device_id == lease['deviceId']).with_for_update())
            row = session.get(PushOutbox, lease['deviceId'])
            if row is None or device is None or device.revoked or row.lease_id != lease['leaseId']:
                return
            row.lease_id, row.lease_until = None, None
            if device.push_token != lease['token'] or device.token_generation != lease['generation']:
                return
            self.store.measure(session, 'provider_' + result.state)
            if result.state == 'accepted':
                row.sent_sequence = max(row.sent_sequence, lease['sequence'])
                if row.sent_sequence >= row.dirty_sequence:
                    row.dirty_since = None
                row.attempts, row.disabled_reason = 0, None
                row.next_attempt = now() + timedelta(seconds=30)
            elif result.state == 'invalid_token':
                device.push_token, device.push_provider = None, 'none'
                row.disabled_reason = 'invalid_token'
            else:
                row.attempts = min(row.attempts + 1, 100)
                row.disabled_reason = result.state
                delay = max(result.retry_after, min(3600, 30 * 2 ** min(row.attempts - 1, 10)) * random.uniform(1, 1.2))
                row.next_attempt = now() + timedelta(seconds=max(result.retry_after, min(3600, delay)))

    def dispatch(self, maximum=100):
        if not self.sender.enabled:
            return {}
        from ..database import AccountRecord
        with self.store.database.session() as session:
            ids = session.scalars(select(PushOutbox.device_id).join(Device, Device.device_id == PushOutbox.device_id)
                .join(AccountRecord, AccountRecord.account_id == Device.account_id).where(
                PushOutbox.dirty_sequence > PushOutbox.sent_sequence, PushOutbox.next_attempt <= now(),
                Device.revoked.is_(False), Device.push_provider == 'fcm', Device.push_token.is_not(None),
                AccountRecord.enabled.is_(True))
                .order_by(PushOutbox.next_attempt).limit(maximum)).all()
        counts = {}
        for device_id in ids:
            if self.should_stop():
                break
            lease = self.claim(device_id)
            if lease is None:
                continue
            try:
                self.store.rate_limit('fcm:egress', rate=100, burst=100, shared_global=False)
                result = self.sender.send(lease['token'])
            except UpdateError:
                result = PushResult('retry', 1)
            self.finish(lease, result)
            counts[result.state] = counts.get(result.state, 0) + 1
        return counts
