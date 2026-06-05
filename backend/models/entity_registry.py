import json
import sqlite3
from typing import List


class EntityRegistry:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS limb_entities (
                    entity_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    category TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    aliases TEXT DEFAULT '[]',
                    apple_person_uuid TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS limb_entity_asset_links (
                    entity_id TEXT NOT NULL,
                    asset_path TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    PRIMARY KEY (entity_id, asset_path),
                    FOREIGN KEY (entity_id) REFERENCES limb_entities(entity_id)
                )
                """
            )
            conn.commit()

    def sync_apple_person(self, uuid: str, name: str, asset_paths: List[str]):
        entity_id = f"apple_{uuid}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO limb_entities (entity_id, source, category, display_name, apple_person_uuid)
                VALUES (?, 'apple_photos', 'person', ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    apple_person_uuid = excluded.apple_person_uuid,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (entity_id, name, uuid),
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO limb_entity_asset_links (entity_id, asset_path)
                VALUES (?, ?)
                """,
                [(entity_id, path) for path in asset_paths],
            )
            conn.commit()

    def register_custom_entity(self, entity_id: str, category: str, display_name: str, aliases: List[str] = None):
        alias_json = json.dumps(aliases or [], ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO limb_entities (entity_id, source, category, display_name, aliases)
                VALUES (?, 'limb_custom', ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    category = excluded.category,
                    display_name = excluded.display_name,
                    aliases = excluded.aliases,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (entity_id, category, display_name, alias_json),
            )
            conn.commit()
