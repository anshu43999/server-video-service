"""Real project/model/scene API setup for stream transport regressions."""
from test_project_model_assignments import ModelApiFixture


class StreamApiFixture(ModelApiFixture):
    def setUp(self):
        super().setUp()
        assigned = self._assign(headers=self.headers)
        self.assertEqual(200, assigned.status_code, assigned.text)
        created = self.client.post(self.project_path + '/scenes', headers=self.headers, json={
            'sceneId': 'transport', 'name': 'Transport fixture', 'inputTypes': ['video'],
            'expectedRevision': 0, 'models': [{
                'projectModelId': assigned.json()['projectModelId'],
                'position': 0, 'execution': 'single',
            }],
        })
        self.assertEqual(201, created.status_code, created.text)
        approved = self.client.post(self.project_path + '/scenes/transport/approval',
            headers=self.headers, json={'approved': True,
                'expectedRevision': created.json()['revision'], 'reason': 'Transport test review'})
        self.assertEqual(200, approved.status_code, approved.text)
        self.selection = {'sceneId': 'transport', 'planId': 'default',
                          'sceneRevision': approved.json()['revision']}
        self.streams_path = self.project_path + '/streams'
        # Preview requires a same-origin cookie, not a bearer token.
        login = self.client.post('/aiyoloapi/auth/login', json={
            'username': 'model-assignment-admin', 'password': 'temporary-test-password'})
        self.assertEqual(200, login.status_code, login.text)

    def create_stream(self, stream_id):
        response = self.client.post(self.streams_path, json={
            'stream_id': stream_id, **self.selection})
        self.assertEqual(201, response.status_code, response.text)
        return response
