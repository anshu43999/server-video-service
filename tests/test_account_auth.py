import unittest
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import reset_memory_auth_for_tests
from app.config import settings
from app.database import AccountRecord, AccountSessionRecord, Base, database
from app.main import app


TEST_DIRECTORY = Path(__file__).resolve().parent


class AccountAuthApiTests(unittest.TestCase):
    def setUp(self):
        self.old_database_url = database.url
        self.old_deployment_env = settings.deployment_env
        self.old_admin_token = settings.admin_token
        self.old_mobile_token = settings.mobile_token
        temporary_database = tempfile.NamedTemporaryFile(suffix=".db", dir=TEST_DIRECTORY, delete=False)
        temporary_database.close()
        self.temp_database_path = Path(temporary_database.name)
        database.close()
        database.url = f"sqlite:///{self.temp_database_path.as_posix()}"
        Base.metadata.create_all(database.engine)
        settings.admin_token = None
        settings.mobile_token = None
        settings.deployment_env = "production"
        reset_memory_auth_for_tests()
        self.client = TestClient(app)

    def tearDown(self):
        reset_memory_auth_for_tests()
        database.close()
        database.url = self.old_database_url
        self.temp_database_path.unlink(missing_ok=True)
        settings.deployment_env = self.old_deployment_env
        settings.admin_token = self.old_admin_token
        settings.mobile_token = self.old_mobile_token

    def test_setup_login_me_logout_and_business_gate(self):
        status = self.client.get("/api/auth/status").json()
        self.assertTrue(status["setupRequired"])
        self.assertFalse(status["authenticated"])
        self.assertEqual(self.client.get("/api/models").status_code, 401)

        setup = self.client.post("/api/auth/setup", json={"username": "Admin", "password": "correct-horse-1"})
        self.assertEqual(setup.status_code, 200)
        self.assertEqual(setup.json()["user"], {"username": "admin", "role": "admin"})
        token = setup.json()["accessToken"]
        self.assertGreater(len(token), 40)

        anonymous = TestClient(app)
        self.assertEqual(anonymous.get("/api/models").status_code, 401)
        self.assertEqual(anonymous.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").json()["username"], "admin")

        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

        failed = self.client.post("/api/auth/login", json={"username": "admin", "password": "incorrect-1"})
        self.assertEqual(failed.status_code, 401)
        login = self.client.post("/api/auth/login", json={"username": "admin", "password": "correct-horse-1"})
        self.assertEqual(login.status_code, 200)
        bearer = {"Authorization": f"Bearer {login.json()['accessToken']}"}
        self.assertEqual(self.client.get("/api/auth/me", headers=bearer).status_code, 200)

    def test_admin_can_create_operator_and_operator_cannot_use_admin_api(self):
        setup = self.client.post("/api/auth/setup", json={"username": "admin", "password": "correct-horse-1"})
        admin = {"Authorization": f"Bearer {setup.json()['accessToken']}"}
        created = self.client.post(
            "/api/auth/users",
            headers=admin,
            json={"username": "inspector", "password": "operator-pass-1", "role": "operator"},
        )
        self.assertEqual(created.status_code, 200)
        login = self.client.post("/api/auth/login", json={"username": "inspector", "password": "operator-pass-1"})
        mobile = {"X-Video-Service-Token": login.json()["accessToken"]}
        self.assertEqual(self.client.get("/api/models", headers=mobile).status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard/stats", headers=mobile).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/users", headers=mobile).status_code, 401)

    def test_password_and_session_are_not_returned_by_user_listing(self):
        setup = self.client.post("/api/auth/setup", json={"username": "admin", "password": "correct-horse-1"})
        users = self.client.get(
            "/api/auth/users",
            headers={"Authorization": f"Bearer {setup.json()['accessToken']}"},
        )
        payload = users.text.lower()
        self.assertNotIn("password", payload)
        self.assertNotIn("session", payload)
        self.assertNotIn(setup.json()["accessToken"], payload)

    def test_database_stores_password_hash_and_session_digest_only(self):
        password = "correct-horse-1"
        setup = self.client.post("/api/auth/setup", json={"username": "admin", "password": password})
        token = setup.json()["accessToken"]

        with database.session() as session:
            account = session.get(AccountRecord, "admin")
            sessions = session.query(AccountSessionRecord).all()

        self.assertIsNotNone(account)
        self.assertTrue(account.password_hash.startswith("pbkdf2_sha256$"))
        self.assertNotIn(password, account.password_hash)
        self.assertEqual(1, len(sessions))
        self.assertEqual(64, len(sessions[0].session_hash))
        self.assertNotEqual(token, sessions[0].session_hash)
        self.assertIn("HttpOnly", setup.headers["set-cookie"])


if __name__ == "__main__":
    unittest.main()
