"""Synthetic, local-only proof that explicit exclusions cannot become new fees."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.request_exclusions import (
    RequestExclusionError, exclusion_ledger_path, find_request_exclusion,
    format_request_exclusion, load_request_exclusions, match_request_exclusion,
    require_not_excluded, require_requests_not_excluded, validate_request_exclusion_payload,
)


def row(**changes):
    return {'case_number': '901/26.0TEST', 'service_date': '2026-01-05',
            'completion_evidence': 'user_confirmed_done', 'reason': 'User says this is already handled.',
            'source_filename': 'fictional.jpg', 'source_sha256': 'a' * 64, **changes}


def ledger(*rows, **changes):
    return {'schema_version': 1, 'excluded_cases': list(rows), **changes}


class RequestExclusionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='honorarios-exclusions-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.index = self.root / 'duplicate-index.json'
        self.path = exclusion_ledger_path(self.index)

    def save(self, payload):
        self.path.write_text(json.dumps(payload), encoding='utf-8')

    def test_missing_ledger_is_normal_and_uses_passed_runtime_only(self):
        self.assertEqual(load_request_exclusions(self.path), [])
        self.assertIsNone(find_request_exclusion(row(), self.index))
        require_requests_not_excluded(row(), self.index)
        self.assertFalse(self.path.exists())
        self.save(ledger(row()))
        other_index = self.root / 'other-runtime' / 'data' / 'duplicate-index.json'
        self.assertIsNone(find_request_exclusion(row(), other_index))
        self.assertEqual(exclusion_ledger_path(other_index).parent, other_index.parent)

    def test_completed_and_excluded_have_distinct_honest_labels(self):
        for completion, kind, title in [('user_confirmed_done', 'user_confirmed_done', 'Already handled'),
                                        (None, 'user_excluded', 'Excluded at your request'),
                                        ('arbitrary text', 'user_excluded', 'Excluded at your request')]:
            with self.subTest(completion=completion):
                self.save(ledger(row(completion_evidence=completion)))
                result = find_request_exclusion(row(), self.index)
                self.assertEqual(result['kind'], kind)
                self.assertTrue(format_request_exclusion(result).startswith(title))
                self.assertNotIn('sent', format_request_exclusion(result).lower())
                self.assertNotIn('paid', format_request_exclusion(result).lower())
                with self.assertRaisesRegex(RequestExclusionError, title):
                    require_not_excluded(row(), self.index)

    def test_normalized_identity_and_conservative_period_overlap(self):
        self.save(ledger(row(case_number=' 000901 / 26.0test ', service_period_label=' Morning  Session ')))
        self.assertIsNotNone(find_request_exclusion(row(service_period_label='morning session'), self.index))
        self.assertIsNotNone(find_request_exclusion(row(), self.index))
        self.assertIsNone(find_request_exclusion(row(service_period_label='afternoon'), self.index))
        self.assertIsNone(find_request_exclusion(row(service_date='2026-01-06'), self.index))
        self.assertIsNone(find_request_exclusion(row(case_number='902/26.0TEST'), self.index))
        self.save(ledger(row()))
        self.assertIsNotNone(find_request_exclusion(row(service_period_label='afternoon'), self.index))

    def test_shared_source_hash_does_not_exclude_siblings_or_other_day(self):
        self.save(ledger(row()))
        for changed in ({'case_number': '902/26.0TEST'}, {'service_date': '2026-01-06'}):
            self.assertIsNone(find_request_exclusion(row(**changed), self.index))
        self.assertTrue(find_request_exclusion(row(), self.index)['matching_source_sha256'])
        different_photo = find_request_exclusion(row(source_sha256='b' * 64), self.index)
        self.assertIsNotNone(different_photo)
        self.assertFalse(different_photo['matching_source_sha256'])

    def test_ledger_and_matches_do_not_mutate_or_disclose_raw_evidence(self):
        source = ledger(row(status='sent', sent_at='secret', gmail_message_id='secret',
                            submission_date='secret', submission_channel='paper', source_path='private/secret',
                            reason='private/secret', source_filenames=['fictional.jpg', 'second.jpg']))
        original = deepcopy(source)
        exclusions = validate_request_exclusion_payload(source)
        result = match_request_exclusion(row(), exclusions)
        self.assertEqual(source, original)
        self.assertNotIn('secret', json.dumps(result))
        for name in ('status', 'sent_at', 'gmail_message_id', 'source_path', 'submission_date', 'submission_channel'):
            self.assertNotIn(name, result)
        result['source_filenames'].append('third.jpg')
        self.assertEqual(source, original)
        self.assertEqual(len(exclusions[0]['source_filenames']), 2)

    def test_forms_and_pac_categories_do_not_invent_case_date_exclusions(self):
        source = ledger(forms=[row(completion_evidence='signed fee request submitted'),
                               {'reference': 'PAC99999', 'case_number': None, 'service_date': None},
                               {'reference': 'attendance certificate', 'signature': True}],
                        standing_exclusions=[{'category': 'PSP PAC procedures'}])
        self.save(source)
        self.assertIsNone(find_request_exclusion(row(), self.index))
        self.assertEqual(validate_request_exclusion_payload({'schema_version': 1, 'forms': []}), [])
        self.assertEqual(json.loads(self.path.read_text()), source)

    def test_corrupt_json_and_duplicate_keys_fail_with_fixed_safe_error(self):
        for content in ['{private/path/secret', '{"schema_version":1,"excluded_cases":[],"excluded_cases":[]}',
                        '\ud800', 'null', '[]']:
            with self.subTest(content=repr(content)):
                self.path.write_bytes(content.encode('utf-8', errors='surrogatepass'))
                with self.assertRaises(RequestExclusionError) as error:
                    find_request_exclusion({}, self.index)
                self.assertIn('Saved request exclusions could not be checked', str(error.exception))
                self.assertNotIn('secret', str(error.exception))
                self.assertNotIn(str(self.path), str(error.exception))

    def test_relevant_malformed_records_fail_instead_of_disappearing(self):
        malformed = [ledger(schema_version=True), ledger(schema_version=2), ledger(excluded_cases=None),
                     ledger('not an object'), ledger(row(case_number='PAC99999')),
                     ledger(row(service_date='2026-02-30')), ledger(row(service_date='20260105')),
                     ledger(row(service_date=None)), ledger(row(service_period_label=['morning'])),
                     ledger(row(service_period='morning')),
                     ledger(row(service_period='morning', service_period_label='afternoon')),
                     ledger(row(source_sha256='invalid')),
                     ledger(row(source_filename='C:/private/secret.jpg')), ledger(row(source_filenames='photo.jpg')),
                     ledger(row(source_filenames=[None])), ledger(row(reason={'unexpected': True})),
                     ledger(forms='invalid'), ledger(standing_exclusions=[False])]
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaises(RequestExclusionError):
                    validate_request_exclusion_payload(payload)

    def test_unreadable_directory_and_bounded_input_fail_closed(self):
        self.path.mkdir()
        with self.assertRaises(RequestExclusionError):
            load_request_exclusions(self.path)
        self.path.rmdir()
        self.save(ledger(row()))
        with patch('scripts.request_exclusions.MAX_LEDGER_BYTES', 16):
            with self.assertRaises(RequestExclusionError):
                load_request_exclusions(self.path)
        with patch('scripts.request_exclusions.MAX_EXCLUDED_REQUESTS', 1):
            with self.assertRaises(RequestExclusionError):
                validate_request_exclusion_payload(ledger(row(), row(case_number='902/26.0TEST')))

    def test_incomplete_review_has_no_match_but_invalid_ledger_is_still_visible(self):
        self.save(ledger(row()))
        for intake in ({}, row(case_number=''), row(service_date=''), row(service_date='bad'),
                       row(service_period_label=[])):
            self.assertIsNone(find_request_exclusion(intake, self.index))
        self.save(ledger(excluded_cases='broken'))
        with self.assertRaises(RequestExclusionError):
            find_request_exclusion({}, self.index)

    def test_backup_validator_bounds_all_retained_evidence_and_written_utf8(self):
        for source in (ledger(row(private_note='é' * 100)),
                       ledger(forms=[{'evidence': 'é' * 100}]),
                       ledger(standing_exclusions=[{'evidence': 'é' * 100}]),
                       ledger(private_note='é' * 100)):
            with self.subTest(source=source):
                size = len((json.dumps(source, ensure_ascii=False, indent=2) + '\n').replace('\n', '\r\n').encode('utf-8'))
                with patch('scripts.request_exclusions.MAX_LEDGER_BYTES', size):
                    validate_request_exclusion_payload(source)
                with patch('scripts.request_exclusions.MAX_LEDGER_BYTES', size - 1):
                    with self.assertRaises(RequestExclusionError):
                        validate_request_exclusion_payload(source)
        for invalid in (ledger(private_note=object()), ledger(private_note='\ud800')):
            with self.assertRaises(RequestExclusionError):
                validate_request_exclusion_payload(invalid)

    def test_late_exclusion_is_reloaded_and_no_correction_flags_bypass(self):
        candidate = row(allow_existing_draft=True, correction_reason='replace', supersedes={'draft_id': 'synthetic'})
        require_requests_not_excluded(candidate, self.index)
        self.save(ledger(row()))
        before = self.path.read_bytes()
        with self.assertRaises(RequestExclusionError):
            require_requests_not_excluded(candidate, self.index)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_every_grouped_child_and_top_level_identity_is_checked(self):
        self.save(ledger(row()))
        safe = row(case_number='902/26.0TEST')
        require_requests_not_excluded({'underlying_requests': [safe]}, self.index)
        for payload in ({'underlying_requests': [safe, row()]},
                        {**row(), 'underlying_requests': [safe]},
                        {**safe, 'underlying_requests': [row()]}):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(RequestExclusionError, 'Already handled'):
                    require_requests_not_excluded(payload, self.index)

    def test_malformed_or_missing_children_cannot_bypass_final_guard(self):
        safe = row(case_number='902/26.0TEST')
        for payload in (None, {}, {'underlying_requests': []}, {'underlying_requests': {}},
                        {'underlying_requests': [None]}, {'underlying_requests': [{}]},
                        {'underlying_requests': [{**safe, 'underlying_requests': [row()]}]},
                        {**safe, 'underlying_requests': [row(service_date='invalid')]},
                        row(case_number='invalid'), row(service_date='2026-02-30')):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(RequestExclusionError, 'Every request needs'):
                    require_requests_not_excluded(payload, self.index)

    def test_effective_date_uses_shared_photo_and_confirmation_rules(self):
        self.save(ledger(row()))
        photo = row(service_date='', photo_metadata_date='2026-01-05')
        with self.assertRaisesRegex(RequestExclusionError, 'Already handled'):
            require_requests_not_excluded(photo, self.index)
        conflict = row(service_date='2026-01-06', photo_metadata_date='2026-01-05')
        with self.assertRaisesRegex(RequestExclusionError, 'Every request needs'):
            require_requests_not_excluded(conflict, self.index)
        require_requests_not_excluded({**conflict, 'service_date_source': 'user_confirmed'}, self.index)
        with self.assertRaisesRegex(RequestExclusionError, 'Every request needs'):
            require_requests_not_excluded({**photo, 'photo_metadata_date_requires_confirmation': True}, self.index)

    def test_multiple_reasons_retain_completion_without_fabricating_submission(self):
        self.save(ledger(row(completion_evidence=None), row()))
        result = find_request_exclusion(row(), self.index)
        self.assertEqual(result['kind'], 'user_confirmed_done')
        self.assertNotIn('submission_channel', result)
        self.assertNotIn('sent_at', result)


if __name__ == '__main__':
    unittest.main()
