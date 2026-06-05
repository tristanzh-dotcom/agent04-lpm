#!/usr/bin/env bash
set -euo pipefail

# LIMB Apple Photos 全量索引后台启动脚本。
# 只读取 deploy_and_run.sh 的 export 配置，不执行依赖安装和连通性测试。

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="$PROJECT_ROOT/deploy_and_run.sh"
RUNTIME_DIR="$PROJECT_ROOT/.cache/workspace"
PID_FILE="$RUNTIME_DIR/full-index.pid"
LATEST_LOG="$RUNTIME_DIR/full-index.latest.log"

mkdir -p "$RUNTIME_DIR" "$PROJECT_ROOT/logs"
cd "$PROJECT_ROOT"

if [[ ! -f "$DEPLOY_SCRIPT" ]]; then
  echo "[FAILED] 找不到 deploy_and_run.sh，无法继承生产环境变量。" >&2
  exit 1
fi

while IFS= read -r line; do
  case "$line" in
    ARK_API_KEY=*|\
    ARK_ENDPOINT_ID=*|\
    DEEPSEEK_API_KEY=*|\
    export\ ARK_API_KEY=*|\
    export\ ARK_ENDPOINT_ID=*|\
    export\ DEEPSEEK_API_KEY=*|\
    export\ LIMB_PHOTO_LIBRARY_ROOT=*|\
    export\ LIMB_PHOTO_ROOT=*|\
    export\ LIMB_ARK_DB=*|\
    export\ LIMB_THUMBNAIL_DIR=*|\
    export\ ARK_API_KEY\ ARK_ENDPOINT_ID\ DEEPSEEK_API_KEY)
      eval "$line"
      ;;
  esac
done < "$DEPLOY_SCRIPT"

export PYTHONUNBUFFERED=1
export LIMB_PHOTO_ROOT="${LIMB_PHOTO_ROOT:-/Users/tristanzh/Pictures/Photos Library.photoslibrary/originals}"
export LIMB_ARK_DB="${LIMB_ARK_DB:-data/limb_ark.sqlite3}"
export LIMB_THUMBNAIL_DIR="${LIMB_THUMBNAIL_DIR:-.cache/thumbnails}"

if [[ ! -d "$LIMB_PHOTO_ROOT" ]]; then
  echo "[FAILED] 找不到 Apple Photos originals 目录: $LIMB_PHOTO_ROOT" >&2
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "[FAILED] 全量索引任务已在运行，PID=$old_pid。" >&2
    echo "日志: $(readlink "$LATEST_LOG" 2>/dev/null || echo "$LATEST_LOG")" >&2
    exit 1
  fi
fi

log_path="$PROJECT_ROOT/logs/limb_full_index_$(date +%Y%m%d_%H%M%S).log"
ln -sf "$log_path" "$LATEST_LOG"

echo "[LIMB] 启动 Apple Photos 全量索引后台任务..."
echo "[LIMB] Photo root: $LIMB_PHOTO_ROOT"
echo "[LIMB] Database: $LIMB_ARK_DB"
echo "[LIMB] Log: $log_path"

nohup python3 -u run_index_pipeline.py "$LIMB_PHOTO_ROOT" --concurrency 2 --max-retries 5 >"$log_path" 2>&1 &
pid="$!"
echo "$pid" > "$PID_FILE"

sleep 2
if ps -p "$pid" >/dev/null 2>&1; then
  echo "[OK] 全量索引已启动，PID=$pid"
  echo "[OK] 监控日志: tail -f $log_path"
else
  echo "[FAILED] 全量索引启动后立即退出，请查看日志: $log_path" >&2
  exit 1
fi
