"""Offline user-decision protection through normal app and CLI boundaries."""
from __future__ import annotations

import copy
import json
import re
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from honorarios_app import services
from honorarios_app.gmail_attempts import load_attempts
from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.web import create_app
from scripts.generate_pdf import IntakeError, main as generate_cli
from scripts.build_email_draft import main as build_email_cli
from scripts.check_duplicate import main as check_cli
from scripts.record_gmail_draft import main as record_cli
from scripts.request_exclusions import MAX_LEDGER_BYTES, exclusion_ledger_path
import test_source_email_groups as fixtures


class RequestExclusionGuardTests(unittest.TestCase):
    setUp = fixtures.SourceEmailGroupsTests.setUp
    rows = fixtures.SourceEmailGroupsTests.rows
    prepare = fixtures.SourceEmailGroupsTests.prepare
    request = fixtures.SourceEmailGroupsTests.request
    assert_no_artifacts = fixtures.SourceEmailGroupsTests.assert_no_artifacts

    def exclude(self, row, *, done=True):
        record = {key: row[key] for key in ('case_number', 'service_date', 'service_period_label') if row.get(key)}
        record.update(reason='Fictional explicit user decision', source_filename='fictional-camera.jpg',
                      gmail_sent_evidence=False, submission_date=None)
        if done:
            record['completion_evidence'] = 'user_confirmed_done'
        value = {'schema_version': 1, 'forms': [], 'standing_exclusions': [], 'excluded_cases': [record]}
        exclusion_ledger_path(self.paths.duplicate_index).write_text(json.dumps(value), encoding='utf-8')
        return value

    def client(self):
        return TestClient(create_app(**runtime_path_overrides(self.root)), base_url='http://127.0.0.1')

    def history_bytes(self):
        return {path: path.read_bytes() for path in (self.paths.duplicate_index, self.paths.draft_log)}

    def test_review_stops_before_unrelated_questions_without_fabricating_sent(self):
        row = self.rows(1)[0]
        self.exclude(row)
        incomplete = {'case_number': row['case_number'], 'service_date': row['service_date']}
        before = self.history_bytes()
        result = services.review_intake(incomplete, self.paths)
        self.assertEqual(result['status'], 'excluded')
        self.assertEqual(result['questions'], [])
        self.assertIn('Already handled', result['message'])
        self.assertNotIn('duplicate', result)
        self.assertEqual(result['exclusion']['kind'], 'user_confirmed_done')
        self.assertTrue(result['next_safe_action']['blocked'])
        lifecycle = services.draft_lifecycle_for_intake(row, self.paths)
        self.assertEqual(lifecycle['status'], 'blocked')
        self.assertFalse(lifecycle['replacement_allowed'])
        self.assertEqual(lifecycle['duplicate_records'], [])
        self.assertEqual(self.history_bytes(), before)
        self.assert_no_artifacts()

    def test_excluded_is_not_a_completion_or_email_claim(self):
        row = self.rows(1)[0]
        self.exclude(row, done=False)
        result = services.review_intake(row, self.paths)
        self.assertEqual(result['status'], 'excluded')
        self.assertEqual(result['exclusion']['kind'], 'user_excluded')
        self.assertEqual(result['next_safe_action']['title'], 'Excluded by your saved decision')
        self.assertNotIn('Already handled', result['message'])

    def test_browser_exclusion_summary_uses_saved_identity_without_unrelated_questions(self):
        script = (Path(__file__).resolve().parents[1] / 'honorarios_app/static/app.js').read_text(encoding='utf-8')
        functions = []
        for name in ('escapeHtml', 'renderBeginnerReviewSummary'):
            match = re.search(r'function ' + name + r'\([^\n]*\) \{.*?\n\}', script, re.DOTALL)
            self.assertIsNotNone(match)
            functions.append(match.group(0))
        body = "\n".join(functions) + """
function currentWorkflowGuidance() { return {phase:'review'}; }
function sentDuplicateForReview() { return null; }
const data={status:'excluded',message:'Excluded <unsafe> source',
 next_safe_action:{title:'Already handled — confirmed by you'},
 exclusion:{case_number:'700/26.0TSTXX',service_date:'2026-06-18',service_period_label:''}};
console.log(JSON.stringify(renderBeginnerReviewSummary(data)));
"""
        result = subprocess.run(['node', '--input-type=module', '-'], input=body, text=True, encoding='utf-8',
                                capture_output=True, check=True)
        summary = json.loads(result.stdout)
        self.assertIn('Already handled', summary)
        self.assertIn('700/26.0TSTXX', summary)
        self.assertIn('No further answers are needed', summary)
        self.assertIn('&lt;unsafe&gt;', summary)
        for irrelevant in ('Payment entity', 'Recipient email', 'Service place', 'sent-history', 'paper submission'):
            self.assertNotIn(irrelevant, summary)

    def test_identity_must_be_resolved_before_exclusion_lookup(self):
        row = self.rows(1)[0]
        self.exclude(row)
        for changes in ({'service_date': ''}, {'service_date': '2026-02-30'},
                        {'case_number': row['case_number'] + ' or 799/26.0TSTXX'}):
            with self.subTest(changes=changes):
                result = services.review_intake({**row, **changes}, self.paths)
                self.assertIn(result['status'], ('needs_info', 'error'))
                self.assertNotIn('exclusion', result)

    def test_missing_ledger_and_distinct_case_date_or_period_remain_usable(self):
        row = self.rows(1)[0]
        self.assertEqual(services.review_intake(row, self.paths)['status'], 'ready')
        self.exclude({**row, 'service_period_label': 'morning'})
        for changes in ({'case_number': '799/26.0TSTXX'}, {'service_date': '2026-06-30'},
                        {'service_period_label': 'afternoon'}):
            with self.subTest(changes=changes):
                self.assertEqual(services.review_intake({**row, **changes}, self.paths)['status'], 'ready')

    def test_malformed_present_ledger_blocks_visibly(self):
        row = self.rows(1)[0]
        exclusion_ledger_path(self.paths.duplicate_index).write_text('{broken', encoding='utf-8')
        result = services.review_intake(row, self.paths)
        self.assertEqual(result['status'], 'error')
        self.assertTrue(result['next_safe_action']['blocked'])
        with self.assertRaises(IntakeError):
            services.prepare_intakes([row], self.paths, allow_duplicate=True)
        self.assert_no_artifacts()

    def test_group_exclusion_blocks_all_before_prepare_even_with_correction_flags(self):
        rows = self.rows(3)[1:]
        self.exclude(rows[1])
        for mode in ('source', 'individual'):
            with self.subTest(mode=mode):
                result = services.preflight_intakes(rows, self.paths, email_grouping=mode)
                self.assertEqual(result['status'], 'blocked')
                self.assertIn('Already handled', result['message'])
                with self.assertRaisesRegex(IntakeError, 'Already handled'):
                    services.prepare_intakes(rows, self.paths, email_grouping=mode, allow_duplicate=True,
                                            allow_existing_draft=True, correction_reason='Fictional correction')
        lifecycle = services.draft_lifecycle_for_email_group(rows, self.paths)
        self.assertFalse(lifecycle['replacement_allowed'])
        self.assertEqual(len(lifecycle['exclusions']), 1)
        self.assert_no_artifacts()

    def test_late_exclusion_rechecks_signed_preflight_before_any_artifact(self):
        rows = self.rows(1)
        with self.client() as client:
            result = client.post('/api/prepare/preflight', json={'intakes': rows}).json()
            self.assertEqual(result['status'], 'ready')
            self.exclude(rows[0])
            response = client.post('/api/prepare', json={'intakes': rows, 'preflight_review': result['preflight_review']})
            self.assertGreaterEqual(response.status_code, 400)
            self.assertIn('Already handled', response.text)
        self.assert_no_artifacts()

    def test_late_group_child_exclusion_blocks_handoff_create_record_and_cli_record(self):
        rows = self.rows(3)[1:]
        prepared = self.prepare(rows)
        target = prepared['email_groups'][0]
        request = self.request(prepared, target)
        self.exclude(rows[1])
        before = self.history_bytes()
        recorded = {**request, 'draft_id': 'fictional-excluded-draft', 'message_id': 'fictional-excluded-message'}
        with patch('honorarios_app.services.create_gmail_draft_from_payload') as provider:
            for action, payload in ((services.manual_handoff_packet, request),
                                    (services.create_and_record_gmail_api_draft, request),
                                    (services.record_draft, recorded)):
                with self.subTest(action=action.__name__), self.assertRaisesRegex(IntakeError, 'Already handled'):
                    action(payload, self.paths)
            provider.assert_not_called()
        self.assertEqual(load_attempts(self.paths.draft_log), [])
        args = ['--payload', target['draft_payload'], '--draft-id', 'fictional-excluded-draft',
                '--message-id', 'fictional-excluded-message', '--log', str(self.paths.draft_log),
                '--duplicate-index', str(self.paths.duplicate_index)]
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as errors:
            self.assertEqual(record_cli(args), 2)
        self.assertIn('Already handled', errors.getvalue())
        self.assertEqual(self.history_bytes(), before)

    def test_packet_second_child_is_rechecked_at_handoff(self):
        rows = self.rows(2)
        prepared = services.prepare_intakes(rows, self.paths, packet_mode=True)
        self.exclude(rows[1])
        request = self.request(prepared, prepared['packet'])
        with self.assertRaisesRegex(IntakeError, 'Already handled'):
            services.manual_handoff_packet(request, self.paths)

    def test_direct_pdf_and_email_cli_cannot_bypass_exclusion(self):
        row = self.rows(1)[0]
        self.exclude(row)
        source = self.root / 'fictional-intake.json'
        source.write_text(json.dumps(row), encoding='utf-8')
        output = self.root / 'blocked.pdf'
        args = [str(source), '--profile', str(self.paths.profile), '--duplicate-index', str(self.paths.duplicate_index),
                '--output', str(output), '--html-preview', str(self.root / 'blocked.html'), '--allow-duplicate']
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as errors:
            self.assertEqual(generate_cli(args), 2)
        self.assertIn('Already handled', errors.getvalue())
        self.assertFalse(output.exists())
        payload = self.root / 'blocked-draft.json'
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as errors:
            self.assertEqual(build_email_cli([str(source), '--pdf', str(output), '--output', str(payload),
                                             '--duplicate-index', str(self.paths.duplicate_index)]), 2)
        self.assertIn('Already handled', errors.getvalue())
        self.assertFalse(payload.exists())

    def test_duplicate_check_cli_reports_exclusion_without_a_false_clear_message(self):
        row = self.rows(1)[0]
        self.exclude(row)
        before = self.history_bytes()
        with redirect_stdout(StringIO()) as output:
            result = check_cli(['--case-number', row['case_number'], '--service-date', row['service_date'],
                                '--duplicate-index', str(self.paths.duplicate_index)])
        self.assertEqual(result, 4)
        self.assertIn('Already handled', output.getvalue())
        self.assertNotIn('No duplicate', output.getvalue())
        self.assertEqual(self.history_bytes(), before)

    def test_existing_sent_transition_preserves_real_history_after_late_exclusion(self):
        rows = self.rows(1)
        prepared = self.prepare(rows)
        target = prepared['email_groups'][0]
        request = {**self.request(prepared, target), 'draft_id': 'fictional-existing-draft',
                   'message_id': 'fictional-existing-message'}
        services.record_draft(request, self.paths)
        self.exclude(rows[0])
        services.record_draft({**request, 'status': 'sent', 'sent_date': '2026-06-30'}, self.paths)
        self.assertEqual(json.loads(self.paths.draft_log.read_text())[0]['status'], 'sent')
        self.assertEqual(services.review_intake(rows[0], self.paths)['status'], 'excluded')

    def test_backup_round_trip_preserves_decisions_and_old_backup_cannot_erase_new_ones(self):
        rows = self.rows(2)
        self.exclude(rows[0])
        snapshot = services.backup_payload(self.paths)
        self.assertIn('request_exclusions', snapshot['datasets'])
        destination = self.root / 'moved'
        create_synthetic_runtime(destination)
        moved = services.AppPaths(**runtime_path_overrides(destination))
        payload = {'backup': snapshot, 'confirm_restore': True,
                   'confirmation_phrase': services.LOCAL_BACKUP_RESTORE_PHRASE, 'restore_reason': 'Fictional restore'}
        services.restore_local_backup(payload, moved)
        self.assertEqual(services.review_intake(rows[0], moved)['status'], 'excluded')
        self.exclude(rows[1])
        services.restore_local_backup(payload, self.paths)
        for row in rows:
            self.assertEqual(services.review_intake(row, self.paths)['status'], 'excluded')
        before = exclusion_ledger_path(self.paths.duplicate_index).read_bytes()
        services.restore_local_backup(payload, self.paths)
        self.assertEqual(exclusion_ledger_path(self.paths.duplicate_index).read_bytes(), before)
        malformed = copy.deepcopy(snapshot)
        malformed['datasets']['request_exclusions']['excluded_cases'] = 'invalid'
        with self.assertRaises(IntakeError):
            services.preview_local_backup_import({'backup': malformed}, self.paths)

    def test_oversized_exclusion_backup_is_rejected_before_any_restore_write(self):
        self.exclude(self.rows(1)[0])
        snapshot = services.backup_payload(self.paths)
        snapshot['datasets']['request_exclusions']['forms'] = [{'original_evidence': 'x' * MAX_LEDGER_BYTES}]
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with self.assertRaises(IntakeError):
            services.preview_local_backup_import({'backup': snapshot}, self.paths)
        with self.assertRaises(IntakeError):
            services.restore_local_backup({'backup': snapshot, 'confirm_restore': True,
                'confirmation_phrase': services.LOCAL_BACKUP_RESTORE_PHRASE,
                'restore_reason': 'Fictional oversized ledger'}, self.paths)
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}, before)


if __name__ == '__main__':
    unittest.main()
