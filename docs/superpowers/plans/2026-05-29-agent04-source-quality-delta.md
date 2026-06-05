# Agent04 Source Quality Delta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Agent04 original-versus-preview source-quality reporting and prevent derivative/original source swaps from creating model-consuming semantic delta.

**Architecture:** The backend remains the source of truth for Apple Photos asset inventory. `ArkSearchService` derives `source_quality` from `source_kind`, includes it in status and delta payloads, and treats stable `asset_id/local_identifier` matches as semantically current. The Web publishing server passes the object through to the Agent04 shell, where the header renders aggregate counts only.

**Tech Stack:** Python FastAPI service, SQLite index, Apple Photos read-only bridge, Node.js Web publishing server, browser JavaScript header refresh.

---

### Task 1: Backend Delta Semantics

**Files:**
- Modify: `tests/test_ark_main.py`
- Modify: `backend/ark_main.py`

- [ ] **Step 1: Write failing tests**

Add tests showing `source_path` replacement under the same `asset_id/local_identifier` does not increment `changed_count`, and source-quality counts are returned.

- [ ] **Step 2: Verify tests fail**

Run: `python3 -m unittest tests.test_ark_main.ArkMainTests.test_service_index_delta_treats_apple_source_swap_as_quality_transition tests.test_ark_main.ArkMainTests.test_service_index_status_reports_apple_source_quality`

Expected: FAIL because `source_quality` is absent or `changed_count` is still incremented.

- [ ] **Step 3: Implement minimal backend behavior**

Add a helper that counts `source_kind == "original"` and `source_kind == "derivative"` from Apple Photos assets. Use it in `index_status()` and `_index_delta_from_apple_assets()`. In Apple Photos delta logic, skip mtime-based `changed_count` when a row is matched by `asset_id` or `local_identifier`; count that as `source_file_changed_count` only when the matched indexed path differs from current `source_path`.

- [ ] **Step 4: Verify backend tests pass**

Run: `python3 -m unittest tests.test_ark_main.ArkMainTests.test_service_index_delta_treats_apple_source_swap_as_quality_transition tests.test_ark_main.ArkMainTests.test_service_index_status_reports_apple_source_quality`

Expected: PASS.

### Task 2: Web Status Passthrough And Header Label

**Files:**
- Modify: `/Users/tristanzh/agent/web/tests/agent04-service.test.mjs`
- Modify: `/Users/tristanzh/agent/web/server.mjs`
- Modify: `/Users/tristanzh/agent/web/app/agent04.js`

- [ ] **Step 1: Write failing tests**

Extend the Agent04 service test so the mocked backend returns `source_quality`, then assert `/api/agent04/status` includes the object and `/agent04` renders `索引 14,792 张 · 原图 12,000 · 预览图 2,795`.

- [ ] **Step 2: Verify tests fail**

Run: `cd /Users/tristanzh/agent/web && node --test tests/agent04-service.test.mjs`

Expected: FAIL because source-quality fields are not passed through or rendered.

- [ ] **Step 3: Implement minimal Web behavior**

Pass `source_quality` from backend status/delta into `status.index.source_quality`. Render the aggregate header text in `renderAgent04Page()` and `refreshAgent04Status()`.

- [ ] **Step 4: Verify Web tests pass**

Run: `cd /Users/tristanzh/agent/web && node --test tests/agent04-service.test.mjs`

Expected: PASS.

### Task 3: Final Verification

**Files:**
- Read only verification across backend and Web.

- [ ] **Step 1: Run syntax and targeted tests**

Run:

```bash
python3 -m compileall backend run_index_pipeline.py
python3 -m unittest tests.test_ark_main.ArkMainTests.test_service_index_delta_treats_apple_source_swap_as_quality_transition tests.test_ark_main.ArkMainTests.test_service_index_status_reports_apple_source_quality
cd /Users/tristanzh/agent/web && node --check server.mjs && node --test tests/agent04-service.test.mjs
```

Expected: all commands pass.
