"""Known requests warn before unrelated questions, using only fictional local history."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from honorarios_app.runtime import SYNTHETIC_COURT_EMAIL, create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (AppPaths, create_and_record_gmail_api_draft, duplicate_payload,
                                    draft_lifecycle_for_intake, effective_intake_for_profile, manual_handoff_packet,
                                    preflight_intakes, prepare_intakes, review_intake)
from scripts.generate_pdf import IntakeError, format_duplicate_message


class EarlyDuplicateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-early-duplicate-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        self.intake = {
            'case_number': '0700/26.0EXAMPLE', 'service_date': '2026-06-18',
            'claim_transport': True, 'transport': {'destination': 'Fictionalton'},
        }

    def history(self, *, status='sent', period='', active=False):
        record = {'case_number': '700/26.0example', 'service_date': '2026-06-18'}
        if status is not None:
            record['status'] = status
        if period:
            record['service_period_label'] = period
        if active:
            record.update(status='active', draft_id='synthetic-existing-draft')
            self.paths.draft_log.write_text(json.dumps([record]), encoding='utf-8')
        else:
            self.paths.duplicate_index.write_text(json.dumps([record]), encoding='utf-8')
        return record

    def review_without_writes(self, intake=None):
        incoming = copy.deepcopy(intake if intake is not None else self.intake)
        original = copy.deepcopy(incoming)
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result = review_intake(incoming, self.paths)
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(incoming, original)
        self.assertFalse(result['send_allowed'])
        return result

    def test_sent_drafted_and_legacy_history_warn_before_payer_and_distance(self):
        for status in ('sent', 'drafted', None):
            with self.subTest(status=status):
                self.history(status=status)
                result = self.review_without_writes()
                self.assertEqual(result['status'], 'duplicate')
                self.assertEqual(result['duplicate']['status'], status or 'sent')
                self.assertEqual(result['duplicate']['case_number'], '700/26.0example')
                self.assertEqual(result['questions'], [])
                self.assertTrue(result['next_safe_action']['blocked'])

    def test_user_confirmed_paper_submission_blocks_without_inventing_email_or_date(self):
        record = {**self.history(), 'submission_channel': 'paper', 'submission_evidence': 'user_confirmed',
                  'source_filename': 'fictional-signed-fees.jpg', 'source_sha256': 'a' * 64}
        self.paths.duplicate_index.write_text(json.dumps([record]), encoding='utf-8')
        result = self.review_without_writes()
        self.assertEqual(result['status'], 'duplicate')
        self.assertEqual(result['questions'], [])
        self.assertEqual(result['duplicate']['status'], 'sent')
        self.assertEqual(result['duplicate']['submission_channel'], 'paper')
        self.assertEqual(result['duplicate']['submission_evidence'], 'user_confirmed')
        self.assertIn('already submitted on paper', result['message'])
        self.assertIn('already submitted on paper', result['next_safe_action']['detail'])
        self.assertNotIn('already sent', result['message'])
        for field in ('draft_id', 'message_id', 'thread_id', 'sent_date'):
            self.assertNotIn(field, result['duplicate'])
        lifecycle = draft_lifecycle_for_intake(self.intake, self.paths)
        self.assertEqual(lifecycle['status'], 'blocked')
        self.assertFalse(lifecycle['replacement_allowed'])
        self.assertIn('already submitted on paper', lifecycle['message'])
        self.assertEqual(lifecycle['duplicate_records'][0], result['duplicate'])
        for changed in ({'case_number': '701/26.0EXAMPLE'}, {'service_date': '2026-06-19'}):
            self.assertEqual(self.review_without_writes({**self.intake, **changed})['status'], 'needs_info')

    def test_paper_history_preserves_same_day_period_duplicate_rules(self):
        record = {**self.history(period='manhã'), 'submission_channel': 'paper', 'submission_evidence': 'user_confirmed'}
        self.paths.duplicate_index.write_text(json.dumps([record]), encoding='utf-8')
        for period in ('', ' Manhã '):
            self.assertEqual(self.review_without_writes({**self.intake, 'service_period_label': period})['status'], 'duplicate')
        self.assertEqual(self.review_without_writes({**self.intake, 'service_period_label': 'tarde'})['status'], 'needs_info')

    def test_paper_history_blocks_prepare_and_a_previously_prepared_handoff_before_provider(self):
        source = json.loads((Path(__file__).resolve().parents[1] / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        source['recipient_email'] = SYNTHETIC_COURT_EMAIL
        intake, _, _ = effective_intake_for_profile(source, self.paths)
        prepared = prepare_intakes([intake], self.paths)
        target = prepared['items'][0]
        request = {'payload': target['draft_payload'], 'prepared_review': prepared['prepared_review'], 'gmail_handoff_reviewed': True}
        record = {'case_number': intake['case_number'], 'service_date': intake['service_date'], 'status': 'sent',
                  'submission_channel': 'paper', 'submission_evidence': 'user_confirmed'}
        self.paths.duplicate_index.write_text(json.dumps([record]), encoding='utf-8')
        before = self.paths.duplicate_index.read_bytes(), self.paths.draft_log.read_bytes()
        preflight = preflight_intakes([intake], self.paths)
        self.assertEqual(preflight['status'], 'blocked')
        self.assertIn('already submitted on paper', preflight['message'])
        with self.assertRaisesRegex(IntakeError, 'already submitted on paper'):
            prepare_intakes([intake], self.paths)
        with self.assertRaisesRegex(IntakeError, 'already submitted on paper'):
            manual_handoff_packet(request, self.paths)
        with patch('honorarios_app.services.create_gmail_draft_from_payload') as provider:
            with self.assertRaisesRegex(IntakeError, 'already submitted on paper'):
                create_and_record_gmail_api_draft(request, self.paths)
            provider.assert_not_called()
        self.assertEqual((self.paths.duplicate_index.read_bytes(), self.paths.draft_log.read_bytes()), before)

    def test_paper_presentation_requires_confirmed_completed_evidence_and_channels_are_allowlisted(self):
        record = self.history()
        ordinary = format_duplicate_message(record)
        self.assertIn('Status: already sent', ordinary)
        for changes in ({'submission_channel': 'other'}, {'submission_channel': 'paper'},
                        {'submission_channel': 'paper', 'submission_evidence': 'unverified'},
                        {'submission_channel': 'paper', 'submission_evidence': 'user_confirmed', 'status': 'drafted'}):
            with self.subTest(changes=changes):
                changed = {**record, **changes}
                self.assertNotIn('submitted on paper', format_duplicate_message(changed))
                self.assertNotIn('submission_channel', duplicate_payload(changed))
                self.assertNotIn('submission_evidence', duplicate_payload(changed))
        email = {**record, 'submission_channel': 'email', 'sent_date': '2026-06-20', 'message_id': 'fictional-sent-message'}
        self.assertEqual(duplicate_payload(email)['submission_channel'], 'email')
        self.assertIn('Already sent: 2026-06-20', format_duplicate_message(email))
        self.assertNotIn('submitted on paper', format_duplicate_message(email))

    def test_active_draft_log_warns_when_index_has_not_been_reconciled(self):
        self.history(active=True)
        result = self.review_without_writes()
        self.assertEqual(result['status'], 'active_draft')
        self.assertEqual(result['active_gmail_drafts'][0]['draft_id'], 'synthetic-existing-draft')
        self.assertEqual(result['questions'], [])

    def test_nonstandard_verified_history_warns_without_accepting_new_case_format(self):
        intake = {**self.intake, 'case_number': '0700 / 26 . EXAMPLE'}
        for status in ('sent', 'drafted', None):
            with self.subTest(status=status):
                record = {'case_number': '700/26.example', 'service_date': '2026-06-18'}
                if status is not None:
                    record['status'] = status
                self.paths.duplicate_index.write_text(json.dumps([record]), encoding='utf-8')
                result = self.review_without_writes(intake)
                self.assertEqual(result['status'], 'duplicate')
                self.assertEqual(result['duplicate']['case_number'], '700/26.example')
        record.update(status='active', draft_id='synthetic-nonstandard-draft')
        self.paths.duplicate_index.write_text('[]', encoding='utf-8')
        self.paths.draft_log.write_text(json.dumps([record]), encoding='utf-8')
        self.assertEqual(self.review_without_writes(intake)['status'], 'active_draft')
        self.paths.draft_log.write_text('[]', encoding='utf-8')
        complete = {**intake, 'payment_entity': 'Tribunal Fictional', 'addressee': 'Tribunal Fictional',
                    'claim_transport': False, 'closing_city': 'Fictionalton', 'closing_date': '2026-06-20'}
        result = self.review_without_writes(complete)
        self.assertEqual(result['status'], 'needs_info')
        self.assertIn('case_number', [row['field'] for row in result['questions']])

    def test_nonstandard_history_keeps_exact_identity_and_period_guards(self):
        record = {'case_number': '700/26.EXAMPLE', 'service_date': '2026-06-18',
                  'status': 'sent', 'service_period_label': 'manhã'}
        self.paths.duplicate_index.write_text(json.dumps([record]), encoding='utf-8')
        intake = {**self.intake, 'case_number': '700/26.EXAMPLE'}
        self.assertEqual(self.review_without_writes(intake)['status'], 'duplicate')
        for changed in ({'service_period_label': 'tarde'}, {'service_date': '2026-06-19'},
                        {'case_number': '701/26.EXAMPLE'}):
            with self.subTest(changed=changed):
                result = self.review_without_writes({**intake, **changed})
                self.assertEqual(result['status'], 'needs_info')
                self.assertIn('case_number', [row['field'] for row in result['questions']])

    def test_nonstandard_history_does_not_skip_date_source_or_scope_confirmation(self):
        intake = {**self.intake, 'case_number': '700/26.EXAMPLE'}
        variants = [
            {'case_number': '700/26.EXAMPLE or 701/26.EXAMPLE'},
            {'case_number_requires_confirmation': True},
            {'source_case_numbers': ['700/26.EXAMPLE']},
            {'service_date': ''},
            {'photo_metadata_date': '2026-06-19', 'service_date_source': 'document_text'},
            {'service_date': '', 'photo_metadata_date': '2026-06-18', 'photo_metadata_date_requires_confirmation': True},
            {'source_text': 'Intérprete: eventual diligência e tradução escrita.'},
        ]
        for changed in variants:
            with self.subTest(changed=changed), patch('honorarios_app.services.find_duplicate_record') as duplicates, patch('honorarios_app.services.load_draft_log') as drafts:
                self.assertEqual(self.review_without_writes({**intake, **changed})['status'], 'needs_info')
                duplicates.assert_not_called()
                drafts.assert_not_called()
        with patch('honorarios_app.services.find_duplicate_record') as duplicates, patch('honorarios_app.services.load_draft_log') as drafts:
            self.assertEqual(self.review_without_writes({**intake, 'service_date': '2026-02-30'})['status'], 'error')
            self.assertEqual(self.review_without_writes({**intake, 'source_text': 'Tradução escrita de documento: 150 palavras.'})['status'], 'set_aside')
            duplicates.assert_not_called()
            drafts.assert_not_called()

    def test_blank_period_overlaps_but_distinct_period_keeps_questions(self):
        for active in (False, True):
            with self.subTest(active=active):
                self.paths.duplicate_index.write_text('[]', encoding='utf-8')
                self.paths.draft_log.write_text('[]', encoding='utf-8')
                self.history(period=' Manhã ', active=active)
                expected = 'active_draft' if active else 'duplicate'
                self.assertEqual(self.review_without_writes()['status'], expected)
                self.assertEqual(self.review_without_writes({**self.intake, 'service_period_label': 'manhã'})['status'], expected)
                result = self.review_without_writes({**self.intake, 'service_period_label': 'tarde'})
                self.assertEqual(result['status'], 'needs_info')
                self.assertIn('payment_entity', [row['field'] for row in result['questions']])

    def test_no_match_or_retired_history_keeps_normal_questions(self):
        for status in ('superseded', 'trashed', 'not_found'):
            with self.subTest(status=status):
                self.history(status=status)
                result = self.review_without_writes()
                self.assertEqual(result['status'], 'needs_info')
                self.assertIn('payment_entity', [row['field'] for row in result['questions']])
                self.assertIn('transport.km_one_way', [row['field'] for row in result['questions']])
        self.history()
        self.assertEqual(self.review_without_writes({**self.intake, 'service_date': '2026-06-19'})['status'], 'needs_info')

    def test_unknown_or_conflicting_identity_never_reads_history(self):
        variants = [
            {**self.intake, 'case_number': ''},
            {**self.intake, 'case_number': '700/26.0EXAMPLE or 701/26.0EXAMPLE', 'case_number_requires_confirmation': True},
            {**self.intake, 'service_date': ''},
            {**self.intake, 'service_date': '', 'photo_metadata_date': '2026-06-18', 'photo_metadata_date_requires_confirmation': True},
            {**self.intake, 'photo_metadata_date': '2026-06-19', 'service_date_source': 'document_text'},
        ]
        for intake in variants:
            with self.subTest(intake=intake), patch('honorarios_app.services.find_duplicate_record') as duplicates, patch('honorarios_app.services.load_draft_log') as drafts:
                self.assertEqual(self.review_without_writes(intake)['status'], 'needs_info')
                duplicates.assert_not_called()
                drafts.assert_not_called()

    def test_invalid_calendar_date_never_reads_history(self):
        for invalid in ('2026-02-30', '18/06/2026', 'not a date'):
            with self.subTest(invalid=invalid), patch('honorarios_app.services.find_duplicate_record') as duplicates, patch('honorarios_app.services.load_draft_log') as drafts:
                result = self.review_without_writes({**self.intake, 'service_date': invalid})
                self.assertEqual(result['status'], 'error')
                self.assertIn('YYYY-MM-DD', result['message'])
                duplicates.assert_not_called()
                drafts.assert_not_called()

    def test_complete_manual_request_with_ambiguous_case_still_asks_before_history(self):
        intake = {**self.intake, 'case_number': '700/26.0EXAMPLE or 701/26.0EXAMPLE',
                  'payment_entity': 'Tribunal Fictional', 'addressee': 'Tribunal Fictional',
                  'claim_transport': False, 'closing_city': 'Fictionalton', 'closing_date': '2026-06-20'}
        with patch('honorarios_app.services.find_duplicate_record') as duplicates, patch('honorarios_app.services.load_draft_log') as drafts:
            result = self.review_without_writes(intake)
            self.assertEqual(result['status'], 'needs_info')
            self.assertIn('case_number', [row['field'] for row in result['questions']])
            duplicates.assert_not_called()
            drafts.assert_not_called()

    def test_confirmed_date_exception_can_warn_before_other_questions(self):
        self.history()
        result = self.review_without_writes({**self.intake, 'photo_metadata_date': '2026-06-19',
                                            'service_date_source': 'user_confirmed_exception'})
        self.assertEqual(result['status'], 'duplicate')

    def test_translation_only_stays_set_aside_without_history_reads(self):
        self.history()
        with patch('honorarios_app.services.find_duplicate_record') as duplicates, patch('honorarios_app.services.load_draft_log') as drafts:
            result = self.review_without_writes({**self.intake, 'source_text': 'Tradução escrita de documento: 150 palavras.'})
            self.assertEqual(result['status'], 'set_aside')
            duplicates.assert_not_called()
            drafts.assert_not_called()

    def test_ambiguous_mixed_scope_stays_unresolved_before_history_reads(self):
        self.history()
        with patch('honorarios_app.services.find_duplicate_record') as duplicates, patch('honorarios_app.services.load_draft_log') as drafts:
            result = self.review_without_writes({**self.intake, 'source_text': 'Intérprete: eventual diligência e tradução escrita.'})
            self.assertEqual(result['status'], 'needs_info')
            self.assertIn('mixed_notice_scope', [row['field'] for row in result['questions']])
            duplicates.assert_not_called()
            drafts.assert_not_called()


if __name__ == '__main__':
    unittest.main()
