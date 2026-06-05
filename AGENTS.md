# AGENTS.md - Local Photo Model

Scope: `/Users/tristanzh/agent/Local-photo-model`.

## Web Publishing Boundary

This project publishes through the shared Web platform at `/Users/tristanzh/agent/web`.

Before changing any Web-visible Agent04 behavior, read:

```text
/Users/tristanzh/agent/web/config/agents/agent04.contract.json
```

Human-readable publishing config:

```text
/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md
```

Classify each Web-visible change before editing:

- `Agent Feature Change`: local photo indexing, search, Apple Photos integration, face profile, and backend logic.
- `Agent Publishing Change`: `/agent04` route-owned page, CSS, iframe workbench, and `/api/agent04/*` endpoints.
- `Shared Platform Change`: shared sidebar, shared framework, global theme, server common behavior, contract schema, or all-agent tests.

Hard rule: 不修改 shared 侧边栏 unless TZ explicitly declares a `Shared Platform Change`.

