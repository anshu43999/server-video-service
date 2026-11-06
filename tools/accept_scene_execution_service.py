"""M36-T11 real local acceptance, with explicit internal-test publication consent."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys
from urllib.parse import quote, urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.model_signing import canonical_manifest_payload

DEFAULT = "00000000-0000-0000-0000-000000000001"
SECOND = "uploaded-06b4dd2f10544673ab723226f91c34a7"
PUBLIC_KEY = ROOT.parent / "secrets/model-signing/aiyolo-model-ed25519-public.pem"


class Acceptance:
    def __init__(self, destination):
        self.destination = destination
        self.client = httpx.Client(base_url="http://127.0.0.1:8080", timeout=30, follow_redirects=False)
        self.tokens = {}
        self.trace = []

    def headers(self, role):
        return {"Authorization": "Bearer " + self.tokens[role]} if role in self.tokens else {}

    def request(self, role, method, path, body=None, expected=200):
        if not path.startswith("/aiyoloapi/") or urlsplit(path).netloc:
            raise RuntimeError("only local project/API URLs accepted")
        response = self.client.request(method, path, headers=self.headers(role), json=body)
        self.trace.append(dict(role=role, method=method, path=path, status=response.status_code))
        (self.destination / "api-trace.json").write_text(json.dumps(self.trace, indent=2), encoding="utf-8")
        if response.status_code != expected:
            raise RuntimeError(f"unexpected HTTP status {response.status_code} for {method} {path}")
        return response

    def login(self):
        rows = (ROOT.parent / "harness/TEST_ACCOUNTS.md").read_text(encoding="utf-8-sig").splitlines()
        password = next(parts[2] for line in rows if len(parts := [p.strip().strip('`') for p in line.split('|')]) > 3 and parts[1] == "gly")
        for role in ("admin", "gly", "ptcy"):
            self.tokens[role] = self.request(role, "POST", "/aiyoloapi/auth/login",
                dict(username=role, password=password)).json()["accessToken"]

    def default_config(self):
        return {kind: self.request("admin", "GET", f"/aiyoloapi/projects/{DEFAULT}/{kind}").json()
                for kind in ("members", "model-assignments", "scenes")}

    def release(self, model_id, version):
        return self.request("admin", "GET", f"/aiyoloapi/models/{quote(model_id, safe='')}/versions/{version}").json()

    def verify_package(self, model, artifacts=None):
        selected = artifacts if artifacts is not None else model["artifacts"]
        public = serialization.load_pem_public_key(PUBLIC_KEY.read_bytes())
        if not isinstance(public, Ed25519PublicKey):
            raise RuntimeError("expected trusted Ed25519 public key")
        digests, manifest = {}, None
        for artifact in selected:
            if artifact.get("target") != "mobile":
                continue
            url = artifact.get("versionedUrl", artifact["url"]) if artifacts is None else artifact["url"]
            response = self.request("admin" if artifacts is None else "ptcy", "GET", url)
            digest = hashlib.sha256(response.content).hexdigest()
            if digest != artifact["sha256"].lower() or len(response.content) != artifact["sizeBytes"]:
                raise RuntimeError("artifact integrity mismatch")
            digests[artifact["artifactId"]] = dict(sha256=digest, bytes=len(response.content))
            if artifact["artifactId"] == "android-manifest":
                manifest = response.json()
        if set(digests) != {"android-int8", "android-manifest"} or manifest is None:
            raise RuntimeError("incomplete real Android package")
        payload = canonical_manifest_payload(manifest)
        signature = manifest["signature"]
        if signature["algorithm"] != "Ed25519" or signature["keyId"] != "internal-dev-2026-01":
            raise RuntimeError("unexpected signing identity")
        public.verify(base64.b64decode(signature["signatureBase64"], validate=True), payload)
        if hashlib.sha256(payload).hexdigest() != signature["signedPayloadSha256"]:
            raise RuntimeError("signed payload mismatch")
        if manifest["modelId"] != model["modelId"] or manifest["version"] != model["version"]:
            raise RuntimeError("manifest identity mismatch")
        if manifest["modelFile"]["sha256"].lower() != digests["android-int8"]["sha256"]:
            raise RuntimeError("manifest model digest mismatch")
        return dict(artifacts=digests, signatureVerified=True, releaseEligible=manifest["releaseEligible"],
                    license=manifest["license"])

    def close(self):
        for role in list(self.tokens):
            try:
                self.request(role, "POST", "/aiyoloapi/auth/logout")
            finally:
                self.tokens.pop(role, None)
        self.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--confirm-internal-test-license", action="store_true")
    args = parser.parse_args()
    if not args.confirm_internal_test_license or settings.deployment_env != "development":
        raise RuntimeError("explicit internal-test license consent and development environment required")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    projects = fixture["projects"]
    if len(projects) != 2 or len({p["projectId"] for p in projects}) != 2 or any(
            p["projectId"] == DEFAULT or not p["projectCode"].startswith("m104-") for p in projects):
        raise RuntimeError("expected the two existing isolated projects, never Default")
    output = ROOT / "harness/evidence/M36" / ("M36-T11-service-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True)
    result = dict(task="M36-T11", scope="local-internal-functional-testing-only", commercialApproval=False,
        publicationTargets=["mobile"], projects=[p["projectId"] for p in projects], releases=[], scenes=[])
    service = Acceptance(output)
    baseline = None
    try:
        service.login()
        baseline = service.default_config()
        (output / "default-before.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
        original = service.release(fixture["modelId"], fixture["modelVersion"])
        for version in ("2.0.0", "3.0.0"):
            model = service.release(SECOND, version)
            before = service.verify_package(model)
            if not model["targetReadiness"]["mobile"]["ready"]:
                raise RuntimeError("mobile runtime/artifact readiness gate failed")
            if not model["targetReleaseEligible"]["mobile"]:
                model = service.request("admin", "POST", f"/aiyoloapi/models/{SECOND}/versions/{version}/publish",
                    dict(targets=["mobile"], licenseApproved=True,
                         reason="2026-10-20 user confirmed internal test use/distribution authorization ONLY; M104 isolated acceptance; no commercial or production distribution approval")).json()
            after = service.verify_package(model)
            if model["status"] != "PUBLISHED" or not model["targetReleaseEligible"]["mobile"] or not after["releaseEligible"]:
                raise RuntimeError("publication not effective")
            if model["targetReleaseEligible"]["pc"]:
                raise RuntimeError("unexpected PC publication")
            if before["artifacts"]["android-int8"] != after["artifacts"]["android-int8"]:
                raise RuntimeError("publication modified model weights")
            result["releases"].append(dict(modelId=SECOND, version=version, before=before, after=after,
                targetReleaseEligible=model["targetReleaseEligible"]))
        for project in projects:
            base = "/aiyoloapi/projects/" + project["projectId"]
            current = service.request("admin", "GET", base).json()
            if current["projectCode"] != project["projectCode"]:
                raise RuntimeError("test project identity changed")
            expected = [("m104-image", ["image"], [dict(modelId=fixture["modelId"], version=fixture["modelVersion"], target="mobile", position=0, execution="single")]),
                        ("m104-video", ["video"], [dict(modelId=fixture["modelId"], version=fixture["modelVersion"], target="mobile", position=0, execution="single")]),
                        ("m104-multi", ["image", "video"], [dict(modelId=fixture["modelId"], version=fixture["modelVersion"], target="mobile", position=0, execution="sync"),
                            dict(modelId=SECOND, version="2.0.0", target="mobile", position=1, execution="async")]),
                        ("m104-versioned", ["image", "video"], [dict(modelId=SECOND, version="2.0.0", target="mobile", position=0, execution="single")])]
            for scene_id, inputs, members in expected:
                rows = service.request("gly", "GET", base + "/scenes").json()["scenes"]
                scene = next((s for s in rows if s["sceneId"] == scene_id), None)
                if scene is None:
                    scene = service.request("gly", "POST", base + "/scenes", dict(sceneId=scene_id,
                        name="M104 " + scene_id, inputTypes=inputs, models=members, enabled=True, expectedRevision=0), expected=201).json()
                identities = [{k: m[k] for k in ("modelId", "version", "target", "position", "execution")} for m in scene["models"]]
                if identities != members or scene["inputTypes"] != inputs:
                    raise RuntimeError("existing isolated scene differs; refusing overwrite")
                if not scene["approved"] or any(not m.get("parameterSnapshot") for m in scene["models"]):
                    scene = service.request("gly", "POST", base + f"/scenes/{scene_id}/approval", dict(approved=True,
                        expectedRevision=scene["revision"], reason="M104 explicit isolated scene Android parameter review")).json()
                scene = service.request("ptcy", "GET", base + f"/scenes/{scene_id}?target=mobile").json()
                service.request("ptcy", "POST", base + f"/scenes/{scene_id}/approval", dict(approved=True,
                    expectedRevision=scene["revision"], reason="negative role test"), expected=403)
                multi = len(members) > 1
                resolved = service.request("ptcy", "POST", base + f"/scenes/{scene_id}/resolve", dict(
                    expectedRevision=scene["revision"], target="mobile", inputType=inputs[0]), expected=409 if multi else 200).json()
                if multi and resolved.get("detail", {}).get("code") != "execution_mode_not_supported":
                    raise RuntimeError("multi-model execution was not explicitly rejected")
                for member in scene["models"]:
                    profile = service.request("ptcy", "GET", member["parameterUrl"]).json()
                    if (profile["projectId"], profile["sceneId"], profile["sceneRevision"], profile["modelId"], profile["modelVersion"], profile["platform"]) != (
                            project["projectId"], scene_id, scene["revision"], member["modelId"], member["version"], "android"):
                        raise RuntimeError("parameter identity mismatch")
                    service.verify_package(member["executionModel"], member["executionModel"]["artifacts"])
                result["scenes"].append(dict(projectId=project["projectId"], sceneId=scene_id,
                    revision=scene["revision"], models=len(members), multiExecutionRejected=multi,
                    exactParametersAndSignedDownloads=True))
        unchanged = service.default_config() == baseline
        if not unchanged or service.release(fixture["modelId"], fixture["modelVersion"])["artifacts"] != original["artifacts"]:
            raise RuntimeError("Default configuration or original release changed")
        result.update(result="passed", defaultConfigurationUnchanged=True, originalReleaseUnchanged=True)
    except Exception as error:
        result.update(result="failed", errorType=type(error).__name__, error=str(error))
        raise
    finally:
        try:
            if baseline is not None:
                result["defaultConfigurationUnchanged"] = service.default_config() == baseline
        finally:
            try:
                service.close()
            finally:
                (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(dict(evidence=str(output), result=result.get("result"),
                    publishedVersions=len(result["releases"]), reviewedScenes=len(result["scenes"]),
                    defaultConfigurationUnchanged=result.get("defaultConfigurationUnchanged")), ensure_ascii=False))


if __name__ == "__main__":
    main()
