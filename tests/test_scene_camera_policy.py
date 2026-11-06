import unittest
from copy import deepcopy
from pydantic import ValidationError
from app.project_scenes import CameraPolicy
import test_project_scenes as scenes
import test_project_scene_suite_persistence as persistence


class CameraPolicyTests(unittest.TestCase):
    def test_defaults_and_strict_boundaries(self):
        self.assertEqual(5, CameraPolicy().frameInterval)
        for changes in ({'frameInterval': 0}, {'frameInterval': 121}, {'frameInterval': True},
                        {'frameInterval': 1.5}, {'frameInterval': '5'}, {'batchTimeoutMs': 750},
                        {'batchTimeoutMs': 10001}, {'resultMaxAgeMs': 4999},
                        {'overlayHoldMs': -1}, {'overlayHoldMs': 3001}, {'unknown': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                CameraPolicy(**changes)
        CameraPolicy(frameInterval=120, batchTimeoutMs=10000, resultMaxAgeMs=15000, overlayHoldMs=0)


class CameraPolicyApiTests(scenes.SceneApiTests):
    def test_policy_roundtrip_approval_resolve_and_permission(self):
        policy = dict(frameInterval=9, batchTimeoutMs=7000, resultMaxAgeMs=8000, overlayHoldMs=2000)
        plan = dict(planId='camera', name='相机', inputTypes=['video'], memberIds=['helmet'],
                    execution='single', enabled=True, cameraPolicy=policy)
        body = {**self.scene, 'models': [{**self.member('helmet', target='mobile'), 'memberId': 'helmet'}], 'plans': [plan]}
        result = self.create(body)
        self.assertEqual(201, result.status_code, result.text)
        self.assertEqual(policy, result.json()['plans'][0]['cameraPolicy'])
        path = self.scenes + '/safety'
        approved = self.client.post(path + '/approval', headers=self.owner, json={
            'approved': True, 'expectedRevision': 1, 'reason': 'isolated policy review'})
        self.assertEqual(200, approved.status_code, approved.text)
        catalog = self.client.get(self.scenes, headers=self.user).json()['scenes'][0]
        self.assertEqual(policy, catalog['plans'][0]['cameraPolicy'])
        resolve = dict(planId='camera', target='mobile', inputType='video', expectedRevision=2, clientContractVersion=2)
        resolved = self.client.post(path + '/plans/camera/resolve', headers=self.user, json=resolve)
        self.assertEqual(200, resolved.status_code, resolved.text)
        self.assertEqual(policy, resolved.json()['cameraPolicy'])
        changed = deepcopy(plan); changed['cameraPolicy']['frameInterval'] = 11
        denied = self.client.put(path + '/plans', headers=self.user, json={'plans':[changed], 'expectedRevision':2})
        self.assertEqual(403, denied.status_code)
        updated = self.client.put(path + '/plans', headers=self.owner, json={'plans':[changed], 'expectedRevision':2})
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertFalse(updated.json()['approved'])
        self.assertEqual(3, updated.json()['revision'])
        stale = self.client.post(path + '/plans/camera/resolve', headers=self.user, json=resolve)
        self.assertNotEqual(200, stale.status_code)

    def test_invalid_policy_is_rejected_before_creation(self):
        plan = dict(planId='camera', name='相机', inputTypes=['video'], memberIds=['helmet'],
                    execution='single', cameraPolicy={'frameInterval': True})
        result = self.create({**self.scene, 'models':[{**self.member('helmet'), 'memberId':'helmet'}], 'plans':[plan]})
        self.assertEqual(422, result.status_code)
        self.assertEqual([], self.client.get(self.scenes, headers=self.owner).json()['scenes'])


class CameraPolicyPersistenceTests(persistence.SceneSuitePersistenceTests):
    def test_camera_policy_survives_reload_and_is_not_shared_by_plans(self):
        changes = self.changes()
        policy = dict(frameInterval=12, batchTimeoutMs=8000, resultMaxAgeMs=10000, overlayHoldMs=0)
        changes['plans'][1]['cameraPolicy'] = policy
        saved = self.store.save('p1', 'safety', changes, 0, creating=True)
        reopened = persistence.ProjectScenes(self.db, self.catalog, self.assignments)
        loaded = reopened.get('p1', 'safety')
        self.assertEqual(saved, loaded)
        self.assertEqual(policy, next(p for p in loaded['plans'] if p['planId']=='video')['cameraPolicy'])
        self.assertEqual(5, next(p for p in loaded['plans'] if p['planId']=='image')['cameraPolicy']['frameInterval'])
