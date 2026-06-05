# PhotoKit Prefetch State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-blocking PhotoKit original prefetch state machine while preserving current filesystem-indexed search.

**Architecture:** `backend/apple_photos_bridge.py` owns local-original checks and optional PhotoKit wakeup. `backend/ark_index_engine.py` gains asset metadata compatibility fields. `backend/ark_main.py` schedules prefetch in `BackgroundTasks` after search results are ready.

**Tech Stack:** FastAPI BackgroundTasks, SQLite migrations, PyObjC optional runtime, Python unittest.

---

### Task 1: PhotoKit Bridge

**Files:**
- Create: `backend/apple_photos_bridge.py`
- Test: `tests/test_apple_photos_bridge.py`

- [ ] RED: write tests proving local existing files skip requester and missing files call requester.
- [ ] GREEN: implement `stable_asset_id`, `PhotoKitOriginalPrefetcher`, and `prefetch_originals_if_needed`.

### Task 2: SQLite Asset Metadata Compatibility

**Files:**
- Modify: `backend/ark_index_engine.py`
- Test: `tests/test_ark_index_engine.py`

- [ ] RED: write test that `upsert_photo` accepts asset metadata and `search` returns it.
- [ ] GREEN: add nullable asset columns and return metadata in search rows.

### Task 3: FastAPI Background Prefetch

**Files:**
- Modify: `backend/ark_main.py`
- Test: `tests/test_ark_main.py`

- [ ] RED: write test that search schedules prefetch for rows with local identifiers.
- [ ] GREEN: inject `BackgroundTasks`, return JSON immediately, preserve diagnostics header.

### Task 4: Verification

**Commands:**
- `python3 -m unittest discover -s tests`
- `python3 -m compileall backend tests run_index_pipeline.py`
- `node --check frontend/agent04/app.js`
