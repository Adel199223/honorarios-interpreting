from __future__ import annotations

import os
from pathlib import Path
import shutil
import unittest

from scripts.installed_wheel_smoke import run_installed_wheel_smoke


class InstalledWheelTests(unittest.TestCase):
    def test_wheel_runs_without_checkout_imports_or_private_runtime_data(self):
        uv = os.environ.get("HONORARIOS_UV_EXECUTABLE") or shutil.which("uv")
        self.assertIsNotNone(uv, "The pinned uv executable is required; set HONORARIOS_UV_EXECUTABLE when it is not on PATH.")
        result = run_installed_wheel_smoke(uv_executable=uv)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["package_imports_from_installed_target"])
        self.assertTrue(result["packaged_template_rendered"])
        self.assertTrue(result["synthetic_pdf_generated"])
        self.assertTrue(result["browser_assets_present"])
        self.assertEqual(result["adapter_readiness"]["status"], "ready")
        self.assertFalse(result["checkout_pythonpath_used"])
        self.assertFalse(result["private_runtime_bundled"])
        self.assertFalse(result["network_allowed"])
        self.assertFalse(result["send_allowed"])

    def test_packaged_generator_template_matches_the_source_template(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "templates" / "interprete_requerimento.html"
        bundled = root / "honorarios_app" / "pdf_templates" / "interprete_requerimento.html"
        self.assertEqual(source.read_text(encoding="utf-8"), bundled.read_text(encoding="utf-8"), "Update both template copies together so source and installed workflows render the same request; Windows line endings are equivalent.")


if __name__ == "__main__":
    unittest.main()
