"""Local acceptance infrastructure: real PG/MinIO, SDK and controlled TLS.

No production configuration is written. Only random test buckets are removed.
"""
import hashlib
import hmac
import json
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from minio.deleteobjects import DeleteObject
from minio.versioningconfig import ENABLED, VersioningConfig
from sqlalchemy import select
import uvicorn

from app import auth
from app.admin_frontend import mount_admin_frontend
from app.app_updates import contract as c
from app.app_updates.api import RequestBudget, configured_updates, create_update_router
from app.app_updates.external_api import create_external_router
from app.app_updates.external_fetch import ExternalFetcher
from app.app_updates.external_jobs import ExternalJobs
from app.app_updates.models import AppIdentity, AppUpload
from app.app_updates.apk_verifier import ApkVerifier
from app.app_updates.minio_store import ApkMinioStore
from app.app_updates.upload_api import create_upload_router
from app.app_updates.uploads import ApkUploads
from app.config import Settings, settings
from app.database import DatabaseManager, ProjectRecord, ProjectMembershipRecord
from app.observability import RequestTelemetry
from app.project_management import create_project_management_router
from apk_test_support import ApkFixtures
from postgresql_support import isolated_postgresql_url
from test_apk_external_real import Origin
from test_apk_uploads import COMPAT

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "acceptance-only-password"
SCOPE = dict(contractVersion=c.CONTRACT_VERSION, publisherId="test", packageName=c.PACKAGE_NAME,
             deploymentId="t09-local", channel="minio")


class LiveEnvironment:
    def __init__(self, root, evidence):
        self.root, self.evidence = root, evidence
        self.stack = __import__("contextlib").ExitStack()
        self.http, self.origin_requests, self.gateway_requests = [], [], []

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def start(self):
        cluster = self.stack.enter_context(isolated_postgresql_url("app_update_live"))
        self.db = DatabaseManager(cluster)
        self.stack.callback(self.db.close)
        fixtures = ApkFixtures(self.root)
        self.fixtures = fixtures
        self.apks = {v: fixtures.apk("version-"+str(v),version=v,native_abi="arm64-v8a") for v in (1,100,101,102)}
        self.apks[999] = fixtures.apk("wrong-package", version=999, package="com.example.wrong", native_abi="arm64-v8a")
        self.signer = fixtures.signer(self.apks[1])
        self.hashes = {v:hashlib.sha256(p.read_bytes()).hexdigest() for v,p in self.apks.items()}
        self.origin = Origin(self.root,self.apks[1].read_bytes())
        self.stack.callback(self.origin.close)
        owner = self
        parent = self.origin.server.RequestHandlerClass
        class Handler(parent):
            def do_GET(self):
                path = urlsplit(self.path).path
                owner.origin_requests.append(dict(path=path,authorization=bool(self.headers.get("Authorization")),
                    cookie=bool(self.headers.get("Cookie"))))
                if path == "/redirect.apk":
                    self.send_response(302); self.send_header("Location","/101.apk"); self.send_header("Content-Length","0"); self.end_headers(); return
                if path in ("/403.apk","/404.apk","/429.apk","/503.apk"):
                    self.send_error(int(path[1:4])); return
                data = b"<html>share page</html>" if path == "/html.apk" else owner.apks[int(path[1:-4])].read_bytes()
                if path == "/101.apk" and getattr(owner,"replace_external",False):
                    data = owner.apks[102].read_bytes()
                self.send_response(200); self.send_header("Content-Length",str(len(data)))
                self.send_header("Connection","close"); self.end_headers(); self.wfile.write(data); self.close_connection=True
        self.origin.server.RequestHandlerClass = Handler
        template = ApkMinioStore.from_settings(settings)
        self.bucket = "app-update-t09-"+uuid4().hex
        template.client.make_bucket(self.bucket)
        def remove_bucket():
            errors=list(template.client.remove_objects(self.bucket,(DeleteObject(o.object_name,o.version_id)
                for o in template.client.list_objects(self.bucket,recursive=True,include_version=True))))
            if errors:
                raise RuntimeError("test bucket cleanup failed")
            template.client.remove_bucket(self.bucket)
            (self.evidence/"bucket-cleanup.json").write_text(json.dumps(dict(bucket=self.bucket,removed=True)),encoding="utf-8")
        self.stack.callback(remove_bucket)
        template.client.set_bucket_versioning(self.bucket,VersioningConfig(ENABLED))
        self.store = ApkMinioStore(template.client,bucket=self.bucket,allowed_hosts=["apk.example.com"])
        gateway_root=self.root/"gateway"; gateway_root.mkdir()
        self.gateway=Origin(gateway_root,b"")
        self.stack.callback(self.gateway.close)
        self.region=template.client._get_region(self.bucket)
        parent=self.gateway.server.RequestHandlerClass
        class Gateway(parent):
            def do_GET(self):
                parsed=urlsplit(self.path); query=parse_qs(parsed.query)
                signature=query.pop("X-Amz-Signature",[""])[0]
                credential=query.get("X-Amz-Credential",[""])[0].split("/")
                canonical_query="&".join(quote(k,safe="-_.~")+"="+quote(v[0],safe="-_.~") for k,v in sorted(query.items()))
                canonical="GET\n"+parsed.path+"\n"+canonical_query+"\nhost:apk.example.com\n\nhost\nUNSIGNED-PAYLOAD"
                string_to_sign="AWS4-HMAC-SHA256\n"+query.get("X-Amz-Date",[""])[0]+"\n"+"/".join(credential[1:])+"\n"+hashlib.sha256(canonical.encode()).hexdigest()
                key=("AWS4"+settings.minio_secret_key).encode()
                for value in credential[1:]: key=hmac.new(key,value.encode(),hashlib.sha256).digest()
                valid=hmac.compare_digest(signature,hmac.new(key,string_to_sign.encode(),hashlib.sha256).hexdigest())
                bucket,key_name=unquote(parsed.path).lstrip("/").split("/",1)
                if not valid or bucket!=owner.bucket:
                    self.send_error(403); return
                response=template.client.get_object(bucket,key_name,version_id=query["versionId"][0])
                try: data=response.read()
                finally: response.close(); response.release_conn()
                owner.gateway_requests.append(dict(bucket=bucket,objectKey=key_name,versionPinned=True,sizeBytes=len(data),signatureVerified=True))
                self.send_response(200); self.send_header("Content-Length",str(len(data)))
                self.send_header("Connection","close"); self.end_headers(); self.wfile.write(data); self.close_connection=True
        self.gateway.server.RequestHandlerClass=Gateway
        key=Ed25519PrivateKey.generate()
        key_path=self.root/"metadata-test.pem"
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        scopes=[SCOPE,SCOPE|dict(channel="external"),SCOPE|dict(channel="concurrency")]
        scope_path=self.root/"scopes.json"; scope_path.write_text(json.dumps(scopes),encoding="utf-8")
        evidence_path=self.root/"recovery.json"
        evidence_path.write_text(json.dumps([dict(stableSha256=self.hashes[100],affectedSha256=[self.hashes[101]],
            recoverySha256=self.hashes[102],preservesData=True,restoresStableBehavior=True,serverContractVersion=1,
            evidenceRef="test-only-server-policy-fixture-not-device-proof")]),encoding="utf-8")
        self.config=Settings(_env_file=None,database_url=cluster,app_updates_enabled=True,app_update_key_id="t09-test",
            app_update_private_key_path=str(key_path),app_update_scopes_path=str(scope_path),
            app_update_recovery_evidence_path=str(evidence_path),app_update_gate_capabilities="online.inference",
            app_apk_worker_enabled=True,app_apk_external_enabled=True,app_apk_max_bytes=8*1024**2,
            minio_endpoint=settings.minio_endpoint,minio_access_key=settings.minio_access_key,minio_secret_key=settings.minio_secret_key,
            minio_region=self.region,app_apk_bucket=self.bucket,app_apk_allowed_hosts="apk.example.com",
            app_apk_download_endpoint="https://apk.example.com",model_signing_private_key_path=None)
        self.old_db,self.old_settings=auth.database,auth.settings
        auth.database=self.db
        auth.settings=Settings(_env_file=None,database_url=cluster,deployment_env="production",admin_token=None,mobile_token=None)
        self.stack.callback(self.restore_auth)
        self.accounts={name:auth._create_account(name,PASSWORD,auth.ROLE_ADMIN if name in ("t09-admin-a","t09-admin-b") else auth.ROLE_OPERATOR)
            for name in ("t09-admin-a","t09-admin-b","t09-owner","t09-user")}
        self.project_id=str(uuid4())
        with self.db.session() as session:
            session.add(AppIdentity(package_name=c.PACKAGE_NAME,publisher_id="test",approved_signer_sha256=self.signer,metadata_key_config_ref="t09-test"))
            session.add(ProjectRecord(project_id=self.project_id,project_code="t09-project",display_name="T09隔离项目"))
            session.flush()
            session.add(ProjectMembershipRecord(project_id=self.project_id,account_id=self.accounts["t09-owner"].account_id,
                project_role="PROJECT_OWNER",enabled=True))
            session.add(ProjectMembershipRecord(project_id=self.project_id,account_id=self.accounts["t09-user"].account_id,
                project_role="PROJECT_USER",enabled=True))
        self.rebuild_workers()
        # Establish the real first-version slot before the 100/101/102 exercise.
        self.upload(self.apks[1],"bootstrap")
        self.workers_start()
        self.stack.callback(self.export)
        self.stack.callback(self.workers_stop)
        self.app=self.make_app()
        self.server=None; self.thread=None
        self.start_http()
        self.stack.callback(self.stop_http)
        self.manifest=dict(baseUrl=self.base_url,apks={str(v):str(p) for v,p in self.apks.items()},
            hashes=self.hashes,signer=self.signer,scopes=scopes,projectId=self.project_id,
            evidence=str(self.evidence),accounts={n:u.account_id for n,u in self.accounts.items()})
        (self.root/"manifest.json").write_text(json.dumps(self.manifest),encoding="utf-8")

    def direct_download(self,url):
        """Client-side test connection; never routes bytes through business HTTP."""
        target=self.gateway if "X-Amz-Signature" in url else self.origin
        for _ in range(6):
            parsed=urlsplit(url)
            if parsed.scheme!="https" or parsed.hostname!="apk.example.com":
                raise AssertionError("unexpected test download host")
            connection=target.connection("apk.example.com","8.8.8.8",10)
            connection.request("GET",parsed.path+("?"+parsed.query if parsed.query else ""),headers={"Host":"apk.example.com"})
            response=connection.getresponse()
            try:
                data=response.read()
                if response.status in (301,302,303,307,308):
                    url=urljoin(url,response.getheader("Location")); continue
                if response.status!=200: raise AssertionError("direct download failed")
                return data
            finally: response.close(); connection.close()
        raise AssertionError("too many test download redirects")

    def restore_auth(self):
        auth.database,auth.settings=self.old_db,self.old_settings

    def rebuild_workers(self):
        self.uploads=ApkUploads(self.db,ApkVerifier(self.fixtures.tools),self.store,root=self.root/"uploads",compatibility=COMPAT)
        self.external=ExternalJobs(self.db,ApkVerifier(self.fixtures.tools),ExternalFetcher(
            resolver=lambda *_:("8.8.8.8",),connection=self.origin.connection),root=self.root/"external",compatibility=COMPAT)

    def upload(self,path,key):
        actor=self.accounts["t09-admin-a"].account_id
        identity=self.uploads.begin(actor); self.uploads.path(identity).write_bytes(path.read_bytes())
        self.uploads.finish(identity,idempotency_key=key,reason="server acceptance bootstrap",size_bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.uploads.process_one()
        if self.uploads.status(identity)["state"]!="verified": raise AssertionError("bootstrap verification failed")

    def workers_start(self):
        self.uploads.start(); self.external.start()

    def workers_stop(self):
        self.uploads.close(); self.external.close()

    def make_app(self):
        app=FastAPI()
        app.add_middleware(RequestTelemetry)
        owner=self
        @app.middleware("http")
        async def capture(request,call_next):
            response=await call_next(request)
            path=request.url.path
            # No headers, bodies, tokens, URL query or credentials in evidence.
            if path.startswith("/aiyoloapi/"):
                owner.http.append(dict(method=request.method,path=path,status=response.status_code))
            return response
        app.include_router(auth.create_auth_router())
        app.include_router(create_project_management_router())
        def updates():
            service=configured_updates(self.db,self.config)
            issue=service.tickets
            def diagnostic_ticket(*args):
                try: return issue(*args)
                except Exception as exc:
                    # Fixed diagnostics only; never record request URLs or SDK text.
                    with (self.evidence/"storage-errors.jsonl").open("a",encoding="utf-8") as output:
                        output.write(json.dumps(dict(type=type(exc).__name__,
                            causeType=type(exc.__cause__).__name__ if exc.__cause__ else None))+"\n")
                    raise
            service.tickets=diagnostic_ticket
            return service
        app.include_router(create_update_router(updates,budget=RequestBudget(rate=10000)))
        app.include_router(create_upload_router(lambda:self.uploads,max_bytes=self.config.app_apk_max_bytes,
            receive_seconds=60,budget=RequestBudget(rate=10000)))
        app.include_router(create_external_router(lambda:self.external,budget=RequestBudget(rate=10000)))
        mount_admin_frontend(app,mode="vue",build_dir=ROOT/"admin-web/dist",preview_dir=ROOT/"admin-web/dist-preview")
        return app

    def start_http(self):
        import socket
        sock=socket.socket(); sock.bind(("127.0.0.1",0)); sock.listen(128)
        self.port=sock.getsockname()[1]; self.base_url=f"http://127.0.0.1:{self.port}"
        self.server=uvicorn.Server(uvicorn.Config(self.app,log_level="warning",access_log=False))
        self.thread=threading.Thread(target=lambda:self.server.run(sockets=[sock]),daemon=True); self.thread.start()
        deadline=time.monotonic()+10
        while not self.server.started and self.thread.is_alive() and time.monotonic()<deadline: time.sleep(.05)
        if not self.server.started: raise RuntimeError("acceptance HTTP failed to start")

    def stop_http(self):
        if self.server:
            self.server.should_exit=True; self.thread.join(timeout=10)
            if self.thread.is_alive(): raise RuntimeError("acceptance HTTP failed to stop")

    def restart(self):
        self.stop_http(); self.workers_stop(); self.rebuild_workers(); self.workers_start(); self.start_http()
        self.manifest["baseUrl"]=self.base_url
        (self.root/"manifest.json").write_text(json.dumps(self.manifest),encoding="utf-8")

    def export(self):
        from app.app_updates.models import AppArtifact, AppArtifactSource, AppPolicy, AppRelease, AppRollback, AppAudit
        with self.db.session() as session:
            data=dict(artifacts=[dict(id=a.artifact_id,state=a.state,versionCode=a.version_code,sha256=a.sha256,
                sizeBytes=a.size_bytes,signerSha256=a.signer_sha256) for a in session.scalars(select(AppArtifact))],
                sources=[dict(id=s.source_id,artifactId=s.artifact_id,mode=s.storage_mode,revision=s.source_revision,state=s.state,
                    versionPinned=bool(s.object_version_id)) for s in session.scalars(select(AppArtifactSource))],
                policies=[dict(id=p.policy_id,channel=p.channel,revision=p.revision,selection=p.selection) for p in session.scalars(select(AppPolicy))],
                releases=[dict(id=r.release_id,artifactId=r.artifact_id,state=r.state,purpose=r.purpose) for r in session.scalars(select(AppRelease))],
                rollbacks=[dict(id=r.operation_id,state=r.state,recoveryState=r.recovery_state,revision=r.effective_policy_revision) for r in session.scalars(select(AppRollback))],
                jobs=[dict(id=j.upload_id,kind=j.kind,state=j.state,errorCode=j.error_code,cleanupPending=j.cleanup_pending) for j in session.scalars(select(AppUpload))],
                audit=[dict(actorId=a.actor_id,action=a.action,result=a.result,before=a.before_revision,after=a.after_revision,
                    reason=a.reason,details=a.details) for a in session.scalars(select(AppAudit))])
        for name,value in (("database.json",data),("http.json",self.http),("origin.json",self.origin_requests),("gateway.json",self.gateway_requests)):
            (self.evidence/name).write_text(json.dumps(value,indent=2,default=str),encoding="utf-8")
