from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from honorarios_app import services
from honorarios_app.source_evidence import (
    build_field_evidence,
    build_profile_evidence,
    build_source_attention,
    combine_text_parts,
    fold_match_text,
)


class SourceEvidenceTests(unittest.TestCase):
    def fields(self, **overrides):
        inputs = dict(candidate={}, deterministic_fields={}, metadata={}, ai_recovery={}, profile_decision={}, profiles={})
        inputs.update(overrides)
        return build_field_evidence(**inputs)

    def attention(self, **overrides):
        inputs = dict(candidate={}, review={"status": "ready"}, ai_recovery={}, profile_decision={}, profile_proposal={}, field_evidence=[], warnings=[])
        inputs.update(overrides)
        return build_source_attention(**inputs)

    def test_deterministic_evidence_wins_over_ai_and_profile_defaults(self):
        entries = self.fields(
            candidate={"case_number": "123/26.0SYNTH", "recipient_email": "court@example.test", "source_text": "Case 00123/26.0SYNTH\ncourt@example.test"},
            deterministic_fields={"case_number": "123/26.0SYNTH", "raw_case_number": "00123/26.0SYNTH", "recipient_email": "court@example.test"},
            ai_recovery={"status": "ok", "fields": {"raw_case_number": "00123/26.0SYNTH", "court_email": "court@example.test"}},
            profile_decision={"profile_key": "example", "mode": "explicit_profile"},
            profiles={"example": {"defaults": {"recipient_email": "court@example.test"}}},
        )
        by_field = {entry["field"]: entry for entry in entries}
        self.assertEqual(len(entries), len(by_field), "Each applied field should have one authoritative explanation.")
        self.assertEqual(by_field["case_number"]["source"], "deterministic_text")
        self.assertEqual(by_field["case_number"]["raw_value"], "00123/26.0SYNTH")
        self.assertEqual(by_field["case_number"]["value"], "123/26.0SYNTH")
        self.assertEqual(by_field["recipient_email"]["source"], "visible_email")
        self.assertEqual(by_field["recipient_email"]["excerpt"], "court@example.test")

    def test_conflicting_service_date_keeps_both_values_and_blocks_attention(self):
        entries = self.fields(candidate={"service_date": "2026-09-20", "photo_metadata_date": "2026-09-21"}, deterministic_fields={"service_date": "2026-09-20"}, metadata={"exif_date": "2026-09-21"})
        by_field = {entry["field"]: entry for entry in entries}
        self.assertEqual(by_field["photo_metadata_date"]["source"], "image_metadata")
        self.assertEqual(by_field["service_date"]["status"], "conflicts_with_metadata")
        self.assertEqual(by_field["service_date"]["conflicts_with"], {"field": "photo_metadata_date", "value": "2026-09-21"})
        attention = self.attention(field_evidence=entries)
        self.assertEqual(attention["status"], "blocked")
        self.assertEqual([flag["code"] for flag in attention["flags"]], ["date_conflict"])

    def test_matching_document_date_and_metadata_have_combined_provenance(self):
        entries = self.fields(candidate={"service_date": "2026-09-20", "photo_metadata_date": "2026-09-20"}, deterministic_fields={"service_date": "2026-09-20"}, metadata={"exif_date": "2026-09-20"})
        service = next(entry for entry in entries if entry["field"] == "service_date")
        self.assertEqual(service["source"], "document_text_and_photo_metadata")
        self.assertEqual(service["status"], "applied")
        self.assertEqual(self.attention(field_evidence=entries)["status"], "ready")

    def test_metadata_origin_distinguishes_exif_visible_and_ai_recovered_metadata(self):
        for metadata, ai, source in (
            ({"exif_date": "2026-09-20", "visible_metadata_date": "2026-09-20"}, {}, "image_metadata"),
            ({"visible_metadata_date": "2026-09-20"}, {}, "visible_google_photos_metadata"),
            ({}, {"fields": {"photo_metadata_date": "2026-09-20"}}, "visible_google_photos_metadata"),
            ({}, {}, "image_metadata"),
        ):
            with self.subTest(source=source, metadata=metadata):
                entry = self.fields(candidate={"photo_metadata_date": "2026-09-20"}, metadata=metadata, ai_recovery=ai)[0]
                self.assertEqual(entry["source"], source)
                self.assertEqual(entry["confidence"], "high")

    def test_ai_provenance_uses_visible_values_and_does_not_claim_rejected_values(self):
        entries = self.fields(candidate={"payment_entity": "Synthetic Polícia", "recipient_email": "kept@example.test"}, ai_recovery={"status": "ok", "raw_visible_text": "SYNTHETIC POLICIA", "fields": {"payment_entity": "Synthetic Polícia", "court_email": "other@example.test"}})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["field"], "payment_entity")
        self.assertEqual(entries[0]["source"], "openai_ocr")
        self.assertEqual(entries[0]["confidence"], "high")
        self.assertEqual(entries[0]["excerpt"], "SYNTHETIC POLICIA")

    def test_ai_date_matching_image_metadata_is_high_confidence_evidence(self):
        entries = self.fields(candidate={"service_date": "2026-09-20", "photo_metadata_date": "2026-09-20"}, ai_recovery={"status": "ok", "fields": {"service_date": "2026-09-20"}})
        service = next(entry for entry in entries if entry["field"] == "service_date")
        self.assertEqual(service["source"], "openai_and_photo_metadata")
        self.assertEqual(service["confidence"], "high")

    def test_nested_transport_defaults_are_explained_without_inventing_values(self):
        entries = self.fields(candidate={"transport": {"destination": "Example City", "km_one_way": 12}}, profile_decision={"profile_key": "example", "mode": "auto_applied"}, profiles={"example": {"defaults": {"transport": {"destination": "Example City", "km_one_way": 12}, "payment_entity": "Unused Court"}}})
        by_field = {entry["field"]: entry for entry in entries}
        self.assertEqual(by_field["transport_destination"]["value"], "Example City")
        self.assertEqual(by_field["km_one_way"]["value"], 12)
        self.assertEqual(by_field["km_one_way"]["source"], "service_profile")
        self.assertEqual(by_field["km_one_way"]["confidence"], "high")
        self.assertNotIn("payment_entity", by_field)

    def test_review_blockers_remain_blockers_even_with_successful_ai(self):
        for status, code in (("set_aside", "translation_set_aside"), ("needs_info", "missing_required_info"), ("duplicate", "duplicate_request"), ("active_draft", "active_draft"), ("error", "review_error")):
            with self.subTest(status=status):
                attention = self.attention(review={"status": status, "questions": [{"number": 1}], "message": "Synthetic blocker"}, ai_recovery={"status": "ok"})
                self.assertEqual(attention["status"], "blocked")
                self.assertEqual(attention["flags"][0]["code"], code)

    def test_photo_date_confirmation_avoids_duplicate_missing_date_warning(self):
        attention = self.attention(candidate={"photo_metadata_date": "2026-09-20", "service_place": "Example City"}, ai_recovery={"status": "ok", "missing_fields": ["service_date"]})
        self.assertEqual(attention["status"], "review")
        self.assertEqual([flag["code"] for flag in attention["flags"]], ["photo_metadata_needs_confirmation"])
        self.assertIn("September 20 in Example City", attention["flags"][0]["detail"])
        self.assertIn("Confirm whether this was the service date", attention["flags"][0]["detail"])

    def test_attention_lists_quality_ai_fallback_and_proposal_for_review(self):
        attention = self.attention(warnings=[" first ", "", "second", "third", "fourth"], ai_recovery={"status": "failed", "reason": "Synthetic OCR unavailable"}, profile_decision={"mode": "auto_fallback", "reason": "Only profile available; review its recipient."}, profile_proposal={"status": "proposed"})
        self.assertEqual(attention["status"], "review")
        self.assertEqual(attention["flag_count"], 4)
        self.assertEqual([flag["code"] for flag in attention["flags"]], ["source_warnings", "ai_recovery_issue", "profile_fallback", "profile_proposal"])
        self.assertEqual(attention["flags"][0]["detail"], "first; second; third")
        self.assertIn("review its recipient", attention["flags"][2]["detail"])

    def test_profile_evidence_preserves_explicit_choice_and_separate_suggestion(self):
        evidence = build_profile_evidence({"mode": "explicit_profile", "profile_key": "kept", "suggested_profile_key": "suggested", "auto_applied": False, "signals": ["Synthetic Court", ""]})
        self.assertEqual(evidence["profile_key"], "kept")
        self.assertEqual(evidence["suggested_profile_key"], "suggested")
        self.assertFalse(evidence["auto_applied"])
        self.assertEqual(evidence["signals"], [{"text": "Synthetic Court", "source": "source_text_or_openai_ocr"}])

    def test_pure_evidence_does_not_mutate_inputs_or_read_and_write_files(self):
        inputs = dict(candidate={"service_date": "2026-09-20", "photo_metadata_date": "2026-09-21"}, deterministic_fields={"service_date": "2026-09-20"}, metadata={"exif_date": "2026-09-21"}, ai_recovery={"status": "ok", "fields": {}}, profile_decision={"mode": "auto_fallback", "profile_key": "example", "signals": ["Synthetic Court"]}, profiles={"example": {"defaults": {}}})
        before = copy.deepcopy(inputs)
        with patch.object(Path, "read_text", side_effect=AssertionError("Evidence must not read runtime files")), patch.object(Path, "write_text", side_effect=AssertionError("Evidence must not write runtime files")):
            entries = build_field_evidence(**inputs)
            build_profile_evidence(inputs["profile_decision"])
            self.attention(candidate=inputs["candidate"], ai_recovery=inputs["ai_recovery"], profile_decision=inputs["profile_decision"], field_evidence=entries)
        self.assertEqual(inputs, before)


class EvidenceBoundaryTests(unittest.TestCase):
    def test_existing_services_exports_preserve_caller_compatibility(self):
        for function in (build_field_evidence, build_profile_evidence, build_source_attention, combine_text_parts, fold_match_text):
            with self.subTest(function=function.__name__):
                self.assertIs(getattr(services, function.__name__), function)
        self.assertEqual(fold_match_text("Polícia Judiciária"), "policia judiciaria")
        self.assertEqual(combine_text_parts(" Synthetic ", "synthetic", "Evidence"), "Synthetic\n\nEvidence")

    def test_evidence_can_import_without_orchestration_or_optional_provider_dependencies(self):
        code = """
import json, sys
sys.path.insert(0, sys.argv[1])
from honorarios_app.source_evidence import build_source_attention
result = build_source_attention(candidate={}, review={'status': 'ready'}, ai_recovery={}, profile_decision={}, profile_proposal={}, field_evidence=[], warnings=[])
for name in ('honorarios_app.services', 'honorarios_app.ai_recovery', 'honorarios_app.gmail_draft_api', 'httpx', 'PIL', 'pypdf', 'fastapi', 'openai'):
    assert name not in sys.modules, name
print(json.dumps(result))
"""
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, "-I", "-c", code, str(root)], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), {"status": "ready", "flag_count": 0, "flags": []})


if __name__ == "__main__":
    unittest.main()
