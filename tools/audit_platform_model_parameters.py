"""Read-only legacy override differences. Requires an explicit database URL env var."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.database import (DEFAULT_PROJECT_ID, ModelParameterAuditRecord, ModelParameterProfileRecord,
    ProjectModelAssignmentRecord, ProjectSceneMemberRecord)


def differences(session):
    publications = {}
    for audit in session.scalars(select(ModelParameterAuditRecord).where(
            ModelParameterAuditRecord.project_id == DEFAULT_PROJECT_ID,
            ModelParameterAuditRecord.action == 'PUBLISHED').order_by(ModelParameterAuditRecord.id)):
        profile = audit.payload.get('snapshot') or {}
        publications[(profile.get('modelId'), profile.get('modelVersion'), profile.get('platform'))] = profile
    rows = []
    def add(kind, identity, project, model, version, platform, profile):
        published = publications.get((model, version, platform))
        rows.append(dict(kind=kind, identity=identity, projectId=project, modelId=model, version=version,
            platform=platform, legacyRevision=(profile or {}).get('revision'),
            publishedRevision=published.get('revision') if published else None,
            missingPublication=published is None,
            differentFields=[key for key in ('detection', 'alertRules')
                if (profile or {}).get(key) != (published or {}).get(key)]))
    for row in session.scalars(select(ModelParameterProfileRecord).where(ModelParameterProfileRecord.scope == 'PROJECT')):
        add('project_override', row.profile_key, row.project_id, row.model_id, row.model_version, row.platform, row.payload)
    for row in session.scalars(select(ProjectModelAssignmentRecord)):
        add('assignment_history', row.assignment_id, row.project_id, row.model_id, row.model_version,
            row.parameter_platform, row.parameter_snapshot)
    for row in session.scalars(select(ProjectSceneMemberRecord)):
        add('scene_history', f'{row.scene_id}/{row.member_id}', row.project_id, row.model_id, row.model_version,
            'android' if row.target == 'mobile' else 'server', row.parameter_snapshot)
    return dict(readOnly=True, automaticPublication=False, publishedProfiles=len(publications), rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-env', required=True, help='Name of an explicitly configured environment variable; no .env fallback')
    args = parser.parse_args()
    url = os.environ.get(args.database_url_env)
    if not url:
        parser.error('Explicit database URL environment variable is missing')
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == 'postgresql':
                connection.execute(text('SET TRANSACTION READ ONLY'))
            elif engine.dialect.name == 'sqlite':
                connection.execute(text('PRAGMA query_only=ON'))
            else:
                raise ValueError('Only PostgreSQL and SQLite are supported')
            with Session(bind=connection) as session:
                print(json.dumps(differences(session), ensure_ascii=False, indent=2))
            connection.rollback()
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
