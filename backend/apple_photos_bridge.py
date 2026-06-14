from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import plistlib
import sqlite3
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union
from datetime import datetime, timezone


PathResolver = Callable[[str], Optional[Union[str, os.PathLike]]]
OriginalRequester = Callable[[str], Union[Awaitable[str], str]]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff"}
LOGGER = logging.getLogger(__name__)


def stable_asset_id(local_identifier: str) -> str:
    """把 PhotoKit localIdentifier 转成安全、稳定的文件名/API 主键。"""

    return hashlib.sha1(str(local_identifier).encode("utf-8")).hexdigest()


def is_real_local_file(path: str | os.PathLike[str] | None) -> bool:
    """判断原图是否已真实落在本地磁盘，过滤 0 字节 stub。"""

    if path is None:
        return False
    candidate = Path(path).expanduser()
    return candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0


def _resolve_plist_uid(objects: list[Any], value: Any) -> Any:
    if isinstance(value, plistlib.UID):
        index = int(value.data)
        return objects[index] if 0 <= index < len(objects) else None
    return value


def parse_reverse_location_blob(blob: bytes | None) -> str | None:
    """解析 Apple Photos 已保存的反向地理编码文本。

    Photos.sqlite 中的 ZREVERSELOCATIONDATA 是 NSKeyedArchiver bplist。
    这里只读其中的 place name，不做任何网络反查。
    """

    if not blob:
        return None
    try:
        payload = plistlib.loads(blob)
    except Exception:
        return None
    objects = payload.get("$objects")
    if not isinstance(objects, list):
        return None

    def names_from_array(array_obj: Any) -> list[str]:
        array_obj = _resolve_plist_uid(objects, array_obj)
        if not isinstance(array_obj, dict):
            return []
        names: list[str] = []
        for ref in array_obj.get("NS.objects", []):
            place = _resolve_plist_uid(objects, ref)
            if not isinstance(place, dict):
                continue
            name = _resolve_plist_uid(objects, place.get("name"))
            name = str(name or "").strip()
            if name and name not in names and name.upper() != "CN" and name != "中国":
                names.append(name)
        return names

    root_ref = payload.get("$top", {}).get("root")
    root = _resolve_plist_uid(objects, root_ref)
    map_item = _resolve_plist_uid(objects, root.get("mapItem")) if isinstance(root, dict) else None
    names: list[str] = []
    if isinstance(map_item, dict):
        names = names_from_array(map_item.get("sortedPlaceInfos"))
        if not names:
            names = names_from_array(map_item.get("finalPlaceInfos"))
    if not names:
        for item in objects:
            if isinstance(item, dict) and "name" in item:
                name = _resolve_plist_uid(objects, item.get("name"))
                name = str(name or "").strip()
                if name and name not in names and name.upper() != "CN" and name != "中国":
                    names.append(name)

    if not names:
        return None
    ordered = list(reversed(names))
    return " ".join(ordered[:3])


class ApplePhotosPeopleBridge:
    """只读继承 Apple Photos 已命名人物/宠物聚类结果。

    注意：这里读取的是 macOS Photos 私有 SQLite 结构，所以永远使用只读连接，
    并把结果同步到 LIMB 自己的数据层；严禁写回 Photos.sqlite。
    """

    def __init__(self, photo_library_path: str | os.PathLike[str]) -> None:
        self.photo_library_path = Path(photo_library_path).expanduser().resolve()
        self.photos_db_path = self.photo_library_path / "database" / "Photos.sqlite"

    def connect_readonly(self) -> sqlite3.Connection:
        if not self.photos_db_path.exists():
            raise FileNotFoundError(f"找不到 Apple Photos 数据库: {self.photos_db_path}")
        uri = f"file:{self.photos_db_path}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def list_named_people(self) -> list[dict[str, Any]]:
        """列出 Photos 已命名的人物/宠物聚类，不返回空白未命名候选人。"""

        with self.connect_readonly() as connection:
            person_uuid_expr = self._person_uuid_expression(connection)
            rows = connection.execute(
                f"""
                SELECT
                    p.Z_PK AS person_pk,
                    {person_uuid_expr} AS person_uuid,
                    COALESCE(NULLIF(TRIM(p.ZDISPLAYNAME), ''), NULLIF(TRIM(p.ZFULLNAME), '')) AS label,
                    COALESCE(p.ZFACECOUNT, 0) AS face_count,
                    COALESCE(p.ZDETECTIONTYPE, 0) AS detection_type,
                    COUNT(DISTINCT a.Z_PK) AS asset_count
                FROM ZPERSON p
                LEFT JOIN ZDETECTEDFACE f ON f.ZPERSONFORFACE = p.Z_PK
                LEFT JOIN ZASSET a ON a.Z_PK = f.ZASSETFORFACE
                WHERE COALESCE(NULLIF(TRIM(p.ZDISPLAYNAME), ''), NULLIF(TRIM(p.ZFULLNAME), '')) IS NOT NULL
                GROUP BY p.Z_PK
                ORDER BY asset_count DESC, label ASC
                """
            ).fetchall()

        return [
            {
                "person_pk": int(row["person_pk"]),
                "uuid": row["person_uuid"],
                "label": row["label"],
                "entity_type": self._entity_type(row["detection_type"]),
                "face_count": int(row["face_count"] or 0),
                "asset_count": int(row["asset_count"] or 0),
                "source": "apple_photos",
            }
            for row in rows
        ]

    def iter_person_asset_links(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """返回 Photos 已命名人物/宠物与资产的只读映射。"""

        query = """
            SELECT DISTINCT
                p.Z_PK AS person_pk,
                __PERSON_UUID_EXPR__ AS person_uuid,
                COALESCE(NULLIF(TRIM(p.ZDISPLAYNAME), ''), NULLIF(TRIM(p.ZFULLNAME), '')) AS label,
                COALESCE(p.ZDETECTIONTYPE, 0) AS detection_type,
                a.ZUUID AS asset_uuid,
                a.ZDIRECTORY AS directory,
                a.ZFILENAME AS filename,
                f.ZQUALITY AS quality
            FROM ZPERSON p
            JOIN ZDETECTEDFACE f ON f.ZPERSONFORFACE = p.Z_PK
            JOIN ZASSET a ON a.Z_PK = f.ZASSETFORFACE
            WHERE COALESCE(NULLIF(TRIM(p.ZDISPLAYNAME), ''), NULLIF(TRIM(p.ZFULLNAME), '')) IS NOT NULL
              AND a.ZDIRECTORY IS NOT NULL
              AND a.ZFILENAME IS NOT NULL
            ORDER BY label ASC, quality DESC
        """
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (int(limit),)

        with self.connect_readonly() as connection:
            person_uuid_expr = self._person_uuid_expression(connection)
            query = query.replace("__PERSON_UUID_EXPR__", person_uuid_expr)
            rows = connection.execute(query, parameters).fetchall()

        return [
            {
                "person_pk": int(row["person_pk"]),
                "uuid": row["person_uuid"],
                "label": row["label"],
                "entity_type": self._entity_type(row["detection_type"]),
                "asset_uuid": row["asset_uuid"],
                "original_path": str(self._original_path(row["directory"], row["filename"])),
                "quality": float(row["quality"] or 0),
                "source": "apple_photos",
            }
            for row in rows
        ]

    def iter_asset_location_metadata(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """读取 Apple Photos 已有的位置显示文本，用于同步到 LIMB SQLite。"""

        query = """
            SELECT
                a.ZUUID AS asset_uuid,
                a.ZDIRECTORY AS directory,
                a.ZFILENAME AS filename,
                aa.ZREVERSELOCATIONDATA AS reverse_location_data,
                aa.ZPLACEANNOTATIONDATA AS place_annotation_data
            FROM ZASSET a
            JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK
            WHERE a.ZDIRECTORY IS NOT NULL
              AND a.ZFILENAME IS NOT NULL
              AND (
                aa.ZREVERSELOCATIONDATA IS NOT NULL
                OR aa.ZPLACEANNOTATIONDATA IS NOT NULL
              )
            ORDER BY a.Z_PK ASC
        """
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (int(limit),)

        with self.connect_readonly() as connection:
            rows = connection.execute(query, parameters).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            display_name = parse_reverse_location_blob(row["reverse_location_data"]) or parse_reverse_location_blob(
                row["place_annotation_data"]
            )
            if not display_name:
                continue
            results.append(
                {
                    "asset_uuid": row["asset_uuid"],
                    "original_path": str(self._original_path(row["directory"], row["filename"])),
                    "location_display_name": display_name,
                    "source": "apple_photos",
                }
            )
        return results

    def iter_image_asset_resources(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """列出 Apple Photos 图片资产，并选择可用于视觉打标的本地文件。

        优先使用 `originals/` 真实原图；如果原图处于 iCloud 冷数据且本地不存在，
        则使用 Photos 已落地的 `resources/derivatives/` 预览图。该预览图覆盖全量
        图片资产，足够用于语义打标，同时不需要 PhotoKit/TCC 授权。
        """

        derivative_index = self._build_derivative_index()
        where = ["a.ZDIRECTORY IS NOT NULL", "a.ZFILENAME IS NOT NULL"]
        with self.connect_readonly() as connection:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(ZASSET)").fetchall()}
            if "ZTRASHEDSTATE" in columns:
                where.append("COALESCE(a.ZTRASHEDSTATE, 0) = 0")
            if "ZKIND" in columns:
                where.append("COALESCE(a.ZKIND, 0) = 0")

            query = f"""
                SELECT
                    a.Z_PK AS asset_pk,
                    a.ZUUID AS asset_uuid,
                    a.ZDIRECTORY AS directory,
                    a.ZFILENAME AS filename
                FROM ZASSET a
                WHERE {" AND ".join(where)}
                ORDER BY a.Z_PK ASC
            """
            parameters: tuple[Any, ...] = ()
            if limit is not None:
                query += " LIMIT ?"
                parameters = (int(limit),)
            rows = connection.execute(query, parameters).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            original_path = self._original_path(row["directory"], row["filename"])
            if original_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            asset_uuid = str(row["asset_uuid"] or "").upper()
            derivative_path = derivative_index.get(asset_uuid)
            source_path = original_path if is_real_local_file(original_path) else derivative_path
            if source_path is None or not is_real_local_file(source_path):
                continue
            results.append(
                {
                    "asset_pk": int(row["asset_pk"]),
                    "asset_uuid": row["asset_uuid"],
                    "asset_id": stable_asset_id(row["asset_uuid"]),
                    "local_identifier": f"{row['asset_uuid']}/L0/001",
                    "original_path": str(original_path.resolve()),
                    "source_path": str(Path(source_path).resolve()),
                    "source_kind": "original" if Path(source_path).resolve() == original_path.resolve() else "derivative",
                    "source": "apple_photos",
                }
            )
        return results

    def _original_path(self, directory: str, filename: str) -> Path:
        return (self.photo_library_path / "originals" / str(directory) / str(filename)).resolve()

    def _build_derivative_index(self) -> dict[str, Path]:
        derivatives_root = self.photo_library_path / "resources" / "derivatives"
        if not derivatives_root.exists():
            return {}
        candidates: dict[str, Path] = {}
        for path in derivatives_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            asset_uuid = path.name.split("_", 1)[0].split(".", 1)[0].upper()
            if not asset_uuid:
                continue
            current = candidates.get(asset_uuid)
            if current is None or path.stat().st_size > current.stat().st_size:
                candidates[asset_uuid] = path.resolve()
        return candidates

    def _entity_type(self, detection_type: Any) -> str:
        # Apple 没有公开保证这些私有枚举的语义；先保守标为 person。
        return "person"

    def _person_uuid_expression(self, connection: sqlite3.Connection) -> str:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(ZPERSON)").fetchall()}
        if "ZUUID" in columns:
            return "p.ZUUID"
        if "ZPERSONUUID" in columns:
            return "p.ZPERSONUUID"
        return "CAST(p.Z_PK AS TEXT)"


class ApplePhotosPeopleCache:
    """Apple Photos 人物/宠物聚类的只读缓存。

    macOS 的 TCC 权限会导致 launchd 后台服务无法直接读取 Photos.sqlite。
    因此由有权限的终端进程同步一次缓存，Web 后端稳定读取该 JSON。
    """

    def __init__(self, cache_path: str | os.PathLike[str] = Path("data") / "apple_people_cache.json") -> None:
        self.cache_path = Path(cache_path).expanduser()

    def exists(self) -> bool:
        return self.cache_path.exists() and self.cache_path.is_file()

    def list_named_people(self) -> list[dict[str, Any]]:
        return list(self._read_payload().get("people", []))

    def iter_person_asset_links(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        links = list(self._read_payload().get("links", []))
        if limit is not None:
            return links[: int(limit)]
        return links

    def iter_image_asset_resources(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        assets = list(self._read_payload().get("assets", []))
        if limit is not None:
            return assets[: int(limit)]
        return assets

    def write_snapshot(
        self,
        *,
        people: list[dict[str, Any]],
        links: list[dict[str, Any]],
        assets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "people": [self._with_source(person) for person in people],
            "links": [self._with_source(link) for link in links],
            "assets": [self._with_source(asset) for asset in (assets or [])],
        }
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "people_count": len(payload["people"]),
            "link_count": len(payload["links"]),
            "asset_count": len(payload["assets"]),
            "cache_path": str(self.cache_path.resolve()),
        }

    def _read_payload(self) -> dict[str, Any]:
        if not self.exists():
            return {"version": 1, "people": [], "links": []}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[LIMB-Ark] Apple Photos 人物缓存读取失败: {exc}", flush=True)
            return {"version": 1, "people": [], "links": []}
        if not isinstance(payload, dict):
            return {"version": 1, "people": [], "links": [], "assets": []}
        payload.setdefault("people", [])
        payload.setdefault("links", [])
        payload.setdefault("assets", [])
        return payload

    def _with_source(self, row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "source": "apple_photos"}


class PhotoKitOriginalPrefetcher:
    """PhotoKit 高清原图后台预热器。

    状态机第一层永远先做本地物理文件检查。只有文件不存在或为空时，
    才允许调用 PhotoKit 并设置 networkAccessAllowed=True。
    """

    def __init__(
        self,
        *,
        path_resolver: PathResolver | None = None,
        request_original: OriginalRequester | None = None,
    ) -> None:
        self.path_resolver = path_resolver or self._default_path_resolver
        self.request_original = request_original or self._request_original_with_photokit

    async def prefetch_originals_if_needed(self, identifiers: list[str]) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for identifier in [item for item in identifiers if item]:
            path = self.path_resolver(identifier)
            if is_real_local_file(path):
                states[identifier] = {
                    "state": "local-ready-skip",
                    "original_path": str(Path(path).expanduser()),
                    "asset_id": stable_asset_id(identifier),
                }
                continue

            try:
                result = self.request_original(identifier)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as exc:
                error = str(exc)
                state = "photokit-asset-missing-skip" if "PhotoKit 未找到资产" in error else "photokit-error-skip"
                LOGGER.warning("PhotoKit original prefetch skipped for %s: %s", identifier, error)
                states[identifier] = {
                    "state": state,
                    "original_path": str(path) if path else None,
                    "asset_id": stable_asset_id(identifier),
                    "error": error,
                }
                continue
            states[identifier] = {
                "state": str(result or "photokit-requested"),
                "original_path": str(path) if path else None,
                "asset_id": stable_asset_id(identifier),
            }
        return states

    def _default_path_resolver(self, identifier: str) -> str | None:
        """默认无法从 localIdentifier 可靠反推 originals 文件。

        真正 PhotoKit 索引会把 original_path 写入 SQLite；ark_main 会传入数据库 resolver。
        """

        return None

    async def _request_original_with_photokit(self, identifier: str) -> str:
        await asyncio.to_thread(self._request_original_with_photokit_sync, identifier)
        return "photokit-requested"

    def _request_original_with_photokit_sync(self, identifier: str) -> None:
        try:
            import Photos  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "缺少 PyObjC PhotoKit 依赖，请执行: python3 -m pip install pyobjc-framework-Photos"
            ) from exc

        assets = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_([identifier], None)
        if assets.count() == 0:
            raise RuntimeError(f"PhotoKit 未找到资产: {identifier}")
        asset = assets.objectAtIndex_(0)
        options = Photos.PHImageRequestOptions.alloc().init()
        options.setNetworkAccessAllowed_(True)
        options.setSynchronous_(False)

        manager = Photos.PHImageManager.defaultManager()

        def handler(data, data_uti, orientation, info):  # noqa: ANN001
            return None

        manager.requestImageDataAndOrientationForAsset_options_resultHandler_(asset, options, handler)


async def prefetch_originals_if_needed(
    identifiers: list[str],
    *,
    path_resolver: PathResolver | None = None,
    request_original: OriginalRequester | None = None,
) -> dict[str, dict[str, Any]]:
    prefetcher = PhotoKitOriginalPrefetcher(path_resolver=path_resolver, request_original=request_original)
    return await prefetcher.prefetch_originals_if_needed(identifiers)
