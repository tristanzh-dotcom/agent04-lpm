# Agent04 首屏性能修复归档

日期：2026-06-03  
逻辑分支：Agent04 首屏性能修复  
关联上一分支：Agent04 照片显示修复  

## 问题描述

Web 发布页在切换到 Agent02、Agent03 时页面几乎立即出现，约 500ms 内完成；每次切换到 Agent04 本地图像检索时，页面需要等待约 3 秒以上才出现。重启 Web 服务后首次切到 Agent04 也稳定复现。

这不是 CSS、布局或显示格式问题，而是 Agent04 Web 发布入口的首屏性能问题。

## 当前判断

本问题应单独进入 `Agent04 首屏性能修复` 工作流，不应继续塞进 `Agent04 照片显示修复`。

分类：

- `Agent Publishing Change`
- 影响范围：`/Users/tristanzh/agent/web` 中 Agent04 route-owned 页面和 `/api/agent04/status` 状态读取链路
- 不属于 `Shared Platform Change`
- 不应修改 shared 侧边栏
- 不应触发相册差量同步
- 不应调用 Ark 视觉模型

## 根因证据

实测请求耗时：

```text
/agent02 route total ~= 0.001-0.002s
/agent03 route total ~= 0.001s
/agent04-static/index.html total ~= 0.001s
/agent04-static/app.js total ~= 0.001s
/agent04-static/styles.css total ~= 0.001s
http://127.0.0.1:8004/api/health total ~= 0.002s
http://127.0.0.1:8004/api/index/delta total ~= 3.7-4.0s 单请求
/api/agent04/status total ~= 3.9s 单请求
/agent04 route total ~= 3.9s 单请求
```

并发探测时，`/api/index/delta` 曾被拖到约 40s，说明该对账链路还有资源竞争或串行扫描放大的风险。

## 代码链路

Web 服务中 `/agent04` 当前服务端渲染路径：

```js
if (url.pathname === "/agent04") {
  const { activeTheme } = siteThemePayload(await readSiteThemeConfig(siteThemeConfigPath));
  const html = renderAgent04Page(await agent04Runtime.getStatus(), activeTheme);
  response.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": noStoreHeader });
  response.end(request.method === "HEAD" ? undefined : html);
  return;
}
```

`agent04Runtime.getStatus()` 当前会同步等待：

1. `lifecycle.ensureStarted()`
2. `readLiveIndexStatus()` -> `GET http://127.0.0.1:8004/api/index/status`
3. `readLiveIndexDelta()` -> `GET http://127.0.0.1:8004/api/index/delta`

实际慢点集中在第 3 步。`/api/index/delta` 会读取 Apple Photos 当前资产清单，并与 SQLite 索引全量对账。该操作是本地扫描/对账成本，不应阻塞 Web route 首屏 HTML 返回。

## 核心卡点

Agent04 的 Web route 把“首屏页面渲染”和“live delta 对账”绑定在同一个同步请求里。

因此用户切换到 `/agent04` 时，浏览器不是先看到页面再异步刷新状态，而是必须等待后端完成 Apple Photos delta 对账后才拿到 HTML。

## 建议修复方向

进入新对话后按 SDD -> TDD -> 业务逻辑推进。

建议接口设计目标：

- `/agent04` 首屏 HTML 不等待 `/api/index/delta`
- `/agent04` 可用 cached/fallback index status 立即渲染
- delta 状态由前端异步刷新，或由 Web 服务短 TTL 缓存提供
- `/api/agent04/status` 可以保留 live 能力，但应区分 fast status 与 full delta status
- delta 对账不能在多个并发请求中重复触发长扫描；需要 in-flight 复用或 TTL 缓存

可选设计：

1. `getStatus({ includeDelta: false })` 用于 `/agent04` 首屏。
2. `/api/agent04/status` 默认返回快速状态，附带 `delta.state = "refreshing" | "ready" | "stale"`。
3. 新增或复用异步刷新逻辑，在后台计算 `/api/index/delta`，完成后缓存结果。
4. 前端 `refreshAgent04Status()` 异步读取后更新“发现 N 张待更新 / 相册已同步”按钮。

## 推荐测试

Web 侧测试文件：

```text
/Users/tristanzh/agent/web/tests/agent04-service.test.mjs
```

需要新增或调整的测试点：

- `/agent04` 不应等待慢速 `/api/index/delta` 才返回 HTML。
- 慢速 delta fetch 存在时，`/agent04` 仍能快速渲染 iframe shell。
- `/api/agent04/status` 在设计后的 fast path 下应能返回可用状态。
- delta button 在初始状态未知时应有明确状态，例如“同步状态读取中”，异步刷新后再变为“发现 N 张待更新”或“相册已同步”。
- Agent02、Agent03 route 不受影响。
- 不修改 shared sidebar。

## 复现命令

```bash
curl -sS -o /dev/null -w 'agent02 route total=%{time_total} starttransfer=%{time_starttransfer}\n' http://127.0.0.1:3000/agent02
curl -sS -o /dev/null -w 'agent03 route total=%{time_total} starttransfer=%{time_starttransfer}\n' http://127.0.0.1:3000/agent03
curl -sS -o /dev/null -w 'agent04 route total=%{time_total} starttransfer=%{time_starttransfer}\n' http://127.0.0.1:3000/agent04
curl -sS -o /dev/null -w 'web status total=%{time_total} starttransfer=%{time_starttransfer}\n' http://127.0.0.1:3000/api/agent04/status
curl -sS -o /dev/null -w 'backend delta total=%{time_total} starttransfer=%{time_starttransfer}\n' http://127.0.0.1:8004/api/index/delta
```

## 操作边界

新对话执行修复前必须先读取：

```text
/Users/tristanzh/agent/Local-photo-model/AGENTS.md
/Users/tristanzh/agent/web/config/agents/agent04.contract.json
/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md
```

不要做：

- 不要执行 `/api/index/delta/run`
- 不要重建照片索引
- 不要调用 Ark 视觉模型
- 不要修改 shared 侧边栏
- 不要把这个问题当作 CSS 或布局优化处理

## 建议启动语

```text
请读取并完全理解当前目录下的 `HANDOVER_agent04_first_paint_performance_20260603.md`。
请将本对话逻辑分支锁定为：【Agent04 首屏性能修复】。
先复述当前核心卡点、边界分类和建议 SDD/TDD 下一步，等待我确认后再执行。
```
