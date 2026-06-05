from __future__ import annotations

import argparse
import os

from backend.ark_index_engine import ArkPhotoIndexDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description="给 LIMB Ark 旧照片索引回填 EXIF 拍摄时间和 GPS 信息")
    parser.add_argument("--db", default=os.environ.get("LIMB_ARK_DB", "data/limb_ark.sqlite3"), help="SQLite 索引库路径")
    parser.add_argument("--limit", type=int, default=None, help="只回填最近 N 条缺失记录，默认全量")
    args = parser.parse_args()

    database = ArkPhotoIndexDatabase(args.db)
    updated = database.backfill_capture_metadata(limit=args.limit)
    print(f"[LIMB-Ark] EXIF 元数据回填完成：更新 {updated} 条记录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
