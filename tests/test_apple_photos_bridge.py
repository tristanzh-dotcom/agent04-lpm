import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import plistlib

from backend.apple_photos_bridge import ApplePhotosPeopleBridge, ApplePhotosPeopleCache, parse_reverse_location_blob


def make_reverse_location_blob(*names: str) -> bytes:
    objects = ["$null"]
    refs = []
    for name in names:
        name_index = len(objects)
        objects.append(name)
        place_index = len(objects)
        objects.append({"name": plistlib.UID(name_index), "$class": plistlib.UID(0)})
        refs.append(plistlib.UID(place_index))
    array_index = len(objects)
    objects.append({"NS.objects": refs, "$class": plistlib.UID(0)})
    map_index = len(objects)
    objects.append({"sortedPlaceInfos": plistlib.UID(array_index), "$class": plistlib.UID(0)})
    root_index = len(objects)
    objects.append({"mapItem": plistlib.UID(map_index), "$class": plistlib.UID(0)})
    return plistlib.dumps(
        {
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(root_index)},
            "$objects": objects,
        },
        fmt=plistlib.FMT_BINARY,
    )


class ApplePhotosPeopleBridgeTests(unittest.TestCase):
    def create_fake_photos_library(self, root: Path) -> Path:
        library = root / "Photos Library.photoslibrary"
        database_dir = library / "database"
        database_dir.mkdir(parents=True)
        originals_dir = library / "originals" / "A"
        originals_dir.mkdir(parents=True)
        (originals_dir / "asset-1.jpeg").write_bytes(b"fake-image")
        derivatives_dir = library / "resources" / "derivatives" / "B"
        derivatives_dir.mkdir(parents=True)
        (derivatives_dir / "ASSET-UUID-2_1_105_c.jpeg").write_bytes(b"larger-derivative-preview")
        (derivatives_dir / "ASSET-UUID-2_1_102_o.jpeg").write_bytes(b"small")
        db_path = database_dir / "Photos.sqlite"
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """
                CREATE TABLE ZPERSON (
                    Z_PK INTEGER PRIMARY KEY,
                    ZUUID TEXT,
                    ZDISPLAYNAME TEXT,
                    ZFULLNAME TEXT,
                    ZFACECOUNT INTEGER,
                    ZDETECTIONTYPE INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE ZASSET (
                    Z_PK INTEGER PRIMARY KEY,
                    ZUUID TEXT,
                    ZDIRECTORY TEXT,
                    ZFILENAME TEXT,
                    ZKIND INTEGER DEFAULT 0,
                    ZTRASHEDSTATE INTEGER DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE ZADDITIONALASSETATTRIBUTES (
                    Z_PK INTEGER PRIMARY KEY,
                    ZASSET INTEGER,
                    ZREVERSELOCATIONDATAISVALID INTEGER,
                    ZREVERSELOCATIONDATA BLOB,
                    ZPLACEANNOTATIONDATA BLOB
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE ZDETECTEDFACE (
                    Z_PK INTEGER PRIMARY KEY,
                    ZPERSONFORFACE INTEGER,
                    ZASSETFORFACE INTEGER,
                    ZQUALITY REAL
                )
                """
            )
            connection.execute(
                "INSERT INTO ZPERSON VALUES (1, 'PERSON-UUID-1', '小菲', '小菲', 2, 1)"
            )
            connection.execute(
                "INSERT INTO ZPERSON VALUES (2, 'PERSON-UUID-2', '', '', 3, 1)"
            )
            connection.execute(
                "INSERT INTO ZASSET VALUES (10, 'ASSET-UUID-1', 'A', 'asset-1.jpeg', 0, 0)"
            )
            connection.execute(
                "INSERT INTO ZASSET VALUES (11, 'ASSET-UUID-2', 'B', 'asset-2.jpeg', 0, 0)"
            )
            connection.execute(
                "INSERT INTO ZASSET VALUES (12, 'ASSET-UUID-3', 'C', 'movie.mov', 1, 0)"
            )
            connection.execute(
                "INSERT INTO ZADDITIONALASSETATTRIBUTES VALUES (20, 10, 1, ?, NULL)",
                (make_reverse_location_blob("虹桥南丰城", "长宁区", "上海市", "中国"),),
            )
            connection.execute(
                "INSERT INTO ZDETECTEDFACE VALUES (100, 1, 10, 0.92)"
            )
        return library

    def test_lists_named_people_from_photos_sqlite_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            library = self.create_fake_photos_library(Path(temp_dir))
            bridge = ApplePhotosPeopleBridge(library)

            people = bridge.list_named_people()

            self.assertEqual(len(people), 1)
            self.assertEqual(people[0]["label"], "小菲")
            self.assertEqual(people[0]["uuid"], "PERSON-UUID-1")
            self.assertEqual(people[0]["person_pk"], 1)
            self.assertEqual(people[0]["face_count"], 2)
            self.assertEqual(people[0]["asset_count"], 1)

    def test_iter_person_asset_links_maps_to_original_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            library = self.create_fake_photos_library(Path(temp_dir))
            bridge = ApplePhotosPeopleBridge(library)

            links = list(bridge.iter_person_asset_links())

            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]["label"], "小菲")
            self.assertEqual(links[0]["uuid"], "PERSON-UUID-1")
            self.assertEqual(links[0]["asset_uuid"], "ASSET-UUID-1")
            self.assertEqual(
                links[0]["original_path"],
                str((library / "originals" / "A" / "asset-1.jpeg").resolve()),
            )
            self.assertEqual(links[0]["source"], "apple_photos")

    def test_parses_reverse_location_blob_from_photos_archive(self):
        blob = make_reverse_location_blob("虹桥南丰城", "长宁区", "上海市", "中国")

        self.assertEqual(parse_reverse_location_blob(blob), "上海市 长宁区 虹桥南丰城")

    def test_iter_asset_location_metadata_reads_photos_reverse_location(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            library = self.create_fake_photos_library(Path(temp_dir))
            bridge = ApplePhotosPeopleBridge(library)

            rows = bridge.iter_asset_location_metadata()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["asset_uuid"], "ASSET-UUID-1")
            self.assertEqual(rows[0]["original_path"], str((library / "originals" / "A" / "asset-1.jpeg").resolve()))
            self.assertEqual(rows[0]["location_display_name"], "上海市 长宁区 虹桥南丰城")

    def test_iter_image_asset_resources_uses_original_then_derivative_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            library = self.create_fake_photos_library(Path(temp_dir))
            bridge = ApplePhotosPeopleBridge(library)

            rows = bridge.iter_image_asset_resources()

            self.assertEqual(len(rows), 2)
            by_uuid = {row["asset_uuid"]: row for row in rows}
            self.assertEqual(by_uuid["ASSET-UUID-1"]["source_kind"], "original")
            self.assertEqual(
                by_uuid["ASSET-UUID-1"]["source_path"],
                str((library / "originals" / "A" / "asset-1.jpeg").resolve()),
            )
            self.assertEqual(by_uuid["ASSET-UUID-2"]["source_kind"], "derivative")
            self.assertEqual(
                by_uuid["ASSET-UUID-2"]["source_path"],
                str((library / "resources" / "derivatives" / "B" / "ASSET-UUID-2_1_105_c.jpeg").resolve()),
            )
            self.assertEqual(by_uuid["ASSET-UUID-2"]["original_path"], str((library / "originals" / "B" / "asset-2.jpeg").resolve()))

    def test_people_cache_reads_named_people_and_asset_links(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "apple_people_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "people": [
                            {
                                "label": "小菲",
                                "uuid": "APPLE-PERSON-1",
                                "entity_type": "person",
                                "face_count": 12,
                                "asset_count": 2,
                                "source": "apple_photos",
                            }
                        ],
                        "links": [
                            {
                                "label": "小菲",
                                "uuid": "APPLE-PERSON-1",
                                "asset_uuid": "ASSET-1",
                                "original_path": str(Path(temp_dir) / "A.jpeg"),
                                "quality": 0.88,
                                "source": "apple_photos",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cache = ApplePhotosPeopleCache(cache_path)

            self.assertEqual(cache.list_named_people()[0]["label"], "小菲")
            self.assertEqual(cache.iter_person_asset_links()[0]["quality"], 0.88)

    def test_people_cache_writes_snapshot_from_bridge_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "apple_people_cache.json"
            cache = ApplePhotosPeopleCache(cache_path)

            cache.write_snapshot(
                people=[{"label": "小菲", "uuid": "APPLE-PERSON-1", "asset_count": 1}],
                links=[{"label": "小菲", "uuid": "APPLE-PERSON-1", "original_path": "/tmp/a.jpg"}],
            )

            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["people"][0]["source"], "apple_photos")
            self.assertEqual(payload["links"][0]["source"], "apple_photos")
            self.assertIn("synced_at", payload)


if __name__ == "__main__":
    unittest.main()
