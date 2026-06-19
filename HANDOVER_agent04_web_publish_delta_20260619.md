# Agent04 Web Publishing Delta Handover - 2026-06-19

## Purpose

This document extracts the Web-publishing-relevant changes from the Agent04 workflow so the Web publishing workflow can archive and verify them without mixing in Agent04 backend feature work.

Project path was renamed during the Agent repo split: old path `/Users/tristanzh/agent/Local-photo-model` now maps to `/Users/tristanzh/agent/agent04-lpm`.

## Boundaries

- Agent04 business repo: `/Users/tristanzh/agent/agent04-lpm`
- Web publishing host: `/Users/tristanzh/agent/web`
- Web route: `/agent04`
- Static frontend mount: `/agent04-static/index.html`
- Backend service expected by the published workbench: `http://127.0.0.1:8004`
- Shared platform rule: do not modify the shared sidebar unless TZ explicitly declares a `Shared Platform Change`.

## Sources Read

- `/Users/tristanzh/agent/agent04-lpm/AGENTS.md`
- `/Users/tristanzh/agent/web/config/agents/agent04.contract.json`
- `/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md`
- `/Users/tristanzh/agent/agent04-lpm/HANDOVER_agent04_web_publish_20260613.md`
- `/Users/tristanzh/agent/agent04-lpm/HANDOVER_agent04_repo_split_20260618.md`
- `/Users/tristanzh/agent/agent04-lpm/frontend/agent04/app.js`
- `/Users/tristanzh/agent/agent04-lpm/tests/test_frontend_agent04.py`

## Web Publishing Changes To Carry Forward

### 1. Embedded Agent04 frontend remains the published workbench

The Web shell should continue embedding Agent04 through:

```text
/agent04-static/index.html
```

The embedded static frontend is under:

```text
/Users/tristanzh/agent/agent04-lpm/frontend/agent04
```

The Web shell owns route integration, page chrome, status summary, and cross-agent regression. Agent04 owns search, face indexing, people profiles, and local photo rendering inside the embedded app.

### 2. Static frontend accepts Web-shell commands by message bridge

The Agent04 static frontend exposes:

- `window.limbAgent04SwitchTab`
- `window.limbAgent04RunSearch`
- `message` handling for `agent04:switch-tab`
- `message` handling for `agent04:run-search`

Publishing implication: `/agent04` can keep its route-owned search/tab controls in the shell and forward actions into the iframe/static workbench. Do not reintroduce duplicated local search controls in the embedded lower content unless the Web workflow deliberately changes the product design.

### 3. Search result images prioritize browser-renderable preview URLs

Search cards and lightbox now prefer renderable image URLs in this order:

```text
preview_url -> thumbnail_url -> url -> path
```

Publishing implication: Web/browser rendering must not depend on raw local `file://` paths or direct Photos Library paths. Published Agent04 pages should render images through backend-provided URLs, especially `/photos/...` URLs from the `8004` FastAPI service.

Relevant locked behavior:

- `normalizeResult()` preserves `preview_url`.
- `imagePreviewUrl()` centralizes preview selection.
- card images and lightbox images call `imagePreviewUrl(item)`.
- card images keep fallback handling through `data-fallback-src`.

### 4. Face reindex changed from long synchronous request to background job polling

The published interaction for "补扫相册人脸索引" should use:

- `POST http://127.0.0.1:8004/api/face/reindex`
- `GET http://127.0.0.1:8004/api/face/reindex/job`

Frontend behavior:

- Click starts the job with `POST /api/face/reindex`.
- If the backend returns `started` or `running`, the frontend polls `/api/face/reindex/job`.
- Poll interval is 1200 ms.
- UI status covers `started`, `running`, `completed`, `failed`, and `interrupted`.
- The button is disabled while the polling flow is active and re-enabled in `finally`.

Publishing implication: Web health checks and status managers should not assume this action completes inside one request. CPU-heavy local face scanning belongs to the Agent04 backend, while Web should display or tolerate job progress.

### 5. People profile panel reads Apple Photos inherited people as read-only

The static frontend reads:

```text
GET http://127.0.0.1:8004/api/people/profiles
```

Publishing behavior:

- Apple Photos people are grouped before manual LIMB profiles.
- Apple Photos profiles are shown as "Apple Photos 只读继承".
- Manual profiles remain under "人物库管理".
- Avatar URLs should be treated as backend-renderable URLs; fallback initials are used when avatars fail.

Publishing implication: Web copy and status should not imply that Agent04 writes back to Apple Photos. Apple Photos people are inherited/read-only.

### 6. Manual face profile management remains an Agent04 backend responsibility

The embedded frontend still owns manual profile actions:

- `POST http://127.0.0.1:8004/api/face/register`
- `DELETE http://127.0.0.1:8004/api/face/profiles/{label}`

Publishing implication: Web shell should not duplicate upload, profile mutation, or face vector logic. If Web exposes controls, they should forward into the embedded workbench or call documented backend APIs intentionally.

### 7. Web publishing docs already reflect key Agent04 backend endpoints

As of this handover, `/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md` already lists:

- `/agent04-static/index.html`
- `POST http://127.0.0.1:8004/api/search`
- `POST http://127.0.0.1:8004/api/register_member`
- `POST http://127.0.0.1:8004/api/face/reindex`
- `GET http://127.0.0.1:8004/api/face/reindex/job`
- `GET http://127.0.0.1:8004/api/people/profiles`
- `GET http://127.0.0.1:8004/photos/...`

The JSON contract currently lists only the Web-owned shell route API:

```json
"apiRoutes": ["/api/agent04/status"]
```

Treat that as Web-hosted API surface unless the Web workflow decides the contract schema should also enumerate backend passthrough/local-service APIs.

## Not Web Publishing Changes

These are Agent04 feature/runtime concerns, not Web-shell ownership:

- Apple Photos scanning and path resolution.
- SQLite / FTS5 / Jieba local retrieval.
- face embedding generation and local vector storage.
- `photo_face_index.pkl`, `face_profiles.pkl`, SQLite files, logs, and job JSON under `data/`.
- API-key/model routing configuration.
- repo split cleanup such as `AGENTS.md` scope correction or `backend/app_server.py` path correction.

## Current Web Workflow Risks

- Do not use stale old paths from pre-split handovers. Map `/Users/tristanzh/agent/Local-photo-model` to `/Users/tristanzh/agent/agent04-lpm`.
- Do not run `git stash pop` from `/Users/tristanzh/agent`.
- Do not commit or delete Agent04 runtime data under `data/`.
- Do not change `.ka-sidebar`, `.ka-nav`, global theme, or all-agent shell behavior unless TZ explicitly declares a `Shared Platform Change`.
- If visible `/agent04` changes are made, verify that Agent01/02/03 layouts are not affected.

## Suggested Web Publishing Verification

Run from the Web repo if Web files change:

```bash
cd /Users/tristanzh/agent/web
npm test -- tests/agent04-service.test.mjs
npm test -- tests/new-agent-publishing-contract.test.mjs
```

If `/Users/tristanzh/agent/web/server.mjs` changes, run the full Web test suite:

```bash
cd /Users/tristanzh/agent/web
npm test
```

Run from the Agent04 repo to verify embedded frontend expectations:

```bash
cd /Users/tristanzh/agent/agent04-lpm
python3 -m pytest tests/test_frontend_agent04.py::Agent04FrontendTests::test_face_reindex_button_starts_background_job_and_polls_status -q
python3 -m pytest tests/test_frontend_agent04.py::Agent04FrontendTests::test_search_cards_use_renderable_preview_url_before_thumbnail_or_asset_image -q
python3 -m pytest tests/test_frontend_agent04.py::Agent04FrontendTests::test_register_panel_lists_apple_photos_people_as_read_only_source -q
```

If local services are running, manually verify:

```bash
curl -sS --max-time 5 http://127.0.0.1:3000/agent04
curl -sS --max-time 5 http://127.0.0.1:3000/api/agent04/status
curl -sS --max-time 5 http://127.0.0.1:8004/api/health
curl -sS --max-time 5 http://127.0.0.1:8004/api/face/reindex/job
```

## Recommended Next Action For Web Publishing Workflow

1. Treat this document as the Agent04 publishing delta since the older `HANDOVER_agent04_web_publish_20260613.md`.
2. Re-read `/Users/tristanzh/agent/web/docs/agents/agent04-publishing-config.md`.
3. Confirm whether the Web contract JSON should remain limited to Web-hosted `/api/agent04/status` or should grow a separate local-backend API list.
4. Verify `/agent04` still embeds `/agent04-static/index.html` from `/Users/tristanzh/agent/agent04-lpm/frontend/agent04`.
5. Keep shared sidebar and global platform styles out of scope.
