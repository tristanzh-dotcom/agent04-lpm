import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.apple_photos_bridge import ApplePhotosPeopleCache
from backend.ark_index_engine import ArkPhotoIndexDatabase, ArkVisionBatchIndexer, ArkVisionError, RateLimitError
from run_index_pipeline import IndexPipeline, estimate_bill_yuan


class FakeClient:
    def __init__(self):
        self.calls = []

    async def describe_image(self, image_path: Path):
        self.calls.append(Path(image_path))
        return {
            "description": "蓝天大海边的旅行照片",
            "tags": ["蓝天", "大海", "旅行"],
            "colors": ["蓝色"],
        }


class FailingClient(FakeClient):
    async def describe_image(self, image_path: Path):
        self.calls.append(Path(image_path))
        raise RateLimitError("429 Rate Limit Exceeded")


class TransientEmptyArkClient(FakeClient):
    async def describe_image(self, image_path: Path):
        self.calls.append(Path(image_path))
        if len(self.calls) == 1:
            raise ArkVisionError("方舟视觉推理失败: Expecting value: line 1 column 1 (char 0)")
        return await super().describe_image(image_path)


class RunIndexPipelineTests(unittest.TestCase):
    def create_image(self, path: Path) -> Path:
        Image.new("RGB", (64, 64), (20, 90, 180)).save(path, format="JPEG")
        return path

    def test_estimate_bill_uses_token_count_and_unit_price(self):
        self.assertEqual(estimate_bill_yuan(2500, 0.002), 0.005)

    def test_pipeline_indexes_images_and_reports_stats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = self.create_image(root / "a.jpg")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            pipeline = IndexPipeline(
                photo_root=root,
                database=db,
                ark_client=FakeClient(),
                thumbnail_dir=root / ".cache" / "thumbnails",
                error_log=root / "errors.log",
                concurrency=1,
                show_progress=False,
            )

            stats = asyncio.run(pipeline.run())
            rows = db.search("蓝天大海", limit=10)

            self.assertEqual(stats.indexed, 1)
            self.assertEqual(stats.skipped, 0)
            self.assertEqual(stats.failed, 0)
            self.assertEqual(len(rows), 1)
            self.assertTrue((root / ".cache" / "thumbnails" / f"{stats.indexed_md5s[0]}.jpg").exists())

    def test_pipeline_backfills_apple_photos_location_names_after_indexing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = self.create_image(root / "a.jpg")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            pipeline = IndexPipeline(
                photo_root=root,
                database=db,
                ark_client=FakeClient(),
                thumbnail_dir=root / ".cache" / "thumbnails",
                error_log=root / "errors.log",
                concurrency=1,
                show_progress=False,
                location_metadata_provider=lambda: [
                    {"original_path": image_path, "location_display_name": "上海市 长宁区 虹桥南丰城"}
                ],
            )

            asyncio.run(pipeline.run())
            rows = db.search("蓝天大海", limit=10)

            self.assertEqual(rows[0]["location_display_name"], "上海市 长宁区 虹桥南丰城")

    def test_pipeline_skips_location_name_backfill_when_sqlite_is_locked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = self.create_image(root / "a.jpg")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=image_path,
                md5="abc",
                modify_time=1.0,
                description="蓝天大海边的旅行照片",
                tags=["蓝天", "大海", "旅行"],
                colors=["蓝色"],
            )

            def locked_backfill(rows):
                raise sqlite3.OperationalError("database is locked")

            db.backfill_location_display_names = locked_backfill
            pipeline = IndexPipeline(
                photo_root=root,
                database=db,
                ark_client=FakeClient(),
                thumbnail_dir=root / ".cache" / "thumbnails",
                error_log=root / "errors.log",
                concurrency=1,
                show_progress=False,
                location_metadata_provider=lambda: [
                    {"original_path": image_path, "location_display_name": "上海市 长宁区 虹桥南丰城"}
                ],
            )

            updated = pipeline._backfill_location_display_names()

            self.assertEqual(updated, 0)

    def test_pipeline_logs_failures_and_continues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_image(root / "a.jpg")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            error_log = root / "errors.log"
            pipeline = IndexPipeline(
                photo_root=root,
                database=db,
                ark_client=FailingClient(),
                error_log=error_log,
                concurrency=1,
                max_retries=0,
                show_progress=False,
            )

            stats = asyncio.run(pipeline.run())

            self.assertEqual(stats.indexed, 0)
            self.assertEqual(stats.failed, 1)
            self.assertIn("429", error_log.read_text(encoding="utf-8"))

    def test_pipeline_retries_transient_empty_ark_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_image(root / "a.jpg")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            client = TransientEmptyArkClient()
            pipeline = IndexPipeline(
                photo_root=root,
                database=db,
                ark_client=client,
                error_log=root / "errors.log",
                concurrency=1,
                max_retries=1,
                retry_base_seconds=0,
                show_progress=False,
            )

            stats = asyncio.run(pipeline.run())

            self.assertEqual(stats.indexed, 1)
            self.assertEqual(stats.failed, 0)
            self.assertGreaterEqual(len(client.calls), 2)

    def test_pipeline_indexes_placeholder_after_persistent_empty_ark_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_image(root / "a.jpg")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")

            class PersistentEmptyArkClient(FakeClient):
                async def describe_image(self, image_path: Path):
                    self.calls.append(Path(image_path))
                    raise ArkVisionError("方舟视觉推理失败: Expecting value: line 1 column 1 (char 0)")

            client = PersistentEmptyArkClient()
            pipeline = IndexPipeline(
                photo_root=root,
                database=db,
                ark_client=client,
                error_log=root / "errors.log",
                concurrency=1,
                max_retries=1,
                retry_base_seconds=0,
                show_progress=False,
            )

            stats = asyncio.run(pipeline.run())
            rows = db.search("待复核", limit=10)

            self.assertEqual(stats.indexed, 1)
            self.assertEqual(stats.failed, 0)
            self.assertEqual(len(rows), 1)
            self.assertIn("视觉模型空响应", rows[0]["tags"])

    def test_pipeline_limit_only_processes_first_pending_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.create_image(root / "a.jpg")
            self.create_image(root / "b.jpg")
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            pipeline = IndexPipeline(
                photo_root=root,
                database=db,
                ark_client=FakeClient(),
                error_log=root / "errors.log",
                concurrency=1,
                limit=1,
                show_progress=False,
            )

            stats = asyncio.run(pipeline.run())

            self.assertEqual(stats.indexed, 1)
            self.assertEqual(db.count_photos(), 1)

    def test_pipeline_indexes_apple_photos_derivative_with_original_path_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = root / "Photos Library.photoslibrary"
            derivative = library / "resources" / "derivatives" / "A" / "ASSET_1_105_c.jpeg"
            derivative.parent.mkdir(parents=True)
            self.create_image(derivative)
            original = library / "originals" / "A" / "asset.jpeg"
            original.parent.mkdir(parents=True)
            photo_root = library / "originals"
            photo_root.mkdir(parents=True, exist_ok=True)
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            pipeline = IndexPipeline(
                photo_root=photo_root,
                database=db,
                ark_client=FakeClient(),
                thumbnail_dir=root / ".cache" / "thumbnails",
                error_log=root / "errors.log",
                concurrency=1,
                show_progress=False,
                asset_resource_provider=lambda: [
                    {
                        "source_path": derivative,
                        "original_path": original,
                        "asset_id": "asset-id",
                        "local_identifier": "ASSET/L0/001",
                        "source": "apple_photos",
                    }
                ],
                location_metadata_provider=lambda: [],
            )

            stats = asyncio.run(pipeline.run())
            rows = db.get_photos_by_paths([original])

            self.assertEqual(stats.indexed, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["path"], str(derivative.resolve()))
            self.assertEqual(rows[0]["original_path"], str(original.resolve()))
            self.assertEqual(rows[0]["asset_id"], "asset-id")
            self.assertEqual(rows[0]["source"], "apple_photos")

    def test_pipeline_skips_apple_photos_source_quality_swap_without_model_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = root / "Photos Library.photoslibrary"
            derivative = library / "resources" / "derivatives" / "A" / "ASSET_1_105_c.jpeg"
            original = library / "originals" / "A" / "asset.jpeg"
            derivative.parent.mkdir(parents=True)
            original.parent.mkdir(parents=True)
            self.create_image(derivative)
            self.create_image(original)
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            db.upsert_photo(
                path=derivative,
                md5="old-derivative-md5",
                modify_time=derivative.stat().st_mtime,
                description="已识别的预览图",
                tags=["预览图"],
                colors=["蓝色"],
                asset_id="asset-id",
                local_identifier="ASSET/L0/001",
                original_path=original,
                source="apple_photos",
            )
            client = FakeClient()
            pipeline = IndexPipeline(
                photo_root=library / "originals",
                database=db,
                ark_client=client,
                thumbnail_dir=root / ".cache" / "thumbnails",
                error_log=root / "errors.log",
                concurrency=1,
                show_progress=False,
                asset_resource_provider=lambda: [
                    {
                        "source_path": original,
                        "original_path": original,
                        "asset_id": "asset-id",
                        "local_identifier": "ASSET/L0/001",
                        "source": "apple_photos",
                        "source_kind": "original",
                    }
                ],
                location_metadata_provider=lambda: [],
            )

            with patch.object(
                ArkVisionBatchIndexer,
                "compute_md5",
                side_effect=AssertionError("stable Apple Photos assets should skip before file reads"),
            ):
                stats = asyncio.run(pipeline.run())

            self.assertEqual(stats.indexed, 0)
            self.assertEqual(stats.skipped, 1)
            self.assertEqual(client.calls, [])

    def test_pipeline_uses_apple_photos_asset_cache_when_bridge_is_denied(self):
        class DeniedAppleBridge:
            def __init__(self, library_path):
                self.photo_library_path = Path(library_path)

            def iter_image_asset_resources(self):
                raise RuntimeError("authorization denied")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = root / "Photos Library.photoslibrary"
            derivative = library / "resources" / "derivatives" / "A" / "ASSET_1_105_c.jpeg"
            derivative.parent.mkdir(parents=True)
            self.create_image(derivative)
            original = library / "originals" / "A" / "asset.jpeg"
            original.parent.mkdir(parents=True)
            photo_root = library / "originals"
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            cache_path = root / "apple_people_cache.json"
            ApplePhotosPeopleCache(cache_path).write_snapshot(
                people=[],
                links=[],
                assets=[
                    {
                        "source_path": str(derivative),
                        "original_path": str(original),
                        "asset_id": "asset-id",
                        "local_identifier": "ASSET/L0/001",
                        "source": "apple_photos",
                        "source_kind": "derivative",
                    }
                ],
            )
            client = FakeClient()
            pipeline = IndexPipeline(
                photo_root=photo_root,
                database=db,
                ark_client=client,
                thumbnail_dir=root / ".cache" / "thumbnails",
                error_log=root / "errors.log",
                concurrency=1,
                show_progress=False,
                location_metadata_provider=lambda: [],
            )

            with patch.dict("os.environ", {"LIMB_APPLE_PEOPLE_CACHE": str(cache_path)}, clear=False), \
                 patch("run_index_pipeline.ApplePhotosPeopleBridge", DeniedAppleBridge):
                stats = asyncio.run(pipeline.run())

            rows = db.get_photos_by_paths([original])
            self.assertEqual(stats.indexed, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["path"], str(derivative.resolve()))
            self.assertEqual(rows[0]["asset_id"], "asset-id")

    def test_pipeline_skips_unreadable_apple_photos_assets_and_continues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = root / "Photos Library.photoslibrary"
            unreadable = library / "originals" / "A" / "unreadable.jpeg"
            readable = library / "originals" / "B" / "readable.jpeg"
            unreadable.parent.mkdir(parents=True)
            readable.parent.mkdir(parents=True)
            self.create_image(unreadable)
            self.create_image(readable)
            db = ArkPhotoIndexDatabase(root / "limb.sqlite3")
            error_log = root / "errors.log"
            original_compute_md5 = ArkVisionBatchIndexer.compute_md5

            def compute_md5_or_deny(path):
                if Path(path).name == "unreadable.jpeg":
                    raise PermissionError("Operation not permitted")
                return original_compute_md5(path)

            pipeline = IndexPipeline(
                photo_root=library / "originals",
                database=db,
                ark_client=FakeClient(),
                thumbnail_dir=root / ".cache" / "thumbnails",
                error_log=error_log,
                concurrency=1,
                show_progress=False,
                asset_resource_provider=lambda: [
                    {
                        "source_path": unreadable,
                        "original_path": unreadable,
                        "asset_id": "unreadable-asset",
                        "local_identifier": "UNREADABLE/L0/001",
                        "source": "apple_photos",
                    },
                    {
                        "source_path": readable,
                        "original_path": readable,
                        "asset_id": "readable-asset",
                        "local_identifier": "READABLE/L0/001",
                        "source": "apple_photos",
                    },
                ],
                location_metadata_provider=lambda: [],
            )

            with patch.object(ArkVisionBatchIndexer, "compute_md5", side_effect=compute_md5_or_deny):
                stats = asyncio.run(pipeline.run())

            rows = db.get_photos_by_paths([readable])
            self.assertEqual(stats.indexed, 1)
            self.assertEqual(len(rows), 1)
            self.assertIn("Operation not permitted", error_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
