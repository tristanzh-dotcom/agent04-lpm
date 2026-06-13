from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jieba
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.ark_index_engine import ArkPhotoIndexDatabase, VALID_EXTENSIONS
from backend.apple_photos_bridge import ApplePhotosPeopleBridge, ApplePhotosPeopleCache, prefetch_originals_if_needed
from backend.face_engine import FaceVectorEngine, FaceVectorError
from backend.geocoding import MacOSReverseGeocoder


def load_local_runtime_config() -> None:
    """优先读取 backend/config.py，避免 launchd 环境变量缺失导致能力降级。"""

    try:
        from backend import config
    except Exception:
        return

    for key in (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "LIMB_PHOTO_ROOT",
        "LIMB_FACE_THRESHOLD",
        "LIMB_PHOTOS_BASE_URL",
        "LIMB_ARK_DB",
        "LIMB_THUMBNAIL_DIR",
    ):
        value = getattr(config, key, None)
        if value is not None and str(value).strip():
            os.environ[key] = str(value)


load_local_runtime_config()


DEFAULT_THUMBNAIL_DIR = os.path.expanduser("~/.cache/local-photo-model/thumbnails")


COARSE_LOCATION_BOUNDS: tuple[tuple[str, float, float, float, float], ...] = (
    ("上海", 30.65, 31.92, 120.85, 122.20),
    ("北京", 39.40, 41.10, 115.40, 117.60),
    ("广州", 22.90, 23.60, 112.80, 114.10),
    ("深圳", 22.35, 22.90, 113.70, 114.70),
    ("杭州", 29.80, 30.60, 119.70, 120.70),
    ("苏州", 30.75, 32.05, 119.85, 121.35),
    ("南京", 31.20, 32.65, 118.30, 119.30),
    ("成都", 30.05, 31.35, 103.25, 104.90),
    ("重庆", 28.15, 30.35, 105.20, 107.30),
    ("武汉", 29.90, 31.35, 113.60, 115.10),
    ("西安", 33.70, 34.80, 108.20, 109.80),
)


def readable_location_name(
    latitude: Any,
    longitude: Any,
    text: Any = None,
    reverse_geocoder: Any | None = None,
) -> str | None:
    """把 EXIF GPS 坐标转换成卡片上适合用户阅读的粗粒度地点名。

    Apple Photos 的地名展示来自系统级反向地理编码。这里先在本地服务层做
    可预测、无额外网络依赖的城市级兜底：如果已有非坐标文字就直接使用；
    如果只有坐标，则按常见城市边界映射成“上海”等可读名称。
    """

    text_value = str(text or "").strip()
    coordinate_text = re.fullmatch(r"-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?", text_value)
    if text_value and not coordinate_text:
        return text_value
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None
    if reverse_geocoder is not None:
        try:
            resolved = reverse_geocoder(round(lat, 6), round(lon, 6))
        except Exception:
            resolved = None
        if resolved:
            return str(resolved)
    for label, min_lat, max_lat, min_lon, max_lon in COARSE_LOCATION_BOUNDS:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return label
    return None


class SearchRequest(BaseModel):
    query: str
    limit: int = 50


class PhotoUpdateRequest(BaseModel):
    description: str | None = None
    tags: list[str] | None = None
    colors: list[str] | None = None


class FaceReindexRequest(BaseModel):
    photo_root: str | None = None


class DeepSeekQueryBridge:
    """把感性自然语言查询改写成适合 SQLite FTS5 的检索关键词。

    该桥接器只处理文本，不碰图片。没有配置 DEEPSEEK_API_KEY 时，服务会自动跳过它。
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        http_post: Any | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
        if http_post is None:
            import requests

            http_post = requests.post
        self.http_post = http_post

    def parse(self, query: str) -> dict[str, list[str]]:
        if not self.api_key:
            return {"keywords": [], "colors": []}

        prompt = (
            "你是本地相册检索系统的 Query 解析器。请只返回 JSON，不要解释。\n"
            "目标：把用户感性的中文描述压缩为 SQLite FTS5 适合检索的短关键词。\n"
            '固定格式：{"keywords":["夏天","海边","太阳"],"colors":["蓝色"]}\n'
            "要求：keywords 优先输出季节、地点、人物关系、动作、物体、宠物、交通工具、天气；"
            "colors 只输出明确颜色；不要输出空泛词如 照片、想看、去年。\n"
            f"用户查询：{query}"
        )
        response = self.http_post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return self._parse_content(content)

    def _parse_content(self, content: str) -> dict[str, list[str]]:
        match = re.search(r"\{.*\}", str(content).strip(), flags=re.DOTALL)
        payload = json.loads(match.group(0) if match else content)
        return {
            "keywords": [str(item).strip() for item in payload.get("keywords", []) if str(item).strip()],
            "colors": [str(item).strip() for item in payload.get("colors", []) if str(item).strip()],
        }


class ArkSearchService:
    """面向 Web 的本地检索服务：只查 SQLite，不做在线视觉推理。"""

    def __init__(
        self,
        *,
        db_path: str | os.PathLike[str] | None = None,
        photo_root: str | os.PathLike[str] | None = None,
        photos_base_url: str | None = None,
        thumbnail_dir: str | os.PathLike[str] | None = None,
        thumbnails_base_url: str | None = None,
        query_bridge: Any | None = None,
        family_profile_path: str | os.PathLike[str] | None = None,
        face_engine: Any | None = None,
        apple_people_bridge: Any | None = None,
        apple_people_cache: Any | None = None,
        reverse_geocoder: Any | None = None,
        delta_job_path: str | os.PathLike[str] | None = None,
        delta_log_path: str | os.PathLike[str] | None = None,
        delta_error_log_path: str | os.PathLike[str] | None = None,
        face_reindex_job_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.database = ArkPhotoIndexDatabase(db_path or os.environ.get("LIMB_ARK_DB", "data/limb_ark.sqlite3"))
        configured_root = photo_root or os.environ.get("LIMB_PHOTO_ROOT") or os.environ.get("ARK_PHOTO_ROOT")
        self.photo_root = Path(configured_root).expanduser().resolve() if configured_root else None
        if self.photo_root and self.photo_root.name == "originals" and self.photo_root.parent.name.endswith(
            ".photoslibrary"
        ):
            self.photo_root = self.photo_root.parent
        self.photos_base_url = (photos_base_url or os.environ.get("LIMB_PHOTOS_BASE_URL") or "http://127.0.0.1:8004/photos").rstrip("/")
        self.thumbnail_dir = Path(thumbnail_dir or os.environ.get("LIMB_THUMBNAIL_DIR") or DEFAULT_THUMBNAIL_DIR).expanduser().resolve()
        self.thumbnails_base_url = (
            thumbnails_base_url or os.environ.get("LIMB_THUMBNAILS_BASE_URL") or "http://127.0.0.1:8004/thumbnails"
        ).rstrip("/")
        self.query_bridge = query_bridge if query_bridge is not None else self._default_query_bridge()
        self.family_profile_path = Path(
            family_profile_path or os.environ.get("LIMB_FAMILY_PROFILE") or Path("data") / "family_profile.json"
        ).expanduser()
        self.family_profile = self._load_family_profile()
        self.face_engine = face_engine
        self.apple_people_bridge = apple_people_bridge if apple_people_bridge is not None else self._default_apple_people_bridge()
        self.apple_people_cache = (
            apple_people_cache if apple_people_cache is not None else ApplePhotosPeopleCache(os.environ.get("LIMB_APPLE_PEOPLE_CACHE", Path("data") / "apple_people_cache.json"))
        )
        self.reverse_geocoder = reverse_geocoder
        self.last_search_diagnostic: dict[str, Any] = {}
        self.delta_job_path = Path(delta_job_path or self.database.db_path.parent / "delta_update_job.json")
        self.delta_log_path = Path(delta_log_path or self.database.db_path.parent / "delta_update_job.log")
        self.delta_error_log_path = Path(
            delta_error_log_path or self.database.db_path.parent / "indexing_errors.log"
        )
        self.face_reindex_job_path = Path(
            face_reindex_job_path or self.database.db_path.parent / "face_reindex_job.json"
        )
        self._face_reindex_lock = threading.Lock()

    def _default_query_bridge(self) -> DeepSeekQueryBridge | None:
        if not os.environ.get("DEEPSEEK_API_KEY"):
            return None
        return DeepSeekQueryBridge()

    def _default_apple_people_bridge(self) -> ApplePhotosPeopleBridge | None:
        if self.photo_root is None:
            return None
        library_root = self.photo_root
        if library_root.name == "originals" and library_root.parent.name.endswith(".photoslibrary"):
            library_root = library_root.parent
        if not library_root.name.endswith(".photoslibrary"):
            return None
        photos_db = library_root / "database" / "Photos.sqlite"
        return ApplePhotosPeopleBridge(library_root) if photos_db.exists() else None

    def jieba_tokens(self, query: str) -> list[str]:
        tokens: list[str] = []
        for chunk in re.split(r"[\s,，。；;、/|]+", query.strip()):
            if not chunk:
                continue
            for token in [chunk, *jieba.cut_for_search(chunk)]:
                token = token.strip()
                if token and token not in tokens:
                    tokens.append(token)
        return tokens

    def search(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        self.last_search_diagnostic = {}
        missing_labels = self._missing_registered_face_labels(query)
        if missing_labels:
            self.last_search_diagnostic = {
                "kind": "face_profile_missing",
                "labels": missing_labels,
                "message": f"[{', '.join(missing_labels)}] 尚未入库。请先到人物入库上传 3-5 张清晰人脸样张。",
            }
            return []

        face_rows = self._search_with_face_profiles(query, limit=limit)
        if face_rows is not None:
            return face_rows

        apple_rows = self._search_with_apple_people(query, limit=limit)
        if apple_rows is not None:
            return apple_rows

        rows: list[dict[str, Any]] = []
        for search_query in self._search_query_candidates(query):
            rows = self.database.search(search_query, limit=limit)
            if rows:
                break
        return [self._format_row(row) for row in rows]

    def list_person_profiles(self) -> list[dict[str, Any]]:
        """合并展示 Apple Photos 已命名人物和 LIMB 手动向量库。"""

        profiles: list[dict[str, Any]] = []
        apple_people = self._apple_people_list_named_people()
        apple_links_by_label: dict[str, list[dict[str, Any]]] = {}
        if apple_people:
            for link in self._apple_people_iter_asset_links():
                label = str(link.get("label", "")).strip()
                if label:
                    apple_links_by_label.setdefault(label, []).append(link)
        for person in apple_people:
            profiles.append(
                {
                    "label": person.get("label", ""),
                    "source": "apple_photos",
                    "source_label": "Apple Photos 已识别",
                    "uuid": person.get("uuid"),
                    "entity_type": person.get("entity_type", "person"),
                    "asset_count": int(person.get("asset_count") or 0),
                    "face_count": int(person.get("face_count") or 0),
                    "avatar_url": self._apple_people_avatar_url(
                        str(person.get("label", "")).strip(),
                        apple_links_by_label=apple_links_by_label,
                    ),
                }
            )

        if self.face_engine is not None:
            try:
                for profile in self.face_engine.list_profiles():
                    profiles.append(
                        {
                            **profile,
                            "source": "limb_manual",
                            "source_label": "LIMB 手动入库",
                            "avatar_url": self._manual_face_avatar_url(str(profile.get("label", "")).strip()),
                        }
                    )
            except Exception as exc:
                print(f"[LIMB-Ark] LIMB 人物向量库读取失败: {exc}", flush=True)
        return profiles

    def reindex_faces(
        self,
        *,
        photo_root: str | os.PathLike[str] | None = None,
        face_engine: Any | None = None,
    ) -> dict[str, Any]:
        engine = face_engine or self.face_engine
        if engine is None:
            raise FaceVectorError("LIMB 人物向量库未启用。")

        target_root = photo_root or os.environ.get("LIMB_PHOTO_ROOT") or os.environ.get("ARK_PHOTO_ROOT")
        if photo_root is None:
            apple_assets = self._apple_photo_assets_for_delta()
            source_paths: list[Path] = []
            if apple_assets:
                for asset in apple_assets:
                    source_path = asset.get("source_path") or asset.get("original_path")
                    if source_path:
                        source_paths.append(Path(source_path).expanduser().resolve())
                if source_paths:
                    payload = engine.scan_photo_paths(source_paths)
                    return {**payload, "source": "apple_photos_assets"}

        if not target_root:
            raise FaceVectorError("缺少 photo_root 或 LIMB_PHOTO_ROOT 环境变量。")
        payload = engine.scan_photo_directory(target_root)
        return {**payload, "source": "filesystem"}

    def face_reindex_job_status(self) -> dict[str, Any]:
        if not self.face_reindex_job_path.exists():
            return {"status": "idle"}
        try:
            payload = json.loads(self.face_reindex_job_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"status": "unknown", "message": f"人脸补扫状态读取失败: {exc}"}
        status = str(payload.get("status") or "")
        pid = payload.get("pid")
        if status in {"started", "running"} and pid is not None:
            try:
                if int(pid) != os.getpid():
                    return {
                        **payload,
                        "status": "interrupted",
                        "message": "上一次人脸补扫进程已重启或退出，请重新点击补扫。",
                    }
            except (TypeError, ValueError):
                pass
        return payload

    def _write_face_reindex_job(self, payload: dict[str, Any]) -> None:
        self.face_reindex_job_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.face_reindex_job_path.with_suffix(f"{self.face_reindex_job_path.suffix}.tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.face_reindex_job_path)

    def _face_reindex_source(
        self,
        *,
        photo_root: str | os.PathLike[str] | None,
    ) -> dict[str, Any]:
        target_root = photo_root or os.environ.get("LIMB_PHOTO_ROOT") or os.environ.get("ARK_PHOTO_ROOT")
        if photo_root is None:
            apple_assets = self._apple_photo_assets_for_delta()
            source_paths: list[Path] = []
            if apple_assets:
                for asset in apple_assets:
                    source_path = asset.get("source_path") or asset.get("original_path")
                    if source_path:
                        source_paths.append(Path(source_path).expanduser().resolve())
                if source_paths:
                    return {
                        "source": "apple_photos_assets",
                        "paths": source_paths,
                        "root": None,
                    }
        if not target_root:
            raise FaceVectorError("缺少 photo_root 或 LIMB_PHOTO_ROOT 环境变量。")
        return {
            "source": "filesystem",
            "paths": None,
            "root": str(Path(target_root).expanduser().resolve()),
        }

    def start_face_reindex(
        self,
        *,
        photo_root: str | os.PathLike[str] | None = None,
        face_engine: Any | None = None,
        monitor_async: bool = True,
    ) -> dict[str, Any]:
        engine = face_engine or self.face_engine
        if engine is None:
            raise FaceVectorError("LIMB 人物向量库未启用。")

        with self._face_reindex_lock:
            existing = self.face_reindex_job_status()
            if existing.get("status") in {"started", "running"}:
                return existing

            source_payload = self._face_reindex_source(photo_root=photo_root)
            paths = source_payload["paths"]
            total = len(paths) if paths is not None else 0
            job = {
                "status": "started",
                "pid": os.getpid(),
                "source": source_payload["source"],
                "root": source_payload["root"],
                "total": total,
                "processed": 0,
                "summary": {"indexed": 0, "skipped": 0, "failed": 0},
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "job_path": str(self.face_reindex_job_path),
            }
            self._write_face_reindex_job(job)

        def update_progress(snapshot: dict[str, Any], *, force: bool = False) -> None:
            processed = int(snapshot.get("processed") or 0)
            if not force and processed % 10 != 0 and processed < int(snapshot.get("total") or 0):
                return
            progress_job = {
                **job,
                "status": "running",
                "total": int(snapshot.get("total") or job.get("total") or 0),
                "processed": processed,
                "summary": {
                    "indexed": int(snapshot.get("indexed") or 0),
                    "skipped": int(snapshot.get("skipped") or 0),
                    "failed": int(snapshot.get("failed") or 0),
                },
                "current_path": snapshot.get("path"),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            self._write_face_reindex_job(progress_job)

        def worker() -> None:
            try:
                running_job = {**job, "status": "running", "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                self._write_face_reindex_job(running_job)
                if paths is not None:
                    summary = engine.scan_photo_paths(paths, progress_callback=update_progress, save_every=100)
                else:
                    summary = engine.scan_photo_directory(
                        source_payload["root"],
                        progress_callback=update_progress,
                        save_every=100,
                    )
                current_job = self.face_reindex_job_status()
                final_total = int(current_job.get("total") or total)
                final_processed = int(current_job.get("processed") or final_total)
                finished_job = {
                    **job,
                    "status": "completed",
                    "total": final_total,
                    "processed": final_processed,
                    "summary": {
                        "indexed": int(summary.get("indexed") or 0),
                        "skipped": int(summary.get("skipped") or 0),
                        "failed": int(summary.get("failed") or 0),
                    },
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "message": "人脸索引补扫完成",
                }
                self._write_face_reindex_job(finished_job)
            except Exception as exc:
                failed_job = {
                    **job,
                    "status": "failed",
                    "message": str(exc),
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
                self._write_face_reindex_job(failed_job)

        if monitor_async:
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            return job
        worker()
        return self.face_reindex_job_status()

    def _search_with_face_profiles(self, query: str, *, limit: int) -> list[dict[str, Any]] | None:
        if self.face_engine is None:
            return None
        labels = self.face_engine.known_labels_in_query(query)
        if not labels:
            return None

        semantic_query = self._strip_face_labels(query, labels)
        semantic_rows: list[dict[str, Any]] = []
        candidate_paths: list[str] | None = None
        semantic_miss = False
        if semantic_query:
            for search_query in self._search_query_candidates(semantic_query):
                semantic_rows = self.database.search(search_query, limit=max(limit, 200))
                if semantic_rows:
                    break
            if semantic_rows:
                candidate_paths = [row["path"] for row in semantic_rows]
            else:
                semantic_miss = True

        merged_matches: dict[str, dict[str, Any]] = {}
        for label in labels:
            for match in self.face_engine.match_label(label, candidate_paths=candidate_paths, limit=max(limit, 200)):
                match_path = str(Path(match["path"]).expanduser().resolve())
                current = merged_matches.setdefault(match_path, {"path": match_path, "face_score": 0.0, "matched_labels": []})
                current["face_score"] = max(float(current["face_score"]), float(match.get("face_score", 0.0)))
                if label not in current["matched_labels"]:
                    current["matched_labels"].append(label)

        if not merged_matches:
            if semantic_rows:
                fallback_matches = self._face_matches_for_labels(labels, candidate_paths=None, limit=max(limit, 200))
                if fallback_matches:
                    self.last_search_diagnostic = {
                        "kind": "semantic_face_intersection_empty",
                        "labels": labels,
                        "semantic_query": semantic_query,
                        "semantic_candidate_count": len(semantic_rows),
                        "message": (
                            f"已找到 {len(semantic_rows)} 张符合 [{semantic_query}] 的照片，"
                            f"但没有照片同时匹配 [{', '.join(labels)}] 的人脸。"
                            "已降级返回人物照片，场景条件未命中。"
                        ),
                    }
                    return self._format_face_match_rows(fallback_matches, semantic_miss=True, limit=limit)
                self.last_search_diagnostic = {
                    "kind": "face_filter_empty",
                    "labels": labels,
                    "semantic_query": semantic_query,
                    "semantic_candidate_count": len(semantic_rows),
                    "message": (
                        f"已找到 {len(semantic_rows)} 张符合 [{semantic_query}] 的照片，"
                        f"但没有照片同时匹配 [{', '.join(labels)}] 的人脸。"
                    ),
                }
            return []

        if semantic_miss and semantic_query and not self.last_search_diagnostic:
            self.last_search_diagnostic = {
                "kind": "semantic_face_terms_not_found",
                "labels": labels,
                "semantic_query": semantic_query,
                "semantic_candidate_count": 0,
                "message": (
                    f"没有找到符合 [{semantic_query}] 的照片。"
                    f"已降级返回 [{', '.join(labels)}] 的人物照片，场景条件未命中。"
                ),
            }

        return self._format_face_match_rows(merged_matches, semantic_miss=semantic_miss, limit=limit)

    def _search_with_apple_people(self, query: str, *, limit: int) -> list[dict[str, Any]] | None:
        labels = self._apple_people_labels_in_query(query)
        if not labels:
            return None

        semantic_query = self._strip_face_labels(query, labels)
        semantic_rows: list[dict[str, Any]] = []
        candidate_paths: set[str] | None = None
        semantic_miss = False
        if semantic_query:
            for search_query in self._search_query_candidates(semantic_query):
                semantic_rows = self.database.search(search_query, limit=max(limit, 200))
                if semantic_rows:
                    break
            if semantic_rows:
                candidate_paths = {str(Path(row["path"]).expanduser().resolve()) for row in semantic_rows}
            else:
                semantic_miss = True

        matches: dict[str, dict[str, Any]] = {}
        links = self._apple_people_iter_asset_links()

        for link in links:
            label = str(link.get("label") or "").strip()
            if label not in labels:
                continue
            path = str(Path(link.get("original_path") or "").expanduser().resolve())
            if candidate_paths is not None and path not in candidate_paths:
                continue
            current = matches.setdefault(path, {"path": path, "matched_labels": [], "quality": 0.0})
            current["quality"] = max(float(current["quality"]), float(link.get("quality") or 0.0))
            if label not in current["matched_labels"]:
                current["matched_labels"].append(label)

        if not matches and semantic_rows:
            for link in links:
                label = str(link.get("label") or "").strip()
                if label not in labels:
                    continue
                path = str(Path(link.get("original_path") or "").expanduser().resolve())
                current = matches.setdefault(path, {"path": path, "matched_labels": [], "quality": 0.0})
                current["quality"] = max(float(current["quality"]), float(link.get("quality") or 0.0))
                if label not in current["matched_labels"]:
                    current["matched_labels"].append(label)
            if matches:
                self.last_search_diagnostic = {
                    "kind": "semantic_apple_people_intersection_empty",
                    "labels": labels,
                    "semantic_query": semantic_query,
                    "semantic_candidate_count": len(semantic_rows),
                    "message": (
                        f"已找到 {len(semantic_rows)} 张符合 [{semantic_query}] 的照片，"
                        f"但没有照片同时匹配 Apple Photos 人物 [{', '.join(labels)}]。"
                        "已降级返回人物照片，场景条件未命中。"
                    ),
                }
                semantic_miss = True

        rows = self.database.get_photos_by_paths(matches.keys())
        if semantic_miss and semantic_query and not self.last_search_diagnostic:
            self.last_search_diagnostic = {
                "kind": "semantic_apple_people_terms_not_found",
                "labels": labels,
                "semantic_query": semantic_query,
                "semantic_candidate_count": 0,
                "message": (
                    f"没有找到符合 [{semantic_query}] 的照片。"
                    f"已降级返回 Apple Photos 人物 [{', '.join(labels)}]，场景条件未命中。"
                ),
            }
        formatted = []
        for row in rows:
            match = matches.get(row["path"])
            if match is None and row.get("original_path"):
                match = matches.get(str(Path(row["original_path"]).expanduser().resolve()))
            if match is None:
                continue
            formatted.append(
                self._format_row(
                    row,
                    face_score=match["quality"],
                    matched_labels=match["matched_labels"],
                    semantic_miss=semantic_miss,
                    identity_source="apple_photos",
                )
            )
        formatted.sort(key=lambda item: item.get("face_score", 0.0), reverse=True)
        return formatted[:limit]

    def _face_matches_for_labels(
        self,
        labels: list[str],
        *,
        candidate_paths: list[str] | None,
        limit: int,
    ) -> dict[str, dict[str, Any]]:
        merged_matches: dict[str, dict[str, Any]] = {}
        for label in labels:
            for match in self.face_engine.match_label(label, candidate_paths=candidate_paths, limit=max(limit, 200)):
                match_path = str(Path(match["path"]).expanduser().resolve())
                current = merged_matches.setdefault(match_path, {"path": match_path, "face_score": 0.0, "matched_labels": []})
                current["face_score"] = max(float(current["face_score"]), float(match.get("face_score", 0.0)))
                if label not in current["matched_labels"]:
                    current["matched_labels"].append(label)
        return merged_matches

    def _format_face_match_rows(
        self,
        merged_matches: dict[str, dict[str, Any]],
        *,
        semantic_miss: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.database.get_photos_by_paths(merged_matches.keys())
        formatted = []
        for row in rows:
            match = merged_matches[row["path"]]
            formatted.append(
                self._format_row(
                    row,
                    face_score=match["face_score"],
                    matched_labels=match["matched_labels"],
                    semantic_miss=semantic_miss,
                )
            )
        formatted.sort(key=lambda item: item.get("face_score", 0.0), reverse=True)
        return formatted[:limit]

    def _missing_registered_face_labels(self, query: str) -> list[str]:
        if self.face_engine is None and self.apple_people_bridge is None:
            return []
        try:
            registered = {str(profile.get("label", "")).strip() for profile in self.face_engine.list_profiles()}
        except Exception:
            registered = set()
        registered.update(self._apple_people_labels())
        text = str(query)
        missing = []
        for label in self.family_profile:
            if label and label in text and label not in registered:
                missing.append(label)
        return missing

    def _apple_people_labels(self) -> set[str]:
        return {
            str(person.get("label", "")).strip()
            for person in self._apple_people_list_named_people()
            if str(person.get("label", "")).strip()
        }

    def _apple_people_labels_in_query(self, query: str) -> list[str]:
        text = str(query)
        return [label for label in self._apple_people_labels() if label and label in text]

    def _apple_people_list_named_people(self) -> list[dict[str, Any]]:
        if self.apple_people_bridge is not None:
            try:
                people = self.apple_people_bridge.list_named_people()
                if people:
                    return people
            except Exception as exc:
                print(f"[LIMB-Ark] Apple Photos 人物读取失败: {exc}", flush=True)
        if self.apple_people_cache is None:
            return []
        try:
            return list(self.apple_people_cache.list_named_people())
        except Exception as exc:
            print(f"[LIMB-Ark] Apple Photos 人物缓存读取失败: {exc}", flush=True)
            return []

    def _apple_people_iter_asset_links(self) -> list[dict[str, Any]]:
        if self.apple_people_bridge is not None:
            try:
                links = self.apple_people_bridge.iter_person_asset_links()
                if links:
                    return list(links)
            except Exception as exc:
                print(f"[LIMB-Ark] Apple Photos 人物映射读取失败: {exc}", flush=True)
        if self.apple_people_cache is None:
            return []
        try:
            return list(self.apple_people_cache.iter_person_asset_links())
        except Exception as exc:
            print(f"[LIMB-Ark] Apple Photos 人物映射缓存读取失败: {exc}", flush=True)
            return []

    def _apple_people_avatar_url(
        self,
        label: str,
        *,
        apple_links_by_label: dict[str, list[dict[str, Any]]] | None = None,
    ) -> str | None:
        if not label:
            return None
        source_links = (
            apple_links_by_label.get(label, [])
            if apple_links_by_label is not None
            else self._apple_people_iter_asset_links()
        )
        links = [link for link in source_links if str(link.get("label", "")).strip() == label and link.get("original_path")]
        links.sort(key=lambda item: float(item.get("quality") or 0.0), reverse=True)
        return self._avatar_url_from_paths([link["original_path"] for link in links], fallback_to_photo=True)

    def _manual_face_avatar_url(self, label: str) -> str | None:
        if not label or self.face_engine is None:
            return None
        try:
            for profile in self.face_engine.list_profiles():
                if str(profile.get("label", "")).strip() == label:
                    avatar_path = Path(str(profile.get("avatar_path") or "")).expanduser()
                    if avatar_path.is_file():
                        return f"http://127.0.0.1:8004/face-avatars/{quote(avatar_path.name)}"
        except Exception as exc:
            print(f"[LIMB-Ark] LIMB 人物样张头像读取失败: {exc}", flush=True)
        try:
            matches = self.face_engine.match_label(label, limit=1)
        except Exception as exc:
            print(f"[LIMB-Ark] LIMB 人物头像读取失败: {exc}", flush=True)
            return None
        return self._avatar_url_from_paths([match["path"] for match in matches if match.get("path")])

    def resolve_face_avatar_static_path(self, file_name: str) -> Path | None:
        if self.face_engine is None:
            return None
        avatar_dir = getattr(self.face_engine, "avatar_dir", None)
        if avatar_dir is None:
            return None
        root = Path(avatar_dir).expanduser().resolve()
        candidate = (root / file_name).expanduser().resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _avatar_url_from_paths(self, paths: list[str], *, fallback_to_photo: bool = False) -> str | None:
        rows = self.database.get_photos_by_paths(paths)
        if rows:
            return self.thumbnail_url(rows[0]["md5"])
        if fallback_to_photo and paths:
            return self.photo_path_to_url(paths[0])
        return None

    def _strip_face_labels(self, query: str, labels: list[str]) -> str:
        text = str(query)
        for label in labels:
            text = text.replace(label, " ")
        for word in ("照片", "图片", "查找", "搜索", "包含", "的", "和", "与", "一起", "同时", "是"):
            text = text.replace(word, " ")
        return " ".join(self.jieba_tokens(text))

    def _format_row(
        self,
        row: dict[str, Any],
        *,
        face_score: float | None = None,
        matched_labels: list[str] | None = None,
        semantic_miss: bool = False,
        identity_source: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "md5": row["md5"],
            "path": row["path"],
            "url": self.photo_path_to_url(row["path"]),
            "thumbnail_url": self.thumbnail_url(row["md5"]),
            "preview_url": self.preview_url(row),
            "description": row["description"],
            "tags": row["tags"],
            "colors": row["colors"],
            "taken_at": row.get("taken_at"),
            "location": self._format_location(row),
            "metadata_source": row.get("metadata_source"),
        }
        if face_score is not None:
            payload["face_score"] = face_score
        if matched_labels is not None:
            payload["matched_labels"] = matched_labels
        if semantic_miss:
            payload["semantic_miss"] = True
        if identity_source:
            payload["identity_source"] = identity_source
        for key in ("asset_id", "local_identifier", "original_path", "thumbnail_path", "source"):
            if row.get(key) is not None:
                payload[key] = row.get(key)
        if row.get("asset_id"):
            payload["url"] = f"http://127.0.0.1:8004/api/assets/{quote(str(row['asset_id']))}/image"
        return payload

    def _format_location(self, row: dict[str, Any]) -> dict[str, Any] | None:
        latitude = row.get("latitude")
        longitude = row.get("longitude")
        text = row.get("location_text")
        display_name = row.get("location_display_name")
        if latitude is None and longitude is None and not text:
            return None
        return {
            "latitude": latitude,
            "longitude": longitude,
            "text": text,
            "display_name": display_name or readable_location_name(latitude, longitude, text, self.reverse_geocoder),
        }

    def original_path_for_local_identifier(self, local_identifier: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT original_path FROM photos WHERE local_identifier = ? LIMIT 1",
                (local_identifier,),
            ).fetchone()
        return row["original_path"] if row and row["original_path"] else None

    def _search_query_candidates(self, query: str) -> list[str]:
        candidates: list[str] = []
        bridged = self._bridge_query(query)
        for candidate in [bridged, query, *self._family_profile_query_candidates(query)]:
            candidate = str(candidate).strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _load_family_profile(self) -> dict[str, str]:
        try:
            if self.family_profile_path.exists():
                payload = json.loads(self.family_profile_path.read_text(encoding="utf-8"))
                return {str(key): str(value) for key, value in payload.items()}
        except Exception as exc:
            print(f"[LIMB-Ark] family_profile 读取失败: {exc}", flush=True)
        return {}

    def _family_profile_query_candidates(self, query: str) -> list[str]:
        matched_profiles = [profile for name, profile in self.family_profile.items() if name and name in query]
        if not matched_profiles:
            return []

        object_terms = self._visual_object_terms(query)
        identity_terms = self._identity_terms(matched_profiles)
        candidates: list[str] = []
        for identity in identity_terms:
            for term in object_terms:
                phrase = f"{identity} {term}".strip()
                if phrase and phrase not in candidates:
                    candidates.append(phrase)
        for term in object_terms:
            if term not in candidates:
                candidates.append(term)
        return candidates

    def _visual_object_terms(self, query: str) -> list[str]:
        family_names = set(self.family_profile)
        stop_words = {
            "和",
            "与",
            "及",
            "一起",
            "同时",
            "的",
            "照片",
            "图片",
            "查找",
            "搜索",
            "包含",
            "有",
            "在",
        }
        synonym_map = {
            "猫咪": ["猫咪", "猫"],
            "猫": ["猫", "猫咪"],
            "狗狗": ["狗狗", "狗", "小狗"],
            "狗": ["狗", "小狗", "狗狗"],
            "汽车": ["汽车", "车", "车辆"],
            "车": ["车", "汽车", "车辆"],
        }
        terms: list[str] = []
        for token in self.jieba_tokens(query):
            if token in family_names or token in stop_words or len(token) <= 1:
                continue
            for value in synonym_map.get(token, [token]):
                if value not in terms and value not in stop_words:
                    terms.append(value)
        return terms

    def _identity_terms(self, profiles: list[str]) -> list[str]:
        terms: list[str] = []
        for profile in profiles:
            if any(word in profile for word in ("女性", "夫人", "妈妈", "母亲", "女孩")):
                for token in ("女孩", "女子", "女士", "女性", "人物"):
                    if token not in terms:
                        terms.append(token)
            if any(word in profile for word in ("男性", "爸爸", "父亲", "男士")):
                for token in ("男士", "男子", "男性", "人物"):
                    if token not in terms:
                        terms.append(token)
            for token in self.jieba_tokens(profile):
                if token and token not in terms:
                    terms.append(token)
        return terms or ["人物"]

    def index_status(self) -> dict[str, Any]:
        """返回当前 Ark 文本索引的运行状态，帮助 UI 区分空库和无匹配。"""

        photo_count = self.database.count_photos()
        thumbnail_count = 0
        if self.thumbnail_dir.exists():
            thumbnail_count = sum(1 for path in self.thumbnail_dir.glob("*.jpg") if path.is_file())
        apple_assets = self._apple_photo_assets_for_status()
        return {
            "photos": photo_count,
            "is_empty": photo_count == 0,
            "db_path": str(self.database.db_path),
            "photo_root": str(self.photo_root) if self.photo_root else None,
            "thumbnail_dir": str(self.thumbnail_dir),
            "thumbnails": thumbnail_count,
            "source_quality": self._source_quality_from_apple_assets(apple_assets),
        }

    def _apple_photo_assets_for_status(self) -> list[dict[str, Any]]:
        if self.apple_people_cache is not None:
            try:
                cached_assets = self._filter_cached_apple_assets(
                    self.apple_people_cache.iter_image_asset_resources()
                )
            except Exception as exc:
                print(f"[LIMB-Ark] Apple Photos 资产缓存读取失败: {exc}", flush=True)
                cached_assets = []
            if cached_assets:
                return cached_assets
        return self._apple_photo_assets_for_delta()

    def _source_quality_from_apple_assets(
        self,
        apple_assets: list[dict[str, Any]],
        *,
        source_file_changed_count: int = 0,
    ) -> dict[str, int]:
        original_count = 0
        derivative_count = 0
        for asset in apple_assets:
            source_kind = str(asset.get("source_kind") or "").strip().lower()
            if not source_kind:
                source_path = str(asset.get("source_path") or "")
                original_path = str(asset.get("original_path") or "")
                source_kind = "original" if source_path and source_path == original_path else "derivative"
            if source_kind == "original":
                original_count += 1
            elif source_kind == "derivative":
                derivative_count += 1
        return {
            "original_count": original_count,
            "derivative_count": derivative_count,
            "source_file_changed_count": source_file_changed_count,
        }

    def _index_scan_root(self) -> Path | None:
        if self.photo_root is None:
            return None
        if self.photo_root.name.endswith(".photoslibrary"):
            return self.photo_root / "originals"
        return self.photo_root

    def _iter_local_photo_files(self) -> list[Path]:
        scan_root = self._index_scan_root()
        if scan_root is None or not scan_root.exists() or not scan_root.is_dir():
            return []
        files: list[Path] = []
        for root_dir, _, file_names in os.walk(scan_root):
            for file_name in file_names:
                if file_name.lower().endswith(VALID_EXTENSIONS):
                    files.append((Path(root_dir) / file_name).expanduser().resolve())
        return files

    def _apple_photo_assets_for_delta(self) -> list[dict[str, Any]]:
        bridges: list[Any] = []
        if self.apple_people_bridge is not None:
            bridges.append(self.apple_people_bridge)

        library_root = self.photo_root
        if library_root is not None and library_root.name == "originals" and library_root.parent.name.endswith(
            ".photoslibrary"
        ):
            library_root = library_root.parent
        if library_root is not None and library_root.name.endswith(".photoslibrary"):
            photos_db = library_root / "database" / "Photos.sqlite"
            if photos_db.exists() and all(
                getattr(bridge, "photo_library_path", None) != library_root for bridge in bridges
            ):
                bridges.append(ApplePhotosPeopleBridge(library_root))

        for bridge in bridges:
            try:
                assets = list(bridge.iter_image_asset_resources())
            except Exception as exc:
                print(f"[LIMB-Ark] Apple Photos 资产差量读取失败: {exc}", flush=True)
                continue
            if assets:
                return assets
        if self.apple_people_cache is not None:
            try:
                cached_assets = self._filter_cached_apple_assets(
                    self.apple_people_cache.iter_image_asset_resources()
                )
            except Exception as exc:
                print(f"[LIMB-Ark] Apple Photos 资产缓存读取失败: {exc}", flush=True)
                cached_assets = []
            if cached_assets:
                return cached_assets
        return []

    def _filter_cached_apple_assets(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.photo_root is None:
            return assets
        library_root = self.photo_root
        if library_root.name == "originals" and library_root.parent.name.endswith(".photoslibrary"):
            library_root = library_root.parent
        library_root = library_root.expanduser().resolve()
        filtered: list[dict[str, Any]] = []
        for asset in assets:
            paths = [asset.get("source_path"), asset.get("original_path")]
            for value in paths:
                if not value:
                    continue
                try:
                    Path(value).expanduser().resolve().relative_to(library_root)
                except (OSError, ValueError):
                    continue
                filtered.append(asset)
                break
        return filtered

    def index_delta(self) -> dict[str, Any]:
        """只做本地相册与 SQLite 索引对账，不触发 Ark/DeepSeek。

        差量检测以路径和 modify_time 为快速依据，避免登录页面时计算全量 MD5。
        真正的 MD5 计算仍留给用户主动点击后的增量索引管线。
        """

        indexed_rows = self.database.photo_fingerprints()
        indexed_by_key: dict[str, dict[str, Any]] = {}
        for row in indexed_rows:
            for key in (
                row.get("path"),
                row.get("original_path"),
                row.get("asset_id"),
                row.get("local_identifier"),
            ):
                if key:
                    key_text = str(key)
                    indexed_by_key[key_text] = row
                    if "/" in key_text or key_text.startswith("~"):
                        indexed_by_key[str(Path(key_text).expanduser().resolve())] = row

        apple_assets = self._apple_photo_assets_for_delta()
        if apple_assets:
            return self._index_delta_from_apple_assets(indexed_rows, indexed_by_key, apple_assets)

        return self._index_delta_from_local_files(indexed_rows, indexed_by_key)

    def _index_delta_from_local_files(
        self,
        indexed_rows: list[dict[str, Any]],
        indexed_by_key: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        local_files = self._iter_local_photo_files()
        local_paths = {str(path) for path in local_files}
        missing_count = 0
        changed_count = 0

        for path in local_files:
            key = str(path)
            row = indexed_by_key.get(key)
            if row is None:
                missing_count += 1
                continue
            try:
                modify_time = path.stat().st_mtime
            except OSError:
                missing_count += 1
                continue
            if abs(float(row.get("modify_time") or 0.0) - float(modify_time)) > 0.000001:
                changed_count += 1

        stale_count = 0
        for row in indexed_rows:
            candidates = [
                str(Path(value).expanduser().resolve())
                for value in (row.get("path"), row.get("original_path"))
                if value
            ]
            if not candidates:
                stale_count += 1
                continue
            if not any(candidate in local_paths or Path(candidate).exists() for candidate in candidates):
                stale_count += 1

        has_delta = any((missing_count, changed_count, stale_count))
        return {
            "photo_total": len(local_files),
            "indexed_total": len(indexed_rows),
            "missing_count": missing_count,
            "changed_count": changed_count,
            "stale_count": stale_count,
            "has_delta": has_delta,
            "scan_root": str(self._index_scan_root()) if self._index_scan_root() else None,
            "db_path": str(self.database.db_path),
            "scan_cost": "local_only_no_model_token",
        }

    def _index_delta_from_apple_assets(
        self,
        indexed_rows: list[dict[str, Any]],
        indexed_by_key: dict[str, dict[str, Any]],
        apple_assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        missing_count = 0
        changed_count = 0
        source_file_changed_count = 0
        current_asset_ids: set[str] = set()
        current_local_identifiers: set[str] = set()
        current_paths: set[str] = set()

        for asset in apple_assets:
            asset_keys = [
                ("local_identifier", asset.get("local_identifier")),
                ("asset_id", asset.get("asset_id")),
                ("source_path", asset.get("source_path")),
                ("original_path", asset.get("original_path")),
            ]
            current_asset_ids.update(str(key) for key in (asset.get("asset_id"),) if key)
            current_local_identifiers.update(str(key) for key in (asset.get("local_identifier"),) if key)
            for path_key in (asset.get("source_path"), asset.get("original_path")):
                if path_key:
                    current_paths.add(str(Path(path_key).expanduser().resolve()))

            row = None
            matched_key_name = ""
            for key_name, key in asset_keys:
                if not key:
                    continue
                key_text = str(key)
                row = indexed_by_key.get(key_text)
                if row is None and ("/" in key_text or key_text.startswith("~")):
                    row = indexed_by_key.get(str(Path(key_text).expanduser().resolve()))
                if row is not None:
                    matched_key_name = key_name
                    break
            if row is None:
                missing_count += 1
                continue
            source_path = asset.get("source_path")
            if source_path:
                try:
                    resolved_source_path = Path(source_path).expanduser().resolve()
                    modify_time = resolved_source_path.stat().st_mtime
                except OSError:
                    continue
                source_changed = abs(float(row.get("modify_time") or 0.0) - float(modify_time)) > 0.000001
                row_path = row.get("path")
                if row_path:
                    source_changed = source_changed or str(Path(row_path).expanduser().resolve()) != str(
                        resolved_source_path
                    )
                if matched_key_name in {"asset_id", "local_identifier"}:
                    if source_changed:
                        source_file_changed_count += 1
                elif source_changed:
                    changed_count += 1

        stale_count = 0
        for row in indexed_rows:
            row_asset_id = str(row.get("asset_id") or "")
            row_local_identifier = str(row.get("local_identifier") or "")
            row_paths = {
                str(Path(value).expanduser().resolve())
                for value in (row.get("path"), row.get("original_path"))
                if value
            }
            if row_asset_id and row_asset_id in current_asset_ids:
                continue
            if row_local_identifier and row_local_identifier in current_local_identifiers:
                continue
            if row_paths & current_paths:
                continue
            stale_count += 1

        has_delta = any((missing_count, changed_count, stale_count))
        return {
            "photo_total": len(apple_assets),
            "indexed_total": len(indexed_rows),
            "missing_count": missing_count,
            "changed_count": changed_count,
            "stale_count": stale_count,
            "has_delta": has_delta,
            "scan_root": str(self.photo_root) if self.photo_root else None,
            "db_path": str(self.database.db_path),
            "scan_cost": "local_only_no_model_token",
            "source": "apple_photos_assets",
            "source_quality": self._source_quality_from_apple_assets(
                apple_assets,
                source_file_changed_count=source_file_changed_count,
            ),
        }

    def delta_update_job_status(self) -> dict[str, Any]:
        if not self.delta_job_path.exists():
            return {"status": "idle"}
        try:
            return json.loads(self.delta_job_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"status": "unknown", "message": f"差量更新状态读取失败: {exc}"}

    def _write_delta_update_job(self, payload: dict[str, Any]) -> None:
        self.delta_job_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.delta_job_path.with_suffix(f"{self.delta_job_path.suffix}.tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.delta_job_path)

    def _parse_delta_update_log_summary(self, text: str) -> dict[str, int]:
        patterns = {
            "indexed": r"本次新增成功打标图片数：(\d+)",
            "skipped": r"增量跳过图片数：(\d+)",
            "failed": r"失败图片数：(\d+)",
        }
        summary: dict[str, int] = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                summary[key] = int(match.group(1))
        return summary

    def _permission_error_lines(self, text: str) -> list[str]:
        return [
            line
            for line in text.splitlines()
            if "PermissionError" in line or "Operation not permitted" in line or "authorization denied" in line
        ]

    def _parse_job_time(self, value: Any) -> float:
        try:
            return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z").timestamp()
        except (TypeError, ValueError):
            return 0.0

    def _filter_log_lines_after(self, text: str, started_at: float) -> str:
        if started_at <= 0:
            return text
        lines: list[str] = []
        for line in text.splitlines():
            match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\t", line)
            if match:
                try:
                    line_timestamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
                except ValueError:
                    line_timestamp = started_at
                if line_timestamp + 1 < started_at:
                    continue
            lines.append(line)
        return "\n".join(lines)

    def _pipeline_delta_count(self, delta: dict[str, Any]) -> int:
        return int(delta.get("missing_count") or 0) + int(delta.get("changed_count") or 0)

    def _complete_stale_only_delta_update(self, delta: dict[str, Any]) -> dict[str, Any]:
        started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        prune_payload = self.prune_stale_index_entries()
        delta_after = self.index_delta()
        stale_removed = int(prune_payload.get("deleted_count") or 0)
        remaining_count = (
            int(delta_after.get("missing_count") or 0)
            + int(delta_after.get("changed_count") or 0)
            + int(delta_after.get("stale_count") or 0)
        )
        status = "completed" if not delta_after.get("has_delta") else "needs_attention"
        message = (
            "相册同步完成"
            if status == "completed"
            else f"已清理 {stale_removed} 条旧索引，仍有 {remaining_count} 张待更新。"
        )
        job = {
            "status": status,
            "reason": "stale_pruned",
            "pid": None,
            "delta": delta,
            "started_at": started_at,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "summary": {"stale_removed": stale_removed},
            "delta_after": delta_after,
            "message": message,
            "log_path": str(self.delta_log_path),
            "error_log_path": str(self.delta_error_log_path),
            "log_tail": "",
            "error_log_tail": "",
        }
        self._write_delta_update_job(job)
        return job

    def _finalize_delta_update_job(self, job: dict[str, Any], process: Any, log_file: Any | None = None) -> None:
        try:
            exit_code = int(process.wait())
        finally:
            if log_file is not None:
                log_file.close()

        log_text = ""
        if self.delta_log_path.exists():
            log_text = self.delta_log_path.read_text(encoding="utf-8", errors="replace")
        error_log_text = ""
        if self.delta_error_log_path.exists():
            error_log_text = self.delta_error_log_path.read_text(encoding="utf-8", errors="replace")
        current_error_log_text = self._filter_log_lines_after(error_log_text, self._parse_job_time(job.get("started_at")))
        permission_error_count = len(self._permission_error_lines(log_text)) + len(
            self._permission_error_lines(current_error_log_text)
        )
        summary = self._parse_delta_update_log_summary(log_text)
        if exit_code == 0:
            try:
                prune_payload = self.prune_stale_index_entries()
                summary["stale_removed"] = int(prune_payload.get("deleted_count") or 0)
            except Exception as exc:
                summary["stale_removed"] = 0
                summary["stale_prune_error"] = str(exc)
        delta_after = self.index_delta()
        status = "completed" if exit_code == 0 else "failed"
        remaining_count = (
            int(delta_after.get("missing_count") or 0)
            + int(delta_after.get("changed_count") or 0)
            + int(delta_after.get("stale_count") or 0)
        )
        if exit_code == 0 and permission_error_count and delta_after.get("has_delta"):
            status = "permission_blocked"
            message = f"后台无权限读取相册，仍有 {remaining_count} 张待更新。请从已授权终端执行索引。"
        elif exit_code == 0 and delta_after.get("has_delta"):
            status = "needs_attention"
            message = f"更新进程已结束，但仍有 {remaining_count} 张待更新。请查看日志。"
        elif exit_code == 0:
            message = "相册同步完成"
        else:
            message = f"差量更新进程异常退出: {exit_code}"

        finished_job = {
            **job,
            "status": status,
            "exit_code": exit_code,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "permission_error_count": permission_error_count,
            "summary": summary,
            "delta_after": delta_after,
            "message": message,
            "log_path": str(self.delta_log_path),
            "error_log_path": str(self.delta_error_log_path),
            "log_tail": log_text[-4000:],
            "error_log_tail": current_error_log_text[-4000:],
        }
        self._write_delta_update_job(finished_job)

    def start_delta_update(self, *, popen: Any | None = None, monitor_async: bool = True) -> dict[str, Any]:
        """后台启动现有增量索引管线。

        该方法只在检测到差量时启动；真正的模型调用发生在独立管线进程中，
        因此登录页面和状态检测仍然不消耗 token。
        """

        delta = self.index_delta()
        if not delta["has_delta"]:
            return {"status": "skipped", "reason": "no_delta", "delta": delta}
        if self._pipeline_delta_count(delta) == 0 and int(delta.get("stale_count") or 0) > 0:
            return self._complete_stale_only_delta_update(delta)
        scan_root = self._index_scan_root()
        if scan_root is None:
            raise FileNotFoundError("photo_root is not configured")
        project_root = Path(__file__).resolve().parents[1]
        command = [
            sys.executable,
            "run_index_pipeline.py",
            str(scan_root),
            "--concurrency",
            "2",
            "--max-retries",
            "5",
        ]
        runner = popen or subprocess.Popen
        self.delta_log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = self.delta_log_path.open("w", encoding="utf-8")
        process = runner(
            command,
            cwd=str(project_root),
            start_new_session=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        job = {
            "status": "started",
            "pid": getattr(process, "pid", None),
            "command": " ".join(command[1:]),
            "delta": delta,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "log_path": str(self.delta_log_path),
        }
        self._write_delta_update_job(job)
        if monitor_async:
            thread = threading.Thread(
                target=self._finalize_delta_update_job,
                args=(job, process, log_file),
                daemon=True,
            )
            thread.start()
        else:
            self._finalize_delta_update_job(job, process, log_file)
        return job

    def random_photos(self, *, limit: int = 24) -> list[dict[str, Any]]:
        """随机返回本地索引中的照片，给未搜索状态做自然的相册预览。"""

        return [self._format_row(row) for row in self.database.random_photos(limit=limit)]

    def update_photo_metadata(
        self,
        md5: str,
        *,
        description: str | None = None,
        tags: list[str] | None = None,
        colors: list[str] | None = None,
    ) -> dict[str, Any]:
        updated = self.database.update_photo_metadata(md5, description=description, tags=tags, colors=colors)
        if updated is None:
            raise KeyError(md5)
        return self._format_row(updated)

    def delete_photo(self, md5: str) -> dict[str, Any]:
        deleted = self.database.delete_photo_by_md5(md5)
        if deleted is None:
            raise KeyError(md5)
        thumbnail = self.thumbnail_dir / f"{md5}.jpg"
        try:
            thumbnail.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[LIMB-Ark] 缩略图删除失败 {thumbnail}: {exc}", flush=True)
        return {"status": "deleted", "md5": deleted["md5"], "path": deleted["path"]}

    def _stale_index_rows_from_apple_assets(
        self,
        indexed_rows: list[dict[str, Any]],
        apple_assets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        current_asset_ids = {str(asset.get("asset_id")) for asset in apple_assets if asset.get("asset_id")}
        current_local_identifiers = {
            str(asset.get("local_identifier")) for asset in apple_assets if asset.get("local_identifier")
        }
        current_paths: set[str] = set()
        for asset in apple_assets:
            for value in (asset.get("source_path"), asset.get("original_path")):
                if value:
                    current_paths.add(str(Path(value).expanduser().resolve()))

        stale_rows: list[dict[str, Any]] = []
        for row in indexed_rows:
            row_asset_id = str(row.get("asset_id") or "")
            row_local_identifier = str(row.get("local_identifier") or "")
            row_paths = {
                str(Path(value).expanduser().resolve())
                for value in (row.get("path"), row.get("original_path"))
                if value
            }
            if row_asset_id and row_asset_id in current_asset_ids:
                continue
            if row_local_identifier and row_local_identifier in current_local_identifiers:
                continue
            if row_paths & current_paths:
                continue
            stale_rows.append(row)
        return stale_rows

    def _stale_index_rows_from_local_files(self, indexed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        local_paths = {str(path) for path in self._iter_local_photo_files()}
        stale_rows: list[dict[str, Any]] = []
        for row in indexed_rows:
            candidates = [
                str(Path(value).expanduser().resolve())
                for value in (row.get("path"), row.get("original_path"))
                if value
            ]
            if not candidates or not any(
                candidate in local_paths or Path(candidate).exists() for candidate in candidates
            ):
                stale_rows.append(row)
        return stale_rows

    def prune_stale_index_entries(self) -> dict[str, Any]:
        indexed_rows = self.database.photo_fingerprints()
        apple_assets = self._apple_photo_assets_for_delta()
        if apple_assets:
            stale_rows = self._stale_index_rows_from_apple_assets(indexed_rows, apple_assets)
        else:
            stale_rows = self._stale_index_rows_from_local_files(indexed_rows)

        deleted: list[dict[str, Any]] = []
        for row in stale_rows:
            md5 = row.get("md5")
            if not md5:
                continue
            try:
                deleted.append(self.delete_photo(str(md5)))
            except KeyError:
                continue
        return {"status": "success", "deleted_count": len(deleted), "deleted": deleted}

    def open_photo_in_native_viewer(self, md5: str, open_runner: Any | None = None) -> dict[str, Any]:
        """用 macOS 默认图片查看器打开索引库中的原图。

        前端只传 md5，真实路径必须从 SQLite 索引读取，避免浏览器传任意路径导致误开系统文件。
        Photos Library 内部路径对 Preview 等 App 有 TCC 权限限制，所以先复制到 LIMB 自己的缓存目录。
        """

        photo = self.database.get_photo_by_md5(md5)
        if photo is None:
            raise KeyError(md5)
        candidate = photo.get("original_path") or photo.get("path")
        if not candidate:
            raise FileNotFoundError(md5)
        path = Path(candidate).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(str(path))
        suffix = path.suffix if path.suffix else ".jpg"
        native_open_dir = self.thumbnail_dir.parent / "native-open"
        native_open_dir.mkdir(parents=True, exist_ok=True)
        safe_md5 = re.sub(r"[^a-zA-Z0-9_-]", "", str(photo["md5"])) or "photo"
        open_path = (native_open_dir / f"{safe_md5}{suffix}").resolve()
        quality = "original-copy"
        try:
            shutil.copyfile(path, open_path)
        except PermissionError:
            thumbnail = (self.thumbnail_dir / f"{safe_md5}.jpg").resolve()
            if not thumbnail.exists():
                raise
            open_path.write_bytes(thumbnail.read_bytes())
            quality = "cached-thumbnail"
        runner = open_runner or subprocess.run
        runner(["open", str(open_path)], check=True)
        return {
            "status": "opened",
            "md5": photo["md5"],
            "path": str(open_path),
            "source_path": str(path),
            "quality": quality,
        }

    def _bridge_query(self, query: str) -> str:
        if self.query_bridge is None:
            return query
        try:
            parsed = self.query_bridge.parse(query)
        except Exception as exc:
            print(f"[LIMB-Ark] DeepSeek Query 解析失败，回退原始检索: {exc}", flush=True)
            return query

        terms = [*parsed.get("keywords", []), *parsed.get("colors", [])]
        clean_terms = []
        for term in terms:
            term = str(term).strip()
            if term and term not in clean_terms:
                clean_terms.append(term)
        return " ".join(clean_terms) if clean_terms else query

    def photo_path_to_url(self, photo_path: str | os.PathLike[str]) -> str:
        path = Path(photo_path).expanduser().resolve()
        if self.photo_root is None:
            return str(path)
        try:
            relative = path.relative_to(self.photo_root)
        except ValueError:
            return str(path)
        return f"{self.photos_base_url}/{quote(relative.as_posix())}"

    def thumbnail_url(self, md5: str) -> str:
        return f"{self.thumbnails_base_url}/{quote(str(md5))}.jpg"

    def preview_url(self, row: dict[str, Any]) -> str:
        md5 = str(row.get("md5") or "")
        if md5 and self.resolve_thumbnail_static_path(f"{md5}.jpg") is not None:
            return self.thumbnail_url(md5)
        path = row.get("path")
        if path:
            return self.photo_path_to_url(path)
        return self.thumbnail_url(md5)

    def resolve_photo_static_path(self, url_path: str) -> Path | None:
        if self.photo_root is None:
            return None
        candidate = (self.photo_root / url_path).expanduser().resolve()
        try:
            candidate.relative_to(self.photo_root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def resolve_thumbnail_static_path(self, file_name: str) -> Path | None:
        if not re.fullmatch(r"[a-fA-F0-9]{3,64}\.jpg", file_name):
            return None
        candidate = (self.thumbnail_dir / file_name).expanduser().resolve()
        try:
            candidate.relative_to(self.thumbnail_dir)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def thumbnail_path_for_photo_path(self, photo_path: str | os.PathLike[str]) -> Path | None:
        """按原图路径查找已缓存缩略图，用于 Apple Photos 权限受限时兜底展示。

        macOS 对 `.photoslibrary` 属于 TCC 保护区域。某些后台守护进程即使能看到路径，
        读取原图字节时也会被系统拒绝。缩略图是 LIMB 自己生成在项目 `.cache/` 下的小图，
        可以作为 LightBox 的无坏图兜底。
        """

        rows = self.database.get_photos_by_paths([photo_path])
        if not rows:
            return None
        thumbnail = (self.thumbnail_dir / f"{rows[0]['md5']}.jpg").expanduser().resolve()
        try:
            thumbnail.relative_to(self.thumbnail_dir)
        except ValueError:
            return None
        return thumbnail if thumbnail.is_file() else None

    def resolve_asset_image_static_path(self, asset_id: str) -> Path | None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{3,80}", asset_id):
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT original_path FROM photos WHERE asset_id = ? LIMIT 1",
                (asset_id,),
            ).fetchone()
        if row is None or not row["original_path"]:
            return None
        candidate = Path(row["original_path"]).expanduser().resolve()
        return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None


face_engine = FaceVectorEngine()
service = ArkSearchService(face_engine=face_engine)
app = FastAPI(title="LIMB Ark Text Search Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-LIMB-Search-Diagnostic"],
)


@app.get("/photos/{photo_path:path}")
def get_photo(photo_path: str):
    path = service.resolve_photo_static_path(photo_path)
    if path is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        body = path.read_bytes()
    except PermissionError as exc:
        thumbnail = service.thumbnail_path_for_photo_path(path)
        if thumbnail is None:
            raise HTTPException(
                status_code=403,
                detail=(
                    "macOS denied access to the Apple Photos original. "
                    "Grant Full Disk Access to the process that starts LIMB, or use the cached thumbnail."
                ),
            ) from exc
        return Response(
            thumbnail.read_bytes(),
            media_type="image/jpeg",
            headers={
                "Content-Length": str(thumbnail.stat().st_size),
                "Cache-Control": "public, max-age=3600",
                "X-LIMB-Photo-Stream": "thumbnail-fallback-permission",
                "X-LIMB-Original-Path": str(path),
            },
        )
    return Response(
        body,
        media_type=media_type,
        headers={
            "Content-Length": str(path.stat().st_size),
            "Cache-Control": "public, max-age=3600",
            "Accept-Ranges": "bytes",
            "X-LIMB-Photo-Stream": "ark-sqlite-local-bytes",
        },
    )


@app.get("/thumbnails/{file_name}")
def get_thumbnail(file_name: str):
    path = service.resolve_thumbnail_static_path(file_name)
    if path is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(
        path.read_bytes(),
        media_type="image/jpeg",
        headers={
            "Content-Length": str(path.stat().st_size),
            "Cache-Control": "public, max-age=86400",
            "X-LIMB-Photo-Stream": "ark-thumbnail-cache",
        },
    )


@app.get("/face-avatars/{file_name}")
def get_face_avatar(file_name: str):
    path = service.resolve_face_avatar_static_path(file_name)
    if path is None:
        raise HTTPException(status_code=404, detail="Face avatar not found")
    return Response(
        path.read_bytes(),
        media_type="image/jpeg",
        headers={
            "Content-Length": str(path.stat().st_size),
            "Cache-Control": "public, max-age=3600",
            "X-LIMB-Photo-Stream": "limb-face-profile-avatar",
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/assets/{asset_id}/image")
def get_asset_image(asset_id: str):
    path = service.resolve_asset_image_static_path(asset_id)
    if path is None:
        raise HTTPException(status_code=202, detail="Original is not local yet; PhotoKit prefetch may still be running.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Response(
        path.read_bytes(),
        media_type=media_type,
        headers={
            "Content-Length": str(path.stat().st_size),
            "Cache-Control": "public, max-age=3600",
            "Accept-Ranges": "bytes",
            "X-LIMB-Photo-Stream": "photokit-original-local",
        },
    )


@app.post("/api/search", response_model=None)
def search_photos(request: SearchRequest, background_tasks: BackgroundTasks):
    try:
        rows = service.search(request.query, limit=max(1, min(request.limit, 200)))
        identifiers = [str(row["local_identifier"]) for row in rows if row.get("local_identifier")]
        if identifiers:
            background_tasks.add_task(
                prefetch_originals_if_needed,
                identifiers[:5],
                path_resolver=service.original_path_for_local_identifier,
            )
        headers = {}
        if service.last_search_diagnostic:
            headers["X-LIMB-Search-Diagnostic"] = quote(
                json.dumps(service.last_search_diagnostic, ensure_ascii=False)
            )
        return JSONResponse(content=rows, headers=headers)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/index/status")
def index_status() -> dict[str, Any]:
    try:
        return service.index_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/index/delta")
def index_delta() -> dict[str, Any]:
    try:
        return service.index_delta()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/index/delta/run")
def run_index_delta_update() -> dict[str, Any]:
    try:
        return service.start_delta_update()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/index/delta/job")
def delta_update_job_status() -> dict[str, Any]:
    try:
        return service.delta_update_job_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/photos/random")
def random_photos(limit: int = 24) -> list[dict[str, Any]]:
    try:
        return service.random_photos(limit=max(1, min(int(limit), 80)))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/face/register")
async def register_face_profile(label: str = Form(...), files: list[UploadFile] = File(...)) -> dict[str, Any]:
    if len(files) < 3:
        raise HTTPException(status_code=400, detail="至少需要上传 3 张清晰人脸样张。")

    temp_paths: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix="limb-face-register-") as temp_dir:
            for index, upload in enumerate(files):
                suffix = Path(upload.filename or f"sample-{index}.jpg").suffix or ".jpg"
                target = Path(temp_dir) / f"sample-{index}{suffix}"
                target.write_bytes(await upload.read())
                temp_paths.append(target)
            profile = face_engine.register_profile(label, temp_paths)
    except FaceVectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "success",
        "label": profile["label"],
        "sample_count": profile["sample_count"],
        "message": f"成员 [{profile['label']}] 已成功精确锚定入库",
    }


@app.get("/api/face/profiles")
def list_face_profiles() -> list[dict[str, Any]]:
    try:
        return face_engine.list_profiles()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/people/profiles")
def list_people_profiles() -> list[dict[str, Any]]:
    try:
        return service.list_person_profiles()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/api/face/profiles/{label}")
def delete_face_profile(label: str) -> dict[str, Any]:
    try:
        return face_engine.delete_profile(label)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Face profile not found") from exc
    except FaceVectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/face/reindex")
def reindex_faces(request: FaceReindexRequest) -> dict[str, Any]:
    try:
        return service.start_face_reindex(photo_root=request.photo_root, face_engine=face_engine)
    except FaceVectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/face/reindex/job")
def face_reindex_job_status() -> dict[str, Any]:
    try:
        return service.face_reindex_job_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/photos/{md5}")
def update_photo(md5: str, request: PhotoUpdateRequest) -> dict[str, Any]:
    try:
        return service.update_photo_metadata(
            md5,
            description=request.description,
            tags=request.tags,
            colors=request.colors,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/api/photos/{md5}")
def delete_photo(md5: str) -> dict[str, Any]:
    try:
        return service.delete_photo(md5)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/photos/{md5}/open")
def open_photo_in_native_viewer(md5: str) -> dict[str, Any]:
    try:
        return service.open_photo_in_native_viewer(md5)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Photo file not found") from exc
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail="macOS image viewer failed to open photo") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/search/photos/{md5}")
def update_search_photo(md5: str, request: PhotoUpdateRequest) -> dict[str, Any]:
    """检索工作台使用的人工纠偏别名路由。"""

    return update_photo(md5, request)


@app.delete("/api/search/photos/{md5}")
def delete_search_photo(md5: str) -> dict[str, Any]:
    """检索工作台使用的删除索引别名路由。"""

    return delete_photo(md5)
