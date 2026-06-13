from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tqdm import tqdm

from backend.ark_index_engine import (
    ArkPhotoIndexDatabase,
    ArkVisionBatchIndexer,
    ArkVisionClient,
    ArkVisionError,
    RateLimitError,
    extract_photo_capture_metadata,
    is_transient_ark_vision_error,
    optimize_image_for_ark,
    persist_thumbnail,
)
from backend.apple_photos_bridge import ApplePhotosPeopleBridge, ApplePhotosPeopleCache


DEFAULT_ESTIMATED_TOKENS_PER_IMAGE = 900
DEFAULT_PRICE_YUAN_PER_1K_TOKENS = 0.002
DEFAULT_THUMBNAIL_DIR = os.path.expanduser("~/.cache/local-photo-model/thumbnails")


@dataclass
class PipelineStats:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    estimated_tokens: int = 0
    indexed_md5s: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineWorkItem:
    source_path: Path
    path: Path
    original_path: Path | None = None
    asset_id: str | None = None
    local_identifier: str | None = None
    source: str = "filesystem"


def estimate_bill_yuan(total_tokens: int, price_yuan_per_1k_tokens: float) -> float:
    return round((total_tokens / 1000) * price_yuan_per_1k_tokens, 6)


class IndexPipeline:
    """面向数万张照片的可观测索引流水线。

    与 `ArkVisionBatchIndexer` 使用同一套底层压缩、缩略图、SQLite 写入逻辑；
    这里额外增加进度条、错误日志、断点续传摘要与账单预估。
    """

    def __init__(
        self,
        *,
        photo_root: str | os.PathLike[str],
        database: ArkPhotoIndexDatabase,
        ark_client: Any | None = None,
        thumbnail_dir: str | os.PathLike[str] | None = None,
        error_log: str | os.PathLike[str] = "data/indexing_errors.log",
        concurrency: int = 2,
        max_retries: int = 5,
        retry_base_seconds: float = 1.0,
        max_edge: int = 1024,
        estimated_tokens_per_image: int = DEFAULT_ESTIMATED_TOKENS_PER_IMAGE,
        limit: int | None = None,
        show_progress: bool = True,
        location_metadata_provider: Any | None = None,
        asset_resource_provider: Any | None = None,
    ) -> None:
        self.photo_root = Path(photo_root).expanduser().resolve()
        self.database = database
        self.ark_client = ark_client or ArkVisionClient()
        self.thumbnail_dir = Path(thumbnail_dir or DEFAULT_THUMBNAIL_DIR).expanduser().resolve()
        self.error_log = Path(error_log).expanduser().resolve()
        self.concurrency = max(1, int(concurrency))
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.max_edge = max_edge
        self.estimated_tokens_per_image = estimated_tokens_per_image
        self.limit = limit
        self.show_progress = show_progress
        self.location_metadata_provider = location_metadata_provider or self._default_location_metadata_provider
        self.asset_resource_provider = asset_resource_provider or self._default_asset_resource_provider

    async def run(self) -> PipelineStats:
        queue, skipped = self._build_queue()
        stats = PipelineStats(skipped=skipped)
        work_queue: asyncio.Queue[PipelineWorkItem] = asyncio.Queue()
        for path in queue:
            work_queue.put_nowait(path)

        progress = tqdm(total=len(queue), desc="LIMB Ark 全量索引", unit="张", disable=not self.show_progress)
        workers = [asyncio.create_task(self._worker(work_queue, stats, progress)) for _ in range(self.concurrency)]
        await work_queue.join()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        progress.close()
        self._backfill_location_display_names()
        stats.estimated_tokens = stats.indexed * self.estimated_tokens_per_image
        self.print_summary(stats)
        return stats

    def _default_location_metadata_provider(self) -> list[dict[str, Any]]:
        library_path = self.photo_root
        if self.photo_root.name == "originals" and self.photo_root.parent.name.endswith(".photoslibrary"):
            library_path = self.photo_root.parent
        if not library_path.name.endswith(".photoslibrary"):
            return []
        try:
            return ApplePhotosPeopleBridge(library_path).iter_asset_location_metadata()
        except Exception as exc:
            print(f"[LIMB-Ark] Apple Photos 地点继承跳过: {exc}", flush=True)
            return []

    def _default_asset_resource_provider(self) -> list[dict[str, Any]] | None:
        library_path = self._photos_library_path()
        if library_path is None:
            return None
        try:
            return ApplePhotosPeopleBridge(library_path).iter_image_asset_resources()
        except Exception as exc:
            print(f"[LIMB-Ark] Apple Photos 全量资产读取跳过: {exc}", flush=True)
        cached_assets = self._cached_apple_asset_resources(library_path)
        if cached_assets:
            print(f"[LIMB-Ark] 已从 Apple Photos 缓存继承资产 {len(cached_assets)} 条。", flush=True)
            return cached_assets
        return None

    def _cached_apple_asset_resources(self, library_path: Path) -> list[dict[str, Any]]:
        cache = ApplePhotosPeopleCache(os.environ.get("LIMB_APPLE_PEOPLE_CACHE", "data/apple_people_cache.json"))
        try:
            assets = cache.iter_image_asset_resources()
        except Exception as exc:
            print(f"[LIMB-Ark] Apple Photos 资产缓存读取失败: {exc}", flush=True)
            return []

        library_root = library_path.expanduser().resolve()
        filtered: list[dict[str, Any]] = []
        for asset in assets:
            for value in (asset.get("source_path"), asset.get("original_path")):
                if not value:
                    continue
                try:
                    Path(value).expanduser().resolve().relative_to(library_root)
                except (OSError, ValueError):
                    continue
                filtered.append(asset)
                break
        return filtered

    def _photos_library_path(self) -> Path | None:
        if self.photo_root.name == "originals" and self.photo_root.parent.name.endswith(".photoslibrary"):
            return self.photo_root.parent
        if self.photo_root.name.endswith(".photoslibrary"):
            return self.photo_root
        return None

    def _backfill_location_display_names(self) -> int:
        rows = self.location_metadata_provider() if self.location_metadata_provider else []
        if not rows:
            return 0
        try:
            updated = self.database.backfill_location_display_names(rows)
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            print(f"[LIMB-Ark] Apple Photos 拍摄地点继承跳过: {exc}", flush=True)
            return 0
        if updated:
            print(f"[LIMB-Ark] 已继承 Apple Photos 拍摄地点 {updated} 条。", flush=True)
        return updated

    def _build_queue(self) -> tuple[list[PipelineWorkItem], int]:
        if not self.photo_root.exists() or not self.photo_root.is_dir():
            raise FileNotFoundError(f"相册目录不存在: {self.photo_root}")

        apple_assets = self.asset_resource_provider() if self.asset_resource_provider else None
        if apple_assets is not None:
            self._write_apple_asset_cache(apple_assets)
            return self._build_apple_photos_queue(apple_assets)

        scanner = ArkVisionBatchIndexer(
            photo_root=self.photo_root,
            database=self.database,
            ark_client=self.ark_client,
            thumbnail_dir=self.thumbnail_dir,
            max_concurrency=self.concurrency,
        )
        queue: list[PipelineWorkItem] = []
        skipped = 0
        for path in scanner.iter_image_files(self.photo_root):
            md5 = ArkVisionBatchIndexer.compute_md5(path)
            modify_time = path.stat().st_mtime
            if self.database.is_current(path, md5, modify_time):
                skipped += 1
            else:
                queue.append(PipelineWorkItem(source_path=path, path=path))
        if self.limit is not None:
            queue = queue[: max(0, int(self.limit))]
        return queue, skipped

    def _write_apple_asset_cache(self, apple_assets: list[dict[str, Any]]) -> None:
        library_path = self._photos_library_path()
        if library_path is None:
            return
        try:
            bridge = ApplePhotosPeopleBridge(library_path)
            cache = ApplePhotosPeopleCache(os.environ.get("LIMB_APPLE_PEOPLE_CACHE", "data/apple_people_cache.json"))
            people = bridge.list_named_people()
            links = bridge.iter_person_asset_links()
            cache.write_snapshot(people=people, links=links, assets=apple_assets)
        except Exception as exc:
            print(f"[LIMB-Ark] Apple Photos 资产缓存写入跳过: {exc}", flush=True)

    def _build_apple_photos_queue(self, asset_rows: list[dict[str, Any]]) -> tuple[list[PipelineWorkItem], int]:
        queue: list[PipelineWorkItem] = []
        skipped = 0
        indexed_by_stable_key: dict[str, dict[str, Any]] = {}
        for row in self.database.photo_fingerprints():
            for key in (row.get("asset_id"), row.get("local_identifier")):
                if key:
                    indexed_by_stable_key[str(key)] = row
        for row in asset_rows:
            source_path = Path(row["source_path"]).expanduser().resolve()
            if not source_path.is_file():
                continue
            stable_match = any(
                str(key) in indexed_by_stable_key for key in (row.get("asset_id"), row.get("local_identifier")) if key
            )
            if stable_match:
                skipped += 1
                continue
            try:
                md5 = ArkVisionBatchIndexer.compute_md5(source_path)
                modify_time = source_path.stat().st_mtime
            except OSError as exc:
                self._log_error(source_path, exc)
                skipped += 1
                continue
            if self.database.is_current(source_path, md5, modify_time):
                skipped += 1
                continue
            queue.append(
                PipelineWorkItem(
                    source_path=source_path,
                    path=source_path,
                    original_path=Path(row["original_path"]).expanduser().resolve() if row.get("original_path") else None,
                    asset_id=row.get("asset_id"),
                    local_identifier=row.get("local_identifier"),
                    source=row.get("source") or "apple_photos",
                )
            )
        if self.limit is not None:
            queue = queue[: max(0, int(self.limit))]
        return queue, skipped

    async def _worker(self, queue: asyncio.Queue[PipelineWorkItem], stats: PipelineStats, progress: tqdm) -> None:
        while True:
            item = await queue.get()
            try:
                await self._index_one(item, stats)
            except Exception as exc:
                stats.failed += 1
                self._log_error(item.source_path, exc)
            finally:
                progress.update(1)
                queue.task_done()

    async def _index_one(self, item: PipelineWorkItem, stats: PipelineStats) -> None:
        path = item.source_path
        md5 = ArkVisionBatchIndexer.compute_md5(path)
        modify_time = path.stat().st_mtime
        capture_metadata = extract_photo_capture_metadata(path)
        with tempfile.TemporaryDirectory(prefix="limb-pipeline-") as temp_dir:
            optimized = optimize_image_for_ark(path, temp_dir, max_edge=self.max_edge)
            persist_thumbnail(optimized, self.thumbnail_dir, md5)
            payload = await self._describe_with_retry(optimized)

        self.database.upsert_photo(
            path=item.path,
            md5=md5,
            modify_time=modify_time,
            description=payload["description"],
            tags=payload["tags"],
            colors=payload["colors"],
            raw_json=payload,
            asset_id=item.asset_id,
            local_identifier=item.local_identifier,
            original_path=item.original_path,
            source=item.source,
            **capture_metadata,
        )
        stats.indexed += 1
        stats.indexed_md5s.append(md5)

    async def _describe_with_retry(self, image_path: Path) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                return await self.ark_client.describe_image(image_path)
            except RateLimitError:
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(self.retry_base_seconds * (2**attempt))
            except ArkVisionError as exc:
                text = str(exc)
                if attempt >= self.max_retries and ("Expecting value" in text or "JSONDecodeError" in text):
                    return {
                        "description": "视觉模型多次返回空内容的本地相册图片，已保留为待复核索引。",
                        "tags": ["待复核", "视觉模型空响应", "本地相册"],
                        "colors": [],
                        "fallback_reason": text,
                    }
                if attempt >= self.max_retries or not is_transient_ark_vision_error(exc):
                    raise
                await asyncio.sleep(self.retry_base_seconds * (2**attempt))
            except Exception as exc:
                text = str(exc)
                if ("500" in text or "502" in text or "503" in text or "504" in text) and attempt < self.max_retries:
                    await asyncio.sleep(self.retry_base_seconds * (2**attempt))
                    continue
                raise
        raise RuntimeError("Ark 推理重试耗尽")

    def _log_error(self, path: Path, error: Exception) -> None:
        self.error_log.parent.mkdir(parents=True, exist_ok=True)
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{path}\t{type(error).__name__}\t{error}\n"
        with self.error_log.open("a", encoding="utf-8") as file:
            file.write(line)

    def print_summary(self, stats: PipelineStats) -> None:
        price = float(os.environ.get("LIMB_TOKEN_PRICE_YUAN_PER_1K", DEFAULT_PRICE_YUAN_PER_1K_TOKENS))
        bill = estimate_bill_yuan(stats.estimated_tokens, price)
        print("\n========== LIMB Ark 索引运行摘要 ==========")
        print(f"本次新增成功打标图片数：{stats.indexed}")
        print(f"增量跳过图片数：{stats.skipped}")
        print(f"失败图片数：{stats.failed}")
        print(f"预计消耗总 Token 数：{stats.estimated_tokens}")
        print(f"预估账单：¥{bill:.6f} （按 ¥{price}/千 tokens 估算）")
        print(f"错误日志：{self.error_log}")
        print("==========================================\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="LIMB Ark 全量索引流水线监控脚本")
    parser.add_argument("photo_root", help="真实相册目录")
    parser.add_argument("--db", default=os.environ.get("LIMB_ARK_DB", "data/limb_ark.sqlite3"))
    parser.add_argument("--thumbnail-dir", default=os.environ.get("LIMB_THUMBNAIL_DIR", DEFAULT_THUMBNAIL_DIR))
    parser.add_argument("--error-log", default="data/indexing_errors.log")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--max-edge", type=int, default=1024)
    parser.add_argument("--estimated-tokens-per-image", type=int, default=DEFAULT_ESTIMATED_TOKENS_PER_IMAGE)
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 张待索引图片，用于灰度验证")
    args = parser.parse_args()

    database = ArkPhotoIndexDatabase(args.db)
    pipeline = IndexPipeline(
        photo_root=args.photo_root,
        database=database,
        thumbnail_dir=args.thumbnail_dir,
        error_log=args.error_log,
        concurrency=args.concurrency,
        max_retries=args.max_retries,
        max_edge=args.max_edge,
        estimated_tokens_per_image=args.estimated_tokens_per_image,
        limit=args.limit,
    )
    asyncio.run(pipeline.run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
