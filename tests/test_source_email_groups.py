"""Fictional offline checks for separate PDFs grouped into one source-photo email."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from honorarios_app.runtime import SYNTHETIC_COURT_EMAIL, create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (
    AppPaths, create_and_record_gmail_api_draft, draft_lifecycle_for_email_group,
    effective_intake_for_profile, manual_handoff_packet, preflight_intakes, prepare_intakes,
    record_draft, require_current_preflight_review, require_current_prepared_review, source_email_group_plan,
)
from honorarios_app.web import create_app
from scripts.build_email_draft import file_sha256, validate_draft_payload
from scripts.generate_pdf import IntakeError
from scripts.record_gmail_draft import main as record_cli

ROOT = Path(__file__).resolve().parents[1]


class SourceEmailGroupsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fictional-source-email-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        row = json.loads((ROOT / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        row['recipient_email'] = SYNTHETIC_COURT_EMAIL
        self.intake, _, _ = effective_intake_for_profile(row, self.paths)
        self.network = patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('Network forbidden in source email tests'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def rows(self, count=6):
        rows = []
        for index in range(count):
            row = copy.deepcopy(self.intake)
            row.update(case_number=f'{700 + index}/26.0TSTXX', source_sha256=('a' if index == 0 else 'b') * 64,
                       claim_transport=index < 2)
            if index:
                row['travel_group_id'] = 'fictional-five-cases-one-visit'
            rows.append(row)
        return rows

    def prepare(self, rows=None, **options):
        return prepare_intakes(rows or self.rows(), self.paths, email_grouping='source', **options)

    def record_args(self, target, status='active'):
        return ['--payload', target['draft_payload'], '--draft-id', 'fictional-group-draft',
                '--message-id', 'fictional-group-message', '--status', status,
                '--log', str(self.paths.draft_log), '--duplicate-index', str(self.paths.duplicate_index)]

    def record(self, target, status='active'):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return record_cli(self.record_args(target, status))

    def request(self, prepared, target):
        return {'payload': target['draft_payload'], 'prepared_review': prepared['prepared_review'],
                'gmail_handoff_reviewed': True}

    def assert_no_artifacts(self):
        for directory in (self.paths.output_dir, self.paths.html_dir, self.paths.draft_output_dir,
                          self.paths.manifest_dir, self.paths.intake_output_dir, self.paths.packet_output_dir):
            self.assertFalse(directory.exists() and any(directory.iterdir()), str(directory))

    def test_six_requests_form_two_targets_with_each_separate_pdf_and_exact_members(self):
        prepared = self.prepare()
        groups = prepared['email_groups']
        self.assertEqual([group['member_indices'] for group in groups], [[0], [1, 2, 3, 4, 5]])
        self.assertEqual([group['attachment_count'] for group in groups], [1, 5])
        self.assertEqual(len(prepared['items']), 6)
        self.assertEqual(len(prepared['prepared_review']['payload_paths']), 2)
        self.assertNotIn('packet', prepared)
        for group in groups:
            self.assertFalse(group['send_allowed'])
            self.assertEqual(group['attachment_files'], [prepared['items'][index]['pdf'] for index in group['member_indices']])
            payload = json.loads(Path(group['draft_payload']).read_text(encoding='utf-8'))
            self.assertEqual(validate_draft_payload(payload), [])
            for index, child in zip(group['member_indices'], payload['underlying_requests']):
                self.assertEqual(child['pdf'], prepared['items'][index]['pdf'])
                self.assertEqual(child['pdf_sha256'], file_sha256(Path(child['pdf'])))
                self.assertEqual(child['draft_payload'], prepared['items'][index]['draft_payload'])
        self.assertIn('5 requerimentos', groups[1]['body'])
        self.assertIn('ficheiro PDF separado', groups[1]['body'])
        self.assertNotIn('pacote PDF', groups[1]['body'])
        self.assertEqual([row['claim_transport'] for row in groups[1]['underlying_requests']], [True, False, False, False, False])

    def test_same_photo_recipient_conflict_blocks_before_any_artifact(self):
        rows = self.rows(3)[1:]
        rows[1].update(recipient_email=SYNTHETIC_COURT_EMAIL.replace('court@', 'fictional-alternate@'), recipient_override_reason='Fictional explicitly selected alternate contact')
        self.assertEqual(preflight_intakes(rows, self.paths, email_grouping='source')['status'], 'blocked')
        with self.assertRaisesRegex(IntakeError, 'different recipients'):
            self.prepare(rows)
        self.assert_no_artifacts()

    def test_profile_conflict_is_not_silently_split_into_two_emails(self):
        rows = self.rows(3)[1:]
        rows[0]['personal_profile_id'] = 'fictional-a'
        rows[1]['personal_profile_id'] = 'fictional-b'
        with self.assertRaisesRegex(IntakeError, 'personal profiles'):
            source_email_group_plan(rows, [{'recipient': SYNTHETIC_COURT_EMAIL}] * 2)

    def test_source_hashes_and_missing_hashes_never_merge_by_city_or_date(self):
        rows = self.rows(4)
        rows[2].pop('source_sha256')
        rows[3].pop('source_sha256')
        plans = source_email_group_plan(rows, [{'recipient': SYNTHETIC_COURT_EMAIL}] * 4)
        self.assertEqual([group['member_indices'] for group in plans], [[0], [1], [2], [3]])

    def test_legacy_individual_default_has_only_child_targets(self):
        prepared = prepare_intakes(self.rows(2), self.paths)
        self.assertEqual(prepared['email_grouping'], 'individual')
        self.assertEqual(prepared['email_groups'], [])
        self.assertEqual(prepared['prepared_review']['payload_paths'], [row['draft_payload'] for row in prepared['items']])

    def test_packet_remains_one_combined_pdf_target(self):
        prepared = self.prepare(self.rows(2), packet_mode=True)
        self.assertEqual(prepared['email_groups'], [])
        self.assertTrue(prepared['packet']['packet_mode'])
        self.assertEqual(prepared['prepared_review']['payload_paths'], [prepared['packet']['draft_payload']])

    def test_grouping_change_invalidates_preflight_before_writes(self):
        rows = self.rows(2)
        preflight = preflight_intakes(rows, self.paths, email_grouping='source')
        with self.assertRaisesRegex(IntakeError, 'stale'):
            require_current_preflight_review({'preflight_review': preflight['preflight_review']}, rows, self.paths,
                                            packet_mode=False, email_grouping='individual')
        self.assert_no_artifacts()

    def test_custom_per_request_body_pauses_grouping_without_rewriting(self):
        rows = self.rows(3)[1:]
        rows[0]['email_body'] = 'Fictional custom message retained verbatim.'
        result = preflight_intakes(rows, self.paths, email_grouping='source')
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('custom per-request', result['message'])
        with self.assertRaisesRegex(IntakeError, 'individual emails'):
            self.prepare(rows)
        self.assert_no_artifacts()

    def test_singleton_preserves_existing_custom_body(self):
        rows = self.rows(1)
        rows[0]['email_body'] = 'Fictional custom single request.'
        prepared = self.prepare(rows)
        self.assertEqual(prepared['email_groups'][0]['body'], rows[0]['email_body'])

    def test_each_changed_child_pdf_invalidates_group_review_and_recording(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        last_pdf = Path(group['underlying_requests'][-1]['pdf'])
        last_pdf.write_bytes(last_pdf.read_bytes() + b'\nfictional mutation')
        with self.assertRaisesRegex(IntakeError, 'attachment changed'):
            require_current_prepared_review(self.request(prepared, group), group['draft_payload'], self.paths)
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        self.assertEqual(self.record(group), 2)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))

    def test_changed_child_payload_blocks_handoff_before_any_network(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        last_payload = Path(group['child_payload_paths'][-1])
        last_payload.write_text(last_payload.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        with self.assertRaisesRegex(IntakeError, 'child draft payload changed'):
            manual_handoff_packet(self.request(prepared, group), self.paths)
        with patch('honorarios_app.services.create_gmail_draft_from_payload') as transport:
            with self.assertRaises(IntakeError):
                create_and_record_gmail_api_draft(self.request(prepared, group), self.paths)
            transport.assert_not_called()

    def test_unselected_child_target_is_not_signed_for_group_actions(self):
        prepared = self.prepare(self.rows(3)[1:])
        with self.assertRaisesRegex(IntakeError, 'does not match'):
            require_current_prepared_review(self.request(prepared, prepared['items'][0]), prepared['items'][0]['draft_payload'], self.paths)

    def test_one_group_log_records_every_childs_own_pdf_and_idempotent_upsert(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        self.assertEqual(self.record(group), 0)
        self.assertEqual(self.record(group), 0)
        log = json.loads(self.paths.draft_log.read_text(encoding='utf-8'))
        index = json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))
        self.assertEqual(len(log), 1)
        self.assertEqual(len(index), 2)
        self.assertEqual(log[0]['email_group_id'], group['group_id'])
        self.assertEqual([row['pdf'] for row in index], group['attachment_files'])
        self.assertEqual([row['pdf_sha256'] for row in index], [file_sha256(Path(path)) for path in group['attachment_files']])
        self.assertEqual([row['draft_payload'] for row in index], group['child_payload_paths'])
        self.assertEqual([row['claim_transport'] for row in index], [True, False])

    def test_retirement_without_files_preserves_and_retires_all_child_identities(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        self.assertEqual(self.record(group), 0)
        log = json.loads(self.paths.draft_log.read_text(encoding='utf-8'))[0]
        arguments = ['--case-number', log['case_number'], '--service-date', log['service_date'],
                     '--recipient', log['recipient'], '--pdf', log['pdf'], '--draft-id', log['draft_id'],
                     '--message-id', log['message_id'], '--status', 'trashed', '--log', str(self.paths.draft_log),
                     '--duplicate-index', str(self.paths.duplicate_index)]
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(record_cli(arguments), 0)
        index = json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))
        self.assertEqual([row['status'] for row in index], ['trashed', 'trashed'])
        self.assertEqual([row['pdf'] for row in index], group['attachment_files'])

    def test_malformed_group_child_fails_before_either_history_write(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        payload_path = Path(group['draft_payload'])
        payload = json.loads(payload_path.read_text(encoding='utf-8'))
        payload['underlying_requests'][-1].pop('pdf')
        payload_path.write_text(json.dumps(payload), encoding='utf-8')
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        self.assertEqual(self.record(group), 2)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))

    def test_group_active_check_checks_nonfirst_child_and_every_status(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        last = group['underlying_requests'][-1]
        self.paths.duplicate_index.write_text(json.dumps([{**last, 'status': 'sent'}]), encoding='utf-8')
        lifecycle = draft_lifecycle_for_email_group(group['underlying_requests'], self.paths)
        self.assertEqual(lifecycle['status'], 'blocked')
        self.assertEqual([row['status'] for row in lifecycle['member_checks']], ['clear', 'blocked'])
        self.assertFalse(lifecycle['replacement_allowed'])
        self.assertFalse(lifecycle['can_create_new_draft'])

    def test_child_recorded_after_preparation_blocks_group_create_before_transport(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        last = group['underlying_requests'][-1]
        self.paths.duplicate_index.write_text(json.dumps([{**last, 'status': 'sent'}]), encoding='utf-8')
        with patch('honorarios_app.services.create_gmail_draft_from_payload') as transport:
            with self.assertRaises(IntakeError):
                create_and_record_gmail_api_draft(self.request(prepared, group), self.paths)
            transport.assert_not_called()

    def test_mock_group_create_records_all_children_and_duplicate_second_create_pauses(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        result = {'draft_id': 'fictional-api-draft', 'message_id': 'fictional-api-message',
                  'thread_id': '', 'fake_mode': True, 'to': group['recipient'], 'subject': group['subject'],
                  'attachment_files': group['attachment_files'], 'gmail_api_action': 'users.drafts.create',
                  'attachment_basenames': [Path(path).name for path in group['attachment_files']],
                  'attachment_sha256': group['attachment_sha256']}
        with patch('honorarios_app.services.create_gmail_draft_from_payload', return_value=result) as transport:
            created = create_and_record_gmail_api_draft(self.request(prepared, group), self.paths)
            self.assertEqual(created['recorded_duplicate_count'], 2)
            with self.assertRaises(IntakeError):
                create_and_record_gmail_api_draft(self.request(prepared, group), self.paths)
            self.assertEqual(transport.call_count, 1)

    def test_http_preflight_prepare_and_active_check_preserve_group_contract(self):
        client = TestClient(create_app(**runtime_path_overrides(self.root)))
        rows = self.rows(3)[1:]
        preflight = client.post('/api/prepare/preflight', json={'intakes': rows, 'email_grouping': 'source'})
        self.assertEqual(preflight.status_code, 200)
        result = client.post('/api/prepare', json={'intakes': rows, 'email_grouping': 'source',
                                                  'preflight_review': preflight.json()['preflight_review']})
        self.assertEqual(result.status_code, 200, result.text)
        groups = result.json()['email_groups']
        self.assertEqual(len(groups), 1)
        lifecycle = client.post('/api/drafts/active-check', json={'underlying_requests': groups[0]['underlying_requests']})
        self.assertEqual(lifecycle.status_code, 200)
        self.assertEqual(len(lifecycle.json()['member_checks']), 2)
        malformed = client.post('/api/drafts/active-check', json={'underlying_requests': []})
        self.assertEqual(malformed.status_code, 400)

    def test_manual_record_and_handoff_recheck_newly_sent_nonfirst_child(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        last = group['underlying_requests'][-1]
        self.paths.duplicate_index.write_text(json.dumps([{**last, 'status': 'sent'}]), encoding='utf-8')
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        with self.assertRaisesRegex(IntakeError, 'already sent'):
            record_draft({**self.request(prepared, group), 'draft_id': 'fictional-late', 'message_id': 'fictional-late-message'}, self.paths)
        with self.assertRaisesRegex(IntakeError, 'sent or non-replaceable'):
            manual_handoff_packet(self.request(prepared, group), self.paths)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))

    def test_manual_record_is_idempotent_for_same_draft_and_exact_child_bindings(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        request = {**self.request(prepared, group), 'draft_id': 'fictional-once', 'message_id': 'fictional-message'}
        self.assertEqual(record_draft(request, self.paths)['recorded_duplicate_count'], 2)
        self.assertEqual(record_draft(request, self.paths)['recorded_duplicate_count'], 2)
        self.assertEqual(len(json.loads(self.paths.draft_log.read_text(encoding='utf-8'))), 1)
        self.assertEqual(len(json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))), 2)

    def test_partial_group_correction_cannot_retire_uncovered_siblings(self):
        rows = self.rows(4)[1:]
        original = self.prepare(rows)
        self.assertEqual(self.record(original['email_groups'][0]), 0)
        reason = 'Fictional grouped email correction.'
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        preflight = preflight_intakes(rows[:1], self.paths, email_grouping='source', correction_reason=reason)
        self.assertEqual(preflight['status'], 'blocked')
        self.assertIn('every request', preflight['message'])
        with self.assertRaisesRegex(IntakeError, 'every request'):
            self.prepare(rows[:1], correction_reason=reason)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))
        self.assertEqual([row['status'] for row in json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))], ['drafted'] * 3)

    def test_clear_sibling_and_replaceable_member_are_valid_group_correction(self):
        rows = self.rows(3)[1:]
        old = self.prepare(rows[:1])
        self.assertEqual(self.record(old['email_groups'][0]), 0)
        lifecycle = draft_lifecycle_for_email_group(rows, self.paths)
        self.assertEqual([check['status'] for check in lifecycle['member_checks']], ['blocked', 'clear'])
        self.assertTrue(lifecycle['replacement_allowed'])
        reason = 'Fictional add remaining source case to email.'
        preflight = preflight_intakes(rows, self.paths, email_grouping='source', correction_reason=reason)
        self.assertEqual(preflight['status'], 'ready', preflight['message'])
        corrected = self.prepare(rows, correction_reason=reason)
        target = corrected['email_groups'][0]
        request = {**self.request(corrected, target), 'draft_id': 'fictional-corrected', 'message_id': 'fictional-corrected-message',
                   'supersedes': ['fictional-group-draft'], 'correction_reason': reason}
        handoff = manual_handoff_packet(request, self.paths)
        self.assertEqual(handoff['attachment_count'], 2)
        self.assertEqual(record_draft(request, self.paths)['recorded_duplicate_count'], 2)
        log = json.loads(self.paths.draft_log.read_text(encoding='utf-8'))
        self.assertEqual([row['status'] for row in log], ['superseded', 'active'])
        index = json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))
        self.assertEqual(sum(row['status'] == 'drafted' for row in index), 2)

    def test_incomplete_supersedes_pauses_manual_group_record_before_any_write(self):
        rows = self.rows(3)[1:]
        original = self.prepare(rows)
        self.assertEqual(self.record(original['email_groups'][0]), 0)
        reason = 'Fictional complete-source correction.'
        corrected = self.prepare(rows, correction_reason=reason)
        group = corrected['email_groups'][0]
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        request = {**self.request(corrected, group), 'draft_id': 'fictional-new', 'message_id': 'fictional-new-message', 'correction_reason': reason}
        with self.assertRaisesRegex(IntakeError, 'every blocking draft ID'):
            record_draft(request, self.paths)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))

    def test_child_service_period_identity_is_preserved_without_a_period_label(self):
        rows = self.rows(3)[1:]
        for index, row in enumerate(rows):
            row.update(service_start_time=f'{9 + index:02d}:00', service_end_time=f'{10 + index:02d}:00')
            row.pop('service_period_label', None)
        prepared = self.prepare(rows)
        self.assertEqual(self.record(prepared['email_groups'][0]), 0)
        index = json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))
        self.assertEqual([row['service_start_time'] for row in index], ['09:00', '10:00'])
        self.assertEqual(len(index), 2)

    def test_travel_only_plural_email_does_not_claim_performed_interpreting(self):
        rows = self.rows(2)
        for row in rows:
            row.update(source_sha256='c' * 64, claim_interpreting=False, claim_transport=True)
            row.pop('travel_group_id', None)
        prepared = self.prepare(rows)
        group = prepared['email_groups'][0]
        self.assertEqual(group['subject'], 'Requerimentos de despesas de transporte')
        self.assertIn('despesas de transporte', group['body'])
        self.assertIn('2 requerimentos', group['body'])
        for phrase in ('honorários devidos', 'serviço prestado', 'interpretação realizada', 'IVA', 'IRS'):
            self.assertNotIn(phrase, group['body'])

    def assert_period_history_pauses(self, candidate_period, recorded_period):
        rows = self.rows(3)[1:]
        rows[-1]['service_period_label'] = candidate_period
        prepared = self.prepare(rows)
        group = prepared['email_groups'][0]
        last = group['underlying_requests'][-1]
        self.paths.duplicate_index.write_text(json.dumps([{**last, 'service_period_label': recorded_period, 'status': 'sent'}]), encoding='utf-8')
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        with self.assertRaisesRegex(IntakeError, 'already sent'):
            record_draft({**self.request(prepared, group), 'draft_id': 'fictional-period', 'message_id': 'fictional-period-message'}, self.paths)
        self.assertEqual(self.record(group), 2)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))

    def test_blank_recorded_period_blocks_group_child_with_named_period(self):
        self.assert_period_history_pauses('morning', '')

    def test_named_recorded_period_blocks_group_child_with_blank_period(self):
        self.assert_period_history_pauses('', 'morning')

    def test_prepared_individual_cannot_retire_a_later_group_and_uncovered_child(self):
        rows = self.rows(3)[1:]
        prepared = prepare_intakes(rows[:1], self.paths)
        target = prepared['items'][0]
        old = {**rows[0], 'draft_id': 'fictional-later-group', 'message_id': 'fictional-old-message',
               'status': 'active', 'underlying_requests': rows}
        self.paths.draft_log.write_text(json.dumps([old]), encoding='utf-8')
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        with self.assertRaisesRegex(IntakeError, 'every request'):
            record_draft({**self.request(prepared, target), 'draft_id': 'fictional-individual', 'message_id': 'fictional-new-message',
                          'supersedes': ['fictional-later-group'], 'correction_reason': 'Fictional attempted partial replacement.'}, self.paths)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))

    def test_same_draft_id_sent_retry_never_downgrades_group_to_active(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        self.assertEqual(self.record(group), 0)
        self.assertEqual(self.record(group, 'sent'), 0)
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        self.assertEqual(self.record(group, 'active'), 2)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))
        self.assertEqual([row['status'] for row in json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))], ['sent', 'sent'])

    def test_same_draft_id_retired_retry_cannot_resurrect_group(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        self.assertEqual(self.record(group), 0)
        self.assertEqual(self.record(group, 'superseded'), 0)
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        self.assertEqual(self.record(group), 2)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))

    def test_group_draft_payload_alias_cannot_bypass_current_prepared_review(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        before = (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes())
        with self.assertRaisesRegex(IntakeError, 'Current prepared review'):
            record_draft({'draft_payload': group['draft_payload'], 'draft_id': 'fictional-alias',
                          'message_id': 'fictional-alias-message'}, self.paths)
        self.assertEqual(before, (self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()))

    def test_existing_group_can_be_marked_sent_without_a_new_prepared_review(self):
        prepared = self.prepare(self.rows(3)[1:])
        group = prepared['email_groups'][0]
        self.assertEqual(self.record(group), 0)
        result = record_draft({'payload': group['draft_payload'], 'draft_id': 'fictional-group-draft',
                               'message_id': 'fictional-group-message', 'status': 'sent'}, self.paths)
        self.assertEqual(result['recorded_duplicate_count'], 2)
        self.assertEqual([row['status'] for row in json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))], ['sent', 'sent'])


if __name__ == '__main__':
    unittest.main()
