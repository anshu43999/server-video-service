"""Current account admission and deliberately lossy audit text redaction."""
import re
from datetime import datetime, timezone

from sqlalchemy import select

from ..auth import authenticate, _credential, _session_hash
from ..database import AccountSessionRecord


class SessionActor(str):
    """Only server-created actors carry a session digest into the transaction."""
    def __new__(cls, account_id, session_hash):
        actor = super().__new__(cls, account_id)
        actor.session_hash = session_hash
        return actor


def session_valid(session, actor):
    if not isinstance(actor, SessionActor):
        # Internal workers have a durable accepted job and recheck its account.
        return True
    row = session.scalar(select(AccountSessionRecord).where(
        AccountSessionRecord.session_hash == actor.session_hash).with_for_update())
    if row is None or row.account_id != actor or row.revoked_at is not None:
        return False
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


def current_admin(request):
    principal = authenticate(request)
    if principal is None:
        return None, "authentication_required"
    if principal.legacy or principal.platform_role != "PLATFORM_ADMIN":
        return None, "platform_admin_required"
    return SessionActor(principal.account_id, _session_hash(_credential(request))), None


def audit_text(value):
    # Reasons remain useful prose. URLs and common secret forms have no place
    # in an audit trail; the original request is bound by its SHA-256 instead.
    value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*", "[redacted key]", value, flags=re.S)
    value = re.sub(r"(?i)https?://[^\s<>\"']+", "[redacted URL]", value)
    value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", value)
    value = re.sub(r"(?i)\b(token|password|secret|credential|access[_-]?key|private[_-]?key|signature)\s*[:=]\s*[^\s,;]+",
                   r"\1=[redacted]", value)
    return " ".join(value.split())[:1000] or "[empty reason]"
