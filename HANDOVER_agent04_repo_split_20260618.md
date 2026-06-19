### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_agent04_repo_split_20260618.md`。
1. 请将本对话的逻辑分支锁定为：【Agent04 Repo Split 收工归档】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# Agent04 Repo Split 收工归档 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

本次收工归档发生在 Agent repo split 之后。`/Users/tristanzh/agent/AGENT_REPO_SPLIT_NOTICE_20260618.md` 明确规定：Agent04 的旧项目根 `/Users/tristanzh/agent/Local-photo-model` 已迁移为新权威项目根 `/Users/tristanzh/agent/agent04-lpm`，repo 为 `tristanzh-dotcom/agent04-lpm`。

从现在起，Agent04 的 handover 扫描、git status、提交、push、测试与服务上下文判断，都必须以 `/Users/tristanzh/agent/agent04-lpm` 为根目录。不要在 `/Users/tristanzh/agent` monorepo 根执行 `git stash pop`，也不要把 monorepo 根里旧目录删除状态误判为 Agent04 项目文件删除。

Agent04 的功能上下文仍是本地图像检索：Apple Photos 继承人物、LIMB 手动人脸库、搜索结果排序、PhotoKit 原图预热、长任务状态机和前端 `/agent04` 工作台。模型路由仍遵循 `/Users/tristanzh/agent/GLOBAL_MODEL_ROUTING_RECORD.md`：中文 query semantic bridge 可走 DeepSeek，图片索引可走 Volcengine Ark；事实和运行状态不能由 LLM 生成。

## 今日完成事项

1. 已读取并理解 repo split notice：
   - 文件：`/Users/tristanzh/agent/AGENT_REPO_SPLIT_NOTICE_20260618.md`
   - 关键映射：`Local-photo-model/` -> `agent04-lpm/`
   - 收工规则：在新 repo 根运行 `git status`；不从 monorepo 根做 stash pop；handover 文档必须使用新路径。

2. 已读取并执行收工归档 skill：
   - 文件：`/Users/tristanzh/agent/.ai_skills/handover_skill.md`
   - 本次只创建一个新交接文件：`HANDOVER_agent04_repo_split_20260618.md`
   - 未更新 `HANDOFF.md`、`PROJECT_MEMORY.md`、`CHANGELOG.md` 或其他历史 handover。

3. 已确认 Agent04 新 repo 状态：
   - 权威根目录：`/Users/tristanzh/agent/agent04-lpm`
   - Git remote：`origin https://github.com/tristanzh-dotcom/agent04-lpm.git`
   - 当前分支：`main`
   - 当前 HEAD：`affd8f4 docs(agent04): add final audit checkpoint`
   - `main` 与 `origin/main` 对齐。

4. 已确认当前新 repo 工作区：
   - `git status --short -- .` 仅显示 `?? data/`
   - `data/` 下包含运行库、缓存、job 状态和 `.fuse_hidden*` 文件：
     - `data/limb_ark.sqlite3*`
     - `data/face_profiles.pkl`
     - `data/photo_face_index.pkl`
     - `data/apple_people_cache.json`
     - `data/delta_update_job.json`
     - `data/face_reindex_job.json`
     - `data/*.log`
   - 这些属于运行数据/缓存候选，不应作为代码变更提交。

5. 已确认 Agent04 审计与修复上下文已经进入新 repo：
   - `HANDOVER_agent04_search_result_order_20260613.md`
   - `docs/audit-report-2026-06-13.md`
   - `docs/final-audit-2026-06-14.md`
   - 相关提交已在新 repo 历史中：`d6ff01d fix(agent04): stabilize face indexing workflow`、`affd8f4 docs(agent04): add final audit checkpoint`。

## 已作出的关键决策

1. 收工扫描锚点改为新 repo 根。
   - 原因：repo split notice 是当前最高优先级迁移说明；旧目录到新目录映射已经生效。
   - 放弃方案：不再以 `/Users/tristanzh/agent/Local-photo-model` 或 `/Users/tristanzh/agent` 作为 Agent04 handover 扫描根。

2. 不处理 monorepo root 的旧路径删除和 frozen stash。
   - 原因：notice 明确要求不要在 monorepo 根盲目 `stash pop`，stash 恢复必须按旧前缀到新 repo 前缀做路径级恢复。
   - 放弃方案：不做 `git stash pop`、不恢复 frozen files、不从 monorepo 根判断 Agent04 文件状态。

3. 本次不启动服务、不跑全量测试、不修改业务代码。
   - 原因：用户要求的是“先读取 repo split notice，再做收工归档”；当前收工目标是归档迁移上下文和新根目录状态，而不是实现新需求。
   - 放弃方案：不对 `backend/`、`frontend/`、`tests/` 做任何修复或清理。

4. 保留 `data/` 未跟踪状态，不清理运行库。
   - 原因：`data/` 包含真实运行索引、缓存和 job 状态；删除会影响本地 Agent04 使用。
   - 后续若需要干净工作区，应先明确哪些运行产物可忽略、哪些必须迁出或备份。

## 未解决的风险/报错

1. `AGENTS.md` 仍声明旧 Scope：
   - 当前文件内容仍写：`Scope: /Users/tristanzh/agent/Local-photo-model`
   - 实际权威根已是：`/Users/tristanzh/agent/agent04-lpm`
   - 明天若要修正，应按 SDD/TDD 开发流先确认这是文档迁移修复，再只改 Agent04 新 repo 内的 `AGENTS.md`。

2. `data/` 在新 repo 中显示为未跟踪：
   - 当前 `git status --short -- .` 显示 `?? data/`
   - 其中多数文件被 `.gitignore` 匹配，但目录本身仍显示未跟踪，可能是 `.fuse_hidden*` 或未忽略的 job 文件导致。
   - 不要直接提交 `data/`。

3. repo split 全局迁移仍未完全结束：
   - notice 记录 Phase 1.5 stash restoration 未完成。
   - Phase 1.6 monorepo retirement 未完成。
   - `cc-switch/` 目标仍待最终决策，可能归入 `agent-tooling`。

4. 旧 handover 中的路径已过期：
   - `HANDOVER_agent04_search_result_order_20260613.md` 仍大量引用 `/Users/tristanzh/agent/Local-photo-model`。
   - 明天读取旧 handover 时，应先应用 repo split notice 的映射：旧路径全部理解为 `/Users/tristanzh/agent/agent04-lpm`。

5. 本次未重新验证服务状态：
   - 未执行 `./start_workspace.sh`。
   - 未访问 `http://127.0.0.1:3000/agent04` 或 `http://127.0.0.1:8004/api/index/status`。
   - 如明天涉及运行验证，先确认 web platform 已按新路径托管 Agent04。

## 下一步行动

1. 明天接手第一步，先读取 repo split notice：
   ```bash
   sed -n '1,260p' /Users/tristanzh/agent/AGENT_REPO_SPLIT_NOTICE_20260618.md
   ```

2. 进入 Agent04 新 repo 根，不使用旧目录：
   ```bash
   cd /Users/tristanzh/agent/agent04-lpm
   git status --short -- .
   git remote -v
   git log --oneline --decorate --max-count=8
   ```

3. 若继续 Agent04 搜索排序/审计修复上下文，读取：
   ```bash
   sed -n '1,260p' HANDOVER_agent04_search_result_order_20260613.md
   sed -n '1,220p' docs/final-audit-2026-06-14.md
   ```
   读取后把旧路径 `/Users/tristanzh/agent/Local-photo-model` 映射为新路径 `/Users/tristanzh/agent/agent04-lpm`。

4. 若要清理工作区，只先分析 `data/`，不要删除：
   ```bash
   git status --ignored --short -- data
   find data -maxdepth 2 -type f -print | sort | sed -n '1,120p'
   ```

5. 若要修正文档路径，建议先做最小 SDD：
   - 目标：更新 Agent04 新 repo 内 stale path references。
   - 优先文件：`AGENTS.md`。
   - 禁止范围：不要改 monorepo 根 frozen stash，不要跨 repo 批量替换。

