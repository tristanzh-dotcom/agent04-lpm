# Agent04 最终代码审计 — 2026-06-14

**审计阶段**: 开发完成，人工测试通过，提交前最终审阅
**测试基线**: 169 passed / 3 failed（3 个失败均为沙箱环境限制，非回归）
**变更范围**: 3 个 back-end 文件 + 3 个 test 文件，无 front-end、Web 平台、数据文件变更

---

## 一、变更逐行审阅

### 包 A — 搜索输入防御（FTS5 crash + LIKE escape）

**文件**: `backend/ark_index_engine.py:418-479`

| 检查项 | 结论 |
|--------|------|
| `sqlite3.OperationalError` 仅捕获 FTS5 MATCH 块，不吞并 LIKE 或返回格式化异常 | ✅ |
| `_escape_like_query()` 先转义 `\` → `\\` 再转义 `%`/`_`（顺序正确，避免双重转义） | ✅ |
| LIKE SQL 使用 `ESCAPE '\'` 匹配转义字符 | ✅ |
| `_build_fts_query()` 未被修改（保持现状，边界约定） | ✅ |
| 空查询 `""` 仍在 `search()` 开头返回 `[]`（未走 FTS5 路径） | ✅ |
| 正常查询路径优先走 FTS5 bm25 排序，零结果时走 LIKE 回退 | ✅ |
| 无多余代码引入（新增 `_escape_like_query` 4 行，无其他变更） | ✅ |

**测试**: `test_database_search_falls_back_to_like_when_fts_query_is_invalid` — 验证 `"test` 不抛异常且返回匹配结果。`test_database_search_escapes_like_wildcards_in_fallback` — 验证搜索 `%` 仅匹配含字面 `%` 的照片，不泄漏为全量召回。

**等级**: ✅ 无瑕疵

---

### 包 B — 长任务状态机（face_reindex + delta_update）

**文件**: `backend/ark_main.py:365-418, 1340-1392, 1538-1593`

**核心工具方法**:

`_process_exists(pid)` (L393-408):
| 检查项 | 结论 |
|--------|------|
| 使用 `os.kill(pid, 0)` 检测进程存在性 | ✅ |
| `ProcessLookupError` → False（进程不存在）| ✅ |
| `PermissionError` → True（存在但无权限信号，通常是别人的进程）| ✅ |
| `OSError` catch-all → False（保守假设不存在）| ✅ |
| PID ≤ 0 或非 int → False | ✅ |

`_process_parent_pid(pid)` (L410-435):
| 检查项 | 结论 |
|--------|------|
| 使用 `ps -o ppid=` 获取父进程 PID | ✅ |
| macOS `ps` 兼容（`-o ppid=` 是标准格式）| ✅ |
| timeout 2s 防止 ps 挂起 | ✅ |
| 解析失败 → None（不阻断后续逻辑）| ✅ |
| 异常 → None | ✅ |

**face_reindex_job_status()** (L365-391):

逻辑：不存在 → idle / 读 JSON 失败 → unknown / PID 不存在 → interrupted / PID ≠ current → interrupted / 否则返回原状态。

| 检查项 | 结论 |
|--------|------|
| PID 检查顺序：先检测进程存在，再检测是否为当前进程 | ✅ |
| `int(pid)` 转换失败不抛异常（except catch）| ✅ |
| `interrupted` 同时适用于"进程已死"和"进程属于其他实例"两种情况 | ✅ |
| daemon 线程语义：即使 PID 存在且属于其他进程，也标记 interrupted（daemon 线程不能跨进程存活）| ✅ |

**delta_update_job_status()** (L1365-1392):

| 检查项 | 结论 |
|--------|------|
| 不存在 → idle / `started`/`running` + PID 不在 → interrupted | ✅ |
| PID 存在但父 PID ≠ os.getpid() → `orphaned`（子进程存活但父进程已重启）| ✅ |
| PID 存在且父 PID = current → 返回原状态（正在运行）| ✅ |
| `orphaned` 语义独立于 `interrupted`（前端可区分"已死需重试" vs "仍在跑请等待") | ✅ |

**start_delta_update()** (L1538-1593):

| 检查项 | 结论 |
|--------|------|
| 启动前调用 `delta_update_job_status()` 检查现有 job | ✅ |
| block 状态为 `started`/`running`/`orphaned`（任意一种都阻止重复启动）| ✅ |
| `orphaned` 被 block：孤儿进程仍在运行，不应重复启动 | ✅ |
| `interrupted` 不 block：允许重新启动 | ✅ |
| 检查在后继的 `index_delta()` 之前执行（避免无意义的文件系统扫描）| ✅ |

**测试**: 4 个新测试全覆盖 — running guard 阻止重复 Popen、dead PID → interrupted、live orphan → orphaned、face_reindex dead PID → interrupted。

**等级**: ✅ 无瑕疵

---

### 包 C — 人脸索引 mtime 缓存

**文件**: `backend/face_engine.py:61, 240-244, 356-374`

**缓存结构**:
```python
_pickle_cache: dict[Path, tuple[tuple[int, int], dict[str, Any]]]
```
Key: pickle 文件路径。Value: `((st_mtime_ns, st_size), payload)`。

| 检查项 | 结论 |
|--------|------|
| 使用 `st_mtime_ns`（纳秒）而非 `st_mtime`（秒），避免 1s 精度问题 | ✅ |
| 结合 `st_size` 做指纹，防止同秒内 overwrite 到相同大小文件时误命中 | ✅ |
| 仅 `load_profiles()` 和 `load_photo_index()` 走缓存路径 | ✅ |
| 其他 pickle 调用点（测试夹具中的 `_load_pickle`）不受影响 | ✅ |

**写入后缓存同步**:

`_save_pickle()` (L369-374) 在 `pickle.dump()` 后立即 `stat()` 并将新 fingerprint+payload 写入缓存。

| 检查项 | 结论 |
|--------|------|
| `register_profile()` → `_save_pickle(profiles_path)` → 缓存自动更新 | ✅ |
| `delete_profile()` → `_save_pickle(profiles_path)` → 缓存自动更新 | ✅ |
| `scan_photo_paths()` → `_save_pickle(photo_index_path)` → 缓存自动更新 | ✅ |
| 所有写路径都经过 `_save_pickle`，无需手动 invalidate | ✅ |

**文件不存在处理**:

`_load_cached_pickle()` (L356-367) 中 `path.exists()` 为 False 时主动 `pop` 缓存并返回 `{}`。防止 pickle 被外部删除后缓存返回脏数据。

| 检查项 | 结论 |
|--------|------|
| 缓存命中先比较 fingerprint，不匹配时重新加载 | ✅ |
| 文件不存在时清理缓存条目 | ✅ |
| 不存在时返回空 dict（与 `_load_pickle` 行为一致）| ✅ |

**测试**: `test_match_label_reuses_cached_pickles_when_files_are_unchanged` — 注册 profile、扫描 photo、清空缓存后，两次 `match_label` 调用间仅产生 2 次 `_load_pickle` 调用（profiles 和 photo index 各 1 次），验证第二轮命中缓存而非重新读盘。

**等级**: ✅ 无瑕疵

---

## 二、测试套件

| 指标 | 值 |
|------|-----|
| 总测试数 | 172 |
| 通过 | 169 |
| 失败（沙箱） | 3 |
| 新增测试 | 7（A: 2, B: 4, C: 1） |
| 被修改的已有测试 | 0 |
| 新增回归 | 0 |

3 个失败均为 pre-existing sandbox 环境限制：
- `test_entity_query.py::test_intersect_query_logic` — sqlite3 disk I/O error（VM 文件系统限制）
- `test_face_engine.py::test_delete_profile_removes_label_from_vector_library` — PermissionError 删除 `.cache/face-avatars/` 下文件
- `test_face_engine.py::test_register_profile_persists_new_avatar_and_delete_removes_old_avatar` — 同上

**无新增失败。无已有测试被削弱。**

---

## 三、回归面排查

| 检查项 | 结论 |
|--------|------|
| 前端文件（`frontend/agent04/` 下 3 个文件）是否被修改 | 否 |
| Web 平台（`/Users/tristanzh/agent/web/`）是否被修改 | 否 |
| 数据文件（`data/*.sqlite3`, `data/*.pkl`, `data/*.json`）是否被修改 | 否 |
| 配置文件（`backend/config.py`）是否被修改 | 否 |
| Shell 脚本是否被修改 | 否 |
| 依赖（`requirements.txt`）是否变更 | 否 |
| Python 编译（`compileall`）是否通过 | ✅ |
| 全局 search API 行为（无 face label 的纯 FTS5 查询）是否受影响 | 否（`sqlite3.OperationalError` 仅在 FTS5 语法错误时触发，正常查询不受影响） |
| 人脸搜索 API 行为是否受影响 | 否（仅增加读缓存，无逻辑变更） |
| 前端轮询接口 `/api/face/reindex/job` 返回格式是否兼容 | 是（`interrupted` 状态字段已存在，前端已处理） |

---

## 四、综合评定

| 评分维度 | 评分 | 说明 |
|---------|------|------|
| 代码质量 | A | 最小变更，精准切入，无多余重构 |
| 测试覆盖 | A | 每个修复点均有对应用例，覆盖正常/异常/边界 |
| 设计一致性 | A | 三个包独立实现，无交叉耦合，与约定 SDD 对齐 |
| 回归安全性 | A | 0 新增失败，0 已有测试退化 |
| 向后兼容 | A | API 响应格式无 breaking change，前端无需更新 |

**总评: A — 可立即提交。**

---

*审计方法: 全量代码审阅 + 全量测试运行 + 回归面排查 + 文件修改范围验证*  
*审计人: Claude (Cowork audit session)*
