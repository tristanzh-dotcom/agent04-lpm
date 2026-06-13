from __future__ import annotations

"""
LIMB Ark 视觉索引引擎。

旧本地视觉模型清理指令（按需执行，不在脚本中自动删除用户文件）：

    # 1. 卸载本地 CLIP/人脸向量依赖
    python3 -m pip uninstall -y <旧本地视觉推理依赖包名>

    # 2. 删除 LIMB 旧模型缓存与旧向量索引
    rm -rf backend/models
    rm -f data/photo_index.pkl data/family_vectors.pkl

    # 3. 安装火山方舟 SDK 与新索引依赖
    python3 -m pip install --upgrade "volcengine-python-sdk[ark]" Pillow fastapi uvicorn python-multipart

新架构原则：
- 不再本地跑视觉模型，不再保存本地视觉向量。
- 扫描阶段调用专属火山方舟 Endpoint 生成结构化中文描述与标签。
- 检索阶段只查本地 SQLite/FTS5，前端请求不再触发视觉模型推理。
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import random
import re
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import jieba
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError


VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff")
ARK_MODEL = "doubao-1-5-vision-pro-32k"


class RateLimitError(RuntimeError):
    """火山方舟 429 / RPM / TPM 限流错误。"""


class ArkVisionError(RuntimeError):
    """方舟视觉打标失败。"""


def is_transient_ark_vision_error(error: Exception) -> bool:
    text = str(error)
    return any(
        token in text
        for token in (
            "Expecting value",
            "line 1 column 1",
            "JSONDecodeError",
            "500",
            "502",
            "503",
            "504",
        )
    )


def tokenize_chinese(text: str) -> list[str]:
    """用 Jieba 生成适合 FTS5 的中文 token，同时保留原始短语做兜底。"""

    normalized = str(text).strip()
    if not normalized:
        return []

    tokens: list[str] = []
    for chunk in re.split(r"[\s,，。；;、/|]+", normalized):
        chunk = chunk.strip()
        if not chunk:
            continue
        tokens.append(chunk)
        for token in jieba.cut_for_search(chunk):
            token = token.strip()
            if token and token not in tokens:
                tokens.append(token)
    return tokens


def jieba_cut(text: str) -> str:
    return " ".join(tokenize_chinese(text))


def build_search_text(description: str, tags: list[str], colors: list[str]) -> str:
    raw_text = " ".join([description, *tags, *colors])
    return " ".join([raw_text, jieba_cut(raw_text)])


def optimize_image_for_ark(
    source_path: str | os.PathLike[str],
    temp_dir: str | os.PathLike[str],
    *,
    max_edge: int = 1024,
    jpeg_quality: int = 85,
) -> Path:
    """将原图等比压缩成干净 JPEG 临时文件，避免大图/Exif 拖慢批量上传。

    Pillow 默认会保留部分元数据；这里显式创建新的 RGB 图像并只保存像素内容，
    从而抹除 Exif、地理位置、缩略图等大体积元数据。
    """

    source = Path(source_path).expanduser().resolve()
    output_dir = Path(temp_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    readable_source = source

    try:
        Image.open(source).close()
    except UnidentifiedImageError:
        if source.suffix.lower() not in {".heic", ".heif"}:
            raise
        converted = output_dir / f"{source.stem}-sips-source.jpg"
        subprocess.run(
            ["sips", "-s", "format", "jpeg", str(source), "--out", str(converted)],
            check=True,
            capture_output=True,
            text=True,
        )
        readable_source = converted

    with Image.open(readable_source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        clean_size = (max(14, image.size[0]), max(14, image.size[1]))
        clean_image = Image.new("RGB", clean_size, (255, 255, 255))
        offset = ((clean_size[0] - image.size[0]) // 2, (clean_size[1] - image.size[1]) // 2)
        clean_image.paste(image, offset)

        target = output_dir / f"{source.stem}-{hashlib.md5(str(source).encode()).hexdigest()[:10]}.jpg"
        clean_image.save(target, format="JPEG", quality=jpeg_quality, optimize=True)
        return target


def persist_thumbnail(optimized_path: str | os.PathLike[str], thumbnail_dir: str | os.PathLike[str], md5: str) -> Path:
    """把已压缩好的 1024px JPEG 作为前端缩略图持久化缓存。"""

    output_dir = Path(thumbnail_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{md5}.jpg"
    if not target.exists():
        target.write_bytes(Path(optimized_path).read_bytes())
    return target


def _parse_exif_datetime(value: Any) -> str | None:
    """把 EXIF 的 `YYYY:MM:DD HH:MM:SS` 转成前端更易消费的 ISO-like 字符串。"""

    text = str(value or "").strip()
    match = re.match(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$", text)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}"


def _ratio_to_float(value: Any) -> float:
    """兼容 Pillow IFDRational、(num, den) tuple 和普通数字。"""

    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        return float(numerator) / float(denominator or 1)
    return float(value)


def _gps_to_decimal(values: Any, ref: Any) -> float | None:
    try:
        degree, minute, second = values
        decimal = _ratio_to_float(degree) + _ratio_to_float(minute) / 60 + _ratio_to_float(second) / 3600
        if str(ref).upper() in {"S", "W"}:
            decimal *= -1
        return round(decimal, 7)
    except Exception:
        return None


def _extract_gps_coordinates(exif: Image.Exif) -> tuple[float | None, float | None]:
    try:
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
    except Exception:
        gps_ifd = exif.get(int(ExifTags.IFD.GPSInfo), {}) or {}
    if not gps_ifd:
        return None, None

    latitude = _gps_to_decimal(gps_ifd.get(2), gps_ifd.get(1))
    longitude = _gps_to_decimal(gps_ifd.get(4), gps_ifd.get(3))
    return latitude, longitude


def extract_photo_capture_metadata(source_path: str | os.PathLike[str]) -> dict[str, Any]:
    """从原始图片读取拍摄时间和 GPS，经 SQLite/API 透传给前端。

    这里读取的是原图的 EXIF，而不是 1024px 压缩图；压缩图会主动抹除 EXIF，
    避免缩略图泄露额外隐私和拖慢加载。
    """

    path = Path(source_path).expanduser().resolve()
    metadata: dict[str, Any] = {
        "taken_at": None,
        "latitude": None,
        "longitude": None,
        "location_text": None,
        "metadata_source": None,
    }

    try:
        with Image.open(path) as image:
            exif = image.getexif()
            for tag in (
                int(ExifTags.Base.DateTimeOriginal),
                int(ExifTags.Base.DateTimeDigitized),
                int(ExifTags.Base.DateTime),
            ):
                taken_at = _parse_exif_datetime(exif.get(tag))
                if taken_at:
                    metadata["taken_at"] = taken_at
                    break

            latitude, longitude = _extract_gps_coordinates(exif)
            if latitude is not None and longitude is not None:
                metadata["latitude"] = latitude
                metadata["longitude"] = longitude
                metadata["location_text"] = f"{latitude:.6f}, {longitude:.6f}"
    except Exception:
        return metadata

    if metadata["taken_at"] or metadata["latitude"] is not None or metadata["longitude"] is not None:
        metadata["metadata_source"] = "exif"
    return metadata


class ArkPhotoIndexDatabase:
    """SQLite + FTS5 本地文本索引库。"""

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10.0)
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.row_factory = sqlite3.Row
        connection.create_function("jieba_cut", 1, jieba_cut)
        return connection

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS photos (
                    path TEXT PRIMARY KEY,
                    md5 TEXT NOT NULL,
                    modify_time REAL NOT NULL,
                    description TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    colors_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    indexed_at REAL NOT NULL,
                    asset_id TEXT,
                    local_identifier TEXT,
                    original_path TEXT,
                    thumbnail_path TEXT,
                    source TEXT
                )
                """
            )
            self._ensure_asset_columns(connection)
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS photos_fts
                USING fts5(path UNINDEXED, search_text, tokenize='unicode61')
                """
            )
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version < 2:
                self._rebuild_fts(connection)
                connection.execute("PRAGMA user_version = 2")

    def _ensure_asset_columns(self, connection: sqlite3.Connection) -> None:
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(photos)").fetchall()}
        columns = {
            "asset_id": "TEXT",
            "local_identifier": "TEXT",
            "original_path": "TEXT",
            "thumbnail_path": "TEXT",
            "source": "TEXT",
            "taken_at": "TEXT",
            "latitude": "REAL",
            "longitude": "REAL",
            "location_text": "TEXT",
            "location_display_name": "TEXT",
            "metadata_source": "TEXT",
        }
        for name, column_type in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE photos ADD COLUMN {name} {column_type}")

    def _rebuild_fts(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT path, description, tags_json, colors_json FROM photos").fetchall()
        connection.execute("DELETE FROM photos_fts")
        for row in rows:
            tags = json.loads(row["tags_json"])
            colors = json.loads(row["colors_json"])
            connection.execute(
                "INSERT INTO photos_fts(path, search_text) VALUES (?, ?)",
                (row["path"], build_search_text(row["description"], tags, colors)),
            )

    def is_current(self, path: str | os.PathLike[str], md5: str, modify_time: float) -> bool:
        resolved = str(Path(path).expanduser().resolve())
        with self.connect() as connection:
            row = connection.execute(
                "SELECT md5, modify_time FROM photos WHERE path = ?",
                (resolved,),
            ).fetchone()
        return bool(row and row["md5"] == md5 and float(row["modify_time"]) == float(modify_time))

    def upsert_photo(
        self,
        *,
        path: str | os.PathLike[str],
        md5: str,
        modify_time: float,
        description: str,
        tags: list[str],
        colors: list[str],
        raw_json: dict[str, Any] | None = None,
        asset_id: str | None = None,
        local_identifier: str | None = None,
        original_path: str | os.PathLike[str] | None = None,
        thumbnail_path: str | os.PathLike[str] | None = None,
        source: str | None = None,
        taken_at: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        location_text: str | None = None,
        location_display_name: str | None = None,
        metadata_source: str | None = None,
    ) -> None:
        resolved = str(Path(path).expanduser().resolve())
        resolved_original = str(Path(original_path).expanduser().resolve()) if original_path else resolved
        resolved_thumbnail = str(Path(thumbnail_path).expanduser().resolve()) if thumbnail_path else None
        clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        clean_colors = [str(color).strip() for color in colors if str(color).strip()]
        payload = raw_json or {"description": description, "tags": clean_tags, "colors": clean_colors}
        search_text = build_search_text(description, clean_tags, clean_colors)

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO photos(
                    path, md5, modify_time, description, tags_json, colors_json, raw_json, indexed_at,
                    asset_id, local_identifier, original_path, thumbnail_path, source,
                    taken_at, latitude, longitude, location_text, location_display_name, metadata_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    md5 = excluded.md5,
                    modify_time = excluded.modify_time,
                    description = excluded.description,
                    tags_json = excluded.tags_json,
                    colors_json = excluded.colors_json,
                    raw_json = excluded.raw_json,
                    indexed_at = excluded.indexed_at,
                    asset_id = excluded.asset_id,
                    local_identifier = excluded.local_identifier,
                    original_path = excluded.original_path,
                    thumbnail_path = excluded.thumbnail_path,
                    source = excluded.source,
                    taken_at = excluded.taken_at,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    location_text = excluded.location_text,
                    location_display_name = excluded.location_display_name,
                    metadata_source = excluded.metadata_source
                """,
                (
                    resolved,
                    md5,
                    modify_time,
                    description,
                    json.dumps(clean_tags, ensure_ascii=False),
                    json.dumps(clean_colors, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                    time.time(),
                    asset_id,
                    local_identifier,
                    resolved_original,
                    resolved_thumbnail,
                    source or "filesystem",
                    taken_at,
                    latitude,
                    longitude,
                    location_text,
                    location_display_name,
                    metadata_source,
                ),
            )
            connection.execute("DELETE FROM photos_fts WHERE path = ?", (resolved,))
            connection.execute(
                "INSERT INTO photos_fts(path, search_text) VALUES (?, ?)",
                (resolved, search_text),
            )

    def search(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        clean_query = query.strip()
        if not clean_query:
            return []

        fts_query = self._build_fts_query(clean_query)
        like_query = f"%{clean_query}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT p.path, p.md5, p.description, p.tags_json, p.colors_json,
                       p.asset_id, p.local_identifier, p.original_path, p.thumbnail_path, p.source,
                       p.taken_at, p.latitude, p.longitude, p.location_text, p.location_display_name, p.metadata_source
                FROM photos_fts f
                JOIN photos p ON p.path = f.path
                WHERE photos_fts MATCH ?
                ORDER BY bm25(photos_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            if not rows:
                rows = connection.execute(
                    """
                    SELECT p.path, p.md5, p.description, p.tags_json, p.colors_json,
                           p.asset_id, p.local_identifier, p.original_path, p.thumbnail_path, p.source,
                           p.taken_at, p.latitude, p.longitude, p.location_text, p.location_display_name, p.metadata_source
                    FROM photos p
                    JOIN photos_fts f ON p.path = f.path
                    WHERE f.search_text LIKE ?
                    LIMIT ?
                    """,
                    (like_query, limit),
                ).fetchall()

        return [
            {
                "path": row["path"],
                "md5": row["md5"],
                "description": row["description"],
                "tags": json.loads(row["tags_json"]),
                "colors": json.loads(row["colors_json"]),
                "asset_id": row["asset_id"],
                "local_identifier": row["local_identifier"],
                "original_path": row["original_path"],
                "thumbnail_path": row["thumbnail_path"],
                "source": row["source"] or "filesystem",
                "taken_at": row["taken_at"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "location_text": row["location_text"],
                "location_display_name": row["location_display_name"],
                "metadata_source": row["metadata_source"],
            }
            for row in rows
        ]

    def count_photos(self) -> int:
        """返回当前已经落库的照片索引数量，用于健康检查和前端空库提示。"""

        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM photos").fetchone()
        return int(row[0])

    def photo_fingerprints(self) -> list[dict[str, Any]]:
        """返回索引库中的轻量文件指纹，用于本地差量检测。

        该方法只读取路径、mtime 和 md5，不读取图片、不调用模型。
        """

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT path, original_path, md5, modify_time, asset_id, local_identifier, source
                FROM photos
                """
            ).fetchall()
        return [
            {
                "path": row["path"],
                "original_path": row["original_path"],
                "md5": row["md5"],
                "modify_time": row["modify_time"],
                "asset_id": row["asset_id"],
                "local_identifier": row["local_identifier"],
                "source": row["source"] or "filesystem",
            }
            for row in rows
        ]

    def random_photos(self, *, limit: int = 24) -> list[dict[str, Any]]:
        """随机抽取已索引照片，用于前端未搜索时的相册预览流。"""

        safe_limit = max(1, min(int(limit), 80))
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT path, md5, description, tags_json, colors_json,
                       asset_id, local_identifier, original_path, thumbnail_path, source,
                       taken_at, latitude, longitude, location_text, location_display_name, metadata_source
                FROM photos
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

        return [
            {
                "path": row["path"],
                "md5": row["md5"],
                "description": row["description"],
                "tags": json.loads(row["tags_json"]),
                "colors": json.loads(row["colors_json"]),
                "asset_id": row["asset_id"],
                "local_identifier": row["local_identifier"],
                "original_path": row["original_path"],
                "thumbnail_path": row["thumbnail_path"],
                "source": row["source"] or "filesystem",
                "taken_at": row["taken_at"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "location_text": row["location_text"],
                "location_display_name": row["location_display_name"],
                "metadata_source": row["metadata_source"],
            }
            for row in rows
        ]

    def get_photo_by_md5(self, md5: str) -> dict[str, Any] | None:
        """按 md5 读取照片记录，用于人工纠偏和删除前确认。"""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT path, md5, modify_time, description, tags_json, colors_json, raw_json,
                       asset_id, local_identifier, original_path, thumbnail_path, source,
                       taken_at, latitude, longitude, location_text, location_display_name, metadata_source
                FROM photos
                WHERE md5 = ?
                LIMIT 1
                """,
                (md5,),
            ).fetchone()
        if row is None:
            return None
        return {
            "path": row["path"],
            "md5": row["md5"],
            "modify_time": row["modify_time"],
            "description": row["description"],
            "tags": json.loads(row["tags_json"]),
            "colors": json.loads(row["colors_json"]),
            "raw_json": json.loads(row["raw_json"]),
            "asset_id": row["asset_id"],
            "local_identifier": row["local_identifier"],
            "original_path": row["original_path"],
            "thumbnail_path": row["thumbnail_path"],
            "source": row["source"] or "filesystem",
            "taken_at": row["taken_at"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "location_text": row["location_text"],
            "location_display_name": row["location_display_name"],
            "metadata_source": row["metadata_source"],
        }

    def get_photos_by_paths(self, paths: Iterable[str | os.PathLike[str]]) -> list[dict[str, Any]]:
        """按本地绝对路径批量读取照片记录，保持输入顺序。

        Apple Photos 冷数据会用 derivative 预览图作为 `path` 落库，同时保留
        原始 `original_path`。人物映射仍来自 Apple Photos 原图路径，所以这里
        必须同时匹配 `path` 和 `original_path`。
        """

        resolved_paths = [str(Path(path).expanduser().resolve()) for path in paths]
        if not resolved_paths:
            return []
        placeholders = ",".join("?" for _ in resolved_paths)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT path, md5, description, tags_json, colors_json,
                       asset_id, local_identifier, original_path, thumbnail_path, source,
                       taken_at, latitude, longitude, location_text, location_display_name, metadata_source
                FROM photos
                WHERE path IN ({placeholders}) OR original_path IN ({placeholders})
                """,
                [*resolved_paths, *resolved_paths],
            ).fetchall()

        by_lookup: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = {
                "path": row["path"],
                "md5": row["md5"],
                "description": row["description"],
                "tags": json.loads(row["tags_json"]),
                "colors": json.loads(row["colors_json"]),
                "asset_id": row["asset_id"],
                "local_identifier": row["local_identifier"],
                "original_path": row["original_path"],
                "thumbnail_path": row["thumbnail_path"],
                "source": row["source"] or "filesystem",
                "taken_at": row["taken_at"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "location_text": row["location_text"],
                "location_display_name": row["location_display_name"],
                "metadata_source": row["metadata_source"],
            }
            by_lookup[row["path"]] = payload
            if row["original_path"]:
                by_lookup[row["original_path"]] = payload
        return [by_lookup[path] for path in resolved_paths if path in by_lookup]

    def backfill_capture_metadata(self, *, extractor: Any = extract_photo_capture_metadata, limit: int | None = None) -> int:
        """给旧索引补齐 EXIF 拍摄时间/GPS，不重新调用 Ark、不改动语义标签。"""

        query = """
            SELECT path FROM photos
            WHERE metadata_source IS NULL
               OR (taken_at IS NULL AND latitude IS NULL AND longitude IS NULL)
            ORDER BY indexed_at DESC
        """
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (int(limit),)

        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        updated = 0
        for row in rows:
            path = row["path"]
            metadata = extractor(path)
            if not any(
                metadata.get(key) is not None for key in ("taken_at", "latitude", "longitude", "location_text")
            ):
                continue
            with self.connect() as connection:
                connection.execute(
                    """
                    UPDATE photos
                    SET taken_at = ?, latitude = ?, longitude = ?, location_text = ?, metadata_source = ?
                    WHERE path = ?
                    """,
                    (
                        metadata.get("taken_at"),
                        metadata.get("latitude"),
                        metadata.get("longitude"),
                        metadata.get("location_text"),
                        metadata.get("metadata_source"),
                        path,
                    ),
                )
            updated += 1
        return updated

    def backfill_location_display_names(self, rows: Iterable[dict[str, Any]]) -> int:
        """把 Apple Photos 已有人类可读地点名同步到本地索引。"""

        updated = 0
        with self.connect() as connection:
            for row in rows:
                display_name = str(row.get("location_display_name") or "").strip()
                original_path = row.get("original_path")
                if not display_name or not original_path:
                    continue
                resolved = str(Path(original_path).expanduser().resolve())
                cursor = connection.execute(
                    """
                    UPDATE photos
                    SET location_display_name = ?,
                        metadata_source = CASE
                            WHEN metadata_source IS NULL OR metadata_source = ''
                            THEN 'apple_photos'
                            ELSE metadata_source
                        END
                    WHERE path = ? OR original_path = ?
                    """,
                    (display_name, resolved, resolved),
                )
                updated += int(cursor.rowcount or 0)
        return updated

    def update_photo_metadata(
        self,
        md5: str,
        *,
        description: str | None = None,
        tags: list[str] | None = None,
        colors: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """按 md5 更新人工修正后的描述、标签和色彩，并同步刷新 FTS 文本。"""

        current = self.get_photo_by_md5(md5)
        if current is None:
            return None

        next_description = str(description).strip() if description is not None else current["description"]
        next_tags = [str(tag).strip() for tag in (tags if tags is not None else current["tags"]) if str(tag).strip()]
        next_colors = [
            str(color).strip() for color in (colors if colors is not None else current["colors"]) if str(color).strip()
        ]
        raw_json = {
            **current.get("raw_json", {}),
            "description": next_description,
            "tags": next_tags,
            "colors": next_colors,
            "manual_override": True,
        }
        search_text = build_search_text(next_description, next_tags, next_colors)

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE photos
                SET description = ?, tags_json = ?, colors_json = ?, raw_json = ?, indexed_at = ?
                WHERE md5 = ?
                """,
                (
                    next_description,
                    json.dumps(next_tags, ensure_ascii=False),
                    json.dumps(next_colors, ensure_ascii=False),
                    json.dumps(raw_json, ensure_ascii=False),
                    time.time(),
                    md5,
                ),
            )
            connection.execute("DELETE FROM photos_fts WHERE path = ?", (current["path"],))
            connection.execute(
                "INSERT INTO photos_fts(path, search_text) VALUES (?, ?)",
                (current["path"], search_text),
            )
        return self.get_photo_by_md5(md5)

    def delete_photo_by_md5(self, md5: str) -> dict[str, Any] | None:
        """按 md5 从主表与 FTS 表删除照片索引，返回被删除记录。"""

        current = self.get_photo_by_md5(md5)
        if current is None:
            return None
        with self.connect() as connection:
            rows = connection.execute("SELECT path FROM photos WHERE md5 = ?", (md5,)).fetchall()
            for row in rows:
                connection.execute("DELETE FROM photos_fts WHERE path = ?", (row["path"],))
            connection.execute("DELETE FROM photos WHERE md5 = ?", (md5,))
        return current

    def _build_fts_query(self, query: str) -> str:
        tokens = tokenize_chinese(query)
        if len(tokens) > 1 and not re.search(r"[\s,，。；;、/|]+", query.strip()):
            tokens = tokens[1:]
        if not tokens:
            return f'"{query}"'
        return " AND ".join(f'"{token}"' for token in tokens[:8])


class ArkVisionClient:
    """火山方舟视觉模型适配器。

    这里坚持使用 SDK 托管能力：调用方只传入本地优化后的图片路径，不手写图床上传。
    最新 SDK 若支持本地路径自动托管，`image_url.url` 会直接交给 SDK 处理。
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint_id: str | None = None,
        model: str = ARK_MODEL,
    ) -> None:
        self.api_key = api_key or os.environ.get("ARK_API_KEY")
        self.endpoint_id = endpoint_id or os.environ.get("ARK_ENDPOINT_ID")
        self.model = self.endpoint_id or model
        if not self.api_key:
            raise ArkVisionError("缺少 ARK_API_KEY 环境变量。")

        try:
            from volcenginesdkarkruntime import AsyncArk
        except ImportError as exc:
            raise ArkVisionError(
                "缺少火山方舟 SDK，请执行: python3 -m pip install --upgrade 'volcengine-python-sdk[ark]'"
            ) from exc

        self.client = AsyncArk(api_key=self.api_key)

    async def describe_image(self, image_path: Path) -> dict[str, Any]:
        system_prompt = (
            "你是 LIMB 本地相册索引系统的视觉打标器。"
            "请严格只返回 JSON，不要 Markdown，不要解释。"
            "JSON 格式必须为："
            '{"description":"一段细腻的中文场景描述","tags":["标签1","标签2"],"colors":["主色调"]}。'
            "标签必须包含人物、物体、动作、场景、交通工具、宠物、服饰、地点等可检索要素。"
        )
        image_reference = self._image_path_to_data_url(image_path)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请分析这张本地相册图片并生成结构化 JSON 标签。"},
                            {"type": "image_url", "image_url": {"url": image_reference}},
                        ],
                    },
                ],
                temperature=0,
            )
            content = response.choices[0].message.content
            return self._parse_json_content(content)
        except Exception as exc:
            text = str(exc)
            if "429" in text or "Rate Limit" in text or "rate limit" in text:
                raise RateLimitError(text) from exc
            raise ArkVisionError(f"方舟视觉推理失败: {text}") from exc

    def _image_path_to_data_url(self, image_path: Path) -> str:
        """把本地压缩图转成 Ark 接口支持的 base64 data URL。"""

        encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", content.strip(), flags=re.DOTALL)
        payload = json.loads(match.group(0) if match else content)
        return {
            "description": str(payload.get("description", "")).strip(),
            "tags": [str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()],
            "colors": [str(color).strip() for color in payload.get("colors", []) if str(color).strip()],
        }


@dataclass
class IndexStats:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0


class ArkVisionBatchIndexer:
    """带限流、退避重试、增量跳过的批量打标器。"""

    def __init__(
        self,
        *,
        photo_root: str | os.PathLike[str],
        database: ArkPhotoIndexDatabase,
        ark_client: Any | None = None,
        max_concurrency: int = 3,
        max_retries: int = 5,
        retry_base_seconds: float = 1.0,
        max_edge: int = 1024,
        thumbnail_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.photo_root = Path(photo_root).expanduser().resolve()
        self.database = database
        self.ark_client = ark_client or ArkVisionClient()
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.max_edge = max_edge
        self.thumbnail_dir = Path(thumbnail_dir or Path(".cache") / "thumbnails").expanduser().resolve()

    @staticmethod
    def compute_md5(path: str | os.PathLike[str]) -> str:
        digest = hashlib.md5()
        with Path(path).open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def scan_and_index(self) -> int:
        if not self.photo_root.exists() or not self.photo_root.is_dir():
            raise FileNotFoundError(f"相册目录不存在: {self.photo_root}")

        queue: list[Path] = []
        skipped = 0
        for path in self.iter_image_files(self.photo_root):
            md5 = self.compute_md5(path)
            modify_time = path.stat().st_mtime
            if self.database.is_current(path, md5, modify_time):
                skipped += 1
                continue
            queue.append(path)

        print(f"[LIMB-Ark] 待索引 {len(queue)} 张，跳过未变化 {skipped} 张。", flush=True)
        stats = IndexStats(skipped=skipped)
        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = [asyncio.create_task(self._index_one(path, stats)) for path in queue]
        if tasks:
            await asyncio.gather(*tasks)
        print(
            f"[LIMB-Ark] 完成：indexed={stats.indexed} skipped={stats.skipped} failed={stats.failed}",
            flush=True,
        )
        return stats.indexed

    def iter_image_files(self, root: Path) -> Iterable[Path]:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in VALID_EXTENSIONS:
                yield path.resolve()

    async def _index_one(self, path: Path, stats: IndexStats) -> None:
        async with self.semaphore:
            try:
                md5 = self.compute_md5(path)
                modify_time = path.stat().st_mtime
                capture_metadata = extract_photo_capture_metadata(path)
                with tempfile.TemporaryDirectory(prefix="limb-ark-") as temp_dir:
                    optimized = optimize_image_for_ark(path, temp_dir, max_edge=self.max_edge)
                    persist_thumbnail(optimized, self.thumbnail_dir, md5)
                    payload = await self._describe_with_retry(optimized)
                self.database.upsert_photo(
                    path=path,
                    md5=md5,
                    modify_time=modify_time,
                    description=payload["description"],
                    tags=payload["tags"],
                    colors=payload["colors"],
                    raw_json=payload,
                    **capture_metadata,
                )
                stats.indexed += 1
            except Exception as exc:
                stats.failed += 1
                print(f"[LIMB-Ark] 索引失败 {path}: {exc}", flush=True)

    async def _describe_with_retry(self, optimized_path: Path) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                return await self.ark_client.describe_image(optimized_path)
            except RateLimitError:
                if attempt >= self.max_retries:
                    raise
                delay = self.retry_base_seconds * (2**attempt) + random.uniform(0, self.retry_base_seconds)
                print(f"[LIMB-Ark] 命中限流，{delay:.2f}s 后重试。", flush=True)
                await asyncio.sleep(delay)
            except ArkVisionError as exc:
                if attempt >= self.max_retries or not is_transient_ark_vision_error(exc):
                    raise
                delay = self.retry_base_seconds * (2**attempt) + random.uniform(0, self.retry_base_seconds)
                print(f"[LIMB-Ark] Ark 临时响应异常，{delay:.2f}s 后重试。", flush=True)
                await asyncio.sleep(delay)
        raise ArkVisionError("重试耗尽。")


def main() -> int:
    parser = argparse.ArgumentParser(description="LIMB Ark 云端视觉离线建索引")
    parser.add_argument("photo_root", help="本地相册目录，例如 Apple Photos 的 originals 或导出的照片目录")
    parser.add_argument("--db", default="data/limb_ark.sqlite3", help="SQLite 索引库路径")
    parser.add_argument("--concurrency", type=int, default=3, help="最大并发请求数")
    parser.add_argument("--max-edge", type=int, default=1024, help="上传前图片最长边像素")
    args = parser.parse_args()

    database = ArkPhotoIndexDatabase(args.db)
    indexer = ArkVisionBatchIndexer(
        photo_root=args.photo_root,
        database=database,
        max_concurrency=args.concurrency,
        max_edge=args.max_edge,
    )
    asyncio.run(indexer.scan_and_index())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
