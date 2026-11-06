"""Approved JSON identity shared with Android SceneParameterSnapshot (v1)."""
from decimal import Decimal
from hashlib import sha256
import json


def canonical_parameter_json(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # UTF-8, not ASCII escape spelling; reject malformed surrogate strings.
        value.encode("utf-8", errors="strict")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("non-finite approved parameter")
        if number == 0:
            return "0"
        encoded = format(number, "f")
        return encoded.rstrip("0").rstrip(".") if "." in encoded else encoded
    if isinstance(value, list):
        return "[" + ",".join(canonical_parameter_json(item) for item in value) + "]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return "{" + ",".join(canonical_parameter_json(key) + ":" +
            canonical_parameter_json(value[key]) for key in sorted(value)) + "}"
    raise ValueError("unsupported approved parameter type")


def parameter_digest(snapshot):
    return sha256(canonical_parameter_json(snapshot).encode("utf-8")).hexdigest()
