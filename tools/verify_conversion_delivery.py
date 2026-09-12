"""Verify an already completed local conversion through real HTTP/WS APIs."""
import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from websockets.sync.client import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8094")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("This local verification helper only targets localhost")
    headers = {"X-Admin-Token": os.environ["VERIFY_ADMIN_TOKEN"]} if os.environ.get("VERIFY_ADMIN_TOKEN") else {}
    mobile = {"X-Video-Service-Token": os.environ["VERIFY_MOBILE_TOKEN"]} if os.environ.get("VERIFY_MOBILE_TOKEN") else {}
    report = {"at": datetime.now(timezone.utc).isoformat(), "model_id": args.model_id, "job_id": args.job_id}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=60) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        job = request("GET", f"/api/conversion/jobs/{args.job_id}").json()
        assert job["status"] == "succeeded", job.get("error")
        model = request("GET", f"/api/models/{args.model_id}").json()
        assert model["serverReady"] and model["androidReady"]
        report.update(version=model["version"], labels=len(model["labels"]),
                      conversion_seconds=round(job["updated_at"] - job["created_at"], 2), artifacts=[])
        for artifact in model["artifacts"]:
            data = request("GET", artifact["url"]).content
            digest = hashlib.sha256(data).hexdigest()
            assert len(data) == artifact["sizeBytes"] and digest.lower() == artifact["sha256"].lower()
            report["artifacts"].append({"id": artifact["artifactId"], "bytes": len(data), "sha256": digest})
        stream_id = "m26-verify-" + uuid.uuid4().hex[:10]
        request("POST", "/api/streams", json={"stream_id": stream_id})
        try:
            bound = request("PUT", f"/api/streams/{stream_id}/model", json={"model_id": args.model_id}).json()
            assert bound["model"]["modelId"] == args.model_id
            request("POST", f"/api/streams/{stream_id}/yolo", json={"enabled": True})
            assets = Path(sys.prefix) / "Lib" / "site-packages" / "ultralytics" / "assets" / "bus.jpg"
            if not assets.exists():
                import ultralytics
                assets = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
            ws_base = args.base_url.replace("http://", "ws://", 1)
            with connect(f"{ws_base}/api/streams/{stream_id}/detections", additional_headers=mobile) as results:
                with connect(f"{ws_base}/api/streams/{stream_id}/ingest", additional_headers=mobile) as ingest:
                    ingest.send(assets.read_bytes())
                    envelope = json.loads(results.recv(timeout=45))
            assert envelope.get("detections"), envelope
            report["stream_inference"] = {"bound_model": args.model_id, "result": envelope}
        finally:
            request("DELETE", f"/api/streams/{stream_id}")
    report["result"] = "passed"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "labels": report["labels"], "artifacts": report["artifacts"],
                      "detections": len(report["stream_inference"]["result"]["detections"]), "evidence": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
