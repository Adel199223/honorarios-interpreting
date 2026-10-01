"""Fictional, offline acceptance for one photo containing several requests."""
from __future__ import annotations

import copy
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from honorarios_app import ai_recovery as ai
from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (
    AppPaths, apply_numbered_answers, preflight_intakes, prepare_intakes, recover_source_upload,
    require_current_preflight_review, review_intake_with_profile_evidence,
)
from honorarios_app.web import create_app
from scripts.generate_pdf import IntakeError


CASES = tuple(f'{number}/26.0TSTXX' for number in range(710, 715))
CAPTURE_DATE = '2026-09-26'
CITY = 'Capture City'
COURT = 'Tribunal de Capture City'
COURT_DOMAIN = 'tribunais' + '.org.pt'
RECIPIENT = 'fictional-capture@' + COURT_DOMAIN
TABLE_TEXT = ('Registo dos processos do serviço de interpretação presencial\n'
              'Processo\n' + '\n'.join(CASES))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


class MultiCaseSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-multi-case-public-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        write_json(self.paths.known_destinations, [{
            'destination': CITY, 'institution_examples': [COURT], 'km_one_way': 12,
            'notes': 'Fictional saved travel distance for the capture-city venue.',
        }])
        profiles = json.loads(self.paths.personal_profiles.read_text(encoding='utf-8'))
        profiles['profiles'][0]['travel_distances_by_city'][CITY] = 12
        write_json(self.paths.personal_profiles, profiles)
        write_json(self.paths.ai_config.with_name('photo-defaults.local.json'), {
            'capture_date_is_service_date': True,
            'photo_city_court': True,
            'missing_venue_is_city_court': True,
            'city_courts': {CITY: {
                'payment_entity': COURT, 'addressee': COURT, 'recipient_email': RECIPIENT,
            }},
        })
        original_connect = socket.socket.connect
        def synthetic_connect(sock, address):
            # Windows asyncio creates its own loopback socket pair even with an
            # in-process TestClient. Real HTTP transport remains forbidden below.
            host = address[0] if isinstance(address, tuple) else ''
            if host and ipaddress.ip_address(host).is_loopback:
                return original_connect(sock, address)
            raise AssertionError('Multi-case checks must stay offline.')
        network = patch('socket.socket.connect', new=synthetic_connect)
        network.start()
        self.addCleanup(network.stop)
        http = patch('httpx.HTTPTransport.handle_request',
                     side_effect=AssertionError('Multi-case checks must not make HTTP requests.'))
        http.start()
        self.addCleanup(http.stop)
        self.content = BytesIO()
        Image.new('RGB', (600, 900), 'white').save(self.content, format='JPEG')

    def managed_snapshot(self):
        return {path: path.read_bytes() for directory in ('config', 'data')
                for path in self.root.joinpath(directory).glob('*.json')}

    def assert_no_preparation_artifacts(self):
        for directory in (self.paths.output_dir, self.paths.html_dir,
                          self.paths.draft_output_dir, self.paths.intake_output_dir,
                          self.paths.manifest_dir, self.paths.packet_output_dir):
            self.assertEqual(list(directory.rglob('*')), [], str(directory.name))

    def recovery(self, *, case_numbers=CASES, text=TABLE_TEXT, fields=None):
        payload = {
            'status': 'ok', 'attempted': True, 'provider': 'fictional-replayed-recovery',
            'fields': {'photo_metadata_date': CAPTURE_DATE, 'photo_metadata_city': CITY,
                       **(fields or {})},
            'raw_visible_text': text, 'warnings': [], 'translation_indicators': [],
        }
        if case_numbers is not None:
            payload['case_numbers'] = list(case_numbers)
        return payload

    def upload(self, *, case_numbers=CASES, text=TABLE_TEXT, fields=None, through_api=False):
        before = self.managed_snapshot()
        recovery = self.recovery(case_numbers=case_numbers, text=text, fields=fields)
        with patch('honorarios_app.services.recover_source_with_openai', return_value=recovery) as provider:
            if through_api:
                with TestClient(create_app(**runtime_path_overrides(self.root)), base_url='http://127.0.0.1') as client:
                    response = client.post('/api/sources/upload',
                        files={'file': ('fictional-five-cases.jpg', self.content.getvalue(), 'image/jpeg')},
                        data={'source_kind': 'photo', 'profile_name': 'auto',
                              'visible_text': text, 'ai_recovery_mode': 'off'})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
            else:
                result = recover_source_upload(
                    filename='fictional-five-cases.jpg', content_type='image/jpeg',
                    content=self.content.getvalue(), source_kind='photo', profile_name='auto',
                    visible_text=text, ai_recovery_mode='off', paths=self.paths)
            provider.assert_called_once()
        self.assertEqual(self.managed_snapshot(), before)
        self.assert_no_preparation_artifacts()
        self.assertFalse(result['send_allowed'])
        return result

    def ready_candidates(self, result):
        self.assertEqual(result['case_count'], len(CASES))
        records = result['case_candidates']
        self.assertEqual(len(records), len(CASES))
        candidates = [record['candidate_intake'] for record in records]
        self.assertEqual([candidate['case_number'] for candidate in candidates], list(CASES))
        self.assertEqual(result['candidate_intake'], candidates[0])
        self.assertEqual(result['review'], records[0]['review'])
        for record in records:
            self.assertEqual(record['review']['status'], 'ready', record['review'])
            self.assertFalse(record['review']['send_allowed'])
        return candidates

    def test_photo_upload_returns_five_reviewed_candidates_without_writing_requests(self):
        result = self.upload(through_api=True)
        self.assertEqual(result['status'], 'uploaded')
        candidates = self.ready_candidates(result)
        self.assertEqual(len({candidate['source_sha256'] for candidate in candidates}), 1)
        self.assertTrue(candidates[0]['source_sha256'])
        for candidate in candidates:
            self.assertEqual(candidate['service_date'], CAPTURE_DATE)
            self.assertEqual(candidate['payment_entity'], COURT)
            self.assertEqual(candidate['recipient_email'], RECIPIENT)
            self.assertEqual(candidate['service_place'], COURT)
            self.assertEqual(candidate['source_case_number'], candidate['case_number'])
            self.assertEqual(candidate['raw_case_number'], candidate['case_number'])
            self.assertEqual(candidate['source_text'], candidates[0]['source_text'])

    def test_five_cases_with_one_photo_hash_generate_five_distinct_pdfs(self):
        candidates = self.ready_candidates(self.upload())
        before = self.managed_snapshot()
        preflight = preflight_intakes(candidates, self.paths, packet_mode=False)
        self.assertEqual(preflight['status'], 'ready', preflight)
        self.assertEqual(len(preflight['items']), 5)
        self.assertFalse(preflight['write_allowed'])
        self.assert_no_preparation_artifacts()
        prepared = prepare_intakes(candidates, self.paths, packet_mode=False)
        self.assertEqual(prepared['status'], 'prepared')
        self.assertFalse(prepared['packet_mode'])
        self.assertNotIn('packet', prepared)
        self.assertFalse(prepared['send_allowed'])
        self.assertEqual(len(prepared['items']), 5)
        self.assertEqual(len({item['pdf'] for item in prepared['items']}), 5)
        self.assertEqual(len(list(self.paths.output_dir.glob('*.pdf'))), 5)
        for case_number, item in zip(CASES, prepared['items']):
            text = '\n'.join(page.extract_text() or '' for page in PdfReader(item['pdf']).pages)
            self.assertIn(case_number, text)
            for other in set(CASES) - {case_number}:
                self.assertNotIn(other, text)
            self.assertIn('26/09/2026', text)
            self.assertIn(COURT, text)
            self.assertIn('Example Interpreter', text)
            payload = json.loads(Path(item['draft_payload']).read_text(encoding='utf-8'))
            self.assertEqual(payload['to'], RECIPIENT)
            self.assertFalse(payload['send_allowed'])
        self.assertEqual(self.managed_snapshot(), before)

    def test_repeated_and_leading_zero_equivalent_rows_do_not_create_extra_requests(self):
        repeated = [CASES[0], '00710/26.0TSTXX', *CASES[1:], CASES[0]]
        text = 'Processos do serviço de interpretação\n' + '\n'.join(repeated)
        self.ready_candidates(self.upload(case_numbers=repeated, text=text))

    def test_legacy_multiline_raw_case_field_is_split_instead_of_concatenated(self):
        raw = '\n'.join(CASES)
        result = self.upload(case_numbers=None, fields={'raw_case_number': raw, 'case_number': raw})
        self.ready_candidates(result)
        for record in result['case_candidates']:
            candidate = record['candidate_intake']
            self.assertNotIn('\n', candidate['case_number'])
            self.assertEqual(candidate['source_case_number'], candidate['case_number'])

    def test_each_fanned_out_case_keeps_its_identity_during_later_profile_review(self):
        candidates = self.ready_candidates(self.upload())
        for candidate in candidates:
            with self.subTest(case=candidate['case_number']):
                review = review_intake_with_profile_evidence(copy.deepcopy(candidate), self.paths)
                self.assertEqual(review['status'], 'ready', review)
                self.assertEqual(review['intake']['case_number'], candidate['case_number'])
                self.assertEqual(review['intake']['source_case_number'], candidate['case_number'])

    def test_malformed_reference_cannot_become_ready_from_profile_defaults(self):
        raw = '710/??.0TSTXX'
        result = self.upload(case_numbers=[raw], text='Processo ' + raw,
                             fields={'raw_case_number': raw})
        records = result.get('case_candidates') or [result]
        self.assertTrue(records)
        for record in records:
            self.assertNotEqual(record['review']['status'], 'ready')
            self.assertIn('case_number', {q['field'] for q in record['review'].get('questions', [])})

    def test_alternative_readings_of_one_unclear_reference_are_not_two_ready_cases(self):
        text = f'Processo {CASES[0]} ou {CASES[1]} (últimos dígitos ilegíveis).'
        result = self.upload(case_numbers=[CASES[0], CASES[1]], text=text)
        records = result.get('case_candidates') or [result]
        self.assertTrue(records)
        self.assertFalse(any(record['review']['status'] == 'ready' for record in records), records)

    def test_unclear_reference_does_not_discard_another_readable_service_row(self):
        text = (f'Processo {CASES[0]} ou {CASES[1]} (últimos dígitos ilegíveis).\n'
                f'Processo {CASES[2]}\nRegisto do serviço de interpretação presencial.')
        result = self.upload(case_numbers=CASES[:3], text=text)
        records = result['case_candidates']
        self.assertEqual(len(records), 2)
        readable = [record for record in records if record['candidate_intake'].get('case_number')]
        unresolved = [record for record in records if not record['candidate_intake'].get('case_number')]
        self.assertEqual(len(readable), 1)
        self.assertEqual(readable[0]['candidate_intake']['case_number'], CASES[2])
        self.assertEqual(readable[0]['review']['status'], 'ready')
        self.assertEqual(len(unresolved), 1)
        self.assertNotEqual(unresolved[0]['review']['status'], 'ready')
        self.assertIn('ilegíveis', unresolved[0]['candidate_intake']['raw_case_number'])

    def test_readable_case_survives_unrelated_uncertainty_in_a_later_same_line_sentence(self):
        for uncertainty in ('Data do serviço ilegível.', 'Local da diligência ilegível.'):
            with self.subTest(uncertainty=uncertainty):
                text = f'Processo {CASES[0]}. {uncertainty}'
                result = self.upload(case_numbers=[CASES[0]], text=text,
                                     fields={'case_number': CASES[0], 'raw_case_number': CASES[0]})
                self.assertEqual(result['case_count'], 1)
                candidate = result['candidate_intake']
                self.assertEqual(candidate['case_number'], CASES[0])
                self.assertEqual(candidate['source_case_number'], CASES[0])
                self.assertNotIn('case_number', {q['field'] for q in result['review'].get('questions', [])})

    def test_ambiguous_row_attention_is_blocked_even_beside_a_ready_case(self):
        text = (f'Processo {CASES[2]}\n'
                f'Processo {CASES[0]} ou {CASES[1]} (últimos dígitos ilegíveis).')
        result = self.upload(case_numbers=CASES[:3], text=text)
        for record in result['case_candidates']:
            review = record['review']
            evidence = review.get('review_evidence') or review.get('source_evidence') or {}
            attention = evidence.get('attention') or {}
            if not record['candidate_intake'].get('case_number'):
                self.assertEqual(review['status'], 'needs_info')
                self.assertEqual(attention.get('status'), 'blocked', record)
                self.assertTrue(any(flag.get('severity') == 'blocked' for flag in attention.get('flags', [])))
            else:
                self.assertEqual(review['status'], 'ready')
                self.assertNotEqual(attention.get('status'), 'blocked')

    def test_numbered_case_answer_requires_one_valid_reference_before_readiness(self):
        text = f'Processo {CASES[0]} ou {CASES[1]} (últimos dígitos ilegíveis).'
        uploaded = self.upload(case_numbers=CASES[:2], text=text)
        candidate = uploaded['candidate_intake']
        for bad_answer in (f'{CASES[0]} ou {CASES[1]}', '710/??.0TSTXX'):
            with self.subTest(answer=bad_answer):
                initial = review_intake_with_profile_evidence(copy.deepcopy(candidate), self.paths)
                questions = {q['field']: q['number'] for q in initial['questions']}
                self.assertIn('case_number', questions)
                bad = apply_numbered_answers({'intake': initial['intake'],
                    'answer_text': f"{questions['case_number']}. {bad_answer}"}, self.paths)
                self.assertEqual(bad['status'], 'needs_info', bad)
                self.assertFalse(bad['intake'].get('case_number'))
                self.assertEqual(preflight_intakes([bad['intake']], self.paths)['status'], 'blocked')
                with self.assertRaises(IntakeError):
                    prepare_intakes([bad['intake']], self.paths)
                remaining = {q['field']: q['number'] for q in bad['questions']}
                resolved = apply_numbered_answers({'intake': bad['intake'],
                    'answer_text': f"{remaining['case_number']}. {CASES[0]}"}, self.paths)
                self.assertEqual(resolved['status'], 'ready', resolved)
                self.assertEqual(resolved['intake']['case_number'], CASES[0])
        self.assert_no_preparation_artifacts()

    def test_npp_and_npe_administrative_references_do_not_become_fee_requests(self):
        administrative = ('720/26.0TSTXX', '721/26.0TSTXX')
        text = (f'Processo {CASES[0]}\nNPP: {administrative[0]}\n'
                f'NPe: {administrative[1]}\nRegisto do serviço de interpretação presencial.')
        result = self.upload(case_numbers=[CASES[0], *administrative], text=text)
        self.assertEqual(result['case_count'], 1)
        self.assertEqual(result['candidate_intake']['case_number'], CASES[0])
        self.assertEqual(result['review']['status'], 'ready', result['review'])
        self.assertEqual(len(result['case_candidates']), 1)

    def test_spaced_suffix_does_not_create_ready_truncated_case_or_extra_row(self):
        for declared in ([], [CASES[0]], ['710/26.0T']):
            with self.subTest(declared=declared):
                raw = '710/26.0T S T X X'
                result = self.upload(case_numbers=declared, text=f'Processo {raw}')
                self.assertEqual(result['case_count'], 1)
                self.assertEqual(result['candidate_intake']['case_number'], '')
                self.assertEqual(result['candidate_intake']['raw_case_number'], raw)
                self.assertEqual(result['review']['status'], 'needs_info')
                self.assertEqual(preflight_intakes([result['candidate_intake']], self.paths)['status'], 'blocked')
                corrected = copy.deepcopy(result['candidate_intake'])
                corrected['case_number'] = CASES[0]
                reviewed = review_intake_with_profile_evidence(corrected, self.paths)
                self.assertEqual(reviewed['status'], 'ready')
                self.assertEqual(reviewed['intake']['case_number'], CASES[0])
        self.assert_no_preparation_artifacts()

    def test_existing_duplicate_blocks_entire_batch_before_any_artifacts(self):
        candidates = self.ready_candidates(self.upload())
        write_json(self.paths.duplicate_index, [{
            'case_number': CASES[-1], 'service_date': CAPTURE_DATE,
            'status': 'sent', 'recipient': RECIPIENT,
        }])
        before = self.managed_snapshot()
        preflight = preflight_intakes(candidates, self.paths, packet_mode=False)
        self.assertEqual(preflight['status'], 'blocked')
        self.assertEqual(preflight['items'][-1]['status'], 'blocked')
        with self.assertRaises(IntakeError):
            prepare_intakes(candidates, self.paths, packet_mode=False)
        self.assert_no_preparation_artifacts()
        self.assertEqual(self.managed_snapshot(), before)

    def test_duplicate_sibling_cannot_bypass_batch_checks_with_shared_photo_hash(self):
        candidates = self.ready_candidates(self.upload())
        duplicate = copy.deepcopy(candidates[0])
        duplicate['case_number'] = '00710/26.0TSTXX'
        preflight = preflight_intakes([*candidates, duplicate], self.paths, packet_mode=False)
        self.assertEqual(preflight['status'], 'blocked')
        with self.assertRaisesRegex(IntakeError, 'Duplicate request'):
            prepare_intakes([*candidates, duplicate], self.paths, packet_mode=False)
        self.assert_no_preparation_artifacts()

    def test_removing_reordering_or_editing_photo_siblings_invalidates_preflight(self):
        candidates = self.ready_candidates(self.upload())
        preflight = preflight_intakes(candidates, self.paths, packet_mode=False)
        require_current_preflight_review({'preflight_review': preflight['preflight_review']},
                                        candidates, self.paths, packet_mode=False)
        edited = copy.deepcopy(candidates)
        edited[-1]['service_date'] = '2026-09-27'
        for changed in (candidates[:-1], list(reversed(candidates)), edited):
            with self.subTest(cases=[row['case_number'] for row in changed]):
                with self.assertRaises(IntakeError):
                    require_current_preflight_review({
                        'preflight_review': preflight['preflight_review'],
                    }, changed, self.paths, packet_mode=False)
        self.assert_no_preparation_artifacts()


class MultiCaseNormalizationTests(unittest.TestCase):
    def test_administrative_label_does_not_hide_later_nuipc_on_same_line(self):
        from honorarios_app.source_cases import source_case_rows
        rows = source_case_rows(f'NPP: 990/26.0TSTXX NUIPC: {CASES[0]}', {})
        self.assertEqual([row['case_number'] for row in rows], [CASES[0]])

    def test_lowercase_spaced_suffix_and_normal_conjunction_remain_distinct(self):
        from honorarios_app.source_cases import source_case_rows
        for raw in ('710/26.0t s t x x', '710/26.0T S t X x', '710/26.0TSTX X'):
            with self.subTest(raw=raw):
                rows = source_case_rows('Processo ' + raw, {'case_numbers': [CASES[0]]})
                self.assertEqual(rows, [{'case_number': '', 'raw_case_number': raw}])
        rows = source_case_rows(f'{CASES[0]} e {CASES[1]}', {})
        self.assertEqual([row['case_number'] for row in rows], list(CASES[:2]))

    def test_strict_extraction_schema_requires_a_case_list(self):
        schema = ai.AI_RECOVERY_RESPONSE_FORMAT['format']['schema']
        self.assertIn('case_numbers', schema['required'])
        self.assertEqual(schema['properties']['case_numbers']['type'], 'array')
        self.assertEqual(schema['properties']['case_numbers']['items']['type'], 'string')

    def test_multiple_cases_leave_legacy_single_case_fields_empty(self):
        normalized = ai._normalize_ai_payload({
            'case_numbers': list(CASES), 'raw_visible_text': TABLE_TEXT,
            'fields': {'case_number': CASES[0], 'raw_case_number': CASES[0]},
        })
        self.assertEqual(normalized['case_numbers'], list(CASES))
        self.assertFalse(normalized['fields'].get('case_number'))
        self.assertFalse(normalized['fields'].get('raw_case_number'))


if __name__ == '__main__':
    unittest.main()
