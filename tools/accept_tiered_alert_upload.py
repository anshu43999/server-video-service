"""M37-T07: real loopback HTTP + migrated remote PostgreSQL + remote MinIO.

Never resets global stores or modifies the configured business schema. All remote
objects are under a freshly generated prefix; exact created keys are cleaned up.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import httpx
from PIL import Image
from sqlalchemy import func, select
from app.alert_evidence import AlertEvidenceStore
from app.alerts.disposition import AlertDispositionStore
from app.alerts.evidence_retention import cleanup_alert_evidence
from app.config import settings
from app.database import (AlertEventRecord, AlertDispositionActionRecord, DatabaseManager,
                          ProjectRecord, ProjectMembershipRecord)
from postgresql_support import isolated_postgresql_url


def sha(content):
    return hashlib.sha256(content).hexdigest()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def image(width, height):
    pixels = bytes(channel for y in range(height) for x in range(width)
                   for channel in ((x * 17 + y * 3) % 256, (y * 11) % 256, (x + y) % 256))
    out = BytesIO()
    Image.frombytes("RGB", (width, height), pixels).save(out, "JPEG", quality=80)
    return out.getvalue()


def cost_baseline():
    events, retry, shifts = 1000, 1.02, 250
    primary, thumb, original, fraction = 300 * 1024, 48 * 1024, 5 * 1024**2, 0.1
    # Two explicit legacy bounds avoid conflating the 300 KiB primary and 5 MiB L4 cap.
    result = {"assumptions": {"eventsPerShift": events, "shiftHours": 8,
        "shiftsPerYear": shifts, "shiftsPerDayForStorage": 1, "thumbnailBytes": thumb,
        "compressedPrimaryBytes": primary, "l4MaximumBytes": original,
        "l4Fraction": fraction, "transientFullBodyRetryRate": 0.02,
        "localCompletedDays": 7, "localPendingMaximumDays": 30, "serverDays": 90},
        "scope": "Image payload bytes only; measured HTTP/JSON/multipart bytes and latency reported separately."}
    for label, old, l4 in (("compressed-primary", primary, primary), ("maximum-original", original, original)):
        new = thumb + fraction * l4
        result[label] = {"legacyImageBytesPerShift": events * old * retry,
            "tieredImageBytesPerShift": events * new * retry,
            "legacyImageBytesPerYear": events * old * retry * shifts,
            "tieredImageBytesPerYear": events * new * retry * shifts,
            "savingFraction": 1 - new / old,
            "legacyRemoteBytesAt90Days": events * old * 90,
            "tieredRemoteBytesAt90Days": events * new * 90,
            "tieredObjectBytesDaysPerShift": events * new * 90}
    result["local"] = {"completedBytes7Days": events * (primary + thumb) * 7,
        "allPendingBytesAt30DayEscalation": events * (primary + thumb) * 30,
        "note": "No automatic purge of pending media; legacy local retention was ineffective, so no finite measured legacy bound is claimed."}
    return result


def run_android(output, port, account_id, token, project_id, database):
    """Opt-in API27 counterpart. Never installs/clears/force-stops the formal app."""
    adb = r"D:\Users\45393\Android\sdk\platform-tools\adb.exe"
    package = "com.aiyolo.inspection.regressionprobe"
    target = [adb, "-s", "emulator-5554"]

    def command(*args, timeout=180):
        done = subprocess.run([*target, *args], capture_output=True, timeout=timeout,
                              cwd=ROOT.parent / "mobile-app")
        check(done.returncode == 0, "adb command failed (no credentials emitted)")
        return done.stdout.decode("utf-8", errors="replace")

    check(command("shell", "getprop", "ro.build.version.sdk").strip() == "27", "API27 required")
    check("package:" in command("shell", "pm", "path", package), "isolated product APK must be installed first")
    reverse = f"tcp:{port}"
    try:
        for phase in ("seed", "offline", "recover", "revoked", "resumed"):
            command("shell", "am", "force-stop", package)
            if phase == "offline":
                command("reverse", "--remove", reverse)
            elif phase in {"seed", "recover"}:
                command("reverse", reverse, reverse)
            if phase in {"revoked", "resumed"}:
                with database.session() as session:
                    session.get(ProjectMembershipRecord, (project_id, account_id)).enabled = phase == "resumed"
            # This token exists only in this disposable schema. It is never written to evidence/logs.
            text = command("shell", "am", "instrument", "-w", "-r", "-e", "class",
                "com.aiyolo.inspection.events.RealTieredUploadInstrumentedTest",
                "-e", "tieredPhase", phase, "-e", "tieredOrigin", f"http://127.0.0.1:{port}",
                "-e", "tieredAccount", account_id, "-e", "tieredProject", project_id,
                "-e", "tieredToken", token,
                package + ".test/androidx.test.runner.AndroidJUnitRunner")
            text = text.replace(token, "<redacted>")
            (output / f"android-{phase}.txt").write_text(text, encoding="utf-8")
            report = command("exec-out", "run-as", package, "cat", "files/m105-tiered-report.json")
            check(token not in report, "Android report must not expose credentials")
            (output / "android-report.json").write_text(report, encoding="utf-8")
            check("OK (1 test)" in text and "FAILURES!!!" not in text,
                  f"API27 {phase} failed; inspect android-{phase}.txt")
        report = command("exec-out", "run-as", package, "cat", "files/m105-tiered-report.json")
        check(token not in report, "Android report must not expose credentials")
        result = json.loads(report)
        (output / "android-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        subprocess.run([*target, "reverse", "--remove", reverse], capture_output=True, timeout=15,
                       cwd=ROOT.parent / "mobile-app")
        command("shell", "am", "force-stop", package)


class CommittedResponseDrop(BaseHTTPRequestHandler):
    """Fault injection on the wire AFTER the real service has committed."""
    upstream = ""

    def do_PUT(self):
        content = self.rfile.read(int(self.headers["Content-Length"]))
        with httpx.Client(trust_env=False, timeout=30) as upstream:
            response = upstream.put(self.upstream + self.path, content=content,
                headers={k: v for k, v in self.headers.items()
                         if k.lower() not in {"host", "connection", "content-length"}})
            self.server.committed_status = response.status_code
        self.close_connection = True

    def log_message(self, *args):
        pass


def run(output: Path, *, android: bool = False):
    output.mkdir(parents=True, exist_ok=False)
    golden_path = ROOT / "docs/mobile-alert-tiered-upload-v1-golden.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    run_id = uuid.uuid4().hex
    prefix = f"alerts/acceptance-m37/{run_id}"
    store = AlertEvidenceStore(endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket, secure=settings.minio_secure, region=settings.minio_region,
        prefix=prefix, auto_create_bucket=False)
    check(store.enabled, "real configured MinIO is required")
    store.validate()
    check(not list(store._client.list_objects(store.bucket, prefix=prefix + "/", recursive=True)),
          "fresh acceptance object prefix must be empty")
    trace, checks = [], []
    result = {"runId": run_id, "contractSha256": sha((ROOT / "docs/mobile-alert-tiered-upload-v1.md").read_bytes()),
        "goldenSha256": sha(golden_path.read_bytes()), "projectId": golden["projectId"],
        "eventId": golden["eventId"], "intelligentVerification": "excluded-by-user",
        "transport": "real TCP HTTP / remote PostgreSQL / remote MinIO", "trace": trace,
        "checks": checks, "cost": cost_baseline(), "status": "running"}
    started = time.time()
    try:
        with isolated_postgresql_url("m37_acceptance") as database_url, \
             tempfile.TemporaryDirectory(prefix="m37-acceptance-") as runtime:
            database = DatabaseManager(database_url)
            process = None
            log = (output / "worker.log").open("w", encoding="utf-8")
            with socket.socket() as available:
                available.bind(("127.0.0.1", 0))
                port = available.getsockname()[1]
            env = os.environ.copy()
            env.update(DATABASE_URL=database_url, TIERED_ACCEPTANCE_RUNTIME=runtime,
                TIERED_ACCEPTANCE_PORT=str(port), MINIO_ENDPOINT=settings.minio_endpoint,
                MINIO_ACCESS_KEY=settings.minio_access_key, MINIO_SECRET_KEY=settings.minio_secret_key,
                MINIO_BUCKET=settings.minio_bucket, MINIO_SECURE=str(settings.minio_secure).lower(),
                MINIO_ALERT_PREFIX=prefix, MINIO_AUTO_CREATE_BUCKET="false")
            if settings.minio_region:
                env["MINIO_REGION"] = settings.minio_region
            client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=40, trust_env=False)
            try:
                process = subprocess.Popen([sys.executable, str(ROOT / "tools/tiered_acceptance_worker.py")],
                    cwd=runtime, env=env, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for _ in range(100):
                    check(process.poll() is None, "worker stopped; inspect worker.log")
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.2)
                else:
                    raise AssertionError("isolated service readiness deadline exceeded")
                password = uuid.uuid4().hex
                admin = client.post("/aiyoloapi/auth/setup", json={"username": "acceptance-admin", "password": password})
                check(admin.status_code == 200, "isolated auth setup failed")
                admin_headers = {"Authorization": "Bearer " + admin.json()["accessToken"]}
                member = client.post("/aiyoloapi/auth/users", headers=admin_headers,
                    json={"username": "acceptance-member", "password": password, "role": "operator"})
                check(member.status_code == 200, "isolated member setup failed")
                account_id = member.json()["accountId"]
                project_id = golden["projectId"]
                with database.session() as session:
                    session.add(ProjectRecord(project_id=project_id, project_code="project-golden-a",
                                              display_name="Tiered upload acceptance", lifecycle_state="ACTIVE"))
                    session.flush()
                    session.add(ProjectMembershipRecord(project_id=project_id, account_id=account_id,
                                                        project_role="PROJECT_OWNER", enabled=True))
                login = client.post("/aiyoloapi/auth/login", json={"username": "acceptance-member", "password": password})
                check(login.status_code == 200, "isolated member login failed")
                headers = {"Authorization": "Bearer " + login.json()["accessToken"], "X-Mobile-Alert-Contract": "1.0"}
                client.cookies.clear()

                def request(name, method, path, expected, error_code=None, **kwargs):
                    begun = time.perf_counter()
                    response = client.request(method, path, headers={**headers, **kwargs.pop("headers", {})}, **kwargs)
                    trace.append({"name": name, "method": method, "path": path,
                        "httpStatus": response.status_code, "expectedStatus": expected,
                        "requestBodyBytes": len(response.request.read()), "responseBodyBytes": len(response.content),
                        "durationMs": round((time.perf_counter() - begun) * 1000, 3),
                        "requestSha256": sha(response.request.content), "responseSha256": sha(response.content)})
                    check(response.status_code == expected,
                          f"{name}: expected HTTP {expected}, observed {response.status_code}")
                    if error_code:
                        check(response.json().get("detail", {}).get("code") == error_code,
                              f"{name}: unexpected error code")
                    checks.append(name)
                    return response

                fact = deepcopy(golden["requests"][0]["body"])
                base = f"/aiyoloapi/projects/{project_id}"
                path = base + "/alerts/" + quote(fact["eventId"], safe="")
                first = request("fact-first", "POST", base + "/alerts/mobile-ingest", 202, json=fact)
                check(first.json()["created"] and first.json()["event"]["disposition"]["status"] == "OPEN", "L1 must create OPEN")
                replay = request("fact-exact-replay", "POST", base + "/alerts/mobile-ingest", 202, json=fact)
                check(not replay.json()["created"], "fact replay duplicated event")
                for key, value in (("sourceId", "different-source"), ("ruleId", "different-rule"),
                                   ("subjectKey", "different-subject"), ("startedAtUs", fact["startedAtUs"] - 1)):
                    request("identity-conflict-" + key, "POST", base + "/alerts/mobile-ingest", 409,
                            error_code="event_identity_conflict", json={**fact, key: value})
                delta = golden["requests"][2]["body"]
                operation = {"Idempotency-Key": delta["operationId"]}
                late = golden["requests"][3]
                request("disposition-before-fact", "PUT", late["path"], 409,
                        headers=operation, json=late["body"])
                disposition = request("disposition-false-positive", "PUT", path + "/disposition", 200,
                                      headers=operation, json=delta)
                check(disposition.json()["disposition"]["actor"] == account_id, "actor must come from session")
                request("disposition-replay", "PUT", path + "/disposition", 200, headers=operation, json=delta)
                request("disposition-conflict", "PUT", path + "/disposition", 409,
                        headers=operation, json={**delta, "actedAtUs": delta["actedAtUs"] + 1})
                again = request("fact-after-disposition", "POST", base + "/alerts/mobile-ingest", 202, json=fact)
                check(again.json()["event"]["disposition"]["status"] == "FALSE_POSITIVE", "L1 replay reset disposition")

                fixtures = {"thumbnail": image(320, 180), "original": image(1280, 720)}
                manifest = {}
                for kind, content in fixtures.items():
                    (output / f"{kind}.jpg").write_bytes(content)
                    manifest[kind] = {"sha256": sha(content), "byteLength": len(content),
                        "width": 320 if kind == "thumbnail" else 1280, "height": 180 if kind == "thumbnail" else 720,
                        "goldenSha256Placeholder": golden["requests"][4 if kind == "thumbnail" else 5]["multipart"]["sha256"]}
                    upload_headers = {"Idempotency-Key": golden["operationIds"][kind]}
                    form = {"evidenceType": kind, "contentVersion": "1", "sha256": sha(content)}
                    uploaded = request(kind + "-upload", "POST", path + "/evidence", 201,
                        headers=upload_headers, data=form, files={"file": (kind + ".jpg", content, "image/jpeg")})
                    duplicated = request(kind + "-replay", "POST", path + "/evidence", 200,
                        headers=upload_headers, data=form, files={"file": (kind + ".jpg", content, "image/jpeg")})
                    check(uploaded.json() == duplicated.json(), "evidence replay changed reference")
                    uri = uploaded.json()["evidence"]["uri"]
                    read = request(kind + "-read", "GET", uri, 200)
                    check(read.content == content, "remote evidence bytes differ")
                    changed = content + b"different"
                    request(kind + "-conflict", "POST", path + "/evidence", 409, headers=upload_headers,
                        data={**form, "sha256": sha(changed)}, files={"file": (kind + ".jpg", changed, "image/jpeg")})
                result["materializedFixtures"] = manifest
                request("bad-image-signature", "POST", path + "/evidence", 415,
                    error_code="unsupported_media_type",
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                    data={"evidenceType": "original", "contentVersion": "2", "sha256": sha(b"invalid")},
                    files={"file": ("bad.jpg", b"invalid", "image/jpeg")})
                for name, data, expected, code in (
                    ("oversize-original", b"\xff\xd8\xff" + bytes(5 * 1024**2), 413, "evidence_too_large"),
                    ("digest-mismatch", fixtures["original"], 422, "digest_mismatch")):
                    request(name, "POST", path + "/evidence", expected, error_code=code,
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                        data={"evidenceType": "original", "contentVersion": "2", "sha256": "0" * 64},
                        files={"file": ("original.jpg", data, "image/jpeg")})
                request("evidence-before-fact", "POST", base + "/alerts/local:missing/evidence", 404,
                    error_code="event_not_found", headers={"Idempotency-Key": str(uuid.uuid4())},
                    data={"evidenceType": "thumbnail", "contentVersion": "1", "sha256": sha(fixtures["thumbnail"])},
                    files={"file": ("thumbnail.jpg", fixtures["thumbnail"], "image/jpeg")})
                request("fact-preserves-uploaded-evidence", "POST", base + "/alerts/mobile-ingest", 202, json=fact)
                request("cross-project-invisible", "GET",
                        path.replace(project_id, "project-not-authorized") + "/evidence/thumbnail/1", 404,
                        error_code="project_not_found")
                request("v1-rejects-inline-image", "POST", base + "/alerts/mobile-ingest", 422,
                    json={**fact, "eventId": "local:rejected-inline", "evidence": {"snapshotDataUrl": "data:image/png;base64,AAAA"}})
                with database.session() as session:
                    membership = session.get(ProjectMembershipRecord, (project_id, account_id))
                    membership.enabled = False
                request("revoked-fact", "POST", base + "/alerts/mobile-ingest", 404, json=fact)
                request("revoked-evidence-read", "GET", path + "/evidence/thumbnail/1", 404)
                with database.session() as session:
                    session.get(ProjectMembershipRecord, (project_id, account_id)).enabled = True
                request("restored-evidence-read", "GET", path + "/evidence/thumbnail/1", 200)

                # Finish the delayed event from the frozen out-of-order vector.
                late_fact = {**fact, "eventId": "local:camera-late:1790000000400000", "sourceId": "camera-late",
                    "startedAtUs": 1790000000400000, "confirmedAtUs": 1790000000400000,
                    "lastSeenAtUs": 1790000000400000}
                request("delayed-fact-arrives", "POST", base + "/alerts/mobile-ingest", 202, json=late_fact)

                # A second TCP hop discards a real committed response, then replay settles it.
                CommittedResponseDrop.upstream = str(client.base_url).rstrip("/")
                proxy = ThreadingHTTPServer(("127.0.0.1", 0), CommittedResponseDrop)
                thread = threading.Thread(target=proxy.serve_forever, daemon=True)
                thread.start()
                try:
                    try:
                        with httpx.Client(trust_env=False, timeout=30) as wire:
                            wire.put(f"http://127.0.0.1:{proxy.server_port}" + late["path"],
                                     headers={**headers, **operation}, json=late["body"])
                    except httpx.RemoteProtocolError:
                        check(proxy.committed_status == 200, "response fault must occur after successful service commit")
                    else:
                        raise AssertionError("wire fault did not discard the response")
                    request("committed-response-timeout-replay", "PUT", late["path"], 200,
                            headers=operation, json=late["body"])
                finally:
                    proxy.shutdown()
                    proxy.server_close()
                    thread.join(timeout=5)
                with database.session() as session:
                    rows = session.scalars(select(AlertEventRecord).where(AlertEventRecord.project_id == project_id)).all()
                    count = session.scalar(select(func.count()).select_from(AlertDispositionActionRecord).where(
                        AlertDispositionActionRecord.project_id == project_id))
                    check(len(rows) == 2 and count == 2, "HTTP replays/ordering created duplicates or orphan rows")
                    payload = deepcopy(next(row.payload for row in rows if row.event_id == fact["eventId"]))
                    check("base64" not in json.dumps(payload), "new v1 metadata persisted image bytes")
                result["databaseSnapshot"] = {"eventCount": len(rows), "actionCount": count, "event": payload}
                objects = list(store._client.list_objects(store.bucket, prefix=prefix + "/", recursive=True))
                check(len(objects) == 2, "replays/errors created extra MinIO objects")
                result["minioSnapshot"] = []
                for kind, content in fixtures.items():
                    ref = payload["evidence"][kind]["1"]
                    obj = ref["objectStorage"]
                    stat = store._client.stat_object(store.bucket, obj["objectKey"])
                    check(stat.size == obj["sizeBytes"] == ref["byteLength"] == len(content), "DB/MinIO byte length mismatch")
                    check(obj["sha256"] == ref["sha256"] == sha(content), "DB/MinIO reference digest mismatch")
                    body = store.read_tiered(ref, project_id, fact["eventId"], kind, 1).content
                    check(sha(body) == sha(content), "MinIO stored bytes digest mismatch")
                    result["minioSnapshot"].append({"type": kind, "objectKey": obj["objectKey"],
                        "sha256": sha(body), "byteLength": stat.size, "etag": stat.etag})
                image_fact = {**fact, "eventId": "local:image-golden:1790000000000000",
                              "origin": "MOBILE_IMAGE", "sourceId": "image:golden"}
                request("open-image-fact", "POST", base + "/alerts/mobile-ingest", 202, json=image_fact)
                dashboard = request("dashboard-source-denominators", "GET", base + "/dashboard/stats?range=today", 200).json()
                check(dashboard["summary"]["totalEvents"] == 3 and dashboard["summary"]["handledEvents"] == 2,
                      "dashboard must count OPEN facts in denominator")
                check(dashboard["sources"]["MOBILE_IMAGE"]["openEvents"] == 1
                      and dashboard["sources"]["MOBILE_CAMERA"]["handledEvents"] == 2, "source groups differ")
                result["dashboardSnapshot"] = {key: dashboard[key] for key in ("summary", "sources", "dispositions")}
                if android:
                    result["android"] = run_android(output, port, account_id,
                        login.json()["accessToken"], project_id, database)
                    with database.session() as session:
                        result["androidDatabaseSnapshot"] = [
                            {"eventId": row.event_id, "payload": deepcopy(row.payload)}
                            for row in session.scalars(select(AlertEventRecord).where(
                                AlertEventRecord.project_id == project_id)).all()]
                        action_count = session.scalar(select(func.count()).select_from(AlertDispositionActionRecord).where(
                            AlertDispositionActionRecord.project_id == project_id))
                        check(action_count == 2, "Android retry added duplicate server actions")
                    reconciled = []
                    snapshot = result["android"]["phases"][-1]["snapshot"]
                    for queued in snapshot["evidence"]:
                        check(queued["state"] == "SYNCED", "Android evidence lane is incomplete")
                        remote_event = next(row["payload"] for row in result["androidDatabaseSnapshot"]
                                            if row["eventId"] == queued["eventId"])
                        version = queued["uri"].rsplit("/", 1)[1]
                        ref = remote_event["evidence"][queued["type"]][version]
                        content = store.read_tiered(ref, project_id, queued["eventId"], queued["type"], int(version)).content
                        check(queued["sha256"] == ref["sha256"] == sha(content), "Room/DB/MinIO digest mismatch")
                        check(queued["byteLength"] == ref["byteLength"] == len(content), "Room/DB/MinIO length mismatch")
                        reconciled.append({"type": queued["type"], "contentVersion": int(version),
                            "sha256": sha(content), "byteLength": len(content), "objectKey": ref["objectStorage"]["objectKey"]})
                    check(len(list(store._client.list_objects(store.bucket, prefix=prefix + "/", recursive=True)))
                          == len(reconciled) == 3, "Android retries created extra or missing MinIO objects")
                    result["androidReconciliation"] = {"actionCount": action_count, "objects": reconciled}
                now = datetime.now(timezone.utc)
                with database.session() as session:
                    row = session.get(AlertEventRecord, (project_id, fact["eventId"]))
                    snapshot = deepcopy(row.payload)
                    for kind in fixtures:
                        snapshot["evidence"][kind]["1"]["uploadedAt"] = (now - timedelta(days=100)).isoformat()
                    snapshot["evidence"]["original"]["1"].update(
                        retentionUntil=(now + timedelta(days=30)).isoformat(), retentionReason="acceptance-authorized-sample")
                    row.payload = snapshot
                dry = cleanup_alert_evidence(database, store, now=now)
                marked = cleanup_alert_evidence(database, store, now=now, apply=True)
                removed = cleanup_alert_evidence(database, store, now=now + timedelta(hours=25), apply=True)
                check(dry["marked"] == marked["marked"] == removed["deleted"] == 1, "retention mark/grace/remove mismatch")
                request("expired-thumbnail-gone", "GET", path + "/evidence/thumbnail/1", 404)
                request("explicit-retained-original", "GET", path + "/evidence/original/1", 200)
                check(cleanup_alert_evidence(database, store, now=now + timedelta(hours=25), apply=True)["deleted"] == 0,
                      "cleanup must be idempotent")
                result["retention"] = {"dryRun": dry, "marked": marked, "removed": removed}
                result["status"] = "passed"
            finally:
                client.close()
                if process is not None:
                    try:
                        if process.poll() is None:
                            process.stdin.write(b"stop\n")
                            process.stdin.flush()
                        process.wait(timeout=20)
                    except (subprocess.TimeoutExpired, BrokenPipeError):
                        process.kill()
                        process.wait(timeout=5)
                    finally:
                        process.stdin.close()
                log.close()
                database.close()
    except Exception as exc:
        result["status"] = "failed"
        result["failure"] = {"type": type(exc).__name__, "message": str(exc) if isinstance(exc, AssertionError) else "See worker.log and rerun with diagnostics; connection secrets are not emitted."}
        raise
    finally:
        owned = list(store._client.list_objects(store.bucket, prefix=prefix + "/", recursive=True))
        for obj in owned:
            check(obj.object_name.startswith(prefix + "/"), "cleanup escaped unique test prefix")
            store._client.remove_object(store.bucket, obj.object_name)
        result["cleanup"] = {"uniquePrefix": prefix, "testObjectsRemoved": len(owned),
            "remaining": len(list(store._client.list_objects(store.bucket, prefix=prefix + "/", recursive=True)))}
        result["durationSeconds"] = round(time.time() - started, 3)
        durations = sorted(row["durationMs"] for row in trace)
        if durations:
            result["latencyMs"] = {"p50": durations[len(durations)//2], "p95": durations[min(len(durations)-1, int(len(durations)*0.95))]}
            result["trafficBytes"] = {"requestBodies": sum(row["requestBodyBytes"] for row in trace),
                                      "responseBodies": sum(row["responseBodyBytes"] for row in trace),
                                      "includesNegativeAndReplayVectors": True}
            result["requestCount"] = len(trace)
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(checks), "evidence": str(output / "result.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--android", action="store_true", help="Run prebuilt isolated API27 test APK against this real service")
    args = parser.parse_args()
    run(args.output.resolve(), android=args.android)
