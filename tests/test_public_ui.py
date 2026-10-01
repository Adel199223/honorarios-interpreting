from pathlib import Path
import json
import re
import subprocess


from scripts.local_app_smoke import run_smoke


from test_public_candidate_smoke import PublicCandidateSmokeTests


class PublicUiTests(PublicCandidateSmokeTests):
    def test_homepage_exposes_browser_flow_landmarks(self):
        client = self.make_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.text
        for text in [
            "LegalPDF Honorários",
            "Guided Interpretation",
            "Start Interpretation Request",
            "guided-intake-steps",
            "Upload source",
            "Review what was found",
            "Answer questions",
            "Preview PDF",
            "Draft email",
            "advanced-intake-fields",
            "Show advanced intake fields",
            "advanced-workflow-panel",
            "Advanced",
            "Batch tools and direct PDF generation stay hidden here until needed.",
            "Show batch tools",
            "What I found",
            "What I still need",
            "beginner-review-panel hidden",
            "technical-actions-menu",
            "advanced-status-details",
            "Refresh app data",
            "Open JSON reference",
            "Reset workspace",
            "Add source file",
            "Review source",
            "Choose one local notification PDF, photo, or screenshot, then click Review source.",
            "Source reviewed. Continue in Review Case Details",
            "Change source",
            "Recover PDF",
            "Recover photo",
            "Or drop/paste a source here",
            "Other source options",
            "Best result: upload the original or downloaded photo when you can.",
            "Supporting proof / declarations",
            "Add supporting attachments",
            "Review Interpretation Request",
            "Google Photos selected-photo import",
            "Open Google Photos Picker",
            "Batch Queue",
            "Packet mode",
            "Packet item inspector",
            "Packet draft recording helper",
            "Gmail handoff checklist",
            "LegalPDF Integration Preview",
            "Build integration checklist",
            "Build adapter import plan",
            "LegalPDF Adapter Contract",
            "LegalPDF Apply History",
            "LegalPDF Restore Plan",
            "Refresh apply history",
            "Restore Confirmation Phrase",
            "RESTORE LOCAL HONORARIOS BACKUP",
            "Restore Reason",
            "Local Diagnostics",
            "Source upload smoke",
            "Supporting attachment smoke",
            "Copy isolated source upload smoke command",
            "Copy isolated attachment smoke command",
            "Copy LegalPDF adapter readiness command",
            "Copy advanced Gmail API smoke command",
            "Copy Browser/IAB review smoke command",
            "Copy Browser/IAB upload smoke command",
            "Copy Browser/IAB attachment smoke command",
            "Copy Browser/IAB answers/apply smoke command",
            "Copy Browser/IAB attachment stale smoke command",
            "Copy Browser/IAB record helper smoke command",
            "Copy Python browser record helper smoke command",
            "Copy Browser/IAB Recent Work smoke command",
            "Preview destination diff",
            "Preview guarded destination",
            "Preview court-email diff",
            "Preview guarded court email",
            "Public GitHub Readiness",
            "Run tracked Git gate",
            "Gmail Draft API",
            "Email safety",
            "Creates Gmail drafts only.",
            "You review and send manually in Gmail.",
            "Draft-only Gmail",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, page)
        self.assertNotIn("Uses `_create_draft` only.", page)
        self.assertNotIn('id="questions"', page)
        self.assertIn('class="panel workspace-panel batch-queue-panel advanced-workflow-panel hidden"', page)
        self.assertIn('id="review-intake" class="primary-button hidden"', page)
        self.assertIn('class="app-status-details advanced-status-details"', page)
        style_css = Path(__file__).resolve().parents[1].joinpath("honorarios_app", "static", "style.css").read_text(encoding="utf-8")
        self.assertIn(".technical-actions-content .app-status-details", style_css)
        self.assertNotIn('<details class="app-status-details">', page)
        self.assertIn('class="secondary-upload-options"', page)
        self.assertIn('class="supporting-attachment-details"', page)
        self.assertIn("Review recovered details", page)
        self.assertIn("Enter details manually", page)
        self.assertIn("Clear review", page)
        app_js = Path(__file__).resolve().parents[1].joinpath("honorarios_app", "static", "app.js").read_text(encoding="utf-8")
        self.assertIn('$("#review-intake")?.classList.toggle("hidden", !hasReviewableIntake)', app_js)
        self.assertIn(".simple-task-shell:not(.has-review) .advanced-intake-fields", style_css)
        self.assertIn(".simple-task-shell:not(.has-review) .supporting-attachment-details", style_css)
        self.assertLess(page.index('id="source-upload-form"'), page.index('id="source-drop-zone"'))
        self.assertLess(page.index('id="source-drop-zone"'), page.index('class="upload-grid primary-upload-grid"'))
        self.assertNotIn("Guided Translation", page)
        self.assertNotIn("not a separate task", page)
        self.assertNotIn("_send_email", page)
        self.assertNotIn("_send_draft", page)
        self.assertNotIn("messages.send", page)
        self.assertNotIn("drafts.send", page)


    def test_browser_js_guides_metadata_date_confirmation_without_writes(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        app_js += (root / "honorarios_app" / "static" / "review_guidance.js").read_text(encoding="utf-8")
        style_css = (root / "honorarios_app" / "static" / "style.css").read_text(encoding="utf-8")
        for text in [
            "source-review-wizard",
            "Review this source",
            "What happened",
            "I found",
            "Still needed:",
            "beginner-found-details",
            "Show recovered details",
            "function renderBeginnerQuestionFocus",
            "beginner-question-focus",
            "Answer these questions",
            "Type your numbered answers",
            "Questions first; evidence stays below.",
            'case_number: "case number"',
            'claim_transport: "transport decision"',
            'case_number: "398/24.5T8BJA"',
            'claim_transport: "yes"',
            "transport destination",
            "one-way kilometers",
            "Is ${escapeHtml(label)} the service date?",
            "No PDF, Gmail draft, or local record was created by this review.",
            "Review draft text and create fee-request PDF",
            "Open the draft preview, check the Portuguese text, then use the existing guarded PDF button.",
            "data-open-review-drawer-focus-prepare",
            "focusDrawerPrepareButton",
            '"drawer-prepare-intake-inline"',
            "function syncDrawerProgressiveDisclosure",
            "document.body.dataset.drawerWorkflowState",
            "data-confirm-metadata-service-date",
            "photo_metadata_user_confirmed",
            "data-focus-date-answer",
            "data-not-sure-date",
            "function showHomeReviewPanel",
            "function hideHomeReviewPanel",
            "details.open = false",
            'shell.classList.add("has-review")',
            'shell.classList.remove("has-review", "source-review", "manual-review")',
            "focusHomeReviewCard",
            "await reviewIntake({ openDrawer: false })",
            "applyNumberedAnswers({ sourceSelector: \"#home-numbered-answers\", openDrawer: false })",
            "hideHomeReviewPanel();",
            "function applyReview(data, options = {})",
            "options.openDrawer !== false",
            "Review what I found below before any PDF or Gmail draft step.",
            "home-numbered-answers",
            "home-apply-numbered-answers",
            "function renderInlineAnswerPanel",
            "function hasMeaningfulNumberedAnswer",
            "function numberedAnswersText",
            "function renderGuidedStep",
            'shell.classList.toggle("source-review", state.currentReviewOrigin === "source")',
            'state.currentReviewOrigin = "source"',
            'state.currentReviewOrigin = "manual"',
            "target.closest(\"#interpretation-review-drawer\")",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, app_js)
        for css in [
            ".source-review-wizard",
            ".source-review-title",
            ".beginner-found-details",
            ".beginner-found-details > summary",
            ".beginner-question-focus",
            ".beginner-question-list",
            ".beginner-question-list li",
            "grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));",
            ".beginner-question-list li.is-answer-box",
            ".beginner-outcome-banner",
            ".source-safety-line",
            ".simple-task-shell.has-review #interpretation-seed-panel",
            ".simple-task-shell.has-review #interpretation-intake-panel",
            ".simple-task-shell.has-review.source-review #source-upload-form",
            ".simple-task-shell.has-review.source-review #build-profile",
            ".review-source-change-hint",
            ".date-confirmation-actions",
            ".beginner-ready-cta",
            ".primary-mini-button",
            ".inline-answer-panel",
            ".drawer-review-actions",
            'body[data-drawer-workflow-state="answer_questions"] #draft-lifecycle-panel',
            'body:not([data-drawer-workflow-state="review_gmail_draft_args"]) #manual-handoff-card',
            'body:not([data-drawer-workflow-state="review_gmail_draft_args"]) #manual-record-card',
            'body:not([data-drawer-workflow-state="review_gmail_draft_args"]) #record-draft',
        ]:
            with self.subTest(css=css):
                self.assertIn(css, style_css)
        mobile_tail = style_css.rsplit("@media (max-width: 760px)", 1)[1]
        self.assertIn(".beginner-ready-cta", mobile_tail)
        self.assertIn(".review-source-change-hint button", mobile_tail)
        self.assertIn("flex-direction: column;", mobile_tail)
        self.assertIn(".beginner-ready-cta button", mobile_tail)
        self.assertIn("width: 100%;", mobile_tail)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)


    def test_public_docs_list_browser_iab_answers_apply_diagnostics(self):
        root = Path(__file__).resolve().parents[1]
        docs = {
            "README.md": (root / "README.md").read_text(encoding="utf-8"),
            "docs/web-app-roadmap.md": (root / "docs" / "web-app-roadmap.md").read_text(encoding="utf-8"),
            "docs/process-optimizations.md": (root / "docs" / "process-optimizations.md").read_text(encoding="utf-8"),
        }
        for relative, text in docs.items():
            with self.subTest(relative=relative):
                self.assertIn("Browser/IAB answers/apply", text)
                self.assertIn("--browser-answer-questions", text)
                self.assertIn("--browser-apply-history", text)


    def test_browser_js_keeps_legalpdf_restore_controls_guarded(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        smoke_js = (root / "scripts" / "browser_iab_smoke.mjs").read_text(encoding="utf-8")
        for text in [
            "/api/health",
            "serverConnection",
            "renderServerConnectionStatus",
            "setServerDisconnected",
            "syncServerConnectionGates",
        ]:
            with self.subTest(stale_guard=text):
                self.assertIn(text, app_js)
        for text in [
            "Apply this restore locally",
            "Restore local references from backup",
            "RESTORE LEGALPDF APPLY BACKUP",
            "legalpdf-restore-reason",
            "legalpdf-restore-phrase",
            "confirm-legalpdf-restore",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, app_js)
                self.assertIn(text, smoke_js)
        for text in [
            "function renderSourceAttention",
            "Review Attention",
            "attention-flags",
            "attention-severity",
        ]:
            with self.subTest(source_attention=text):
                self.assertIn(text, app_js)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)
        self.assertNotIn("_send_email", smoke_js)
        self.assertNotIn("_send_draft", smoke_js)


    def test_browser_iab_smoke_attempts_guarded_upload_evidence(self):
        root = Path(__file__).resolve().parents[1]
        smoke_js = (root / "scripts" / "browser_iab_smoke.mjs").read_text(encoding="utf-8")
        for text in [
            "createSyntheticUploadFixtures",
            "/api/health",
            "browser_health_check",
            "setSyntheticInputFile",
            "setInputFiles",
            "#source-file",
            "#supporting-attachment-file",
            "#source-upload-form button[type=submit]",
            "#supporting-attachment-form button[type=submit]",
            "openSupportingAttachmentDetails",
            ".supporting-attachment-details > summary",
            "browser_photo_upload_evidence",
            "browser_pdf_upload_evidence",
            "browser_supporting_attachment_upload_evidence",
            "browser_supporting_attachment_stale",
            "browser_record_helper",
            "browser_profile_proposal",
            "browser_recent_work_lifecycle",
            "browser_recent_work_reconciliation",
            "recentWorkReconciliation: false",
            'else if (item === "--recent-work-reconciliation") args.recentWorkReconciliation = true',
            "browser_recent_work_reconciliation_fake_mode_required",
            "browser_recent_work_reconciliation_status_required",
            "draft-missing-active",
            "keepOpen: false",
            'else if (item === "--keep-open") args.keepOpen = true',
            "let existingTabIds = new Set()",
            "let runnerCreatedTab = false",
            "let runnerBorrowedBlankTab = false",
            "let runnerTabCleanupMode = \"close\"",
            "function isBlankTabInfo",
            "async function safeSelectedTabInfo",
            "async function cleanupBlankFallback",
            "runnerCreatedTab = true",
            "runnerBorrowedBlankTab = true",
            "selected_blank_tab",
            "Browser/IAB borrowed the selected blank tab as a disposable smoke pane.",
            "Runner-owned Browser/IAB tab reset to about:blank after a navigation timeout.",
            "Browser/IAB did not allocate a disposable smoke tab; refusing to drive an existing tab.",
            "browser_tab_cleanup",
            "await setupAtlasRuntime({ globals: globalThis });",
            "await tab.close()",
            "await tab.goto(\"about:blank\")",
            "if (!args.keepOpen && (runnerCreatedTab || runnerBorrowedBlankTab) && tab)",
            "Browser/IAB closed the disposable smoke tab.",
            "Browser/IAB reset the sole disposable smoke tab to about:blank.",
            "Browser/IAB kept the disposable smoke tab open for debugging.",
            "keep_open: true",
            "keep_open: false",
            "--keep-open",
            "browser_batch_stale_gating",
            "browser_legalpdf_import_gates",
            "browser_public_readiness_gate",
            "#run-public-readiness",
            "#public-readiness-result",
            "Tracked Git content is ready for the public repo.",
            "Local overlays",
            "Full workspace gate",
            "GOCSPX",
            "ya29.",
            "/api/gmail/status",
            "fake_mode",
            "draft_only",
            "draft_create_ready",
            "browser_gmail_api_status_required",
            "browser_gmail_api_fake_mode_required",
            "browser_local_diagnostics",
            "#refresh-diagnostics",
            "#diagnostics-result",
            "#copy-runtime-doctor-command",
            "#copy-isolated-source-upload-smoke-command",
            "#copy-legalpdf-adapter-readiness-command",
            "#copy-isolated-adapter-contract-smoke-command",
            "#copy-browser-iab-review-smoke-command",
            "#copy-browser-iab-answer-apply-smoke-command",
            "runtime_doctor",
            "isolated_source_upload_smoke",
            "legalpdf_adapter_readiness",
            "isolated_adapter_contract_smoke",
            "Python runtime doctor",
            "python scripts/runtime_doctor.py --json",
            "runtimeDoctorClipboardText",
            "LegalPDF adapter readiness",
            "python scripts/legalpdf_adapter_caller.py",
            "--readiness-only",
            "adapterReadinessClipboardText",
            "browser_iab_smoke",
            "browser_iab_answer_apply_smoke",
            "--source-upload-checks",
            "--adapter-contract-checks",
            "--browser-answer-questions",
            "--browser-apply-history",
            "data-use-profile-proposal",
            "#preview-profile-change",
            "#gmail-response-raw",
            "#autofill-record-from-prepared",
            "#record_draft_id",
            'expectButtonDisabled(tab, "#record-parsed-prepared-draft"',
            'expectButtonEnabled(tab, "#record-parsed-prepared-draft"',
            "Review the PDF preview and exact Gmail args before local recording.",
            "Source Evidence",
            "Filename",
            "synthetic-declaracao.pdf",
            "--supporting-attachment-stale",
            "--browser-record-helper",
            "supportingAttachmentStale",
            "supporting attachments changed",
            "#copy-browser-iab-supporting-attachment-stale-smoke-command",
            "#copy-browser-iab-record-helper-smoke-command",
            "#copy-python-browser-record-helper-smoke-command",
            "#copy-browser-iab-recent-work-reconciliation-smoke-command",
            "browser_iab_supporting_attachment_stale_smoke",
            "browser_iab_record_helper_smoke",
            "python_browser_record_helper_smoke",
            "browser_iab_recent_work_reconciliation_smoke",
            "--browser-recent-work-reconciliation",
            "recentWorkReconciliationClipboardText",
            "requiresIsolatedSyntheticRuntime(args)",
            "healthAttestsIsolatedSyntheticRuntime(health)",
            "browser_isolated_runtime_required",
            "requires an isolated synthetic runtime",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, smoke_js)
        for flag in [
            "args.prepareReplacement",
            "args.preparePacket",
            "args.gmailApiCreate",
            "args.recentWorkLifecycle",
            "args.recentWorkReconciliation",
            "args.manualHandoffStale",
            "args.supportingAttachmentStale",
        ]:
            with self.subTest(isolation_flag=flag):
                self.assertIn(flag, smoke_js)
        self.assertLess(
            smoke_js.index("browser_gmail_api_fake_mode_required"),
            smoke_js.index('click(tab, "#create-gmail-api-draft"'),
        )
        gmail_block = smoke_js.split("if (args.gmailApiCreate)", 1)[1].split(
            'if (!args.prepareReplacement || args.preparePacket)',
            1,
        )[0]
        self.assertLess(
            gmail_block.index("data-verify-created-draft"),
            gmail_block.index('fill(tab, "#record_draft_id", "draft-mismatch-smoke"'),
        )
        self.assertLess(
            gmail_block.index('fill(tab, "#record_draft_id", "draft-mismatch-smoke"'),
            gmail_block.index('click(tab, "#verify-gmail-draft"'),
        )
        for text in [
            'fill(tab, "#record_message_id", "local-message-smoke"',
            'fill(tab, "#record_thread_id", "local-thread-smoke"',
            'expectSelectorText(tab, "#gmail-verify-result", "reconciliation mismatch"',
            'expectSelectorText(tab, "#gmail-verify-result", "Message ID differs"',
            'expectSelectorText(tab, "#gmail-verify-result", "Thread ID differs"',
            'expectSelectorText(tab, "#gmail-verify-result", "No local records were changed"',
            'expectSelectorText(tab, "#gmail-verify-result", "users.drafts.get"',
        ]:
            with self.subTest(gmail_mismatch=text):
                self.assertIn(text, gmail_block)
        self.assertNotIn('click(tab, "#record-parsed-prepared-draft"', gmail_block)
        self.assertNotIn('click(tab, "#record-draft"', gmail_block)
        self.assertNotIn('click(tab, "[data-history-mark-sent', gmail_block)
        reconciliation_block = smoke_js.split("if (args.recentWorkReconciliation)", 1)[1].split("if (args.profileProposal)", 1)[0]
        self.assertLess(
            reconciliation_block.index("browser_recent_work_reconciliation_fake_mode_required"),
            reconciliation_block.index('click(tab, "button[data-history-source=\\"draft_log\\"][data-history-verify-draft]"'),
        )
        for text in [
            'expectSelectorText(tab, "#history-draft-action-result", "Read-only Gmail draft verification"',
            'expectSelectorText(tab, "#history-draft-action-result", "not_found"',
            'expectSelectorText(tab, "#history-draft-action-result", "users.drafts.get"',
            'expectSelectorText(tab, "#history-draft-action-result", "No local records were changed"',
        ]:
            with self.subTest(recent_work_reconciliation=text):
                self.assertIn(text, reconciliation_block)
        self.assertNotIn('click(tab, "[data-history-mark-sent', reconciliation_block)
        self.assertNotIn('click(tab, "[data-history-mark-not-found', reconciliation_block)
        self.assertNotIn("/api/drafts/status", reconciliation_block)
        self.assertNotIn("/api/gmail/drafts/reconcile-not-found", reconciliation_block)
        self.assertNotIn('click(tab, "#create-gmail-api-draft"', reconciliation_block)
        self.assertNotIn("Browser/IAB smoke does not drive local file-picker uploads yet", smoke_js)
        self.assertNotIn("setupAtlasRuntime({ globals: globalThis, backend })", smoke_js)
        self.assertNotIn('click(tab, "[data-history-mark-not-found', smoke_js)
        self.assertNotIn("_send_email", smoke_js)
        self.assertNotIn("_send_draft", smoke_js)


    def test_packet_browser_smoke_closes_drawer_before_preparing_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        smoke_js = (root / "scripts" / "browser_iab_smoke.mjs").read_text(encoding="utf-8")
        flow_py = (root / "scripts" / "browser_flow_smoke.py").read_text(encoding="utf-8")
        packet_block = smoke_js.split("if (args.preparePacket)", 1)[1].split("if (args.recordHelper)", 1)[0]
        record_helper_block = smoke_js.split("if (args.recordHelper)", 1)[1].split("if (args.supportingAttachmentStale)", 1)[0]
        flow_packet_block = flow_py.split("def _prepare_packet()", 1)[1].split("if prepare_packet:", 1)[0]
        flow_record_helper_block = flow_py.split("if record_helper:", 1)[1].split("if manual_handoff_stale:", 1)[0]
        flow_supporting_stale_block = flow_py.split("if supporting_attachment_stale:", 1)[1].split("if manual_handoff_stale:", 1)[0]
        flow_expect_text_block = flow_py.split("def expect_text", 1)[1].split("def fill", 1)[0]
        flow_homepage_block = flow_py.split('if not _safe_step(checks, "browser_homepage"', 1)[1].split('def _review_drawer()', 1)[0]
        flow_selector_text_block = flow_py.split("def expect_selector_text", 1)[1].split("def expect_selector_attribute_contains", 1)[0]
        flow_value_block = flow_py.split("def expect_selector_value", 1)[1].split("def expect_button_disabled", 1)[0]
        flow_reset_block = flow_py.split('if not _safe_step(checks, "browser_workspace_reset"', 1)[1].split("finally:", 1)[0]

        preflight_index = packet_block.index('click(tab, "#preflight-batch-intakes"')
        close_index = packet_block.index("closeReviewDrawerIfOpen()")
        prepare_index = packet_block.index('click(tab, "#prepare-batch-intakes"')

        self.assertIn("reviewDrawerOpen = true", packet_block[preflight_index:prepare_index])
        self.assertLess(preflight_index, close_index)
        self.assertLess(close_index, prepare_index)
        self.assertIn('expectSelectorText(tab, "#prepare-results", "Packet draft recording helper"', packet_block)
        self.assertIn('expectSelectorText(tab, "#prepare-results", "Underlying duplicate blockers"', packet_block)
        self.assertNotIn('expectBodyText(tab, "Packet draft recording helper"', packet_block)

        self.assertIn("review_drawer_open = True", flow_packet_block)
        self.assertIn("locator = self._page.get_by_text(text, exact=False)", flow_expect_text_block)
        self.assertIn("for index in range(locator.count())", flow_expect_text_block)
        self.assertIn("locator.nth(index).is_visible", flow_expect_text_block)
        self.assertIn("self._page.wait_for_timeout(100)", flow_expect_text_block)
        self.assertIn("Expected visible text", flow_expect_text_block)
        self.assertIn("deadline = time.monotonic()", flow_selector_text_block)
        self.assertIn("text.lower() in last_content.lower()", flow_selector_text_block)
        self.assertIn("last_content", flow_selector_text_block)
        self.assertIn("elif correction_mode:", flow_py)
        self.assertIn("if not prepare_replacement or prepare_packet:", flow_py)
        self.assertIn('wait_for(state="attached"', flow_value_block)
        self.assertNotIn('wait_for(state="visible"', flow_value_block)
        self.assertNotIn('driver.expect_text("Next safe action")', flow_homepage_block)
        self.assertLess(flow_packet_block.index("_close_review_drawer_if_open()"), flow_packet_block.index('driver.click(\'label[for="batch-packet-mode"]\')'))
        self.assertNotIn("get_by_text(text, exact=False).wait_for", flow_expect_text_block)
        self.assertNotIn("get_by_text(text, exact=False).first().wait_for", flow_expect_text_block)
        self.assertNotIn("get_by_text(text, exact=False).first.wait_for", flow_expect_text_block)
        self.assertIn("_close_review_drawer_if_open()", flow_packet_block)
        self.assertIn('driver.expect_selector_text("#prepare-results", "Packet draft recording helper")', flow_packet_block)
        self.assertIn('driver.expect_selector_text("#prepare-results", "Underlying duplicate blockers")', flow_packet_block)
        self.assertNotIn('driver.expect_text("Packet draft recording helper")', flow_packet_block)
        self.assertIn('click(tab, "#parse-gmail-response"', record_helper_block)
        self.assertIn('click(tab, "#autofill-record-from-prepared"', record_helper_block)
        self.assertNotIn('click(tab, "#record-parsed-prepared-draft"', record_helper_block)
        self.assertNotIn('click(tab, "#record-draft"', record_helper_block)
        self.assertNotIn('click(tab, "#create-gmail-api-draft"', record_helper_block)
        self.assertIn('driver.expect_button_disabled("#record-parsed-prepared-draft")', flow_record_helper_block)
        self.assertIn('"Review the PDF preview and exact Gmail args before local recording."', flow_record_helper_block)
        self.assertIn('_expect_record_value("#record_payload", ".draft.json")', flow_record_helper_block)
        self.assertIn('driver.check("#gmail_handoff_reviewed")', flow_record_helper_block)
        self.assertIn('driver.expect_button_enabled("#record-parsed-prepared-draft")', flow_record_helper_block)
        self.assertIn('driver.expect_selector_attribute_contains("#prepare-results", "data-stale-reason", "intake form changed")', flow_record_helper_block)
        self.assertIn("record_helper_should_mutate_prepared_state = not (manual_handoff_stale or supporting_attachment_stale)", flow_record_helper_block)
        self.assertIn('driver.set_input_file("#supporting-attachment-file", supporting_upload_path)', flow_supporting_stale_block)
        self.assertLess(flow_supporting_stale_block.index('driver.click("#build-manual-handoff")'), flow_supporting_stale_block.index("_close_review_drawer_if_open()"))
        self.assertLess(flow_supporting_stale_block.index("_close_review_drawer_if_open()"), flow_supporting_stale_block.index('driver.set_input_file("#supporting-attachment-file", supporting_upload_path)'))
        self.assertLess(flow_reset_block.index("_close_review_drawer_if_open()"), flow_reset_block.index('driver.click("#reset-workspace")'))
        self.assertIn('driver.expect_button_disabled("#copy-manual-handoff-prompt")', flow_supporting_stale_block)
        self.assertIn('driver.expect_selector_value_equals("#record_payload", "")', flow_supporting_stale_block)
        self.assertIn('driver.expect_selector_attribute_contains("#prepare-results", "data-stale-reason", "supporting attachments changed")', flow_supporting_stale_block)
        self.assertNotIn('driver.click("#record-parsed-prepared-draft")', flow_record_helper_block)
        self.assertNotIn('driver.click("#record-draft")', flow_record_helper_block)
        self.assertNotIn('driver.click("#create-gmail-api-draft")', flow_record_helper_block)
        self.assertNotIn('driver.click("#record-parsed-prepared-draft")', flow_supporting_stale_block)
        self.assertNotIn('driver.click("#record-draft")', flow_supporting_stale_block)
        self.assertNotIn('driver.click("#create-gmail-api-draft")', flow_supporting_stale_block)


    def test_browser_js_prefights_single_prepare_before_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        prepare_body = app_js.split("async function prepareIntake", 1)[1].split("function renderPrepared", 1)[0]

        snapshot_index = prepare_body.index('const requestIntake = cloneIntake(options.correctionMode ? preparedTargetIntake() || state.currentIntake : state.currentIntake)')
        revision_index = prepare_body.index('const capturedRevision = beginPreparation()')
        preflight_index = prepare_body.index('requestWorkflowJson("/api/prepare/preflight"')
        binding_index = prepare_body.index('requestPayload.preflight_review = preflight.preflight_review')
        prepare_index = prepare_body.index('requestWorkflowJson("/api/prepare"')
        accepted_index = prepare_body.index('state.lastPrepared = data')
        self.assertLess(snapshot_index, revision_index)
        self.assertLess(revision_index, preflight_index)
        self.assertLess(preflight_index, prepare_index)
        self.assertLess(preflight_index, binding_index)
        self.assertLess(binding_index, prepare_index)
        self.assertLess(prepare_index, accepted_index)
        self.assertIn('intakes: [cloneIntake(requestIntake)]', prepare_body)
        self.assertIn('const requestPayload = { intakes: [requestIntake], render_previews: true }', prepare_body)
        self.assertEqual(prepare_body.count('}, { revision: capturedRevision })'), 2)
        self.assertIn('if (!preflight) return null;', prepare_body[preflight_index:prepare_index])
        self.assertIn('if (!data) return null;', prepare_body[prepare_index:accepted_index])
        self.assertIn('if (!isWorkflowResponseCurrent(capturedRevision, state.workflowRevision)) return null;', prepare_body)
        wrapper = app_js.split('function requestWorkflowJson', 1)[1].split('async function ', 1)[0]
        self.assertIn('awaitWorkflowResponse(() => requestJson(url, options), captured', wrapper)
        self.assertIn("requestPayload.preflight_review = preflight.preflight_review", prepare_body)
        self.assertIn("preflightPayload.correction_reason = requestPayload.correction_reason", prepare_body)
        self.assertIn('packet_mode: false', prepare_body)

    def test_prepare_snapshot_survives_edits_and_late_responses_are_discarded(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / 'honorarios_app/static/app.js').read_text(encoding='utf-8')
        functions = []
        for name, declaration in (('cloneIntake', 'function'), ('requestWorkflowJson', 'function'),
                                  ('prepareIntake', 'async function')):
            match = re.search(declaration + r' ' + name + r'\([^\n]*\) \{.*?\n\}', app_js, re.DOTALL)
            self.assertIsNotNone(match, name)
            functions.append(match.group(0))
        module_url = (root / 'honorarios_app/static/review_guidance.js').as_uri()
        script = 'import { awaitWorkflowResponse, isWorkflowResponseCurrent } from ' + json.dumps(module_url) + ';\n'
        script += """
let state, requests, rendered, transport;
function reset() {
  state = { currentIntake: { case_number: 'FICT-700', transport: { km_one_way: 12 } }, workflowRevision: 7, lastPrepared: null };
  requests = []; rendered = [];
}
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
function mergeFormIntoCurrentIntake() {}
function beginPreparation() { return state.workflowRevision; }
function finishPreparationWait() {}
async function buildIntakeFromProfile() { throw new Error('Unexpected profile construction'); }
function requestJson(url, options) { requests.push({ url, payload: JSON.parse(options.body) }); return transport(url); }
function renderNextSafeAction() {}
function setStatus() {}
function showAlert() {}
function openReviewDrawer() {}
function renderPrepared(data) { rendered.push(data); }
async function loadReference() {}
""" + '\n'.join(functions) + """
const ready = { status: 'ready', preflight_review: { token: 'synthetic-reviewed-token' } };
const prepared = { status: 'ready', items: [] };
reset();
const first = deferred();
transport = url => url.endsWith('/preflight') ? first.promise : Promise.resolve(prepared);
const preparing = prepareIntake();
state.currentIntake.transport.km_one_way = 999;
state.currentIntake.case_number = 'FICT-EDITED';
first.resolve(ready);
await preparing;
const snapshot = { requests, current: state.currentIntake, preparedAccepted: state.lastPrepared === prepared, rendered: rendered.length };

reset();
const stalePreflight = deferred();
transport = () => stalePreflight.promise;
const beforeEdit = prepareIntake();
state.workflowRevision += 1;
stalePreflight.resolve(ready);
const ignoredPreflight = await beforeEdit;
const latePreflight = { result: ignoredPreflight, requests: requests.length, rendered: rendered.length, prepared: state.lastPrepared };

reset();
const stalePrepare = deferred();
const enteredPrepare = deferred();
transport = url => {
  if (url.endsWith('/preflight')) return Promise.resolve(ready);
  enteredPrepare.resolve(); return stalePrepare.promise;
};
const beforeSecondEdit = prepareIntake();
await enteredPrepare.promise;
state.workflowRevision += 1;
stalePrepare.resolve(prepared);
const ignoredPrepare = await beforeSecondEdit;
const latePrepare = { result: ignoredPrepare, requests: requests.length, rendered: rendered.length, prepared: state.lastPrepared };
console.log(JSON.stringify({ snapshot, latePreflight, latePrepare }));
"""
        result = subprocess.run(['node', '--input-type=module', '-'], input=script, text=True,
                                encoding='utf-8', capture_output=True, timeout=20, check=True, cwd=root)
        data = json.loads(result.stdout)
        snapshot = data['snapshot']
        self.assertEqual([item['url'] for item in snapshot['requests']], ['/api/prepare/preflight', '/api/prepare'])
        for request in snapshot['requests']:
            self.assertEqual(request['payload']['intakes'][0], {'case_number': 'FICT-700', 'transport': {'km_one_way': 12}})
        self.assertEqual(snapshot['requests'][1]['payload']['preflight_review'], {'token': 'synthetic-reviewed-token'})
        self.assertEqual(snapshot['current']['transport']['km_one_way'], 999)
        self.assertTrue(snapshot['preparedAccepted'])
        self.assertEqual(snapshot['rendered'], 1)
        self.assertEqual(data['latePreflight'], {'result': None, 'requests': 1, 'rendered': 0, 'prepared': None})
        self.assertEqual(data['latePrepare'], {'result': None, 'requests': 2, 'rendered': 0, 'prepared': None})


    def test_browser_js_routes_one_click_recording_through_strict_prepared_endpoint(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("async function recordPreparedDraftFromForm", app_js)
        one_click_body = app_js.split("async function recordFromParsedResponseAndPreparedPayload", 1)[1].split("function ", 1)[0]
        self.assertIn("await recordPreparedDraftFromForm()", one_click_body)
        self.assertNotIn("await recordDraft()", one_click_body)
        prepared_record_body = app_js.split("async function recordPreparedDraftFromForm", 1)[1].split("async function ", 1)[0]
        self.assertIn('requestJson("/api/drafts/record"', prepared_record_body)
        self.assertIn("gmail_handoff_reviewed: true", prepared_record_body)
        self.assertIn("...currentPreparedReviewFields(payloadPath)", prepared_record_body)
        manual_record_body = app_js.split("async function recordDraft()", 1)[1].split("function ", 1)[0]
        self.assertIn('requestJson("/api/drafts/status"', manual_record_body)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)


    def test_browser_js_invalidates_stale_prepared_payloads(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        for text in [
            "function clearPreparedArtifacts",
            "state.lastPrepared = null",
            "state.draftLifecycle = null",
            "record_payload",
            "record_draft_id",
            "record_message_id",
            "record_thread_id",
            "record_supersedes",
            "gmail-response-raw",
            "renderDraftLifecycle(null)",
            "syncActionGates(null)",
            "source changed",
            "review changed",
            "review reset",
            "intake form changed",
            "supporting attachments changed",
            "data-stale-reason",
            'removeAttribute("data-stale-reason")',
        ]:
            with self.subTest(text=text):
                self.assertIn(text, app_js)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)


    def test_browser_js_requires_handoff_review_before_one_click_record(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        page = (root / "honorarios_app" / "templates" / "index.html").read_text(encoding="utf-8")
        for text in [
            "Gmail handoff checklist",
            "I reviewed the PDF preview",
            "I used the exact `_create_draft` args shown above",
            "gmail_handoff_reviewed",
            "Review the PDF preview and exact Gmail args before local recording.",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, app_js + page)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)


    def test_local_app_smoke_runner_browser_click_through_contract_is_injectable(self):
        client = self.make_client()
        seen_kwargs = {}

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def browser_runner(_base_url, **kwargs):
            seen_kwargs.update(kwargs)
            return {
                "status": "ready",
                "checks": [
                    {"name": "browser_review_drawer", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_answer_questions", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_photo_upload_evidence", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_pdf_upload_evidence", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_supporting_attachment_upload_evidence", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_correction_mode", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_replacement_prepare", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_supporting_attachment_stale", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_record_helper", "status": "ready", "message": "ok", "details": {}},
                ],
                "failure_count": 0,
                "send_allowed": False,
            }

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            browser_click_through=True,
            browser_answer_questions=True,
            browser_upload_photo=True,
            browser_upload_pdf=True,
            browser_upload_supporting_attachment=True,
            browser_correction_mode=True,
            browser_prepare_replacement=True,
            browser_supporting_attachment_stale=True,
            browser_record_helper=True,
            browser_apply_history=True,
            browser_runner=browser_runner,
        )
        self.assertEqual(report["status"], "ready", report)
        self.assertIn("browser_review_drawer", {check["name"] for check in report["checks"]})
        self.assertIn("browser_answer_questions", {check["name"] for check in report["checks"]})
        self.assertIn("browser_photo_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_pdf_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_supporting_attachment_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_correction_mode", {check["name"] for check in report["checks"]})
        self.assertIn("browser_replacement_prepare", {check["name"] for check in report["checks"]})
        self.assertIn("browser_record_helper", {check["name"] for check in report["checks"]})
        self.assertTrue(seen_kwargs["answer_questions"])
        self.assertTrue(seen_kwargs["upload_photo"])
        self.assertTrue(seen_kwargs["upload_pdf"])
        self.assertTrue(seen_kwargs["upload_supporting_attachment"])
        self.assertTrue(seen_kwargs["correction_mode"])
        self.assertTrue(seen_kwargs["prepare_replacement"])
        self.assertTrue(seen_kwargs["supporting_attachment_stale"])
        self.assertTrue(seen_kwargs["record_helper"])
        self.assertTrue(seen_kwargs["apply_history"])


    def test_isolated_app_smoke_forwards_browser_iab_answer_and_apply_flags(self):
        root = Path(__file__).resolve().parents[1]
        smoke_source = (root / "scripts" / "isolated_app_smoke.py").read_text(encoding="utf-8")
        smoke_call_block = smoke_source.split("report = smoke_runner(", 1)[1].split(")", 1)[0]
        main_call_block = smoke_source.split("report = run_isolated_app_smoke(", 1)[1].split(")", 1)[0]

        self.assertIn("browser_answer_questions: bool = False", smoke_source)
        self.assertIn("browser_apply_history: bool = False", smoke_source)
        self.assertIn("browser_recent_work_reconciliation: bool = False", smoke_source)
        self.assertIn("browser_answer_questions=browser_answer_questions", smoke_call_block)
        self.assertIn("browser_apply_history=browser_apply_history", smoke_call_block)
        self.assertIn("browser_recent_work_reconciliation=browser_recent_work_reconciliation", smoke_call_block)
        self.assertIn('parser.add_argument("--browser-answer-questions"', smoke_source)
        self.assertIn('parser.add_argument("--browser-apply-history"', smoke_source)
        self.assertIn('parser.add_argument("--browser-recent-work-reconciliation"', smoke_source)
        self.assertIn("browser_answer_questions=args.browser_answer_questions", main_call_block)
        self.assertIn("browser_apply_history=args.browser_apply_history", main_call_block)
        self.assertIn("browser_recent_work_reconciliation=args.browser_recent_work_reconciliation", main_call_block)

    def test_visible_key_facts_escape_values_and_edit_shortcuts_only_focus_existing_fields(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app/static/app.js").read_text(encoding="utf-8")
        functions = []
        for name in ("escapeHtml", "displayValue", "renderBeginnerFacts", "focusReviewCorrection"):
            match = re.search(r"function " + name + r"\([^\n]*\) \{.*?\n\}", app_js, re.DOTALL)
            self.assertIsNotNone(match, name)
            functions.append(match.group(0))
        module_url = (root / "honorarios_app/static/review_guidance.js").as_uri()
        script = "import { beginnerReviewFacts, claimModeLabel } from " + json.dumps(module_url) + ";\n"
        script += "\n".join(functions) + """
const details = {open:false};
const focused = [], lookups = [];
const allowed = ['case_number','service_date','payment_entity','service_place','recipient_email'];
const inputs = Object.fromEntries(allowed.map(field => [field, {
  closest(selector) { if (selector !== '.advanced-intake-fields') throw new Error('Unexpected target'); return details; },
  scrollIntoView() {}, focus() { focused.push(field); }
}]));
const document = {getElementById(field) { lookups.push(field); return inputs[field]; }};
const injection = '<img src=x onerror="alert(1)">';
const intake = {case_number:'123/26.0SYNTH',service_date:'2026-09-28',service_date_source:'user_confirmed',payment_entity:injection,service_place:'Fictional Office',recipient_email:'court@example.test'};
const before = JSON.stringify(intake);
const data = {source_evidence:{field_evidence:[{field:'payment_entity',value:injection,source:'openai_ocr',confidence:'low'}]}};
const html = renderBeginnerFacts(data, intake);
const edited = allowed.map(focusReviewCorrection);
const invalid = focusReviewCorrection('source_file');
console.log(JSON.stringify({html,edited,invalid,focused,lookups,opened:details.open,intakeUnchanged:before===JSON.stringify(intake)}));
"""
        result = subprocess.run(["node", "--input-type=module", "-"], input=script, text=True,
                                encoding="utf-8", capture_output=True, timeout=20, check=True, cwd=root)
        data = json.loads(result.stdout)
        html = data["html"]
        self.assertIn('aria-label="Check key facts"', html)
        self.assertIn("AI suggestion · check source", html)
        self.assertIn("You confirmed this date", html)
        self.assertIn("&lt;img src=x", html)
        self.assertNotIn("<img", html)
        self.assertEqual(html.count("data-review-correct-field="), 5)
        self.assertIn('aria-label="Edit recipient email"', html)
        fields = ["case_number", "service_date", "payment_entity", "service_place", "recipient_email"]
        self.assertEqual(data["edited"], [True] * 5)
        self.assertFalse(data["invalid"])
        self.assertEqual(data["focused"], fields)
        self.assertEqual(data["lookups"], fields)
        self.assertTrue(data["opened"])
        self.assertTrue(data["intakeUnchanged"], "Edit shortcuts must not change, review or prepare values themselves.")
