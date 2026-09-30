from __future__ import annotations

import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import AppPaths, choose_service_profile, recover_source_upload
from scripts.generate_pdf import IntakeError


class ServiceProfileSelectionTests(unittest.TestCase):
    def choose(self, profiles, *, requested="auto", text="Synthetic interpreting source"):
        return choose_service_profile(requested_profile=requested, extracted_text=text, ai_recovery={}, profiles=profiles)

    def test_generic_fallback_is_used_only_when_available(self):
        decision = self.choose({"court_mp_generic": {"defaults": {}}, "example": {"defaults": {}}})
        self.assertEqual(decision["profile_key"], "court_mp_generic")
        self.assertEqual(decision["mode"], "auto_fallback")
        self.assertFalse(decision["auto_applied"])

    def test_only_available_profile_is_a_visible_low_confidence_fallback(self):
        decision = self.choose({"example_interpreting": {"defaults": {}}}, text="Synthetic interpreting source")
        self.assertEqual(decision["profile_key"], "example_interpreting")
        self.assertEqual(decision["mode"], "auto_fallback")
        self.assertEqual(decision["confidence"], "low")
        self.assertIn("payment entity and recipient", decision["reason"])
        self.assertFalse(decision["auto_applied"])

    def test_multiple_profiles_without_a_match_do_not_choose_payment_defaults(self):
        decision = self.choose({"first": {"defaults": {}}, "second": {"defaults": {}}})
        self.assertEqual(decision["profile_key"], "")
        self.assertEqual(decision["confidence"], "low")
        self.assertIn("No profile defaults were applied", decision["reason"])

    def test_confident_available_match_remains_automatic(self):
        decision = self.choose({"beja_trabalho": {"defaults": {}}, "example": {"defaults": {}}}, text="Tribunal do Trabalho de Beja")
        self.assertEqual(decision["profile_key"], "beja_trabalho")
        self.assertEqual(decision["mode"], "auto_applied")
        self.assertTrue(decision["auto_applied"])

    def test_explicit_choice_is_kept_even_with_conflicting_evidence(self):
        decision = self.choose({"beja_trabalho": {"defaults": {}}, "example": {"defaults": {}}}, requested="example", text="Tribunal do Trabalho de Beja")
        self.assertEqual(decision["profile_key"], "example")
        self.assertEqual(decision["suggested_profile_key"], "beja_trabalho")
        self.assertEqual(decision["mode"], "explicit_profile")
        self.assertFalse(decision["auto_applied"])

    def test_empty_profiles_have_an_actionable_blocker(self):
        with self.assertRaisesRegex(IntakeError, "Add a service profile in References"):
            self.choose({})


class SyntheticUploadProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="honorarios-profile-selection-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        photo = BytesIO()
        Image.new("RGB", (24, 24), "white").save(photo, format="PNG")
        self.photo = photo.getvalue()

    def upload(self, *, profile="auto", stub_ai=True):
        kwargs = dict(filename="synthetic-source.png", content_type="image/png", content=self.photo, source_kind="photo", profile_name=profile, visible_text="Synthetic interpreting service 999/26.0EXAMPLE on 2026-09-20", ai_recovery_mode="off", paths=self.paths)
        if not stub_ai:
            return recover_source_upload(**kwargs)
        with patch("honorarios_app.services.recover_source_with_openai", return_value={"status": "disabled", "fields": {}}):
            return recover_source_upload(**kwargs)

    def test_default_synthetic_auto_detect_upload_recovers_and_reviews(self):
        result = self.upload()
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["candidate_intake"]["payment_entity"], "Example Court")
        decision = result["source_evidence"]["auto_profile"]
        self.assertEqual(decision["profile_key"], "example_interpreting")
        self.assertEqual(decision["confidence"], "low")
        flag = next(flag for flag in result["source_evidence"]["attention"]["flags"] if flag["code"] == "profile_fallback")
        self.assertIn("payment entity and recipient", flag["detail"])
        self.assertFalse(result["send_allowed"])
        self.assertFalse(list(self.paths.output_dir.glob("*.pdf")))

    def test_ambiguous_upload_keeps_source_evidence_and_asks_for_payment(self):
        first = json.loads(self.paths.service_profiles.read_text(encoding="utf-8"))["example_interpreting"]
        second = copy.deepcopy(first)
        second["defaults"]["payment_entity"] = "Other Synthetic Court"
        second["defaults"]["recipient_email"] = "other@example.test"
        self.paths.service_profiles.write_text(json.dumps({"first": first, "second": second}), encoding="utf-8")
        result = self.upload()
        self.assertNotIn("payment_entity", result["candidate_intake"])
        self.assertNotIn("recipient_email", result["candidate_intake"])
        self.assertEqual(result["candidate_intake"]["case_number"], "999/26.0EXAMPLE")
        self.assertEqual(result["review"]["status"], "needs_info")
        self.assertIn("payment_entity", [question["field"] for question in result["review"]["questions"]])
        self.assertEqual(result["source_evidence"]["auto_profile"]["profile_key"], "")

    def test_missing_configuration_blocks_before_storing_upload_or_calling_ai(self):
        self.paths.service_profiles.unlink()
        with patch("honorarios_app.services.recover_source_with_openai") as provider:
            with self.assertRaisesRegex(IntakeError, "Service profiles are missing.*References"):
                self.upload(stub_ai=False)
            provider.assert_not_called()
        self.assertEqual(list(self.paths.source_upload_dir.iterdir()), [])

    def test_empty_configuration_blocks_before_storing_upload(self):
        self.paths.service_profiles.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(IntakeError, "No service profiles are available"):
            self.upload()
        self.assertEqual(list(self.paths.source_upload_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
