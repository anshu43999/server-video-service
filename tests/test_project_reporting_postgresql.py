"""Run only against a fresh random schema; never migrate or delete public data."""
import json
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import insert, inspect, text

from app import auth
from app.alerts.disposition import AlertDispositionStore
from app.audit_retention import retain_audits
from app.dashboard import DashboardStatsService
from app.database import DatabaseManager, ProjectRecord, ProjectAuditEventRecord, AlertEventRecord
from app.project_management import _audit_page
from app.project_reports import prepare_export
from postgresql_support import isolated_postgresql_url


@unittest.skipUnless(os.environ.get('RUN_POSTGRES_TESTS')=='1','requires isolated PostgreSQL schema')
class ReportingPostgresTests(unittest.TestCase):
    def test_migration_reports_pagination_retention_and_performance(self):
        with isolated_postgresql_url('t13_reporting', revision='20261012_11') as url:
            config=Config('alembic.ini');config.set_main_option('sqlalchemy.url',url.replace('%','%%'))
            command.downgrade(config,'20261012_10');command.upgrade(config,'head');command.upgrade(config,'head');command.check(config)
            db=DatabaseManager(url)
            try:
                self.assertIn('ix_project_audit_page',{i['name'] for i in inspect(db.engine).get_indexes('project_audit_events')})
                now=datetime.now(timezone.utc)
                with db.session() as session:
                    session.add_all([ProjectRecord(project_id=p,project_code=p,display_name=p,created_at=now,updated_at=now) for p in ('alpha','beta')]);session.flush()
                    for p in ('alpha','beta'):
                        for offset in range(0,10000,500):
                            session.execute(insert(ProjectAuditEventRecord),[
                                {'audit_id':f'{p}-{i:06}', 'project_id':p,'occurred_at':now-timedelta(days=400),
                                 'action':'report.export','target_type':'report','outcome':'SUCCESS','change_summary':{'secret':'PRIVATE'}}
                                for i in range(offset,offset+500)])
                            session.execute(insert(AlertEventRecord),[
                                {'project_id':p,'event_id':f'event-{i:06}','created_at':now,'updated_at':now,'payload':{'eventId':f'event-{i:06}',
                                 'label':'head','severity':'MAJOR','confirmedAtUs':int(now.timestamp()*1e6),'evidence':{'snapshotDataUrl':'x'*4096}}}
                                for i in range(offset,offset+500)])
                with patch.object(auth,'database',db):
                    started=time.perf_counter();seen=set();cursor=None
                    for _ in range(100):
                        page=_audit_page('alpha',100,cursor,{'action':'report.export'})
                        seen.update(r['auditId'] for r in page['events']);cursor=page['nextCursor']
                        self.assertNotIn('PRIVATE',json.dumps(page))
                    audit_ms=(time.perf_counter()-started)*1000
                    self.assertEqual(10000,len(seen));self.assertIsNone(cursor)
                store=AlertDispositionStore(db);started=time.perf_counter()
                stats=DashboardStatsService(db,store).build('today',{}, {},'alpha')
                stats_ms=(time.perf_counter()-started)*1000;self.assertEqual(10000,stats['summary']['totalEvents'])
                started=time.perf_counter();output,count=prepare_export(store,'alpha',False,lambda:None)
                export_ms=(time.perf_counter()-started)*1000
                try:
                    self.assertEqual(10000,count);self.assertEqual(10000,json.load(output)['count'])
                finally:output.close()
                dry=retain_audits(db,held_projects=['beta']);self.assertEqual(10000,dry['eligible']['project_audit_events'])
                applied=retain_audits(db,held_projects=['beta'],apply=True)
                self.assertEqual(10000,applied['deleted']['project_audit_events'])
                self.assertEqual(0,sum(retain_audits(db,held_projects=['beta'],apply=True)['deleted'].values()))
                with db.session() as session:
                    self.assertEqual(10000,session.scalar(text("SELECT count(*) FROM project_audit_events WHERE project_id='beta'")))
                self.assertLess(audit_ms,20000);self.assertLess(stats_ms,15000);self.assertLess(export_ms,20000)
                print(json.dumps({'backend':'postgresql','rowsPerProject':10000,'projects':2,'audit100PagesMs':round(audit_ms,1),
                    'statsMs':round(stats_ms,1),'exportMs':round(export_ms,1)}))
            finally:db.close()
