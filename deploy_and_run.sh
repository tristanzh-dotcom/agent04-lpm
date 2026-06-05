#!/usr/bin/env bash
set -euo pipefail

# LIMB Ark 专属 Endpoint 通道生产首航脚本。
# 执行顺序：
# 1. 强固 Python 依赖
# 2. 校验 Ark / DeepSeek / 本地路径配置
# 3. 运行 0.002 元级别连通性热测试
# 4. 热测试通过后启动全量 Apple Photos 打标任务

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

ARK_API_KEY="${ARK_API_KEY:?请先在环境变量中设置 ARK_API_KEY}"
ARK_ENDPOINT_ID="${ARK_ENDPOINT_ID:?请先在环境变量中设置 ARK_ENDPOINT_ID}"
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
export ARK_API_KEY ARK_ENDPOINT_ID DEEPSEEK_API_KEY
export LIMB_PHOTO_LIBRARY_ROOT="/Users/tristanzh/Pictures/Photos Library.photoslibrary"
export LIMB_PHOTO_ROOT="$LIMB_PHOTO_LIBRARY_ROOT/originals"
export LIMB_ARK_DB="data/limb_ark.sqlite3"
export LIMB_THUMBNAIL_DIR=".cache/thumbnails"

mkdir -p "$(dirname "$LIMB_ARK_DB")" "$LIMB_THUMBNAIL_DIR"

echo "========== LIMB Ark Endpoint 首航部署 =========="
echo "项目目录: $PROJECT_ROOT"
echo "相册目录: $LIMB_PHOTO_ROOT"
echo "数据库: $LIMB_ARK_DB"
echo "缩略图缓存: $LIMB_THUMBNAIL_DIR"
echo "Ark Endpoint: $ARK_ENDPOINT_ID"
echo "================================================"

echo "[1/4] 正在强固 Python 运行依赖..."
python3 -m pip install --upgrade "volcengine-python-sdk[ark]" jieba tqdm fastapi uvicorn pillow \
  pyobjc-core==10.3.2 pyobjc-framework-Cocoa==10.3.2 \
  pyobjc-framework-Photos==10.3.2 pyobjc-framework-CoreLocation==10.3.2

echo "[2/4] 正在校验 Apple Photos originals 路径..."
if [[ ! -d "$LIMB_PHOTO_ROOT" ]]; then
  echo "[FAILED] 找不到相册 originals 目录: $LIMB_PHOTO_ROOT" >&2
  echo "请确认照片图库名称是否为：Photos Library.photoslibrary，或手动改成你的真实 .photoslibrary 路径。" >&2
  exit 1
fi

echo "[3/4] 正在进行 0.002 元的专属 Endpoint 通道热测试..."
python3 tests/test_ark_connectivity.py

echo "[4/4] 连通性测试通过，合闸启动全量相册打标任务..."
python3 run_index_pipeline.py "$LIMB_PHOTO_ROOT" --concurrency 2 --max-retries 5
