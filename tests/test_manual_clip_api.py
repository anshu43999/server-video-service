import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import select, func
from app.database import DatabaseManager, Base, AlertEventRecord, ProjectRecord, MobileClipRecord
from project_api_support import ProjectApiSupport


def seed_clip_event(db, project, account, event='a'):
    with db.session() as session:
        session.add(ProjectRecord(project_id=project,project_code='clip-fixture',display_name='clip-fixture')); session.flush()
        session.add(AlertEventRecord(project_id=project,event_id=event,payload={'mobileProducer':{'accountId':account}}))


def container_fixture():
    def box(k, b): return (len(b)+8).to_bytes(4,'big')+k+b
    stsd=box(b'stsd',bytes(4)+b'\0\0\0\1'+box(b'avc1',bytes(78)+box(b'avcC',bytes.fromhex('0142001effe100'))))
    mdia=box(b'mdia',box(b'hdlr',bytes(8)+b'vide')+box(b'minf',box(b'stbl',stsd+box(b'stsz',bytes(8)+b'\0\0\0\1'))))
    return box(b'ftyp',b'isom0000')+box(b'mdat',b'test')+box(b'moov',box(b'trak',mdia))


class ClipApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.start_project_api('clip-api')
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.db=DatabaseManager('sqlite:///'+str(Path(tmp.name)/'clips.db')); self.addCleanup(self.db.close)
        Base.metadata.create_all(self.db.engine)
        seed_clip_event(self.db,self.project_id,self.account_id)
        self.mockdb=patch('app.main.database',self.db);self.mockdb.start();self.addCleanup(self.mockdb.stop)
        self.url=f'{self.project_path}/alerts/a/local-clip'
        self.body=container_fixture()
        self.h={**self.headers,'X-Clip-Consent':'single-v1','X-Clip-SHA256':hashlib.sha256(self.body).hexdigest(),'Content-Type':'video/mp4'}
    def test_replayed_receipt_survives_new_connection_and_identifies_exact_bytes(self):
        self.assertEqual(200,self.client.get(self.url,headers=self.headers).status_code)
        first=self.client.put(self.url,headers=self.h,content=self.body); self.assertEqual(201,first.status_code,first.text)
        self.db.close()
        again=self.client.put(self.url,headers=self.h,content=self.body);self.assertEqual(200,again.status_code,again.text)
        self.assertEqual(first.json(),again.json())
        with self.db.session() as s:
            self.assertEqual(1,s.scalar(select(func.count()).select_from(MobileClipRecord)))
            self.assertEqual(self.body,s.scalar(select(MobileClipRecord)).content)
    def test_rejects_unsigned_wrong_digest_invalid_mp4_oversize_wrong_event_or_owner(self):
        self.client.cookies.clear(); self.assertEqual(401,self.client.put(self.url,content=self.body,headers={'Content-Type':'video/mp4'}).status_code)
        for mod,code in [({'X-Clip-Consent':'no'},422),({'X-Clip-SHA256':'0'*64},422),({'Content-Length':'19999999'},413),({'Content-Type':'image/jpeg'},415)]:
            self.assertEqual(code,self.client.put(self.url,headers={**self.h,**mod},content=self.body).status_code)
        bad=b'not a video';self.assertEqual(415,self.client.put(self.url,headers={**self.h,'X-Clip-SHA256':hashlib.sha256(bad).hexdigest()},content=bad).status_code)
        self.assertEqual(404,self.client.put(self.url.replace('/a/','/b/'),headers=self.h,content=self.body).status_code)
        with self.db.session() as s:s.get(AlertEventRecord,(self.project_id,'a')).payload={'mobileProducer':{'accountId':'other'}}
        self.assertEqual(403,self.client.put(self.url,headers=self.h,content=self.body).status_code)
        with self.db.session() as s:self.assertEqual(0,s.scalar(select(func.count()).select_from(MobileClipRecord)))
