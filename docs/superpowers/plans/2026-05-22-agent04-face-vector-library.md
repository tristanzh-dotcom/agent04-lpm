# Agent04 Face Vector Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real local face-vector profile library to Agent04 so users can register nicknames with 3-5 face photos and search by nickname.

**Architecture:** Keep Ark + SQLite as the semantic search layer. Add `backend/face_engine.py` as an isolated local face embedding layer backed by `face_profiles.pkl` and `photo_face_index.pkl`, then let `ark_main.py` combine semantic candidates with face matching when a registered nickname appears in the query.

**Tech Stack:** FastAPI, Pillow, NumPy, optional InsightFace/ONNX Runtime, vanilla HTML/CSS/JS for `/frontend/agent04/`.

---

### Task 1: Face Engine Core

**Files:**
- Create: `backend/face_engine.py`
- Test: `tests/test_face_engine.py`

- [ ] Write failing tests for profile averaging, threshold matching, and photo indexing.
- [ ] Implement `FaceVectorEngine` with injectable detector for unit tests.
- [ ] Verify targeted tests pass.

### Task 2: FastAPI Integration

**Files:**
- Modify: `backend/ark_main.py`
- Test: `tests/test_ark_face_api.py`

- [ ] Write failing tests for `/api/face/register`, `/api/face/profiles`, `/api/face/reindex`, and search fusion.
- [ ] Implement API routes and search fusion.
- [ ] Verify API tests pass.

### Task 3: Frontend Agent04 Profile UI

**Files:**
- Modify: `frontend/agent04/index.html`
- Modify: `frontend/agent04/app.js`
- Modify: `frontend/agent04/styles.css`

- [ ] Add local tabs inside the Agent04 right-side canvas.
- [ ] Add nickname registration form with 3-5 image previews.
- [ ] Add profile list and face match metadata in search results.
- [ ] Verify browser interaction against local service.

### Task 4: Dependencies and Verification

**Files:**
- Modify: `backend/requirements.txt`

- [ ] Add local face embedding runtime dependencies.
- [ ] Run compileall and full unit tests.
- [ ] Restart local workspace and smoke test `/agent04`.
