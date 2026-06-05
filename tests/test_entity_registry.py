import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.models.entity_registry import EntityRegistry


class EntityRegistryTests(unittest.TestCase):
    def test_unifies_apple_people_and_limb_custom_entities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "limb_entities.sqlite3")
            registry = EntityRegistry(db_path)

            registry.sync_apple_person(
                uuid="APPLE-PERSON-UUID-1",
                name="小菲",
                asset_paths=[
                    "/photos/originals/A/asset-1.jpeg",
                    "/photos/originals/A/asset-2.jpeg",
                ],
            )
            registry.register_custom_entity(
                entity_id="custom_defender_110",
                category="vehicle",
                display_name="路虎卫士",
                aliases=["Defender", "卫士", "车"],
            )

            with sqlite3.connect(db_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT
                        e.entity_id,
                        e.source,
                        e.category,
                        e.display_name,
                        e.aliases,
                        e.apple_person_uuid,
                        COUNT(l.asset_path) AS linked_assets
                    FROM limb_entities e
                    LEFT JOIN limb_entity_asset_links l ON l.entity_id = e.entity_id
                    GROUP BY e.entity_id
                    ORDER BY e.entity_id
                    """
                ).fetchall()

            by_id = {row["entity_id"]: dict(row) for row in rows}

            self.assertEqual(set(by_id), {"apple_APPLE-PERSON-UUID-1", "custom_defender_110"})
            self.assertEqual(by_id["apple_APPLE-PERSON-UUID-1"]["source"], "apple_photos")
            self.assertEqual(by_id["apple_APPLE-PERSON-UUID-1"]["category"], "person")
            self.assertEqual(by_id["apple_APPLE-PERSON-UUID-1"]["display_name"], "小菲")
            self.assertEqual(by_id["apple_APPLE-PERSON-UUID-1"]["apple_person_uuid"], "APPLE-PERSON-UUID-1")
            self.assertEqual(by_id["apple_APPLE-PERSON-UUID-1"]["linked_assets"], 2)
            self.assertEqual(by_id["custom_defender_110"]["source"], "limb_custom")
            self.assertEqual(by_id["custom_defender_110"]["category"], "vehicle")
            self.assertEqual(json.loads(by_id["custom_defender_110"]["aliases"]), ["Defender", "卫士", "车"])
            self.assertEqual(by_id["custom_defender_110"]["linked_assets"], 0)


if __name__ == "__main__":
    unittest.main()
