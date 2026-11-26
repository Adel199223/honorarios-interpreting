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
from honorarios_app.source_history import completed_fee_source_identity


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

    def completed_source(self, **changes):
        return {**self.intake, 'case_number': '', 'case_number_requires_confirmation': True,
                'service_date': '2026-11-05', 'service_date_source': 'photo_metadata',
                'photo_metadata_date': '2026-11-05', 'source_kind': 'photo', 'source_sha256': 'a' * 64,
                'source_text': ('Requerimento\nA requerente vem requerer o pagamento dos honorários, '
                                'por, no dia 18 junho de 2026, ter desempenhado as funções de '
                                'tradutor / intérprete no âmbito do inquérito NUIPC700/26.0EXAMPLE.\n'
                                'Fictionalton, 5 de novembro de 2026.'), **changes}

    def test_completed_fee_source_checks_paper_history_before_mixed_scope_without_changing_date(self):
        record = {**self.history(), 'submission_channel': 'paper', 'submission_evidence': 'user_confirmed'}
        self.paths.duplicate_index.write_text(json.dumps([record]), encoding='utf-8')
        intake = self.completed_source()
        result = self.review_without_writes(intake)
        self.assertEqual(result['status'], 'duplicate')
        self.assertEqual(result['questions'], [])
        self.assertEqual(result['source_history_identity']['service_date'], '2026-06-18')
        self.assertEqual(result['source_history_identity']['case_number'], '700/26.0EXAMPLE')
        self.assertEqual(intake['service_date'], '2026-11-05')
        self.assertIn('intake date has not been changed', result['message'])
        self.assertIn('already submitted on paper', result['message'])
        for key in ('sent_date', 'message_id', 'thread_id'):
            self.assertNotIn(key, result['duplicate'])

    def test_completed_source_drafted_active_and_explicit_exclusion_history(self):
        for active in (False, True):
            self.paths.duplicate_index.write_text('[]', encoding='utf-8')
            self.paths.draft_log.write_text('[]', encoding='utf-8')
            self.history(status='drafted', active=active)
            self.assertEqual(self.review_without_writes(self.completed_source())['status'],
                             'active_draft' if active else 'duplicate')
        self.paths.duplicate_index.write_text('[]', encoding='utf-8')
        self.paths.draft_log.write_text('[]', encoding='utf-8')
        self.paths.duplicate_index.with_name('paper-submissions.local.json').write_text(json.dumps({
            'schema_version': 1, 'excluded_cases': [{'case_number': '700/26.0EXAMPLE',
                'service_date': '2026-06-18', 'completion_evidence': 'user_confirmed_done'}]}), encoding='utf-8')
        result = self.review_without_writes(self.completed_source())
        self.assertEqual(result['status'], 'excluded')
        self.assertEqual(result['exclusion']['kind'], 'user_confirmed_done')

    def test_completed_source_no_match_and_wrong_historical_case_or_day_keep_normal_questions(self):
        for record in (None, {'case_number': '701/26.0EXAMPLE', 'service_date': '2026-06-18', 'status': 'sent'},
                       {'case_number': '700/26.0EXAMPLE', 'service_date': '2026-06-19', 'status': 'sent'}):
            self.paths.duplicate_index.write_text(json.dumps([record] if record else []), encoding='utf-8')
            result = self.review_without_writes(self.completed_source())
            self.assertEqual(result['status'], 'needs_info')
            self.assertIn('mixed_notice_scope', [row['field'] for row in result['questions']])
            self.assertNotIn('source_history_identity', result)

    def test_completed_source_parser_rejects_ambiguous_negated_future_and_unbound_evidence(self):
        source = self.completed_source()['source_text']
        variants = [source + '\nProcesso 701/26.0EXAMPLE',
                    source.replace('NUIPC700/26.0EXAMPLE', 'NUIPC700/26.0EXAMPLE ou ilegível'),
                    source.replace('NUIPC700/26.0EXAMPLE', 'NPP 700/26.0EXAMPLE'),
                    source.replace('EXAMPLE', 'E X A M P L E'),
                    source.replace('ter desempenhado', 'não ter desempenhado'),
                    source.replace('ter desempenhado', 'irá desempenhar'),
                    source.replace('18 junho de 2026', '30 fevereiro de 2026'),
                    source.replace('no dia 18 junho de 2026, ter desempenhado', 'emitido no dia 18 junho de 2026, para desempenhar'),
                    source.replace('no dia 18 junho de 2026, ter desempenhado', 'ter desempenhado'),
                    source + '\nNo dia 19 junho de 2026, ter prestado o serviço.',
                    source.replace('Requerimento', 'Certificado de presença')]
        for text in variants:
            with self.subTest(text=text):
                self.assertIsNone(completed_fee_source_identity(self.completed_source(source_text=text)))
        for changes in ({'source_kind': 'manual_review'}, {'source_sha256': ''},
                        {'source_text': '', 'notes': source}, {'source_text': '', 'source_filename': source},
                        {'source_text': '', 'ai_recovery': {'fields': {'case_number': '700/26.0EXAMPLE'}}},
                        {'ai_recovery': {'source_scope': 'uncertain'}},
                        {'ai_recovery': {'incidental_background_text': source}}):
            with self.subTest(changes=changes):
                self.assertIsNone(completed_fee_source_identity(self.completed_source(**changes)))

    def test_completed_source_manual_conflicts_are_visible_and_derived_input_is_not_authority(self):
        self.history()
        for changes in ({'case_number': '701/26.0EXAMPLE'},
                        {'case_number': '700/26.0EXAMPLE', 'service_date_source': 'user_confirmed'}):
            result = self.review_without_writes(self.completed_source(**changes))
            self.assertEqual(result['status'], 'needs_info')
            self.assertIn('conflicts with this completed fee source', result['message'])
            self.assertEqual(result['source_history_identity']['service_date'], '2026-06-18')
        stale = self.completed_source(source_text='An ordinary attendance certificate.',
            source_history_identity={'case_number': '700/26.0EXAMPLE', 'service_date': '2026-06-18'})
        self.assertEqual(self.review_without_writes(stale)['status'], 'needs_info')

    def test_source_bound_separate_service_confirmation_preserves_manual_date_and_rechecks_history(self):
        from honorarios_app.services import apply_numbered_answers
        self.history()
        intake = self.completed_source(case_number='700/26.0EXAMPLE', service_date_source='user_confirmed_exception')
        result = self.review_without_writes(intake)
        self.assertEqual(result['questions'][0]['field'], 'source_history_separate_service')
        confirmed = apply_numbered_answers({'intake': intake, 'answers': '1. separate-service'}, self.paths)
        self.assertTrue(confirmed['source_history_separate_service_confirmed'])
        current = confirmed['intake']
        self.assertEqual(current['service_date'], '2026-11-05')
        self.assertEqual(current['service_date_source'], 'user_confirmed_exception')
        self.assertIn('mixed_notice_scope', [row['field'] for row in confirmed['questions']])
        for changes in ({'source_sha256': 'b' * 64}, {'source_text': current['source_text'] + '\nChanged source.'},
                        {'service_date': '2026-11-06'}, {'case_number': '702/26.0EXAMPLE'}):
            changed = self.review_without_writes({**current, **changes})
            self.assertEqual(changed['questions'][0]['field'], 'source_history_separate_service')
        self.paths.duplicate_index.write_text(json.dumps([{'case_number': '700/26.0EXAMPLE',
            'service_date': '2026-11-05', 'status': 'sent'}]), encoding='utf-8')
        # Confirming a separate service never exempts that service's own history.
        from scripts.source_classification import source_scope_fingerprint
        current.update(mixed_notice_scope='interpreting-only')
        current['mixed_notice_scope_fingerprint'] = source_scope_fingerprint(current)
        self.assertEqual(self.review_without_writes(current)['status'], 'duplicate')

    def test_completed_source_distinct_reviewed_period_retains_normal_overlap(self):
        from honorarios_app.services import apply_numbered_answers
        self.history(period='manhã')
        self.assertEqual(self.review_without_writes(self.completed_source())['status'], 'duplicate')
        intake = self.completed_source(case_number='700/26.0EXAMPLE',service_date='2026-06-18',
                                       service_date_source='user_confirmed',service_period_label='tarde')
        result = self.review_without_writes(intake)
        self.assertEqual(result['status'], 'needs_info')
        self.assertEqual(result['questions'][0]['field'],'source_history_separate_service')
        confirmed = apply_numbered_answers({'intake':intake,'answers':'1. separate-service'}, self.paths)
        self.assertTrue(confirmed['source_history_separate_service_confirmed'])
        current = confirmed['intake']
        changed = self.review_without_writes({**current,'service_period_label':'noite'})
        self.assertEqual(changed['questions'][0]['field'],'source_history_separate_service')

    def test_cli_completed_source_guards_stop_before_new_generation_or_email_payload(self):
        import contextlib
        from io import StringIO
        from scripts.generate_pdf import main as pdf_main
        from scripts.build_email_draft import main as email_main
        self.history()
        path = self.root / 'fictional-completed-intake.json'
        path.write_text(json.dumps(self.completed_source()), encoding='utf-8')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for function, arguments in ((pdf_main, [str(path), '--allow-duplicate']),
                                    (email_main, [str(path), '--pdf', str(self.root / 'absent.pdf')])):
            with contextlib.redirect_stderr(StringIO()) as output:
                self.assertEqual(function([*arguments, '--duplicate-index', str(self.paths.duplicate_index)]), 2)
            self.assertIn('Source service identity', output.getvalue())
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        import subprocess, sys
        result = subprocess.run([sys.executable, 'scripts/generate_pdf.py', str(path), '--allow-duplicate',
            '--duplicate-index', str(self.paths.duplicate_index)], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('Source service identity', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_completed_source_history_blocks_preflight_prepare_even_with_duplicate_override(self):
        self.history()
        intake = self.completed_source(case_number='700/26.0EXAMPLE')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = preflight_intakes([intake], self.paths, allow_duplicate=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('Source service identity', result['message'])
        with self.assertRaisesRegex(IntakeError, 'Source service identity'):
            prepare_intakes([intake], self.paths, allow_duplicate=True)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_recovered_details_rereview_preserves_original_source_and_capture_default(self):
        from honorarios_app.services import review_intake_with_profile_evidence
        self.history()
        intake = self.completed_source()
        result = review_intake_with_profile_evidence(intake, self.paths)
        self.assertEqual(result['status'],'duplicate')
        for key in ('source_sha256','source_kind','source_text','service_date','photo_metadata_date'):
            self.assertEqual(result['intake'][key],intake[key])
        self.assertEqual(result['source_history_identity']['service_date'],'2026-06-18')

    def test_selected_custom_draft_log_blocks_hidden_source_identity(self):
        from scripts.prepare_honorarios import validate_intake_before_generation
        records = [{'case_number':'700/26.0EXAMPLE','service_date':'2026-06-18',
                    'status':'active','draft_id':'fictional-custom-log-draft'}]
        with self.assertRaisesRegex(IntakeError,'Source service identity'):
            validate_intake_before_generation(self.root/'absent.json',self.completed_source(),profile={},
                email_config={},court_directory=[],duplicate_index=self.paths.duplicate_index,draft_log=records,
                allow_duplicate=False,allow_existing_draft=False)

    def test_same_actual_source_request_keeps_exact_record_retry_and_guarded_correction(self):
        from honorarios_app.services import record_draft
        source = json.loads((Path(__file__).resolve().parents[1] / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        source['recipient_email']=SYNTHETIC_COURT_EMAIL
        intake,_,_=effective_intake_for_profile(source,self.paths)
        intake.update(self.completed_source(case_number=intake['case_number'],claim_transport=False,
            service_date='2026-06-18',photo_metadata_date='2026-06-18',service_date_source='photo_metadata'))
        intake['source_text']=intake['source_text'].replace('700/26.0EXAMPLE',intake['case_number'])
        from scripts.source_classification import source_scope_fingerprint
        intake.update(mixed_notice_scope='interpreting-only')
        intake['mixed_notice_scope_fingerprint']=source_scope_fingerprint(intake)
        prepared=prepare_intakes([intake],self.paths)
        request={'payload':prepared['items'][0]['draft_payload'],'prepared_review':prepared['prepared_review'],
                 'gmail_handoff_reviewed':True,'draft_id':'synthetic-exact-draft',
                 'message_id':'synthetic-exact-message','thread_id':'synthetic-exact-thread'}
        record_draft(request,self.paths)
        record_draft(request,self.paths)
        self.assertEqual(len(json.loads(self.paths.draft_log.read_text(encoding='utf-8'))),1)
        correction=preflight_intakes([intake],self.paths,allow_existing_draft=True,correction_reason='Fictional reviewed correction')
        self.assertEqual(correction['status'],'ready',correction['message'])

    def test_late_completed_source_history_blocks_frozen_prepared_handoff_create_and_record(self):
        from honorarios_app.services import record_draft
        source = json.loads((Path(__file__).resolve().parents[1] / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        source['recipient_email'] = SYNTHETIC_COURT_EMAIL
        intake, _, _ = effective_intake_for_profile(source, self.paths)
        intake.update(self.completed_source(case_number=intake['case_number'], claim_transport=False))
        intake['source_text'] = intake['source_text'].replace('700/26.0EXAMPLE', intake['case_number'])
        intake.update(service_date='2026-11-05', service_date_source='photo_metadata',
                      mixed_notice_scope='interpreting-only')
        from scripts.source_classification import source_scope_fingerprint
        intake['mixed_notice_scope_fingerprint'] = source_scope_fingerprint(intake)
        prepared = prepare_intakes([intake], self.paths)
        target = prepared['items'][0]
        draft_data = json.loads(Path(target['draft_payload']).read_text(encoding='utf-8'))
        self.assertIn('source_history_evidence', draft_data)
        self.assertNotIn('source_history_evidence', draft_data['gmail_create_draft_args'])
        request = {'payload': target['draft_payload'], 'prepared_review': prepared['prepared_review'], 'gmail_handoff_reviewed': True,
                   'draft_id': 'synthetic-late-draft', 'message_id': 'synthetic-late-message', 'thread_id': 'synthetic-late-thread'}
        self.paths.duplicate_index.write_text(json.dumps([{'case_number': intake['case_number'], 'service_date': '2026-06-18', 'status': 'sent'}]), encoding='utf-8')
        before = self.paths.duplicate_index.read_bytes(), self.paths.draft_log.read_bytes()
        with self.assertRaisesRegex(IntakeError, 'Source service identity'):
            manual_handoff_packet(request, self.paths)
        with patch('honorarios_app.services.create_gmail_draft_from_payload') as provider:
            with self.assertRaisesRegex(IntakeError, 'Source service identity'):
                create_and_record_gmail_api_draft(request, self.paths)
            provider.assert_not_called()
        with self.assertRaisesRegex(IntakeError, 'Source service identity'):
            record_draft(request, self.paths)
        from scripts.record_gmail_draft import main as record_main
        import contextlib
        from io import StringIO
        with contextlib.redirect_stderr(StringIO()) as output:
            self.assertEqual(record_main(['--payload', target['draft_payload'], '--draft-id', request['draft_id'],
                '--message-id', request['message_id'], '--thread-id', request['thread_id'],
                '--log', str(self.paths.draft_log), '--duplicate-index', str(self.paths.duplicate_index)]), 2)
        self.assertIn('Source service identity', output.getvalue())
        self.assertEqual(before, (self.paths.duplicate_index.read_bytes(), self.paths.draft_log.read_bytes()))


if __name__ == '__main__':
    unittest.main()
