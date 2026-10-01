"""Fictional, provider-free acceptance of claim scope and explicit shared visits."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from honorarios_app.runtime import SYNTHETIC_COURT_EMAIL, create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (
    AppPaths, _assert_gmail_create_duplicate_clear, apply_answer_to_intake,
    effective_intake_for_profile, preflight_intakes, prepare_intakes, review_intake,
)
from scripts.build_email_draft import custom_transport_body_conflict, resolve_email_body, validate_draft_payload
from scripts.claim_options import ClaimError, claim_metadata, recorded_travel_requests, validate_shared_travel_groups
from scripts.generate_pdf import IntakeError, build_rendered_request, generate_pdf
from scripts.intake_questions import missing_questions
from scripts.prepare_honorarios import main as prepare_cli
from scripts.record_gmail_draft import main as record_cli
from scripts.request_identity import request_identity_key

ROOT = Path(__file__).resolve().parents[1]


class ClaimOptionsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fictional-claim-options-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        self.intake = json.loads((ROOT / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        self.intake['recipient_email'] = SYNTHETIC_COURT_EMAIL
        self.intake, self.profile, _ = effective_intake_for_profile(self.intake, self.paths)
        self.email_config = json.loads(self.paths.email_config.read_text(encoding='utf-8'))
        # Any unexpected provider/network path fails immediately.
        self.network_guard = patch('socket.socket.connect', side_effect=AssertionError('Network is forbidden in synthetic claim tests'))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def row(self, number=100, **fields):
        intake = copy.deepcopy(self.intake)
        intake.update(case_number=f'{number}/26.0TSTXX', **fields)
        return intake

    def rows(self):
        return [self.row(number, travel_group_id='fictional-explicit-visit', claim_transport=number == 101)
                for number in range(101, 106)]

    def rendered_text(self, intake):
        target = self.root / 'actual-claim.pdf'
        rendered = build_rendered_request(intake, self.profile)
        generate_pdf(rendered, target)
        reader = PdfReader(target)
        self.assertEqual(len(reader.pages), 1)
        return rendered, ' '.join(reader.pages[0].extract_text().split())

    def assert_no_artifacts(self):
        for directory in (self.paths.output_dir, self.paths.html_dir, self.paths.draft_output_dir,
                          self.paths.manifest_dir, self.paths.intake_output_dir, self.paths.packet_output_dir):
            self.assertFalse(directory.exists() and any(directory.iterdir()), str(directory))

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def cli_args(self, rows):
        sources = []
        for index, row in enumerate(rows):
            source = self.root / f'input-{index}.json'
            self.write(source, row)
            sources.append(str(source))
        return sources + [
            '--profile', str(self.paths.profile), '--template', str(self.paths.template),
            '--email-config', str(self.paths.email_config), '--court-emails', str(self.paths.court_emails),
            '--duplicate-index', str(self.paths.duplicate_index), '--draft-log', str(self.paths.draft_log),
            '--output-dir', str(self.paths.output_dir), '--html-dir', str(self.paths.html_dir),
            '--draft-output-dir', str(self.paths.draft_output_dir), '--manifest', str(self.paths.manifest_dir / 'cli.json'),
        ]

    def test_legacy_default_still_claims_interpreting_and_existing_transport(self):
        legacy = self.row()
        explicit = {**legacy, 'claim_interpreting': True}
        self.assertEqual(build_rendered_request(legacy, self.profile), build_rendered_request(explicit, self.profile))
        rendered, text = self.rendered_text(legacy)
        self.assertIn('honorários devidos', text)
        self.assertIn(rendered.vat_irs_phrase, text)
        self.assertIn('despesas de transporte', text)

    def test_interpreting_only_needs_no_distance_and_omits_travel(self):
        row = self.row(claim_interpreting=True, claim_transport=False)
        row.pop('transport')
        self.assertEqual(missing_questions(row), [])
        rendered, text = self.rendered_text(row)
        self.assertIsNone(rendered.transport_paragraph)
        self.assertNotIn('despesas de transporte', text)
        self.assertNotIn(' km', text)
        self.assertIn('honorários devidos', text)
        self.assertIn(rendered.vat_irs_phrase, text)

    def test_travel_only_actual_pdf_claims_attendance_and_transport_without_performed_service_or_tax(self):
        row = self.row(claim_interpreting=False, claim_transport=True)
        row.update(service_period_label='manhã', service_start_time='09:00', service_end_time='11:00')
        rendered, text = self.rendered_text(row)
        for value in ('compareci na qualidade de intérprete', '15/01/2026', 'Example Police Station',
                      'despesas de transporte', '12 km', self.profile['signature_name'], self.profile['iban'],
                      self.profile['payment_phrase'], self.profile['address']):
            self.assertIn(value, text)
        for value in ('honorários devidos', 'diligência realizada', 'serviço de interpretação prestado',
                      'IVA', 'IRS', '09:00', '11:00', 'não prestei'):
            self.assertNotIn(value, text)
        self.assertEqual(rendered.vat_irs_phrase, '')
        self.assertTrue(rendered.transport_paragraph.startswith('Requer '))

    def test_neither_pauses_and_numbered_choice_recovers_without_changing_identity(self):
        row = self.row(claim_interpreting=False, claim_transport=False)
        identity = request_identity_key(row)
        self.assertEqual(missing_questions(row)[0]['field'], 'claim_options')
        self.assertEqual(review_intake(row, self.paths)['status'], 'needs_info')
        with self.assertRaisesRegex(IntakeError, 'at least one'):
            build_rendered_request(row, self.profile)
        for value, expected in [('both', (True, True)), ('interpreting-only', (True, False)), ('travel-only', (False, True))]:
            apply_answer_to_intake(row, 'claim_options', value)
            self.assertEqual((row['claim_interpreting'], row['claim_transport']), expected)
            self.assertEqual(request_identity_key(row), identity)

    def test_claim_flags_must_be_booleans(self):
        for field, value in [('claim_interpreting', 'false'), ('claim_transport', 1)]:
            with self.subTest(field=field), self.assertRaises(IntakeError):
                build_rendered_request(self.row(**{field: value}), self.profile)

    def test_travel_distance_must_be_positive_and_finite(self):
        for distance in (0, -1, float('nan'), float('inf'), '-inf', 'invalid'):
            with self.subTest(distance=distance), self.assertRaisesRegex(IntakeError, 'must be'):
                row = self.row(claim_interpreting=False)
                row['transport']['km_one_way'] = distance
                build_rendered_request(row, self.profile)

    def test_travel_only_default_email_does_not_mutate_saved_preferences(self):
        before = copy.deepcopy(self.email_config)
        result = prepare_intakes([self.row(claim_interpreting=False)], self.paths)
        payload = json.loads(Path(result['items'][0]['draft_payload']).read_text(encoding='utf-8'))
        self.assertEqual(payload['subject'], 'Requerimento de despesas de transporte')
        self.assertIn('comparência na qualidade de intérprete', payload['body'])
        self.assertNotIn('honorários', payload['body'])
        self.assertTrue(payload['draft_only'])
        self.assertFalse(payload['send_allowed'])
        self.assertEqual(validate_draft_payload(payload), [])
        self.assertEqual(json.loads(self.paths.email_config.read_text(encoding='utf-8')), before)

    def test_normal_custom_travel_email_and_genre_title_remain_verbatim(self):
        for body in ('Requerimento de honorários\nSolicito apenas despesas de transporte pela comparência.',
                     'Não solicito honorários; solicito apenas transporte.',
                     'Não prestei interpretação. Requeiro apenas transporte.'):
            with self.subTest(body=body):
                self.assertFalse(custom_transport_body_conflict(body))
                self.assertEqual(resolve_email_body(self.row(claim_interpreting=False, email_body=body), self.email_config), body)

    def test_custom_performed_work_or_fee_claim_blocks_review_and_zero_artifact_preparation(self):
        for body in ('Requeiro o pagamento dos honorários devidos.', 'Prestei serviço de interpretação.',
                     'A diligência foi realizada no tribunal.',
                     'Não peço recibo, mas solicito pagamento dos honorários.'):
            with self.subTest(body=body):
                row = self.row(claim_interpreting=False, email_body=body)
                self.assertEqual(review_intake(row, self.paths)['status'], 'error')
                self.assertEqual(preflight_intakes([row], self.paths)['status'], 'blocked')
                with self.assertRaisesRegex(IntakeError, 'custom body'):
                    prepare_intakes([row], self.paths)
                self.assert_no_artifacts()

    def test_five_shared_cases_generate_five_pdfs_with_exactly_one_travel_claim(self):
        rows = self.rows()
        rows[2]['transport'].pop('km_one_way')  # Nonclaiming members need no distance.
        self.assertEqual(preflight_intakes(rows, self.paths)['status'], 'ready')
        result = prepare_intakes(rows, self.paths)
        self.assertEqual(len(result['items']), 5)
        travel = []
        for item in result['items']:
            text = ' '.join(PdfReader(item['pdf']).pages[0].extract_text().split())
            travel.append('despesas de transporte' in text)
            self.assertIn(item['case_number'], text)
            self.assertTrue(item['claim_interpreting'])
            self.assertEqual(item['travel_group_id'], 'fictional-explicit-visit')
        self.assertEqual(travel, [True, False, False, False, False])

    def test_double_transport_owner_blocks_services_before_any_artifact(self):
        rows = self.rows()
        rows[1]['claim_transport'] = True
        self.assertEqual(preflight_intakes(rows, self.paths)['status'], 'blocked')
        with self.assertRaisesRegex(IntakeError, 'More than one'):
            prepare_intakes(rows, self.paths)
        self.assert_no_artifacts()

    def test_double_owner_blocks_direct_cli_with_zero_artifacts(self):
        rows = self.rows()
        rows[1]['claim_transport'] = True
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(prepare_cli(self.cli_args(rows)), 2)
        self.assert_no_artifacts()

    def test_valid_shared_visit_direct_cli_retains_claim_metadata(self):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(prepare_cli(self.cli_args(self.rows()[:2])), 0)
        manifest = json.loads((self.paths.manifest_dir / 'cli.json').read_text(encoding='utf-8'))
        self.assertEqual([item['claim_transport'] for item in manifest['items']], [True, False])
        self.assertEqual(manifest['items'][0]['travel_group_binding'], manifest['items'][1]['travel_group_binding'])

    def test_same_city_date_ungrouped_requests_are_not_assumed_one_visit(self):
        rows = [self.row(101), self.row(102)]
        self.assertEqual(preflight_intakes(rows, self.paths)['status'], 'ready')
        self.assertEqual(len(prepare_intakes(rows, self.paths)['items']), 2)

    def test_explicit_group_of_one_is_allowed(self):
        self.assertEqual(preflight_intakes([self.rows()[0]], self.paths)['status'], 'ready')

    def test_conflicting_date_venue_destination_profile_or_origin_stops_shared_group(self):
        for field in ('service_date', 'service_place', 'personal_profile_id', 'destination', 'origin'):
            with self.subTest(field=field):
                rows = self.rows()[:2]
                if field in ('destination', 'origin'):
                    rows[1]['transport'][field] = 'Other Fictional City'
                else:
                    rows[1][field] = '2026-01-16' if field == 'service_date' else 'Other Fictional Value'
                with self.assertRaisesRegex(ClaimError, 'conflict'):
                    validate_shared_travel_groups(rows)

    def test_unclear_group_date_or_destination_or_profile_is_not_inferred(self):
        for field in ('service_date', 'personal_profile_id', 'destination'):
            with self.subTest(field=field):
                row = self.rows()[0]
                (row['transport'] if field == 'destination' else row).pop(field)
                with self.assertRaises(ClaimError):
                    validate_shared_travel_groups([row])

    def test_false_transport_numbered_answer_retains_group_itinerary(self):
        row = self.rows()[0]
        transport = copy.deepcopy(row['transport'])
        apply_answer_to_intake(row, 'claim_transport', 'no')
        self.assertEqual(row['transport'], transport)
        self.assertFalse(row['claim_transport'])

    def prior(self, row, status='drafted'):
        return {**{key: row[key] for key in ('case_number', 'service_date')}, **claim_metadata(row),
                'status': status, 'draft_id': 'fictional-old-draft', 'message_id': 'fictional-message'}

    def test_recorded_other_owner_blocks_sibling_but_retired_and_legacy_records_do_not_infer(self):
        first, second = self.rows()[:2]
        second['claim_transport'] = True
        for status in ('active', 'drafted', 'sent'):
            with self.subTest(status=status):
                self.write(self.paths.duplicate_index, [self.prior(first, status)])
                self.assertEqual(preflight_intakes([second], self.paths)['status'], 'blocked')
                with self.assertRaisesRegex(IntakeError, 'already recorded'):
                    prepare_intakes([second], self.paths)
        for status in ('superseded', 'trashed', 'not_found'):
            self.write(self.paths.duplicate_index, [self.prior(first, status)])
            self.assertEqual(preflight_intakes([second], self.paths)['status'], 'ready')
        self.write(self.paths.duplicate_index, [{'case_number': first['case_number'], 'service_date': first['service_date'], 'status': 'sent'}])
        self.assertEqual(preflight_intakes([second], self.paths)['status'], 'ready')
        self.assert_no_artifacts()

    def test_recorded_conflicting_group_binding_blocks_even_nonclaimant(self):
        first, second = self.rows()[:2]
        prior = self.prior(first)
        prior['travel_group_binding'][4] = 'other origin'
        self.write(self.paths.duplicate_index, [prior])
        self.assertEqual(preflight_intakes([second], self.paths)['status'], 'blocked')

    def test_prepared_unrecorded_owner_does_not_reserve_shared_trip_or_block_retry(self):
        first, second = self.rows()[:2]
        second['claim_transport'] = True
        prepare_intakes([first], self.paths)
        self.assertEqual(preflight_intakes([first], self.paths)['status'], 'ready')
        prepare_intakes([first], self.paths)
        self.assertEqual(preflight_intakes([second], self.paths)['status'], 'ready')

    def test_recording_retains_metadata_and_final_gmail_guard_blocks_prepared_sibling(self):
        first, second = self.rows()[:2]
        second['claim_transport'] = True
        result = prepare_intakes([first], self.paths)
        sibling = prepare_intakes([second], self.paths)
        payload_path = result['items'][0]['draft_payload']
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(record_cli(['--payload', payload_path, '--draft-id', 'fictional-draft', '--message-id', 'fictional-message',
                                         '--log', str(self.paths.draft_log), '--duplicate-index', str(self.paths.duplicate_index)]), 0)
        for path in (self.paths.draft_log, self.paths.duplicate_index):
            record = json.loads(path.read_text(encoding='utf-8'))[0]
            self.assertTrue(record['claim_transport'])
            self.assertEqual(record['travel_group_binding'], claim_metadata(first)['travel_group_binding'])
        payload = json.loads(Path(sibling['items'][0]['draft_payload']).read_text(encoding='utf-8'))
        with self.assertRaisesRegex(IntakeError, 'before contacting Gmail.*already recorded'):
            _assert_gmail_create_duplicate_clear(request_payload={}, draft_payload=payload, paths=self.paths)

    def test_direct_recording_conflicting_owner_is_rejected_without_log_mutation(self):
        first, second = self.rows()[:2]
        second['claim_transport'] = True
        result = prepare_intakes([second], self.paths)
        self.write(self.paths.draft_log, [self.prior(first, 'active')])
        before = self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = record_cli(['--payload', result['items'][0]['draft_payload'], '--draft-id', 'fictional-new', '--message-id', 'fictional-new-message',
                               '--log', str(self.paths.draft_log), '--duplicate-index', str(self.paths.duplicate_index)])
        self.assertEqual(code, 2)
        self.assertEqual((self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()), before)

    def test_duplicate_identity_is_unchanged_across_claim_modes(self):
        self.write(self.paths.duplicate_index, [self.prior(self.row(), 'sent')])
        for flags in ({'claim_interpreting': True, 'claim_transport': False}, {'claim_interpreting': False, 'claim_transport': True}):
            with self.subTest(flags=flags):
                self.assertEqual(review_intake(self.row(**flags), self.paths)['status'], 'duplicate')
                self.assertEqual(preflight_intakes([self.row(**flags)], self.paths)['status'], 'blocked')
        self.assert_no_artifacts()

    def test_packet_all_travel_only_uses_transport_wording_and_retains_each_identity_and_group(self):
        rows = [self.row(101, claim_interpreting=False), self.row(102, claim_interpreting=False)]
        for index, row in enumerate(rows):
            row['travel_group_id'] = f'fictional-separate-visit-{index}'
        result = prepare_intakes(rows, self.paths, packet_mode=True)
        payload = json.loads(Path(result['packet']['draft_payload']).read_text(encoding='utf-8'))
        self.assertNotIn('honorários', payload['body'])
        self.assertEqual(payload['subject'], 'Requerimento de despesas de transporte')
        self.assertEqual([request['claim_interpreting'] for request in payload['underlying_requests']], [False, False])
        self.assertEqual(len(recorded_travel_requests({'status': 'active', **payload} for _ in range(1))), 2)
        self.assertEqual(validate_draft_payload(payload), [])

    def test_mixed_packet_scope_is_independent_of_first_case_claim_mode(self):
        rows = [self.row(101, claim_interpreting=False), self.row(102, claim_transport=False)]
        result = prepare_intakes(rows, self.paths, packet_mode=True)
        payload = json.loads(Path(result['packet']['draft_payload']).read_text(encoding='utf-8'))
        self.assertIn('honorários e despesas de transporte', payload['body'])
        self.assertTrue(payload['claim_interpreting'])
        self.assertEqual([request['claim_interpreting'] for request in payload['underlying_requests']], [False, True])

    def test_conflicting_travel_only_packet_custom_body_blocks_before_files(self):
        rows = [self.row(101, claim_interpreting=False, packet_email_body='Requeiro honorários devidos.'),
                self.row(102, claim_interpreting=False)]
        self.assertEqual(preflight_intakes(rows, self.paths, packet_mode=True)['status'], 'blocked')
        with self.assertRaisesRegex(IntakeError, 'custom body'):
            prepare_intakes(rows, self.paths, packet_mode=True)
        self.assert_no_artifacts()

    def test_invalid_prepared_group_binding_fails_payload_validation(self):
        result = prepare_intakes([self.rows()[0]], self.paths)
        payload = json.loads(Path(result['items'][0]['draft_payload']).read_text(encoding='utf-8'))
        payload['travel_group_binding'][0] = '2026-01-16'
        self.assertTrue(any('date differs' in error for error in validate_draft_payload(payload)))

    def test_retiring_packet_without_reloading_payload_retires_all_group_claims(self):
        rows = self.rows()[:2]
        result = prepare_intakes(rows, self.paths, packet_mode=True)
        arguments = ['--draft-id', 'fictional-packet', '--message-id', 'fictional-message',
                     '--log', str(self.paths.draft_log), '--duplicate-index', str(self.paths.duplicate_index)]
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(record_cli(arguments + ['--payload', result['packet']['draft_payload']]), 0)
        record = json.loads(self.paths.draft_log.read_text(encoding='utf-8'))[0]
        self.assertEqual([child['claim_transport'] for child in record['underlying_requests']], [True, False])
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(record_cli(arguments + ['--case-number', record['case_number'], '--service-date', record['service_date'],
                                                   '--recipient', record['recipient'], '--pdf', record['pdf'], '--status', 'trashed']), 0)
        index = json.loads(self.paths.duplicate_index.read_text(encoding='utf-8'))
        self.assertEqual([child['status'] for child in index], ['trashed', 'trashed'])
        sibling = self.row(103, travel_group_id='fictional-explicit-visit')
        self.assertEqual(preflight_intakes([sibling], self.paths)['status'], 'ready')

    def test_recorded_owner_retry_keeps_normal_case_duplicate_guard(self):
        owner = self.rows()[0]
        self.write(self.paths.duplicate_index, [self.prior(owner, 'drafted')])
        validate_shared_travel_groups([owner], prior_requests=recorded_travel_requests([self.prior(owner)]))
        self.assertEqual(preflight_intakes([owner], self.paths)['status'], 'blocked')
        self.assertEqual(review_intake(owner, self.paths)['status'], 'duplicate')

    def court_row(self, number=101, venue='Tribunal de Vila Fictícia', **fields):
        return self.row(number, travel_group_id='fictional-explicit-visit',
                        service_place=venue, service_entity=venue, service_entity_type='court',
                        service_place_phrase=f'em diligência realizada no {venue}', **fields)

    def test_ordinary_local_court_names_match_only_for_shared_trip_comparison(self):
        names = (
            'Tribunal Judicial de Vila Fictícia',
            'Juízo de Competência Genérica de Vila Fictícia',
            'Tribunal Judicial da Comarca de Cidade Exemplo — Juízo de Competência Genérica de Vila Fictícia',
            'Tribunal Judicial da Comarca de Cidade Exemplo - Juízo de Competência Genérica de Vila Fictícia',
            'Tribunal Judicial da Comarca de Cidade Exemplo\nJuízo de Competência Genérica de Vila Fictícia',
        )
        current = self.court_row(claim_transport=True)
        for name in names:
            with self.subTest(name=name):
                original = self.court_row(venue=name, claim_transport=True)
                prior = self.prior(original)
                before = copy.deepcopy((current, prior))
                validate_shared_travel_groups([current], prior_requests=[prior])
                self.assertEqual((current, prior), before)
                self.assertEqual(prior['travel_group_binding'], claim_metadata(original)['travel_group_binding'])
                self.assertNotEqual(prior['travel_group_binding'][1], claim_metadata(current)['travel_group_binding'][1])

    def test_same_owner_short_court_correction_prepares_without_rewriting_history(self):
        formal = 'Tribunal Judicial da Comarca de Cidade Exemplo — Juízo de Competência Genérica de Vila Fictícia'
        old = [self.court_row(number, formal, claim_transport=number == 101) for number in (101, 102)]
        prior = [self.prior(row) for row in old]
        for path in (self.paths.draft_log, self.paths.duplicate_index):
            self.write(path, prior)
        before = self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()
        current = [self.court_row(number, claim_transport=number == 101) for number in (101, 102)]
        self.assertEqual(review_intake(current[0], self.paths)['status'], 'duplicate')
        self.assertEqual(preflight_intakes(current, self.paths)['status'], 'blocked')
        self.assert_no_artifacts()
        reason = 'Fictional court display-name correction; visit and travel owner unchanged.'
        self.assertEqual(preflight_intakes(current, self.paths, correction_reason=reason)['status'], 'ready')
        prepared = prepare_intakes(current, self.paths, correction_reason=reason)
        self.assertEqual(len(prepared['items']), 2)
        for row, item in zip(current, prepared['items']):
            payload = json.loads(Path(item['draft_payload']).read_text(encoding='utf-8'))
            self.assertEqual(payload['travel_group_binding'], claim_metadata(row)['travel_group_binding'])
            self.assertEqual(payload['claim_transport'], row['claim_transport'])
            self.assertTrue(item['correction_mode'])
            self.assertEqual(validate_draft_payload(payload), [])
        self.assertEqual((self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()), before)

    def test_equivalent_court_cannot_transfer_a_recorded_travel_claim_to_another_identity(self):
        owner = self.court_row(venue='Juízo de Competência Genérica de Vila Fictícia', claim_transport=True)
        prior = self.prior(owner)
        for current in (self.court_row(102, claim_transport=True),
                        self.court_row(claim_transport=True, service_period_label='manhã')):
            with self.subTest(identity=request_identity_key(current)):
                with self.assertRaisesRegex(ClaimError, 'already recorded on another request'):
                    validate_shared_travel_groups([current], prior_requests=[prior])

    def test_equivalent_court_cannot_hide_other_recorded_trip_fact_changes(self):
        old = self.court_row(venue='Juízo de Competência Genérica de Vila Fictícia', claim_transport=True)
        prior = self.prior(old)
        for field in ('service_date', 'service_place', 'personal_profile_id', 'destination', 'origin'):
            with self.subTest(field=field):
                current = self.court_row(claim_transport=True)
                if field in ('destination', 'origin'):
                    current['transport'][field] = 'Other Fictional City'
                else:
                    current[field] = {'service_date': '2026-01-16',
                                      'service_place': 'Tribunal de Outra Vila',
                                      'personal_profile_id': 'fictional-other-profile'}[field]
                with self.assertRaisesRegex(ClaimError, 'conflicting or unclear'):
                    validate_shared_travel_groups([current], prior_requests=[prior])

    def test_specialised_unknown_station_or_comarca_only_names_remain_distinct(self):
        for name in (
            'Tribunal do Trabalho de Vila Fictícia',
            'Tribunal de Família e Menores de Vila Fictícia',
            'Tribunal de Vila Fictícia — Juízo do Trabalho',
            'Juízo Local Criminal de Vila Fictícia',
            'Tribunal Judicial da Comarca de Vila Fictícia',
            'Posto da GNR de Vila Fictícia',
            'Unknown Fictional Hall',
            'Tribunal de Vila Fictícia e Outra Vila',
            'Tribunal de Vila Fictícia, Edifício Anexo',
        ):
            with self.subTest(name=name):
                original = self.court_row(venue=name, claim_transport=True)
                prior = self.prior(original)
                validate_shared_travel_groups([original], prior_requests=[prior])
                with self.assertRaisesRegex(ClaimError, 'conflicting or unclear'):
                    validate_shared_travel_groups([self.court_row(claim_transport=True)], prior_requests=[prior])

    def test_equivalent_current_court_spellings_still_allow_only_one_travel_owner(self):
        rows = [self.court_row(claim_transport=True),
                self.court_row(102, venue='Juízo de Competência Genérica de Vila Fictícia', claim_transport=False)]
        before = copy.deepcopy(rows)
        validate_shared_travel_groups(rows)
        self.assertEqual(rows, before)
        rows[1]['claim_transport'] = True
        with self.assertRaisesRegex(ClaimError, 'More than one request'):
            validate_shared_travel_groups(rows)

    def test_malformed_recorded_binding_stops_actionably_without_type_errors(self):
        first, sibling = self.rows()[:2]
        for index, value in ((4, []), (2, 123), (0, ''), (1, ' '), (2, ''), (3, '')):
            with self.subTest(index=index, value=value):
                prior = self.prior(first)
                prior['travel_group_binding'][index] = value
                with self.assertRaisesRegex(ClaimError, 'conflicting or unclear'):
                    validate_shared_travel_groups([sibling], prior_requests=[prior])
                self.write(self.paths.duplicate_index, [prior])
                self.assertEqual(preflight_intakes([sibling], self.paths)['status'], 'blocked')
                self.assert_no_artifacts()

    def test_travel_only_missing_and_conflicting_date_questions_ask_attendance_date(self):
        missing = self.row(claim_interpreting=False)
        missing.pop('service_date')
        question = next(question for question in missing_questions(missing) if question['field'] == 'service_date')
        self.assertIn('attend in person', question['question'])
        self.assertIn('attendance date', question['answer_hint'])
        self.assertNotIn('provide', question['question'])
        conflicting = self.row(claim_interpreting=False, service_date_source='document_text', photo_metadata_date='2026-01-16')
        question = next(question for question in missing_questions(conflicting) if question['field'] == 'service_date_source')
        self.assertIn('2026-01-15', question['question'])
        self.assertIn('2026-01-16', question['question'])
        self.assertIn('attend in person', question['question'])
        self.assertNotIn('provide', question['question'])


if __name__ == '__main__':
    unittest.main()
