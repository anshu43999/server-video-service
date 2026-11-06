"""Business mutation markers, committed with their assignment/scene writes."""
from copy import deepcopy
from uuid import uuid4
from sqlalchemy import event
from .models import DomainEvent

_notifier = None


def configure_notifier(notifier):
    global _notifier
    _notifier = notifier


def add_domain_event(session, project_id, kind, payload):
    session.add(DomainEvent(event_id=str(uuid4()), project_id=project_id,
                            payload={'kind': kind, 'truth': deepcopy(payload)}))
    if not session.info.get('model_update_notify'):
        session.info['model_update_notify'] = True
        def committed(current):
            if not current.in_nested_transaction() and _notifier is not None:
                _notifier()
        event.listen(session, 'after_commit', committed)
