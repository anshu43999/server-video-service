"""Offline, redacted App-update preflight; never connects to a database.

Reads environment and explicitly configured files, never .env. Does not create
directories, mutate keys, start workers, publish releases, or test APK downloads.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

TRUE = {"1", "true", "yes", "on"}
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _file(env, name):
    value = env.get(name, "")
    path = Path(value)
    if not value or not path.is_absolute() or not path.is_file() or not os.access(path, os.R_OK):
        raise ValueError(name + "_missing_or_unreadable")
    return path


def _json(env, name):
    path = _file(env, name)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError(name + "_too_large")
    return json.loads(path.read_text(encoding="utf-8"))


def check(env, *, tools_only=False, run=subprocess.run):
    checks = []

    def probe(name, action):
        try:
            action()
            checks.append({"check": name, "ok": True})
        except Exception:
            # Never print paths, tool output, exception text or credential values.
            checks.append({"check": name, "ok": False})

    def command(name, args):
        executable = _file(env, name)
        if not os.access(executable, os.X_OK):
            raise ValueError("tool_not_executable")
        result = run([str(executable), *args], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=False)
        if result.returncode:
            raise ValueError("tool_failed")

    probe("aapt2_executable", lambda: command("APP_APK_AAPT2_PATH", ["version"]))
    probe("java_executable", lambda: command("APP_APK_JAVA_PATH", ["-version"]))
    probe("apksigner_executable", lambda: command("APP_APK_JAVA_PATH",
          ["-jar", str(_file(env, "APP_APK_APKSIGNER_JAR_PATH")), "version"]))

    if not tools_only:
        def required_flag(name):
            if env.get(name, "").strip().lower() not in TRUE:
                raise ValueError("mandatory_feature_disabled")
        for name in ("APP_UPDATES_ENABLED", "APP_APK_EXTERNAL_ENABLED"):
            probe(name, lambda name=name: required_flag(name))

        def scopes():
            values = _json(env, "APP_UPDATE_SCOPES_PATH")
            if not isinstance(values, list) or not values:
                raise ValueError("scope_missing")
            fields = {"contractVersion", "publisherId", "packageName", "channel", "deploymentId"}
            for value in values:
                if not isinstance(value, dict) or set(value) != fields:
                    raise ValueError("scope_fields_invalid")
                if value["contractVersion"] != "app-update/v1" or value["packageName"] != "com.aiyolo.inspection":
                    raise ValueError("scope_contract_invalid")
                if any(not isinstance(value[k], str) or not ID.fullmatch(value[k])
                       for k in ("publisherId", "channel", "deploymentId")):
                    raise ValueError("scope_identity_invalid")
        probe("scope_file_schema", scopes)

        def compatibility():
            value = _json(env, "APP_APK_COMPATIBILITY_PATH")
            numeric = ("server_contract_min", "server_contract_max", "data_schema_version",
                       "readable_schema_min", "readable_schema_max")
            if not isinstance(value, dict) or set(value) != {*numeric, "evidence_ref"}:
                raise ValueError("compatibility_fields_invalid")
            if any(type(value[k]) is not int or not 1 <= value[k] <= 2147483647 for k in numeric):
                raise ValueError("compatibility_integer_invalid")
            if value["server_contract_min"] > value["server_contract_max"] or not (
                value["readable_schema_min"] <= value["data_schema_version"] <= value["readable_schema_max"]
            ):
                raise ValueError("compatibility_range_invalid")
            if not isinstance(value["evidence_ref"], str) or not 1 <= len(value["evidence_ref"]) <= 512:
                raise ValueError("compatibility_evidence_missing")
        probe("compatibility_file_schema_only", compatibility)

        def signing():
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            if not ID.fullmatch(env.get("APP_UPDATE_KEY_ID", "")):
                raise ValueError("key_id_invalid")
            path = _file(env, "APP_UPDATE_PRIVATE_KEY_PATH")
            if path.stat().st_size > 65536:
                raise ValueError("key_file_too_large")
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("wrong_key_type")
            if env.get("MODEL_SIGNING_PRIVATE_KEY_PATH"):
                other_path = _file(env, "MODEL_SIGNING_PRIVATE_KEY_PATH")
                if other_path.stat().st_size > 65536:
                    raise ValueError("model_key_file_too_large")
                other = serialization.load_pem_private_key(other_path.read_bytes(), password=None)
                if not isinstance(other, Ed25519PrivateKey) or key.public_key().public_bytes_raw() == other.public_key().public_bytes_raw():
                    raise ValueError("independent_keys_required")
        probe("app_signing_key_and_configured_model_key_separation", signing)

        def writable(name):
            value = env.get(name, "")
            path = Path(value)
            if not value or not path.is_absolute() or not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
                raise ValueError("working_directory_not_writable")
        directories = ["APP_APK_EVIDENCE_ROOT", "APP_APK_STAGING_ROOT", "APP_APK_EXTERNAL_ROOT"]
        if env.get("APP_APK_WORKER_ENABLED", "").strip().lower() in TRUE:
            directories.append("APP_APK_UPLOAD_ROOT")
        for name in directories:
            probe(name + "_permission_estimate", lambda name=name: writable(name))

    return {"ok": all(item["ok"] for item in checks), "mode": "tools" if tools_only else "offline_configuration",
            "checks": checks, "production_ready": False,
            "not_checked": ["database_schema_and_identity", "compatibility_evidence_provenance",
                            "client_trust", "https_download", "actual_volume_writes_and_capacity",
                            "real_apk_verification_and_install"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-only", action="store_true")
    args = parser.parse_args()
    result = check(os.environ, tools_only=args.tools_only)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
