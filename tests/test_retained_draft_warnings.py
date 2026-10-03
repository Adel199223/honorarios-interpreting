"""Removal is separate from identity protection; all fixtures are offline."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from honorarios_app import services, backup
from honorarios_app.runtime import runtime_path_overrides, create_synthetic_runtime
from honorarios_app.web import create_app
from scripts.generate_pdf import IntakeError
import test_source_email_groups as fixtures


class RetainedDraftWarningsTests(unittest.TestCase):
    setUp = fixtures.SourceEmailGroupsTests.setUp
    rows = fixtures.SourceEmailGroupsTests.rows
    prepare = fixtures.SourceEmailGroupsTests.prepare
    record = fixtures.SourceEmailGroupsTests.record
    record_args = fixtures.SourceEmailGroupsTests.record_args
    request = fixtures.SourceEmailGroupsTests.request

    def seed(self, count=1):
        rows = self.rows(count + 1)[1:] if count > 1 else self.rows(1)
        prepared = self.prepare(rows)
        self.assertEqual(self.record(prepared['email_groups'][0]), 0)
        return rows, prepared

    def archive_request(self):
        return {'workspace_id': services.workspace_runtime_id(self.paths),
                'draft_id': 'fictional-group-draft', 'message_id': 'fictional-group-message',
                'confirm_archive': True}

    def client(self):
        return TestClient(create_app(**runtime_path_overrides(self.root)), base_url='http://127.0.0.1')

    def test_archive_all_children_then_review_prepare_and_stale_create_stay_blocked(self):
        rows, prepared = self.seed(3)
        with patch('honorarios_app.services.create_gmail_draft_from_payload') as provider:
            response = self.client().post('/api/drafts/archive', json=self.archive_request())
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['duplicate_protection_retained'])
            self.assertFalse(response.json()['gmail_contacted'])
            for row in rows:
                review = services.review_intake(row, self.paths)
                self.assertEqual(review['status'], 'duplicate')
                self.assertEqual(review['duplicate']['draft_lifecycle_status'], 'archived')
                self.assertIn('warning retained', review['next_safe_action']['title'])
                self.assertTrue(review['next_safe_action']['blocked'])
            with self.assertRaises(IntakeError):
                services.prepare_intakes(rows, self.paths)
            stale = self.request(prepared, prepared['email_groups'][0])
            with self.assertRaises(IntakeError):
                services.create_and_record_gmail_api_draft(stale, self.paths)
            provider.assert_not_called()
        log = json.loads(self.paths.draft_log.read_text(encoding='utf-8'))
        index = json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))
        self.assertEqual(log[0]['status'], 'archived')
        self.assertEqual(len(index), 3)
        self.assertTrue(all(row['status'] == 'drafted' for row in index))
        self.assertFalse(any(row.get('sent_date') for row in index))
        self.assertEqual(services.draft_lifecycle_for_intake(rows[0], self.paths)['active_gmail_drafts'], [])
        changed = {**rows[0], 'service_date': '2026-04-29'}
        self.assertNotEqual(services.review_intake(changed, self.paths)['status'], 'duplicate')

    def test_archive_rejects_stale_workspace_ids_and_missing_confirmation_without_writes(self):
        self.seed()
        before = [p.read_bytes() for p in (self.paths.draft_log, self.paths.duplicate_index)]
        for changes in ({'workspace_id': 'wrong'}, {'draft_id': 'unknown'}, {'message_id': 'wrong'},
                        {'confirm_archive': False}, {'confirm_archive': 'true'}):
            response = self.client().post('/api/drafts/archive', json={**self.archive_request(), **changes})
            self.assertEqual(response.status_code, 400)
            self.assertEqual([p.read_bytes() for p in (self.paths.draft_log, self.paths.duplicate_index)], before)

    def test_archive_does_not_trust_client_membership_and_repeated_archive_is_safe(self):
        rows, _ = self.seed(2)
        payload = {**self.archive_request(), 'case_number': '999/26.0TSTXX', 'underlying_requests': [rows[0]]}
        for _ in range(2):
            result = services.archive_draft(payload, self.paths)
            self.assertTrue(result['duplicate_protection_retained'])
        index = json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))
        self.assertEqual({r['case_number'] for r in index}, {r['case_number'] for r in rows})

    def test_backup_round_trip_retains_removed_child_warnings_and_rejects_missing_coverage(self):
        rows, _ = self.seed(2)
        services.archive_draft(self.archive_request(), self.paths)
        exported = services.export_local_backup(self.paths)['backup']
        target = self.root / 'restored'
        create_synthetic_runtime(target)
        paths = services.AppPaths(**runtime_path_overrides(target))
        services.restore_local_backup({'backup': exported, 'confirm_restore': True,
            'confirmation_phrase': services.LOCAL_BACKUP_RESTORE_PHRASE,
            'restore_reason': 'Fictional archived draft round trip'}, paths)
        for row in rows:
            self.assertEqual(services.review_intake(row, paths)['status'], 'duplicate')
        datasets = {'gmail_draft_log': json.loads(paths.draft_log.read_text(encoding='utf-8')),
                    'duplicate_index': json.loads(paths.duplicate_index.read_text(encoding='utf-8')),
                    'gmail_attempts': []}
        backup.validate_history_coverage(datasets)
        datasets['duplicate_index'].pop()
        with self.assertRaisesRegex(IntakeError, 'missing matching duplicate protection'):
            backup.validate_history_coverage(datasets)

    def test_known_missing_draft_reconciliation_retains_warning(self):
        rows, _ = self.seed()
        record = json.loads(self.paths.draft_log.read_text(encoding='utf-8'))[0]
        payload = services._payload_from_existing_draft(record, status='not_found')
        payload.update(confirm_not_found=True, reconciliation_reason='Fictional deleted draft')
        with patch('honorarios_app.services.gmail_api_draft_verify', return_value={'status': 'not_found'}):
            result = services.reconcile_gmail_draft_not_found(payload, self.paths)
        self.assertEqual(result['lifecycle_status'], 'not_found')
        self.assertEqual(services.review_intake(rows[0], self.paths)['status'], 'duplicate')

    def test_archived_backup_index_failure_does_not_install_an_unprotected_lifecycle(self):
        rows, _ = self.seed(2)
        services.archive_draft(self.archive_request(), self.paths)
        exported = services.export_local_backup(self.paths)['backup']
        target = self.root / 'index-failure-restored'
        create_synthetic_runtime(target)
        paths = services.AppPaths(**runtime_path_overrides(target))
        original = services.atomic_write_json
        before = {path: path.read_bytes() for path in (paths.draft_log, paths.duplicate_index)}

        def fail_index(path, value):
            if path == paths.duplicate_index:
                raise OSError('Fictional restore index interruption')
            return original(path, value)

        request = {'backup': exported, 'confirm_restore': True,
            'confirmation_phrase': services.LOCAL_BACKUP_RESTORE_PHRASE,
            'restore_reason': 'Fictional archived restore interruption'}
        with patch('honorarios_app.services.atomic_write_json', side_effect=fail_index):
            with self.assertRaisesRegex(OSError, 'index interruption'):
                services.restore_local_backup(request, paths)
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        services.restore_local_backup(request, paths)
        self.assertTrue(all(services.review_intake(row, paths)['status'] == 'duplicate' for row in rows))

    def test_archived_backup_log_failure_keeps_every_warning_and_retry_completes(self):
        rows, _ = self.seed(2)
        services.archive_draft(self.archive_request(), self.paths)
        exported = services.export_local_backup(self.paths)['backup']
        # These manual records have no provider-attempt reservation to provide
        # fallback protection during an interrupted history restore.
        self.assertEqual(exported['datasets']['gmail_attempts'], [])
        target = self.root / 'log-failure-restored'
        create_synthetic_runtime(target)
        paths = services.AppPaths(**runtime_path_overrides(target))
        original = services.atomic_write_json

        def fail_log(path, value):
            if path == paths.draft_log:
                raise OSError('Fictional restore log interruption')
            return original(path, value)

        request = {'backup': exported, 'confirm_restore': True,
            'confirmation_phrase': services.LOCAL_BACKUP_RESTORE_PHRASE,
            'restore_reason': 'Fictional archived restore interruption'}
        with patch('honorarios_app.services.atomic_write_json', side_effect=fail_log):
            with self.assertRaisesRegex(OSError, 'log interruption'):
                services.restore_local_backup(request, paths)
        self.assertEqual(json.loads(paths.draft_log.read_text(encoding='utf-8')), [])
        index = json.loads(paths.duplicate_index.read_text(encoding='utf-8'))
        self.assertEqual(len(index), 2)
        self.assertTrue(all(row['status'] == 'drafted' and row['duplicate_warning_retained'] for row in index))
        self.assertTrue(all(services.review_intake(row, paths)['status'] == 'duplicate' for row in rows))
        with self.assertRaises(IntakeError):
            services.prepare_intakes(rows, paths)
        services.restore_local_backup(request, paths)
        log = json.loads(paths.draft_log.read_text(encoding='utf-8'))
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]['status'], 'archived')
        self.assertTrue(log[0]['duplicate_warning_retained'])
        self.assertTrue(all(services.review_intake(row, paths)['status'] == 'duplicate' for row in rows))
