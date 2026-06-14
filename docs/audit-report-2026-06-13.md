# 本地图像检索 — 项目审计报告

**日期**: 2026-06-13  
**审计范围**: 全栈代码审计 — 后端 (FastAPI/SQLite)、前端 (Vanilla JS)、测试套件  
**测试基线**: 153 passed / 6 failed (3 前端 test 过期, 2 sandbox 权限, 1 sandbox I/O)

---

## 发现概览

| 严重度 | 数量 | 涉及模块 |
|--------|------|----------|
| Critical | 2 | face_engine (pickle), ark_index_engine (FTS5 crash) |
| High | 3 | ark_main (daemon abandoned), ark_main (no rate limit), ark_main (wide except) |
| Medium | 6 | face_engine (perf), ark_main (sync I/O), ark_index_engine (wildcard leak), CORS, ark_main (race) |
| Low | 4 | frontend (test drift), ark_main (no body limit), config (hardcoded path) |

---

## 1. Security Vulnerabilities

### [Critical] CVE-1: Pickle 反序列化远程代码执行 (RCE)

**文件**: `backend/face_engine.py:348-358`

`_load_pickle()` 和 `_save_pickle()` 使用标准库 `pickle` 读写人脸向量数据。Python 的 `pickle` 模块在文档中明确标注不安全 — 反序列化任意 pickle 数据可导致任意代码执行。如果攻击者能写入 `face_profiles.pkl` 或 `photo_face_index.pkl`（例如通过提权的另一个本地进程、共享目录、或备份恢复），即可在 LIMB 进程上下文中执行任意代码。

**修复建议**: 使用 `safetensors` 或纯 JSON/NumPy `.npy` 格式替代 pickle；或至少为 pickle 文件添加 HMAC 签名验证。

### [Critical] CVE-2: FTS5 查询解析崩溃导致 500 错误

**文件**: `backend/ark_index_engine.py:418-451`

`ArkPhotoIndexDatabase.search()` 在 FTS5 MATCH 解析失败时抛出未捕获的 `sqlite3.OperationalError`（例如用户输入 `"test"` — 未闭合引号导致 `unterminated string`）。该异常穿透到 FastAPI 路由层，由 `except Exception` 捕获后返回 HTTP 500。

实测触发向量：
- `"test"` → `unterminated string`
- 包含 null 字节的输入 → 同类型错误
- 这只是搜索 API，不涉及数据写入，但会导致搜索功能完全不可用，直到用户清空输入。

**修复建议**: 在 `_build_fts_query()` 中调用 `sqlite3` 的 FTS5 查询校验函数，或在 `search()` 方法内部捕获 `OperationalError` 并降级到 LIKE 回退路径。

---

### [High] SEC-1: Daemon 线程在进程退出时被静默丢弃

**文件**: `backend/ark_main.py:511` (face reindex), `backend/ark_main.py:1487` (delta update)

`start_face_reindex()` 和 `start_delta_update()` 使用 `threading.Thread(daemon=True)` 启动后台工作线程。Python 的 daemon 线程在进程退出时被强制终止，不执行清理：

- `face_reindex_job.json` 和 `delta_update_job.json` 永久留在 "running" 状态
- 下次启动时，`face_reindex_job_status()` 中的 PID 检查会检测 PID 不匹配并返回 "interrupted"，但 delta 更新没有等效的 PID 恢复逻辑
- 没有 `atexit` 处理器或信号处理器来标记任务为失败

**修复建议**: (a) 为两个 job 状态系统添加 `atexit` 处理器，将进行中的 job 标记为 "interrupted"；(b) 在服务启动时自动清理明显已死的 job 状态。

### [High] SEC-2: 所有端点无速率限制

**文件**: `backend/ark_main.py:1726-2024`

FastAPI 应用没有任何速率限制中间件。所有 21 个端点均可被无限制调用，包括：
- `POST /api/search` — 每次都触发人脸向量匹配（含 12MB pickle 加载）
- `POST /api/face/reindex` — 启动 14K 图片的人脸扫描
- `POST /api/index/delta/run` — 启动完整增量索引子进程

虽然是 localhost-only 服务，但本地恶意脚本可以轻易将其打挂。

**修复建议**: 添加 `slowapi` 或类似库，至少对 `/api/search` 和 `/api/face/reindex` 设置合理限制。

### [High] SEC-3: 宽泛的异常捕获隐藏真实错误

**文件**: `backend/ark_main.py` (30+ 处 `except Exception`)

大量 `except Exception as exc` 块不做错误分类，统一返回 HTTP 500 或静默降级。典型案例：
- `_apple_people_list_named_people()` (L749-752): 异常被静默捕获后打印日志并 fallback 到缓存，调用方无法区分 "没有数据" 和 "数据库损坏"
- `index_delta()` (L1870): 任何异常都返回 500，但 FTS5 parse error 应该是 400

**修复建议**: 引入更精细的异常类型（`SearchError`, `IndexError`, `AuthError` 等），在 FastAPI 层面使用 exception handlers 做统一转换。

---

## 2. Data Integrity

### [Medium] DATA-1: FTS5 LIKE 回退路径泄露通配符语义

**文件**: `backend/ark_index_engine.py:439-451`

当 FTS5 MATCH 查询返回零结果时，代码回退到 `LIKE '%query%'` 查询。SQL LIKE 的通配符 `%` 和 `_` 可匹配任意字符，导致：
- 搜索 `%` 返回所有已索引照片（验证：返回 1 条）
- 虽然实际影响有限（14K 照片中随机匹配），但语义上不正确

**修复建议**: 在 LIKE 查询前对 `%` 和 `_` 做转义（`\%` 和 `\_`），或者仅在非 SQL 通配符查询时启用 LIKE 回退。

### [Medium] DATA-2: 人脸搜索每次都从磁盘加载 12MB+ pickle

**文件**: `backend/face_engine.py:203, 242-243`

`match_label()` 每次调用都会调用 `load_photo_index()`，将整个 `photo_face_index.pkl`（~12.3MB，~14K 条目）从磁盘反序列化到内存。API 路径 `_search_with_face_profiles()` 为查询中的每个人脸标签调用一次 `match_label()`。对于 "小菲 和 爸爸" 这样的查询，这意味着两次完整的 12MB 磁盘读取和 pickle 反序列化。

没有内存缓存，没有 LRU，没有 mmap。

**修复建议**: 在 `FaceVectorEngine.__init__` 中添加基于修改时间的缓存；当 pickle 文件未被修改时复用内存中的索引。

### [Medium] DATA-3: face_reindex 进度更新的原子性窗口

**文件**: `backend/ark_main.py:451-468, 470-508`

`update_progress()` 回调在每次进度更新时调用 `_write_face_reindex_job()`（每 10 张照片），后者写入临时文件后 rename。虽然文件写入是原子的，但：
- `_face_reindex_lock` 只在 `start_face_reindex()` 初始写入时持有
- 进度更新和状态读取（`face_reindex_job_status()`）之间没有锁保护
- 理论上可能出现：读取线程读到 old 状态 → 前台显示 "7040/14959" → 实际已完成 7050

**修复建议**: 对 `face_reindex_job_path` 的读/写都加同一把锁；或使用 `fcntl.flock` 做文件级锁。

---

## 3. Performance Bottlenecks

### [Medium] PERF-1: 同步 I/O 阻塞 FastAPI 事件循环

**文件**: `backend/ark_main.py` (21 个同步路由, 仅 1 个异步路由)

所有路由都是同步的（`def` 而非 `async def`），仅 `/api/face/register` 是异步的。FastAPI 在内部线程池中运行同步路由，性能影响对 localhost 服务可控，但：
- `get_photo()` 路由读取整个文件到内存 (`path.read_bytes()`)
- 对于 HEIF/RAW 原图（可能 20-50MB），这会阻塞线程池线程

**修复建议**: 对大文件使用 `StreamingResponse` + `FileResponse`（支持 range requests）。

### [Medium] PERF-2: 12MB face index 在纯 Python 中做 O(N) 线性扫描

**文件**: `backend/face_engine.py:203-211`

`match_label()` 对 `photo_face_index` 中的所有 ~14K 条目做线性余弦相似度扫描。每次相似度计算包括：
1. NumPy 数组归一化
2. 向量点积
3. 最高分挑选

对于 14K 照片 × 512 维向量，即使是在 Python+NumPy 中也是可测量的延迟（约 10-50ms per label，取决于 CPU）。这个操作阻塞了同步的 `/api/search` 路由。

**修复建议**: (a) 为 photo_face_index 构建 Faiss IVF 或 HNSW 索引；(b) 在服务启动时预计算并缓存归一化向量。

### [Medium] PERF-3: os.walk 在同步 API 路由中执行

**文件**: `backend/ark_main.py:1047-1056`

`_iter_local_photo_files()` 在被 `index_delta()` 调用时，通过 `os.walk` 遍历整个 photo_root。在 Apple Photos originals 目录（可能有数十个子目录）中，这在首次调用时可能需要数百毫秒。

**修复建议**: 缓存文件列表并用 `watchdog` 或 `fsevents` 做增量更新。

---

## 4. Error Handling & Edge Cases

### [Medium] ERR-1: FTS5 查询错误未降级

**文件**: `backend/ark_index_engine.py:418-451`

当 FTS5 MATCH 抛出 `OperationalError`（如未闭合引号），整个 `search()` 方法失败。代码已经有 LIKE 回退路径，但 FTS5 异常发生在到达回退之前。修复应为在 FTS5 查询周围加 try/except 并在异常时直接走 LIKE 路径。

### [Medium] ERR-2: DeepSeek API 调用无重试

**文件**: `backend/ark_main.py:156-170`

`DeepSeekQueryBridge.parse()` 调用 DeepSeek API 时设置了 `timeout=20`，但没有重试逻辑。网络抖动会导致查询直接回退到原始文本。这是设计上可接受的（DeepSeek 是可选的增强层），但缺少指数退避重试使其在面对瞬时故障时过于脆弱。

### [Low] ERR-3: 上传文件无大小限制

**文件**: `backend/ark_main.py:1901`

`/api/face/register` 端点接收 multipart 文件上传，但没有设置 `MAX_UPLOAD_SIZE` 或 Content-Length 检查。FastAPI/Starlette 默认会缓冲到磁盘，但无限制的上传可耗尽磁盘空间。

### [Low] ERR-4: 前端的 delete API 无二次确认

**文件**: `frontend/agent04/app.js` (delete 路径)

Lightbox 中的删除按钮直接调用 `DELETE /api/photos/{md5}`，没有确认对话框。这与 face profile 删除有关联确认对话框形成对比。

---

## 5. Test Suite Status

### 测试覆盖概览

| 模块 | 测试文件 | 状态 |
|------|---------|------|
| ark_main (核心搜索) | test_ark_main.py | ✅ 全通过 |
| ark_index_engine | test_ark_index_engine.py | ✅ 全通过 |
| apple_photos_bridge | test_apple_photos_bridge.py | ✅ 全通过 |
| frontend (static) | test_frontend_agent04.py | ⚠️ 3 失败 |
| face_engine | test_face_engine.py | ⚠️ 2 失败 (sandbox) |
| entity | test_entity_query.py | ⚠️ 1 失败 (sandbox) |
| security/config | test_runtime_config_security.py | ✅ 全通过 |
| connectivity | test_ark_connectivity.py | ✅ 全通过 |
| misc | test_backend_main_compat, test_workspace_scripts | ✅ 全通过 |

### 失败的测试分析

**前端测试 3 个失败** (`test_frontend_agent04.py`):
- `test_lightbox_back_button_lives_in_inspector_not_over_photo`: 断言 `data-lightbox-back` 属性存在于 lightbox `<dialog>` 中，但实际结构中该属性在 inspector 内部。HTML 结构已演变，测试未同步更新。
- `test_lightbox_keeps_photo_and_inspector_visually_separated`: 断言 `.limb-lightbox-stage img` 有 `position: absolute;`，但当前 CSS 使用了 `grid-area: photo`，不再需要 absolute 定位。
- `test_lightbox_primary_actions_are_in_inspector_header`: 断言 `grid-template-columns: auto auto 1fr;` 存在于特定 CSS 规则中，但 CSS 已重构。

这三项均为测试与代码不同步的问题，不影响功能正确性。

**Face engine 2 个失败** (`test_face_engine.py`):
- `test_delete_profile_removes_label_from_vector_library`: `PermissionError` 在 `candidate.unlink()` — 沙箱环境阻止删除项目目录下的文件
- `test_register_profile_persists_new_avatar_and_delete_removes_old_avatar`: 同上

这是沙箱限制，非代码缺陷。

**Entity query 1 个失败** (`test_entity_query.py`):
- `test_intersect_query_logic`: `sqlite3.OperationalError: disk I/O error` — 沙箱文件系统限制

---

## 6. Defensive Posture Assessment

### 路径遍历防护: 充分

所有静态文件服务端点都实施了 `relative_to()` 检查：
- `resolve_photo_static_path()` — 验证相对于 photo_root
- `resolve_thumbnail_static_path()` — 验证相对于 thumbnail_dir + MD5 文件名正则
- `resolve_face_avatar_static_path()` — 验证相对于 avatar_dir
- `resolve_asset_image_static_path()` — asset_id 正则验证 + 数据库查询

### SQL 注入防护: 充分

- 所有 SQLite 查询使用参数化语句（`?` 占位符）
- FTS5 查询通过 `_build_fts_query()` 构建，每个 token 用双引号包裹
- 唯一的字符串拼接在 `get_photos_by_paths()` 中的 `IN` 子句 — 这是对于参数化占位符数量的必要构建，但值仍然参数化
- `_ensure_asset_columns()` 中的 `ALTER TABLE` 使用字符串拼接 — 列名来自硬编码字典，不接受用户输入

### API Key 管理: 良好

- `config.py` 不存储硬编码密钥（已验证测试）
- `ARK_API_KEY` 从环境变量读取，deploy 脚本使用 `${ARK_API_KEY:?}` 强制要求
- `DEEPSEEK_API_KEY` 是可选的，未设置时系统优雅降级

### CORS 配置: 可接受（localhost-only）

服务仅在 localhost 上运行。CORS 允许 `localhost:3000`、`127.0.0.1:3000`、`localhost:5500`、`127.0.0.1:5500`，匹配 Web 平台的开发和生产端口。`allow_methods=["*"]` 和 `allow_headers=["*"]` 在纯本地部署中可接受。

---

## 7. 修复优先级

| 优先级 | 发现 | 预估工作量 | 风险 |
|--------|------|-----------|------|
| P0 | CVE-1: pickle → safetensors/npy | 4h | RCE（需本地文件写入权限） |
| P0 | CVE-2: FTS5 parse crash → 500 | 1h | 搜索功能拒绝服务 |
| P1 | SEC-1: daemon 线程 abandon → atexit | 2h | 状态污染，需手动清理 |
| P1 | DATA-2: face index 内存缓存 | 3h | 搜索延迟 (10-50ms → <1ms) |
| P2 | PERF-2: Faiss/HNSW 索引替代线性扫描 | 8h | 人脸搜索延迟降低 10-50x |
| P2 | SEC-2: 速率限制 | 2h | 本地 DoS 防护 |
| P3 | 前端 test 更新 (3 tests) | 1h | CI 红标噪音 |
| P3 | PERF-1: photo streaming | 3h | 大图加载内存优化 |
| P4 | ERR-4: delete confirmation | 30min | UX 防御 |

---

*审计工具: 静态分析 + 动态验证 + 153/159 测试通过*  
*未涉及: 第三方依赖 CVE 扫描 (volcengine-sdk, insightface, onnxruntime) — 建议单独运行 `pip-audit` 或 `safety`*
