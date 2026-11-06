"""Operator-invoked retention. No automatic deletion and no deletion API."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select
from .database import ProjectAuditEventRecord, PlatformAuditEventRecord, ProjectRecord


def retain_audits(database, *, days=365, batch_size=500, apply=False, held_projects=(), now=None):
    if not database.enabled:
        raise ValueError('retention requires a persistent database')
    if not 90 <= days <= 36500 or not 1 <= batch_size <= 5000:
        raise ValueError('retention requires 90..36500 days and batch size 1..5000')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('retention time must include timezone')
    cutoff = now - timedelta(days=days)
    held_projects = tuple(set(held_projects))
    with database.session() as session:
        found = set(session.scalars(select(ProjectRecord.project_id).where(ProjectRecord.project_id.in_(held_projects))))
        if found != set(held_projects):
            raise ValueError('unknown legal-hold project; refusing retention')
    result = {'mode':'apply' if apply else 'dry-run', 'cutoff':cutoff.isoformat(), 'days':days,
              'heldProjects':list(held_projects), 'eligible':{}, 'deleted':{}}
    for model in (ProjectAuditEventRecord, PlatformAuditEventRecord):
        criteria = [model.occurred_at < cutoff]
        if model is ProjectAuditEventRecord and held_projects:
            criteria.append(model.project_id.not_in(held_projects))
        with database.session() as session:
            result['eligible'][model.__tablename__] = session.scalar(select(func.count()).select_from(model).where(*criteria))
        total = 0
        if apply:
            while True:
                with database.session() as session:
                    ids = list(session.scalars(select(model.audit_id).where(*criteria)
                               .order_by(model.occurred_at, model.audit_id).limit(batch_size).with_for_update(skip_locked=True)))
                    if not ids:
                        break
                    deleted = session.execute(delete(model).where(model.audit_id.in_(ids), *criteria)).rowcount
                    total += deleted
                    # Each committed batch records its own recoverable boundary;
                    # process interruption cannot leave unaudited deletion.
                    session.add(PlatformAuditEventRecord(audit_id=str(uuid4()), occurred_at=now,
                        action='audit.retention', target_type=model.__tablename__, outcome='SUCCESS',
                        change_summary={'cutoff':cutoff.isoformat(), 'deleted':deleted,
                                        'heldProjects':list(held_projects)}, request_id=str(uuid4())))
        result['deleted'][model.__tablename__] = total
    return result
