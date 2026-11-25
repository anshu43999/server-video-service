"""API27 integration fixture. Only an explicit managed local run enables this test."""
import hashlib
import os
from pathlib import Path
import socket
import subprocess
from contextlib import contextmanager
import threading
import time
import unittest
from unittest.mock import patch
from sqlalchemy import select
import uvicorn
from app import main
from app.database import Base,DatabaseManager,MobileClipRecord
from project_api_support import ProjectApiSupport
from test_manual_clip_api import seed_clip_event

@contextmanager
def managed_fixture():
    directory=Path(os.environ['M203_LIVE_DIR']).resolve()
    assert directory.parent.name=='harness-runs' and directory.name.startswith('M203-T09-')
    assert (directory/'.owner.json').is_file() and not (directory/'local.db').exists()
    try: yield directory
    finally:
        (directory/'local.db').unlink(missing_ok=True)

@unittest.skipUnless(os.getenv('M203_LIVE_PORT'),'requires dedicated emulator and managed runner')
class RealClip(ProjectApiSupport,unittest.TestCase):
    def test_real_app_receipt_replay(self):
        self.start_project_api('clip-live')
        with managed_fixture() as tmp:
            db=DatabaseManager('sqlite:///'+str(Path(tmp)/'local.db'));Base.metadata.create_all(db.engine)
            try:
                seed_clip_event(db,self.project_id,self.account_id)
                statuses=[]; requests=[]; receipts=[]
                async def relay(scope,receive,send):
                    if scope['type']=='http' and scope['method']=='PUT':
                        requests.append(scope['path']); dropped=False
                        async def intercept(msg):
                            nonlocal dropped
                            if msg['type']=='http.response.start':
                                statuses.append(msg['status']); dropped=msg['status']==201
                                if dropped: msg={**msg,'status':503}
                            if msg['type']=='http.response.body' and statuses and statuses[-1] in (200,201) and msg.get('body'):
                                import json
                                receipt=json.loads(msg['body']);receipts.append(receipt)
                            await send(msg)
                        return await main.app(scope,receive,intercept)
                    return await main.app(scope,receive,send)
                port=int(os.environ['M203_LIVE_PORT']); adb=r'D:\Users\45393\Android\sdk\platform-tools\adb.exe'
                server=uvicorn.Server(uvicorn.Config(relay,host='127.0.0.1',port=port,lifespan='off',
                    timeout_graceful_shutdown=2,timeout_keep_alive=1,access_log=False,log_level='critical'))
                with patch('app.main.database',db), socket.socket() as listener:
                    listener.bind(('127.0.0.1',port));listener.listen(16)
                    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
                    try:
                        until=time.monotonic()+10
                        while not server.started:
                            self.assertLess(time.monotonic(),until);time.sleep(.05)
                        ticket=self.headers['Authorization'].split()[1]
                        cmd=[adb,'-s','emulator-5554','shell','am','instrument','-w','-r','-e','class','com.aiyolo.inspection.events.ManualClipLiveInstrumentedTest']
                        for k,v in dict(clipPort=port,clipAccount=self.account_id,clipProject=self.project_id,clipTicket=ticket).items():cmd+=['-e',k,str(v)]
                        runner='com.aiyolo.inspection.m201t02.test/androidx.test.runner.AndroidJUnitRunner'
                        prep=subprocess.run(cmd+['-e','clipPhase','prepare',runner],capture_output=True,timeout=65)
                        prep_text=prep.stdout.decode('utf8','replace').replace(ticket,'<redacted>')
                        self.assertIn('OK (1 test)',prep_text,prep_text[-2000:])
                        subprocess.run([adb,'-s','emulator-5554','shell','am','force-stop','com.aiyolo.inspection.m201t02'],check=True,timeout=10)
                        self.assertEqual([],requests,'capture, approval and process stop must not start a transfer')
                        cmd+=['com.aiyolo.inspection.m201t02.test/androidx.test.runner.AndroidJUnitRunner']
                        result=subprocess.run(cmd,capture_output=True,timeout=150)
                        text=result.stdout.decode('utf8','replace').replace(ticket,'<redacted>')
                        print('actual PUT statuses:',statuses,'request count:',len(requests))
                        self.assertIn('OK (1 test)',text,text[-3500:]);self.assertEqual([201,200],[s for s in statuses if s in (200,201)])
                        self.assertEqual(2,len(receipts)); self.assertEqual(receipts[0],receipts[1]);self.assertLessEqual(len(requests),5)
                        with db.session() as s:
                            rows=s.scalars(select(MobileClipRecord)).all();self.assertEqual(1,len(rows));r=rows[0]
                            self.assertEqual(r.sha256,hashlib.sha256(r.content).hexdigest());self.assertEqual(r.sha256,receipts[0]['sha256'])
                            print('verified one attachment:',len(r.content),'bytes; identical digest and receipt on retry')
                    finally:
                        server.should_exit=True;thread.join(10);self.assertFalse(thread.is_alive())
            finally:db.close()
