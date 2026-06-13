### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_agent04_web_publish_20260613.md`。
1. 请将本对话的逻辑分支锁定为：【Agent04 Web发布移交】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# Agent04 Web发布移交 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

Agent04 的业务根在 `/Users/tristanzh/agent/Local-photo-model`，Web 发布宿主在 `/Users/tristanzh/agent/web`。本次归档只移交“应由 Web 工作流统一治理”的发布层内容：Agent04 静态前端交互、Web 发布契约/文档、Web 壳状态与跨 Agent 回归验证。

业务能力本身仍属于 Local-photo-model：Apple Photos 读取、本地人脸向量索引、`photo_face_index.pkl`、SQLite 检索、`8004` FastAPI 后端。Web 工作流不应重扫照片、不应改人脸向量结构、不应写入模型密钥。

本轮分类：

- `Agent Feature Change`：后台人脸补扫 job、批量落盘、`/api/face/reindex/job` 后端状态接口。
- `Agent Publishing Change`：`frontend/agent04/app.js` 中“补扫相册人脸索引”按钮从等待长 POST 改为启动任务后轮询状态。
- `Shared Platform Change`：未实施。没有修改 shared 侧边栏，也没有修改 `/Users/tristanzh/agent/web` 的 Agent04 文件。

## 今日完成事项

- 已确认当前 Web 侧 Agent04 contract：
  - `/Users/tristanzh/agent/web/config/agents/agent04.contract.json`
  - `/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md`
- 当前项目内与 Web 发布相关的实际 diff：
  - `/Users/tristanzh/agent/Local-photo-model/frontend/agent04/app.js`
    - 新增 `faceReindexJobApi = /api/face/reindex/job`。
    - 新增 `formatFaceReindexJobStatus(job)`，统一展示 `started/running/completed/failed/interrupted` 状态。
    - 新增 `pollFaceReindexJob()`，每 1200ms 轮询后台人脸补扫 job。
    - “补扫相册人脸索引”按钮不再依赖同步 POST 返回 `indexed/skipped/failed`，而是 `POST /api/face/reindex` 后轮询 job 状态。
  - `/Users/tristanzh/agent/Local-photo-model/tests/test_frontend_agent04.py`
    - 新增静态测试 `test_face_reindex_button_starts_background_job_and_polls_status`，锁定前端必须使用 job endpoint 和轮询逻辑。
- 当前会话早前已涉及的 Web 发布层事实，也应由 Web 工作流继承：
  - `frontend/agent04/app.js` 已使用 `preview_url` 作为卡片和 Lightbox 的优先图片源。
  - `frontend/agent04/index.html` 曾更新静态脚本版本以刷新 Agent04 静态前端缓存。
  - Web 发布页必须继续通过 `/agent04-static/index.html` 嵌入 Agent04 静态前端。
  - 图片首屏展示不应依赖 PhotoKit 原图预热接口；卡片图片应优先使用浏览器可直接渲染的 `preview_url` / `/photos/...`。
- 当前 `/Users/tristanzh/agent/web` 检查结果：
  - 未发现 Agent04 指定文件的本轮 diff。
  - Web 工作区存在大量其他 Agent dirty 文件，与本次 Agent04 移交无关，接手时不要混入。

## 已作出的关键决策

- 放弃“点击补扫后等待一次长请求完成”的 Web 交互。原因：本地人脸模型扫描会占用 CPU，长同步请求会让页面无状态、无进度，并可能被 Web 管理器健康检查误判。
- 采用“启动任务 + 状态轮询”的发布层交互：
  - `POST http://127.0.0.1:8004/api/face/reindex` 只负责提交任务并快速返回。
  - `GET http://127.0.0.1:8004/api/face/reindex/job` 负责读取进度和最终状态。
- Web 前端只展示状态，不拥有人脸补扫业务逻辑。
- 不在 Web 工作流里直接降低人脸匹配阈值来增加“小菲”结果数。结果少的核心原因是旧 `photo_face_index.pkl` 只覆盖约 1270 条路径，不是展示格式问题。
- 不修改 shared 侧边栏、不修改 Agent02/03/05/06 布局、不修改 Web 全局主题。

## 未解决的风险/报错

- 需要 Web 工作流更新 `/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md` 的 API 合约：
  - 应新增 `POST http://127.0.0.1:8004/api/face/reindex`。
  - 应新增 `GET http://127.0.0.1:8004/api/face/reindex/job`。
  - 当前文档仍保留旧的 `POST /api/register_member` 描述，需由 Web 工作流核对是否已经过时。
- 需要 Web 工作流判断是否要调整 Web 后端 Agent04 管理器策略：
  - 当前问题暴露出 `8004` 后端在 CPU-heavy 任务期间可能被健康检查重启。
  - 本轮业务侧已把补扫改为后台 job 并批量落盘，但 Web 统一管理层仍应确认健康检查超时、重启策略、状态缓存是否适合本地模型任务。
- `tests/test_frontend_agent04.py` 全量运行仍有 3 个 Lightbox 布局断言失败：
  - `test_lightbox_back_button_lives_in_inspector_not_over_photo`
  - `test_lightbox_keeps_photo_and_inspector_visually_separated`
  - `test_lightbox_primary_actions_are_in_inspector_header`
  这些失败与本次人脸补扫轮询无关，属于 Web/视觉布局治理范围，应由 Web 工作流单独处理。
- 本轮没有替 TZ 触发全量“补扫相册人脸索引”。修复完成后当前 job 状态是 `idle`，需要 TZ 在页面点击后才会重新扫描。

## 下一步行动

1. Web 工作流接手后先读取边界文件：

```bash
sed -n '1,220p' /Users/tristanzh/agent/Local-photo-model/AGENTS.md
sed -n '1,220p' /Users/tristanzh/agent/web/config/agents/agent04.contract.json
sed -n '1,260p' /Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md
```

2. 核对 Agent04 静态前端发布层 diff：

```bash
cd /Users/tristanzh/agent/Local-photo-model
git diff -- frontend/agent04/app.js tests/test_frontend_agent04.py
```

3. 在 Web 文档/契约中补充新的人脸补扫 job API，并确认不触碰 shared 侧边栏。

4. 运行当前已通过的 Agent04 发布层聚焦测试：

```bash
cd /Users/tristanzh/agent/Local-photo-model
python3 -m pytest tests/test_frontend_agent04.py::Agent04FrontendTests::test_face_reindex_button_starts_background_job_and_polls_status -q
```

5. 运行后端功能侧验证，确保 Web 发布层更新没有破坏 Agent04 业务接口：

```bash
cd /Users/tristanzh/agent/Local-photo-model
python3 -m pytest tests/test_ark_main.py tests/test_ark_index_engine.py tests/test_run_index_pipeline.py tests/test_face_engine.py tests/test_ark_face_api.py -q
curl -sS --max-time 5 http://127.0.0.1:8004/api/health
curl -sS --max-time 5 http://127.0.0.1:8004/api/face/reindex/job
```

6. 如果 Web 工作流要处理 Lightbox 失败，先单独建立 Web 视觉治理 SDD/TDD，不要混入本次人脸补扫 job 交互。
