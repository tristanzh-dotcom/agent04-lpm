import unittest
from pathlib import Path

from backend import app_server
from backend.app_server import app


class AppServerTests(unittest.TestCase):
    def test_entity_db_path_resolves_inside_current_repo(self):
        repo_root = Path(__file__).resolve().parents[1]
        expected_path = repo_root / "tests" / "sandbox_limb_workbench.db"

        self.assertEqual(Path(app_server.DB_PATH), expected_path)
        self.assertEqual(Path(app_server.query_engine.db_path), expected_path)
        self.assertNotIn("Local-photo-model", app_server.DB_PATH)

    def test_root_route_explains_available_entity_api(self):
        client = app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "SUCCESS")
        self.assertEqual(payload["service"], "LIMB Entity Inner Core")
        self.assertIn("/api/entities/list", payload["routes"])
        self.assertIn("/api/entities/search", payload["routes"])


if __name__ == "__main__":
    unittest.main()
