"""Public regressions using fictional cases and temporary duplicate records."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.check_duplicate import main as check_duplicate
from scripts.generate_pdf import IntakeError, find_duplicate_record, get_service_date_value


class IntakeRulesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-intake-rules-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.index = self.root / 'duplicate-index.json'
        self.index.write_text('[]', encoding='utf-8')
        self.intake = {'case_number': '0100/26.0TSTXX', 'service_date': '2026-01-15'}

    def record(self, **fields):
        record = {'case_number': '100/26.0tstxx', 'service_date': '2026-01-15', **fields}
        self.index.write_text(json.dumps([record]), encoding='utf-8')
        return record

    def test_unconfirmed_metadata_conflict_blocks_instead_of_claiming_no_duplicate(self):
        intake = {**self.intake, 'photo_metadata_date': '2026-01-16', 'service_date_source': 'document_text'}
        source = self.root / 'intake.json'
        source.write_text(json.dumps(intake), encoding='utf-8')
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = check_duplicate([str(source), '--duplicate-index', str(self.index)])
        self.assertEqual(code, 2)
        self.assertNotIn('No duplicate found', stdout.getvalue())
        self.assertIn('Conflicting service dates', stderr.getvalue())
        self.assertEqual(self.index.read_text(encoding='utf-8'), '[]')

    def test_explicit_date_exception_checks_the_chosen_service_date(self):
        record = self.record(status='drafted')
        intake = {**self.intake, 'photo_metadata_date': '2026-01-16', 'service_date_source': 'user_confirmed_exception'}
        before = copy.deepcopy(intake)
        self.assertEqual(get_service_date_value(intake), '2026-01-15')
        self.assertEqual(find_duplicate_record(intake, self.index, strict=True), record)
        self.assertEqual(intake, before)

    def test_metadata_requiring_confirmation_is_not_silently_accepted(self):
        with self.assertRaisesRegex(IntakeError, 'Missing required field: service_date'):
            get_service_date_value({'photo_metadata_date': '2026-01-15', 'photo_metadata_date_requires_confirmation': True})
        self.assertEqual(get_service_date_value({'photo_metadata_date': '2026-01-15'}), '2026-01-15')

    def test_closing_date_never_substitutes_for_missing_service_date(self):
        with self.assertRaisesRegex(IntakeError, 'Missing required field: service_date'):
            get_service_date_value({'closing_date': '2026-01-16'})

    def test_invalid_calendar_date_stops_duplicate_check(self):
        with self.assertRaisesRegex(IntakeError, 'service_date must use YYYY-MM-DD'):
            find_duplicate_record({**self.intake, 'service_date': '2026-02-30'}, self.index, strict=True)

    def test_sent_drafted_and_legacy_records_block_normalized_case(self):
        for fields in ({}, {'status': 'sent'}, {'status': 'drafted'}):
            with self.subTest(fields=fields):
                record = self.record(**fields)
                self.assertEqual(find_duplicate_record(self.intake, self.index, strict=True), record)

    def test_same_period_blocks_different_period_can_coexist(self):
        record = self.record(status='drafted', service_period_label=' Manhã  ')
        self.assertEqual(find_duplicate_record({**self.intake, 'service_period_label': 'manhã'}, self.index, strict=True), record)
        self.assertIsNone(find_duplicate_record({**self.intake, 'service_period_label': 'tarde'}, self.index, strict=True))
        # An unspecified period cannot bypass an existing same-day blocker.
        self.assertEqual(find_duplicate_record(self.intake, self.index, strict=True), record)

    def test_retired_draft_statuses_are_auditable_without_blocking(self):
        for status in ('superseded', 'trashed', 'not_found'):
            with self.subTest(status=status):
                self.record(status=status)
                self.assertIsNone(find_duplicate_record(self.intake, self.index, strict=True))


if __name__ == '__main__':
    unittest.main()
