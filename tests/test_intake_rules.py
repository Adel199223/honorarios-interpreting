"""Public regressions using fictional cases and temporary duplicate records."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (
    AppPaths, apply_numbered_answers, preflight_intakes, recover_source_upload, review_intake,
)

from scripts.check_duplicate import main as check_duplicate
from scripts.intake_questions import missing_questions
from scripts.generate_pdf import IntakeError, find_duplicate_record, get_service_date_value


class IntakeRulesTests(unittest.TestCase):
    def test_conflict_question_shows_both_dates_and_accepts_explicit_choices(self):
        intake = {'service_date': '2026-09-26', 'photo_metadata_date': '2026-09-28',
                  'service_date_source': 'document_text'}
        question = next(q for q in missing_questions(intake) if q['field'] == 'service_date_source')
        self.assertIn('2026-09-26', question['question'])
        self.assertIn('2026-09-28', question['question'])
        self.assertIn('document or metadata', question['answer_hint'])

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


class UploadedPhotoDateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-photo-date-rules-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        image = Image.new('RGB', (400, 400), 'white')
        exif = image.getexif()
        exif[36867] = '2026:09:26 10:15:00'
        buffer = BytesIO()
        image.save(buffer, format='JPEG', exif=exif)
        self.photo = buffer.getvalue()

    def upload(self, visible_text=''):
        with patch('honorarios_app.services.recover_source_with_openai', return_value={'status': 'disabled', 'fields': {}}):
            return recover_source_upload(filename='synthetic-exif-source.jpg', content_type='image/jpeg',
                                         content=self.photo, source_kind='photo', profile_name='auto',
                                         visible_text=visible_text, ai_recovery_mode='off', paths=self.paths)

    def test_exif_capture_date_is_evidence_and_requires_service_date_answer(self):
        result = self.upload()
        candidate = result['candidate_intake']
        self.assertEqual(result['source']['metadata']['exif_date'], '2026-09-26')
        self.assertEqual(candidate['photo_metadata_date'], '2026-09-26')
        self.assertNotIn('service_date', candidate)
        self.assertTrue(candidate['photo_metadata_date_requires_confirmation'])
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertEqual([question['field'] for question in result['review']['questions']], ['case_number', 'service_date'])

    def test_answering_only_case_cannot_promote_exif_date_or_unblock_preflight(self):
        candidate = self.upload()['candidate_intake']
        before = copy.deepcopy(candidate)
        result = apply_numbered_answers({'intake': candidate, 'answers': '1. 700/26.0EXAMPLE'}, self.paths)
        self.assertEqual(candidate, before)
        self.assertEqual(result['status'], 'needs_info')
        self.assertEqual(result['applied_fields'], ['case_number'])
        self.assertEqual([question['field'] for question in result['questions']], ['service_date'])
        self.assertNotIn('service_date', result['intake'])
        self.assertEqual(result['intake']['photo_metadata_date'], '2026-09-26')
        with self.assertRaisesRegex(IntakeError, 'Missing required field: service_date'):
            preflight_intakes([result['intake']], self.paths)
        for directory in (self.paths.output_dir, self.paths.draft_output_dir, self.paths.manifest_dir):
            self.assertFalse(list(directory.glob('*')))
        self.assertEqual(json.loads(self.paths.duplicate_index.read_text(encoding='utf-8')), [])
        self.assertEqual(json.loads(self.paths.draft_log.read_text(encoding='utf-8')), [])

    def test_explicit_date_answer_enables_review_and_keeps_duplicate_protection(self):
        candidate = self.upload()['candidate_intake']
        result = apply_numbered_answers({'intake': candidate, 'answers': '1. 700/26.0EXAMPLE\n2. 2026-09-26'}, self.paths)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['intake']['service_date'], '2026-09-26')
        self.assertEqual(result['intake']['service_date_source'], 'user_confirmed')
        self.assertEqual(preflight_intakes([result['intake']], self.paths)['status'], 'ready')
        self.paths.duplicate_index.write_text(json.dumps([{'case_number': '700/26.0EXAMPLE', 'service_date': '2026-09-26', 'status': 'drafted'}]), encoding='utf-8')
        self.assertEqual(review_intake(result['intake'], self.paths)['status'], 'duplicate')
        self.assertEqual(preflight_intakes([result['intake']], self.paths)['status'], 'blocked')

    def test_document_service_date_remains_authoritative_when_it_matches_exif(self):
        result = self.upload('Synthetic interpreting service 700/26.0EXAMPLE on 2026-09-26')
        candidate = result['candidate_intake']
        self.assertEqual(candidate['service_date'], '2026-09-26')
        self.assertFalse(candidate.get('photo_metadata_date_requires_confirmation', False))
        self.assertEqual(candidate['service_date_source'], 'document_text_and_photo_metadata')
        self.assertEqual(result['review']['status'], 'ready')

    def test_document_exif_conflict_still_requires_explicit_date_choice(self):
        result = self.upload('Synthetic interpreting service 700/26.0EXAMPLE on 2026-09-25')
        candidate = result['candidate_intake']
        self.assertEqual(candidate['service_date'], '2026-09-25')
        self.assertEqual(candidate['photo_metadata_date'], '2026-09-26')
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertEqual([question['field'] for question in result['review']['questions']], ['service_date_source'])
        confirmed = apply_numbered_answers({'intake': candidate, 'answers': '1. metadata'}, self.paths)
        self.assertEqual(confirmed['status'], 'ready')
        self.assertEqual(confirmed['intake']['service_date'], '2026-09-26')
        self.assertEqual(confirmed['intake']['service_date_source'], 'photo_metadata_user_confirmed')


if __name__ == '__main__':
    unittest.main()
