import os
import sqlite3
import unittest

from backend.models.entity_query import EntityQueryEngine
from backend.models.entity_registry import EntityRegistry


class TestEntityQueryEngine(unittest.TestCase):
    def setUp(self):
        self.test_db = "tests/test_query_sandbox.db"
        self.registry = EntityRegistry(self.test_db)
        self.engine = EntityQueryEngine(self.test_db)

        self.registry.register_custom_entity("custom_defender_110", "vehicle", "路虎卫士")
        self.registry.sync_apple_person("mock_uuid_mom", "妈", ["/img/photo1.jpg", "/img/photo2.jpg"])

        with sqlite3.connect(self.test_db) as conn:
            conn.execute(
                "INSERT INTO limb_entity_asset_links (entity_id, asset_path) VALUES ('custom_defender_110', '/img/photo1.jpg')"
            )
            conn.commit()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_intersect_query_logic(self):
        mom_photos = self.engine.query_assets_by_entities(["apple_mock_uuid_mom"], "INTERSECT")
        self.assertEqual(len(mom_photos), 2)

        intersect_photos = self.engine.query_assets_by_entities(
            ["apple_mock_uuid_mom", "custom_defender_110"],
            "INTERSECT",
        )
        self.assertEqual(len(intersect_photos), 1)
        self.assertEqual(intersect_photos[0], "/img/photo1.jpg")


if __name__ == "__main__":
    unittest.main()
