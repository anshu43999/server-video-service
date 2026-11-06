"""Independent App metadata signing. Private keys never enter the database."""
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .contract import Id, MAX_METADATA_BYTES, SIGNATURE_DOMAIN, SignedEnvelope
from pydantic import TypeAdapter


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class AppPublisher:
    def __init__(self, key_id, private_key):
        self.key_id = TypeAdapter(Id).validate_python(key_id)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("App metadata requires Ed25519")
        self.key = private_key

    @classmethod
    def from_settings(cls, settings):
        path = Path(settings.app_update_private_key_path).resolve(strict=True)
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        # Even distinct paths must not reuse the model signing key.
        if settings.model_signing_private_key_path:
            model_key = serialization.load_pem_private_key(
                Path(settings.model_signing_private_key_path).read_bytes(), password=None)
            if key.public_key().public_bytes_raw() == model_key.public_key().public_bytes_raw():
                raise ValueError("App and model metadata keys must be independent")
        return cls(settings.app_update_key_id, key)

    def sign(self, value):
        raw = json_bytes(value)
        if len(raw) > MAX_METADATA_BYTES:
            raise ValueError("App metadata too large")
        return SignedEnvelope(keyId=self.key_id, payloadBase64Url=b64(raw),
            signatureBase64Url=b64(self.key.sign(SIGNATURE_DOMAIN + raw))).model_dump()
