"""Offline migration bundles. No automatic startup migration or in-place restore.

Bundles contain credentials and evidence: store them outside source control with
operator-only ACLs. Every write requires a maintenance window; source databases
and original evidence are never deleted by restore.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import quote
from uuid import UUID, uuid5

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from .alert_evidence import AlertEvidenceStore
from .database import DEFAULT_PROJECT_ID, Base

ROOT = Path(__file__).resolve().parents[1]
LEGACY = "20260920_05"
TARGET = "20261019_13"
UPGRADED_REVISIONS = {"20261012_11", "20261014_12", TARGET}
NAMESPACE = UUID("b31965a3-7fc1-4ae9-b1c1-cf2edbd74d45")
OWNED = (
    "alert_events", "alert_disposition_actions", "false_positive_feedback", "alert_rules",
    "alert_rule_bindings", "alert_rule_audits", "model_parameter_profiles", "model_parameter_audits",
    "alert_verification_config", "alert_verifications", "alert_delivery_receipts", "stream_configs",
)
ARCHIVE_NAME = "orphan-delivery-receipts"


class MigrationError(RuntimeError):
    """An operator-actionable error containing no source data or connection secrets."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encode_row(row):
    # Schema-driven datetime decoding avoids interpreting user JSON as type tags.
    return {key: (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()
            if isinstance(value, datetime) else value for key, value in row.items()}


def decode_row(table, row):
    return {key: datetime.fromisoformat(value) if value is not None and isinstance(table.c[key].type, sa.DateTime)
            else value for key, value in row.items()}


def config(connection):
    result = Config(str(ROOT / "alembic.ini"))
    result.set_main_option("script_location", str(ROOT / "alembic"))
    result.set_main_option("sqlalchemy.url", connection.engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    result.attributes["connection"] = connection
    return result


def identity(connection):
    url = connection.engine.url
    if url.get_backend_name() == "sqlite":
        value = ["sqlite", str(Path(url.database).resolve())]
    else:
        value = ["postgresql", url.host, url.port or 5432, url.database,
                 connection.scalar(sa.text("SELECT current_schema()"))]
    return digest(canonical(value).encode())


@contextmanager
def database_connection(url, *, write=False):
    parsed = make_url(url)
    if parsed.get_backend_name() not in {"sqlite", "postgresql"} or parsed.database == ":memory:":
        raise MigrationError("only file SQLite or PostgreSQL is supported")
    engine = sa.create_engine(parsed)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "sqlite":
                # Explicit BEGIN keeps SQLite batch DDL transactional. FK constraints
                # are verified before commit because Alembic reconstructs parent tables.
                connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
            else:
                connection.execution_options(isolation_level="SERIALIZABLE" if write else "REPEATABLE READ")
                connection.begin()
                connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
                if not write:
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            try:
                yield connection
                if write and engine.dialect.name == "sqlite":
                    if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
                        raise MigrationError("foreign key reconciliation failed")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
    finally:
        engine.dispose()


def schema(connection):
    inspector = sa.inspect(connection)
    tables = inspector.get_table_names()
    if set(tables) - (set(Base.metadata.tables) | {"alembic_version"}):
        raise MigrationError("unknown tables: use a native full database backup and review schema first")
    if inspector.get_view_names():
        raise MigrationError("custom views are unsupported by the portable restore; use native backup")
    if connection.dialect.name == "postgresql":
        extras = connection.scalar(sa.text(
            "SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=current_schema()"))
        if extras:
            raise MigrationError("custom triggers require native backup")
    elif connection.scalar(sa.text("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'")):
        raise MigrationError("custom triggers require native backup")
    metadata = sa.MetaData()
    metadata.reflect(connection, only=tables)
    revision = connection.scalar(sa.text("SELECT version_num FROM alembic_version")) if "alembic_version" in tables else None
    known = {r.revision for r in ScriptDirectory.from_config(config(connection)).walk_revisions()}
    if (tables and not revision) or (revision and revision not in known):
        raise MigrationError("missing or unsupported Alembic revision")
    return metadata, revision


def schema_signature(connection):
    """Reject custom schema drift before treating a portable restore as verified."""
    inspector = sa.inspect(connection)
    result = {}
    schema_name = connection.scalar(sa.text("SELECT current_schema()")) if connection.dialect.name == "postgresql" else None
    for name in inspector.get_table_names():
        columns = []
        for column in inspector.get_columns(name):
            default = column.get("default")
            if default and schema_name:
                default = default.replace(schema_name + ".", "")
            columns.append({"name": column["name"], "type": str(column["type"]),
                            "nullable": column["nullable"], "default": default})
        result[name] = {"columns": columns, "pk": inspector.get_pk_constraint(name),
                        "fk": sorted(inspector.get_foreign_keys(name), key=canonical),
                        "unique": sorted(inspector.get_unique_constraints(name), key=canonical),
                        "indexes": sorted(inspector.get_indexes(name), key=canonical),
                        "checks": sorted(inspector.get_check_constraints(name), key=canonical)}
    return result


def sequence_state(connection, metadata):
    result = {}
    if connection.dialect.name != "postgresql":
        return result
    for table in metadata.tables.values():
        for column in table.primary_key.columns:
            if not isinstance(column.type, sa.Integer):
                continue
            sequence = connection.scalar(sa.text("SELECT pg_get_serial_sequence(:table, :column)"),
                                         {"table": table.name, "column": column.name})
            if sequence:
                # Name comes from the catalog; quote each identifier explicitly.
                parts = connection.execute(sa.text(
                    "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE c.oid=CAST(:sequence AS regclass)"), {"sequence": sequence}).one()
                quoted = ".".join(connection.dialect.identifier_preparer.quote(part) for part in parts)
                state = connection.execute(sa.text(f"SELECT last_value,is_called FROM {quoted}")).mappings().one()
                result[f"{table.name}.{column.name}"] = dict(state)
    return result


def rows(connection, table):
    if not table.primary_key.columns:
        raise MigrationError("a backup table lacks a primary key")
    return connection.execute(sa.select(table).order_by(*table.primary_key.columns)
                              .execution_options(yield_per=100)).mappings()


def fingerprint(connection, table):
    checksum = hashlib.sha256()
    count = 0
    for row in rows(connection, table):
        checksum.update((canonical(encode_row(row)) + "\n").encode())
        count += 1
    return {"count": count, "sha256": checksum.hexdigest()}


def orphan_query(metadata):
    receipts = metadata.tables["alert_delivery_receipts"]
    events = metadata.tables["alert_events"]
    return sa.select(receipts).where(~sa.exists(sa.select(1).where(
        events.c.event_id == receipts.c.event_id))).order_by(receipts.c.delivery_id)


def write_orphan_archive(connection, metadata, bundle):
    checksum, count = hashlib.sha256(), 0
    with (bundle / f"{ARCHIVE_NAME}.jsonl").open("xb") as handle:
        if "alert_delivery_receipts" in metadata.tables:
            with closing(connection.execute(orphan_query(metadata).execution_options(yield_per=100)).mappings()) as result:
                for row in result:
                    line = (canonical(encode_row(row)) + "\n").encode()
                    handle.write(line)
                    checksum.update(line)
                    count += 1
        handle.flush()
        os.fsync(handle.fileno())
    return {"count": count, "sha256": checksum.hexdigest(), "reason": "missing-parent-alert",
            "file": f"{ARCHIVE_NAME}.jsonl"}


def nonarchived_receipts(bundle, manifest):
    """Merge the sorted archive and original snapshot without loading all IDs."""
    archived = iter(saved_rows(bundle, ARCHIVE_NAME))
    orphan = next(archived, None)
    for row in saved_rows(bundle, "alert_delivery_receipts"):
        if orphan is not None and row["delivery_id"] == orphan["delivery_id"]:
            if row != orphan:
                raise MigrationError("orphan archive differs from original backup")
            orphan = next(archived, None)
        else:
            yield row
    if orphan is not None:
        raise MigrationError("orphan archive contains records absent from original backup")


def preflight(connection):
    metadata, revision = schema(connection)
    report = {"revision": revision, "targetRevision": TARGET, "source": identity(connection),
              "tables": {name: fingerprint(connection, table) for name, table in metadata.tables.items()},
              "accountMapping": [], "defaultProjectId": DEFAULT_PROJECT_ID, "blockers": []}
    if revision not in {None, LEGACY, *UPGRADED_REVISIONS}:
        raise MigrationError("finish/review the existing migration before starting this rollout")
    if "accounts" in metadata.tables and revision == LEGACY:
        accounts = metadata.tables["accounts"]
        enabled_owner = False
        for row in rows(connection, accounts):
            if row["role"] not in {"admin", "operator"}:
                raise MigrationError("unrecognized legacy account role")
            enabled_owner |= row["role"] == "admin" and row["enabled"]
            report["accountMapping"].append({
                "username": row["username"],
                "accountId": str(uuid5(NAMESPACE, f"legacy-account:{row['username']}")),
                "platformRole": "PLATFORM_ADMIN" if row["role"] == "admin" else "NORMAL_USER",
                "projectRole": "PROJECT_OWNER" if row["role"] == "admin" else "PROJECT_USER",
                "enabled": bool(row["enabled"]),
            })
        if report["accountMapping"] and not enabled_owner:
            raise MigrationError("legacy accounts require an enabled administrator owner")
        # New project-qualified FK did not exist on legacy delivery receipts.
        orphan_count = connection.scalar(sa.text(
            "SELECT COUNT(*) FROM alert_delivery_receipts d LEFT JOIN alert_events e "
            "ON d.event_id=e.event_id WHERE e.event_id IS NULL"))
        if orphan_count:
            report["blockers"].append({"code": "orphan_delivery_receipts", "count": orphan_count})
    if revision in UPGRADED_REVISIONS:
        report["alreadyUpgraded"] = True
    return report


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class Assets:
    """Validate and copy evidence; no arbitrary network fetch or original deletion."""
    def __init__(self, bundle, *, roots=(), store=None, inventory=None, event_evidence=None, evidence_bundle=None):
        self.bundle = Path(bundle)
        self.roots = [Path(root).resolve() for root in roots]
        self.store = store
        self.inventory = inventory if inventory is not None else {}
        self.event_evidence = event_evidence
        self.evidence_bundle = Path(evidence_bundle) if evidence_bundle is not None else None
        self.cached_manifest = verify_bundle(self.evidence_bundle) if self.evidence_bundle else None
        self.reused_count = 0

    def read_source(self, reference, event_id):
        if isinstance(reference, dict):
            store = self.store
            if not store or not store.enabled or reference.get("provider") != "minio" or reference.get("bucket") != store.bucket:
                raise MigrationError("evidence object store must be explicitly configured")
            key = str(reference.get("objectKey") or "")
            event_hash = digest(event_id.encode())
            prefix = re.escape(store.prefix)
            project_hash = digest(DEFAULT_PROJECT_ID.encode())
            # Accept only the old event hash key or the already partitioned default key.
            allowed = rf"{prefix}/(?:projects/{project_hash}/)?{event_hash[:2]}/{event_hash}\.(png|jpg|webp|bin)"
            if re.fullmatch(allowed, key) is None:
                raise MigrationError("object evidence ownership mismatch")
            response = None
            try:
                response = store._client.get_object(store.bucket, key)
                content = response.read(8_000_001)
            finally:
                if response is not None:
                    response.close()
                    response.release_conn()
            media = reference.get("contentType") or "image/jpeg"
            if reference.get("sha256") and digest(content) != reference["sha256"]:
                raise MigrationError("object evidence checksum mismatch")
        elif reference.startswith("data:image/"):
            body = AlertEvidenceStore.decode_data_url(reference)
            return body.content, body.content_type
        else:
            # Known legacy URI layouts; roots are operator-specified and symlinks
            # must resolve inside one of those roots.
            if "?" in reference or "#" in reference or ".." in Path(reference).parts:
                raise MigrationError("unsafe local evidence reference")
            candidates = []
            if reference.startswith(("/aiyoloapi/alerts/", "/api/alerts/")):
                if reference.rsplit("/", 1)[-1] != "evidence":
                    raise MigrationError("unrecognized evidence route")
                if reference.split("/")[-2] != quote(event_id, safe=""):
                    raise MigrationError("local evidence event mismatch")
                if self.event_evidence:
                    current = self.event_evidence(event_id)
                    backing = next((current[k] for k in ("objectStorage", "snapshotDataUrl", "localPath", "snapshotUri")
                                    if current.get(k) and current[k] != reference), None)
                    if backing is not None:
                        return self.read_source(backing, event_id)
                candidates = [root / f"{event_id}.jpg" for root in self.roots]
            elif "://" in reference:
                raise MigrationError("remote evidence URLs require an explicit offline import")
            else:
                relative = reference.removeprefix("/static/").removeprefix("static/")
                path = Path(reference)
                candidates = [path] if path.is_absolute() else [root / relative for root in self.roots]
                if reference.startswith("/static/"):
                    candidates = [root / relative for root in self.roots]
            valid = {p.resolve() for p in candidates if p.is_file() and
                     any(p.resolve().is_relative_to(root) for root in self.roots)}
            if len(valid) != 1:
                raise MigrationError("missing, ambiguous or out-of-root local evidence")
            path = valid.pop()
            with path.open("rb") as handle:
                content = handle.read(8_000_001)
            media = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        if not content or len(content) > 8_000_000 or media not in {"image/png", "image/jpeg", "image/webp"}:
            raise MigrationError("evidence must be a supported image within 8 MB")
        return content, media

    def image(self, reference, event_id, *, capture):
        key = digest(canonical([event_id, reference]).encode())
        if capture:
            cached = self.cached_manifest["assets"].get(key) if self.cached_manifest else None
            if cached is not None:
                if cached["eventId"] != event_id or cached["projectId"] != DEFAULT_PROJECT_ID:
                    raise MigrationError("cached evidence ownership mismatch")
                # Only a content-bound object reference or an exact inline data URL
                # can be reused. Mutable file paths without a source hash cannot.
                if isinstance(reference, dict):
                    if reference.get("sha256") != cached["sha256"]:
                        raise MigrationError("cached object requires matching source checksum")
                elif not reference.startswith("data:image/"):
                    raise MigrationError("cached evidence reference is not content-bound")
                content = (self.evidence_bundle / "assets" / cached["sha256"]).read_bytes()
                if digest(content) != cached["sha256"] or len(content) != cached["size"]:
                    raise MigrationError("cached evidence checksum mismatch")
                media = cached["contentType"]
                self.reused_count += 1
            else:
                content, media = self.read_source(reference, event_id)
            checksum = digest(content)
            target = self.bundle / "assets" / checksum
            if not target.exists():
                with target.open("xb") as handle:
                    handle.write(content)
            entry = {"sha256": checksum, "size": len(content), "contentType": media,
                     "projectId": DEFAULT_PROJECT_ID, "eventId": event_id}
            self.inventory[key] = entry
        else:
            entry = self.inventory.get(key)
            if not entry or entry["eventId"] != event_id or entry["projectId"] != DEFAULT_PROJECT_ID:
                raise MigrationError("missing evidence ownership receipt")
            content = (self.bundle / "assets" / entry["sha256"]).read_bytes()
            if digest(content) != entry["sha256"] or len(content) != entry["size"]:
                raise MigrationError("backup evidence checksum mismatch")
            media = entry["contentType"]
        return f"data:{media};base64,{base64.b64encode(content).decode('ascii')}"

    def transform(self, name, row, *, capture=False):
        row = dict(row)
        payload = row.get("payload")
        if name not in OWNED or not isinstance(payload, dict):
            return row
        payload = json.loads(canonical(payload))
        if payload.get("projectId") not in {None, "", DEFAULT_PROJECT_ID}:
            raise MigrationError("legacy payload has conflicting project ownership")
        payload["projectId"] = DEFAULT_PROJECT_ID
        event_id = str(row.get("event_id") or payload.get("eventId") or "")
        evidence = payload.get("evidence")
        # Delivery/audit payloads are historical notification metadata (including
        # redacted placeholders), not evidence stores. Preserve them verbatim.
        if name in {"alert_events", "false_positive_feedback"} and isinstance(evidence, dict):
            references = [evidence[k] for k in ("objectStorage", "snapshotDataUrl", "localPath", "snapshotUri") if evidence.get(k)]
            # A storage/local reference plus its public route names the same asset.
            material = [ref for ref in references if not (isinstance(ref, str) and ref.startswith("/aiyoloapi/"))]
            references = material or references
            images = [self.image(ref, event_id, capture=capture) for ref in references]
            if len(set(images)) > 1:
                raise MigrationError("conflicting evidence representations")
            if images:
                for field in ("objectStorage", "snapshotDataUrl", "localPath"):
                    evidence.pop(field, None)
                evidence["snapshotUri"] = images[0]
        if name == "false_positive_feedback":
            for field in ("image", "screenshot"):
                if payload.get(field):
                    payload[field] = self.image(payload[field], event_id, capture=capture)
        row["payload"] = payload
        return row

    def restore_row(self, name, row):
        # Recover bytes from the bundle even if originals were lost. Keep legacy
        # project semantics and only canonicalize external evidence to inline data.
        original_payload = row.get("payload")
        result = self.transform(name, row)
        if isinstance(original_payload, dict) and name in OWNED:
            if "projectId" not in original_payload:
                result["payload"].pop("projectId", None)
            else:
                result["payload"]["projectId"] = original_payload["projectId"]
        return result


def prepare(url, bundle, *, roots=(), store=None, evidence_bundle=None):
    bundle = Path(bundle).resolve()
    # Exclusive directory creation also prevents accidentally replacing a backup.
    bundle.mkdir(mode=0o700, parents=True, exist_ok=False)
    (bundle / "assets").mkdir(mode=0o700)
    assets = Assets(bundle, roots=roots, store=store, evidence_bundle=evidence_bundle)
    with database_connection(url) as connection:
        report = preflight(connection)
        if report["revision"] in UPGRADED_REVISIONS:
            raise MigrationError("database already upgraded; this tool only accepts pre-rollout snapshots")
        metadata, _ = schema(connection)
        def event_evidence(event_id):
            table = metadata.tables.get("alert_events")
            if table is None:
                return {}
            payload = connection.scalar(sa.select(table.c.payload).where(table.c.event_id == event_id))
            return (payload or {}).get("evidence") or {}
        assets.event_evidence = event_evidence
        for table in metadata.sorted_tables:
            with (bundle / f"{table.name}.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
                for row in rows(connection, table):
                    try:
                        assets.transform(table.name, row, capture=True)
                    except MigrationError as exc:
                        raise MigrationError(f"{exc}; table={table.name}") from None
                    handle.write(canonical(encode_row(row)) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        report.update({"format": 2, "createdAt": datetime.now(timezone.utc).isoformat(), "assets": assets.inventory,
                       "orphanArchive": write_orphan_archive(connection, metadata, bundle),
                       "evidenceReuse": {"count": assets.reused_count, "sourceBundleId":
                           digest((Path(evidence_bundle) / "manifest.json").read_bytes()) if evidence_bundle else None},
                       "dialect": connection.dialect.name, "schema": schema_signature(connection),
                       "sequences": sequence_state(connection, metadata),
                       "columns": {t.name: list(t.c.keys()) for t in metadata.sorted_tables},
                       "primaryKeys": {t.name: [c.name for c in t.primary_key.columns] for t in metadata.sorted_tables}})
        atomic_json(bundle / "manifest.json", report)
        atomic_json(bundle / "manifest.sha256.json", {"sha256": digest((bundle / "manifest.json").read_bytes())})
        atomic_json(bundle / "checkpoint.json", {"phase": "prepared"})
    verify_bundle(bundle)
    return summary(report, "prepared")


def verify_bundle(bundle):
    bundle = Path(bundle)
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    expected = json.loads((bundle / "manifest.sha256.json").read_text(encoding="utf-8"))["sha256"]
    if digest(manifest_bytes) != expected:
        raise MigrationError("backup manifest checksum mismatch")
    manifest = json.loads(manifest_bytes)
    if manifest.get("format") not in {1, 2} or manifest.get("revision") not in {None, LEGACY}:
        raise MigrationError("unsupported backup format or source revision")
    for name, entry in manifest["tables"].items():
        if name not in set(Base.metadata.tables) | {"alembic_version"}:
            raise MigrationError("unknown backup table")
        count = 0
        checksum = hashlib.sha256()
        with (bundle / f"{name}.jsonl").open("rb") as handle:
            for line in handle:
                checksum.update(line)
                count += 1
        if count != entry["count"] or checksum.hexdigest() != entry["sha256"]:
            raise MigrationError("backup table checksum mismatch")
    for entry in manifest["assets"].values():
        if not re.fullmatch("[a-f0-9]{64}", entry["sha256"]):
            raise MigrationError("invalid backup asset key")
        content = (bundle / "assets" / entry["sha256"]).read_bytes()
        if digest(content) != entry["sha256"] or len(content) != entry["size"]:
            raise MigrationError("backup evidence checksum mismatch")
    archive = manifest.get("orphanArchive")
    if archive is not None:
        if archive["file"] != f"{ARCHIVE_NAME}.jsonl":
            raise MigrationError("invalid orphan archive path")
        checksum, count = hashlib.sha256(), 0
        with (bundle / archive["file"]).open("rb") as handle:
            for line in handle:
                checksum.update(line)
                count += 1
        if count != archive["count"] or checksum.hexdigest() != archive["sha256"]:
            raise MigrationError("orphan archive checksum mismatch")
        if "alert_delivery_receipts" in manifest["tables"]:
            # Exhaust the merge to verify that every archived original is retained.
            for _ in nonarchived_receipts(bundle, manifest):
                pass
    return manifest


def summary(manifest, phase):
    return {"phase": phase, "sourceRevision": manifest["revision"], "targetRevision": TARGET,
            "applyReady": manifest["format"] == 2,
            "tables": {name: entry["count"] for name, entry in manifest["tables"].items()},
            "accounts": len(manifest["accountMapping"]), "evidenceReferences": len(manifest["assets"]),
            "blockers": manifest.get("blockers", []), "evidenceReuse": manifest.get("evidenceReuse"),
            "orphanArchive": manifest.get("orphanArchive")}


def saved_rows(bundle, name):
    with (Path(bundle) / f"{name}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def reconcile(connection, bundle, manifest, *, archived_orphans=None):
    metadata, revision = schema(connection)
    if revision != TARGET:
        raise MigrationError("migration has not reached target revision")
    if archived_orphans is None:
        audit = metadata.tables["platform_audit_events"]
        receipt = connection.scalar(sa.select(audit.c.change_summary).where(
            audit.c.action == "migration.default_project",
            audit.c.target_id == digest((Path(bundle) / "manifest.json").read_bytes())))
        archived_orphans = bool(receipt and receipt.get("orphanArchive"))
        if archived_orphans and receipt["orphanArchive"] != manifest.get("orphanArchive"):
            raise MigrationError("migration archive receipt differs from backup")
    assets = Assets(bundle, inventory=manifest["assets"])
    for name, expected in manifest["tables"].items():
        if name == "alembic_version":
            continue
        table = metadata.tables[name]
        # Compare every original column and value, including payload transformations.
        count = 0
        with closing(connection.execute(sa.select(table).order_by(
            *(table.c[key] for key in manifest["primaryKeys"][name]))
            .execution_options(yield_per=100)).mappings()) as actual:
            originals = nonarchived_receipts(bundle, manifest) if archived_orphans and name == "alert_delivery_receipts" else saved_rows(bundle, name)
            for before, after in zip(originals, actual):
                transformed = assets.transform(name, before)
                for key, value in transformed.items():
                    actual_value = encode_row(after)[key]
                    if actual_value != value:
                        raise MigrationError(f"row reconciliation failed: {name}")
                if name in OWNED and after["project_id"] != DEFAULT_PROJECT_ID:
                    raise MigrationError("business row ownership reconciliation failed")
                count += 1
        expected_count = expected["count"] - (manifest["orphanArchive"]["count"] if archived_orphans and name == "alert_delivery_receipts" else 0)
        if count != expected_count or connection.scalar(sa.select(sa.func.count()).select_from(table)) != count:
            raise MigrationError(f"row count reconciliation failed: {name}")
    for entry in manifest["accountMapping"]:
        account = connection.execute(sa.select(metadata.tables["accounts"]).where(
            metadata.tables["accounts"].c.username == entry["username"])).mappings().one()
        membership = connection.execute(sa.select(metadata.tables["project_memberships"]).where(
            metadata.tables["project_memberships"].c.account_id == entry["accountId"],
            metadata.tables["project_memberships"].c.project_id == DEFAULT_PROJECT_ID)).mappings().one()
        if account["account_id"] != entry["accountId"] or account["platform_role"] != entry["platformRole"] or membership["project_role"] != entry["projectRole"] or bool(membership["enabled"]) != entry["enabled"]:
            raise MigrationError("account mapping reconciliation failed")
    if connection.scalar(sa.select(sa.func.count()).select_from(metadata.tables["projects"])) != 1:
        raise MigrationError("default project reconciliation failed")
    result = summary(manifest, "reconciled")
    if archived_orphans:
        result["onlineDeliveryReceipts"] = (
            manifest["tables"]["alert_delivery_receipts"]["count"] - manifest["orphanArchive"]["count"]
        )
    return result


def apply(url, bundle, *, maintenance=False, archive_orphan_receipts=False, fault=None):
    if not maintenance:
        raise MigrationError("stop all writers and acknowledge --maintenance before applying")
    bundle = Path(bundle)
    manifest = verify_bundle(bundle)
    if manifest["format"] != 2:
        raise MigrationError("legacy evidence-only bundle is not eligible for apply; prepare a new backup")
    archive = manifest.get("orphanArchive")
    allowed = archive_orphan_receipts and archive and archive["count"] > 0
    blockers = manifest.get("blockers", [])
    if blockers and not (allowed and blockers == [{"code": "orphan_delivery_receipts", "count": archive["count"]}]):
        raise MigrationError("preflight blockers remain; resolve source data explicitly and prepare a new backup")
    bundle_id = digest((bundle / "manifest.json").read_bytes())
    restored_path = bundle / "restore-verification.json"
    if not restored_path.is_file() or json.loads(restored_path.read_text(encoding="utf-8")).get("bundleId") != bundle_id:
        raise MigrationError("first restore this bundle to a separate empty destination and verify it")
    with database_connection(url, write=True) as connection:
        if identity(connection) != manifest["source"]:
            raise MigrationError("backup belongs to another source database/schema")
        metadata, revision = schema(connection)
        if connection.dialect.name == "postgresql" and metadata.tables:
            for table in metadata.sorted_tables:
                connection.execute(sa.text(f'LOCK TABLE "{table.name}" IN ACCESS EXCLUSIVE MODE'))
        if revision in UPGRADED_REVISIONS:
            receipt = connection.scalar(sa.text(
                "SELECT COUNT(*) FROM platform_audit_events WHERE action='migration.default_project' AND target_id=:id"),
                {"id": bundle_id})
            if receipt:
                return summary(manifest, "already-applied")
            raise MigrationError("target revision lacks this migration receipt; manual review required")
        if revision != manifest["revision"] or schema_signature(connection) != manifest["schema"]:
            raise MigrationError("source schema changed since backup")
        for name, table in metadata.tables.items():
            if fingerprint(connection, table) != manifest["tables"][name]:
                raise MigrationError("source data changed since backup; prepare a new bundle")
        atomic_json(bundle / "checkpoint.json", {"phase": "applying", "bundleId": bundle_id})
        if allowed:
            checksum, count = hashlib.sha256(), 0
            with closing(connection.execute(orphan_query(metadata).execution_options(yield_per=100)).mappings()) as current_orphans:
                for row in current_orphans:
                    checksum.update((canonical(encode_row(row)) + "\n").encode())
                    count += 1
            if count != archive["count"] or checksum.hexdigest() != archive["sha256"]:
                raise MigrationError("orphan candidates changed since backup")
            receipts = metadata.tables["alert_delivery_receipts"]
            events = metadata.tables["alert_events"]
            deleted = connection.execute(receipts.delete().where(~sa.exists(sa.select(1).where(
                events.c.event_id == receipts.c.event_id)))).rowcount
            if deleted != count:
                raise MigrationError("orphan archive count reconciliation failed")
            if fault:
                fault("after-archive")
        command.upgrade(config(connection), TARGET)
        if fault:
            fault("after-schema")
        current, _ = schema(connection)
        assets = Assets(bundle, inventory=manifest["assets"])
        for name in OWNED:
            if name not in manifest["tables"]:
                continue
            table = current.tables[name]
            originals = nonarchived_receipts(bundle, manifest) if allowed and name == "alert_delivery_receipts" else saved_rows(bundle, name)
            for row in originals:
                transformed = assets.transform(name, row)
                if transformed.get("payload") == row.get("payload"):
                    continue
                conditions = [table.c[key.name] == (DEFAULT_PROJECT_ID if key.name == "project_id" else row[key.name])
                              for key in table.primary_key.columns]
                connection.execute(table.update().where(*conditions).values(payload=transformed["payload"]))
        result = reconcile(connection, bundle, manifest, archived_orphans=bool(allowed))
        connection.execute(current.tables["platform_audit_events"].insert().values(
            audit_id=str(uuid5(NAMESPACE, bundle_id)), action="migration.default_project", target_type="migration",
            target_id=bundle_id, change_summary={"sourceRevision": manifest["revision"], "targetRevision": TARGET,
                                                "orphanArchive": archive if allowed else None},
            outcome="SUCCESS"))
        if fault:
            fault("before-commit")
    # The receipt is in the DB transaction: a crash before this file update is retry-safe.
    atomic_json(bundle / "checkpoint.json", {"phase": "completed", "bundleId": bundle_id})
    return result


def restore(url, bundle, *, maintenance=False):
    """Recover to a separate empty destination, preserving the upgraded source."""
    if not maintenance:
        raise MigrationError("acknowledge --maintenance before restoring")
    manifest = verify_bundle(bundle)
    if manifest["format"] != 2:
        raise MigrationError("legacy evidence-only bundle is not eligible for restore; prepare a new backup")
    assets = Assets(bundle, inventory=manifest["assets"])
    with database_connection(url, write=True) as connection:
        if connection.dialect.name != manifest["dialect"]:
            raise MigrationError("restore must use the same database dialect")
        if identity(connection) == manifest["source"]:
            raise MigrationError("in-place restore forbidden; select a separate empty destination")
        if sa.inspect(connection).get_table_names() or sa.inspect(connection).get_view_names():
            raise MigrationError("restore destination must be empty")
        if manifest["revision"]:
            command.upgrade(config(connection), manifest["revision"])
            metadata, _ = schema(connection)
            if schema_signature(connection) != manifest["schema"]:
                raise MigrationError("source schema drift requires native backup/restore review")
            if set(metadata.tables) != set(manifest["tables"]):
                raise MigrationError("backup schema does not match revision")
            for table in metadata.sorted_tables:
                if list(table.c.keys()) != manifest["columns"][table.name]:
                    raise MigrationError("backup columns do not match revision")
                if table.name == "alembic_version":
                    continue
                batch = []
                for row in saved_rows(bundle, table.name):
                    batch.append(decode_row(table, assets.restore_row(table.name, row)))
                    if len(batch) == 100:
                        connection.execute(table.insert(), batch)
                        batch.clear()
                if batch:
                    connection.execute(table.insert(), batch)
                if connection.dialect.name == "postgresql":
                    for column in table.primary_key.columns:
                        if isinstance(column.type, sa.Integer):
                            sequence = connection.scalar(sa.text("SELECT pg_get_serial_sequence(:table, :column)"),
                                                         {"table": table.name, "column": column.name})
                            if sequence:
                                maximum = connection.scalar(sa.select(sa.func.max(column)))
                                captured = manifest["sequences"].get(f"{table.name}.{column.name}", {})
                                value = max(maximum or 1, captured.get("last_value", 1))
                                called = bool(captured.get("is_called")) or (maximum is not None and maximum >= value)
                                connection.execute(sa.text("SELECT setval(CAST(:seq AS regclass), :value, :called)"),
                                                   {"seq": sequence, "value": value, "called": called})
            for name, table in metadata.tables.items():
                expected_hash = hashlib.sha256()
                for row in saved_rows(bundle, name):
                    expected_hash.update((canonical(assets.restore_row(name, row)) + "\n").encode())
                expected = {"count": manifest["tables"][name]["count"], "sha256": expected_hash.hexdigest()}
                if fingerprint(connection, table) != expected:
                    raise MigrationError("restored database differs from backup")
        restored_identity = identity(connection)
    atomic_json(Path(bundle) / "restore-verification.json", {
        "bundleId": digest((Path(bundle) / "manifest.json").read_bytes()),
        "destination": restored_identity, "verifiedAt": datetime.now(timezone.utc).isoformat(),
    })
    return summary(manifest, "restored-to-empty-destination")
