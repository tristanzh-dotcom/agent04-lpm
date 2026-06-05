from __future__ import annotations

import argparse
import os
from pathlib import Path

from backend.apple_photos_bridge import ApplePhotosPeopleBridge, ApplePhotosPeopleCache


def resolve_library_path(value: str | os.PathLike[str] | None) -> Path:
    """把 originals 或 .photoslibrary 路径统一归一为图库根目录。"""

    if value:
        candidate = Path(value).expanduser().resolve()
    else:
        candidate = Path("~/Pictures/照片图库.photoslibrary").expanduser().resolve()
        if not candidate.exists():
            candidate = Path("~/Pictures/Photos Library.photoslibrary").expanduser().resolve()
    if candidate.name == "originals" and candidate.parent.name.endswith(".photoslibrary"):
        return candidate.parent
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 Apple Photos 已命名人物/宠物到 LIMB 只读缓存。")
    parser.add_argument(
        "photo_library",
        nargs="?",
        default=os.environ.get("LIMB_PHOTO_ROOT") or os.environ.get("ARK_PHOTO_ROOT"),
        help="Apple Photos 图库根目录，或其中的 originals 目录。",
    )
    parser.add_argument(
        "--cache-path",
        default=os.environ.get("LIMB_APPLE_PEOPLE_CACHE", "data/apple_people_cache.json"),
        help="输出缓存路径，默认 data/apple_people_cache.json。",
    )
    parser.add_argument("--limit-links", type=int, default=None, help="调试用：只同步前 N 条人物-照片映射。")
    args = parser.parse_args()

    library_path = resolve_library_path(args.photo_library)
    bridge = ApplePhotosPeopleBridge(library_path)
    cache = ApplePhotosPeopleCache(args.cache_path)

    people = bridge.list_named_people()
    links = bridge.iter_person_asset_links(limit=args.limit_links)
    assets = bridge.iter_image_asset_resources()
    summary = cache.write_snapshot(people=people, links=links, assets=assets)

    print("[LIMB-Ark] Apple Photos 人物缓存同步完成")
    print(f"  图库: {library_path}")
    print(f"  人物/宠物: {summary['people_count']} 个")
    print(f"  人物-照片映射: {summary['link_count']} 条")
    print(f"  图片资产: {summary['asset_count']} 张")
    print(f"  缓存: {summary['cache_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
