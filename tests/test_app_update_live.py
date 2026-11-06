"""M42-T09 real HTTP, production browser, SDK, MinIO and controlled HTTPS."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.app_updates import contract as c
from app.app_updates.api import configured_updates
from app.app_updates.models import AppArtifact, AppArtifactSource, AppAudit, AppUpload
from app.app_updates.signatures import verify_envelope
from app.database import AccountRecord
from app_update_live_support import LiveEnvironment, PASSWORD, ROOT, SCOPE


@unittest.skipUnless(os.environ.get("RUN_APP_UPDATE_LIVE") == "1", "requires isolated live runner")
class AppUpdateLiveTests(unittest.TestCase):
    def test_real_browser_and_service_restart_faults(self):
        evidence=Path(os.environ["APK_TEST_EVIDENCE_ROOT"]); evidence.mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(prefix="app-update-live-",dir=ROOT/".tmp")
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        with LiveEnvironment(root,evidence) as env:
            command=["npm.cmd","run","test:e2e","--","--config","playwright.app-updates-live.config.ts"]
            process_env=os.environ.copy(); process_env.update(APP_UPDATE_LIVE_URL=env.base_url,APP_UPDATE_LIVE_MANIFEST=str(root/"manifest.json"))
            # Keep traces per run, including failed attempts.
            command.extend(["--output",str(evidence/"browser-artifacts")])
            with (evidence/"browser.log").open("w",encoding="utf-8") as output:
                browser=subprocess.run(command,cwd=ROOT/"admin-web",env=process_env,stdout=output,stderr=output,timeout=360)
            self.assertEqual(0,browser.returncode,"see browser.log")
            browser_result=json.loads((evidence/"browser.json").read_text())
            admin=httpx.Client(base_url=env.base_url,timeout=30)
            self.addCleanup(admin.close)
            second=httpx.Client(base_url=env.base_url,timeout=30)
            self.addCleanup(second.close)
            for client,name in ((admin,"t09-admin-a"),(second,"t09-admin-b")):
                self.assertEqual(200,client.post("/aiyoloapi/auth/login",json=dict(username=name,password=PASSWORD)).status_code)
            prefix="/aiyoloapi/admin/app-updates"
            def check(channel,current,installation="device-live"):
                body=(SCOPE|dict(channel=channel,requestId=uuid4().hex,installationId=installation,currentVersionCode=current,
                    currentVersionName=str(current),sdkInt=27,supportedAbis=["arm64-v8a"],signerSha256=env.signer,
                    serverContractVersion=1,lastPolicyRevision=0))
                response=admin.post("/aiyoloapi/mobile/app-updates/check",json=body)
                self.assertEqual(200,response.status_code,response.text)
                expected={k:body[k] for k in c.ClientContext.model_fields}
                publisher=configured_updates(env.db,env.config).publisher
                value=verify_envelope(response.content,trusted_keys={publisher.key_id:publisher.key.public_key()},message_type="check",expected=expected,min_policy_revision=1)
                return body,value
            network=[]
            def download(context,value,version,mode):
                target=value.release
                self.assertEqual(version,target.versionCode)
                body={k:context[k] for k in c.ClientContext.model_fields}|dict(expectedPolicyRevision=value.policyRevision,
                    releaseId=target.releaseId,artifactId=target.artifactId,sourceId=target.sourceId,sourceRevision=target.sourceRevision,
                    sha256=target.sha256,sizeBytes=target.sizeBytes)
                response=admin.post(f"/aiyoloapi/mobile/app-updates/{target.releaseId}/download-ticket",json=body)
                self.assertEqual(200,response.status_code,response.text)
                expected={k:body[k] for k in c.ClientContext.model_fields}|dict(releaseId=target.releaseId,artifactId=target.artifactId,
                    sourceId=target.sourceId,sourceRevision=target.sourceRevision,sha256=target.sha256,sizeBytes=target.sizeBytes,
                    signerSha256=env.signer,versionCode=version)
                publisher=configured_updates(env.db,env.config).publisher
                ticket=verify_envelope(response.content,trusted_keys={publisher.key_id:publisher.key.public_key()},message_type="download",expected=expected,min_policy_revision=value.policyRevision)
                business_before=len(env.http); gateway_before=len(env.gateway_requests); origin_before=len(env.origin_requests)
                data=env.direct_download(ticket.downloadUrl)
                self.assertEqual(target.sha256,hashlib.sha256(data).hexdigest()); self.assertEqual(target.sizeBytes,len(data))
                self.assertEqual(business_before,len(env.http))
                self.assertEqual(gateway_before+(mode=="internal"),len(env.gateway_requests))
                if mode=="internal":
                    self.assertEqual(origin_before,len(env.origin_requests))
                else:
                    self.assertGreater(len(env.origin_requests),origin_before)
                permission=admin.post(f"/aiyoloapi/mobile/app-updates/{target.releaseId}/install-permission",json=body|dict(verifiedVersionCode=version,verifiedSignerSha256=env.signer))
                self.assertEqual(200,permission.status_code,permission.text)
                verify_envelope(permission.content,trusted_keys={publisher.key_id:publisher.key.public_key()},message_type="install_permission",expected=expected,min_policy_revision=value.policyRevision)
                return body
            for channel in ("minio","external"):
                _,value=check(channel,100,"stable-"+channel)
                self.assertEqual("up_to_date",value.result)
                context,value=check(channel,101,channel)
                target=value.release
                self.assertEqual((102,"recovery"),(target.versionCode,target.releasePurpose))
                mode="internal" if channel=="minio" else "external"
                body=download(context,value,102,mode)
                operation=admin.get(prefix+"/rollbacks/"+target.rollbackOperationId).json()
                self.assertNotIn("healthy",operation["deviceCounts"])
                bad_id=browser_result["releases"][channel]["101"]
                rejected=admin.post(f"/aiyoloapi/mobile/app-updates/{bad_id}/download-ticket",json=body|dict(releaseId=bad_id))
                self.assertEqual(410,rejected.status_code,rejected.text)
                network.append(dict(channel=channel,storageMode=mode,version=102,hashMatched=True,directOrigin=True,businessBytesProxied=False,
                    noPrematureHealth=True,stoppedVersionDenied=True))
            # MinIO direct download is a real SigV4 HTTPS GET against the versioned bucket.
            with env.db.session() as session:
                artifact=session.scalar(select(AppArtifact).where(AppArtifact.version_code==100,AppArtifact.state=="verified"))
                source=session.scalar(select(AppArtifactSource).where(AppArtifactSource.artifact_id==artifact.artifact_id,
                    AppArtifactSource.storage_mode=="internal"))
                from app.app_updates.delivery import configured_tickets
                from app.app_updates.service import now
                from datetime import timedelta
                url,_=configured_tickets(env.config)(source,artifact,now(),now()+timedelta(seconds=120))
                before=len(env.http); data=env.direct_download(url)
                self.assertEqual(before,len(env.http)); self.assertEqual(artifact.sha256,hashlib.sha256(data).hexdigest())
            # Two real platform accounts race the same fresh publication; CAS elects one.
            artifact_id=target.artifactId
            scope=SCOPE|dict(channel="concurrency")
            releases={}; sources={}
            for version,mode in ((100,"internal"),(101,"external")):
                with env.db.session() as session:
                    artifact=session.scalar(select(AppArtifact).where(AppArtifact.version_code==version,AppArtifact.state=="verified"))
                    source=session.scalar(select(AppArtifactSource).where(AppArtifactSource.artifact_id==artifact.artifact_id,
                        AppArtifactSource.storage_mode==mode,AppArtifactSource.state=="verified"))
                    sources[version]=(source.source_id,source.source_revision)
                    draft=scope|dict(artifactId=artifact.artifact_id,importance="normal",notes=["T09 concurrent publication"],
                        idempotencyKey="race-draft-"+str(version),reason="T09 create isolated publication")
                response=admin.post(prefix+"/releases",json=draft)
                self.assertEqual(201,response.status_code,response.text)
                releases[version]=response.json()["resourceId"]
            def publish_body(version,key,revision):
                return scope|dict(releaseId=releases[version],sourceId=sources[version][0],sourceRevision=sources[version][1],
                    minSupportedVersionCode=1,restrictedCapabilities=[],expectedPolicyRevision=revision,
                    idempotencyKey=key,reason="T09 real HTTP CAS")
            response=admin.post(prefix+f"/releases/{releases[100]}/publish",json=publish_body(100,"race-stable",1))
            self.assertEqual(200,response.status_code,response.text)
            context,value=check("concurrency",1,"before-update")
            download(context,value,100,"internal")
            commands=[publish_body(101,"race-a",2),publish_body(101,"race-b",2)]
            from threading import Barrier
            barrier=Barrier(2)
            def compete(index):
                barrier.wait(timeout=10)
                return (admin,second)[index].post(prefix+f"/releases/{releases[101]}/publish",json=commands[index])
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses=list(pool.map(compete,(0,1)))
            self.assertEqual([200,409],sorted(r.status_code for r in responses))
            winner=next(i for i,r in enumerate(responses) if r.status_code==200)
            self.assertEqual("policy_revision_conflict",responses[1-winner].json()["code"])
            replay=(admin,second)[winner].post(prefix+f"/releases/{releases[101]}/publish",json=commands[winner])
            self.assertEqual(200,replay.status_code,replay.text)
            self.assertEqual(responses[winner].json(),replay.json())
            with env.db.session() as session:
                audits=session.scalars(select(AppAudit).where(AppAudit.resource_id==releases[101],
                    AppAudit.action=="app_release_publish",AppAudit.result=="succeeded")).all()
                self.assertEqual(1,len(audits))
                self.assertEqual((2,3),(audits[0].before_revision,audits[0].after_revision))
            context,value=check("concurrency",100,"after-update")
            download(context,value,101,"external")
            stop=scope|dict(releaseId=releases[101],expectedPolicyRevision=3,idempotencyKey="race-stop",reason="T09 stop after download")
            response=second.post(prefix+f"/releases/{releases[101]}/stop",json=stop)
            self.assertEqual(200,response.status_code,response.text)
            self.assertEqual(response.json(),second.post(prefix+f"/releases/{releases[101]}/stop",json=stop).json())
            _,value=check("concurrency",100,"after-stop")
            self.assertEqual("up_to_date",value.result)
            for code in (403,404,429,503):
                req=dict(packageName=c.PACKAGE_NAME,downloadUrl=f"https://apk.example.com/{code}.apk",allowedDownloadHosts=["apk.example.com"],
                    idempotencyKey="fault-"+str(code),reason="T09 source failure")
                response=admin.post(prefix+"/external-artifacts",json=req); self.assertEqual(202,response.status_code,response.text)
                self.wait_job(env,"fault-"+str(code),"failed","external_http_"+str(code))
            for name,path,error in (("html","html","external_not_apk"),("wrong","999","package_mismatch")):
                response=admin.post(prefix+"/external-artifacts",json=dict(packageName=c.PACKAGE_NAME,downloadUrl=f"https://apk.example.com/{path}.apk",
                    allowedDownloadHosts=["apk.example.com"],idempotencyKey=name,reason="T09 reject wrong bytes"))
                self.assertEqual(202,response.status_code,response.text)
                self.wait_job(env,name,"failed",error)
            env.replace_external=True
            with env.db.session() as session:
                bad=session.scalar(select(AppArtifact).where(AppArtifact.version_code==101,AppArtifact.state=="verified"))
                bad_artifact=bad.artifact_id
            response=admin.post(prefix+f"/artifacts/{bad_artifact}/download-sources",json=dict(packageName=c.PACKAGE_NAME,
                downloadUrl="https://apk.example.com/101.apk",allowedDownloadHosts=["apk.example.com"],expectedArtifactSha256=env.hashes[101],
                idempotencyKey="replaced",reason="T09 replaced file"))
            self.assertEqual(202,response.status_code,response.text)
            self.wait_job(env,"replaced","failed","external_file_changed")
            env.replace_external=False
            # Queued request survives a complete HTTP/worker/database-engine restart.
            env.workers_stop()
            response=second.post(prefix+f"/artifacts/{artifact_id}/download-sources",json=dict(packageName=c.PACKAGE_NAME,
                downloadUrl="https://apk.example.com/102.apk",allowedDownloadHosts=["apk.example.com"],expectedArtifactSha256=env.hashes[102],
                idempotencyKey="restart-job",reason="T09 durable restart"))
            self.assertEqual(202,response.status_code,response.text)
            env.db.close(); env.restart()
            admin.close(); admin=httpx.Client(base_url=env.base_url,timeout=30)
            self.addCleanup(admin.close)
            self.assertEqual(200,admin.post("/aiyoloapi/auth/login",json=dict(username="t09-admin-a",password=PASSWORD)).status_code)
            self.wait_job(env,"restart-job","succeeded")
            check("external",101,"restart-device")
            # Sessions carry current platform role, including the second administrator.
            second.close(); second=httpx.Client(base_url=env.base_url,timeout=30); self.addCleanup(second.close)
            self.assertEqual(200,second.post("/aiyoloapi/auth/login",json=dict(username="t09-admin-b",password=PASSWORD)).status_code)
            with env.db.session() as session:
                session.get(AccountRecord,env.accounts["t09-admin-b"].account_id).platform_role="NORMAL_USER"
            self.assertEqual(403,second.post(prefix+"/external-artifacts",json={}).status_code)
            self.assertEqual([],list(env.external.root.glob("*.apk")))
            self.assertFalse(any(r["authorization"] or r["cookie"] for r in env.origin_requests))
            (evidence/"service.json").write_text(json.dumps(dict(network=network,restart=True,secondAdminDemotionDenied=True,
                realMinioVersionedDownload=True,concurrentPublishStatuses=sorted(r.status_code for r in responses),
                singlePublishAudit=True,publishAndStopReplay=True,normalDownloads=[100,101],
                sourceFaults=[403,404,429,503,"html","wrong-package","replacement"],
                testOnlyCompatibilityEvidence=True,androidInstallationTested=False),indent=2),encoding="utf-8")

    def wait_job(self,env,key,state,error=None):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            with env.db.session() as session:
                job=session.scalar(select(AppUpload).where(AppUpload.idempotency_key==key))
                if job and job.state in ("succeeded","failed") and not job.cleanup_pending:
                    self.assertEqual(state,job.state,job.error_code)
                    if error: self.assertEqual(error,job.error_code)
                    return
            time.sleep(.1)
        self.fail("job did not settle: "+key)
