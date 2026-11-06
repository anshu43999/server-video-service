"""M112 current authority -> facts on the M111 binding/sequence, never grants.

No TTL or transport event is evidence of removal. Only permanent registry
history and the scene soft-delete row can produce a removed result.
"""
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from ..database import ProjectModelAssignmentRecord, ProjectSceneRecord
from ..project_model_policy import project_target_usable
from .protocol import digest, timestamp, byte_size, validate, UpdateError, MAX_INTEGER, ITEM_BYTES, PAGE_BYTES, now
from .models import Change, PushOutbox, Receipt


def enabled(device):
    return 1 in device.capabilities.get('resourceLifecycleVersions', [])


def binding(device):
    return dict(serviceOrigin=device.origin, accountId=device.account_id,
                deviceId=device.device_id, bindingEpoch=device.epoch)


def ledger_key(entry):
    return 'lifecycle:' + entry['inventoryEntryId']


def content(result):
    return {key: value for key, value in result.items() if key != 'confirmedAt'}


def result(resource, reason='unknown'):
    distribution, authorization = {
        'unknown': ('unknown', 'unknown'), 'current': ('available', 'eligible'),
        'project_grant_removed': ('available', 'denied'),
        'distribution_stopped': ('stopped', 'denied'), 'release_revoked': ('stopped', 'denied'),
        'scene_disabled': ('stopped', 'denied'), 'release_removed': ('removed', 'denied'),
        'scene_removed': ('removed', 'denied'),
    }[reason]
    return dict(visibility='visible', resourceKey=deepcopy(resource), distributionState=distribution,
                authorizationState=authorization, reasonCode=reason,
                confirmedAt=None if reason == 'unknown' else timestamp())


def matching_artifact(model, resource):
    return next((a for a in model.get('artifacts', []) if a.get('artifactId') == resource['artifactId'] and
                 a.get('sha256', '').lower() == resource['artifactSha256'] and
                 (a.get('target') == resource['target'] or
                  a.get('platform') == ('android' if resource['target'] == 'mobile' else 'server'))), None)


def durable_removal(row, resource):
    # Legacy UNINSTALLED rows without a durable operation/identity are not proof
    # that this exact retained artifact was removed.
    if (row.get('modelId') != resource['modelId'] or row.get('version') != resource['version'] or
            row.get('status') != 'UNINSTALLED' or type(row.get('lifecycleRevision')) is not int or
            row['lifecycleRevision'] < 1 or not row.get('operationId') or not matching_artifact(row, resource)):
        return False
    try:
        return datetime.fromisoformat(row['deletedAt'].replace('Z', '+00:00')).tzinfo is not None
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


class LifecycleAuthority:
    def __init__(self, projection):
        self.projection = projection

    def __call__(self, session, device, entry, registry=None):
        p, resource = self.projection, entry['resourceKey']
        if resource is None:
            return result(None)
        project = resource['projectId']
        if not p.store.allowed(session, device, project):
            return dict(visibility='opaque', authorizationState='denied', reasonCode='scope_inaccessible')
        source = resource['grantSource']
        scene = None
        if source['kind'] == 'suite':
            row = session.get(ProjectSceneRecord, (project, source['sceneId']), populate_existing=True)
            if row is None:
                return result(resource)
            if row.deleted_at is not None:
                return result(resource, 'scene_removed' if resource['kind'] == 'scene_revision'
                              else 'project_grant_removed')
            if not row.enabled:
                return result(resource, 'scene_disabled' if resource['kind'] == 'scene_revision'
                              else 'project_grant_removed')
            if not row.approved or row.revision != source['sceneRevision']:
                return result(resource, 'project_grant_removed')
            scene = p.scenes._read(session, project, source['sceneId'])
            plan = next((plan for plan in scene['plans'] if plan['planId'] == source['planId'] and plan['enabled']), None)
            if plan is None:
                return result(resource, 'project_grant_removed')
            members = {member['memberId']: member for member in scene['models']
                       if member['target'] == resource['target']}
            selection = next((item['source']['selection'] for item in device.inventory
                              if item['source']['kind'] == 'scene' and
                              item['source']['projectId'] == project and
                              item['source']['sceneId'] == source['sceneId'] and
                              item['source']['selectionDigest'] == source['selectionDigest']), None)
            if selection is None:
                selection = dict(planIds=[source['planId']], memberIds=sorted(plan['memberIds']))
                if source['selectionDigest'] != digest(selection):
                    return result(resource)
            selected_plans = [next((p for p in scene['plans'] if p['planId'] == ident and p['enabled']), None)
                              for ident in selection['planIds']]
            if (source['planId'] not in selection['planIds'] or
                    any(member not in members for member in selection['memberIds']) or
                    any(p is None or not set(p['memberIds']).issubset(selection['memberIds']) for p in selected_plans)):
                return result(resource, 'project_grant_removed')
            if resource['kind'] == 'scene_revision':
                if resource['incarnation'] != source['sceneId']:
                    return result(resource, 'project_grant_removed')
                for member_id in selection['memberIds']:
                    member = members[member_id]
                    try:
                        p.scenes._validated_artifacts(member)
                    except (KeyError, ValueError, OSError):
                        return result(resource)
                    except Exception as exc:
                        if getattr(exc, 'status_code', None) is not None:
                            return result(resource, 'project_grant_removed')
                        raise
                return result(resource, 'current')
            member = members.get(source['memberId'])
            if (not member or source['memberId'] not in plan['memberIds'] or
                    member['modelId'] != resource['modelId'] or member['version'] != resource['version']):
                return result(resource, 'project_grant_removed')

        registry = registry if registry is not None else p.catalog._load()
        if any(durable_removal(row, resource) for row in registry.get('modelHistory', [])):
            return result(resource, 'release_removed')
        try:
            model = p.catalog.get(resource['modelId'], resource['version'])
        except KeyError:
            return result(resource)
        if model.get('status') == 'REVOKED':
            return result(resource, 'release_revoked')
        if model.get('status') == 'DEPRECATED':
            return result(resource, 'distribution_stopped')
        if source['kind'] == 'standalone':
            row = session.get(ProjectModelAssignmentRecord, source['assignmentId'], populate_existing=True)
            if (row is None or row.project_id != project or not row.enabled or row.model_id != resource['modelId'] or
                    row.model_version != resource['version'] or
                    row.parameter_platform != ('android' if resource['target'] == 'mobile' else 'server')):
                return result(resource, 'project_grant_removed')
        artifact = matching_artifact(model, resource)
        if not artifact or not project_target_usable(model, resource['target']):
            return result(resource, 'project_grant_removed')
        if resource['target'] == 'mobile' and model.get('signatureStatus') != 'signed':
            return result(resource, 'project_grant_removed')
        return result(resource, 'current')


class LifecycleStoreMixin:
    """All methods run under the existing M111 binding lock and transaction."""

    def lifecycle_inventory_update(self, device, body, epochs, present):
        entries = body.get('lifecycleEntries', [])
        if enabled(device) != ('lifecycleEntries' in body):
            raise UpdateError(409, 'target_changed')
        ids = [entry['inventoryEntryId'] for entry in entries]
        if len(set(ids)) != len(ids):
            raise UpdateError(400, 'invalid_request')
        for entry in entries:
            resource = entry['resourceKey']
            if resource and resource['kind'] == 'scene_revision':
                source = resource['grantSource']
                if any(resource[k] != source[k] for k in ('sceneId', 'sceneRevision', 'selectionDigest')):
                    raise UpdateError(400, 'invalid_request')
            key, epoch = ledger_key(entry), entry['sourceEpoch']
            present.add(key)
            old = epochs.get(key)
            identity = digest(resource)
            if old and (epoch < old['epoch'] or identity != old['resourceDigest'] or
                        epoch == old['epoch'] and old['retired']):
                raise UpdateError(409, 'target_changed')
            state = deepcopy(old or {})
            if old is None or epoch != old['epoch']:
                state.update(reportSeq=0, stage=None)
            state.update(epoch=epoch, resourceDigest=identity, retired=False)
            epochs[key] = state
        return deepcopy(entries)

    def lifecycle_outcome(self, session, device, entry, registry=None):
        authority = getattr(self, 'lifecycle_authority', None)
        if authority is None:
            raise UpdateError(503, 'temporarily_unavailable')
        outcome = authority(session, device, entry, registry)
        old = device.lifecycle_facts.get(entry['inventoryEntryId'])
        state = device.source_epochs[ledger_key(entry)]
        # Opaque remains opaque even if a terminal identity was previously known.
        if outcome['visibility'] != 'opaque':
            if state.get('terminalResult'):
                outcome = deepcopy(state['terminalResult'])
            elif (outcome.get('reasonCode') == 'unknown' and old and
                  old['result']['authorizationState'] == 'denied'):
                outcome = deepcopy(old['result'])
        return outcome

    def refresh_lifecycle(self, session, device, registry):
        if not enabled(device) or device.inventory_revision == 0:
            return
        facts, epochs = deepcopy(device.lifecycle_facts), deepcopy(device.source_epochs)
        for entry in device.lifecycle_inventory:
            key = entry['inventoryEntryId']
            old = facts.get(key)
            outcome = self.lifecycle_outcome(session, device, entry, registry)
            same = old and old['sourceEpoch'] == entry['sourceEpoch'] and content(old['result']) == content(outcome)
            if same:
                continue
            revision = old['lifecycleRevision'] + 1 if old else 1
            if revision > MAX_INTEGER:
                raise UpdateError(413, 'capacity_exceeded')
            fact = dict(kind='resource_lifecycle', binding=binding(device), inventoryRevision=device.inventory_revision,
                        inventoryEntryId=key, sourceEpoch=entry['sourceEpoch'],
                        lifecycleItemId=old['lifecycleItemId'] if old else str(uuid4()),
                        lifecycleRevision=revision, result=outcome)
            validate(fact, 'lifecycle_fact')
            if byte_size(fact) > ITEM_BYTES or device.sequence >= MAX_INTEGER:
                raise UpdateError(413, 'capacity_exceeded')
            facts[key] = fact
            if outcome.get('distributionState') == 'removed':
                epochs[ledger_key(entry)]['terminalResult'] = deepcopy(outcome)
            device.sequence += 1
            session.add(Change(device_id=device.device_id, sequence=device.sequence, update_id=None,
                payload=dict(sequence=device.sequence, operation='lifecycle', item=deepcopy(fact))))
            self._dirty_lifecycle(session, device)
        # Retired watermarks stay bounded and survive transport log compaction.
        if byte_size(facts) > 16 * PAGE_BYTES or byte_size(epochs) > 2 * PAGE_BYTES:
            raise UpdateError(413, 'capacity_exceeded')
        device.lifecycle_facts, device.source_epochs = facts, epochs

    @staticmethod
    def _dirty_lifecycle(session, device):
        push = session.get(PushOutbox, device.device_id)
        if push is None:
            push = PushOutbox(device_id=device.device_id)
            session.add(push)
        if push.dirty_since is None or push.sent_sequence >= push.dirty_sequence:
            push.dirty_since = now()
        push.dirty_sequence = device.sequence
        session.flush()

    def lifecycle_snapshot(self, session, device):
        """No success snapshot until every accepted inventory entry has a fact."""
        if not enabled(device):
            return [], []
        if device.inventory_revision == 0:
            raise UpdateError(409, 'target_changed')
        facts = []
        entries = sorted(device.lifecycle_inventory, key=lambda e: e['inventoryEntryId'])
        for entry in entries:
            fact = device.lifecycle_facts.get(entry['inventoryEntryId'])
            if not fact or fact['sourceEpoch'] != entry['sourceEpoch']:
                raise UpdateError(503, 'temporarily_unavailable')
            fact = deepcopy(fact)
            fact['inventoryRevision'] = device.inventory_revision
            self.lifecycle_read_guard(session, device, fact, 'snapshot_expired')
            facts.append(fact)
        return facts, dict(inventoryRevision=device.inventory_revision, inventoryCount=len(entries),
                           inventoryDigest=digest(entries))

    def lifecycle_read_guard(self, session, device, fact, error='cursor_expired'):
        entry = next((e for e in device.lifecycle_inventory if e['inventoryEntryId'] == fact['inventoryEntryId']), None)
        if (not enabled(device) or not entry or fact['binding'] != binding(device) or
                fact['inventoryRevision'] != device.inventory_revision or fact['sourceEpoch'] != entry['sourceEpoch'] or
                content(self.lifecycle_outcome(session, device, entry)) != content(fact['result'])):
            raise UpdateError(410, error)

    def lifecycle_report(self, session, device, report):
        event_id, identity = report['eventId'], digest(report)
        existing = session.get(Receipt, (device.device_id, event_id))
        entry = next((e for e in device.lifecycle_inventory if e['inventoryEntryId'] == report['inventoryEntryId']), None)
        state = device.source_epochs.get(ledger_key(report))
        fact = device.lifecycle_facts.get(report['inventoryEntryId'])
        ack = dict(eventId=event_id, outcome='accepted', permanent=False, errorCode=None)
        # Retired sources may still finish their own cleanup, never an older epoch.
        valid = enabled(device) and report['binding'] == binding(device) and state and state['epoch'] == report['sourceEpoch']
        if not valid:
            ack.update(outcome='rejected', permanent=True, errorCode='target_changed')
        elif existing:
            ack = deepcopy(existing.result)
            if existing.payload_digest != identity:
                ack.update(outcome='rejected', permanent=True, errorCode='event_payload_conflict')
            elif ack['outcome'] == 'accepted':
                ack['outcome'] = 'duplicate'
            return ack
        elif report['reportSeq'] <= state.get('reportSeq', 0):
            ack.update(outcome='stale', permanent=True, errorCode='stale_report')
        elif 'lifecycleItemId' in report and (not fact or report['lifecycleItemId'] != fact['lifecycleItemId'] or
                                             report['lifecycleRevision'] > fact['lifecycleRevision']):
            ack.update(outcome='rejected', permanent=True, errorCode='target_changed')
        elif 'lifecycleRevision' in report and report['lifecycleRevision'] < fact['lifecycleRevision']:
            ack.update(outcome='stale', permanent=True, errorCode='stale_report')
        elif report['stage'] in {'discovered', 'authorization_invalidated'} and not entry:
            ack.update(outcome='rejected', permanent=True, errorCode='target_changed')
        elif (report['stage'] == 'authorization_invalidated' and fact['result']['authorizationState'] != 'denied'):
            ack.update(outcome='rejected', permanent=True, errorCode='target_changed')
        else:
            # Discovery cannot undo cleanup even when delivered with a higher seq.
            stage = report['stage']
            if state.get('stage') in {'references_removed', 'files_cleaned', 'cleanup_blocked'} and stage in {
                    'discovered', 'authorization_invalidated'}:
                ack.update(outcome='stale', permanent=True, errorCode='stale_report')
            elif state.get('stage') == 'files_cleaned' and stage != 'files_cleaned':
                ack.update(outcome='stale', permanent=True, errorCode='stale_report')
            else:
                epochs = deepcopy(device.source_epochs)
                epochs[ledger_key(report)].update(reportSeq=report['reportSeq'], stage=stage)
                device.source_epochs = epochs
        if existing is None:
            session.add(Receipt(device_id=device.device_id, event_id=event_id, update_id=None,
                                payload_digest=identity, payload=deepcopy(report), result=deepcopy(ack)))
            session.flush()
        return ack
