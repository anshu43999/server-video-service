import json
import logging
import tempfile
import time
import tracemalloc
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import insert, select, func, text

from app import auth
import app.main as main
from app.alerts.disposition import AlertDispositionStore
from app.audit_retention import retain_audits
from app.dashboard import DashboardStatsService
from app.database import Base, DatabaseManager, ProjectRecord, AlertEventRecord, ProjectAuditEventRecord, PlatformAuditEventRecord
from app.project_management import _audit_page
from app.project_reports import prepare_export
from app.observability import SafeAccessFilter, SafeWebSocketFilter
from project_api_support import ProjectApiSupport


class ReportingApiTests(ProjectApiSupport, unittest.TestCase):
    def setUp(self):
        self.start_project_api('reports-project')
        self.store = AlertDispositionStore(None)
        self._project_isolation.enter_context(patch.object(main, 'alert_disposition_store', self.store))
        for pid in (self.project_id, 'foreign-project'):
            self.store.register({'eventId':'shared-id', 'ruleId':'helmet', 'sourceId':'gate',
                'label':'head', 'severity':'MAJOR', 'confirmedAtUs':time.time_ns()//1000,
                'evidence':{'snapshotDataUrl':'data:image/png;base64,SECRET'},
                'private':'rtsp://user:password@host/live?token=SECRET'}, project_id=pid)
            self.store.mark_false_positive('shared-id', self.account_id, project_id=pid)

    def test_complete_exports_are_scoped_sanitized_audited_and_bounded(self):
        for suffix in ('/alerts/export', '/alerts/false-positives/export', '/alerts/export/false-positives'):
            response = self.client.get(self.project_path+suffix, headers=self.headers)
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(self.project_id, response.json()['projectId'])
            self.assertEqual(1, response.json()['count'])
            self.assertEqual('no-store', response.headers['cache-control'])
            for secret in ('SECRET','password','foreign-project','snapshotDataUrl'):
                self.assertNotIn(secret, response.text)
            page = self.client.get(self.project_path+'/audit', params={'requestId':response.headers['x-request-id']}, headers=self.headers).json()
            self.assertTrue(any(r['action'].startswith('export.') for r in page['events']))
        with patch('app.project_reports.MAX_ROWS', 0):
            self.assertEqual(413, self.client.get(self.project_path+'/alerts/export', headers=self.headers).status_code)
        self.assertEqual(200, self.client.get(self.project_path+'/alerts/export', headers=self.headers).status_code)

    def test_user_cannot_export_read_audit_or_platform_summary(self):
        account=self.client.post('/aiyoloapi/platform/accounts', headers=self.headers,
            json={'username':'reports-user','password':'test-password-123'}).json()
        self.client.post(self.project_path+'/members',headers=self.headers,json={'accountId':account['accountId'],'projectRole':'PROJECT_USER'})
        token=self.client.post('/aiyoloapi/auth/login',json={'username':'reports-user','password':'test-password-123'}).json()['accessToken']
        headers={'Authorization':'Bearer '+token}
        for suffix in ('/alerts/export','/alerts/false-positives/export','/audit'):
            self.assertEqual(403,self.client.get(self.project_path+suffix,headers=headers).status_code)
        self.assertEqual(403,self.client.get('/aiyoloapi/metrics',headers=headers).status_code)
        self.assertEqual(404,self.client.get('/aiyoloapi/projects/foreign-project/alerts/export',headers=headers).status_code)

    def test_platform_summary_has_no_project_or_stream_details(self):
        for pid in (self.project_id,'foreign-project'):
            main.streams[(pid,'secret-stream')]=SimpleNamespace(close=AsyncMock(),metrics=lambda:{'frames_received':7,'frames_processed':5,'frames_dropped':2,'last_error':'rtsp://password'})
        result=self.client.get('/aiyoloapi/metrics',headers=self.headers)
        self.assertEqual({'total':2,'framesReceived':14,'framesProcessed':10,'framesDropped':4},result.json()['streams'])
        self.assertEqual('platform',result.json()['scope'])
        self.assertNotIn('secret-stream',result.text)
        self.assertNotIn(self.project_id,result.text)

    def test_request_logs_use_server_identity_and_never_raw_input(self):
        with self.assertLogs('aiyolo.requests',level='INFO') as captured:
            response=self.client.get(self.project_path+'/alerts/export?token=TOP_SECRET',
                headers={**self.headers,'X-Request-Id':'TOP_SECRET','X-Operator-Id':'forged'})
        record=json.loads(captured.records[-1].getMessage())
        self.assertEqual(response.headers['x-request-id'],record['requestId'])
        self.assertEqual(self.project_id,record['projectId'])
        self.assertEqual(self.account_id,record['accountId'])
        self.assertEqual('/aiyoloapi/projects/{project_id}/alerts/export',record['route'])
        self.assertNotIn('TOP_SECRET',str(captured.output))
        self.assertNotIn('forged',str(captured.output))

    def test_recent_alert_limit_and_transport_logs_are_safe(self):
        for i in range(35):
            self.store.register({'eventId':str(i),'confirmedAtUs':i+1},project_id=self.project_id)
        response=self.client.get(self.project_path+'/alerts?limit=20',headers=self.headers)
        self.assertEqual(20,len(response.json()['events']))
        self.assertEqual(422,self.client.get(self.project_path+'/alerts?limit=101',headers=self.headers).status_code)
        record=logging.LogRecord('uvicorn.error',logging.INFO,'',1,'%s - "WebSocket %s" [accepted]',('ip','/ws?token=SECRET'),None)
        self.assertTrue(SafeWebSocketFilter().filter(record));self.assertNotIn('SECRET',record.getMessage())
        self.assertFalse(SafeAccessFilter().filter(record))

    def test_download_revocation_releases_export_slot(self):
        # One row: initial check, first batch, complete-file check, then first
        # transfer chunk. Revocation must abort transfer and release its slot.
        import app.project_reports as reports
        before=reports._slots._value
        with patch.object(reports,'assert_export_access',side_effect=[None,None,None,HTTPException(403,'revoked')]):
            with self.assertRaises(Exception):
                self.client.get(self.project_path+'/alerts/export',headers=self.headers)
        self.assertEqual(before,reports._slots._value)
        self.assertEqual(200,self.client.get(self.project_path+'/alerts/export',headers=self.headers).status_code)


class ReportingStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=DatabaseManager('sqlite:///'+str(Path(self.temp.name)/'reports.db'))
        Base.metadata.create_all(self.db.engine)
        self.store=AlertDispositionStore(self.db)
        with self.db.session() as session:
            session.add_all([ProjectRecord(project_id=p,project_code=p,display_name=p) for p in ('alpha','beta')])
        self.now=datetime.now(timezone.utc)

    def tearDown(self):
        self.db.close();self.temp.cleanup()

    def seed_audits(self,count=200):
        with self.db.session() as session:
            session.execute(insert(ProjectAuditEventRecord),[
                {'audit_id':f'{p}-{i:06}', 'project_id':p, 'occurred_at':self.now,
                 'action':'report.read' if i%2 else 'report.export','target_type':'report','outcome':'SUCCESS',
                 'request_id':f'request-{i}', 'change_summary':{'password':'SECRET','data':'x'*1024}}
                for p in ('alpha','beta') for i in range(count)])

    def test_filtered_keyset_pages_do_not_repeat_or_cross_scope(self):
        self.seed_audits()
        with patch.object(auth,'database',self.db):
            seen=[];cursor=None;filters={'action':'report.export','outcome':'SUCCESS'}
            while True:
                page=_audit_page('alpha',17,cursor,filters)
                seen += [r['auditId'] for r in page['events']]
                self.assertNotIn('SECRET',json.dumps(page))
                cursor=page['nextCursor']
                if cursor is None:break
                with self.assertRaises(HTTPException):_audit_page('beta',17,cursor,filters)
                with self.assertRaises(HTTPException):_audit_page('alpha',17,cursor,{'action':'report.read'})
            self.assertEqual(100,len(seen));self.assertEqual(100,len(set(seen)))
            self.assertTrue(all(s.startswith('alpha-') for s in seen))
            self.assertEqual([], _audit_page('alpha',25,None,{'since':(self.now+timedelta(days=1)).isoformat()})['events'])

    def test_feedback_database_projection_keeps_portable_reference(self):
        self.store.register({'eventId':'e','evidence':{'snapshotUri':'/private/frame.jpg'}},project_id='alpha')
        self.store.mark_false_positive('e','operator',project_id='alpha')
        output,count=prepare_export(self.store,'alpha',True,lambda:None)
        try:
            report=json.load(output)
        finally:output.close()
        self.assertEqual(1,count)
        self.assertEqual('evidence/frame.jpg',report['entries'][0]['image'])
        self.assertEqual(report['entries'],report['trainingEntries'])
        self.assertNotIn('/private',json.dumps(report))

    def test_retention_dry_run_hold_boundary_batches_and_repeat(self):
        cutoff=self.now-timedelta(days=365)
        with self.db.session() as session:
            session.execute(insert(ProjectAuditEventRecord),[
                {'audit_id':f'{p}-{i}', 'project_id':p,'occurred_at':cutoff-timedelta(seconds=1),
                 'action':'test','target_type':'report','outcome':'SUCCESS','change_summary':{}}
                for p in ('alpha','beta') for i in range(12)])
            session.add(ProjectAuditEventRecord(audit_id='boundary',project_id='alpha',occurred_at=cutoff,
                action='test',target_type='report',outcome='SUCCESS',change_summary={}))
            session.add(PlatformAuditEventRecord(audit_id='old-platform',occurred_at=cutoff-timedelta(seconds=1),
                action='test',target_type='report',outcome='SUCCESS',change_summary={}))
        dry=retain_audits(self.db,held_projects=['beta'],now=self.now)
        self.assertEqual(12,dry['eligible']['project_audit_events']);self.assertEqual(0,sum(dry['deleted'].values()))
        applied=retain_audits(self.db,held_projects=['beta'],now=self.now,apply=True,batch_size=5)
        self.assertEqual(12,applied['deleted']['project_audit_events'])
        self.assertEqual(1,applied['deleted']['platform_audit_events'])
        self.assertEqual(0,sum(retain_audits(self.db,held_projects=['beta'],now=self.now,apply=True)['deleted'].values()))
        with self.db.session() as session:
            self.assertIsNotNone(session.get(ProjectAuditEventRecord,'boundary'))
            self.assertEqual(4,session.scalar(select(func.count()).select_from(PlatformAuditEventRecord)))
        with self.assertRaises(ValueError):retain_audits(self.db,days=1,apply=True)
        with self.assertRaises(ValueError):retain_audits(self.db,held_projects=['missing'],apply=True)

    def test_large_project_reports_bounded_memory_and_indexed_audit_pages(self):
        # 20k alerts carrying 4 KiB evidence each, plus 20k audit rows, split
        # across two projects. Neither evidence nor foreign rows may escape.
        count=10_000
        with self.db.session() as session:
            for p in ('alpha','beta'):
                for batch in range(0,count,500):
                    session.execute(insert(AlertEventRecord),[
                        {'project_id':p,'event_id':f'event-{i:06}','created_at':self.now,'disposition_status':'OPEN',
                         'payload':{'eventId':f'event-{i:06}','label':'head','severity':'MAJOR',
                                    'confirmedAtUs':int(self.now.timestamp()*1e6),'evidence':{'snapshotDataUrl':'x'*4096}}}
                        for i in range(batch,batch+500)])
        self.seed_audits(count)
        tracemalloc.start();started=time.perf_counter()
        stats=DashboardStatsService(self.db,self.store).build('30d',{}, {}, 'alpha')
        stats_ms=(time.perf_counter()-started)*1000
        self.assertEqual(count,stats['summary']['totalEvents']);self.assertEqual(count,sum(b['count'] for b in stats['trend']))
        started=time.perf_counter();checks=[]
        output,rows=prepare_export(self.store,'alpha',False,lambda:checks.append(True))
        export_ms=(time.perf_counter()-started)*1000
        self.assertEqual(count,rows);self.assertGreater(len(checks),10)
        size=output.seek(0,2);output.close()
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        self.assertLess(peak,24*1024*1024)
        with patch.object(auth,'database',self.db):
            started=time.perf_counter();seen=set();cursor=None
            for _ in range(100):
                page=_audit_page('alpha',100,cursor)
                seen.update(r['auditId'] for r in page['events']);cursor=page['nextCursor']
            paging_ms=(time.perf_counter()-started)*1000
            self.assertEqual(count,len(seen));self.assertIsNone(cursor)
        with self.db.session() as session:
            plan=str(session.execute(text("EXPLAIN QUERY PLAN SELECT audit_id FROM project_audit_events WHERE project_id='alpha' ORDER BY julianday(occurred_at) DESC,audit_id DESC LIMIT 101")).all())
        self.assertIn('ix_project_audit_page_sqlite',plan)
        self.assertLess(stats_ms,15000);self.assertLess(export_ms,20000);self.assertLess(paging_ms,15000)
        print(json.dumps({'rowsPerProject':count,'projects':2,'statsMs':round(stats_ms,1),'exportMs':round(export_ms,1),
            'audit100PagesMs':round(paging_ms,1),'peakBytes':peak,'exportBytes':size,'queryPlan':plan}))

    def test_export_rechecks_authorization_and_closes_on_revocation(self):
        with self.db.session() as session:
            session.execute(insert(AlertEventRecord),[{'project_id':'alpha','event_id':str(i),'payload':{'eventId':str(i)}} for i in range(600)])
        calls=[]
        def check():
            calls.append(True)
            if len(calls)==3:raise HTTPException(403,'revoked')
        with self.assertRaises(HTTPException):prepare_export(self.store,'alpha',False,check)


if __name__=='__main__':unittest.main()
