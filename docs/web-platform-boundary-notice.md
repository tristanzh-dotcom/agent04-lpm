# Web Platform Boundary Notice

Date: 2026-05-26

This project is published through the shared Web publishing platform at `/Users/tristanzh/agent/web`.

## Classification

Any change that affects the Web-visible `/agent04` page, route registration, shared shell, shared sidebar, common theme, or platform tests must be classified before editing:

- `Agent Feature Change`: business logic inside this project.
- `Agent Publishing Change`: `/agent04` route-owned Web publishing surface or `/api/agent04/*`.
- `Shared Platform Change`: shared framework, shared sidebar, global CSS/theme, server common behavior, contract schema, or all-Agent test structure.

## Required Contract

Before changing Web publishing behavior, read:

```text
/Users/tristanzh/agent/web/config/agents/agent04.contract.json
```

Human-readable publishing config:

```text
/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md
```

## Hard Boundary

- Do not modify, hide, resize, replace, or restyle the shared Web `侧边栏`.
- Mandatory boundary: 不修改 shared 侧边栏.
- Web-visible CSS and layout changes must stay inside the Agent04 `右边栏` unless TZ explicitly declares a `Shared Platform Change`.
- Do not bypass `/Users/tristanzh/agent/web` to alter the 3000 publishing surface.

## Verification

For Web publishing changes, run the tests declared in the contract. For shared platform changes, run:

```bash
cd /Users/tristanzh/agent/web
npm run test:contracts
npm run test:all-agents
```
