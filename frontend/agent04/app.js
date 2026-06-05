(() => {
  const root = document.querySelector("#limb-workbench");
  if (!root) return;

  const apiBase = document.querySelector('meta[name="agent04-api-base"]')?.content?.replace(/\/$/, "") ?? "http://127.0.0.1:8004";
  const searchApi = `${apiBase}/api/search`;
  const randomPhotosApi = `${apiBase}/api/photos/random`;
  const statusApi = `${apiBase}/api/index/status`;
  const faceRegisterApi = `${apiBase}/api/face/register`;
  const faceProfilesApi = `${apiBase}/api/face/profiles`;
  const peopleProfilesApi = `${apiBase}/api/people/profiles`;
  const faceReindexApi = `${apiBase}/api/face/reindex`;

  const form = root.querySelector("[data-search-form]");
  const panels = root.querySelectorAll("[data-panel]");
  const statusEl = root.querySelector("[data-status]");
  const resultsEl = root.querySelector("[data-results]");
  const lightbox = root.querySelector("[data-lightbox]");
  const lightboxStage = root.querySelector("[data-lightbox-stage]");
  const lightboxImage = root.querySelector("[data-lightbox-image]");
  const lightboxHint = root.querySelector("[data-lightbox-hint]");
  const lightboxClose = root.querySelector("[data-lightbox-close]");
  const lightboxPrev = root.querySelector("[data-lightbox-prev]");
  const lightboxNext = root.querySelector("[data-lightbox-next]");
  const inspectorDescription = root.querySelector("[data-inspector-description]");
  const inspectorIdentity = root.querySelector("[data-inspector-identity]");
  const inspectorCapture = root.querySelector("[data-inspector-capture]");
  const inspectorTags = root.querySelector("[data-inspector-tags]");
  const inspectorPath = root.querySelector("[data-inspector-path]");
  const editForm = root.querySelector("[data-edit-form]");
  const copyPathButton = root.querySelector("[data-copy-path]");
  const editToggle = root.querySelector("[data-edit-toggle]");
  const editCancel = root.querySelector("[data-edit-cancel]");
  const similarButton = root.querySelector("[data-similar-button]");
  const similarTray = root.querySelector("[data-similar-tray]");
  const similarStrip = root.querySelector("[data-similar-strip]");
  const similarClear = root.querySelector("[data-similar-clear]");
  const deleteButton = root.querySelector("[data-delete-button]");
  const faceForm = root.querySelector("[data-face-form]");
  const faceFileInput = faceForm?.querySelector('input[type="file"]');
  const faceSubmitButton = root.querySelector("[data-face-submit]");
  const facePreviews = root.querySelector("[data-face-previews]");
  const photoSlots = root.querySelector("[data-photo-slots]");
  const faceStatus = root.querySelector("[data-face-status]");
  const dropzone = root.querySelector("[data-dropzone]");
  const profileList = root.querySelector("[data-profile-list]");
  const refreshProfilesButton = root.querySelector("[data-refresh-profiles]");
  const reindexButton = root.querySelector("[data-face-reindex]");
  const profileConfirmDialog = root.querySelector("[data-profile-confirm]");
  const profileConfirmLabel = root.querySelector("[data-profile-confirm-label]");
  const profileConfirmAccept = root.querySelector("[data-profile-confirm-accept]");
  const profileConfirmCancel = root.querySelector("[data-profile-confirm-cancel]");

  let allResults = [];
  let currentItem = null;
  let currentLightboxIndex = -1;
  let lightboxLoadToken = 0;
  let similarResults = [];
  let indexStatus = null;
  let lastSearchDiagnostic = null;
  let selectedFaceFiles = [];
  let facePreviewUrls = [];
  const resultStateStorageKey = "agent04:search-result-state:v1";

  const colorPalette = {
    红: "#c93d32",
    红色: "#c93d32",
    蓝: "#2968c8",
    蓝色: "#2968c8",
    绿: "#2f8754",
    绿色: "#2f8754",
    墨绿: "#18483b",
    黄: "#d8a72f",
    黄色: "#d8a72f",
    金色: "#c99b34",
    白: "#f3efe5",
    白色: "#f3efe5",
    黑: "#202322",
    黑色: "#202322",
    灰: "#8c9290",
    灰色: "#8c9290",
    橙: "#d87934",
    橙色: "#d87934",
    粉: "#df8eaa",
    粉色: "#df8eaa",
    紫: "#8067b7",
    紫色: "#8067b7",
    棕: "#7a5137",
    棕色: "#7a5137",
  };

  function setStatus(text) {
    statusEl.hidden = false;
    statusEl.textContent = text;
  }

  function readPersistedResultState() {
    try {
      return JSON.parse(window.localStorage?.getItem(resultStateStorageKey) || "null");
    } catch {
      return null;
    }
  }

  function writePersistedResultState(patch) {
    try {
      const current = readPersistedResultState() || {};
      window.localStorage?.setItem(
        resultStateStorageKey,
        JSON.stringify({ ...current, ...patch, updatedAt: new Date().toISOString() }),
      );
    } catch {
      // Search persistence is local UI state; live search remains authoritative.
    }
  }

  function renderEmpty(message) {
    resultsEl.classList.remove("is-loading");
    resultsEl.innerHTML = `<p class="limb-empty">${escapeHtml(message)}</p>`;
  }

  function diagnosticEmptyMessage(fallback) {
    if (lastSearchDiagnostic?.kind === "face_filter_empty") {
      return lastSearchDiagnostic.message || "已找到符合场景的照片，但没有照片同时匹配指定人物人脸。";
    }
    if (lastSearchDiagnostic?.kind === "face_profile_missing") {
      return lastSearchDiagnostic.message || "这个人物昵称尚未入库。请先到人物入库上传 3-5 张清晰人脸样张。";
    }
    return fallback;
  }

  function isSemanticIntersectionDiagnostic() {
    const kind = String(lastSearchDiagnostic?.kind || "");
    return kind.startsWith("semantic_") && kind.endsWith("_intersection_empty");
  }

  function setEditMode(enabled) {
    editForm.hidden = !enabled;
    editToggle.classList.toggle("is-active", enabled);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function splitList(value) {
    return String(value ?? "")
      .split(/[,，、\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function formValue(targetForm, name) {
    return String(targetForm?.elements?.namedItem(name)?.value ?? "");
  }

  function normalizeResult(item) {
    if (typeof item === "string") {
      return {
        md5: "",
        path: item,
        url: item,
        preview_url: item,
        thumbnail_url: item,
        description: item.replace(/^https?:\/\/127\.0\.0\.1:8004\/photos\//, ""),
        tags: [],
        colors: [],
        taken_at: null,
        location: null,
      };
    }
    return {
      md5: item.md5 ?? "",
      path: item.path ?? "",
      url: item.url ?? item.path ?? "",
      preview_url: item.preview_url ?? item.thumbnail_url ?? item.url ?? item.path ?? "",
      thumbnail_url: item.thumbnail_url ?? item.url ?? item.path ?? "",
      description: item.description ?? "",
      tags: Array.isArray(item.tags) ? item.tags : [],
      colors: Array.isArray(item.colors) ? item.colors : [],
      taken_at: item.taken_at ?? null,
      location: item.location ?? null,
      matched_labels: Array.isArray(item.matched_labels) ? item.matched_labels : [],
      face_score: typeof item.face_score === "number" ? item.face_score : null,
      semantic_miss: Boolean(item.semantic_miss),
    };
  }

  function imagePreviewUrl(item) {
    return item.preview_url || item.thumbnail_url || item.url || item.path || "";
  }

  function handleResultImageError(event) {
    const image = event.target;
    if (!image?.matches?.(".limb-photo-button img")) return;
    const fallback = image.dataset.fallbackSrc || "";
    if (fallback) {
      image.dataset.fallbackSrc = "";
      image.src = fallback;
      return;
    }
    image.closest(".limb-card")?.classList.add("is-image-error");
  }

  function setLightboxHint(text, state = "") {
    if (!lightboxHint || !lightboxStage) return;
    lightboxHint.textContent = text;
    lightboxStage.dataset.state = state;
  }

  function hideSimilarStrip() {
    similarResults = [];
    if (similarTray) similarTray.hidden = true;
    if (similarStrip) similarStrip.innerHTML = "";
  }

  function renderSkeleton() {
    resultsEl.classList.add("is-loading");
    resultsEl.innerHTML = Array.from({ length: 8 }, (_, index) => {
      const tone = 220 + (index % 4) * 46;
      return `<article class="limb-skeleton-card" style="height:${tone}px"><i></i><b></b><span></span></article>`;
    }).join("");
  }

  function visibleResults() {
    return allResults;
  }

  function circularIndex(index, length) {
    if (!length) return -1;
    return ((index % length) + length) % length;
  }

  function formatCaptureDate(value) {
    if (!value) return "拍摄时间：日期未记录";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return `拍摄时间：${String(value).slice(0, 16)}`;
    const year = parsed.getFullYear();
    const month = String(parsed.getMonth() + 1).padStart(2, "0");
    const day = String(parsed.getDate()).padStart(2, "0");
    const hour = String(parsed.getHours()).padStart(2, "0");
    const minute = String(parsed.getMinutes()).padStart(2, "0");
    return `拍摄时间：${year}-${month}-${day} ${hour}:${minute}`;
  }

  function formatCaptureLocation(location) {
    if (!location) return "拍摄地点：地点未记录";
    if (typeof location === "string") return `拍摄地点：${location || "地点未记录"}`;
    if (location.display_name) return `拍摄地点：${String(location.display_name)}`;
    if (location.text) return `拍摄地点：${String(location.text)}`;
    if (location.latitude != null && location.longitude != null) {
      return `拍摄地点：${Number(location.latitude).toFixed(6)}, ${Number(location.longitude).toFixed(6)}`;
    }
    return "拍摄地点：地点未记录";
  }

  function renderCards(visible) {
    resultsEl.innerHTML = visible.map((item, index) => {
      const faceBadge = item.matched_labels.length
        ? `<div class="limb-face-badge">${escapeHtml(item.matched_labels.join("，"))} · ${(item.face_score * 100).toFixed(0)}%</div>`
        : "";
      const semanticBadge = item.semantic_miss ? `<div class="limb-semantic-badge">场景词未命中，已按人物召回</div>` : "";
      const captureDate = formatCaptureDate(item.taken_at);
      const captureLocation = formatCaptureLocation(item.location);
      const previewUrl = imagePreviewUrl(item);
      const fallbackUrl = item.url && item.url !== previewUrl ? item.url : "";
      return `<article class="limb-card" data-result-index="${index}">
        <button type="button" class="limb-photo-button" data-open-index="${index}">
          <img loading="lazy" decoding="async" src="${escapeHtml(previewUrl)}" data-fallback-src="${escapeHtml(fallbackUrl)}" alt="${escapeHtml(item.description || "相册缩略图")}" onload="this.closest('.limb-card')?.classList.add('is-image-ready')" />
        </button>
        <div class="limb-card-meta">
          ${faceBadge}
          ${semanticBadge}
          <p title="${escapeHtml(item.description)}">${escapeHtml(item.description || "无描述")}</p>
          <div class="limb-card-capture" aria-label="拍摄信息">
            <span title="拍摄日期">${escapeHtml(captureDate)}</span>
            <span title="拍摄地点">${escapeHtml(captureLocation)}</span>
          </div>
        </div>
      </article>`;
    }).join("");
  }

  function renderResults() {
    const visible = visibleResults();
    resultsEl.classList.remove("is-loading");

    if (!visible.length) {
      const emptyMessage = indexStatus?.is_empty
        ? `当前 Ark 索引库为空。请先运行首航打标脚本，将 Apple Photos 写入 ${indexStatus.db_path || "SQLite 索引库"}。`
        : diagnosticEmptyMessage("当前描述下没有照片，换个关键词再试。");
      resultsEl.innerHTML = `<p class="limb-empty">${escapeHtml(emptyMessage)}</p>`;
      setStatus(`当前显示 0 / ${allResults.length} 张`);
      return;
    }

    renderCards(visible);
    if (isSemanticIntersectionDiagnostic()) {
      setStatus(lastSearchDiagnostic.message || `当前显示 ${visible.length} / ${allResults.length} 张，场景条件未命中，已降级返回人物照片`);
    } else {
      setStatus(`当前显示 ${visible.length} / ${allResults.length} 张`);
    }
  }

  function resetSearchScrollPosition() {
    const scrollTargets = [
      resultsEl,
      root,
      document.scrollingElement,
      document.documentElement,
      document.body,
    ];
    scrollTargets.forEach((target) => {
      if (!target) return;
      target.scrollTop = 0;
    });
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail ?? `后端返回 ${response.status}`);
    }
    const diagnosticHeader = response.headers.get("X-LIMB-Search-Diagnostic");
    if (diagnosticHeader) {
      try {
        lastSearchDiagnostic = JSON.parse(decodeURIComponent(diagnosticHeader));
      } catch {
        lastSearchDiagnostic = null;
      }
    } else if (url === searchApi) {
      lastSearchDiagnostic = null;
    }
    return response.json();
  }

  async function refreshIndexStatus() {
    try {
      indexStatus = await fetchJson(statusApi);
    } catch (error) {
      indexStatus = null;
      console.warn("[LIMB] 索引状态读取失败", error);
    }
    return indexStatus;
  }

  async function runSearch(query) {
    lastSearchDiagnostic = null;
    statusEl.hidden = false;
    setStatus("正在检索本地语义索引...");
    resetSearchScrollPosition();
    renderSkeleton();
    resetSearchScrollPosition();
    const payload = await fetchJson(searchApi, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query, limit: 160 }),
    });
    allResults = payload.map(normalizeResult);
    if (!allResults.length) {
      await refreshIndexStatus();
    }
    renderResults();
    resetSearchScrollPosition();
    writePersistedResultState({
      panel: "search",
      query,
      results: allResults,
      diagnostic: lastSearchDiagnostic,
    });
  }

  async function runSearchFromShell(query) {
    const normalizedQuery = String(query ?? "").trim();
    switchPanel("search");
    if (!normalizedQuery) {
      setStatus("请输入要搜索的中文描述");
      return;
    }
    if (form?.elements?.query) {
      form.elements.query.value = normalizedQuery;
    }
    await runSearch(normalizedQuery);
  }

  async function loadInitialGallery() {
    statusEl.hidden = true;
    resultsEl.classList.add("is-loading");
    resultsEl.innerHTML = Array.from({ length: 10 }, (_, index) => {
      const tone = 180 + (index % 5) * 42;
      return `<article class="limb-skeleton-card" style="height:${tone}px"><i></i><b></b><span></span></article>`;
    }).join("");
    try {
      const payload = await fetchJson(`${randomPhotosApi}?limit=24`);
      allResults = payload.map(normalizeResult);
      resultsEl.classList.remove("is-loading");
      if (allResults.length) {
        renderCards(allResults);
      } else {
        resultsEl.innerHTML = "";
      }
    } catch (error) {
      resultsEl.classList.remove("is-loading");
      resultsEl.innerHTML = "";
      console.warn("[LIMB] 初始随机相册读取失败", error);
    }
  }

  function showLightboxAt(index) {
    const visible = visibleResults();
    const nextIndex = circularIndex(index, visible.length);
    if (nextIndex < 0) return;
    currentLightboxIndex = nextIndex;
    openLightbox(visible[nextIndex]);
  }

  function openLightbox(item) {
    currentItem = item;
    const token = ++lightboxLoadToken;
    const previewUrl = imagePreviewUrl(item);
    const originalUrl = item.url || previewUrl;
    lightboxImage.src = previewUrl;
    setLightboxHint(originalUrl && originalUrl !== previewUrl ? "正在载入高清原图..." : "", "loading");
    if (originalUrl && originalUrl !== previewUrl) {
      const probe = new Image();
      probe.onload = () => {
        if (token !== lightboxLoadToken) return;
        lightboxImage.src = originalUrl;
        setLightboxHint("", "");
      };
      probe.onerror = () => {
        if (token !== lightboxLoadToken) return;
        lightboxImage.src = previewUrl;
        setLightboxHint("原图暂时被 macOS 照片库权限保护，已显示本地缩略图。", "fallback");
      };
      probe.src = originalUrl;
    } else {
      setLightboxHint("", "");
    }
    hideSimilarStrip();
    inspectorDescription.textContent = item.description || "暂无描述";
    if (item.semantic_miss) {
      inspectorDescription.textContent += "\n\n提示：场景词未命中，当前结果按人物召回。";
    }
    inspectorIdentity.textContent = item.matched_labels?.length
      ? `${item.matched_labels.join("，")} · ${(item.face_score * 100).toFixed(0)}%`
      : "未命中人物身份";
    inspectorCapture.innerHTML = `
      <span>${escapeHtml(formatCaptureDate(item.taken_at))}</span>
      <span>${escapeHtml(formatCaptureLocation(item.location))}</span>
    `;
    inspectorPath.textContent = item.path || item.url || "";
    inspectorTags.innerHTML = item.tags.length ? item.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") : "<em>暂无标签</em>";
    editForm.elements.description.value = item.description || "";
    editForm.elements.tags.value = item.tags.join("，");
    setEditMode(false);
    if (!lightbox.open) {
      document.body.classList.add("limb-modal-open");
      lightbox.show();
    }
  }

  async function openCurrentPhotoInNativeViewer() {
    if (!currentItem?.md5) {
      setLightboxHint("这张照片缺少索引 ID，无法唤起 macOS 图片查看器。", "fallback");
      return;
    }
    try {
      setLightboxHint("正在用 macOS 图片查看器打开原图...", "loading");
      const response = await fetch(`${apiBase}/api/photos/${encodeURIComponent(currentItem.md5)}/open`, {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `后端返回 ${response.status}`);
      if (payload.quality === "cached-thumbnail") {
        setLightboxHint("", "");
        return;
      }
      setLightboxHint("", "");
    } catch (error) {
      console.warn("[LIMB] macOS 图片查看器打开失败", error);
      setLightboxHint(`无法唤起 macOS 图片查看器：${error.message}`, "fallback");
    }
  }

  function closeLightbox() {
    lightboxLoadToken += 1;
    if (lightbox.open) lightbox.close();
    document.body.classList.remove("limb-modal-open");
    lightboxImage.removeAttribute("src");
    setLightboxHint("", "");
    setEditMode(false);
    hideSimilarStrip();
    currentItem = null;
    currentLightboxIndex = -1;
  }

  function replaceResult(updated) {
    const normalized = normalizeResult(updated);
    allResults = allResults.map((item) => (item.md5 && item.md5 === normalized.md5 ? normalized : item));
    currentItem = normalized;
    renderResults();
    const nextIndex = visibleResults().findIndex((item) => item.md5 && item.md5 === normalized.md5);
    showLightboxAt(nextIndex >= 0 ? nextIndex : 0);
  }

  function switchPanel(panelName) {
    closeLightbox();
    const nextPanel = panelName === "register" ? "register" : "search";
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.panel !== nextPanel;
    });
    writePersistedResultState({ panel: nextPanel });
    if (nextPanel === "register") {
      loadProfiles();
    }
  }

  function restorePersistedSearchResults() {
    const state = readPersistedResultState();
    if (!state || !Array.isArray(state.results) || !state.results.length) return false;
    lastSearchDiagnostic = state.diagnostic || null;
    allResults = state.results.map(normalizeResult);
    switchPanel(state.panel === "register" ? "register" : "search");
    if (form?.elements?.query && typeof state.query === "string") {
      form.elements.query.value = state.query;
    }
    renderResults();
    return true;
  }

  window.limbAgent04SwitchTab = switchPanel;
  window.limbAgent04RunSearch = runSearchFromShell;

  window.addEventListener("message", (event) => {
    if (event.data?.type === "agent04:switch-tab") {
      switchPanel(event.data.target);
    }
    if (event.data?.type === "agent04:run-search") {
      runSearchFromShell(event.data.query);
    }
  });

  function setFaceStatus(text) {
    if (faceStatus) faceStatus.textContent = text;
  }

  function revokeFacePreviewUrls() {
    facePreviewUrls.forEach((url) => URL.revokeObjectURL(url));
    facePreviewUrls = [];
  }

  function setSelectedFaceFiles(files, { append = false } = {}) {
    const incoming = [...files].filter((file) => file?.type?.startsWith("image/"));
    selectedFaceFiles = append ? [...selectedFaceFiles, ...incoming].slice(0, 5) : incoming.slice(0, 5);
    if (faceFileInput) faceFileInput.value = "";
    renderFacePreviews(selectedFaceFiles);
  }

  function removeSelectedFaceFile(index) {
    selectedFaceFiles = selectedFaceFiles.filter((_, fileIndex) => fileIndex !== index);
    if (faceFileInput) faceFileInput.value = "";
    renderFacePreviews(selectedFaceFiles);
  }

  function renderFacePreviews(files) {
    revokeFacePreviewUrls();
    const selected = [...files].slice(0, 5);
    const previewItems = selected.map((file, index) => {
      const url = URL.createObjectURL(file);
      facePreviewUrls.push(url);
      return { file, index, url };
    });
    if (facePreviews) {
      facePreviews.innerHTML = previewItems
        .map(({ file, index, url }) => {
          return `<figure><img src="${url}" alt="人脸样张 ${index + 1}" /><figcaption>${escapeHtml(file.name)}</figcaption></figure>`;
        })
        .join("");
    }
    if (!photoSlots) return;
    photoSlots.classList.toggle("is-empty", selected.length === 0);
    const slots = previewItems.map(({ index, url }) => {
      return `<figure class="limb-photo-slot is-filled">
        <img src="${url}" alt="人脸样张 ${index + 1}" />
        <button class="limb-photo-remove" type="button" data-remove-face-index="${index}" aria-label="删除这张样张">×</button>
      </figure>`;
    });
    if (selected.length < 5) {
      slots.push(`<button class="limb-photo-slot limb-photo-add" type="button" data-photo-add="" aria-label="继续添加照片">+</button>`);
    }
    photoSlots.innerHTML = slots.join("");
  }

  async function loadProfiles() {
    if (!profileList) return;
    profileList.innerHTML = "<p>人物库读取中...</p>";
    try {
      const profiles = await fetchJson(peopleProfilesApi);
      const manualProfiles = profiles.filter((profile) => profile.source !== "apple_photos");
      const appleProfiles = profiles.filter((profile) => profile.source === "apple_photos");
      profileList.innerHTML = profiles.length
        ? [
            renderProfileSection("人物库分组", "可删除，优先用于昵称精确检索", manualProfiles),
            renderProfileSection("Apple Photos 只读继承", "来自 macOS 照片人物/宠物识别，不写回相册", appleProfiles),
          ].join("")
        : "<p>还没有人物入库。</p>";
    } catch (error) {
      profileList.innerHTML = `<p>${escapeHtml(error instanceof Error ? error.message : "人物列表读取失败")}</p>`;
    }
  }

  function profileInitial(label) {
    return String(label || "?").trim().slice(0, 1).toUpperCase() || "?";
  }

  function handleProfileAvatarError(event) {
    const avatar = event.target.closest(".limb-profile-avatar");
    if (!avatar) return;
    avatar.classList.add("is-fallback");
    avatar.textContent = avatar.dataset.fallbackInitial || "?";
  }

  function renderProfileSection(title, subtitle, profiles) {
    if (!profiles.length) return "";
    return `<section class="limb-profile-group">
      <header>
        <strong>${escapeHtml(title)}</strong>
        <span class="limb-profile-summary">${escapeHtml(subtitle)}</span>
      </header>
      <div class="limb-profile-grid">
        ${profiles.map(renderProfileCard).join("")}
      </div>
    </section>`;
  }

  function renderProfileCard(profile) {
    const source = profile.source === "apple_photos" ? "apple_photos" : "limb_manual";
    const meta = source === "apple_photos"
      ? `${Number(profile.asset_count || 0)} 张照片 · ${Number(profile.face_count || 0)} 张人脸`
      : `${Number(profile.sample_count || 0)} 张样张 · ${escapeHtml(profile.updated_at || "已入库")}`;
    const action = source === "apple_photos"
      ? `<span class="limb-profile-readonly">只读继承</span>`
      : `<button class="limb-profile-delete" type="button" data-profile-delete="${escapeHtml(profile.label)}" aria-label="删除 ${escapeHtml(profile.label)}">删除</button>`;
    const initial = escapeHtml(profileInitial(profile.label));
    const avatar = profile.avatar_url
      ? `<img src="${escapeHtml(profile.avatar_url)}" alt="" loading="lazy" decoding="async" />`
      : initial;
    return `<article class="limb-profile-card" data-profile-source="${source}" title="${escapeHtml(meta)}">
      <div class="limb-profile-avatar${profile.avatar_url ? "" : " is-fallback"}" data-fallback-initial="${initial}">${avatar}</div>
      <div class="limb-profile-content">
        <strong>${escapeHtml(profile.label)}</strong>
        ${action}
      </div>
    </article>`;
  }

  function confirmProfileDelete(label) {
    if (!profileConfirmDialog || !profileConfirmAccept || !profileConfirmCancel || !profileConfirmLabel) {
      return Promise.resolve(false);
    }
    profileConfirmLabel.textContent = `确认删除 [${label}] 的人物向量库？删除后搜索将不再识别这个昵称。`;
    return new Promise((resolve) => {
      let settled = false;
      const finish = (confirmed) => {
        if (settled) return;
        settled = true;
        profileConfirmAccept.removeEventListener("click", handleAccept);
        profileConfirmCancel.removeEventListener("click", handleCancel);
        profileConfirmDialog.removeEventListener("cancel", handleCancel);
        profileConfirmDialog.removeEventListener("close", handleClose);
        if (profileConfirmDialog.open) profileConfirmDialog.close();
        resolve(confirmed);
      };
      const handleAccept = () => finish(true);
      const handleCancel = () => finish(false);
      const handleClose = () => finish(false);
      profileConfirmAccept.addEventListener("click", handleAccept);
      profileConfirmCancel.addEventListener("click", handleCancel);
      profileConfirmDialog.addEventListener("cancel", handleCancel);
      profileConfirmDialog.addEventListener("close", handleClose);
      profileConfirmDialog.showModal();
    });
  }

  async function submitFaceProfile(event) {
    event?.preventDefault?.();
    const label = formValue(faceForm, "label").trim();
    const files = selectedFaceFiles;
    if (!label) {
      setFaceStatus("请先输入人物昵称");
      return;
    }
    if (files.length < 3 || files.length > 5) {
      setFaceStatus("请上传 3-5 张清晰人脸照片");
      return;
    }

    const formData = new FormData();
    formData.append("label", label);
    files.forEach((file) => formData.append("files", file));
    const submitButton = faceSubmitButton || faceForm.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    submitButton.textContent = "模型训练中...";
    setFaceStatus(`正在为 [${label}] 提取本地人脸向量...`);
    try {
      const payload = await fetchJson(faceRegisterApi, { method: "POST", body: formData });
      setFaceStatus(payload.message || `成员 [${label}] 已成功精确锚定入库`);
      faceForm.reset();
      selectedFaceFiles = [];
      if (facePreviews) facePreviews.innerHTML = "";
      renderFacePreviews([]);
      await loadProfiles();
    } catch (error) {
      setFaceStatus(error instanceof Error ? error.message : "人物入库失败");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "开始学习";
    }
  }

  faceSubmitButton?.addEventListener("click", (event) => submitFaceProfile(event));

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = String(form.elements.query?.value ?? "").trim();
    if (!query) {
      setStatus("请输入要搜索的中文描述");
      return;
    }
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      await runSearch(query);
    } catch (error) {
      allResults = [];
      indexStatus = null;
      renderEmpty(error instanceof Error ? error.message : "搜索失败");
      setStatus("搜索失败");
    } finally {
      button.disabled = false;
    }
  });

  faceFileInput?.addEventListener("change", () => setSelectedFaceFiles(faceFileInput.files ?? [], { append: true }));
  photoSlots?.addEventListener("click", (event) => {
    const removeButton = event.target.closest("[data-remove-face-index]");
    if (removeButton) {
      event.preventDefault();
      event.stopPropagation();
      removeSelectedFaceFile(Number(removeButton.dataset.removeFaceIndex));
      return;
    }
    if (event.target.closest("[data-photo-add]")) {
      faceFileInput?.click();
    }
  });

  dropzone?.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragging");
  });

  dropzone?.addEventListener("dragleave", () => {
    dropzone.classList.remove("is-dragging");
  });

  dropzone?.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragging");
    if (!event.dataTransfer?.files?.length) return;
    setSelectedFaceFiles(event.dataTransfer.files, { append: true });
  });

  faceForm?.addEventListener("submit", submitFaceProfile);
  refreshProfilesButton?.addEventListener("click", loadProfiles);

  profileList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-profile-delete]");
    if (!button) return;
    const label = button.dataset.profileDelete || "";
    if (!label) return;
    if (!(await confirmProfileDelete(label))) return;
    button.disabled = true;
    setFaceStatus(`正在删除 [${label}] 的本地人脸向量...`);
    try {
      const payload = await fetchJson(`${faceProfilesApi}/${encodeURIComponent(label)}`, { method: "DELETE" });
      setFaceStatus(`成员 [${payload.label || label}] 已从本地向量库删除`);
      await loadProfiles();
    } catch (error) {
      setFaceStatus(error instanceof Error ? error.message : `删除 [${label}] 失败`);
      button.disabled = false;
    }
  });
  profileList?.addEventListener(
    "error",
    (event) => {
      if (event.target?.matches?.(".limb-profile-avatar img")) {
        handleProfileAvatarError(event);
      }
    },
    true
  );

  reindexButton?.addEventListener("click", async () => {
    reindexButton.disabled = true;
    setFaceStatus("正在补扫相册人脸索引，这一步会占用本地 CPU...");
    try {
      const payload = await fetchJson(faceReindexApi, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({}),
      });
      setFaceStatus(`人脸索引完成：新增/更新 ${payload.indexed}，跳过 ${payload.skipped}，失败 ${payload.failed}`);
    } catch (error) {
      setFaceStatus(error instanceof Error ? error.message : "人脸补扫失败");
    } finally {
      reindexButton.disabled = false;
    }
  });

  resultsEl?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-index]");
    if (!button) return;
    showLightboxAt(Number(button.dataset.openIndex));
  });
  resultsEl?.addEventListener("error", handleResultImageError, true);

  lightboxPrev?.addEventListener("click", (event) => {
    event.stopPropagation();
    showLightboxAt(currentLightboxIndex - 1);
  });

  lightboxNext?.addEventListener("click", (event) => {
    event.stopPropagation();
    showLightboxAt(currentLightboxIndex + 1);
  });

  lightboxImage?.addEventListener("click", (event) => {
    event.stopPropagation();
    openCurrentPhotoInNativeViewer();
  });

  function renderSimilarStrip(items) {
    if (!similarStrip || !similarTray) return;
    similarResults = items
      .map(normalizeResult)
      .filter((item) => imagePreviewUrl(item) && item.md5 !== currentItem?.md5)
      .slice(0, 12);
    similarStrip.innerHTML = similarResults.length
      ? similarResults.map((item, index) => `<button type="button" class="limb-similar-item" data-similar-index="${index}">
          <img src="${escapeHtml(imagePreviewUrl(item))}" alt="${escapeHtml(item.description || "相似照片")}" loading="lazy" decoding="async" />
          <span>${escapeHtml(item.description || "相似照片")}</span>
        </button>`).join("")
      : `<p>没有找到更多相似照片。</p>`;
    similarTray.hidden = false;
  }

  similarButton?.addEventListener("click", async () => {
    if (!currentItem) return;
    const query = currentItem.tags.slice(0, 5).join(" ") || currentItem.description;
    setLightboxHint("正在寻找相似照片...", "loading");
    try {
      const payload = await fetchJson(searchApi, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query, limit: 24 }),
      });
      renderSimilarStrip(payload);
      setLightboxHint("", "");
    } catch (error) {
      setLightboxHint(error instanceof Error ? error.message : "相似照片检索失败", "fallback");
    }
  });

  similarStrip?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-similar-index]");
    if (!button) return;
    const item = similarResults[Number(button.dataset.similarIndex)];
    if (item) openLightbox(item);
  });

  similarClear?.addEventListener("click", hideSimilarStrip);

  copyPathButton?.addEventListener("click", async () => {
    if (!currentItem) return;
    const text = currentItem.path || currentItem.url || "";
    try {
      await navigator.clipboard.writeText(text);
      setStatus("本地绝对路径已复制");
    } catch {
      window.prompt("复制本地绝对路径", text);
    }
  });

  editToggle?.addEventListener("click", () => {
    setEditMode(editForm.hidden);
  });

  editCancel?.addEventListener("click", () => {
    setEditMode(false);
  });

  editForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentItem?.md5) return;
    const submitButton = editForm.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    try {
      const updated = await fetchJson(`${apiBase}/api/search/photos/${encodeURIComponent(currentItem.md5)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          description: editForm.elements.description.value.trim(),
          tags: splitList(editForm.elements.tags.value),
          colors: currentItem.colors,
        }),
      });
      replaceResult(updated);
      setStatus("人工修正已写入 SQLite 索引");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "保存失败");
    } finally {
      submitButton.disabled = false;
    }
  });

  deleteButton?.addEventListener("click", async () => {
    if (!currentItem?.md5) return;
    const confirmed = window.confirm("确认从检索库移除？只会移除索引，不会删除 Apple Photos 原图。");
    if (!confirmed) return;
    deleteButton.disabled = true;
    try {
      await fetchJson(`${apiBase}/api/search/photos/${encodeURIComponent(currentItem.md5)}`, { method: "DELETE" });
      allResults = allResults.filter((item) => item.md5 !== currentItem.md5);
      renderResults();
      if (allResults.length) {
        showLightboxAt(currentLightboxIndex);
      } else {
        closeLightbox();
      }
      setStatus("索引记录和缩略图缓存已删除，原图未受影响");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "删除失败");
    } finally {
      deleteButton.disabled = false;
    }
  });

  lightboxClose?.addEventListener("click", closeLightbox);
  lightbox?.addEventListener("wheel", (event) => {
    event.stopPropagation();
  });
  lightbox?.addEventListener("click", (event) => {
    if (event.target === lightbox) closeLightbox();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && lightbox?.open) closeLightbox();
    if (event.key === "ArrowLeft" && lightbox?.open) {
      event.preventDefault();
      showLightboxAt(currentLightboxIndex - 1);
    }
    if (event.key === "ArrowRight" && lightbox?.open) {
      event.preventDefault();
      showLightboxAt(currentLightboxIndex + 1);
    }
  });

  if (!restorePersistedSearchResults()) loadInitialGallery();
  renderFacePreviews([]);
  window.addEventListener("beforeunload", revokeFacePreviewUrls);
})();
