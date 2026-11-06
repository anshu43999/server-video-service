"""Isolated PostgreSQL + real HTTP acceptance for M36-T18. Never uses the dev DB."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
PG = Path('D:/PostgreSQL/bin')
MODEL_ID = 'uploaded-06b4dd2f10544673ab723226f91c34a7'
PASSWORD = 'temporary-internal-test-password'
OUT = Path(os.environ.get('M36_T18_OUT', ROOT / 'harness/evidence/M36/M36-T18-live-postgres-http.json'))


class Acceptance:
    def __init__(self, base, db_url):
        self.client = httpx.Client(base_url=base, timeout=30)
        self.db_url = db_url
        self.tokens, self.trace = {}, []
        self.snapshots = []

    def call(self, role, method, path, body=None, expected=200):
        if not path.startswith('/aiyoloapi/') or '://' in path:
            raise RuntimeError('local API paths only')
        request_id = 'm36-t18-' + uuid4().hex
        headers = {'x-request-id': request_id}
        if role in self.tokens:
            headers['Authorization'] = 'Bearer ' + self.tokens[role]
        response = self.client.request(method, path, json=body, headers=headers)
        entry = dict(role=role, method=method, path=path, status=response.status_code,
                     requestId=response.headers.get('x-request-id'))
        if response.content and response.headers.get('content-type', '').startswith('application/json'):
            payload = response.json()
            if response.status_code >= 400:
                entry['error'] = payload.get('detail')
        self.trace.append(entry)
        assert response.status_code == expected, (entry, response.text[:700])
        return response

    def approve(self, base, revision, approved=True, role='gly'):
        return self.call(role, 'POST', base+'/approval', dict(expectedRevision=revision,
            approved=approved, reason='M36-T18 isolated internal approval review')).json()

    def resolve(self, base, revision, plan='photo', role='ptcy', expected=200, **overrides):
        body = dict(planId=plan, expectedRevision=revision, target='mobile', inputType='video' if plan=='camera' else 'image',
                    clientContractVersion=3, supportedExecutionModes=['async' if plan=='camera' else 'sync'])
        body.update(overrides)
        response = self.call(role, 'POST', base+f'/plans/{plan}/resolve', body, expected)
        if expected == 200:
            result = response.json()
            assert result['resolutionOnly'] is True and result['runtimeAuthorization'] is False
            assert result['resolveContractVersion'] == 3
            wanted = {'video-a','video-b'} if plan=='camera' else {'image-a','image-b'}
            assert {m['memberId'] for m in result['members']} == wanted
            for member in result['members']:
                profile = member['parameterSnapshot']
                assert profile['projectId'] == result['projectId']
                assert profile['modelId'] == member['modelId'] == MODEL_ID
                assert profile['modelVersion'] == member['version']
                assert profile['platform'] == member['parameterPlatform'] == 'android'
                assert profile['revision'] == member['parameterRevision']
                assert len(member['artifactSha256']) == 64 and len(member['artifacts']) == 2
                assert all(a['exists'] and a['hashValid'] and a['target']=='mobile' for a in member['artifacts'])
            self.snapshots.append(result)
        return response.json()

    def run(self):
        self.tokens['admin'] = self.call('admin','POST','/aiyoloapi/auth/setup',dict(username='m36-t18-admin',password=PASSWORD)).json()['accessToken']
        admin = self.call('admin','GET','/aiyoloapi/auth/me').json()
        accounts = {}
        for role in ('gly','ptcy'):
            account = self.call('admin','POST','/aiyoloapi/platform/accounts',dict(username='m36-t18-'+role,
                password=PASSWORD,platformRole='NORMAL_USER'),201).json()
            accounts[role] = account['accountId']
            self.tokens[role] = self.call(role,'POST','/aiyoloapi/auth/login',dict(username=account['username'],password=PASSWORD)).json()['accessToken']
        projects, bases = [], []
        for suffix in ('a','b'):
            project = self.call('admin','POST','/aiyoloapi/projects',dict(projectCode='m36-t18-'+suffix,
                displayName='M36 T18 '+suffix,ownerAccountId=admin['accountId']),201).json()
            projects.append(project['projectId'])
            path='/aiyoloapi/projects/'+project['projectId']
            for role, project_role in (('gly','PROJECT_OWNER'),('ptcy','PROJECT_USER')):
                self.call('admin','POST',path+'/members',dict(accountId=accounts[role],projectRole=project_role),201)
            members = [dict(memberId=kind+'-'+letter,modelId=MODEL_ID,version=version,target='mobile',
                position=i,inputTypes=[kind],execution='single')
                for i,(kind,letter,version) in enumerate((('image','a','2.0.0'),('image','b','3.0.0'),('video','a','2.0.0'),('video','b','3.0.0')))]
            plans = [dict(planId=plan,name=plan,inputTypes=[kind],memberIds=[kind+'-a',kind+'-b'],execution=mode,enabled=True)
                for plan,kind,mode in (('photo','image','sync'),('camera','video','async'))]
            base=path+'/scenes/mixed';bases.append(base)
            body=dict(sceneId='mixed',name='混合安全套件',inputTypes=['image','video'],models=members,plans=plans,enabled=True,expectedRevision=0)
            self.call('ptcy','POST',path+'/scenes',body,403)
            self.call('gly','POST',path+'/scenes',body,201)
            self.approve(base,1,role='admin' if suffix=='b' else 'gly')
            self.resolve(base,2);self.resolve(base,2,'camera')
            self.resolve(base,2,role='admin')
            self.resolve(base,2,role='gly')
            for version,modes in ((1,[]),(2,['sync']),(3,[]),(3,['async'])):
                error=self.resolve(base,2,expected=409,clientContractVersion=version,supportedExecutionModes=modes)
                assert error['detail']['code']=='execution_mode_not_supported'
            assert self.resolve(base,2,expected=409,inputType='video')['detail']['code']=='scene_input_not_supported'
            self.call('ptcy','POST',base+'/approval',dict(expectedRevision=2,approved=True,reason='forbidden'),403)
        a,b=bases
        profile_url=a+'/members/image-a/parameter-profile?sceneRevision=2'
        self.call('ptcy','GET',profile_url,expected=403)
        profile=self.call('gly','GET',profile_url).json()
        profile['detection']['confidenceThreshold']=0.21
        body={key:profile[key] for key in ('schemaVersion','detection','alertRules')}|{'expectedRevision':profile['revision']}
        saved=self.call('gly','PUT',profile_url,body).json();assert saved['revision']==1
        self.call('gly','PUT',profile_url,body,409)
        before=self.resolve(a,2)
        assert before['members'][0]['parameterRevision']==0
        # The same exact release in another project must keep its own profile.
        assert self.resolve(b,2)['members'][0]['parameterRevision']==0
        self.approve(a,2)
        current=self.resolve(a,3)
        assert current['members'][0]['parameterSnapshot']['detection']['confidenceThreshold']==0.21
        assert current['members'][0]['parameterRevision']==1
        # Check every selected member, not just the first bundle entry.
        for resolved in (current, self.resolve(a,3,'camera')):
            for selected in resolved['members']:
                frozen=self.call('ptcy','GET',selected['parameterUrl']).json()
                assert frozen['detection']==selected['parameterSnapshot']['detection']
                assert frozen['revision']==selected['parameterRevision']
                for artifact in selected['artifacts']:
                    projection=next(item for item in selected['executionModel']['artifacts']
                                    if item['artifactId']==artifact['artifactId'])
                    assert projection['sha256'].lower()==artifact['sha256'].lower()
                    content=self.call('ptcy','GET',projection['url']).content
                    assert hashlib.sha256(content).hexdigest().lower()==artifact['sha256'].lower()
        self.resolve(a,2,expected=409)
        self.call('gly','GET',profile_url,expected=409)
        scene=self.call('ptcy','GET',a).json()
        member=scene['models'][0]
        download=member['executionModel']['artifacts'][0]['url'];parameters=member['parameterUrl']
        downloaded=self.call('ptcy','GET',download)
        assert hashlib.sha256(downloaded.content).hexdigest().lower()==member['executionModel']['artifacts'][0]['sha256'].lower()
        for url in (download,parameters):
            self.call('ptcy','GET',url.replace('expectedRevision=3','expectedRevision=2'),expected=409)
            self.call('ptcy','GET',url.replace('versions/2.0.0','versions/9.0.0'),expected=404)
        self.call('ptcy','GET',download.replace('/android-int8/','/server-pt/'),expected=404)
        self.call('ptcy','GET',parameters.replace('target=mobile','target=pc'),expected=404)
        self.call('ptcy','GET',download.replace(projects[0],projects[1]),expected=409)
        # Config mutation clears approval; it is never implicitly reapproved.
        changed=self.call('gly','PATCH',a,dict(expectedRevision=3,name='重新审核套件')).json()
        assert changed['revision']==4 and not changed['approved']
        self.resolve(a,3,expected=404)
        self.call('ptcy','GET',download,expected=404)
        self.approve(a,4)
        current=self.resolve(a,5)
        self.call('ptcy','GET',download,expected=409)
        self.approve(a,5,False)
        self.resolve(a,5,expected=404)
        self.call('ptcy','GET',parameters,expected=404)
        self.approve(a,6)
        self.resolve(a,7)
        # Persisted snapshots and audit records are captured before deliberate withdrawal.
        engine=create_engine(self.db_url)
        with engine.connect() as conn:
            db={name:[dict(row) for row in conn.execute(text(query)).mappings()] for name,query in {
                'scenes':"SELECT project_id,scene_id,revision,approved FROM project_scenes ORDER BY project_id",
                'plans':"SELECT project_id,scene_id,plan_id,execution,parameter_sources FROM project_scene_plans ORDER BY project_id,plan_id",
                'members':"SELECT project_id,scene_id,member_id,model_id,model_version,target,parameter_snapshot FROM project_scene_members ORDER BY project_id,position",
                'audit':"SELECT project_id,request_id,actor_account_id,project_role,action,previous_revision,new_revision,outcome FROM project_audit_events ORDER BY occurred_at,audit_id",
                'profiles':"SELECT project_id,model_id,model_version,platform,revision FROM model_parameter_profiles WHERE scope='PROJECT'",
            }.items()}
            assert len(db['scenes'])==2 and len(db['plans'])==4 and len(db['members'])==8
            assert all(len(plan['parameter_sources'])==2 for plan in db['plans'])
            assert any(row['action']=='model_parameters.update' and row['request_id'] in {t['requestId'] for t in self.trace} for row in db['audit'])
            assert conn.execute(text('SELECT count(*) FROM project_model_assignments')).scalar_one()==0
        engine.dispose()
        memberships=self.call('gly','GET','/aiyoloapi/projects/'+projects[0]+'/members').json()['members']
        membership=next(m for m in memberships if m['accountId']==accounts['ptcy'])
        self.call('gly','DELETE',f"/aiyoloapi/projects/{projects[0]}/members/{accounts['ptcy']}?expectedRevision={membership['revision']}",expected=204)
        for url in (download,parameters):self.call('ptcy','GET',url,expected=404)
        self.resolve(a,7,expected=404)
        self.resolve(b,2)
        self.call('admin','POST',f'/aiyoloapi/models/{MODEL_ID}/versions/3.0.0/revoke',dict(reason='isolated copy withdrawal'))
        self.resolve(b,2,expected=404)
        url_b=f"{b}/models/{MODEL_ID}/versions/3.0.0/artifacts/android-int8/download?expectedRevision=2"
        self.call('ptcy','GET',url_b,expected=404)
        return dict(task='M36-T18',at=datetime.now(timezone.utc).isoformat(),projects=projects,
            roles={'admin':'PLATFORM_ADMIN','gly':'PROJECT_OWNER','ptcy':'PROJECT_USER'},
            scope='isolated HTTP/DB configuration and authorization; no inference or extra publication',
            androidConsumer='M108-T08',snapshots=self.snapshots,database=db,caseCount=len(self.trace),trace=self.trace)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def main():
    runtime=ROOT/'.tmp'/('m36-t18-'+uuid4().hex)
    runtime.mkdir(parents=True)
    data=runtime/'pg-data';pg_port,service_port=free_port(),free_port()
    db_url=f'postgresql+psycopg://aiyolo_app@127.0.0.1:{pg_port}/postgres'
    base=f'http://127.0.0.1:{service_port}'
    env={k:v for k,v in os.environ.items() if not k.startswith(('DATABASE_','MINIO_','MODEL_SIGNING_','VERIFICATION_PROVIDER_','ADMIN_TOKEN','MOBILE_TOKEN','LEGACY_'))}
    env.update(DATABASE_URL=db_url,DEPLOYMENT_ENV='development',ADMIN_FRONTEND_MODE='vue',
        CALIBRATION_ROOT=str(runtime/'calibration'),M36_T18_RUNTIME=str(runtime),
        PYTHONPATH=os.pathsep.join([str(ROOT),str(ROOT/'tests')]),RUN_POSTGRES_TESTS='1')
    # Copy the already authorized internal releases; never publish or alter source assets.
    payload=json.loads((ROOT/'models/registry.json').read_text(encoding='utf-8'))
    rows=[deepcopy(row) for row in payload['models'] if row['modelId']==MODEL_ID and row['version'] in ('2.0.0','3.0.0')]
    assert len(rows)==2 and all(row['status']=='PUBLISHED' and row['publishedTargets']==['mobile'] for row in rows)
    for row in rows:
        for artifact in row['artifacts']:
            source=ROOT/artifact['path'];destination=runtime/artifact['path'];destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,destination)
            assert hashlib.sha256(destination.read_bytes()).hexdigest().lower()==artifact['sha256'].lower()
    (runtime/'models/registry.json').write_text(json.dumps({'models':rows}),encoding='utf-8')
    (runtime/'models/profiles.json').write_text(json.dumps({'schemaVersion':2,'profiles':{},'audit':[]}),encoding='utf-8')
    source_digest=hashlib.sha256((ROOT/'models/registry.json').read_bytes()).hexdigest()
    service=None;pg_started=False;acceptance=None
    result={'runtime':str(runtime),'pgPort':pg_port,'servicePort':service_port,'databaseIdentity':{'driver':'postgresql+psycopg','user':'aiyolo_app','host':'127.0.0.1','database':'postgres'}}
    log=(runtime/'runner.log').open('w',encoding='utf-8')
    try:
        subprocess.run([str(PG/'initdb.exe'),'-D',str(data),'-U','aiyolo_app','--auth-local=trust','--auth-host=trust','--encoding=UTF8','--locale=C'],check=True,stdout=log,stderr=log)
        subprocess.run([str(PG/'pg_ctl.exe'),'-D',str(data),'-l',str(runtime/'postgres.log'),'-o',f'-h 127.0.0.1 -p {pg_port}','-w','start'],check=True,stdout=log,stderr=log)
        pg_started=True
        engine=create_engine(db_url)
        with engine.connect() as conn:
            assert Path(conn.execute(text('SHOW data_directory')).scalar_one()).resolve()==data.resolve()
            assert conn.execute(text('SELECT current_user')).scalar_one()=='aiyolo_app'
        engine.dispose()
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=env,check=True,stdout=log,stderr=log)
        service_log=(runtime/'service.log').open('w',encoding='utf-8')
        service=subprocess.Popen([sys.executable,'-m','uvicorn','m36_t18_server:app','--host','127.0.0.1','--port',str(service_port)],cwd=runtime,env=env,stdout=service_log,stderr=service_log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if service.poll() is not None:raise RuntimeError('isolated service exited; inspect '+str(runtime/'service.log'))
            try:
                health=httpx.get(base+'/healthz',timeout=2)
                if health.status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(0.3)
        else:raise RuntimeError('service health timeout')
        acceptance=Acceptance(base,db_url)
        result.update(acceptance.run())
        print(f"HTTP acceptance passed: {result['caseCount']} requests; runtime {runtime}",flush=True)
        # PostgreSQL regression uses the same isolated endpoint but random, cleaned schemas.
        command=[sys.executable,'-m','unittest','test_scene_execution_parameters.SceneParameterPostgresTests',
            'test_scene_execution_parameters.SceneParameterMigrationTests','test_project_scene_suite_persistence','-v']
        with (runtime/'postgres-tests.log').open('w',encoding='utf-8') as test_log:
            completed=subprocess.run(command,cwd=ROOT,env=env,stdout=test_log,stderr=test_log)
        result['postgresRegressionExitCode']=completed.returncode
        if completed.returncode:raise RuntimeError('PostgreSQL regression failed; inspect '+str(runtime/'postgres-tests.log'))
        result['passed']=True
    finally:
        if acceptance:
            for role in acceptance.tokens:
                try:acceptance.call(role,'POST','/aiyoloapi/auth/logout')
                except Exception:pass
            acceptance.client.close()
            result.setdefault('trace',acceptance.trace)
        if service:
            service.terminate()
            try:service.wait(timeout=15)
            except subprocess.TimeoutExpired:service.kill();service.wait(timeout=5)
            service_log.close()
        if pg_started:
            subprocess.run([str(PG/'pg_ctl.exe'),'-D',str(data),'-w','stop','-m','fast'],check=True,stdout=log,stderr=log)
        log.close()
        for port in (pg_port,service_port):
            with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',port))!=0
        result['temporaryPortsClosed']=True
        result['sourceRegistryUnchanged']=hashlib.sha256((ROOT/'models/registry.json').read_bytes()).hexdigest()==source_digest
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        assert result['sourceRegistryUnchanged']
    print(json.dumps({key:result[key] for key in ('passed','caseCount','temporaryPortsClosed','sourceRegistryUnchanged')},indent=2))


if __name__=='__main__':
    main()
