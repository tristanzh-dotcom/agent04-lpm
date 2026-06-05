### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_agent04_photo_display_20260602.md`。
1. 请将本对话的逻辑分支锁定为：【Agent04 照片显示修复】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# Agent04 照片显示修复 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

Agent04 的核心目标是在本机 Apple Photos 资产上提供稳定、低成本、隐私边界清晰的语义检索。照片展示链路必须使用浏览器可直接渲染的本地图片 URL，不能依赖可能缺失的缩略图缓存，也不能把会返回 202 JSON 的 PhotoKit 原图预热接口当成 `<img>` 资源。

当前活跃规则以本项目当前代码、测试、`/Users/tristanzh/agent/Local-photo-model/AGENTS.md`、Agent04 Web contract 和 live API 验证为准。`_archive_legacy/` 和历史交接只作为考古资料，默认不参与当前判断。

## 今日完成事项

- 读取并继承 `/Users/tristanzh/agent/Local-photo-model/HANDOVER_20260530.md` 与 `/Users/tristanzh/agent/Local-photo-model/HANDOVER_agent04_search_20260530.md`。
- 检查卡死线程 `阅读交接并开始工作`：
  - 线程状态为 `active/inProgress`，最新 turn 无任何 items，判断为 Codex 空 in-progress 卡死，不是项目命令卡住。
  - 该线程此前完成过一次索引闭环：8 张剩余图片入库，45 条 stale 清理，`delta_after.has_delta=false`。
- 复核当前 live 状态：
  - `GET http://127.0.0.1:8004/api/health` 返回 OK。
  - 当前 delta 已再次漂移：`missing_count=29`、`stale_count=57`、`has_delta=true`。
  - 该漂移是 Apple Photos 当前资产清单与 SQLite 索引再次不一致，不是 Web 状态接口误报。
- 修复照片无法显示：
  - 修改 `/Users/tristanzh/agent/Local-photo-model/backend/ark_main.py`：
    - 搜索结果新增 `preview_url`。
    - `preview_url` 优先使用真实存在的缓存缩略图。
    - 缩略图不存在时退到当前 SQLite 索引源图的 `/photos/...` URL。
    - 保留 `url` 作为高清/资产入口；不再让前端卡片依赖它做首屏预览。
  - 修改 `/Users/tristanzh/agent/Local-photo-model/frontend/agent04/app.js`：
    - `normalizeResult()` 继承 `preview_url`。
    - 新增 `imagePreviewUrl()`，卡片、灯箱、相似照片优先使用可渲染预览 URL。
    - 新增图片加载失败时的一次 fallback，避免卡片永久空白。
  - 修改 `/Users/tristanzh/agent/Local-photo-model/frontend/agent04/index.html`：
    - 静态脚本版本更新为 `v=20260602-preview-url`，避免浏览器继续使用旧缓存。
  - 修改测试：
    - `/Users/tristanzh/agent/Local-photo-model/tests/test_ark_main.py`
    - `/Users/tristanzh/agent/Local-photo-model/tests/test_frontend_agent04.py`
    - `/Users/tristanzh/agent/web/tests/agent04-service.test.mjs`
- 重启 8004 后端，让 Web 平台重新拉起最新 `backend.ark_main:app`。
- 浏览器验证：
  - 打开 `http://127.0.0.1:3000/agent04-static/index.html`。
  - 页面加载脚本 `app.js?v=20260602-preview-url`。
  - `老妈` 搜索结果卡片可显示照片；前 8 张图片 `naturalWidth/naturalHeight` 均大于 0，`errorCount=0`。

## 已作出的关键决策

- 采用 `preview_url` 作为前端卡片图片接口字段，而不是继续复用 `thumbnail_url` 或 `url`。
- 放弃“补全所有缩略图缓存后再显示”的方案。原因是缩略图缓存是派生资产，缺失时不应阻断浏览器展示；当前索引源图已经是可读本地图片。
- 放弃让前端直接用 `/api/assets/{asset_id}/image` 做卡片预览。原因是该接口可能返回 202 JSON 触发 PhotoKit 原图预热，不满足 `<img>` 资源必须直接返回图片字节的要求。
- `url` 继续保留为高清/资产入口，避免破坏已有灯箱和原图预热语义。
- 本轮修改属于 Agent04 功能与发布边界内的局部变更；未修改 shared 侧边栏。

## 未解决的风险/报错

- 当前相册索引仍存在 delta：
  - `photo_total=14775`
  - `indexed_total=14803`
  - `missing_count=29`
  - `changed_count=0`
  - `stale_count=57`
  - `has_delta=true`
- 若要重新同步，需要执行差量更新；这会对 29 张 missing 调用 Ark 视觉模型，并清理 57 条 stale SQLite 旧索引。执行前必须由 TZ 明确确认，并按 SDD/TDD/操作边界处理。
- 日志中仍有 PhotoKit 找不到资产的历史异常，主要影响打开原图/原图预热，不影响本轮卡片照片显示。
- `/Users/tristanzh/agent/web` 工作区存在非本轮产生的 Agent03 dirty 文件和一个未追踪 SDD 文档：
  - `app/agent03.js`
  - `tests/agent03-browser-interaction.test.mjs`
  - `docs/superpowers/specs/2026-06-02-agent03-workflow-result-state-isolation-sdd.md`
  本轮只改了 Web 侧 `tests/agent04-service.test.mjs` 的 Agent04 静态脚本版本断言，不应触碰 Agent03 变更。
- 当前 `/api/agent04/status` 仍显示 `thumbnails=1`，这是服务读取的项目 `.cache/thumbnails` 统计口径；实际运行缩略图目录与索引缓存状态存在历史漂移。由于本轮已绕开缩略图缺失导致的展示阻塞，暂未重构缩略图统计口径。

## 下一步行动

1. 明天接手第一步读取本文件：

```bash
sed -n '1,260p' /Users/tristanzh/agent/Local-photo-model/HANDOVER_agent04_photo_display_20260602.md
```

2. 复验照片显示：

```bash
python3 - <<'PY'
import json, urllib.request
payload=json.dumps({"query":"老妈","limit":5}, ensure_ascii=False).encode("utf-8")
req=urllib.request.Request("http://127.0.0.1:8004/api/search", data=payload, headers={"content-type":"application/json"})
rows=json.load(urllib.request.urlopen(req, timeout=20))
for row in rows[:5]:
    url=row["preview_url"]
    response=urllib.request.urlopen(url, timeout=10)
    print(row["md5"], response.status, response.headers.get("content-type"), response.headers.get("content-length"))
PY
```

3. 如继续处理同步漂移，先确认是否允许调用 Ark，然后再执行差量更新；不要在未确认前直接跑：

```bash
curl -sS --max-time 45 http://127.0.0.1:8004/api/index/delta | python3 -m json.tool
```

4. 如继续处理“打开大图/原图预热失败”，单独建立 SDD/TDD，重点检查：
   - `/api/assets/{asset_id}/image`
   - `PhotoKitOriginalPrefetcher`
   - PhotoKit 找不到资产时是否应返回可渲染 fallback，而不是后台异常。

5. 今日已完成验证命令：

```bash
python3 -m unittest tests.test_ark_index_engine tests.test_run_index_pipeline tests.test_ark_main tests.test_apple_photos_bridge tests.test_frontend_agent04
python3 -m compileall backend run_index_pipeline.py tests
cd /Users/tristanzh/agent/web && node --test tests/agent04-service.test.mjs
```

