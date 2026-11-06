"""Register approved public APK identity without rotating keys or publishing.

Read-only by default; --apply is required. Never modifies an existing identity.
No APK private key or password is loaded. Runtime flags must remain disabled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.app_updates.contract import PACKAGE_NAME, Scope
from app.app_updates.models import AppIdentity
from app.app_updates.publisher import AppPublisher
from app.database import DatabaseManager


def ensure_identity(session, *, publisher_id, signer_sha256, metadata_key_id, apply=False):
    if session.get_bind().dialect.name == 'postgresql':
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext('aiyolo.app-update.identity.bootstrap'))"))
    existing = session.scalar(select(AppIdentity).where(AppIdentity.package_name == PACKAGE_NAME).with_for_update())
    expected = dict(publisher_id=publisher_id, approved_signer_sha256=signer_sha256, metadata_key_config_ref=metadata_key_id)
    if existing:
        if any(getattr(existing, key) != value for key, value in expected.items()) or existing.first_version_code != 1:
            raise ValueError('Existing App identity conflicts; no change made.')
        return dict(result='unchanged', packageName=PACKAGE_NAME, versionHighWater=existing.version_high_water)
    if not apply:
        return dict(result='would_create', packageName=PACKAGE_NAME, versionHighWater=None)
    session.add(AppIdentity(package_name=PACKAGE_NAME, first_version_code=1, version_high_water=0, **expected))
    session.flush()
    return dict(result='created', packageName=PACKAGE_NAME, versionHighWater=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--certificate', required=True)
    parser.add_argument('--expected-signer', required=True)
    parser.add_argument('--metadata-public-key', required=True)
    args = parser.parse_args()
    from app.config import settings
    if settings.app_updates_enabled or settings.app_apk_external_enabled or settings.app_apk_worker_enabled:
        raise ValueError('Preparatory registration requires distribution switches off.')
    cert_bytes = Path(args.certificate).read_bytes()
    cert = x509.load_der_x509_certificate(cert_bytes)
    digest = hashlib.sha256(cert_bytes).hexdigest()
    if digest != args.expected_signer or not isinstance(cert.public_key(), rsa.RSAPublicKey) or cert.public_key().key_size < 2048:
        raise ValueError('Approved certificate identity mismatch.')
    if 'Android Debug' in cert.subject.rfc4514_string():
        raise ValueError('Debug certificate cannot be approved.')
    publisher = AppPublisher.from_settings(settings)
    expected_public = serialization.load_pem_public_key(Path(args.metadata_public_key).read_bytes())
    if publisher.key.public_key().public_bytes_raw() != expected_public.public_bytes_raw():
        raise ValueError('Metadata public/private keys differ.')
    scopes = [Scope.model_validate(item) for item in json.loads(Path(settings.app_update_scopes_path).read_text(encoding='utf-8'))]
    if len(scopes) != 1:
        raise ValueError('Bootstrap requires exactly one explicit scope.')
    db = DatabaseManager(settings.database_url)
    if db.backend != 'postgresql':
        raise ValueError('Operator bootstrap expects the configured PostgreSQL database.')
    try:
        with db.session() as session:
            result = ensure_identity(session, publisher_id=scopes[0].publisherId, signer_sha256=digest,
                metadata_key_id=publisher.key_id, apply=args.apply)
        print(json.dumps(result | dict(scope=scopes[0].model_dump(), signerSha256=digest,
            metadataKeyId=publisher.key_id, distributionEnabled=False), indent=2))
    finally:
        db.engine.dispose()


if __name__ == '__main__':
    main()
