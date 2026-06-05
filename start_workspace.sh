#!/usr/bin/env bash
set -euo pipefail

# 项目4运行入口已收口到本地 Web 发布平台。
# 本脚本只负责拉起/重启 3000 平台服务；Agent04 的 8004 FastAPI
# 后端由 /Users/tristanzh/agent/web/server.mjs 在需要时托管启动。

WEB_ROOT="/Users/tristanzh/agent/web"
WEB_LABEL="com.tz.agent-web-service"
WEB_PLIST="$WEB_ROOT/ops/$WEB_LABEL.plist"
INSTALLED_PLIST="$HOME/Library/LaunchAgents/$WEB_LABEL.plist"

if [[ ! -f "$WEB_PLIST" ]]; then
  echo "[FAILED] 找不到 Web 发布平台 LaunchAgent 模板: $WEB_PLIST" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$WEB_ROOT/.logs"
cp "$WEB_PLIST" "$INSTALLED_PLIST"

if launchctl print "gui/$(id -u)/$WEB_LABEL" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$(id -u)/$WEB_LABEL"
else
  launchctl bootstrap "gui/$(id -u)" "$INSTALLED_PLIST"
fi

for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:3000/agent04" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! curl -fsS "http://127.0.0.1:3000/agent04" >/dev/null 2>&1; then
  echo "[FAILED] 本地 Web 发布平台未就绪，请查看 $WEB_ROOT/.logs/agent-web-server.err.log" >&2
  exit 1
fi

cat <<'EOF'
==================================================
智能相册工作台已通过本地 Web 发布平台合闸
==================================================
前端入口: http://127.0.0.1:3000/agent04
平台状态: http://127.0.0.1:3000/api/agent04/status
说明: 8004 后端由 3000 平台按需托管，不再使用独立 uvicorn LaunchAgent。
==================================================
EOF
