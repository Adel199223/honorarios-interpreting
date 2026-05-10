from pathlib import Path
import unittest


class BrowserIabSmokeSourceTests(unittest.TestCase):
    def smoke_source(self) -> str:
        root = Path(__file__).resolve().parents[1]
        return (root / "scripts" / "browser_iab_smoke.mjs").read_text(encoding="utf-8")

    def test_runner_closes_its_disposable_tab_by_default(self):
        smoke_js = self.smoke_source()

        for text in [
            "keepOpen: false",
            'else if (item === "--keep-open") args.keepOpen = true',
            "let existingTabIds = new Set()",
            "let runnerCreatedTab = false",
            "let runnerTabCleanupMode = \"close\"",
            "runnerCreatedTab = true",
            "Browser/IAB did not allocate a disposable smoke tab; refusing to drive an existing tab.",
            "browser_tab_cleanup",
            "await setupAtlasRuntime({ globals: globalThis });",
            "await tab.close()",
            "await tab.goto(\"about:blank\")",
            "if (!args.keepOpen && runnerCreatedTab && tab)",
            "Browser/IAB closed the disposable smoke tab.",
            "Browser/IAB reset the sole disposable smoke tab to about:blank.",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, smoke_js)

        self.assertNotIn("setupAtlasRuntime({ globals: globalThis, backend })", smoke_js)

    def test_runner_can_keep_debug_tab_open_explicitly(self):
        smoke_js = self.smoke_source()
        usage_block = smoke_js.split("Usage: node scripts/browser_iab_smoke.mjs", 1)[1].split('");', 1)[0]

        self.assertIn("--keep-open", usage_block)
        self.assertIn("Browser/IAB kept the disposable smoke tab open for debugging.", smoke_js)
        self.assertIn("keep_open: true", smoke_js)
        self.assertIn("keep_open: false", smoke_js)

    def test_cleanup_preserves_no_write_safety_rules(self):
        smoke_js = self.smoke_source()
        record_helper_block = smoke_js.split("if (args.recordHelper)", 1)[1].split("if (args.supportingAttachmentStale)", 1)[0]

        self.assertNotIn('click(tab, "#record-parsed-prepared-draft"', record_helper_block)
        self.assertNotIn('click(tab, "#record-draft"', record_helper_block)
        self.assertNotIn('click(tab, "#create-gmail-api-draft"', record_helper_block)
        self.assertNotIn("_send_email", smoke_js)
        self.assertNotIn("_send_draft", smoke_js)

    def test_local_diagnostics_smoke_covers_runtime_doctor_command(self):
        smoke_js = self.smoke_source()

        for text in [
            "#copy-runtime-doctor-command",
            '"data-copy-diagnostic-command", "runtime_doctor"',
            "Python runtime doctor",
            "python scripts/runtime_doctor.py --json",
            "runtimeDoctorClipboardText",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, smoke_js)

        forbidden_scan = smoke_js.split("for (const forbidden of forbiddenSendActions)", 1)[1].split("throw new Error", 1)[0]
        self.assertIn("runtimeDoctorClipboardText.includes(forbidden)", forbidden_scan)

    def test_recent_work_reconciliation_smoke_is_fake_gmail_read_only(self):
        smoke_js = self.smoke_source()

        for text in [
            "recentWorkReconciliation: false",
            'else if (item === "--recent-work-reconciliation") args.recentWorkReconciliation = true',
            "browser_recent_work_reconciliation_fake_mode_required",
            "browser_recent_work_reconciliation_status_required",
            "browser_recent_work_reconciliation",
            'click(tab, "button[data-history-source=\\"draft_log\\"][data-history-verify-draft]"',
            'expectSelectorText(tab, "#history-draft-action-result", "Read-only Gmail draft verification"',
            'expectSelectorText(tab, "#history-draft-action-result", "not_found"',
            'expectSelectorText(tab, "#history-draft-action-result", "users.drafts.get"',
            'expectSelectorText(tab, "#history-draft-action-result", "No local records were changed"',
            "--recent-work-reconciliation",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, smoke_js)

        marker = "if (args.recentWorkReconciliation)"
        self.assertIn(marker, smoke_js)
        reconciliation_block = smoke_js.split(marker, 1)[1].split("if (args.profileProposal)", 1)[0]
        self.assertLess(
            reconciliation_block.index("browser_recent_work_reconciliation_fake_mode_required"),
            reconciliation_block.index('click(tab, "button[data-history-source=\\"draft_log\\"][data-history-verify-draft]"'),
        )
        self.assertNotIn('click(tab, "[data-history-mark-sent', reconciliation_block)
        self.assertNotIn('click(tab, "[data-history-mark-not-found', reconciliation_block)
        self.assertNotIn("/api/drafts/status", reconciliation_block)
        self.assertNotIn("/api/gmail/drafts/reconcile-not-found", reconciliation_block)
        self.assertNotIn('click(tab, "#create-gmail-api-draft"', reconciliation_block)
        self.assertNotIn('click(tab, "#record-parsed-prepared-draft"', reconciliation_block)


if __name__ == "__main__":
    unittest.main()
