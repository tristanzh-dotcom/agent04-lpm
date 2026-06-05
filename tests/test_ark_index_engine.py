import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.ark_index_engine import (
    ArkPhotoIndexDatabase,
    ArkVisionClient,
    ArkVisionBatchIndexer,
    ARK_MODEL,
    RateLimitError,
    extract_photo_capture_metadata,
    optimize_image_for_ark,
)


class FakeArkClient:
    def __init__(self, failures_before_success=0):
        self.failures_before_success = failures_before_success
        self.calls = []

    async def describe_image(self, image_path: Path) -> dict:
        self.calls.append(Path(image_path))
        if len(self.calls) <= self.failures_before_success:
            raise RateLimitError("429 Rate Limit Exceeded")
        return {
            "description": "小菲穿着跳伞装备坐在直升机里，窗外是山谷。",
            "tags": ["小菲", "跳伞", "直升机", "户外"],
            "colors": ["白色", "绿色"],
        }


class ArkIndexEngineTests(unittest.TestCase):
    def create_image(self, path: Path, size=(2400, 1600)) -> Path:
        image = Image.new("RGB", size, (120, 160, 200))
        image.save(path, format="JPEG", quality=95)
        return path

    def test_optimize_image_limits_long_edge_and_strips_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.create_image(Path(temp_dir) / "source.jpg", size=(2400, 1200))
            output = optimize_image_for_ark(source, Path(temp_dir), max_edge=1024)

            with Image.open(output) as optimized:
                self.assertLessEqual(max(optimized.size), 1024)
                self.assertEqual(optimized.format, "JPEG")
                self.assertEqual(optimized.mode, "RGB")

            self.assertLess(output.stat().st_size, source.stat().st_size)

    def test_optimize_image_pads_tiny_short_edge_to_ark_minimum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.create_image(Path(temp_dir) / "source.jpg", size=(13, 1200))
            output = optimize_image_for_ark(source, Path(temp_dir), max_edge=1024)

            with Image.open(output) as optimized:
                self.assertGreaterEqual(min(optimized.size), 14)
                self.assertLessEqual(max(optimized.size), 1024)

    def test_optimize_image_uses_sips_fallback_for_heic_when_pillow_cannot_decode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.heic"
            source.write_bytes(b"fake-heic")

            def fake_sips(command, check, capture_output, text):
                output = Path(command[-1])
                self.create_image(output, size=(1600, 1200))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("backend.ark_index_engine.subprocess.run", side_effect=fake_sips) as run_sips:
                output = optimize_image_for_ark(source, root / "optimized", max_edge=1024)

            run_sips.assert_called_once()
            with Image.open(output) as optimized:
                self.assertEqual(optimized.format, "JPEG")
                self.assertLessEqual(max(optimized.size), 1024)

    def test_extract_photo_capture_metadata_reads_exif_datetime_original(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "dated.jpg"
            image = Image.new("RGB", (32, 32), (200, 40, 40))
            exif = Image.Exif()
            exif[36867] = "2024:08:12 15:23:45"
            image.save(source, format="JPEG", exif=exif)

            metadata = extract_photo_capture_metadata(source)

            self.assertEqual(metadata["taken_at"], "2024-08-12T15:23:45")
            self.assertEqual(metadata["metadata_source"], "exif")

    def test_database_upsert_and_fts_search_returns_matching_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = ArkPhotoIndexDatabase(Path(temp_dir) / "limb_ark.sqlite3")
            image_path = Path(temp_dir) / "a.jpg"
            self.create_image(image_path, size=(32, 32))

            db.upsert_photo(
                path=image_path,
                md5="abc",
                modify_time=123.0,
                description="小菲穿着跳伞装备坐在直升机里",
                tags=["小菲", "跳伞", "直升机"],
                colors=["白色"],
            )

            rows = db.search("小菲 跳伞", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["path"], str(image_path.resolve()))
            self.assertEqual(rows[0]["md5"], "abc")
            self.assertIn("跳伞", rows[0]["tags"])

    def test_database_stores_capture_datetime_and_location_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = ArkPhotoIndexDatabase(Path(temp_dir) / "limb_ark.sqlite3")
            image_path = Path(temp_dir) / "metadata.jpg"
            self.create_image(image_path, size=(32, 32))

            db.upsert_photo(
                path=image_path,
                md5="meta-md5",
                modify_time=123.0,
                description="老张在上海外滩散步",
                tags=["老张", "外滩"],
                colors=["蓝色"],
                taken_at="2024-08-12T15:23:45",
                latitude=31.2304,
                longitude=121.4737,
                location_text="31.230400, 121.473700",
                metadata_source="exif",
            )

            rows = db.search("外滩", limit=10)

            self.assertEqual(rows[0]["taken_at"], "2024-08-12T15:23:45")
            self.assertEqual(rows[0]["latitude"], 31.2304)
            self.assertEqual(rows[0]["longitude"], 121.4737)
            self.assertEqual(rows[0]["location_text"], "31.230400, 121.473700")
            self.assertEqual(rows[0]["metadata_source"], "exif")

    def test_database_backfills_apple_photos_location_display_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            image_path = root / "originals" / "A" / "asset-1.jpeg"
            image_path.parent.mkdir(parents=True)
            self.create_image(image_path, size=(32, 32))
            db.upsert_photo(
                path=image_path,
                md5="abc",
                modify_time=1.0,
                description="牛肉汤",
                tags=["牛肉汤"],
                colors=["棕色"],
                location_text="31.209147, 121.403364",
            )

            updated = db.backfill_location_display_names(
                [{"original_path": image_path, "location_display_name": "上海市 长宁区 虹桥南丰城"}]
            )
            rows = db.search("牛肉汤", limit=1)

            self.assertEqual(updated, 1)
            self.assertEqual(rows[0]["location_display_name"], "上海市 长宁区 虹桥南丰城")

    def test_database_backfills_missing_capture_metadata_without_reindexing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = ArkPhotoIndexDatabase(Path(temp_dir) / "limb_ark.sqlite3")
            image_path = Path(temp_dir) / "old.jpg"
            self.create_image(image_path, size=(32, 32))
            db.upsert_photo(
                path=image_path,
                md5="old-md5",
                modify_time=123.0,
                description="旧索引照片",
                tags=["旧索引"],
                colors=["灰色"],
            )

            updated = db.backfill_capture_metadata(
                extractor=lambda path: {
                    "taken_at": "2024-09-01T08:00:00",
                    "latitude": 22.5431,
                    "longitude": 114.0579,
                    "location_text": "22.543100, 114.057900",
                    "metadata_source": "exif",
                }
            )

            rows = db.search("旧索引", limit=10)
            self.assertEqual(updated, 1)
            self.assertEqual(rows[0]["taken_at"], "2024-09-01T08:00:00")
            self.assertEqual(rows[0]["location_text"], "22.543100, 114.057900")

    def test_database_stores_optional_photokit_asset_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            image_path = root / "photo.jpg"
            self.create_image(image_path, size=(32, 32))

            db.upsert_photo(
                path=image_path,
                md5="asset-md5",
                modify_time=1.0,
                description="老张在餐厅吃饭",
                tags=["老张", "吃饭", "餐厅"],
                colors=["暖黄"],
                asset_id="asset123",
                local_identifier="LOCAL/123",
                original_path=image_path,
                thumbnail_path=root / ".cache" / "asset123.jpg",
                source="photokit",
            )

            rows = db.search("吃饭", limit=10)

            self.assertEqual(rows[0]["asset_id"], "asset123")
            self.assertEqual(rows[0]["local_identifier"], "LOCAL/123")
            self.assertEqual(rows[0]["original_path"], str(image_path.resolve()))
            self.assertEqual(rows[0]["source"], "photokit")

    def test_database_get_photos_by_paths_matches_original_path_for_derivative_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            derivative_path = root / "resources" / "derivatives" / "A" / "ASSET_1_105_c.jpeg"
            original_path = root / "originals" / "A" / "asset.jpeg"
            derivative_path.parent.mkdir(parents=True)
            original_path.parent.mkdir(parents=True)
            self.create_image(derivative_path, size=(32, 32))

            db.upsert_photo(
                path=derivative_path,
                md5="derivative-md5",
                modify_time=1.0,
                description="小菲在草地上抱着狗",
                tags=["小菲", "狗"],
                colors=["绿色"],
                original_path=original_path,
                source="apple_photos",
            )

            rows = db.get_photos_by_paths([original_path])

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["path"], str(derivative_path.resolve()))
            self.assertEqual(rows[0]["original_path"], str(original_path.resolve()))

    def test_database_count_photos_reports_index_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = ArkPhotoIndexDatabase(Path(temp_dir) / "limb_ark.sqlite3")
            image_path = Path(temp_dir) / "a.jpg"
            self.create_image(image_path, size=(32, 32))

            self.assertEqual(db.count_photos(), 0)

            db.upsert_photo(
                path=image_path,
                md5="abc",
                modify_time=123.0,
                description="小菲和狗在草地上",
                tags=["小菲", "狗"],
                colors=["绿色"],
            )

            self.assertEqual(db.count_photos(), 1)

    def test_jieba_tokenized_search_matches_compact_chinese_phrase(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = ArkPhotoIndexDatabase(Path(temp_dir) / "limb_ark.sqlite3")
            image_path = Path(temp_dir) / "sea.jpg"
            self.create_image(image_path, size=(32, 32))
            db.upsert_photo(
                path=image_path,
                md5="sea-md5",
                modify_time=1.0,
                description="小菲站在蓝天和大海之间，画面明亮清爽",
                tags=["蓝天", "大海", "旅行"],
                colors=["蓝色", "白色"],
            )

            rows = db.search("蓝天大海", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["md5"], "sea-md5")

    def test_incremental_scan_skips_unchanged_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = self.create_image(root / "photo.jpg", size=(64, 64))
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5=ArkVisionBatchIndexer.compute_md5(image_path),
                modify_time=image_path.stat().st_mtime,
                description="已存在的照片",
                tags=["已存在"],
                colors=[],
            )
            indexer = ArkVisionBatchIndexer(
                photo_root=root,
                database=db,
                ark_client=FakeArkClient(),
                max_concurrency=2,
                retry_base_seconds=0,
            )

            count = asyncio.run(indexer.scan_and_index())

            self.assertEqual(count, 0)
            self.assertEqual(indexer.ark_client.calls, [])

    def test_rate_limit_retry_eventually_indexes_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = self.create_image(root / "photo.jpg", size=(64, 64))
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            client = FakeArkClient(failures_before_success=2)
            indexer = ArkVisionBatchIndexer(
                photo_root=root,
                database=db,
                ark_client=client,
                max_concurrency=1,
                max_retries=3,
                retry_base_seconds=0,
            )

            count = asyncio.run(indexer.scan_and_index())
            rows = db.search("跳伞", limit=10)

            self.assertEqual(count, 1)
            self.assertEqual(len(client.calls), 3)
            self.assertEqual(len(rows), 1)

    def test_indexer_persists_md5_thumbnail_for_new_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = self.create_image(root / "photo.jpg", size=(2400, 1600))
            db = ArkPhotoIndexDatabase(root / "limb_ark.sqlite3")
            thumb_dir = root / ".cache" / "thumbnails"
            indexer = ArkVisionBatchIndexer(
                photo_root=root,
                database=db,
                ark_client=FakeArkClient(),
                thumbnail_dir=thumb_dir,
                max_concurrency=1,
                retry_base_seconds=0,
            )

            count = asyncio.run(indexer.scan_and_index())
            md5 = ArkVisionBatchIndexer.compute_md5(image_path)
            thumbnail = thumb_dir / f"{md5}.jpg"

            self.assertEqual(count, 1)
            self.assertTrue(thumbnail.exists())
            with Image.open(thumbnail) as image:
                self.assertLessEqual(max(image.size), 1024)

    def test_ark_client_uses_endpoint_id_when_configured(self):
        class FakeCompletions:
            def __init__(self):
                self.kwargs = None

            async def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps(
                                    {
                                        "description": "红色方块",
                                        "tags": ["红色"],
                                        "colors": ["红色"],
                                    },
                                    ensure_ascii=False,
                                )
                            )
                        )
                    ]
                )

        class FakeAsyncArk:
            instance = None

            def __init__(self, api_key):
                self.api_key = api_key
                self.chat = SimpleNamespace(completions=FakeCompletions())
                FakeAsyncArk.instance = self

        fake_module = SimpleNamespace(AsyncArk=FakeAsyncArk)
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = self.create_image(Path(temp_dir) / "photo.jpg", size=(32, 32))
            with patch.dict(sys.modules, {"volcenginesdkarkruntime": fake_module}):
                with patch.dict(
                    "os.environ",
                    {"ARK_API_KEY": "las-test", "ARK_ENDPOINT_ID": "ep-legacy"},
                    clear=False,
                ):
                    client = ArkVisionClient()
                    asyncio.run(client.describe_image(image_path))

        self.assertEqual(FakeAsyncArk.instance.chat.completions.kwargs["model"], "ep-legacy")

    def test_ark_client_sends_local_image_as_base64_data_url(self):
        class FakeCompletions:
            def __init__(self):
                self.kwargs = None

            async def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps(
                                    {
                                        "description": "红色方块",
                                        "tags": ["红色"],
                                        "colors": ["红色"],
                                    },
                                    ensure_ascii=False,
                                )
                            )
                        )
                    ]
                )

        class FakeAsyncArk:
            instance = None

            def __init__(self, api_key):
                self.api_key = api_key
                self.chat = SimpleNamespace(completions=FakeCompletions())
                FakeAsyncArk.instance = self

        fake_module = SimpleNamespace(AsyncArk=FakeAsyncArk)
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = self.create_image(Path(temp_dir) / "photo.jpg", size=(32, 32))
            with patch.dict(sys.modules, {"volcenginesdkarkruntime": fake_module}):
                with patch.dict("os.environ", {"ARK_API_KEY": "ark-test"}, clear=False):
                    client = ArkVisionClient()
                    asyncio.run(client.describe_image(image_path))

        image_url = FakeAsyncArk.instance.chat.completions.kwargs["messages"][1]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/jpeg;base64,"))


if __name__ == "__main__":
    unittest.main()
