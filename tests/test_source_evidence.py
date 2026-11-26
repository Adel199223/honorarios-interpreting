from __future__ import annotations

import copy
import hashlib
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
    def user_point_candidate(self):
        excerpts = ['radoria da República da Comarca de Fictional City',
                    'Local Criminal - 1ª Sec Inquéritos de Fictional City']
        text = '\n'.join(excerpts) + '\nLargo Old Address'
        point = {'geometry_basis': 'user_confirmed_photo_venue', 'confirmation_source_sha256': 'a' * 64,
                 'confirmation_date': '2026-11-01', 'radius_m': 50}
        location = {**point, 'source': 'verified_gps_source_venue', 'source_sha256': 'b' * 64,
                    'source_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                    'service_entity': 'Ministério Público de Fictional City', 'service_entity_type': 'ministerio_publico',
                    'city': 'Fictional City', 'service_place': 'Tribunal de Fictional City', 'distance_m': 2.5,
                    'reason': 'Editable inferred venue, not proof of attendance or interpreting.',
                    'source_urls': ['https://places.example.test/current-postal-address'],
                    'matched_source_phrases': ['local criminal', 'inqueritos de fictional city'],
                    'source_agency_corroboration': {'basis': 'corroborated_procuradoria_heading',
                        'derived_agency_type': 'ministerio_publico', 'city': 'Fictional City', 'raw_excerpts': excerpts}}
        candidate = {'source_text': text, 'source_sha256': 'b' * 64, 'photo_metadata_date': '2026-10-18',
                     'service_entity': location['service_entity'], 'service_entity_type': location['service_entity_type'],
                     'service_place': location['service_place'], 'source_location_evidence': location,
                     'photo_defaults_applied': {'photo_city': 'Fictional City', 'photo_city_source': 'verified_gps_area'}}
        return candidate, point

    def test_user_point_city_and_venue_explain_confirmation_separately_from_public_address(self):
        candidate, point = self.user_point_candidate()
        area = {**point, 'source_url': 'https://places.example.test/current-postal-address'}
        metadata = {'gps_city_match': {'status': 'matched', 'city': 'Fictional City', 'matches': [area]}}
        for source_metadata in (metadata, {}):
            with self.subTest(rereview=not source_metadata):
                rows = {row['field']: row for row in self.fields(candidate=candidate, metadata=source_metadata)}
                for field in ('photo_capture_city', 'service_place'):
                    reason = rows[field]['reason']
                    self.assertIn('user-confirmed photo-location point', reason)
                    self.assertIn('radius 50 m', reason)
                    self.assertIn('confirmed 2026-11-01', reason)
                    self.assertIn('not publicly verified building coordinates', reason)
                    self.assertIn('postal address separately', reason)
                    self.assertNotIn('confirmed 2026-10-18', reason)
                if source_metadata:
                    self.assertIn('user-confirmed photo-location point', rows['photo_gps_city']['reason'])
                    self.assertEqual(rows['photo_gps_city']['excerpt'], area['source_url'])
        self.assertEqual(candidate['photo_metadata_date'], '2026-10-18')

    def test_derived_mp_agency_quotes_actual_cropped_lines_without_inventing_literal_name(self):
        candidate, _ = self.user_point_candidate()
        for ai in ({}, {'status': 'ok', 'raw_visible_text': candidate['source_text'], 'fields': {}}):
            rows = {row['field']: row for row in self.fields(candidate=candidate, ai_recovery=ai)}
            agency = rows['source_agency_type']
            self.assertEqual(agency['label'], 'Derived source agency')
            self.assertEqual(agency['source'], 'corroborated_source_heading')
            self.assertEqual(agency['value'], 'ministerio_publico')
            self.assertEqual(agency['excerpt'], '\n'.join(candidate['source_location_evidence']['source_agency_corroboration']['raw_excerpts']))
            self.assertNotIn('Ministério Público', agency['excerpt'])
            self.assertIn('not claimed as literal source text', agency['reason'])
            self.assertNotIn('ministerio publico', rows['service_place']['excerpt'])
            if ai:
                self.assertIn('recovered by AI', agency['reason'])
        self.assertIn('Largo Old Address', candidate['source_text'])

    def test_stale_or_edited_venue_proof_does_not_label_current_service_as_user_point_or_derived_mp(self):
        candidate, _ = self.user_point_candidate()
        for changes in ({'source_sha256': 'c' * 64}, {'source_text': candidate['source_text'] + '\nEdited'},
                        {'service_place': 'Manual venue'}, {'service_entity': 'Manual agency'},
                        {'service_entity_type': 'other'}, {'photo_capture_city': 'Other City'}):
            with self.subTest(changes=changes):
                rows = self.fields(candidate={**candidate, **changes})
                self.assertFalse(any(row['field'] == 'source_agency_type' for row in rows))
                self.assertFalse(any('user-confirmed photo-location point' in row['reason'] for row in rows))
        candidate['source_location_evidence']['source_agency_corroboration']['raw_excerpts'][0] = 'Invented complete heading'
        self.assertFalse(any(row['field'] == 'source_agency_type' for row in self.fields(candidate=candidate)))

    def test_legacy_venue_never_receives_user_point_label_and_bad_metadata_is_not_described_as_confirmed(self):
        candidate, _ = self.user_point_candidate()
        location = candidate['source_location_evidence']
        for key in ('geometry_basis', 'confirmation_source_sha256', 'confirmation_date'):
            del location[key]
        self.assertFalse(any('user-confirmed photo-location point' in row['reason'] for row in self.fields(candidate=candidate)))
        location.update(geometry_basis='user_confirmed_photo_venue', confirmation_source_sha256='a' * 64,
                        confirmation_date='2026-11-01', radius_m=50.01)
        self.assertFalse(any('user-confirmed photo-location point' in row['reason'] for row in self.fields(candidate=candidate)))

    def test_documentary_source_context_is_rendered_visibly_and_escaped(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'honorarios_app/static/app.js').read_text(encoding='utf-8')
        body = source.split('function renderSourceEvidence(data) {', 1)[1].split('function renderAiRecovery', 1)[0].rsplit('}', 1)[0]
        script = r"""
const boxes = new Map();
function $(selector) { if (!boxes.has(selector)) boxes.set(selector, {innerHTML:'', className:'',querySelector:()=>null}); return boxes.get(selector); }
function escapeHtml(value) { return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'); }
function renderFieldEvidence() { return ''; }
function renderSourceAttention() { return ''; }
const render = (data) => new Function('data','$','escapeHtml','renderFieldEvidence','renderSourceAttention', BODY)(data,$,escapeHtml,renderFieldEvidence,renderSourceAttention);
const row={case_number:'711/26.0TSTXX',excerpt:'Junte certidão <img src=x onerror=evil()>',documentary_only:true};
render({review_evidence:{case_number:'710/26.0TSTXX',documentary_case_references:[row]}});
let html=$('#source-evidence-body').innerHTML;
if (!html.includes('excluded from requests') || !html.includes(row.case_number) || !html.includes('&lt;img') || html.includes('<img src=x')) throw Error('Missing or unsafe documentary evidence');
render({review_evidence:{case_number:'710/26.0TSTXX',documentary_case_references:[]}});
if ($('#source-evidence-body').innerHTML.includes(row.case_number)) throw Error('Stale documentary evidence survived changed source');
""".replace('BODY', json.dumps(body))
        run = subprocess.run(['node', '--input-type=module', '-'], input=script, text=True,
                             capture_output=True, check=False)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_corroborated_letterhead_retains_ai_origin_and_never_claims_a_physical_venue(self):
        text = 'NACIONAL REPUBLICANA\nCOMANDO TERRITORIAL DE Fictional City'
        agency = {'service_entity': 'Guarda Nacional Republicana', 'service_entity_type': 'gnr',
                  'evidence_text': text, 'reason': 'Two heading clues match.'}
        candidate = {**{key: agency[key] for key in ('service_entity', 'service_entity_type')},
                     'source_text': text, 'photo_defaults_applied': {'source_agency_evidence': agency}}
        for ai, expected in (({'status': 'ok', 'raw_visible_text': text, 'fields': {}}, 'openai_ocr'),
                             ({}, 'document_text')):
            with self.subTest(expected=expected):
                evidence = self.fields(candidate=candidate, ai_recovery=ai)
                rows = [row for row in evidence if row['field'] in {'service_entity', 'service_entity_type'}]
                self.assertEqual(len(rows), 2)
                for row in rows:
                    self.assertEqual(row['source'], expected)
                    self.assertIn('does not establish physical venue', row['reason'])
                self.assertFalse(any(row['field'] == 'service_place' for row in evidence))
        edited = {**candidate, 'service_entity': 'Manual agency', 'service_entity_type': 'other'}
        self.assertFalse(any('corroborated source letterhead' in row['reason'] for row in self.fields(candidate=edited)))

    def test_later_photo_case_has_scoped_ocr_evidence_without_promoting_self_agreement(self):
        text = 'Processos 710/26.0TSTXX e 711/26.0TSTXX'
        entries = self.fields(candidate={'case_number': '711/26.0TSTXX', 'source_case_numbers': ['710/26.0TSTXX', '711/26.0TSTXX'], 'source_text': text},
            deterministic_fields={'case_number': '710/26.0TSTXX'},
            ai_recovery={'status': 'ok', 'raw_visible_text': text, 'case_numbers': ['710/26.0TSTXX', '711/26.0TSTXX'], 'fields': {}})
        case = next(entry for entry in entries if entry['field'] == 'case_number')
        self.assertEqual(case['value'], '711/26.0TSTXX')
        self.assertEqual(case['source'], 'openai_ocr')
        self.assertEqual(case['confidence'], 'medium')

    def test_model_only_case_array_does_not_supply_confirmed_evidence(self):
        entries = self.fields(candidate={'case_number': '711/26.0TSTXX', 'source_case_numbers': ['711/26.0TSTXX'], 'source_text': 'Unreadable'},
            ai_recovery={'status': 'ok', 'raw_visible_text': 'Unreadable', 'case_numbers': ['711/26.0TSTXX'], 'fields': {}})
        self.assertFalse(any(entry['field'] == 'case_number' for entry in entries))

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

    def test_confirmed_date_difference_is_resolved_attention_with_both_dates_retained(self):
        for origin in ("user_confirmed", "user_confirmed_exception", "document_text_user_confirmed", "photo_metadata_user_confirmed"):
            with self.subTest(origin=origin):
                candidate = {"service_date": "2026-09-26", "photo_metadata_date": "2026-09-28", "service_date_source": origin}
                entries = self.fields(candidate=candidate, metadata={"exif_date": "2026-09-28"})
                before = copy.deepcopy(entries)
                attention = self.attention(candidate=candidate, field_evidence=entries)
                self.assertEqual(attention["status"], "ready")
                self.assertEqual(attention["flag_count"], 1)
                flag = attention["flags"][0]
                self.assertEqual((flag["code"], flag["severity"]), ("date_conflict_resolved", "info"))
                self.assertIn("2026-09-26", flag["detail"])
                self.assertIn("2026-09-28", flag["detail"])
                self.assertIn("no further date answer", flag["detail"])
                service = next(entry for entry in entries if entry["field"] == "service_date")
                self.assertEqual(service["conflicts_with"], {"field": "photo_metadata_date", "value": "2026-09-28"})
                self.assertEqual(entries, before, "Resolving attention must retain the original conflict ledger.")

    def test_date_confirmation_does_not_resolve_other_blockers_or_a_changed_date(self):
        candidate = {"service_date": "2026-09-26", "photo_metadata_date": "2026-09-28", "service_date_source": "user_confirmed_exception"}
        entries = self.fields(candidate=candidate, metadata={"exif_date": "2026-09-28"})
        for status in ("needs_info", "duplicate", "active_draft", "set_aside", "error"):
            with self.subTest(status=status):
                attention = self.attention(candidate=candidate, review={"status": status}, field_evidence=entries)
                self.assertEqual(attention["status"], "blocked")
                self.assertEqual(attention["flags"][0]["severity"], "blocked")
                self.assertEqual(attention["flags"][-1]["code"], "date_conflict_resolved")
        for changed in ({**candidate, "service_date": "2026-09-25"}, {**candidate, "service_date_source": "document_text"}):
            with self.subTest(changed=changed):
                attention = self.attention(candidate=changed, field_evidence=entries)
                self.assertEqual(attention["status"], "blocked")
                self.assertEqual(attention["flags"][0]["code"], "date_conflict")

    def test_metadata_origin_distinguishes_exif_visible_and_ai_recovered_metadata(self):
        for metadata, ai, source, confidence in (
            ({"exif_date": "2026-09-20", "visible_metadata_date": "2026-09-20"}, {}, "image_metadata", "high"),
            ({"visible_metadata_date": "2026-09-20"}, {}, "visible_google_photos_metadata", "high"),
            ({}, {"fields": {"photo_metadata_date": "2026-09-20"}}, "openai_ocr", "medium"),
            ({"visible_metadata_date": "2026-09-20"}, {"fields": {"photo_metadata_date": "2026-09-20"}}, "openai_ocr", "medium"),
            ({}, {}, "image_metadata", "medium"),
        ):
            with self.subTest(source=source, metadata=metadata):
                entry = self.fields(candidate={"photo_metadata_date": "2026-09-20"}, metadata=metadata, ai_recovery=ai)[0]
                self.assertEqual(entry["source"], source)
                self.assertEqual(entry["confidence"], confidence)

    def test_ai_provenance_uses_visible_values_and_does_not_claim_rejected_values(self):
        entries = self.fields(candidate={"payment_entity": "Synthetic Polícia", "recipient_email": "kept@example.test"}, ai_recovery={"status": "ok", "raw_visible_text": "SYNTHETIC POLICIA", "fields": {"payment_entity": "Synthetic Polícia", "court_email": "other@example.test"}})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["field"], "payment_entity")
        self.assertEqual(entries[0]["source"], "openai_ocr")
        self.assertEqual(entries[0]["confidence"], "medium")
        self.assertEqual(entries[0]["excerpt"], "SYNTHETIC POLICIA")
        self.assertIn("not independent confirmation", entries[0]["reason"])

    def test_ai_date_matching_image_metadata_is_not_confirmed_service_date(self):
        entries = self.fields(candidate={"service_date": "2026-09-20", "photo_metadata_date": "2026-09-20"}, ai_recovery={"status": "ok", "fields": {"service_date": "2026-09-20"}})
        service = next(entry for entry in entries if entry["field"] == "service_date")
        self.assertEqual(service["source"], "openai_and_photo_metadata")
        self.assertEqual(service["confidence"], "medium")
        self.assertIn("does not confirm when the service happened", service["reason"])

    def test_ai_inferred_payment_place_and_recipient_stay_low_and_reviewable(self):
        candidate = {"payment_entity": "Fictional Court", "service_place": "Fictional Office", "recipient_email": "court@example.test"}
        entries = self.fields(candidate=candidate, ai_recovery={"status": "ok", "raw_visible_text": "Interpretation requested", "fields": {**candidate, "court_email": candidate["recipient_email"]}})
        self.assertEqual({entry["field"] for entry in entries}, set(candidate))
        for entry in entries:
            self.assertEqual(entry["confidence"], "low")
            self.assertIn("may be inferred", entry["reason"])

    def test_reparsing_ai_ocr_does_not_promote_its_case_email_or_date(self):
        values = {"case_number": "123/26.0SYNTH", "service_date": "2026-09-20", "recipient_email": "court@example.test"}
        text = "Case 123/26.0SYNTH\nService: 20/09/2026\ncourt@example.test"
        entries = self.fields(candidate={**values, "source_text": text}, deterministic_fields=values, ai_recovery={"status": "ok", "raw_visible_text": text, "fields": {**values, "court_email": values["recipient_email"]}})
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(entry["source"] == "openai_ocr" and entry["confidence"] == "medium" for entry in entries))

    def test_independent_document_text_retains_its_provenance_despite_matching_ai(self):
        ai_text = "Possible process 123/26.0SYNTH"
        entries = self.fields(candidate={"case_number": "123/26.0SYNTH", "source_text": "Document process: 123/26.0SYNTH\n\n" + ai_text}, deterministic_fields={"case_number": "123/26.0SYNTH"}, ai_recovery={"status": "ok", "raw_visible_text": ai_text, "fields": {"case_number": "123/26.0SYNTH"}})
        self.assertEqual(entries[0]["source"], "deterministic_text")
        self.assertEqual(entries[0]["confidence"], "high")

    def test_explicit_unknown_service_place_is_source_evidence_without_a_saved_reference(self):
        place = "Posto da GNR de Faro"
        text = "Diligência de interpretação realizada no Posto da GNR de Faro em 26/09/2026."
        candidate = {"service_place": place, "source_text": text}
        deterministic = {"service_place": place}
        entry = self.fields(candidate=candidate, deterministic_fields=deterministic, profiles={})[0]
        self.assertEqual(entry["source"], "document_text")
        self.assertEqual(entry["confidence"], "high")
        self.assertIn("physical service place in the source text", entry["reason"])
        self.assertNotIn("known destination", entry["reason"])
        self.assertEqual(entry["excerpt"], text)
        ai_entry = self.fields(candidate=candidate, deterministic_fields=deterministic, profiles={},
                               ai_recovery={"status": "ok", "raw_visible_text": text, "fields": {"service_place": place}})[0]
        self.assertEqual(ai_entry["source"], "openai_ocr")
        self.assertEqual(ai_entry["confidence"], "medium", "Reparsing the same AI text cannot confirm an unknown place.")

    def test_patterns_found_only_in_ai_text_remain_ai_even_if_structured_fields_are_missing(self):
        text = "Process 123/26.0SYNTH\ncourt@example.test"
        fields = {"case_number": "123/26.0SYNTH", "recipient_email": "court@example.test"}
        entries = self.fields(candidate={**fields, "source_text": text}, deterministic_fields=fields, ai_recovery={"status": "ok", "raw_visible_text": text, "fields": {}})
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(entry["source"] == "openai_ocr" and entry["confidence"] == "medium" for entry in entries))

    def test_explicit_date_confirmation_is_distinct_from_ai_and_profile_defaults(self):
        for origin in ("user_confirmed", "user_confirmed_exception", "document_text_user_confirmed", "photo_metadata_user_confirmed"):
            with self.subTest(origin=origin):
                entries = self.fields(candidate={"service_date": "2026-09-20", "service_date_source": origin}, ai_recovery={"status": "ok", "fields": {"service_date": "2026-09-20"}})
                self.assertEqual(entries[0]["source"], "user_confirmed")
                self.assertIn("explicitly supplied or confirmed", entries[0]["reason"])

    def test_ai_conflicts_and_domain_blockers_do_not_disappear_with_new_confidence_labels(self):
        entries = self.fields(candidate={"service_date": "2026-09-20", "photo_metadata_date": "2026-09-21"}, ai_recovery={"status": "ok", "fields": {"service_date": "2026-09-20"}}, metadata={"exif_date": "2026-09-21"})
        attention = self.attention(field_evidence=entries, review={"status": "duplicate"})
        self.assertEqual(attention["status"], "blocked")
        self.assertEqual([flag["code"] for flag in attention["flags"]], ["duplicate_request", "date_conflict"])

    def test_nested_transport_defaults_are_explained_without_inventing_values(self):
        entries = self.fields(candidate={"transport": {"destination": "Example City", "km_one_way": 12}}, profile_decision={"profile_key": "example", "mode": "auto_applied"}, profiles={"example": {"defaults": {"transport": {"destination": "Example City", "km_one_way": 12}, "payment_entity": "Unused Court"}}})
        by_field = {entry["field"]: entry for entry in entries}
        self.assertEqual(by_field["transport_destination"]["value"], "Example City")
        self.assertEqual(by_field["km_one_way"]["value"], 12)
        self.assertEqual(by_field["km_one_way"]["source"], "service_profile")
        self.assertEqual(by_field["km_one_way"]["confidence"], "medium")
        self.assertIn("does not confirm this source", by_field["km_one_way"]["reason"])
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
