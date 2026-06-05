import json
import sqlite3
from typing import Any, Dict, List


class EntityQueryEngine:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_all_registered_entities(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    entity_id,
                    source,
                    category,
                    display_name,
                    aliases,
                    apple_person_uuid,
                    updated_at
                FROM limb_entities
                ORDER BY source, category, display_name
                """
            ).fetchall()

        return [self._entity_row_to_dict(row) for row in rows]

    def query_assets_by_entities(self, entity_ids: List[str], match_mode: str = "INTERSECT") -> List[str]:
        clean_ids = [entity_id for entity_id in entity_ids if entity_id]
        if not clean_ids:
            return []

        mode = match_mode.upper()
        if mode not in {"INTERSECT", "UNION"}:
            raise ValueError(f"Unsupported entity match mode: {match_mode}")

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT asset_path, COUNT(DISTINCT entity_id) AS matched_entities
                FROM limb_entity_asset_links
                WHERE entity_id IN ({",".join("?" for _ in clean_ids)})
                GROUP BY asset_path
                ORDER BY asset_path
                """,
                clean_ids,
            ).fetchall()

        if mode == "UNION":
            return [row[0] for row in rows]

        required_matches = len(set(clean_ids))
        return [row[0] for row in rows if int(row[1]) == required_matches]

    def _entity_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "entity_id": row["entity_id"],
            "source": row["source"],
            "category": row["category"],
            "display_name": row["display_name"],
            "aliases": json.loads(row["aliases"] or "[]"),
            "apple_person_uuid": row["apple_person_uuid"],
            "updated_at": row["updated_at"],
        }
