#!/usr/bin/env bash
set -euo pipefail

# 项目4不再单独管理 8004。停止工作台时关闭本地 Web 发布平台；
# 由平台启动的 Agent04 后端子进程会随 server.close() 进入清理流程。

WEB_LABEL="com.tz.agent-web-service"
LEGACY_BACKEND_LABEL="com.tz.limb-photo-backend"

if launchctl print "gui/$(id -u)/$LEGACY_BACKEND_LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LEGACY_BACKEND_LABEL" || true
fi

if launchctl print "gui/$(id -u)/$WEB_LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$WEB_LABEL" || true
fi

legacy_plist="$HOME/Library/LaunchAgents/$LEGACY_BACKEND_LABEL.plist"
if [[ -f "$legacy_plist" ]]; then
  mv "$legacy_plist" "$legacy_plist.retired-$(date +%Y%m%d%H%M%S)"
fi

cat <<'EOF'
==================================================
本地 Web 发布平台已收闸
==================================================
说明: Agent04 的独立 uvicorn LaunchAgent 已退役。
如需恢复工作台，请执行 ./start_workspace.sh
==================================================
EOF
