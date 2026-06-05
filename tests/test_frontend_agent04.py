import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def css_rule(styles, selector):
    exact_marker = f"\n{selector} {{"
    marker = exact_marker if exact_marker in styles else f"\n{selector}"
    start = styles.index(marker)
    block_start = styles.index("{", start)
    end = styles.index("\n}", block_start) + 2
    return styles[start:end]


class Agent04FrontendTests(unittest.TestCase):
    def test_face_register_form_uses_explicit_named_item_lookup(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("namedItem(name)", app_js)
        self.assertNotIn("faceForm.elements.label?.value", app_js)

    def test_face_register_form_lets_javascript_show_validation_feedback(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")

        self.assertIn('class="limb-face-form"', index_html)
        self.assertIn("data-face-form", index_html)
        self.assertIn("novalidate", index_html)

    def test_register_panel_uses_clear_three_part_workflow(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        register_panel = index_html[index_html.index('<section class="limb-register-panel"') : index_html.index('<dialog class="limb-lightbox"')]

        self.assertIn("limb-register-form-card", register_panel)
        self.assertNotIn("limb-register-status-card", register_panel)
        self.assertIn("limb-profile-board", register_panel)
        self.assertIn("新增人物", register_panel)
        self.assertNotIn("入库状态", register_panel)
        self.assertIn("人物库管理", register_panel)
        self.assertNotIn("搜索描述", register_panel)
        self.assertNotIn("data-face-reindex", register_panel[register_panel.index("limb-face-input-row"):register_panel.index("</form>")])
        self.assertIn("data-face-reindex", register_panel[register_panel.index("limb-profile-board"):])
        self.assertIn("grid-template-columns: minmax(0, 1fr);", styles)
        self.assertNotIn(".limb-register-status-card", styles)

    def test_register_panel_removes_developer_kickers_and_uses_compact_feedback(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        register_panel = index_html[index_html.index('<section class="limb-register-panel"') : index_html.index('<dialog class="limb-lightbox"')]

        self.assertNotIn("FACE VECTOR LIBRARY", register_panel)
        self.assertNotIn("LOCAL ONLY", register_panel)
        self.assertNotIn("limb-kicker", register_panel)
        self.assertIn("limb-face-feedback", register_panel)
        self.assertIn("data-face-status", register_panel)
        self.assertIn(".limb-face-feedback", styles)
        title_rule = css_rule(styles, ".limb-register-title")
        self.assertIn("font-size: 20px;", title_rule)

    def test_register_submit_and_status_are_in_title_action_row(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        register_panel = index_html[index_html.index('<section class="limb-register-panel"') : index_html.index('<dialog class="limb-lightbox"')]
        card = register_panel[register_panel.index('<section class="limb-register-form-card"') : register_panel.index('<div class="limb-profile-board"')]
        controls = card[card.index('<div class="limb-register-controls"') :]
        form = register_panel[register_panel.index('<form class="limb-face-form"') : register_panel.index('</form>')]

        self.assertIn("limb-register-controls", register_panel)
        self.assertIn("开始学习", controls)
        self.assertIn("data-face-status", controls)
        self.assertNotIn("开始学习", form)
        self.assertNotIn("data-face-status", form)
        self.assertLess(controls.index("limb-register-title"), controls.index("人物昵称"))
        self.assertLess(controls.index("人物昵称"), controls.index("data-face-submit"))
        self.assertLess(controls.index("data-face-submit"), controls.index("data-face-status"))
        self.assertLess(card.index("limb-register-controls"), card.index("limb-face-form"))
        form_card_rule = css_rule(styles, ".limb-register-form-card")
        self.assertIn("display: grid;", form_card_rule)
        self.assertIn("grid-template-columns: minmax(210px, 260px) minmax(560px, 660px);", form_card_rule)
        self.assertIn("justify-content: center;", form_card_rule)

    def test_register_panel_compacts_to_two_layers(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        register_panel = index_html[index_html.index('<section class="limb-register-panel"') : index_html.index('<dialog class="limb-lightbox"')]

        self.assertLess(register_panel.index("limb-face-input-row"), register_panel.index("limb-dropzone"))
        self.assertLess(register_panel.index("data-face-submit"), register_panel.index("limb-dropzone"))
        self.assertNotIn('<p>上传 3-5 张清晰人脸样张，保存为 LIMB 本地昵称特征。</p>', register_panel)
        self.assertIn("limb-register-title", register_panel)
        self.assertIn("limb-register-form-card", register_panel)
        form_rule = styles[styles.index(".limb-face-form") : styles.index(".limb-face-form label")]
        self.assertIn("padding: 0;", form_rule)
        self.assertIn("border: 0;", form_rule)
        dropzone_rule = styles[styles.index(".limb-dropzone") : styles.index(".limb-dropzone.is-dragging")]
        self.assertIn("min-height: 118px;", dropzone_rule)

    def test_register_form_uses_short_nickname_input_and_photo_slots(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        register_panel = index_html[index_html.index('<section class="limb-register-panel"') : index_html.index('<dialog class="limb-lightbox"')]

        self.assertIn("limb-face-input-row", register_panel)
        self.assertIn('maxlength="8"', register_panel)
        self.assertNotIn("limb-file-button", register_panel)
        self.assertNotIn("data-file-trigger", register_panel)
        self.assertNotIn("选择照片", register_panel)
        self.assertIn("limb-photo-slots", register_panel)
        self.assertIn("data-photo-slots", register_panel)
        self.assertIn("limb-photo-add", app_js)
        self.assertIn("slice(0, 5)", app_js)
        self.assertIn("faceFileInput?.click()", app_js)
        self.assertNotIn("faceFileTrigger", app_js)
        self.assertIn(".limb-face-input-row", styles)
        self.assertIn("display: flex;", styles[styles.index(".limb-face-input-row") : styles.index(".limb-face-form input", styles.index(".limb-face-input-row"))])
        self.assertNotIn(".limb-file-button", styles)
        self.assertIn(".limb-photo-slots", styles)
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr));", styles)

    def test_register_card_uses_single_horizontal_strip_with_controls_next_to_photo_slots(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        register_card = index_html[index_html.index('<section class="limb-register-form-card"') : index_html.index('<div class="limb-profile-board"')]
        card_rule = css_rule(styles, ".limb-register-form-card")
        controls_rule = css_rule(styles, ".limb-register-controls")
        input_row_rule = css_rule(styles, ".limb-face-input-row")
        feedback_rule = css_rule(styles, ".limb-face-feedback")
        submit_button_rule = css_rule(styles, ".limb-face-input-row button")
        nickname_input_rule = css_rule(styles, '.limb-face-input-row input[type="text"]')
        slot_rule = css_rule(styles, ".limb-photo-slot")

        self.assertIn("<span>人物昵称</span>", register_card)
        self.assertLess(register_card.index("limb-register-title"), register_card.index("limb-face-input-row"))
        self.assertLess(register_card.index("limb-face-input-row"), register_card.index("limb-dropzone"))
        self.assertLess(register_card.index("<input"), register_card.index("data-face-submit"))
        self.assertLess(register_card.index("data-face-submit"), register_card.index("data-face-status"))
        self.assertIn("display: grid;", card_rule)
        self.assertIn("grid-template-columns: minmax(210px, 260px) minmax(560px, 660px);", card_rule)
        self.assertIn("justify-content: center;", card_rule)
        self.assertIn("align-items: center;", card_rule)
        self.assertIn("display: grid;", controls_rule)
        self.assertIn("grid-template-rows: auto auto auto;", controls_rule)
        self.assertIn("justify-items: start;", controls_rule)
        self.assertIn("gap: 10px;", controls_rule)
        self.assertIn("display: flex;", input_row_rule)
        self.assertIn("align-items: center;", input_row_rule)
        self.assertIn("flex: 0 0 auto;", submit_button_rule)
        self.assertIn("width: 8em;", nickname_input_rule)
        self.assertIn("min-height: 34px;", nickname_input_rule)
        self.assertIn("font-size: 12px;", nickname_input_rule)
        self.assertIn("min-height: 34px;", submit_button_rule)
        self.assertIn("font-size: 12px;", submit_button_rule)
        self.assertIn("background: transparent;", feedback_rule)
        self.assertIn("border: 0;", feedback_rule)
        self.assertIn("width: 100%;", feedback_rule)
        self.assertIn("text-align: left;", feedback_rule)
        self.assertIn("justify-content: flex-start;", feedback_rule)
        self.assertIn("white-space: normal;", feedback_rule)
        self.assertIn("justify-self: stretch;", feedback_rule)
        self.assertIn("height: 118px;", slot_rule)
        self.assertIn(".limb-face-input-row input[type=\"text\"]", styles)
        self.assertIn(".limb-face-form input[type=\"text\"]", styles)

    def test_face_learning_button_click_runs_js_validation_before_backend_request(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        register_head = index_html[index_html.index('<section class="limb-register-form-card"') : index_html.index('<div class="limb-profile-board"')]
        submit_fn = app_js[app_js.index("async function submitFaceProfile") : app_js.index("form?.addEventListener")]
        submit_listener = app_js[app_js.index('faceSubmitButton?.addEventListener("click"') : app_js.index('form?.addEventListener')]
        submit_button = register_head[register_head.index("<button") : register_head.index("</button>", register_head.index("data-face-submit"))]

        self.assertIn("data-face-submit", register_head)
        self.assertIn('type="button"', submit_button)
        self.assertNotIn('type="submit"', submit_button)
        self.assertNotIn('form="limb-face-form"', submit_button)
        self.assertIn("const faceSubmitButton", app_js)
        self.assertIn("faceSubmitButton?.addEventListener(\"click\"", app_js)
        self.assertIn("submitFaceProfile(event)", submit_listener)
        self.assertIn("event?.preventDefault?.();", submit_fn)
        self.assertLess(submit_fn.index("请上传 3-5 张清晰人脸照片"), submit_fn.index("fetchJson(faceRegisterApi"))

    def test_photo_slots_render_only_selected_photos_plus_one_add_button(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        render_fn = app_js[app_js.index("function renderFacePreviews") : app_js.index("async function loadProfiles")]

        self.assertIn("selectedFaceFiles", app_js)
        self.assertIn("facePreviewUrls", app_js)
        self.assertIn("revokeFacePreviewUrls", app_js)
        self.assertIn("setSelectedFaceFiles", app_js)
        self.assertIn("append = false", app_js)
        self.assertIn("selectedFaceFiles = append", app_js)
        self.assertIn("URL.revokeObjectURL", app_js)
        self.assertIn("selected.length < 5", render_fn)
        self.assertIn("limb-photo-add", render_fn)
        self.assertIn('photoSlots.classList.toggle("is-empty"', render_fn)
        self.assertNotIn("<span", render_fn)
        self.assertNotIn("while (slots.length < 5)", render_fn)
        slot_rule = styles[styles.index(".limb-photo-slot") : styles.index(".limb-photo-slot img")]
        self.assertIn("margin: 0;", slot_rule)
        self.assertIn("aspect-ratio: 1;", slot_rule)
        self.assertIn("width: 100%;", slot_rule)
        self.assertIn("height: 118px;", slot_rule)
        self.assertIn("gap: 4px;", styles[styles.index(".limb-photo-slots") : styles.index(".limb-photo-slot {")])
        empty_rule = styles[styles.index(".limb-photo-slots.is-empty .limb-photo-add") : styles.index(".limb-photo-slot {")]
        self.assertIn("grid-column: 3;", empty_rule)
        self.assertNotIn("grid-template-columns:", empty_rule)

    def test_selected_face_photos_can_be_removed_before_learning(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        render_fn = app_js[app_js.index("function renderFacePreviews") : app_js.index("async function loadProfiles")]

        self.assertIn("removeSelectedFaceFile", app_js)
        self.assertIn("data-remove-face-index", render_fn)
        self.assertIn("删除这张样张", render_fn)
        self.assertIn('event.target.closest("[data-remove-face-index]")', app_js)
        self.assertIn("selectedFaceFiles.filter", app_js)
        self.assertIn(".limb-photo-remove", styles)
        remove_rule = styles[styles.index(".limb-photo-remove") : styles.index(".limb-photo-remove:hover")]
        self.assertIn("position: absolute;", remove_rule)
        self.assertIn("right: 4px;", remove_rule)
        self.assertIn("top: 4px;", remove_rule)

    def test_profile_delete_uses_centered_in_app_confirm_dialog(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        profile_click_handler = app_js[app_js.index('profileList?.addEventListener("click"') : app_js.index('profileList?.addEventListener(\n    "error"')]
        dialog_markup = index_html[index_html.index('<dialog class="limb-confirm-dialog"') : index_html.index('<dialog class="limb-lightbox"')]
        dialog_rule = styles[styles.index(".limb-confirm-dialog") : styles.index(".limb-confirm-dialog::backdrop")]

        self.assertIn("limb-confirm-dialog", dialog_markup)
        self.assertIn("data-profile-confirm-label", dialog_markup)
        self.assertIn("data-profile-confirm-accept", dialog_markup)
        self.assertIn("data-profile-confirm-cancel", dialog_markup)
        self.assertIn("confirmProfileDelete", app_js)
        self.assertIn("showModal()", app_js)
        self.assertIn("await confirmProfileDelete(label)", profile_click_handler)
        self.assertNotIn("confirm(`确认删除", profile_click_handler)
        self.assertIn("position: fixed;", dialog_rule)
        self.assertIn("inset: 0;", dialog_rule)
        self.assertIn("margin: auto;", dialog_rule)

    def test_register_panel_lists_apple_photos_people_as_read_only_source(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("/api/people/profiles", app_js)
        self.assertIn("apple_photos", app_js)
        self.assertIn("Apple Photos 只读继承", app_js)
        self.assertIn("人物库分组", app_js)
        self.assertIn("data-profile-source", app_js)

    def test_profile_management_shows_loading_state_before_fetching_people(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        load_profiles = app_js[app_js.index("async function loadProfiles") : app_js.index("function profileInitial")]

        self.assertIn("人物库读取中", load_profiles)
        self.assertLess(load_profiles.index("人物库读取中"), load_profiles.index("await fetchJson(peopleProfilesApi)"))

    def test_search_status_handles_all_semantic_intersection_diagnostics(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function isSemanticIntersectionDiagnostic", app_js)
        self.assertIn('String(lastSearchDiagnostic?.kind || "")', app_js)
        self.assertIn('kind.startsWith("semantic_")', app_js)
        self.assertIn('kind.endsWith("_intersection_empty")', app_js)
        self.assertIn("场景条件未命中", app_js)

    def test_profile_management_groups_manual_before_apple_photos_with_visual_cards(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("const manualProfiles", app_js)
        self.assertIn("const appleProfiles", app_js)
        self.assertLess(app_js.index("manualProfiles"), app_js.index("appleProfiles"))
        self.assertIn("人物库分组", app_js)
        self.assertIn("Apple Photos 只读继承", app_js)
        self.assertIn("renderProfileSection", app_js)
        self.assertIn("limb-profile-avatar", app_js)
        self.assertIn("profile.avatar_url", app_js)
        self.assertIn("<img", app_js[app_js.index("function renderProfileCard"):app_js.index("async function submitFaceProfile")])
        self.assertIn("handleProfileAvatarError", app_js)
        self.assertIn("data-fallback-initial", app_js)
        self.assertIn("limb-profile-group", app_js)
        self.assertIn("limb-profile-delete", app_js)
        self.assertIn("limb-profile-readonly", app_js)
        self.assertIn(".limb-profile-avatar", styles)
        self.assertIn(".limb-profile-avatar img", styles)
        self.assertIn(".limb-profile-avatar.is-fallback", styles)
        self.assertIn(".limb-profile-delete", styles)
        delete_rule = styles[styles.index(".limb-profile-delete") : styles.index(".limb-profile-delete:hover")]
        self.assertIn("position: static;", delete_rule)
        self.assertNotIn("right:", delete_rule)
        self.assertNotIn("bottom:", delete_rule)

    def test_profile_group_header_is_compact_single_line_to_prioritize_images(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        section_fn = app_js[app_js.index("function renderProfileSection") : app_js.index("function renderProfileCard")]
        header_rule = styles[styles.index(".limb-profile-group header") : styles.index(".limb-profile-group header strong")]
        group_rule = styles[styles.index(".limb-profile-group {") : styles.index(".limb-profile-group header")]

        self.assertIn('class="limb-profile-summary"', section_fn)
        self.assertNotIn("<div>", section_fn)
        self.assertIn("align-items: center;", header_rule)
        self.assertIn("flex-wrap: nowrap;", header_rule)
        self.assertIn("white-space: nowrap;", styles[styles.index(".limb-profile-summary") : styles.index(".limb-profile-group header strong")])
        self.assertIn("gap: 8px;", group_rule)
        self.assertIn("padding: 8px;", group_rule)

    def test_profile_cards_prioritize_large_image_over_metadata_text(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        card_fn = app_js[app_js.index("function renderProfileCard") : app_js.index("async function submitFaceProfile")]
        card_rule = css_rule(styles, ".limb-profile-card")
        avatar_rule = css_rule(styles, ".limb-profile-avatar")
        content_rule = css_rule(styles, ".limb-profile-content")

        self.assertNotIn("<span>${escapeHtml(meta)}</span>", card_fn)
        self.assertNotIn("<em>", card_fn)
        self.assertNotIn("sourceLabel", card_fn)
        self.assertLess(card_fn.index("<strong>${escapeHtml(profile.label)}</strong>"), card_fn.index("${action}"))
        self.assertIn('title="${escapeHtml(meta)}"', card_fn)
        grid_rule = css_rule(styles, ".limb-profile-grid")
        self.assertIn("grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));", grid_rule)
        self.assertIn("gap: 8px;", grid_rule)
        self.assertIn("grid-template-rows: minmax(118px, 1fr) auto;", card_rule)
        self.assertIn("grid-template-columns: 1fr;", card_rule)
        self.assertIn("padding: 7px;", card_rule)
        self.assertIn("height: 118px;", avatar_rule)
        self.assertIn("width: 100%;", avatar_rule)
        self.assertIn("display: flex;", content_rule)
        self.assertIn("justify-content: space-between;", content_rule)
        self.assertIn("font-size: 16px;", styles[styles.index(".limb-profile-list strong") : styles.index(".limb-profile-list span")])

    def test_agent04_static_search_panel_no_longer_owns_search_form(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        search_panel = index_html[index_html.index('<section class="limb-search-panel"'):index_html.index('<section class="limb-register-panel"')]

        self.assertNotIn("limb-command", index_html)
        self.assertNotIn("data-search-form", search_panel)
        self.assertNotIn('id="limb-query"', search_panel)
        self.assertNotIn("开始搜索", search_panel)
        self.assertIn('data-status hidden', search_panel)
        self.assertNotIn("输入一句人话描述，照片会以响应式瀑布流在这里展开。", search_panel)

    def test_search_cards_use_renderable_preview_url_before_thumbnail_or_asset_image(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        render_fn = app_js[app_js.index("function renderCards") : app_js.index("function renderResults")]
        lightbox_fn = app_js[app_js.index("function openLightbox") : app_js.index("function closeLightbox")]

        self.assertIn("preview_url: item.preview_url", app_js)
        self.assertIn("function imagePreviewUrl", app_js)
        self.assertIn("imagePreviewUrl(item)", render_fn)
        self.assertIn("data-fallback-src", render_fn)
        self.assertIn("imagePreviewUrl(item)", lightbox_fn)
        self.assertLess(lightbox_fn.index("imagePreviewUrl(item)"), lightbox_fn.index("item.url || previewUrl"))

    def test_agent04_local_tabs_are_removed_from_lower_content(self):
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")

        self.assertNotIn(".limb-local-tabs", styles)
        self.assertNotIn(".limb-panel-switch", styles)

    def test_agent04_lower_content_removes_large_title_block_and_local_tabs(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn('<section class="limb-command"', index_html)
        self.assertNotIn("LIMB ARK WORKBENCH", index_html)
        self.assertNotIn("<h1>本地相册检索工作台</h1>", index_html)
        self.assertNotIn('<nav class="limb-local-tabs limb-panel-switch"', index_html)
        self.assertNotIn('data-tab-target="search"', index_html)
        self.assertNotIn('data-tab-target="register"', index_html)

    def test_agent04_keeps_panel_switching_api_for_publishing_header(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("window.limbAgent04SwitchTab = switchPanel", app_js)
        self.assertIn('type === "agent04:switch-tab"', app_js)

    def test_agent04_keeps_search_api_for_publishing_top_panel(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("window.limbAgent04RunSearch", app_js)
        self.assertIn('type === "agent04:run-search"', app_js)
        self.assertIn("/api/photos/random", app_js)
        self.assertIn("loadInitialGallery", app_js)
        self.assertIn("statusEl.hidden = true", app_js)

    def test_lightbox_has_previous_and_next_controls(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")

        self.assertIn("data-lightbox-prev", index_html)
        self.assertIn("data-lightbox-next", index_html)
        self.assertIn("data-lightbox-back", index_html)
        self.assertIn("返回", index_html)

    def test_lightbox_back_button_lives_in_inspector_not_over_photo(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")

        lightbox_outer = index_html[index_html.index('<dialog class="limb-lightbox"') : index_html.index('<div class="limb-lightbox-stage"')]
        inspector_panel = index_html[index_html.index('<aside class="limb-inspector">') : index_html.index('<p data-inspector-description')]
        inspector_head = index_html[index_html.index('<div class="limb-inspector-head">') : index_html.index("</div>", index_html.index('<div class="limb-inspector-head">'))]

        self.assertIn("data-lightbox-back", lightbox_outer)
        self.assertNotIn("data-lightbox-back", inspector_panel)
        self.assertNotIn("data-lightbox-back", inspector_head)
        self.assertIn(".limb-lightbox-back", styles)
        self.assertIn("padding: 0;", styles[styles.index(".limb-lightbox {") : styles.index(".limb-lightbox::backdrop")])
        self.assertIn("position: absolute;", styles[styles.index(".limb-lightbox-back") : styles.index(".limb-lightbox-back:hover")])
        self.assertIn("top: 50%;", styles[styles.index(".limb-lightbox-back") : styles.index(".limb-lightbox-back:hover")])
        self.assertIn("right: 10px;", styles[styles.index(".limb-lightbox-back") : styles.index(".limb-lightbox-back:hover")])
        self.assertIn("transform: translateY(-50%);", styles[styles.index(".limb-lightbox-back") : styles.index(".limb-lightbox-back:hover")])
        self.assertNotIn("left: 14px;", styles[styles.index(".limb-lightbox-back") : styles.index(".limb-lightbox-back:hover")])

    def test_lightbox_primary_actions_are_in_inspector_header(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")

        inspector_head = index_html[index_html.index('<div class="limb-inspector-head">') : index_html.index('<p data-inspector-description')]

        self.assertNotIn("limb-kicker", inspector_head)
        self.assertNotIn("data-inspector-title", inspector_head)
        self.assertIn("data-similar-button", inspector_head)
        self.assertIn("hidden", inspector_head[inspector_head.index("data-similar-button"):inspector_head.index("data-copy-path")])
        self.assertIn("相似照片功能保留，当前按产品决策隐藏入口", index_html)
        self.assertIn("data-copy-path", inspector_head)
        self.assertIn("limb-inspector-quick-actions", inspector_head)
        self.assertIn(".limb-inspector-quick-actions", styles)
        self.assertIn("grid-template-columns: auto auto 1fr;", styles)
        self.assertIn("align-items: center;", css_rule(styles, ".limb-inspector-head"))

    def test_lightbox_keeps_photo_and_inspector_visually_separated(self):
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        open_rule = styles[styles.index(".limb-lightbox[open]") : styles.index(".limb-lightbox-stage")]
        stage_img_rule = styles[styles.index(".limb-lightbox-stage img") : styles.index(".limb-lightbox-nav")]

        self.assertIn("column-gap: 8px;", open_rule)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);", open_rule)
        self.assertIn("grid-template-rows: minmax(0, 1fr);", open_rule)
        self.assertIn("align-items: stretch;", open_rule)
        self.assertIn("inset: 8px;", styles[styles.index(".limb-lightbox {") : styles.index(".limb-lightbox::backdrop")])
        self.assertIn("width: calc(100vw - 16px);", styles[styles.index(".limb-lightbox {") : styles.index(".limb-lightbox::backdrop")])
        self.assertIn("height: calc(100vh - 16px);", styles[styles.index(".limb-lightbox {") : styles.index(".limb-lightbox::backdrop")])
        self.assertIn("position: absolute;", stage_img_rule)
        self.assertIn("inset: 0;", stage_img_rule)
        self.assertIn("\n  width: 100%;", stage_img_rule)
        self.assertIn("\n  height: 100%;", stage_img_rule)
        self.assertIn("object-fit: contain !important;", stage_img_rule)
        self.assertIn("object-position: center center;", stage_img_rule)

    def test_lightbox_backdrop_does_not_blur_underlying_gallery(self):
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        backdrop_rule = styles[styles.index(".limb-lightbox::backdrop") : styles.index(".limb-lightbox[open]")]

        self.assertIn("background: #040707;", backdrop_rule)
        self.assertIn("backdrop-filter: none;", backdrop_rule)
        self.assertNotIn("blur(", backdrop_rule)

    def test_lightbox_inspector_removes_debug_fields_and_uses_advanced_details(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("照片信息", index_html)
        self.assertIn("data-inspector-identity", index_html)
        self.assertIn("data-inspector-capture", index_html)
        self.assertIn("data-advanced-toggle", index_html)
        self.assertIn("data-advanced-panel", index_html)
        self.assertIn("从检索库移除", index_html)
        self.assertNotIn("INSPECTOR", index_html)
        self.assertNotIn("MD5", app_js)
        self.assertNotIn("data-inspector-colors", index_html)
        self.assertNotIn("主色调", index_html)

    def test_similar_results_render_as_horizontal_filmstrip_inside_lightbox(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("data-similar-strip", index_html)
        self.assertIn("renderSimilarStrip", app_js)
        self.assertIn("limb-similar-strip", styles)
        self.assertIn("grid-auto-flow: column", styles)
        self.assertNotIn("closeLightbox();\n    await runSearchFromShell(query);", app_js)

    def test_lightbox_navigation_uses_circular_result_index(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function circularIndex", app_js)
        self.assertIn("showLightboxAt(currentLightboxIndex - 1)", app_js)
        self.assertIn("showLightboxAt(currentLightboxIndex + 1)", app_js)
        self.assertIn('event.key === "ArrowLeft"', app_js)
        self.assertIn('event.key === "ArrowRight"', app_js)

    def test_clicking_lightbox_image_opens_native_macos_viewer(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("data-open-native-image", index_html)
        self.assertIn("function openCurrentPhotoInNativeViewer", app_js)
        self.assertIn('fetch(`${apiBase}/api/photos/${encodeURIComponent(currentItem.md5)}/open`', app_js)
        self.assertIn('method: "POST"', app_js)
        self.assertIn('payload.quality === "cached-thumbnail"', app_js)
        self.assertIn('setLightboxHint("", "")', app_js[app_js.index('payload.quality === "cached-thumbnail"'):])
        self.assertNotIn("完全磁盘访问权限", app_js)
        self.assertNotIn("已打开 LIMB 缓存缩略图", app_js)
        self.assertIn("payload.detail", app_js)
        open_function = app_js[app_js.index("async function openCurrentPhotoInNativeViewer") : app_js.index("function closeLightbox")]
        self.assertNotIn("closeLightbox();", open_function)
        self.assertIn('lightboxImage?.addEventListener("click"', app_js)
        self.assertIn("currentItem.md5", app_js)

    def test_visible_product_copy_does_not_expose_limb_project_codename(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("<title>本地图像检索</title>", index_html)
        self.assertIn("人物库分组", app_js)
        self.assertIn("确认从检索库移除？", app_js)
        self.assertNotIn("agent04 LIMB Ark 相册工作台", index_html)
        self.assertNotIn("LIMB 本地人物库", app_js)
        self.assertNotIn("确认从 LIMB 检索库移除这张照片？", app_js)

    def test_static_page_closes_agent04_app_script_tag(self):
        index_html = (PROJECT_ROOT / "frontend" / "agent04" / "index.html").read_text(encoding="utf-8")

        self.assertIn('<script src="/agent04-static/app.js?v=20260602-preview-url"></script>', index_html)
        self.assertNotIn('<script src="/agent04-static/app.js?v=20260602-preview-url">\n', index_html)

    def test_new_search_resets_result_scroll_position(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function resetSearchScrollPosition", app_js)
        reset_function = app_js[
            app_js.index("function resetSearchScrollPosition") : app_js.index("async function runSearch")
        ]
        run_search_function = app_js[
            app_js.index("async function runSearch") : app_js.index("async function runSearchFromShell")
        ]

        self.assertIn("resultsEl", reset_function)
        self.assertIn("document.scrollingElement", reset_function)
        self.assertIn("target.scrollTop = 0", reset_function)
        self.assertGreaterEqual(run_search_function.count("resetSearchScrollPosition();"), 2)

    def test_lightbox_never_blocks_publishing_header_switching(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        switch_function = app_js[app_js.index("function switchPanel") : app_js.index("window.limbAgent04SwitchTab")]
        open_lightbox_function = app_js[app_js.index("function openLightbox") : app_js.index("async function openCurrentPhotoInNativeViewer")]

        self.assertNotIn("showModal", open_lightbox_function)
        self.assertIn("lightbox.show();", app_js)
        self.assertIn("closeLightbox();", switch_function)
        hidden_rule = styles[styles.index(".limb-modal-open .limb-search-panel") : styles.index(".limb-modal-open .limb-lightbox")]
        self.assertIn("visibility: hidden;", hidden_rule)
        self.assertIn(".limb-modal-open .limb-lightbox", styles)
        self.assertIn("visibility: visible;", styles[styles.index(".limb-modal-open .limb-lightbox"):])
        self.assertNotIn("pointer-events: none;", styles[styles.index(".limb-modal-open"):styles.index(".limb-search-panel")])

    def test_result_cards_show_capture_metadata_instead_of_tags_and_colors(self):
        app_js = (PROJECT_ROOT / "frontend" / "agent04" / "app.js").read_text(encoding="utf-8")

        self.assertIn("taken_at: item.taken_at", app_js)
        self.assertIn("location: item.location", app_js)
        self.assertIn("function formatCaptureDate", app_js)
        self.assertIn("function formatCaptureLocation", app_js)
        self.assertIn("拍摄时间：", app_js)
        self.assertIn("拍摄地点：", app_js)
        self.assertIn("location.display_name", app_js)
        self.assertIn('class="limb-card-capture"', app_js)
        self.assertNotIn('class="limb-card-tags"', app_js)
        self.assertNotIn('class="limb-card-colors"', app_js)

    def test_result_card_capture_metadata_uses_regular_font_weight(self):
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        start = styles.index(".limb-card-capture span")
        end = styles.index(".limb-card-color", start)
        block = styles[start:end]

        self.assertIn("font-weight: 400;", block)
        self.assertNotIn("font-weight: 760;", block)

    def test_result_gallery_uses_row_filling_grid_instead_of_css_columns(self):
        styles = (PROJECT_ROOT / "frontend" / "agent04" / "styles.css").read_text(encoding="utf-8")
        start = styles.index(".limb-masonry {")
        end = styles.index(".limb-masonry.is-loading", start)
        masonry_rule = styles[start:end]

        self.assertIn("display: grid;", masonry_rule)
        self.assertIn("grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));", masonry_rule)
        self.assertIn("gap: 14px;", masonry_rule)
        self.assertIn("align-items: start;", masonry_rule)
        self.assertNotIn("column-count", masonry_rule)
        self.assertNotIn("column-gap", masonry_rule)
        self.assertNotIn(".limb-masonry {\n    column-count:", styles)


if __name__ == "__main__":
    unittest.main()
