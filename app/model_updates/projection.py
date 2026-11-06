"""Rebuildable registry/approval -> binding projection. Inventory is not authority."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import logging
import re
from uuid import uuid4

from sqlalchemy import select, text

from ..database import (AccountRecord, ProjectModelAssignmentRecord, ProjectSceneRecord, ProjectSceneMemberRecord,
                       ProjectRecord, ProjectMembershipRecord)
from ..project_model_policy import project_target_usable
from ..scene_parameter_digest import parameter_digest
from .models import Device, Inbox, DomainEvent, PushOutbox
from .protocol import UpdateError, digest, now, source_identity, target_digest, validate, TERMINAL

log = logging.getLogger(__name__)


def source_key(source):
    return source_identity(source)


def approved_artifact(model, parameters):
    if not project_target_usable(model, 'mobile') or model.get('signatureStatus') != 'signed':
        return None
    artifact = next((item for item in model.get('artifacts', [])
                     if item.get('platform') == 'android' and item.get('format') == 'tflite'), None)
    manifest = next((item for item in model.get('artifacts', [])
                     if item.get('artifactId') == 'android-manifest'), None)
    # Zero is the existing inherited/default profile revision; never invent one.
    if not artifact or not manifest or not parameters or parameters.get('revision', -1) < 0:
        return None
    result = dict(modelId=model['modelId'], version=model['version'], artifactDigest=artifact['sha256'].lower(),
        manifestDigest=manifest['sha256'].lower(), parameterRevision=parameters['revision'],
        parameterDigest=parameter_digest(parameters), sizeBytes=artifact['sizeBytes'])
    validate(result, 'artifact')
    return result


class Projection:
    def __init__(self, store, catalog, scenes):
        self.store, self.catalog, self.scenes = store, catalog, scenes
        from .lifecycle import LifecycleAuthority
        self.store.lifecycle_authority = LifecycleAuthority(self)

    def resolve(self, session, device, entry):
        try:
            return self._resolve(session, device, entry)
        except KeyError:
            # A retained source can outlive the exact release. It must cease
            # authorizing updates without rolling back its lifecycle fact.
            # Storage/parse failures still abort and retry the transaction.
            return None

    def _resolve(self, session, device, entry):
        source = entry['source']
        project_id = source['projectId']
        if not self.store.allowed(session, device, project_id):
            return None
        if source['kind'] == 'assignment':
            row = session.get(ProjectModelAssignmentRecord, source['assignmentId'], populate_existing=True)
            if row is None or row.project_id != project_id or not row.enabled or row.parameter_platform != 'android':
                return None
            model = self.catalog.get(row.model_id, row.model_version)
            artifact = approved_artifact(model, row.parameter_snapshot)
            if artifact is None:
                return None
            artifacts, revision = [artifact], row.revision
            criteria = 'activated' if entry['active'] else 'installed'
        else:
            scene = self.scenes._read(session, project_id, source['sceneId'])
            if scene is None or scene.get('deletedAt') or not scene['enabled'] or not scene['approved']:
                return None
            selection = source['selection']
            members = {item['memberId']: item for item in scene['models'] if item['target'] == 'mobile'}
            if any(item not in members for item in selection['memberIds']):
                return None
            for plan_id in selection['planIds']:
                plan = next((plan for plan in scene['plans'] if plan['planId'] == plan_id and plan['enabled']), None)
                if not plan or not set(plan['memberIds']).issubset(selection['memberIds']):
                    return None
            artifacts = []
            for member_id in selection['memberIds']:
                member = members[member_id]
                model = self.catalog.get(member['modelId'], member['version'])
                artifact = approved_artifact(model, self.scenes.reviewed_parameters(scene, member))
                if artifact is None:
                    return None
                artifacts.append(artifact)
            revision, criteria = scene['revision'], 'revision_selected'
        target = dict(source=deepcopy(source), approvalRevision=revision, successCriteria=criteria,
                      successCriteriaRevision=entry['selectionGeneration'], artifacts=artifacts)
        target['targetDigest'] = target_digest(target)
        target['updateId'] = digest([self.store.binding(device), target['targetDigest']])
        target['supersedesUpdateId'] = None
        validate(target, 'target')
        return target

    def authorized(self, session, device, item):
        """Current approval check at read/report time; never trusts inventory grants."""
        if not self.store.allowed(session, device, item['release']['projectId']):
            return False
        if item['target'] is None:
            return item['release']['modelId'] in self.related_models(session, device).get(item['release']['projectId'], set())
        if item['stage'] in {'invalidated', 'superseded'}:
            return True
        source = item['target']['source']
        entry = next((entry for entry in device.inventory if entry['source'] == source), None)
        if entry is None:
            return item['stage'] in {'invalidated', 'superseded'}
        try:
            current = self.resolve(session, device, entry)
        except (KeyError, ValueError, OSError, UpdateError):
            return False
        return bool(current and current['targetDigest'] == item['target']['targetDigest'])

    def related_models(self, session, device):
        projects = select(ProjectRecord.project_id).where(ProjectRecord.lifecycle_state == 'ACTIVE')
        account = self.store.account(session, device.account_id)
        if account.platform_role != 'PLATFORM_ADMIN':
            projects = projects.join(ProjectMembershipRecord, ProjectMembershipRecord.project_id == ProjectRecord.project_id).where(
                ProjectMembershipRecord.account_id == device.account_id, ProjectMembershipRecord.enabled.is_(True))
        result = {}
        for project_id in session.scalars(projects):
            assignments = session.scalars(select(ProjectModelAssignmentRecord).where(
                ProjectModelAssignmentRecord.project_id == project_id, ProjectModelAssignmentRecord.enabled.is_(True),
                ProjectModelAssignmentRecord.parameter_platform == 'android')).all()
            models = {row.model_id for row in assignments}
            models.update(session.scalars(select(ProjectSceneMemberRecord.model_id).join(ProjectSceneRecord,
                (ProjectSceneRecord.project_id == ProjectSceneMemberRecord.project_id) &
                (ProjectSceneRecord.scene_id == ProjectSceneMemberRecord.scene_id)).where(
                    ProjectSceneMemberRecord.project_id == project_id, ProjectSceneMemberRecord.target == 'mobile',
                    ProjectSceneRecord.enabled.is_(True), ProjectSceneRecord.approved.is_(True),
                    ProjectSceneRecord.deleted_at.is_(None))))
            result[project_id] = models
        return result

    def release_notices(self, session, device, registry):
        desired = set()
        # Last publication order, never lexical version ordering. Legacy entries
        # lacking history retain registry insertion order as their stable fallback.
        order = {(entry['modelId'], entry['version']): index for index, entry in enumerate(registry.get('models', []))}
        for index, event in enumerate(registry.get('modelHistory', []), len(order)):
            if event.get('status') == 'PUBLISHED':
                order[(event.get('modelId'), event.get('version'))] = index
        for project_id, model_ids in self.related_models(session, device).items():
            for model_id in model_ids:
                entries = sorted((entry for entry in registry.get('models', []) if entry.get('modelId') == model_id),
                                 key=lambda entry: order.get((model_id, entry.get('version')), -1), reverse=True)
                latest = None
                for entry in entries:
                    candidate = self.catalog.get(model_id, entry['version'])
                    if project_target_usable(candidate, 'mobile'):
                        latest = candidate
                        break
                if latest is None:
                    continue
                approved = session.scalar(select(ProjectModelAssignmentRecord.assignment_id).where(
                    ProjectModelAssignmentRecord.project_id == project_id, ProjectModelAssignmentRecord.model_id == model_id,
                    ProjectModelAssignmentRecord.model_version == latest['version'], ProjectModelAssignmentRecord.enabled.is_(True),
                    ProjectModelAssignmentRecord.parameter_platform == 'android'))
                if not approved:
                    approved = session.scalar(select(ProjectSceneMemberRecord.member_id).join(ProjectSceneRecord,
                        (ProjectSceneRecord.project_id == ProjectSceneMemberRecord.project_id) &
                        (ProjectSceneRecord.scene_id == ProjectSceneMemberRecord.scene_id)).where(
                            ProjectSceneMemberRecord.project_id == project_id,
                            ProjectSceneMemberRecord.model_id == model_id,
                            ProjectSceneMemberRecord.model_version == latest['version'],
                            ProjectSceneMemberRecord.target == 'mobile',
                            ProjectSceneRecord.enabled.is_(True), ProjectSceneRecord.approved.is_(True),
                            ProjectSceneRecord.deleted_at.is_(None)))
                if approved:
                    continue
                artifact = next((value for value in latest.get('artifacts', []) if value.get('format') == 'tflite' and
                                 value.get('platform') == 'android'), None)
                if not artifact:
                    continue
                release = dict(projectId=project_id, modelId=model_id, version=latest['version'], artifactDigest=artifact['sha256'].lower())
                update_id = digest([self.store.binding(device), 'release', release])
                desired.add(update_id)
                self.store._put(session, device, dict(updateId=update_id, itemRevision=1, kind='release_available',
                    target=None, release=release, discovery='pending_discovery', stage='waiting_approval', errorCode=None),
                    'release:' + digest([project_id, model_id]))
        return desired

    def one(self, device_id):
        with self.store.database.session() as session:
            # Match business writers: project -> binding -> child rows.
            peek = session.get(Device, device_id)
            if peek is None or peek.revoked:
                return True
            def projects_for(row):
                return sorted({entry['source']['projectId'] for entry in row.inventory} |
                    {entry['resourceKey']['projectId'] for entry in row.lifecycle_inventory if entry['resourceKey']})
            projects = projects_for(peek)
            for project in projects:
                session.scalar(select(ProjectRecord).where(ProjectRecord.project_id == project).with_for_update(read=True))
            device = session.scalar(select(Device).where(Device.device_id == device_id).with_for_update().execution_options(populate_existing=True))
            if device.revoked:
                return True
            # Inventory may change while waiting for the lock. Never acquire
            # another project lock after the binding lock (business lock order).
            if projects != projects_for(device):
                return False
            account = session.get(AccountRecord, device.account_id, populate_existing=True)
            if account is None or not account.enabled:
                device.revoked, device.push_token = True, None
                session.query(PushOutbox).filter(PushOutbox.device_id == device_id).delete()
                return True
            registry = self.catalog._load()
            self.store.refresh_lifecycle(session, device, registry)
            desired = self.release_notices(session, device, registry)
            for entry in device.inventory:
                source = entry['source']
                key = source_key(source)
                target = self.resolve(session, device, entry)
                if target is None:
                    continue
                desired.add(target['updateId'])
                # Current inventory equal to approved exact bytes/revision is
                # already reconciled, not an install request to repeat.
                if (entry['retainedRevision'] == target['approvalRevision'] and
                        entry['artifacts'] == target['artifacts']):
                    continue
                previous = session.scalars(select(Inbox).where(Inbox.device_id == device_id, Inbox.source_key == key)
                                           .order_by(Inbox.updated_at.desc())).all()
                old = next((row for row in previous if row.update_id != target['updateId'] and
                            row.payload['stage'] not in {'invalidated', 'superseded'}), None)
                if old is not None:
                    target['supersedesUpdateId'] = old.update_id
                artifact = target['artifacts'][0]
                release = dict(projectId=source['projectId'], modelId=artifact['modelId'],
                               version=artifact['version'], artifactDigest=artifact['artifactDigest'])
                self.store._put(session, device, dict(updateId=target['updateId'], itemRevision=1, kind='update_ready',
                    target=target, release=release, discovery='pending_discovery', stage='available', errorCode=None), key)
            for row in session.scalars(select(Inbox).where(Inbox.device_id == device_id)).all():
                if row.update_id in desired or row.payload['stage'] in {'invalidated', 'superseded'}:
                    continue
                if row.payload['target'] is None:
                    # Waiting release notices are informational. Their removal
                    # is represented by a terminal item, not inferred directory absence.
                    item = deepcopy(row.payload)
                    item['stage'], item['itemRevision'] = 'superseded', item['itemRevision'] + 1
                    row.authority_revision = item['itemRevision']
                    row.payload = item
                    self.store._change(session, device, row)
                    continue
                active_source = next((entry for entry in device.inventory if source_key(entry['source']) == row.source_key), None)
                replacement = self.resolve(session, device, active_source) if active_source else None
                # Ordinary approval replacement coalesces one successor; never
                # resets the executing download or authorizes its old commit.
                running = row.payload['stage'] in {'downloading', 'verifying', 'staged', 'warming', 'committing'}
                if (replacement is not None and running and
                        replacement['source']['sourceEpoch'] == row.payload['target']['source']['sourceEpoch'] and
                        replacement['successCriteriaRevision'] == row.payload['target']['successCriteriaRevision'] and
                        not (active_source['retainedRevision'] == replacement['approvalRevision'] and
                             active_source['artifacts'] == replacement['artifacts'])):
                    continue
                item = deepcopy(row.payload)
                item['stage'] = 'superseded' if replacement else 'invalidated'
                item['errorCode'] = 'target_changed' if replacement else 'access_revoked'
                item['itemRevision'] += 1
                row.authority_revision = item['itemRevision']
                row.payload = item
                self.store._change(session, device, row, 'upsert' if replacement else 'invalidate')
            return True

    def scan(self):
        self.store.require_storage()
        start = now()
        # Registry read failures abort before acknowledging domain outbox facts.
        self.catalog._load()
        offset, processed, failed = None, 0, 0
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='model-updates') as pool:
            while True:
                with self.store.database.session() as session:
                    query = select(Device.device_id).where(Device.revoked.is_(False)).order_by(Device.device_id).limit(200)
                    if offset:
                        query = query.where(Device.device_id > offset)
                    devices = session.scalars(query).all()
                if not devices:
                    break
                batches = [devices[start:start + 100] for start in range(0, len(devices), 100)]
                for successes, failures in pool.map(self._batch, batches):
                    processed += successes
                    failed += failures
                offset = devices[-1]
        if not failed:
            with self.store.database.session() as session:
                for event in session.scalars(select(DomainEvent).where(DomainEvent.processed_at.is_(None), DomainEvent.created_at <= start)):
                    event.processed_at = now()
        return {'processedDevices': processed, 'failedDevices': failed, 'elapsedSeconds': (now() - start).total_seconds()}

    def _batch(self, devices):
        # Two 100-device batches across processes. Keep the advisory lease in a
        # separate transaction; each binding still commits independently. A
        # crash releases the slot and unacknowledged source events are replayed.
        with self.store.database.session() as lease:
            if self.store.database.backend == 'postgresql':
                acquired = any(lease.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),
                    {'key': key}) for key in (1110201, 1110202))
                if not acquired:
                    return 0, len(devices)
            results = [self._safe_one(device_id) for device_id in devices]
            return sum(results), len(results) - sum(results)

    def _safe_one(self, device_id):
        try:
            return self.one(device_id)
        except Exception:
            # No payload/account/token in logs; failed transactions keep all facts.
            log.warning('model update projection failed')
            return False
