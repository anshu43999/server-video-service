"""Actual SDK verification -> release -> signed direct-download -> hash.

TLS origin mapping is test-only; production has no loopback bypass. MinIO uses
an isolated random versioned bucket and never touches application objects.
"""
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from minio.deleteobjects import DeleteObject
from minio.versioningconfig import ENABLED, VersioningConfig
from minio import Minio
from sqlalchemy import select

from app.app_updates import contract as c
from app.app_updates.apk_verifier import ApkVerifier
from app.app_updates.delivery import MinioTickets
from app.app_updates.external_fetch import ExternalFetcher
from app.app_updates.external_jobs import ExternalJobs
from app.app_updates.minio_store import ApkMinioStore
from app.app_updates.models import AppIdentity, AppArtifact, AppArtifactSource
from app.app_updates.publisher import AppPublisher
from app.app_updates.service import AppUpdates
from app.app_updates.uploads import ApkUploads
from app.config import settings
from app.database import DatabaseManager, AccountRecord
from apk_test_support import ApkFixtures
from postgresql_support import isolated_postgresql_url
from test_apk_external_real import Origin
from test_apk_uploads import COMPAT
from test_app_update_service import SCOPE, wire

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("RUN_APP_DELIVERY_REAL") == "1", "requires SDK, isolated PostgreSQL and MinIO")
class RealDeliveryTests(unittest.TestCase):
    def test_both_sources_publish_and_direct_download(self):
        temp = tempfile.TemporaryDirectory(prefix="app-delivery-real-", dir=ROOT / ".tmp")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        cluster = isolated_postgresql_url("app_delivery")
        db = DatabaseManager(cluster.__enter__())
        self.addCleanup(lambda: cluster.__exit__(None,None,None))
        self.addCleanup(db.close)
        fixtures = ApkFixtures(root)
        first = fixtures.apk("first", version=1, native_abi="arm64-v8a")
        second = fixtures.apk("second", version=2, native_abi="arm64-v8a")
        signer = fixtures.signer(first)
        publisher = AppPublisher("app-test-real", Ed25519PrivateKey.generate())
        with db.session() as session:
            session.add(AccountRecord(account_id="admin", username="admin", password_hash="fixture", role="admin", platform_role="PLATFORM_ADMIN"))
            session.add(AppIdentity(package_name=c.PACKAGE_NAME, publisher_id="test", approved_signer_sha256=signer,
                metadata_key_config_ref=publisher.key_id))
        origin = Origin(root, first.read_bytes())
        self.addCleanup(origin.close)
        fetcher = ExternalFetcher(resolver=lambda *_:("8.8.8.8",),connection=origin.connection)
        external = ExternalJobs(db,ApkVerifier(fixtures.tools),fetcher,root=root/"external",compatibility=COMPAT)
        external.register("admin",wire(c.ExternalArtifactRequest,packageName=c.PACKAGE_NAME,
            downloadUrl="https://apk.example.com/file.apk",allowedDownloadHosts=["apk.example.com"],
            idempotencyKey="external",reason="real TLS acceptance"))
        external.process_one()
        with db.session() as session:
            first_artifact = session.scalar(select(AppArtifact).where(AppArtifact.version_code==1))
            self.assertIsNotNone(first_artifact)
            first_id = first_artifact.artifact_id
            first_source = session.scalar(select(AppArtifactSource).where(AppArtifactSource.artifact_id==first_id))
            source_id = first_source.source_id
        updates = AppUpdates(db,publisher,scopes=[SCOPE])
        draft = updates.draft("admin",wire(c.ReleaseDraftRequest,**SCOPE,artifactId=first_id,importance="normal",
            notes=["first version"],idempotencyKey="draft-one",reason="real source"))
        updates.publish("admin",wire(c.PublishRequest,**SCOPE,releaseId=draft["resourceId"],sourceId=source_id,
            sourceRevision=1,minSupportedVersionCode=1,restrictedCapabilities=[],expectedPolicyRevision=1,
            idempotencyKey="publish-one",reason="real source"))
        # The first version cannot upgrade itself; verify production direct
        # source URL from the policy binding without inventing versionCode=0.
        self.assertEqual(1,len(origin.requests))
        template=ApkMinioStore.from_settings(settings)
        bucket="app-delivery-test-"+uuid4().hex
        template.client.make_bucket(bucket)
        evidence={"bucket":bucket,"externalFirstVersionVerified":True}
        try:
            template.client.set_bucket_versioning(bucket,VersioningConfig(ENABLED))
            from urllib.parse import urlsplit
            # The available MinIO is private HTTP. Exercise a controlled TLS
            # S3 gateway, validating SigV4 and reading the exact version. This
            # is external storage infrastructure, never the business API.
            gateway_root=root/"gateway"
            gateway_root.mkdir()
            gateway=Origin(gateway_root,b"")
            self.addCleanup(gateway.close)
            parent=gateway.server.RequestHandlerClass
            class S3Handler(parent):
                def do_GET(self):
                    from urllib.parse import parse_qs, quote, unquote
                    gateway.requests.append({"path":self.path})
                    parsed=urlsplit(self.path)
                    query=parse_qs(parsed.query)
                    signature=query.pop("X-Amz-Signature")[0]
                    credential=query["X-Amz-Credential"][0].split("/")
                    canonical_query="&".join(quote(k,safe="-_.~")+"="+quote(v[0],safe="-_.~")
                        for k,v in sorted(query.items()))
                    canonical="GET\n"+parsed.path+"\n"+canonical_query+"\nhost:apk.example.com\n\nhost\nUNSIGNED-PAYLOAD"
                    string_to_sign="AWS4-HMAC-SHA256\n"+query["X-Amz-Date"][0]+"\n"+"/".join(credential[1:])+"\n"+hashlib.sha256(canonical.encode()).hexdigest()
                    key=("AWS4"+settings.minio_secret_key).encode()
                    for value in credential[1:]:
                        key=hmac.new(key,value.encode(),hashlib.sha256).digest()
                    correct=hmac.new(key,string_to_sign.encode(),hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(signature,correct):
                        self.send_error(403)
                        return
                    object_bucket,object_key=unquote(parsed.path).lstrip("/").split("/",1)
                    if object_bucket!=bucket:
                        self.send_error(403)
                        return
                    response=template.client.get_object(bucket,object_key,version_id=query["versionId"][0])
                    try:
                        data=response.read()
                    finally:
                        response.close()
                        response.release_conn()
                    self.send_response(200)
                    self.send_header("Content-Length",str(len(data)))
                    self.send_header("Connection","close")
                    self.end_headers()
                    self.wfile.write(data)
                    self.close_connection=True
            gateway.server.RequestHandlerClass=S3Handler
            region=template.client._get_region(bucket)
            signing_client=Minio("apk.example.com",access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,secure=True,region=region)
            store=ApkMinioStore(template.client,bucket=bucket,allowed_hosts=["apk.example.com"])
            uploads=ApkUploads(db,ApkVerifier(fixtures.tools),store,root=root/"uploads",compatibility=COMPAT)
            upload=uploads.begin("admin")
            uploads.path(upload).write_bytes(second.read_bytes())
            uploads.finish(upload,idempotency_key="internal-two",reason="real MinIO acceptance",
                size_bytes=second.stat().st_size,sha256=hashlib.sha256(second.read_bytes()).hexdigest())
            uploads.process_one()
            self.assertEqual("verified",uploads.status(upload)["state"])
            second_id=uploads.status(upload)["resourceId"]
            # Register the same bytes at a public TLS source as another source
            # revision. Switching a published source is not silently allowed.
            origin.raw=second.read_bytes()
            external.register("admin",wire(c.SourceRequest,packageName=c.PACKAGE_NAME,
                downloadUrl="https://apk.example.com/file.apk",allowedDownloadHosts=["apk.example.com"],
                expectedArtifactSha256=hashlib.sha256(origin.raw).hexdigest(),idempotencyKey="external-two",reason="real mirror"),
                target_artifact_id=second_id)
            external.process_one()
            with db.session() as session:
                sources=session.scalars(select(AppArtifactSource).where(AppArtifactSource.artifact_id==second_id)).all()
                internal=next(s for s in sources if s.storage_mode=="internal")
                public=next(s for s in sources if s.storage_mode=="external")
            scope2=SCOPE|{"channel":"external-test"}
            updates=AppUpdates(db,publisher,scopes=[SCOPE,scope2],tickets=MinioTickets(store,signing_client))
            for scope,source in [(SCOPE,internal),(scope2,public)]:
                draft=updates.draft("admin",wire(c.ReleaseDraftRequest,**scope,artifactId=second_id,importance="important",
                    notes=["real direct delivery"],idempotencyKey="draft-"+source.storage_mode,reason="real source"))
                release=draft["resourceId"]
                rev=2 if scope==SCOPE else 1
                result=updates.publish("admin",wire(c.PublishRequest,**scope,releaseId=release,sourceId=source.source_id,
                    sourceRevision=source.source_revision,minSupportedVersionCode=1,restrictedCapabilities=[],
                    expectedPolicyRevision=rev,idempotencyKey="publish-"+source.storage_mode,reason="real source"))
                check=wire(c.CheckRequest,**scope,requestId="check-real",installationId="real-device",currentVersionCode=1,
                    currentVersionName="1",sdkInt=27,supportedAbis=["arm64-v8a"],signerSha256=signer,
                    serverContractVersion=1,lastPolicyRevision=0)
                updates.check(check)
                body=wire(c.DownloadRequest,**scope,requestId="download-real",installationId="real-device",currentVersionCode=1,
                    expectedPolicyRevision=result["revision"],releaseId=release,artifactId=second_id,sourceId=source.source_id,
                    sourceRevision=source.source_revision,sha256=hashlib.sha256(origin.raw).hexdigest(),sizeBytes=len(origin.raw))
                from app.app_updates.signatures import verify_envelope
                expected=body.model_dump(include=set(c.ClientContext.model_fields))|dict(releaseId=release,artifactId=second_id,
                    sourceId=source.source_id,sourceRevision=source.source_revision,versionCode=2,sha256=body.sha256,
                    sizeBytes=body.sizeBytes,signerSha256=signer)
                signed=updates.download(body)
                payload=verify_envelope(json.dumps(signed).encode(),trusted_keys={publisher.key_id:publisher.key.public_key()},
                    message_type="download",expected=expected,min_policy_revision=result["revision"])
                if source.storage_mode=="external":
                    before=len(origin.requests)
                    content=io.BytesIO()
                    fetcher.fetch(payload.downloadUrl,payload.allowedDownloadHosts,content)
                    data=content.getvalue()
                    self.assertEqual(before+1,len(origin.requests))
                else:
                    # A later object at the same key does not change a signed
                    # ticket's versionId. GET uses the actual presigned URL.
                    template.client.put_object(bucket,source.object_key,io.BytesIO(b"changed"),7)
                    connection=gateway.connection("apk.example.com","8.8.8.8",10)
                    parsed=urlsplit(payload.downloadUrl)
                    connection.request("GET",parsed.path+"?"+parsed.query)
                    response=connection.getresponse()
                    data=response.read()
                    self.assertEqual(200,response.status,data[:200])
                    connection.close()
                self.assertEqual(body.sizeBytes,len(data))
                self.assertEqual(body.sha256,hashlib.sha256(data).hexdigest())
                permission=updates.install(wire(c.InstallPermissionRequest,**body.model_dump(),verifiedVersionCode=2,
                    verifiedSignerSha256=signer))
                verify_envelope(json.dumps(permission).encode(),trusted_keys={publisher.key_id:publisher.key.public_key()},
                    message_type="install_permission",expected=expected,min_policy_revision=result["revision"])
                evidence[source.storage_mode]=dict(signedTicketVerified=True,directDownloadHashMatched=True,
                    installPermissionVerified=True,sourceRevision=source.source_revision)
            evidence["tlsTestMapping"]="validated public fixture IP -> controlled loopback TLS; production unchanged"
            evidence["minioTestGateway"]="test gateway validates SigV4 and reads versionId through MinIO SDK; public production gateway not tested"
        finally:
            errors=list(template.client.remove_objects(bucket,(DeleteObject(o.object_name,o.version_id)
                for o in template.client.list_objects(bucket,recursive=True,include_version=True))))
            self.assertEqual([],errors)
            template.client.remove_bucket(bucket)
            evidence["testBucketRemoved"]=True
            directory=Path(os.environ["APK_TEST_EVIDENCE_ROOT"])
            directory.mkdir(parents=True,exist_ok=True)
            (directory/"delivery-integration.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
