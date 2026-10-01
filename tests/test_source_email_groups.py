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

    def test_repreparing_same_cases_preserves_all_previous_reviewed_artifacts(self):
        rows = self.rows(2)
        with patch('honorarios_app.services.timestamp_slug', return_value='20261001T120000Z'):
            original = self.prepare(rows)
            preserved = {Path(original['manifest'])}
            for item in original['items']:
                preserved.update(Path(item[key]) for key in ('pdf', 'html_preview', 'draft_payload', 'intake'))
            preserved.update(Path(group['draft_payload']) for group in original['email_groups'])
            before = {path: path.read_bytes() for path in preserved}
            changed = copy.deepcopy(rows)
            changed[0]['transport']['km_one_way'] = 99
            revised = self.prepare(changed)
        self.assertNotEqual(original['manifest'], revised['manifest'])
        self.assertEqual({path: path.read_bytes() for path in preserved}, before)
        for old, new in zip(original['items'], revised['items']):
            self.assertNotEqual(old['pdf'], new['pdf'])
            self.assertNotEqual(old['draft_payload'], new['draft_payload'])
        for group in original['email_groups']:
            require_current_prepared_review(self.request(original, group), group['draft_payload'], self.paths)
        for group in revised['email_groups']:
            require_current_prepared_review(self.request(revised, group), group['draft_payload'], self.paths)

    def test_correction_preserves_recorded_attachment_and_payload_bytes(self):
        rows = self.rows(1)
        original = self.prepare(rows)
        target = original['email_groups'][0]
        self.assertEqual(self.record(target), 0)
        preserved = {Path(original['manifest']), self.paths.draft_log, self.paths.duplicate_index,
                     Path(target['draft_payload']), Path(target['pdf'])}
        for item in original['items']:
            preserved.update(Path(item[key]) for key in ('pdf', 'html_preview', 'draft_payload', 'intake'))
        before = {path: path.read_bytes() for path in preserved}
        changed = copy.deepcopy(rows)
        changed[0]['transport']['km_one_way'] = 99
        revised = self.prepare(changed, correction_reason='Correcting the fictional recorded distance.')
        self.assertEqual({path: path.read_bytes() for path in preserved}, before)
        self.assertNotEqual(revised['items'][0]['pdf'], original['items'][0]['pdf'])
        original_payload = json.loads(Path(target['draft_payload']).read_text(encoding='utf-8'))
        self.assertEqual(validate_draft_payload(original_payload), [])
        require_current_prepared_review(self.request(original, target), target['draft_payload'], self.paths)

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
        client = TestClient(create_app(**runtime_path_overrides(self.root)), base_url='http://127.0.0.1')
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


class GmailAttemptRecoveryTests(unittest.TestCase):
    """Offline transport faults exercise real create/recovery endpoints."""
    setUp = SourceEmailGroupsTests.setUp
    rows = SourceEmailGroupsTests.rows
    prepare = SourceEmailGroupsTests.prepare
    request = SourceEmailGroupsTests.request

    def client(self):
        return TestClient(create_app(**runtime_path_overrides(self.root)), base_url='http://127.0.0.1')

    def prepared_request(self):
        prepared = self.prepare(self.rows(1))
        return self.request(prepared, prepared['email_groups'][0])

    def fake_transport(self, *, timeout_first=False, http_status=200):
        import httpx
        from contextlib import ExitStack
        self.remote = []
        original_client = httpx.Client
        def handler(request):
            self.assertEqual(request.method, 'POST')
            self.assertEqual(request.url.path, '/gmail/v1/users/me/drafts')
            if http_status != 200:
                return httpx.Response(http_status, json={'error': {'message': 'Fictional provider rejection'}})
            number = len(self.remote) + 1
            result = {'id': f'fictional-created-{number}', 'message': {'id': f'fictional-message-{number}', 'threadId': f'fictional-thread-{number}'}}
            self.remote.append(result)
            if timeout_first and number == 1:
                raise httpx.ReadTimeout('Lost response after committing the fictional draft', request=request)
            return httpx.Response(200, json=result)
        def client_factory(*args, **kwargs):
            kwargs['transport'] = httpx.MockTransport(handler)
            return original_client(*args, **kwargs)
        stack = ExitStack()
        stack.enter_context(patch('honorarios_app.gmail_draft_api.gmail_access_token', return_value=('fictional-token', {})))
        stack.enter_context(patch('honorarios_app.gmail_draft_api.fake_gmail_draft_api_enabled', return_value=False))
        stack.enter_context(patch('honorarios_app.gmail_draft_api.httpx.Client', side_effect=client_factory))
        return stack

    def test_lost_response_blocks_retry_reprepare_and_restarted_signer(self):
        request = self.prepared_request()
        with self.fake_transport(timeout_first=True):
            first = self.client().post('/api/gmail/drafts/create', json=request).json()
            self.assertEqual(first['status'], 'creation_uncertain')
            with patch('honorarios_app.services._PREPARED_REVIEW_SECRET', b'fictional-new-process-signing-key'):
                fresh = self.prepared_request()
                second = self.client().post('/api/gmail/drafts/create', json=fresh).json()
            self.assertEqual(second['attempt_id'], first['attempt_id'])
            self.assertEqual(second['status'], 'creation_uncertain')
            self.assertEqual(len(self.remote), 1)
        self.assertEqual(json.loads(self.paths.draft_log.read_text()), [])

    def test_process_interruption_keeps_durable_started_reservation(self):
        request = self.prepared_request()
        with patch('honorarios_app.services.create_gmail_draft_from_payload', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                create_and_record_gmail_api_draft(request, self.paths)
        with patch('honorarios_app.services.create_gmail_draft_from_payload') as transport:
            result = create_and_record_gmail_api_draft(self.prepared_request(), self.paths)
        transport.assert_not_called()
        self.assertEqual(result['status'], 'creation_uncertain')

    def test_pending_attempt_also_blocks_another_manual_handoff(self):
        request = self.prepared_request()
        with self.fake_transport(timeout_first=True):
            self.client().post('/api/gmail/drafts/create', json=request)
        with self.assertRaisesRegex(IntakeError, 'pending Gmail attempt'):
            manual_handoff_packet(request, self.paths)

    def test_confirmed_remote_ids_survive_log_failure_and_recover_without_new_create(self):
        from honorarios_app.gmail_attempts import load_attempts
        request = self.prepared_request()
        with self.fake_transport():
            with patch('scripts.record_gmail_draft.write_log', side_effect=PermissionError('Fictional locked log')):
                first = self.client().post('/api/gmail/drafts/create', json=request).json()
            self.assertEqual(first['status'], 'created_unrecorded')
            self.assertEqual(first['draft_id'], self.remote[0]['id'])
            with patch('honorarios_app.services._PREPARED_REVIEW_SECRET', b'fictional-new-process-signing-key'):
                recovered = self.client().post('/api/gmail/drafts/create', json={'recover_attempt_id': first['attempt_id'], 'gmail_handoff_reviewed': True}).json()
            self.assertTrue(recovered['recovered_existing_draft'])
            self.assertEqual(recovered['draft_id'], first['draft_id'])
            self.assertEqual(recovered['gmail_api_action'], 'local_record_recovery')
            self.assertEqual(recovered['confirmation']['gmail_api_action'], 'local_record_recovery')
            self.assertEqual(load_attempts(self.paths.draft_log)[0]['gmail_result']['gmail_api_action'], 'users.drafts.create')
            self.assertEqual(len(self.remote), 1)
        self.assertEqual(len(json.loads(self.paths.draft_log.read_text())), 1)
        self.assertEqual(len(json.loads(self.paths.duplicate_index.read_text())), 1)

    def test_partial_history_write_recovers_both_files_without_second_draft(self):
        request = self.prepared_request()
        with self.fake_transport():
            with patch('scripts.record_gmail_draft.write_duplicate_index', side_effect=PermissionError('Fictional locked index')):
                first = self.client().post('/api/gmail/drafts/create', json=request).json()
            self.assertEqual(len(json.loads(self.paths.draft_log.read_text())), 1)
            self.assertEqual(json.loads(self.paths.duplicate_index.read_text()), [])
            reference = self.client().get('/api/reference').json()
            self.assertEqual(reference['pending_gmail_attempts'][0]['attempt_id'], first['attempt_id'])
            self.assertEqual(reference['pending_gmail_attempts'][0]['status'], 'created_unrecorded')
            result = self.client().post('/api/gmail/drafts/create', json={'recover_attempt_id': first['attempt_id'], 'gmail_handoff_reviewed': True}).json()
            self.assertEqual(result['status'], 'created')
            self.assertEqual(len(self.remote), 1)
        self.assertEqual(len(json.loads(self.paths.draft_log.read_text())), 1)
        self.assertEqual(len(json.loads(self.paths.duplicate_index.read_text())), 1)
        self.assertEqual(self.client().get('/api/reference').json()['pending_gmail_attempts'], [])

    def test_uncertain_correction_can_resolve_absent_without_changing_old_draft(self):
        request = self.prepared_request()
        with self.fake_transport():
            original = self.client().post('/api/gmail/drafts/create', json=request).json()
        prepared = self.prepare(self.rows(1), correction_reason='Fictional approved correction')
        correction = self.request(prepared, prepared['email_groups'][0])
        correction.update(supersedes=[original['draft_id']], correction_reason='Fictional approved correction')
        before = self.paths.draft_log.read_bytes()
        with self.fake_transport(timeout_first=True):
            pending = self.client().post('/api/gmail/drafts/create', json=correction).json()
            self.assertEqual(pending['status'], 'creation_uncertain')
            resolved = self.client().post('/api/gmail/drafts/create', json={
                'resolve_attempt_id': pending['attempt_id'], 'gmail_handoff_reviewed': True,
                'confirmation_phrase': 'I CHECKED GMAIL: NO DRAFT', 'resolution_reason': 'Fictional user found only the old draft'}).json()
        self.assertEqual(resolved['status'], 'not_created')
        self.assertEqual(before, self.paths.draft_log.read_bytes())

    def test_recovery_rejects_changed_original_attachment(self):
        request = self.prepared_request()
        with self.fake_transport():
            with patch('scripts.record_gmail_draft.write_log', side_effect=PermissionError('Fictional locked log')):
                first = self.client().post('/api/gmail/drafts/create', json=request).json()
            pdf = Path(first['attachment_files'][0])
            pdf.write_bytes(pdf.read_bytes() + b'fictional changed attachment')
            recovered = self.client().post('/api/gmail/drafts/create', json={'recover_attempt_id': first['attempt_id'], 'gmail_handoff_reviewed': True})
            self.assertEqual(recovered.status_code, 400)
            self.assertIn('original', recovered.json()['message'])
            self.assertEqual(len(self.remote), 1)

    def test_explicit_absent_resolution_is_required_before_new_create(self):
        request = self.prepared_request()
        with self.fake_transport(timeout_first=True):
            first = self.client().post('/api/gmail/drafts/create', json=request).json()
            args = {'resolve_attempt_id': first['attempt_id'], 'gmail_handoff_reviewed': True}
            self.assertEqual(self.client().post('/api/gmail/drafts/create', json=args).status_code, 400)
            args.update(confirmation_phrase='I CHECKED GMAIL: NO DRAFT', resolution_reason='Fictional user checked the mailbox')
            resolved = self.client().post('/api/gmail/drafts/create', json=args).json()
            self.assertTrue(resolved['create_retry_allowed'])
            self.assertEqual(resolved['gmail_api_action'], 'local_attempt_resolution')
            result = self.client().post('/api/gmail/drafts/create', json=request).json()
            self.assertEqual(result['status'], 'created')
            self.assertEqual(len(self.remote), 2)

    def test_uncertain_result_can_record_confirmed_existing_ids_without_another_post(self):
        request = self.prepared_request()
        with self.fake_transport(timeout_first=True):
            first = self.client().post('/api/gmail/drafts/create', json=request).json()
            args = {'recover_attempt_id': first['attempt_id'], 'gmail_handoff_reviewed': True,
                    'draft_id': self.remote[0]['id'], 'message_id': self.remote[0]['message']['id']}
            self.assertEqual(self.client().post('/api/gmail/drafts/create', json=args).status_code, 400)
            args['confirmation_phrase'] = 'I CHECKED THE EXISTING GMAIL DRAFT'
            result = self.client().post('/api/gmail/drafts/create', json=args).json()
            self.assertEqual(result['status'], 'created')
            self.assertEqual(len(self.remote), 1)

    def test_provider_rejection_does_not_leave_uncertain_reservation(self):
        from honorarios_app.gmail_attempts import load_attempts
        request = self.prepared_request()
        with self.fake_transport(http_status=401):
            response = self.client().post('/api/gmail/drafts/create', json=request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(load_attempts(self.paths.draft_log)[-1]['state'], 'not_created')
        with self.fake_transport():
            self.assertEqual(self.client().post('/api/gmail/drafts/create', json=request).json()['status'], 'created')

    def test_concurrent_same_request_creates_only_one_remote_draft(self):
        from concurrent.futures import ThreadPoolExecutor
        request = self.prepared_request()
        def run():
            try:
                return create_and_record_gmail_api_draft(request, self.paths)['status']
            except IntakeError:
                return 'blocked'
        with self.fake_transport(), ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: run(), range(2)))
            self.assertEqual(sorted(results), ['blocked', 'created'])
            self.assertEqual(len(self.remote), 1)

    def test_recorded_attempt_cannot_reactivate_sent_history(self):
        from honorarios_app.gmail_attempts import load_attempts
        request = self.prepared_request()
        with self.fake_transport():
            result = self.client().post('/api/gmail/drafts/create', json=request).json()
        record_draft({'payload': request['payload'], 'draft_id': result['draft_id'], 'message_id': result['message_id'], 'status': 'sent'}, self.paths)
        attempt_id = load_attempts(self.paths.draft_log)[0]['attempt_id']
        recovered = self.client().post('/api/gmail/drafts/create', json={'recover_attempt_id': attempt_id, 'gmail_handoff_reviewed': True})
        self.assertEqual(recovered.status_code, 400)
        self.assertEqual(json.loads(self.paths.draft_log.read_text())[0]['status'], 'sent')

    def test_atomic_write_failure_keeps_previous_complete_history(self):
        from scripts.state_store import atomic_write_json
        original = self.paths.draft_log.read_bytes()
        with patch('scripts.state_store.os.replace', side_effect=PermissionError('Fictional locked target')):
            with self.assertRaises(PermissionError):
                atomic_write_json(self.paths.draft_log, [{'fictional': 'new value'}])
        self.assertEqual(self.paths.draft_log.read_bytes(), original)

    def test_attempt_lock_excludes_another_local_app_process(self):
        import subprocess
        import sys
        from scripts.state_store import state_file_lock
        lock_path = self.root / 'fictional-cross-process.lock'
        script = "from pathlib import Path\nimport sys\nfrom scripts.state_store import state_file_lock\nwith state_file_lock(Path(sys.argv[1])):\n print('locked', flush=True)\n sys.stdin.read(1)\n"
        child = subprocess.Popen([sys.executable, '-u', '-c', script, str(lock_path)], cwd=ROOT,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'locked')
            with self.assertRaises(TimeoutError):
                with state_file_lock(lock_path, timeout=0.1):
                    self.fail('A second process acquired the held attempt lock')
        finally:
            _stdout, stderr = child.communicate('\n', timeout=5)
        self.assertEqual(child.returncode, 0, stderr)

    def test_profile_tax_selection_reaches_review_and_pdf(self):
        from honorarios_app.services import load_personal_profiles
        from pypdf import PdfReader
        profile = dict(load_personal_profiles(self.paths)['profiles'][0])
        profile.update(iva_text='13%', irs_text='Retenção de 25%')
        response = self.client().post('/api/profiles/save', json={'profile': profile, 'make_main': True})
        self.assertEqual(response.status_code, 200)
        review = self.client().post('/api/review', json={'intake': self.intake}).json()
        self.assertIn('IVA de 13%', review['draft_text'])
        self.assertIn('Retenção de 25%', review['draft_text'])
        prepared = self.prepare(self.rows(1))
        text = '\n'.join(page.extract_text() for page in PdfReader(prepared['items'][0]['pdf']).pages)
        self.assertIn('IVA de 13%', text)
        self.assertIn('Retenção de 25%', text)
        self.assertNotIn('não está sujeito a retenção', text)

    def test_ai_only_recipient_is_not_promoted_and_existing_manual_choice_is_preserved(self):
        from honorarios_app.services import merge_ai_recovery_into_intake
        unseen = SYNTHETIC_COURT_EMAIL.replace('court@', 'fictional-unseen@')
        recovery = {'status': 'ok', 'fields': {'court_email': unseen}, 'raw_visible_text': 'Fictional court document without a printed email.', 'warnings': []}
        row = copy.deepcopy(self.intake)
        row.pop('recipient_email', None)
        merged = merge_ai_recovery_into_intake(row, recovery)
        self.assertFalse(merged.get('recipient_email'))
        self.assertTrue(merged['ai_recovery']['warnings'])
        recovery['raw_visible_text'] = unseen
        merged = merge_ai_recovery_into_intake(copy.deepcopy(self.intake), recovery)
        self.assertEqual(merged['recipient_email'], SYNTHETIC_COURT_EMAIL)


if __name__ == '__main__':
    unittest.main()
