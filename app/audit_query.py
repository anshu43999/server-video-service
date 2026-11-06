"""Shared validated audit filters and fingerprinted cursor scope."""
from datetime import datetime, timezone
from fastapi import HTTPException, Query


def audit_filters(action: str | None = Query(None, max_length=128),
                  actorAccountId: str | None = Query(None, max_length=36),
                  requestId: str | None = Query(None, max_length=128),
                  outcome: str | None = Query(None, pattern='^(SUCCESS|DENIED|FAILED)$'),
                  targetType: str | None = Query(None, max_length=128),
                  since: datetime | None = Query(None), until: datetime | None = Query(None)):
    if any(v is not None and v.tzinfo is None for v in (since, until)):
        raise HTTPException(422, detail='audit time must include timezone')
    if since and until and since > until:
        raise HTTPException(422, detail='audit time range is reversed')
    values = dict(action=action, actorAccountId=actorAccountId, requestId=requestId,
                  outcome=outcome, targetType=targetType, since=since, until=until)
    return {k: v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else v
            for k, v in values.items() if v is not None}
