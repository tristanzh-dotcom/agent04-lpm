"""兼容旧运维入口。

历史 launchd 配置曾使用 `backend.main:app` 启动 8004。
当前真实实现已经迁移到 `backend.ark_main:app`，这里保留轻量导出，避免旧守护配置
因为模块不存在而导致后端掉线。
"""

from backend.ark_main import app

