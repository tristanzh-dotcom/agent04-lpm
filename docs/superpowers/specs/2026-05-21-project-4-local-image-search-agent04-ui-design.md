# 项目 4 本地图像检索 Agent04 UI Design

Date: 2026-05-21
Project: 项目 4 本地图像检索界面设计与前端发布项目
Route: `http://127.0.0.1:3000/agent04`
Frontend sandbox: `/Users/tristanzh/agent/Local-photo-model/frontend/agent04/`
Backend sandbox: `http://127.0.0.1:8004`

## Goal

Build a right-side-only 本地图像检索 interaction surface for the local publishing platform. The interface must preserve the global left Sidebar, avoid all full-page refreshes, and make search and face registration feel fluid even when the backend is working over 14591 Apple Photos assets.

## Non-Negotiable Boundaries

- All Phase 4 frontend files live under `frontend/agent04/`.
- The route is owned by the local publishing platform at `/agent04`; 本地图像检索 must not assume ownership of the global shell or Sidebar.
- 本地图像检索 code must never modify or depend on left Sidebar DOM.
- All right-side forms must call `event.preventDefault()`.
- Internal view switching must be JavaScript state switching, not navigation.
- API calls use only port `8004`.
- The legacy files `frontend/index.html` and `frontend/admin.html` are treated as reference material only.

## Architecture

Phase 4 uses a single-page right-side workbench. The page contains two internal panels:

- Search panel: semantic query, loading skeleton, result carousel, empty/error states.
- Register panel: label input, drag-and-drop upload, thumbnail preview, training status, success feedback.

The page is plain HTML5, CSS3, and vanilla ES6. There is no npm build step. Swiper.js may be loaded by CDN or by a local vendor file if the publishing platform requires offline-first operation.

## File Layout

```text
frontend/agent04/
├── index.html
├── styles.css
└── app.js
```

Responsibilities:

- `index.html`: static right-side markup only, including the root `.agent04-shell`.
- `styles.css`: scoped UI styling using `.agent04-` and `.limb-` prefixes.
- `app.js`: state machine, fetch calls, Swiper lifecycle, drag/drop, thumbnail previews, error handling.

## DOM Structure

```text
.agent04-shell
  .limb-toolbar
    .limb-tabs
      button[data-view="search"]
      button[data-view="register"]
    .limb-service-state
  section.limb-panel[data-panel="search"]
    form.limb-search-form
    .limb-stage
      .limb-skeleton
      .limb-empty
      .limb-error
      .swiper.limb-swiper
    button.limb-load-more
  section.limb-panel[data-panel="register"]
    form.limb-register-form
      input[name="label"]
      input[type="file"][multiple]
      .limb-dropzone
      .limb-preview-grid
      .limb-register-status
```

Only the active panel is visible. Hidden panels remain mounted to preserve input state.

## State Model

The UI keeps a small state object:

```js
{
  view: "search",
  query: "",
  loading: false,
  resultUrls: [],
  visibleUrls: [],
  nextOffset: 0,
  selectedFiles: [],
  registerStatus: "idle"
}
```

View changes update CSS classes and ARIA attributes only. They do not change `window.location`, do not submit forms, and do not touch platform-level DOM.

## API Contracts

### Search

Request:

```http
POST http://127.0.0.1:8004/api/search
Content-Type: application/json
```

```json
{
  "query": "查找小菲、爸爸和卫士车同时出现的照片"
}
```

Response:

```json
[
  "http://127.0.0.1:8004/photos/resources/derivatives/masters/A/example.jpeg"
]
```

Client behavior:

- Show skeleton immediately.
- Wait for response.
- Keep only top 12 URLs for first render.
- Store the remaining URLs in an internal queue.
- Render a “继续载入 12 张” button when more URLs exist.

### Register Member

Request:

```http
POST http://127.0.0.1:8004/api/register_member
Content-Type: multipart/form-data
```

Fields:

- `label`: member label, for example `小菲`
- `files`: multiple image files

Accepted success response shapes:

```json
{
  "label": "小菲",
  "vector_dim": 512,
  "registered_photos": 3
}
```

or:

```json
{
  "status": "success",
  "message": "成员 [小菲] 已成功精确锚定入库"
}
```

Client behavior:

- Show local thumbnails immediately using `URL.createObjectURL`.
- Change submit button text to `模型训练中...`.
- Disable submit while uploading.
- On success, show `成员 [小菲] 已成功精确锚定入库`.
- Offer a right-panel-only transition back to search.

## Streaming And Performance

The first render must never insert the full backend result set into the DOM.

Rules:

- First batch: 12 slides.
- Next batches: 12 slides per click.
- Images use lazy loading.
- Slides have stable dimensions to avoid layout shifts.
- Swiper is destroyed and rebuilt after each new search.
- Object URLs created for upload previews are revoked when files are cleared or replaced.

Swiper configuration target:

```js
new Swiper(".limb-swiper", {
  slidesPerView: 1,
  spaceBetween: 16,
  lazy: true,
  preloadImages: false,
  watchSlidesProgress: true,
  keyboard: { enabled: true },
  navigation: {
    nextEl: ".limb-next",
    prevEl: ".limb-prev"
  },
  pagination: {
    el: ".limb-pagination",
    clickable: true
  }
});
```

## Loading, Empty, And Error States

Search loading:

- Show a skeleton band with soft shimmer or pulse.
- Keep toolbar usable, but disable duplicate search submissions.

Empty result:

```text
没有命中照片。可以尝试更宽泛的描述，或先确认对应人物已经完成标记入库。
```

Backend unavailable:

```text
8004 后端服务暂时不可达。
```

Missing DeepSeek key:

```text
语义翻译服务未配置，请检查 backend/config.py。
```

Register no-face error:

```text
未检测到可注册人脸，请换清晰正脸照片。
```

All errors stay inside the right-side 本地图像检索 panel. No global alert is used.

## Visual Direction

The interface should feel like a local media control room rather than a marketing page:

- Dense but calm operational surface.
- Large image stage, restrained controls, clear status affordances.
- No hero section, no page-level marketing copy.
- No nested cards.
- Cards are used only for repeated previews or modal-like contained states.
- Text must not overflow buttons or panels on desktop or mobile.

Suggested palette:

- Deep neutral base for the image stage.
- Warm amber or green accent for active states.
- Separate red/orange only for errors.

Typography:

- Use native macOS Chinese-friendly font stack unless a local font is already provided by the platform.
- Do not use viewport-scaled font sizes.
- Letter spacing stays `0`.

## Accessibility

- Tabs use `aria-selected`.
- Hidden panels use `hidden` or `aria-hidden`.
- Dropzone has keyboard activation.
- Buttons have explicit labels.
- Loading state uses `aria-busy`.
- Error and success messages use `aria-live="polite"`.

## Testing Plan

Manual tests:

1. Open `http://127.0.0.1:3000/agent04`.
2. Switch between search and register panels repeatedly. The left Sidebar must not change.
3. Submit search. The browser URL must not change.
4. During search, skeleton appears and duplicate submit is disabled.
5. Search result renders no more than 12 slides initially.
6. “继续载入 12 张” appends only the next batch.
7. Drag 3 images into register panel. Thumbnails appear without upload.
8. Submit registration. Button changes to `模型训练中...`, then success appears in the panel.
9. Trigger backend-offline state by stopping port 8004. Error appears inside right panel only.

Automated or scripted checks:

- Verify all API URLs point to `127.0.0.1:8004`.
- Verify no form submit changes `window.location.href`.
- Verify `frontend/agent04/` contains all Phase 4 static assets.
- Verify no selectors target global Sidebar ids/classes.

## Out Of Scope

- Rebuilding the global publishing platform Sidebar.
- Changing backend vector search algorithm.
- Re-indexing Apple Photos.
- Moving model files or changing the persistent pickle format.
- Adding npm, React, Vue, or a build pipeline.

## Handoff Notes

The backend engine is stable and already owns the search math. Phase 4 should optimize the right-side experience around that engine: route isolation, smooth AJAX state transitions, bounded DOM work, lazy image loading, and useful local error messaging.
