import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.ark_index_engine import ArkPhotoIndexDatabase
from backend import ark_main
from backend.apple_photos_bridge import ApplePhotosPeopleCache
from backend.ark_main import ArkSearchService, DeepSeekQueryBridge, PhotoUpdateRequest


class ArkMainTests(unittest.TestCase):
    def test_health_route_is_lightweight(self):
        self.assertEqual(ark_main.health(), {"status": "ok"})

    def test_search_returns_url_description_and_tags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            image_path = photo_root / "originals" / "A" / "pic.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"fake-image")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="abc",
                modify_time=1.0,
                description="小菲在直升机里准备跳伞",
                tags=["小菲", "跳伞", "直升机"],
                colors=["白色"],
                taken_at="2024-08-12T15:23:45",
                latitude=31.2304,
                longitude=121.4737,
                location_text="31.230400, 121.473700",
                metadata_source="exif",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                photos_base_url="http://127.0.0.1:8004/photos",
                thumbnails_base_url="http://127.0.0.1:8004/thumbnails",
                reverse_geocoder=lambda latitude, longitude: None,
            )

            rows = service.search("小菲 跳伞", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["url"], "http://127.0.0.1:8004/photos/originals/A/pic.jpg")
            self.assertEqual(rows[0]["thumbnail_url"], "http://127.0.0.1:8004/thumbnails/abc.jpg")
            self.assertEqual(rows[0]["description"], "小菲在直升机里准备跳伞")
            self.assertIn("直升机", rows[0]["tags"])
            self.assertEqual(rows[0]["taken_at"], "2024-08-12T15:23:45")
            self.assertEqual(rows[0]["location"]["latitude"], 31.2304)
            self.assertEqual(rows[0]["location"]["longitude"], 121.4737)
            self.assertEqual(rows[0]["location"]["text"], "31.230400, 121.473700")
            self.assertEqual(rows[0]["location"]["display_name"], "上海")
            self.assertEqual(rows[0]["metadata_source"], "exif")

    def test_search_result_preview_url_falls_back_to_indexed_source_when_thumbnail_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            derivative_path = photo_root / "resources" / "derivatives" / "C" / "asset_1_102_o.jpeg"
            original_path = photo_root / "originals" / "C" / "asset.jpeg"
            derivative_path.parent.mkdir(parents=True)
            original_path.parent.mkdir(parents=True)
            derivative_path.write_bytes(b"preview-image")
            original_path.write_bytes(b"original-image")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=derivative_path,
                md5="abc",
                modify_time=1.0,
                description="妈妈在花园里",
                tags=["妈妈", "花园"],
                colors=["绿色"],
                asset_id="asset123",
                local_identifier="asset-uuid/L0/001",
                original_path=original_path,
                source="apple_photos",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                thumbnail_dir=root / ".cache" / "thumbnails",
                photos_base_url="http://127.0.0.1:8004/photos",
                thumbnails_base_url="http://127.0.0.1:8004/thumbnails",
                reverse_geocoder=lambda latitude, longitude: None,
            )

            rows = service.search("花园", limit=10)

            self.assertEqual(rows[0]["url"], "http://127.0.0.1:8004/api/assets/asset123/image")
            self.assertEqual(
                rows[0]["preview_url"],
                "http://127.0.0.1:8004/photos/resources/derivatives/C/asset_1_102_o.jpeg",
            )

    def test_search_result_preview_url_prefers_cached_thumbnail_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            image_path = photo_root / "originals" / "A" / "pic.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"fake-image")
            thumbnail_dir = root / ".cache" / "thumbnails"
            thumbnail_dir.mkdir(parents=True)
            (thumbnail_dir / "abc.jpg").write_bytes(b"thumbnail")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="abc",
                modify_time=1.0,
                description="小菲在直升机里准备跳伞",
                tags=["小菲", "跳伞", "直升机"],
                colors=["白色"],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                thumbnail_dir=thumbnail_dir,
                thumbnails_base_url="http://127.0.0.1:8004/thumbnails",
                reverse_geocoder=lambda latitude, longitude: None,
            )

            rows = service.search("小菲 跳伞", limit=10)

            self.assertEqual(rows[0]["preview_url"], "http://127.0.0.1:8004/thumbnails/abc.jpg")

    def test_location_formatter_prefers_readable_place_name_over_raw_coordinates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root,
                reverse_geocoder=lambda latitude, longitude: None,
            )

            location = service._format_location(
                {
                    "latitude": 31.209147,
                    "longitude": 121.403364,
                    "location_text": "31.209147, 121.403364",
                }
            )

            self.assertEqual(location["display_name"], "上海")
            self.assertEqual(location["text"], "31.209147, 121.403364")

    def test_location_formatter_uses_reverse_geocoder_before_city_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root,
                reverse_geocoder=lambda latitude, longitude: "上海市 长宁区 中山公园",
            )

            location = service._format_location(
                {
                    "latitude": 31.209147,
                    "longitude": 121.403364,
                    "location_text": "31.209147, 121.403364",
                }
            )

            self.assertEqual(location["display_name"], "上海市 长宁区 中山公园")

    def test_search_route_schedules_photokit_prefetch_for_local_identifiers(self):
        class FakeBackgroundTasks:
            def __init__(self):
                self.tasks = []

            def add_task(self, func, *args, **kwargs):
                self.tasks.append((func, args, kwargs))

        class FakeService:
            last_search_diagnostic = {}

            def search(self, query, *, limit=50):
                return [
                    {
                        "md5": "abc",
                        "path": "/tmp/photo.jpg",
                        "url": "http://127.0.0.1:8004/api/assets/asset123/image",
                        "thumbnail_url": "http://127.0.0.1:8004/thumbnails/asset123.jpg",
                        "description": "老张吃饭",
                        "tags": ["老张", "吃饭"],
                        "colors": ["暖黄"],
                        "asset_id": "asset123",
                        "local_identifier": "LOCAL/123",
                    }
                ]

            def original_path_for_local_identifier(self, local_identifier):
                return "/tmp/photo.jpg"

        tasks = FakeBackgroundTasks()
        with patch("backend.ark_main.service", FakeService()):
            response = ark_main.search_photos(ark_main.SearchRequest(query="老张吃饭"), tasks)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(tasks.tasks), 1)
        self.assertEqual(tasks.tasks[0][1][0], ["LOCAL/123"])

    def test_resolve_thumbnail_static_path_uses_md5_jpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thumbnail_dir = root / ".cache" / "thumbnails"
            thumbnail_dir.mkdir(parents=True)
            thumbnail = thumbnail_dir / "abc.jpg"
            thumbnail.write_bytes(b"thumbnail")
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root,
                thumbnail_dir=thumbnail_dir,
            )

            self.assertEqual(service.resolve_thumbnail_static_path("abc.jpg"), thumbnail.resolve())
            self.assertIsNone(service.resolve_thumbnail_static_path("../abc.jpg"))

    def test_photo_route_falls_back_to_thumbnail_when_original_is_not_permitted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            image_path = photo_root / "originals" / "A" / "pic.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"original")
            thumbnail_dir = root / ".cache" / "thumbnails"
            thumbnail_dir.mkdir(parents=True)
            thumbnail_path = thumbnail_dir / "abc.jpg"
            thumbnail_path.write_bytes(b"thumbnail")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="abc",
                modify_time=1.0,
                description="受保护的 Apple Photos 原图",
                tags=["权限兜底"],
                colors=["灰色"],
            )
            fallback_service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                thumbnail_dir=thumbnail_dir,
            )

            with patch("backend.ark_main.service", fallback_service), patch.object(
                Path, "read_bytes", side_effect=[PermissionError("TCC denied"), b"thumbnail"]
            ):
                response = ark_main.get_photo("originals/A/pic.jpg")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.body, b"thumbnail")
            self.assertEqual(response.headers["X-LIMB-Photo-Stream"], "thumbnail-fallback-permission")

    def test_resolve_asset_image_static_path_uses_original_path_when_local_file_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "asset.jpg"
            image_path.write_bytes(b"asset-image")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="asset-md5",
                modify_time=1.0,
                description="PhotoKit 资产",
                tags=["资产"],
                colors=["蓝色"],
                asset_id="asset123",
                local_identifier="LOCAL/123",
                original_path=image_path,
                source="photokit",
            )
            service = ArkSearchService(db_path=root / "limb_ark.sqlite3", photo_root=root)

            self.assertEqual(service.resolve_asset_image_static_path("asset123"), image_path.resolve())

    def test_service_search_uses_jieba_for_compact_chinese_phrase(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "sea.jpg"
            image_path.write_bytes(b"fake-image")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="abc123",
                modify_time=1.0,
                description="蓝天和大海之间有一张旅行照片",
                tags=["蓝天", "大海", "旅行"],
                colors=["蓝色"],
            )
            service = ArkSearchService(db_path=root / "limb_ark.sqlite3", photo_root=root)

            rows = service.search("蓝天大海", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["thumbnail_url"], "http://127.0.0.1:8004/thumbnails/abc123.jpg")

    def test_service_index_status_reports_empty_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root / "Photos Library.photoslibrary",
                thumbnail_dir=root / ".cache" / "thumbnails",
            )

            status = service.index_status()

            self.assertEqual(status["photos"], 0)
            self.assertTrue(status["is_empty"])
            self.assertEqual(status["db_path"], str((root / "limb_ark.sqlite3").resolve()))

    def test_service_index_delta_counts_local_only_changes_without_model_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "照片图库.photoslibrary"
            originals = photo_root / "originals"
            originals.mkdir(parents=True)

            current_path = originals / "A" / "current.jpg"
            missing_path = originals / "B" / "missing.jpg"
            changed_path = originals / "C" / "changed.jpg"
            stale_path = originals / "D" / "stale.jpg"
            for path, content in (
                (current_path, b"current"),
                (missing_path, b"missing"),
                (changed_path, b"changed"),
                (stale_path, b"stale"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=current_path,
                md5="current-md5",
                modify_time=current_path.stat().st_mtime,
                description="已同步照片",
                tags=["同步"],
                colors=["绿色"],
            )
            db.upsert_photo(
                path=changed_path,
                md5="changed-old-md5",
                modify_time=changed_path.stat().st_mtime - 10,
                description="已变化照片",
                tags=["变化"],
                colors=["黄色"],
            )
            db.upsert_photo(
                path=stale_path,
                md5="stale-md5",
                modify_time=stale_path.stat().st_mtime,
                description="已删除照片",
                tags=["删除"],
                colors=["灰色"],
            )
            stale_path.unlink()
            service = ArkSearchService(db_path=root / "limb_ark.sqlite3", photo_root=photo_root)

            delta = service.index_delta()

            self.assertEqual(delta["photo_total"], 3)
            self.assertEqual(delta["indexed_total"], 3)
            self.assertEqual(delta["missing_count"], 1)
            self.assertEqual(delta["changed_count"], 1)
            self.assertEqual(delta["stale_count"], 1)
            self.assertTrue(delta["has_delta"])
            self.assertEqual(delta["scan_cost"], "local_only_no_model_token")

    def test_index_delta_route_uses_service_without_starting_update(self):
        class FakeService:
            def index_delta(self):
                return {
                    "photo_total": 10,
                    "indexed_total": 9,
                    "missing_count": 1,
                    "changed_count": 0,
                    "stale_count": 0,
                    "has_delta": True,
                    "scan_cost": "local_only_no_model_token",
                }

        with patch("backend.ark_main.service", FakeService()):
            payload = ark_main.index_delta()

        self.assertEqual(payload["missing_count"], 1)
        self.assertEqual(payload["scan_cost"], "local_only_no_model_token")

    def test_service_index_delta_prefers_apple_photos_asset_inventory(self):
        class FakeAppleBridge:
            def __init__(self, assets):
                self.assets = assets

            def iter_image_asset_resources(self):
                return self.assets

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "resources" / "derivatives" / "asset-a.jpg"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"asset-a")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=source_path,
                md5="asset-a-md5",
                modify_time=source_path.stat().st_mtime,
                description="Apple Photos 资产 A",
                tags=["资产"],
                colors=["绿色"],
                asset_id="asset-a",
                local_identifier="asset-a/L0/001",
                original_path=root / "originals" / "A" / "asset-a.jpg",
                source="apple_photos",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root / "照片图库.photoslibrary",
                apple_people_bridge=FakeAppleBridge(
                    [
                        {
                            "asset_id": "asset-a",
                            "local_identifier": "asset-a/L0/001",
                            "source_path": source_path,
                            "original_path": root / "originals" / "A" / "asset-a.jpg",
                        }
                    ]
                ),
            )

            delta = service.index_delta()

            self.assertEqual(delta["photo_total"], 1)
            self.assertEqual(delta["indexed_total"], 1)
            self.assertEqual(delta["missing_count"], 0)
            self.assertEqual(delta["changed_count"], 0)
            self.assertEqual(delta["stale_count"], 0)
            self.assertFalse(delta["has_delta"])
            self.assertEqual(delta["source"], "apple_photos_assets")

    def test_service_index_delta_treats_apple_source_swap_as_quality_transition(self):
        class FakeAppleBridge:
            def __init__(self, assets):
                self.assets = assets

            def iter_image_asset_resources(self):
                return self.assets

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "Photos Library.photoslibrary"
            derivative_path = library_root / "resources" / "derivatives" / "asset-a.jpg"
            original_path = library_root / "originals" / "A" / "asset-a.jpg"
            derivative_path.parent.mkdir(parents=True)
            original_path.parent.mkdir(parents=True)
            derivative_path.write_bytes(b"small-preview")
            original_path.write_bytes(b"full-original")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=derivative_path,
                md5="old-derivative-md5",
                modify_time=derivative_path.stat().st_mtime,
                description="Apple Photos 资产 A",
                tags=["资产"],
                colors=["绿色"],
                asset_id="asset-a",
                local_identifier="asset-a/L0/001",
                original_path=original_path,
                source="apple_photos",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=library_root,
                apple_people_bridge=FakeAppleBridge(
                    [
                        {
                            "asset_id": "asset-a",
                            "local_identifier": "asset-a/L0/001",
                            "source_path": original_path,
                            "original_path": original_path,
                            "source_kind": "original",
                        }
                    ]
                ),
            )

            delta = service.index_delta()

            self.assertEqual(delta["photo_total"], 1)
            self.assertEqual(delta["indexed_total"], 1)
            self.assertEqual(delta["missing_count"], 0)
            self.assertEqual(delta["changed_count"], 0)
            self.assertEqual(delta["stale_count"], 0)
            self.assertFalse(delta["has_delta"])
            self.assertEqual(delta["source_quality"]["original_count"], 1)
            self.assertEqual(delta["source_quality"]["derivative_count"], 0)
            self.assertEqual(delta["source_quality"]["source_file_changed_count"], 1)

    def test_service_index_status_reports_apple_source_quality(self):
        class FakeAppleBridge:
            def iter_image_asset_resources(self):
                return [
                    {"asset_id": "asset-a", "source_kind": "original"},
                    {"asset_id": "asset-b", "source_kind": "derivative"},
                    {"asset_id": "asset-c", "source_kind": "derivative"},
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root / "Photos Library.photoslibrary",
                apple_people_bridge=FakeAppleBridge(),
            )

            status = service.index_status()

            self.assertEqual(status["source_quality"]["original_count"], 1)
            self.assertEqual(status["source_quality"]["derivative_count"], 2)

    def test_service_index_status_prefers_cached_source_quality_without_live_scan(self):
        class CountingAppleBridge:
            calls = 0

            def iter_image_asset_resources(self):
                CountingAppleBridge.calls += 1
                return [{"asset_id": "asset-live", "source_kind": "original"}]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "Photos Library.photoslibrary"
            original_path = library_root / "originals" / "A" / "asset-a.jpg"
            derivative_path = library_root / "resources" / "derivatives" / "asset-b.jpg"
            cache = ApplePhotosPeopleCache(root / "apple_people_cache.json")
            cache.write_snapshot(
                people=[],
                links=[],
                assets=[
                    {
                        "asset_id": "asset-a",
                        "source_kind": "original",
                        "source_path": str(original_path),
                        "original_path": str(original_path),
                    },
                    {
                        "asset_id": "asset-b",
                        "source_kind": "derivative",
                        "source_path": str(derivative_path),
                        "original_path": str(library_root / "originals" / "B" / "asset-b.jpg"),
                    },
                ],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=library_root,
                apple_people_bridge=CountingAppleBridge(),
                apple_people_cache=cache,
            )

            status = service.index_status()

            self.assertEqual(CountingAppleBridge.calls, 0)
            self.assertEqual(status["source_quality"]["original_count"], 1)
            self.assertEqual(status["source_quality"]["derivative_count"], 1)

    def test_apple_people_search_handles_derivative_index_path(self):
        class FakeAppleBridge:
            def list_named_people(self):
                return [
                    {
                        "label": "老妈",
                        "uuid": "person-mom",
                        "entity_type": "person",
                        "asset_count": 1,
                        "face_count": 1,
                        "source": "apple_photos",
                    }
                ]

            def iter_person_asset_links(self):
                return [
                    {
                        "label": "老妈",
                        "uuid": "person-mom",
                        "original_path": str(original_path),
                        "quality": 0.98,
                        "source": "apple_photos",
                    }
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "Photos Library.photoslibrary"
            derivative_path = library_root / "resources" / "derivatives" / "C" / "asset-preview.jpeg"
            original_path = library_root / "originals" / "C" / "asset-original.jpeg"
            derivative_path.parent.mkdir(parents=True)
            original_path.parent.mkdir(parents=True)
            derivative_path.write_bytes(b"preview")
            original_path.write_bytes(b"original")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=derivative_path,
                md5="asset-preview-md5",
                modify_time=derivative_path.stat().st_mtime,
                description="老妈在公园散步",
                tags=["老妈", "公园"],
                colors=["绿色"],
                asset_id="asset-mom",
                local_identifier="ASSET-MOM/L0/001",
                original_path=original_path,
                source="apple_photos",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=library_root,
                apple_people_bridge=FakeAppleBridge(),
            )

            rows = service.search("老妈", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "asset-preview-md5")
            self.assertEqual(rows[0]["matched_labels"], ["老妈"])
            self.assertEqual(rows[0]["identity_source"], "apple_photos")

    def test_service_index_delta_falls_back_to_apple_inventory_when_bridge_is_missing(self):
        class FakeAppleBridge:
            def __init__(self, library_root):
                self.library_root = Path(library_root)

            def iter_image_asset_resources(self):
                return [
                    {
                        "asset_id": "asset-a",
                        "local_identifier": "asset-a/L0/001",
                        "source_path": source_path,
                        "original_path": library_root / "originals" / "A" / "asset-a.jpg",
                    }
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "Photos Library.photoslibrary"
            photos_db = library_root / "database" / "Photos.sqlite"
            photos_db.parent.mkdir(parents=True)
            photos_db.write_bytes(b"fake sqlite marker")
            source_path = library_root / "resources" / "derivatives" / "asset-a.jpg"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"asset-a")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=source_path,
                md5="asset-a-md5",
                modify_time=source_path.stat().st_mtime,
                description="Apple Photos 资产 A",
                tags=["资产"],
                colors=["绿色"],
                asset_id="asset-a",
                local_identifier="asset-a/L0/001",
                original_path=library_root / "originals" / "A" / "asset-a.jpg",
                source="apple_photos",
            )
            service = ArkSearchService(db_path=root / "limb_ark.sqlite3", photo_root=library_root)
            service.apple_people_bridge = None

            with patch("backend.ark_main.ApplePhotosPeopleBridge", FakeAppleBridge):
                delta = service.index_delta()

            self.assertEqual(delta["photo_total"], 1)
            self.assertEqual(delta["missing_count"], 0)
            self.assertEqual(delta["source"], "apple_photos_assets")

    def test_service_index_delta_uses_apple_asset_cache_when_photos_sqlite_is_denied(self):
        class DeniedAppleBridge:
            def iter_image_asset_resources(self):
                raise PermissionError("authorization denied")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "Photos Library.photoslibrary"
            source_path = library_root / "resources" / "derivatives" / "asset-a.jpg"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"asset-a")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=source_path,
                md5="asset-a-md5",
                modify_time=source_path.stat().st_mtime,
                description="Apple Photos 资产 A",
                tags=["资产"],
                colors=["绿色"],
                asset_id="asset-a",
                local_identifier="asset-a/L0/001",
                original_path=library_root / "originals" / "A" / "asset-a.jpg",
                source="apple_photos",
            )
            cache = ApplePhotosPeopleCache(root / "apple_people_cache.json")
            cache.write_snapshot(
                people=[],
                links=[],
                assets=[
                    {
                        "asset_id": "asset-a",
                        "local_identifier": "asset-a/L0/001",
                        "source_path": str(source_path),
                        "original_path": str(library_root / "originals" / "A" / "asset-a.jpg"),
                    }
                ],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=library_root,
                apple_people_bridge=DeniedAppleBridge(),
                apple_people_cache=cache,
            )

            delta = service.index_delta()

            self.assertEqual(delta["photo_total"], 1)
            self.assertEqual(delta["missing_count"], 0)
            self.assertEqual(delta["source"], "apple_photos_assets")

    def test_service_starts_delta_update_only_when_delta_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            originals = photo_root / "originals"
            originals.mkdir(parents=True)
            (originals / "new.jpg").write_bytes(b"new")
            service = ArkSearchService(db_path=root / "limb_ark.sqlite3", photo_root=photo_root)
            calls = []

            def fake_popen(command, cwd, start_new_session, **kwargs):
                calls.append((command, cwd, start_new_session))

                class FakeProcess:
                    pid = 12345

                    def wait(self):
                        return 0

                return FakeProcess()

            payload = service.start_delta_update(popen=fake_popen, monitor_async=False)

            self.assertEqual(payload["status"], "started")
            self.assertEqual(payload["pid"], 12345)
            self.assertIn("run_index_pipeline.py", calls[0][0])
            self.assertEqual(calls[0][0][2], str(originals.resolve()))
            self.assertEqual(payload["delta"]["missing_count"], 1)

    def test_service_prunes_stale_only_delta_without_starting_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            current_path = photo_root / "originals" / "A" / "current.jpg"
            stale_path = photo_root / "originals" / "B" / "stale.jpg"
            current_path.parent.mkdir(parents=True)
            stale_path.parent.mkdir(parents=True)
            current_path.write_bytes(b"current")
            stale_path.write_bytes(b"stale")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=current_path,
                md5="current-md5",
                modify_time=current_path.stat().st_mtime,
                description="当前照片",
                tags=["当前"],
                colors=["蓝色"],
                asset_id="asset-current",
                local_identifier="asset-current/L0/001",
            )
            db.upsert_photo(
                path=stale_path,
                md5="stale-md5",
                modify_time=stale_path.stat().st_mtime,
                description="旧照片",
                tags=["旧照片"],
                colors=["灰色"],
                asset_id="asset-stale",
                local_identifier="asset-stale/L0/001",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                delta_job_path=root / "delta_update_job.json",
                delta_log_path=root / "delta_update_job.log",
                apple_people_bridge=None,
                apple_people_cache=None,
            )
            service._apple_photo_assets_for_delta = lambda: [
                {
                    "source_path": str(current_path),
                    "original_path": str(current_path),
                    "asset_id": "asset-current",
                    "local_identifier": "asset-current/L0/001",
                }
            ]

            def fake_popen(*args, **kwargs):
                raise AssertionError("stale-only delta should not start Ark pipeline")

            payload = service.start_delta_update(popen=fake_popen, monitor_async=False)
            job = service.delta_update_job_status()

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["reason"], "stale_pruned")
            self.assertEqual(payload["summary"]["stale_removed"], 1)
            self.assertEqual(payload["delta_after"]["stale_count"], 0)
            self.assertFalse(payload["delta_after"]["has_delta"])
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["summary"]["stale_removed"], 1)
            self.assertEqual(job["delta_after"]["stale_count"], 0)
            self.assertEqual(service.search("旧照片", limit=10), [])

    def test_service_prunes_stale_entries_after_successful_delta_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            current_path = photo_root / "originals" / "A" / "current.jpg"
            stale_path = photo_root / "originals" / "B" / "stale.jpg"
            current_path.parent.mkdir(parents=True)
            stale_path.parent.mkdir(parents=True)
            current_path.write_bytes(b"current")
            stale_path.write_bytes(b"stale")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=stale_path,
                md5="stale-md5",
                modify_time=stale_path.stat().st_mtime,
                description="旧照片",
                tags=["旧照片"],
                colors=["灰色"],
                asset_id="asset-stale",
                local_identifier="asset-stale/L0/001",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                delta_job_path=root / "delta_update_job.json",
                delta_log_path=root / "delta_update_job.log",
                apple_people_bridge=None,
                apple_people_cache=None,
            )
            service._apple_photo_assets_for_delta = lambda: [
                {
                    "source_path": str(current_path),
                    "original_path": str(current_path),
                    "asset_id": "asset-current",
                    "local_identifier": "asset-current/L0/001",
                }
            ]

            def fake_popen(command, cwd, start_new_session, **kwargs):
                kwargs["stdout"].write("本次新增成功打标图片数：1\n增量跳过图片数：0\n失败图片数：0\n")
                kwargs["stdout"].flush()
                service.database.upsert_photo(
                    path=current_path,
                    md5="current-md5",
                    modify_time=current_path.stat().st_mtime,
                    description="当前照片",
                    tags=["当前"],
                    colors=["蓝色"],
                    asset_id="asset-current",
                    local_identifier="asset-current/L0/001",
                )

                class FakeProcess:
                    pid = 12345

                    def wait(self):
                        return 0

                return FakeProcess()

            service.start_delta_update(popen=fake_popen, monitor_async=False)
            job = service.delta_update_job_status()

            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["summary"]["indexed"], 1)
            self.assertEqual(job["summary"]["stale_removed"], 1)
            self.assertFalse(job["delta_after"]["has_delta"])
            self.assertEqual(job["delta_after"]["stale_count"], 0)
            self.assertEqual(job["message"], "相册同步完成")
            self.assertEqual(service.search("旧照片", limit=10), [])

    def test_service_records_permission_blocked_delta_update_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            originals = photo_root / "originals"
            originals.mkdir(parents=True)
            (originals / "new.jpg").write_bytes(b"new")
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                delta_job_path=root / "delta_update_job.json",
                delta_log_path=root / "delta_update_job.log",
            )

            def fake_popen(command, cwd, start_new_session, **kwargs):
                kwargs["stdout"].write(
                    "PermissionError\t[Errno 1] Operation not permitted: "
                    f"'{originals / 'new.jpg'}'\n"
                )
                kwargs["stdout"].flush()

                class FakeProcess:
                    pid = 12345

                    def wait(self):
                        return 0

                return FakeProcess()

            payload = service.start_delta_update(popen=fake_popen, monitor_async=False)
            job = service.delta_update_job_status()

            self.assertEqual(payload["status"], "started")
            self.assertEqual(job["status"], "permission_blocked")
            self.assertEqual(job["pid"], 12345)
            self.assertEqual(job["exit_code"], 0)
            self.assertEqual(job["permission_error_count"], 1)
            self.assertEqual(job["delta_after"]["missing_count"], 1)
            self.assertIn("后台无权限读取相册", job["message"])
            self.assertIn("Operation not permitted", job["log_tail"])

    def test_service_marks_job_permission_blocked_from_indexing_error_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            originals = photo_root / "originals"
            originals.mkdir(parents=True)
            image_path = originals / "new.jpg"
            image_path.write_bytes(b"new")
            error_log = root / "indexing_errors.log"
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                delta_job_path=root / "delta_update_job.json",
                delta_log_path=root / "delta_update_job.log",
                delta_error_log_path=error_log,
            )

            def fake_popen(command, cwd, start_new_session, **kwargs):
                kwargs["stdout"].write("本次新增成功打标图片数：0\n增量跳过图片数：1\n失败图片数：0\n")
                kwargs["stdout"].flush()
                error_log.write_text(
                    f"2099-01-01 00:00:00\t{image_path}\tPermissionError\t"
                    f"[Errno 1] Operation not permitted: '{image_path}'\n",
                    encoding="utf-8",
                )

                class FakeProcess:
                    pid = 12345

                    def wait(self):
                        return 0

                return FakeProcess()

            service.start_delta_update(popen=fake_popen, monitor_async=False)
            job = service.delta_update_job_status()

            self.assertEqual(job["status"], "permission_blocked")
            self.assertEqual(job["permission_error_count"], 1)
            self.assertIn("indexing_errors.log", job["error_log_path"])
            self.assertIn("Operation not permitted", job["error_log_tail"])

    def test_service_ignores_stale_permission_errors_before_job_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            originals = photo_root / "originals"
            originals.mkdir(parents=True)
            image_path = originals / "new.jpg"
            image_path.write_bytes(b"new")
            error_log = root / "indexing_errors.log"
            error_log.write_text(
                f"2000-01-01 00:00:00\t{image_path}\tPermissionError\t"
                f"[Errno 1] Operation not permitted: '{image_path}'\n",
                encoding="utf-8",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                delta_job_path=root / "delta_update_job.json",
                delta_log_path=root / "delta_update_job.log",
                delta_error_log_path=error_log,
            )

            def fake_popen(command, cwd, start_new_session, **kwargs):
                kwargs["stdout"].write("本次新增成功打标图片数：0\n增量跳过图片数：1\n失败图片数：0\n")
                kwargs["stdout"].flush()

                class FakeProcess:
                    pid = 12345

                    def wait(self):
                        return 0

                return FakeProcess()

            service.start_delta_update(popen=fake_popen, monitor_async=False)
            job = service.delta_update_job_status()

            self.assertEqual(job["status"], "needs_attention")
            self.assertEqual(job["permission_error_count"], 0)

    def test_delta_update_route_uses_service(self):
        class FakeService:
            def start_delta_update(self):
                return {"status": "started", "pid": 123, "delta": {"has_delta": True}}

        with patch("backend.ark_main.service", FakeService()):
            payload = ark_main.run_index_delta_update()

        self.assertEqual(payload["status"], "started")
        self.assertEqual(payload["pid"], 123)

    def test_delta_update_job_route_uses_service(self):
        class FakeService:
            def delta_update_job_status(self):
                return {"status": "permission_blocked", "permission_error_count": 54}

        with patch("backend.ark_main.service", FakeService()):
            payload = ark_main.delta_update_job_status()

        self.assertEqual(payload["status"], "permission_blocked")
        self.assertEqual(payload["permission_error_count"], 54)

    def test_service_random_photos_returns_formatted_thumbnail_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            for index in range(3):
                image_path = root / f"photo-{index}.jpg"
                image_path.write_bytes(b"fake-image")
                db.upsert_photo(
                    path=image_path,
                    md5=f"random-{index}",
                    modify_time=1.0,
                    description=f"随机相册预览 {index}",
                    tags=["预览", f"第{index}张"],
                    colors=["绿色"],
                )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root,
                thumbnails_base_url="http://127.0.0.1:8004/thumbnails",
            )

            rows = service.random_photos(limit=2)

            self.assertEqual(len(rows), 2)
            self.assertIn("thumbnail_url", rows[0])
            self.assertTrue(rows[0]["thumbnail_url"].startswith("http://127.0.0.1:8004/thumbnails/random-"))
            self.assertIn("随机相册预览", rows[0]["description"])

    def test_random_photo_route_caps_limit_and_uses_service(self):
        class FakeService:
            def __init__(self):
                self.limit = None

            def random_photos(self, *, limit=24):
                self.limit = limit
                return [{"md5": "abc", "thumbnail_url": "http://127.0.0.1:8004/thumbnails/abc.jpg"}]

        fake_service = FakeService()
        with patch("backend.ark_main.service", fake_service):
            rows = ark_main.random_photos(limit=999)

        self.assertEqual(fake_service.limit, 80)
        self.assertEqual(rows[0]["md5"], "abc")

    def test_service_search_uses_query_bridge_keywords_for_natural_language(self):
        class FakeQueryBridge:
            def parse(self, query):
                return {"keywords": ["夏天", "海边", "太阳"], "colors": []}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "summer.jpg"
            image_path.write_bytes(b"fake-image")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="summer-md5",
                modify_time=1.0,
                description="夏天海边阳光强烈，朋友们在沙滩上合影",
                tags=["夏天", "海边", "太阳", "朋友"],
                colors=["蓝色", "金色"],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root,
                query_bridge=FakeQueryBridge(),
            )

            rows = service.search("我想看去年夏天和朋友去海边顶着大太阳拍的照片", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertIn("海边", rows[0]["tags"])

    def test_service_search_falls_back_to_local_baseline_when_query_bridge_fails(self):
        class FailingQueryBridge:
            def parse(self, query):
                raise RuntimeError("deepseek unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "dog.jpg"
            image_path.write_bytes(b"fake-image")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="dog-md5",
                modify_time=1.0,
                description="一只狗狗在院子里玩耍",
                tags=["狗狗", "宠物", "院子"],
                colors=["绿色"],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root,
                query_bridge=FailingQueryBridge(),
            )

            rows = service.search("狗狗", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "dog-md5")

    def test_service_search_expands_family_profile_names_to_visual_terms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "xiaofei-cat.jpg"
            image_path.write_bytes(b"fake-image")
            profile_path = root / "family_profile.json"
            profile_path.write_text('{"小菲": "夫人，亚洲女性"}', encoding="utf-8")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="xiaofei-cat",
                modify_time=1.0,
                description="一个女孩躺在床上，身旁有一只猫咪。",
                tags=["女孩", "猫咪", "床", "卧室"],
                colors=["绿色"],
            )
            decoy_path = root / "woman-no-pet.jpg"
            decoy_path.write_bytes(b"fake-image")
            db.upsert_photo(
                path=decoy_path,
                md5="woman-no-pet",
                modify_time=1.0,
                description="一位女性站在机甲旁，画面中无宠物。",
                tags=["女性", "机甲", "无宠物"],
                colors=["白色"],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root,
                family_profile_path=profile_path,
                query_bridge=None,
            )

            rows = service.search("小菲和猫咪一起照片", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "xiaofei-cat")

    def test_deepseek_query_bridge_parses_json_response(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"keywords":["夏天","海边","太阳"],"colors":["蓝色"]}'
                            }
                        }
                    ]
                }

        calls = []

        def fake_post(*args, **kwargs):
            calls.append(kwargs)
            return FakeResponse()

        bridge = DeepSeekQueryBridge(api_key="test-key", http_post=fake_post)

        parsed = bridge.parse("我想看去年夏天和朋友去海边顶着大太阳拍的照片")

        self.assertEqual(parsed["keywords"], ["夏天", "海边", "太阳"])
        self.assertEqual(parsed["colors"], ["蓝色"])
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer test-key")

    def test_service_updates_photo_metadata_by_md5_and_refreshes_search(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "photo.jpg"
            image_path.write_bytes(b"fake-image")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="edit-md5",
                modify_time=1.0,
                description="旧描述",
                tags=["旧标签"],
                colors=["灰色"],
            )
            service = ArkSearchService(db_path=root / "limb_ark.sqlite3", photo_root=root)

            updated = service.update_photo_metadata(
                "edit-md5",
                description="小菲和狗在草地上合影",
                tags=["小菲", "狗", "草地"],
                colors=["绿色"],
            )

            self.assertEqual(updated["description"], "小菲和狗在草地上合影")
            self.assertEqual(updated["tags"], ["小菲", "狗", "草地"])
            rows = service.search("小菲 狗", limit=10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "edit-md5")

    def test_service_deletes_photo_by_md5_and_thumbnail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "photo.jpg"
            image_path.write_bytes(b"fake-image")
            thumbnail_dir = root / ".cache" / "thumbnails"
            thumbnail_dir.mkdir(parents=True)
            thumbnail = thumbnail_dir / "delete-md5.jpg"
            thumbnail.write_bytes(b"thumb")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="delete-md5",
                modify_time=1.0,
                description="待删除照片",
                tags=["删除"],
                colors=["灰色"],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=root,
                thumbnail_dir=thumbnail_dir,
            )

            deleted = service.delete_photo("delete-md5")

            self.assertEqual(deleted["md5"], "delete-md5")
            self.assertFalse(thumbnail.exists())
            self.assertEqual(service.search("删除", limit=10), [])

    def test_service_prunes_stale_apple_photos_index_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            current_path = photo_root / "originals" / "A" / "current.jpg"
            stale_path = photo_root / "originals" / "B" / "stale.jpg"
            current_path.parent.mkdir(parents=True)
            stale_path.parent.mkdir(parents=True)
            current_path.write_bytes(b"current")
            stale_path.write_bytes(b"stale")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=current_path,
                md5="current-md5",
                modify_time=1.0,
                description="当前照片",
                tags=["当前"],
                colors=["蓝色"],
                asset_id="asset-current",
                local_identifier="asset-current/L0/001",
            )
            db.upsert_photo(
                path=stale_path,
                md5="stale-md5",
                modify_time=1.0,
                description="旧照片",
                tags=["旧照片"],
                colors=["灰色"],
                asset_id="asset-stale",
                local_identifier="asset-stale/L0/001",
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                apple_people_bridge=None,
                apple_people_cache=None,
            )
            service._apple_photo_assets_for_delta = lambda: [
                {
                    "source_path": str(current_path),
                    "original_path": str(current_path),
                    "asset_id": "asset-current",
                    "local_identifier": "asset-current/L0/001",
                }
            ]

            payload = service.prune_stale_index_entries()

            self.assertEqual(payload["deleted_count"], 1)
            self.assertEqual(payload["deleted"][0]["md5"], "stale-md5")
            self.assertEqual(service.search("旧照片", limit=10), [])
            self.assertEqual(service.index_delta()["stale_count"], 0)

    def test_service_opens_photo_by_md5_with_macos_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            image_path = photo_root / "originals" / "C" / "photo.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"fake-image")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="open-md5",
                modify_time=1.0,
                description="可用系统图片浏览器打开的照片",
                tags=["打开"],
                colors=["灰色"],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                thumbnail_dir=root / ".cache" / "thumbnails",
            )

            calls = []

            def fake_run(command, check):
                calls.append((command, check))

            opened = service.open_photo_in_native_viewer("open-md5", open_runner=fake_run)

            self.assertEqual(opened["status"], "opened")
            self.assertEqual(opened["md5"], "open-md5")
            self.assertEqual(opened["source_path"], str(image_path.resolve()))
            self.assertTrue(opened["path"].endswith(".cache/native-open/open-md5.jpg"))
            self.assertEqual(Path(opened["path"]).read_bytes(), b"fake-image")
            self.assertEqual(calls, [(["open", opened["path"]], True)])

    def test_service_opens_cached_thumbnail_when_photos_library_denies_original(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo_root = root / "Photos Library.photoslibrary"
            image_path = photo_root / "originals" / "C" / "photo.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"fake-image")
            thumbnail_dir = root / ".cache" / "thumbnails"
            thumbnail_dir.mkdir(parents=True)
            thumbnail = thumbnail_dir / "open-md5.jpg"
            thumbnail.write_bytes(b"cached-thumbnail")
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="open-md5",
                modify_time=1.0,
                description="权限受限的照片",
                tags=["打开"],
                colors=["灰色"],
            )
            service = ArkSearchService(
                db_path=root / "limb_ark.sqlite3",
                photo_root=photo_root,
                thumbnail_dir=thumbnail_dir,
            )
            calls = []

            def fake_run(command, check):
                calls.append((command, check))

            with patch("backend.ark_main.shutil.copyfile", side_effect=[PermissionError("TCC denied"), None]):
                opened = service.open_photo_in_native_viewer("open-md5", open_runner=fake_run)

            self.assertEqual(opened["status"], "opened")
            self.assertEqual(opened["quality"], "cached-thumbnail")
            self.assertTrue(opened["path"].endswith(".cache/native-open/open-md5.jpg"))
            self.assertEqual(Path(opened["path"]).read_bytes(), b"cached-thumbnail")
            self.assertEqual(calls, [(["open", opened["path"]], True)])

    def test_search_photo_alias_routes_support_update_and_delete(self):
        class FakeService:
            def __init__(self):
                self.updated = None
                self.deleted = None
                self.opened = None

            def update_photo_metadata(self, md5, *, description=None, tags=None, colors=None):
                self.updated = (md5, description, tags, colors)
                return {
                    "md5": md5,
                    "path": "/tmp/a.jpg",
                    "url": "http://127.0.0.1:8004/photos/a.jpg",
                    "thumbnail_url": "http://127.0.0.1:8004/thumbnails/abc.jpg",
                    "description": description,
                    "tags": tags,
                    "colors": colors,
                }

            def delete_photo(self, md5):
                self.deleted = md5
                return {"status": "deleted", "md5": md5, "path": "/tmp/a.jpg"}

            def open_photo_in_native_viewer(self, md5):
                self.opened = md5
                return {"status": "opened", "md5": md5, "path": "/tmp/a.jpg"}

        fake_service = FakeService()
        with patch("backend.ark_main.service", fake_service):
            update_response = ark_main.update_search_photo(
                "abc",
                PhotoUpdateRequest(description="新描述", tags=["小菲"], colors=["蓝色"]),
            )
            delete_response = ark_main.delete_search_photo("abc")
            open_response = ark_main.open_photo_in_native_viewer("abc")

        self.assertEqual(update_response["description"], "新描述")
        self.assertEqual(delete_response["status"], "deleted")
        self.assertEqual(open_response["status"], "opened")
        self.assertEqual(fake_service.updated, ("abc", "新描述", ["小菲"], ["蓝色"]))
        self.assertEqual(fake_service.deleted, "abc")
        self.assertEqual(fake_service.opened, "abc")


if __name__ == "__main__":
    unittest.main()
