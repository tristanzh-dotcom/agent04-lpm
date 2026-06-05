import unittest

from backend.app_server import app


class AppServerTests(unittest.TestCase):
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
