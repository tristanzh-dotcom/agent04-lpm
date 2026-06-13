### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_agent04_completion_20260613.md`。
1. 请将本对话的逻辑分支锁定为：【Agent04 功能完成收工】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# Agent04 功能完成收工 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

Agent04 的目标是在本机 Apple Photos 资产上提供稳定、低成本、隐私边界清晰的本地图像语义检索与人物检索。业务能力边界在 `/Users/tristanzh/agent/Local-photo-model`，Web 发布宿主在 `/Users/tristanzh/agent/web`。

本轮核心问题不是 UI 格式，而是功能与性能链路：`小菲` 搜索结果长期只有 11 条，是因为手动人物向量库的相册人脸索引只覆盖旧的少量路径；补扫相册人脸索引原先是同步长请求，CPU-heavy 扫描期间可能被 Web 管理器健康检查判定异常并重启，导致最终 pickle 不落盘。

当前结论：Agent04 功能侧已完成主要修复，补扫改成后台 job + 状态轮询 + 批量落盘；实际搜索 `小菲` 已从 11 条提升到 199 条。仍有一个收尾风险：最新 live job 状态为 `interrupted`，说明上一次补扫进程在 7040/14959 处被重启或退出，需要后续确认是否继续补扫剩余图片。

## 今日完成事项

- 修复差量更新与 stale 清理：
  - `/Users/tristanzh/agent/Local-photo-model/backend/ark_main.py`
    - 增加 stale-only 差量清理路径。
    - 差量管线结束后执行 stale 清理并记录 `stale_removed`。
    - Apple Photos asset 差量匹配更稳，避免旧索引长期残留。
  - `/Users/tristanzh/agent/Local-photo-model/backend/ark_index_engine.py`
    - SQLite 连接增加 `timeout=10.0` 与 `PRAGMA busy_timeout = 10000`，降低并发读写锁冲突。
  - `/Users/tristanzh/agent/Local-photo-model/run_index_pipeline.py`
    - 非关键地点 display-name 回填遇到 database locked 时跳过，不让整条差量更新失败。
- 修复人脸补扫覆盖范围：
  - `/Users/tristanzh/agent/Local-photo-model/backend/face_engine.py`
    - 新增 `scan_photo_paths(image_paths)`，支持直接扫描 Apple Photos asset `source_path`。
    - `scan_photo_directory()` 复用 `scan_photo_paths()`。
  - `/Users/tristanzh/agent/Local-photo-model/backend/ark_main.py`
    - `reindex_faces()` / `start_face_reindex()` 在没有显式 `photo_root` 时优先扫描 Apple Photos asset `source_path`，而不是只扫 `originals`。
- 修复人脸补扫长任务设计：
  - `/Users/tristanzh/agent/Local-photo-model/backend/ark_main.py`
    - 新增 `start_face_reindex()`，后台线程执行补扫。
    - 新增 `face_reindex_job_status()`，读取 `data/face_reindex_job.json`。
    - 新增 job 状态：`started/running/completed/failed/interrupted/idle`。
    - 如果 job 文件中 PID 与当前进程不同，将旧 `running` 判定为 `interrupted`，避免 UI 永久显示运行中。
  - `/Users/tristanzh/agent/Local-photo-model/backend/face_engine.py`
    - `scan_photo_paths()` 支持 `progress_callback` 和 `save_every`。
    - 每批保存 `photo_face_index.pkl`，避免进程中断后全部丢失。
  - `/Users/tristanzh/agent/Local-photo-model/frontend/agent04/app.js`
    - `补扫相册人脸索引` 按钮改为 `POST /api/face/reindex` 提交任务，然后轮询 `GET /api/face/reindex/job`。
- Web 发布移交：
  - 已生成 `/Users/tristanzh/agent/Local-photo-model/HANDOVER_agent04_web_publish_20260613.md`，专门归档需要 Web 工作流接管的发布层改动。
- 清理与上下文隔离：
  - 执行过 `vibe clean`，删除缓存并将非当天旧 handover 移入 `_archive_legacy/`。
  - 执行过 `context clean`，激活逻辑 context filter；没有删除或移动文件。
- 关键测试已补充/更新：
  - `/Users/tristanzh/agent/Local-photo-model/tests/test_ark_main.py`
  - `/Users/tristanzh/agent/Local-photo-model/tests/test_ark_index_engine.py`
  - `/Users/tristanzh/agent/Local-photo-model/tests/test_run_index_pipeline.py`
  - `/Users/tristanzh/agent/Local-photo-model/tests/test_face_engine.py`
  - `/Users/tristanzh/agent/Local-photo-model/tests/test_ark_face_api.py`
  - `/Users/tristanzh/agent/Local-photo-model/tests/test_frontend_agent04.py`

## 已作出的关键决策

- 不通过降低 `LIMB_FACE_THRESHOLD` 来伪造更多 `小菲` 结果。根因是相册人脸索引覆盖不足，不是阈值过严。
- 不继续使用同步长请求做“补扫相册人脸索引”。本地人脸模型扫描是长任务，必须有后台 job、状态读取和中断恢复语义。
- 不让 Web 发布层拥有人脸索引业务逻辑。Web 只负责展示状态与触发后端 API；Apple Photos 读取、人脸 embedding、SQLite 索引仍属于 Local-photo-model。
- 不把 `/api/assets/{asset_id}/image` 当成卡片首屏图片源。卡片展示必须优先用可直接渲染的 `preview_url` / `/photos/...`。
- 不修改 shared 侧边栏；所有 Web 可见改动都限定为 Agent04 静态前端与对应测试，Web 平台治理另交给 Web 工作流。

## 未解决的风险/报错

- 当前 live 后端健康正常：

```text
GET http://127.0.0.1:8004/api/health -> {"status":"ok"}
```

- 当前 live 人脸补扫 job 状态不是 `completed`，而是：

```text
status=interrupted
source=apple_photos_assets
total=14959
processed=7040
summary.indexed=6636
summary.skipped=398
summary.failed=6
message=上一次人脸补扫进程已重启或退出，请重新点击补扫。
```

- 即使 job 中断，批量落盘已生效：

```text
data/photo_face_index.pkl size=12265728
mtime=2026-06-13T16:03:32.315222
```

- 当前搜索 `小菲` 已返回 199 条，说明旧的 11 条问题已实质缓解；但因为补扫只处理到 7040/14959，完整相册覆盖仍未完成。
- `tests/test_frontend_agent04.py` 全量仍有 3 个 Lightbox 布局断言失败，和本次人脸补扫功能无关，已归档给 Web 工作流处理：
  - `test_lightbox_back_button_lives_in_inspector_not_over_photo`
  - `test_lightbox_keeps_photo_and_inspector_visually_separated`
  - `test_lightbox_primary_actions_are_in_inspector_header`
- 当前工作区状态中还有需要后续整理的未跟踪/运行态文件：
  - `data/` 下包含 SQLite、pickle、job json/log 等运行态数据。
  - `docs/superpowers/specs/2026-06-13-agent04-person-register-order-design.md` 为未跟踪设计文档。
  - `tests/test_query_sandbox.db` 与 `tests/test_query_sandbox.db-journal` 为未跟踪测试 SQLite 文件，后续应确认是否清理或加入测试临时目录策略。
- Vibe Clean 将旧 handover 移入 `_archive_legacy/`，因此 git status 中会出现旧 `HANDOVER_*.md` 删除状态和 `_archive_legacy/` 内文件状态；不要误判为业务代码丢失。

## 下一步行动

1. 明天接手先读取本文件和边界文件：

```bash
sed -n '1,260p' /Users/tristanzh/agent/Local-photo-model/HANDOVER_agent04_completion_20260613.md
sed -n '1,220p' /Users/tristanzh/agent/Local-photo-model/AGENTS.md
sed -n '1,220p' /Users/tristanzh/agent/GLOBAL_MODEL_ROUTING_RECORD.md
```

2. 复核 live 状态：

```bash
curl -sS --max-time 5 http://127.0.0.1:8004/api/health
curl -sS --max-time 5 http://127.0.0.1:8004/api/face/reindex/job | python3 -m json.tool
```

3. 复核 `小菲` 搜索数量：

```bash
python3 - <<'PY'
import json, urllib.request
payload=json.dumps({"query":"小菲","limit":200}, ensure_ascii=False).encode("utf-8")
req=urllib.request.Request(
    "http://127.0.0.1:8004/api/search",
    data=payload,
    headers={"content-type":"application/json"},
)
with urllib.request.urlopen(req, timeout=20) as resp:
    rows=json.load(resp)
print(len(rows))
PY
```

4. 如果 TZ 要完整补扫剩余人脸索引，在页面点击“补扫相册人脸索引”，然后观察：

```bash
watch -n 2 'curl -sS http://127.0.0.1:8004/api/face/reindex/job | python3 -m json.tool'
```

5. 若再次出现 `interrupted`，下一步不要改阈值，优先排查：
   - 8004 后端是否被 Web 管理器重启。
   - 后台 job 是否需要独立 worker 进程而非 uvicorn 进程内 daemon thread。
   - Web 健康检查超时和重启策略是否仍对 CPU-heavy 本地模型任务不友好。

6. 功能侧回归验证命令：

```bash
cd /Users/tristanzh/agent/Local-photo-model
python3 -m pytest tests/test_ark_main.py tests/test_ark_index_engine.py tests/test_run_index_pipeline.py tests/test_face_engine.py tests/test_ark_face_api.py -q
python3 -m pytest tests/test_frontend_agent04.py::Agent04FrontendTests::test_face_reindex_button_starts_background_job_and_polls_status -q
python3 -m compileall backend run_index_pipeline.py tests
```
