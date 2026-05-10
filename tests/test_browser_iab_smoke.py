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
            "let runnerCreatedTab = false",
            "runnerCreatedTab = true",
            "browser_tab_cleanup",
            "await setupAtlasRuntime({ globals: globalThis });",
            "await tab.close()",
            "if (!args.keepOpen && runnerCreatedTab && tab)",
            "Browser/IAB closed the disposable smoke tab.",
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


if __name__ == "__main__":
    unittest.main()
