from __future__ import annotations

import argparse
import json
import os

from backend.apple_photos_bridge import ApplePhotosPeopleBridge


def main() -> int:
    parser = argparse.ArgumentParser(description="只读探测 Apple Photos 已命名人物/宠物聚类")
    parser.add_argument(
        "photo_library",
        nargs="?",
        default=os.environ.get("LIMB_PHOTO_LIBRARY_ROOT", "/Users/tristanzh/Pictures/Photos Library.photoslibrary"),
        help="Photos Library.photoslibrary 路径",
    )
    parser.add_argument("--limit-links", type=int, default=10, help="展示前 N 条人物-照片映射样例")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出，便于后续脚本消费")
    args = parser.parse_args()

    bridge = ApplePhotosPeopleBridge(args.photo_library)
    people = bridge.list_named_people()
    links = bridge.iter_person_asset_links(limit=args.limit_links)

    payload = {
        "photo_library": str(bridge.photo_library_path),
        "photos_db": str(bridge.photos_db_path),
        "named_people_count": len(people),
        "people": people,
        "sample_links": links,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("========== LIMB Apple Photos 人物/宠物继承探针 ==========")
    print(f"图库: {payload['photo_library']}")
    print(f"数据库: {payload['photos_db']}")
    print(f"已命名人物/宠物数量: {len(people)}")
    print("\n-- 已命名聚类 --")
    for item in people:
        print(f"- {item['label']} | 照片 {item['asset_count']} | 脸/识别样本 {item['face_count']} | source={item['source']}")
    print("\n-- 映射样例 --")
    for item in links:
        print(f"- {item['label']} -> {item['original_path']} | quality={item['quality']:.3f}")
    print("========================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
