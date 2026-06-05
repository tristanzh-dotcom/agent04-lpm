### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_agent04_first_paint_performance_fix_20260603.md`。
1. 请将本对话的逻辑分支锁定为：【Agent04 首屏性能修复】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# Agent04 首屏性能修复 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

本轮目标是修复 Web 发布页 `/agent04` 的首屏/首次绘制性能问题。核心业务目的不是减少模型 token，也不是重建本地照片索引，而是让“本地图像检索”页面先快速出现，再异步刷新 Apple Photos delta 对账状态。

根因已确认：Web 发布层把 `/agent04` 首屏 HTML 渲染和 `GET http://127.0.0.1:8004/api/index/delta` 全量对账绑定在同一个同步请求里。`/api/index/delta` 会读取 Apple Photos 当前资产清单并与 SQLite 索引做本地全量对账，实测常见耗时约 3.7-4.0s，并发时可被放大。因此它不应该阻塞首屏 HTML 返回。

本次改动分类为 `Agent Publishing Change`：

- 影响范围：`/Users/tristanzh/agent/web` 内 Agent04 route-owned 页面、`/api/agent04/status` 状态链路、Agent04 发布文档与项目记忆。
- 未触发相册差量更新 mutation。
- 未执行 `/api/index/delta/run`。
- 未重建照片索引。
- 未调用 Ark 视觉模型或 DeepSeek。
- 未修改 Local-photo-model 后端业务逻辑。

## 今日完成事项

修改文件：

- `/Users/tristanzh/agent/web/server.mjs`
  - 为 Agent04 runtime 增加 delta normalization。
  - 增加 30s delta cache。
  - 增加 `deltaInFlight` 复用，避免并发 status/page 请求重复触发完整 delta 扫描。
  - `getStatus()` 默认改为 `deltaMode: "background"`，先返回 fast status，再后台刷新 delta。
  - 保留显式 `deltaMode: "live"` 能力，供未来需要等待完整 delta 的调用使用。
  - `/agent04` 首屏在 delta 未知时输出 `data-agent04-delta-state="refreshing"` 和文案 `同步状态读取中`。

- `/Users/tristanzh/agent/web/app/agent04.js`
  - 增加 `updateAgent04DeltaButton(delta)`，统一处理 `refreshing / stale / ready / synced` 状态。
  - `refreshAgent04Status()` 返回 status payload，供后续调度判断。
  - 增加 `scheduleAgent04StatusRefresh()`，当初始状态为 `refreshing` 时短轮询 `/api/agent04/status`，后台 delta 完成后自动更新按钮为 `发现 N 张待更新` 或 `相册已同步`。

- `/Users/tristanzh/agent/web/tests/agent04-service.test.mjs`
  - 更新旧的 live status 测试：首个 status 允许 `refreshing`，后续读取 cached live delta。
  - 新增测试：`/agent04` 在慢 delta Promise 未释放前必须返回 HTML。
  - 新增测试：并发 `/api/agent04/status` 必须快速返回，并复用同一个 in-flight delta refresh。
  - 增加前端 shell 断言：必须包含 `同步状态读取中` 和 `scheduleAgent04StatusRefresh`。

- `/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md`
  - 写入新 API 合约：`/api/agent04/status` 不等待 `/api/index/delta`。
  - 写入验证规则：首屏必须在慢 Apple Photos delta 对账完成前渲染。
  - 写入 delta 初始/缓存状态文案规则。

- `/Users/tristanzh/agent/web/PROJECT_MEMORY.md`
  - 修正 Agent04 当前范式记忆为 `垂直2框范式`。
  - 增加 Agent04 status performance rule：fast status、background delta、短 TTL cache、in-flight 复用。

验证结果：

```text
node --test --test-concurrency=1 tests/agent04-service.test.mjs
结果：7/7 pass

npm test
结果：106/106 pass
```

运行时验证：

```text
当前代码临时实例：http://127.0.0.1:3001
/agent04 route total=0.348951s starttransfer=0.348889s
首次 /api/agent04/status: deltaState=refreshing deltaSource=refreshing
5 秒后 /api/agent04/status: deltaState=ready deltaSource=live hasDelta=true missing=6 changed=0 stale=57
```

可确认的性能提升：

```text
归档基线：/agent04 ~= 3.9s
当前修复版：/agent04 ~= 0.35s
提升倍数：约 11x
延迟下降：约 91%
```

如果拿当天 3000 旧进程实测值对比：

```text
旧 3000 进程：/agent04 ~= 7.79s
当前 3001 修复版：/agent04 ~= 0.35s
提升倍数：约 22x
延迟下降：约 95.5%
```

更严谨的项目口径采用归档基线 `3.9s -> 0.35s`。

## 已作出的关键决策

1. 首屏不再等待 delta 对账。

   `/agent04` 页面只需要 Web shell、iframe、基础 index status 和明确的同步状态文案即可完成首次绘制。Apple Photos delta 是本地扫描/对账成本，不属于首屏 HTML 必需数据。

2. `/api/agent04/status` 默认走 fast path。

   该接口继续返回 Agent04 Web-shell status 和 live index count，但 delta 结果允许为：

   - `state: "refreshing"`：后台正在刷新。
   - `state: "ready"` + `source: "live"`：缓存中已有完成的 live delta。
   - `state: "stale"`：delta 读取失败，保留 fallback 状态。

3. 用短 TTL cache + in-flight 复用处理并发放大风险。

   之前多个并发 `/agent04` 或 `/api/agent04/status` 可能重复触发完整 `/api/index/delta` 扫描。现在同一轮刷新共享 `deltaInFlight`，完成后进入 30s cache。

4. 前端显示明确的中间态。

   delta 未知时按钮文案为 `同步状态读取中`，禁用差量更新按钮；后台状态刷新完成后再变成 `发现 N 张待更新` 或 `相册已同步`。

5. 不把问题误判成 CSS/layout/display 修复。

   本轮没有改 shared sidebar，没有处理相册重建，也没有动 Local-photo-model 后端算法链路。问题核心是 Web route 同步等待慢对账。

6. 模型 token 消耗不变。

   启动加载 Agent04 仍不调用 Ark/DeepSeek。`/api/index/delta` 是 `scan_cost: "local_only_no_model_token"` 的本地扫描对账。本轮只是把它移出首屏阻塞链路，并降低并发重复扫描风险。

## 未解决的风险/报错

1. `127.0.0.1:3000` 上已有旧 Web 进程，仍表现为旧行为。

   实测：

   ```text
   3000 /agent04 ~= 7.79s
   3000 /api/agent04/status ~= 4.09s
   ```

   这说明 3000 尚未重启到当前工作区修复版。当前修复版已通过临时 3001 实例验证。

2. 工作区存在大量本轮之前的未提交改动。

   本轮只围绕 Agent04 性能修复改动上述 5 个文件。`server.mjs` 中还能看到此前已有的 shared sidebar、Agent03、`/api/status` 等 dirty diff；这些不是本轮新增，不要误回滚。

3. Local-photo-model 仓库也有既有 dirty 状态。

   已观察到：

   ```text
   D HANDOVER_20260530.md
   D HANDOVER_agent04_search_20260530.md
   M frontend/agent04/index.html
   M frontend/agent04/styles.css
   ?? HANDOVER_agent04_first_paint_performance_20260603.md
   ```

   本轮性能修复没有修改这些 Local-photo-model 业务/前端文件。

4. Browser MCP 导航/截图工具未暴露可用接口。

   已用完整 `npm test` 中的 browser tests 和临时服务 curl/status 验证替代。若明天需要肉眼验收，可打开当前修复版服务对应 URL。

## 下一步行动

1. 首先确认 3000 是否需要重启到当前修复版。

   当前 3000 是旧行为；若要让正式访问路径生效，需要重启 Web 发布服务。重启前先确认不要打断 TZ 当前正在使用的 3000 进程。

2. 重启后执行首屏性能复测：

   ```bash
   curl -sS -o /dev/null -w 'agent04 route total=%{time_total} starttransfer=%{time_starttransfer}\n' http://127.0.0.1:3000/agent04
   curl -sS -o /dev/null -w 'web status total=%{time_total} starttransfer=%{time_starttransfer}\n' http://127.0.0.1:3000/api/agent04/status
   curl -sS http://127.0.0.1:3000/api/agent04/status
   ```

   预期：

   - `/agent04` 接近 0.35s，而不是 3-8s。
   - 首次 status 可能为 `delta.state = "refreshing"`。
   - 几秒后 status 变为 `delta.state = "ready"` 和 `delta.source = "live"`。

3. 回归测试入口：

   ```bash
   cd /Users/tristanzh/agent/web
   node --test --test-concurrency=1 tests/agent04-service.test.mjs
   npm test
   ```

4. 接手时优先阅读：

   - `/Users/tristanzh/agent/web/server.mjs` 的 `createAgent04Runtime()`。
   - `/Users/tristanzh/agent/web/app/agent04.js` 的 `updateAgent04DeltaButton()` 和 `scheduleAgent04StatusRefresh()`。
   - `/Users/tristanzh/agent/web/tests/agent04-service.test.mjs` 中新增的两个性能测试。

5. 不要做的操作：

   - 不要执行 `/api/index/delta/run`，除非 TZ 明确进入相册差量更新 workflow。
   - 不要重建照片索引。
   - 不要调用 Ark 视觉模型。
   - 不要修改 shared sidebar。
   - 不要把该问题重新当成 CSS/layout 问题处理。
