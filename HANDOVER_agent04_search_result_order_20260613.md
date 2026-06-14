### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_agent04_search_result_order_20260613.md`。
1. 请将本对话的逻辑分支锁定为：【Agent04 搜索结果排序与审计修复】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# Agent04 搜索结果排序与审计修复 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

本工作流属于 `/Users/tristanzh/agent/Local-photo-model` 的 Agent04 本地图像检索功能修复。核心目标是让 Agent04 的人物检索、搜索输入防御、长任务状态机和人脸索引性能符合真实使用预期：搜索结果不能被隐藏上限误导，人物结果应接近 Apple Photos 相册时间线，后台长任务不能留下污染状态，FTS5 输入异常不能造成 HTTP 500。

项目边界：

- Agent Feature Change：`backend/ark_main.py`、`backend/ark_index_engine.py`、`backend/face_engine.py` 及相关测试。
- Agent Publishing Change：`frontend/agent04/app.js` 及相关前端静态断言测试。
- 未做 Shared Platform Change；未修改 shared sidebar。
- Web 平台入口仍为 `http://127.0.0.1:3000/agent04`，Agent04 后端为 `127.0.0.1:8004`，由 Web 平台托管启动。

## 今日完成事项

1. 审计修复包 A：搜索输入防御
   - 修改 `backend/ark_index_engine.py`：
     - FTS5 `MATCH` 遇到 `sqlite3.OperationalError` 时不再冒泡成 500，而是降级到 LIKE fallback。
     - LIKE fallback 对 `%`、`_`、`\` 做 escape，避免搜索 `%` 返回所有照片。
   - 新增/更新 `tests/test_ark_index_engine.py`：
     - 覆盖未闭合引号输入。
     - 覆盖 LIKE 通配符转义。

2. 审计修复包 B：长任务状态机硬化
   - 修改 `backend/ark_main.py`：
     - `face_reindex_job_status()` 使用 PID 存活检测，死进程标记 `interrupted`。
     - `delta_update_job_status()` 检测死 PID 和孤儿子进程。
     - `start_delta_update()` 复用 `started/running/orphaned` job，避免重复启动多个索引子进程。
   - 新增/更新 `tests/test_ark_main.py`：
     - 覆盖 delta job 互斥、死 PID、孤儿进程、人脸补扫 interrupted。

3. 审计修复包 C：人脸索引 mtime 缓存
   - 修改 `backend/face_engine.py`：
     - 对 pickle 读取增加基于 `(st_mtime_ns, st_size)` 的内存缓存。
     - `_save_pickle()` 后主动刷新缓存，避免同秒写入导致 stale read。
   - 新增/更新 `tests/test_face_engine.py`：
     - 覆盖连续 `match_label()` 不重复读磁盘。

4. 人物搜索结果上限修复
   - 修改 `backend/ark_main.py`：
     - 新增 `DEFAULT_SEARCH_RESULT_LIMIT = 200` 和 `PERSON_SEARCH_RESULT_LIMIT = 5000`。
     - `/api/search` 保持普通搜索上限 200，但给人物搜索路径传入 `person_limit=5000`。
     - `search()`、`_search_with_face_profiles()`、`_search_with_apple_people()` 支持 `person_limit`。
   - 修改 `frontend/agent04/app.js`：
     - 主搜索请求从固定 `limit: 160` 改为 `searchResultLimit = 5000`。
   - 新增/更新测试：
     - `tests/test_ark_main.py` 覆盖 Apple Photos 人物可返回 212 张完整集合。
     - `tests/test_frontend_agent04.py` 覆盖前端不再固定请求 160。
     - `tests/test_ark_face_api.py` 同步 FakeService 签名。
   - Live 验证：
     - `老爸: 199`
     - `老妈: 212`
     - `老张: 1290`
     - `小菲: 247`

5. 人物搜索结果排序修复
   - 修改 `backend/ark_main.py`：
     - Apple Photos 人物搜索和 LIMB 手动人脸搜索不再按 `face_score` 主排序。
     - 新增 `_person_timeline_sort_key()`：有 `taken_at` 的照片按拍摄时间倒序，缺日期照片排最后，同时间再按 `face_score` 和稳定 key 排序。
   - 新增/更新测试：
     - `tests/test_ark_main.py::test_apple_people_search_orders_results_by_capture_time_descending`
     - `tests/test_ark_face_api.py::test_manual_face_search_orders_results_by_capture_time_descending`
   - Live 验证：
     - `老妈 212 dated_desc True undated_after_dated True`
     - `老张 1290 dated_desc True undated_after_dated True`
     - `小菲 247 dated_desc True undated_after_dated True`

6. 运行与验证
   - 已执行：
     - `python3 -m pytest tests/test_ark_main.py tests/test_ark_face_api.py tests/test_ark_index_engine.py tests/test_face_engine.py -q` -> `97 passed`
     - `python3 -m compileall backend tests` -> 通过
     - 新增排序测试 -> `2 passed`
   - 已执行 `./start_workspace.sh`，Web 平台和 8004 后端已按项目入口重启。

## 已作出的关键决策

1. 人物查询默认按相册时间线，而不是人脸置信度排序
   - 原因：用户在相册工作流中期望“像 Apple Photos/相机胶卷一样浏览人物照片”。
   - 放弃方案：不再把 `face_score` 作为人物结果主排序；`face_score` 只作为过滤置信度、badge 展示和同时间二级排序。

2. 普通文本搜索仍按相关度/受控上限，不跟随人物查询放开到完整集合
   - 原因：普通语义搜索返回完整库会造成大响应和低质量结果；人物查询有明确集合边界。
   - 实现：`/api/search` 普通上限 200，人物路径上限 5000。

3. 本轮未修改 shared Web 平台
   - 原因：所有变更属于 Agent04 功能/API 和 Agent04 静态前端请求逻辑。
   - Web 平台只负责托管和重启，未改 shared sidebar、全局主题或跨 agent 布局。

4. 前端 lightbox 3 个失败测试暂不按旧断言改 UI
   - 判断：这 3 个失败来自测试漂移，旧断言要求返回按钮覆盖照片区域、图片 absolute 填充；当前 UI 已把操作收敛到 inspector header，图片保持比例居中。
   - 后续应同步测试，而不是回退 UI。

## 未解决的风险/报错

1. 工作区仍有未提交改动
   - 当前 `git status --short -- .` 显示 Local-photo-model 内有多处修改：
     - `backend/ark_index_engine.py`
     - `backend/ark_main.py`
     - `backend/face_engine.py`
     - `frontend/agent04/app.js`
     - `tests/test_ark_face_api.py`
     - `tests/test_ark_index_engine.py`
     - `tests/test_ark_main.py`
     - `tests/test_face_engine.py`
     - `tests/test_frontend_agent04.py`
   - 还有 `docs/audit-report-2026-06-13.md` 未跟踪。
   - `data/`、`tests/test_query_sandbox.db*` 是运行/测试产物，应确认是否清理或加入忽略，不要误提交。

2. vibe clean 后旧 root handover 文件在 git 状态中显示删除
   - `HANDOVER_agent04_first_paint_performance_20260603.md`
   - `HANDOVER_agent04_first_paint_performance_fix_20260603.md`
   - `HANDOVER_agent04_photo_display_20260602.md`
   - 这些此前被移动到 `_archive_legacy/`，但该目录 gitignored。提交前必须决定是否保留删除，不能无意识提交。

3. 前端完整套件仍有 3 个已知失败
   - 失败集中在 lightbox/CSS 断言与当前实现不一致。
   - 建议作为独立测试同步任务处理。

4. 搜索请求返回 200 后，后台 PhotoKit prefetch 曾刷异常栈
   - 典型错误：`RuntimeError: PhotoKit 未找到资产: ...`
   - 当前不影响搜索结果数量和 HTTP 200，但日志噪声明显，后续应把 background task 的 PhotoKit 未找到资产降级为 warning/skip。

5. 人脸补扫 job 状态仍为 interrupted
   - `GET /api/face/reindex/job` 显示此前补扫在 `7040 / 14959` 中断。
   - 当前“小菲”等搜索已有 247 条，但完整人脸索引可能仍未补完。

## 下一步行动

1. 明天第一步先确认工作区状态
   - 执行：
     ```bash
     git status --short -- .
     git diff --stat -- .
     ```
   - 只关注 `/Users/tristanzh/agent/Local-photo-model` 内改动，不要把上级仓库其他项目噪声混入。

2. 决定提交拆分
   - 建议至少拆成：
     - ABC 审计修复：FTS5 fallback、job state、face pickle cache。
     - 搜索体验修复：人物完整结果上限 + 人物时间线排序。
     - 前端测试同步：lightbox 3 个旧断言。
   - 若只做一个 commit，PR/回滚会更难。

3. 修复/同步前端 3 个 lightbox 测试
   - 只改 `tests/test_frontend_agent04.py` 断言。
   - 不建议为旧测试回退 UI。
   - 目标命令：
     ```bash
     python3 -m pytest tests/test_frontend_agent04.py -q
     ```

4. 处理 PhotoKit prefetch 后台异常
   - 建议 TDD 新增测试：`prefetch_originals_if_needed()` 或 `/api/search` background task 遇到 PhotoKit asset not found 不应打印 ASGI exception stack。
   - 修改点大概率在 `backend/apple_photos_bridge.py` 或 `backend/ark_main.py` background task 包装处。

5. 提交前验证
   - 后端核心：
     ```bash
     python3 -m pytest tests/test_ark_main.py tests/test_ark_face_api.py tests/test_ark_index_engine.py tests/test_face_engine.py -q
     python3 -m compileall backend tests
     ```
   - live 验证：
     ```bash
     ./start_workspace.sh
     python3 - <<'PY'
     import json, urllib.request
     for q in ['老爸','老妈','老张','小菲']:
         req = urllib.request.Request(
             'http://127.0.0.1:8004/api/search',
             data=json.dumps({'query': q, 'limit': 5000}).encode('utf-8'),
             headers={'content-type':'application/json'},
             method='POST',
         )
         with urllib.request.urlopen(req, timeout=30) as resp:
             rows = json.loads(resp.read().decode('utf-8'))
         print(q, len(rows), [r.get('taken_at') for r in rows[:3]])
     PY
     ```

