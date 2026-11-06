"""Strict reference decoder for the frozen signing format (no key discovery)."""
import base64
import json
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .contract import (CheckPayload, DownloadPayload, InstallPermissionPayload,
                       MAX_METADATA_BYTES, SIGNATURE_DOMAIN, SignedEnvelope)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON number")


def strict_json(raw: bytes):
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("metadata too large")
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def _decode(value: str):
    result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(result).decode("ascii").rstrip("=") != value:
        raise ValueError("noncanonical base64url")
    return result


def verify_envelope(raw: bytes, *, trusted_keys: dict[str, Ed25519PublicKey],
                    message_type: str, expected: dict, min_policy_revision: int,
                    now: datetime | None = None):
    # Envelope expands payload bytes by 4/3; allow only a bounded wire body.
    if len(raw) > MAX_METADATA_BYTES * 2:
        raise ValueError("envelope too large")
    envelope = SignedEnvelope.model_validate(strict_json_envelope(raw))
    key = trusted_keys.get(envelope.keyId)
    if key is None:
        raise ValueError("unknown metadata signing key")
    payload_bytes = _decode(envelope.payloadBase64Url)
    if len(payload_bytes) > MAX_METADATA_BYTES:
        raise ValueError("metadata too large")
    key.verify(_decode(envelope.signatureBase64Url), SIGNATURE_DOMAIN + payload_bytes)
    # Check duplicate keys before handing original bytes to Pydantic's strict
    # JSON mode, which accepts RFC3339 timestamps without coercing integers.
    strict_json(payload_bytes)
    types = {"check": CheckPayload, "download": DownloadPayload, "install_permission": InstallPermissionPayload}
    model = types[message_type].model_validate_json(payload_bytes)
    clock = now or datetime.now(timezone.utc)
    if not model.issuedAt <= clock < model.authorizationExpiresAt:
        raise ValueError("metadata expired or issued in the future")
    if model.policyRevision < min_policy_revision:
        raise ValueError("policy replay")
    data = model.model_dump(mode="json")
    required = {"publisherId", "packageName", "channel", "deploymentId", "installationId", "requestId", "currentVersionCode"}
    if message_type != "check":
        required.update({"releaseId", "artifactId", "sourceId", "sourceRevision", "versionCode",
                         "sha256", "sizeBytes", "signerSha256"})
    if not required.issubset(expected):
        raise ValueError("missing expected authorization context")
    if any(data.get(key) != value for key, value in expected.items()):
        raise ValueError("authorization context mismatch")
    return model


def strict_json_envelope(raw):
    # Separate limit because encoded payloads can legitimately exceed 256KiB.
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)
