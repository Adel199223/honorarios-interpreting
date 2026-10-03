"""Draft-only, recipient, attachment and duplicate-record rules; no providers."""
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

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import AppPaths, build_profile_intake, preflight_intakes, prepare_intakes, review_intake, require_current_preflight_review
from honorarios_app.gmail_draft_api import build_mime_message
from scripts.build_email_draft import build_email_payload, resolve_recipient, resolve_email_subject, validate_draft_payload
from scripts.generate_pdf import IntakeError, find_duplicate_record
from scripts.record_gmail_draft import main as record_draft


class EmailRulesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-email-rules-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pdf = self.root / 'synthetic-request.pdf'
        self.pdf.write_bytes(b'%PDF-1.4\n% fictional attachment fixture\n')
        self.intake = {'case_number': '100/26.0TSTXX', 'service_date': '2026-01-15', 'payment_entity': 'Example Court', 'court_email_key': 'example-court'}
        self.config = {'default_to': 'court@example.test', 'subject': 'Synthetic fee request', 'body': 'Synthetic request attached.'}
        self.directory = [{'key': 'example-court', 'email': 'court@example.test', 'payment_entity_aliases': ['Example Court']}]

    def test_payment_entity_controls_recipient_instead_of_physical_service_place(self):
        self.intake['service_place'] = 'Example Police Station'
        self.assertEqual(resolve_recipient(self.intake, self.config, self.directory), ('court@example.test', 'court_email_key'))

    def test_custom_subject_and_message_are_exact_in_payload_and_mime(self):
        intake = {**self.intake, 'email_subject': 'Requerimento de Honorários',
                  'email_body': '  Bom dia,\n\nRetificação da data; não é um novo pedido.\nAssinatura fictícia\n'}
        before = copy.deepcopy(self.config)
        payload = build_email_payload(intake, self.pdf, self.config, self.directory)
        self.assertEqual(payload['subject'], intake['email_subject'])
        self.assertEqual(payload['body'], intake['email_body'])
        message = build_mime_message(payload['gmail_create_draft_args'])
        self.assertEqual(str(message['Subject']), intake['email_subject'])
        self.assertEqual(message.get_body().get_content(), intake['email_body'])
        self.assertEqual(self.config, before)
        self.assertEqual(validate_draft_payload(payload), [])

    def test_subject_rejects_header_injection_at_build_payload_and_mime_boundaries(self):
        for value in ['ok\r\nBcc: other@example.test', '\n', 'ok\tbad', 'ok\x00bad', 'ok\x7fbad',
                      'ok\u2028bad', 'x' * 2049, {'bad': 'type'}]:
            with self.subTest(value=repr(value)):
                with self.assertRaises(IntakeError):
                    build_email_payload({**self.intake, 'email_subject': value}, self.pdf, self.config, self.directory)
                payload = build_email_payload(self.intake, self.pdf, self.config, self.directory)
                payload['gmail_create_draft_args']['subject'] = value
                self.assertTrue(validate_draft_payload(payload))
                with self.assertRaises(IntakeError):
                    build_mime_message(payload['gmail_create_draft_args'])

    def test_blank_fields_use_defaults_and_travel_only_subject_cannot_claim_fees(self):
        payload = build_email_payload({**self.intake, 'email_subject': '   ', 'email_body': '  \n'}, self.pdf, self.config, self.directory)
        self.assertEqual((payload['subject'], payload['body']), (self.config['subject'], self.config['body']))
        travel = {**self.intake, 'claim_interpreting': False, 'claim_transport': True}
        self.assertEqual(resolve_email_subject(travel, self.config), 'Requerimento de despesas de transporte')
        self.assertEqual(resolve_email_subject({**travel, 'email_subject': 'Retificação das despesas de transporte'}, self.config), 'Retificação das despesas de transporte')
        with self.assertRaisesRegex(IntakeError, 'Travel-only'):
            resolve_email_subject({**travel, 'email_subject': 'Requerimento de Honorários'}, self.config)

    def test_unknown_recipient_key_does_not_fall_back(self):
        self.intake['court_email_key'] = 'missing-court'
        with self.assertRaisesRegex(IntakeError, 'Unknown court_email_key'):
            resolve_recipient(self.intake, self.config, self.directory)

    def test_mapped_recipient_mismatch_requires_auditable_override_reason(self):
        # Fictional local-only addresses use the validator's required court domain.
        domain = 'tribunais' + '.org.pt'
        expected, other = 'synthetic-a@' + domain, 'synthetic-b@' + domain
        directory = [{'key': 'example-court', 'email': expected, 'payment_entity_aliases': ['Example Court']}]
        intake = {**self.intake, 'recipient_email': other}
        with self.assertRaisesRegex(IntakeError, 'Recipient does not match the payment entity'):
            resolve_recipient(intake, self.config, directory)
        intake['recipient_override_reason'] = 'Synthetic confirmed exceptional recipient.'
        self.assertEqual(resolve_recipient(intake, self.config, directory), (other, 'recipient_email'))

    def test_payload_is_draft_only_with_absolute_attachment_array_and_hash(self):
        payload = build_email_payload(self.intake, self.pdf, self.config, self.directory)
        self.assertEqual(validate_draft_payload(payload), [])
        self.assertFalse(payload['send_allowed'])
        self.assertTrue(payload['draft_only'])
        self.assertEqual(payload['gmail_tool'], '_create_draft')
        self.assertEqual(payload['attachment_files'], [str(self.pdf.resolve())])
        self.assertEqual(payload['attachment_sha256'][str(self.pdf.resolve())], payload['pdf_sha256'])

    def test_send_capability_and_mismatched_attachment_args_are_rejected(self):
        original = build_email_payload(self.intake, self.pdf, self.config, self.directory)
        payload = copy.deepcopy(original)
        payload.update(send_allowed=True, gmail_tool='_send_email', draft_only=False)
        payload['gmail_create_draft_args']['attachment_files'] = []
        errors = '\n'.join(validate_draft_payload(payload))
        self.assertIn('send_allowed must be false', errors)
        self.assertIn('gmail_tool must be _create_draft', errors)
        self.assertIn('draft_only must be true', errors)
        self.assertIn('must match attachment_files', errors)

    def test_supporting_proof_requires_custom_body_and_remains_an_array(self):
        proof = self.root / 'proof.pdf'
        proof.write_bytes(b'%PDF-1.4\n% fictional proof\n')
        intake = {**self.intake, 'additional_attachment_files': [str(proof)]}
        blocked = build_email_payload(intake, self.pdf, self.config, self.directory)
        self.assertFalse(blocked['gmail_create_draft_ready'])
        self.assertTrue(validate_draft_payload(blocked))
        intake['email_body'] = 'Requerimento e documento comprovativo anexos.'
        ready = build_email_payload(intake, self.pdf, self.config, self.directory)
        self.assertEqual(validate_draft_payload(ready), [])
        self.assertEqual(ready['gmail_create_draft_args']['attachment_files'], [str(self.pdf.resolve()), str(proof.resolve())])

    def test_recording_packet_immediately_blocks_each_underlying_request(self):
        requests = [{**self.intake, 'service_period_label': 'manhã'},
                    {**self.intake, 'case_number': '101/26.0TSTXX', 'service_period_label': 'tarde'}]
        payload = build_email_payload({**self.intake, 'underlying_requests': requests}, self.pdf, self.config, self.directory)
        path = self.root / 'draft.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        log, index = self.root / 'draft-log.json', self.root / 'duplicates.json'
        args = ['--payload', str(path), '--log', str(log), '--duplicate-index', str(index),
                '--draft-id', 'synthetic-draft', '--message-id', 'synthetic-message', '--thread-id', 'synthetic-thread']
        with redirect_stdout(StringIO()):
            self.assertEqual(record_draft(args), 0)
            self.assertEqual(record_draft(args), 0)
        self.assertEqual(len(json.loads(log.read_text(encoding='utf-8'))), 1)
        self.assertEqual(len(json.loads(index.read_text(encoding='utf-8'))), 2)
        for intake in requests:
            with self.subTest(case=intake['case_number']):
                record = find_duplicate_record(intake, index, strict=True)
                self.assertEqual(record['status'], 'drafted')
                self.assertEqual(record['draft_id'], 'synthetic-draft')


class SelectedSignatureEmailTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-selected-signature-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        store = json.loads(self.paths.personal_profiles.read_text(encoding='utf-8'))
        selected = copy.deepcopy(store['profiles'][0])
        selected.update(id='selected', first_name='Pessoa', last_name='Fictícia A',
                        document_name_override='Pessoa Fictícia A')
        store['profiles'].append(selected)
        self.paths.personal_profiles.write_text(json.dumps(store), encoding='utf-8')
        defaults = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))['example_interpreting']['defaults']
        self.intake = {**defaults, 'case_number': '710/26.0TSTXX', 'service_date': '2026-09-26',
                       'closing_date': '2026-09-30', 'personal_profile_id': 'selected'}

    def payload(self, item):
        return json.loads(Path(item['draft_payload']).read_text(encoding='utf-8'))

    def test_profile_inputs_and_review_preserve_email_text_and_edits_stale_preflight(self):
        custom = {'email_subject': 'Requerimento de Honorários', 'email_body': 'Texto individual.\nAssinatura fictícia\n'}
        intake = build_profile_intake({'profile': 'example_interpreting', **self.intake, **custom}, self.paths)
        for key, value in custom.items():
            self.assertEqual(intake[key], value)
        self.assertEqual(review_intake(intake, self.paths)['status'], 'ready')
        preflight = preflight_intakes([intake], self.paths)
        self.assertEqual(preflight['status'], 'ready')
        for field in custom:
            with self.subTest(field=field):
                changed = {**intake, field: 'Changed fictional wording'}
                with self.assertRaisesRegex(IntakeError, 'stale'):
                    require_current_preflight_review({'preflight_review': preflight['preflight_review']}, [changed], self.paths,
                                                    packet_mode=False, email_grouping='individual')
        bad = {**intake, 'email_subject': 'bad\nBcc: other@example.test'}
        self.assertEqual(review_intake(bad, self.paths)['status'], 'error')
        self.assertEqual(preflight_intakes([bad], self.paths)['status'], 'blocked')
        self.assertFalse(self.paths.output_dir.exists() and any(self.paths.output_dir.iterdir()))

    def test_default_email_and_actual_pdf_share_selected_signature(self):
        before = self.paths.email_config.read_bytes()
        prepared = prepare_intakes([self.intake], self.paths)
        item = prepared['items'][0]
        payload = self.payload(item)
        text = '\n'.join(page.extract_text() for page in PdfReader(item['pdf']).pages)
        self.assertIn('Pessoa Fictícia A', text)
        self.assertTrue(payload['body'].endswith('Pessoa Fictícia A'))
        self.assertNotIn('Example Interpreter', payload['body'])
        self.assertNotIn('{{signature_name}}', payload['body'])
        self.assertEqual(payload['gmail_create_draft_args']['body'], payload['body'])
        self.assertEqual(validate_draft_payload(payload), [])
        self.assertFalse(payload['send_allowed'])
        self.assertEqual(self.paths.email_config.read_bytes(), before)

    def test_explicit_configured_and_request_bodies_remain_verbatim(self):
        configured = '  Texto explicitamente configurado.\nMelhores cumprimentos,\nAssinatura da Equipa\n'
        config = json.loads(self.paths.email_config.read_text(encoding='utf-8'))
        config['body'] = configured
        self.paths.email_config.write_text(json.dumps(config), encoding='utf-8')
        before = self.paths.email_config.read_bytes()
        prepared = prepare_intakes([self.intake], self.paths)
        self.assertEqual(self.payload(prepared['items'][0])['body'], configured)
        custom = '  Corpo individual e assinatura explícita.\nOutra Pessoa\n'
        prepared = prepare_intakes([{**self.intake, 'case_number': '711/26.0TSTXX', 'email_body': custom}], self.paths)
        self.assertEqual(self.payload(prepared['items'][0])['body'], custom)
        self.assertEqual(self.paths.email_config.read_bytes(), before)

    def test_packet_default_uses_selected_signature_and_custom_packet_stays_verbatim(self):
        intakes = [self.intake, {**self.intake, 'case_number': '711/26.0TSTXX'}]
        prepared = prepare_intakes(intakes, self.paths, packet_mode=True)
        packet = self.payload(prepared['packet'])
        self.assertTrue(packet['body'].endswith('Pessoa Fictícia A'))
        self.assertEqual(len(packet['underlying_requests']), 2)
        self.assertEqual(validate_draft_payload(packet), [])
        self.assertFalse(packet['send_allowed'])
        custom = '  Pacote com assinatura escolhida.\nAssinatura da Equipa\n'
        intakes[0] = {**self.intake, 'case_number': '712/26.0TSTXX', 'packet_email_body': custom}
        intakes[1]['case_number'] = '713/26.0TSTXX'
        prepared = prepare_intakes(intakes, self.paths, packet_mode=True)
        self.assertEqual(self.payload(prepared['packet'])['body'], custom)


class RemovedDraftWarningTests(unittest.TestCase):
    setUp = EmailRulesTests.setUp

    def args(self, *, children=None, name='original'):
        intake = {**self.intake}
        if children:
            intake['underlying_requests'] = children
        payload = build_email_payload(intake, self.pdf, self.config, self.directory)
        path = self.root / f'{name}.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        return ['--payload', str(path), '--log', str(self.root / 'log.json'),
                '--duplicate-index', str(self.root / 'index.json'), '--draft-id', 'fictional-' + name,
                '--message-id', 'fictional-message-' + name, '--thread-id', 'fictional-thread-' + name]

    def run_record(self, args, expected=0):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as errors:
            code = record_draft(args)
        self.assertEqual(code, expected, errors.getvalue())
        return errors.getvalue()

    def rows(self, name):
        return json.loads((self.root / name).read_text(encoding='utf-8'))

    def test_removed_lifecycle_keeps_prior_creation_fact_without_sent_claim(self):
        for status in ('archived', 'trashed', 'not_found'):
            with self.subTest(status=status):
                args = self.args(name=status)
                # Each subcase has a separate request identity/history.
                for filename in ('log.json', 'index.json'):
                    (self.root / filename).write_text('[]', encoding='utf-8')
                self.run_record(args)
                original = self.rows('log.json')[0]
                history = self.rows('index.json')
                drafted_at = history[0]['drafted_at']
                history[0]['private_evidence'] = {'preserved': True}
                (self.root / 'index.json').write_text(json.dumps(history), encoding='utf-8')
                self.run_record([*args, '--status', status])
                log, index = self.rows('log.json')[0], self.rows('index.json')[0]
                self.assertEqual(log['status'], status)
                self.assertTrue(log['duplicate_warning_retained'])
                self.assertEqual(index['status'], 'drafted')
                self.assertEqual(index['draft_lifecycle_status'], status)
                self.assertTrue(index['duplicate_warning_retained'])
                self.assertEqual(index['drafted_at'], drafted_at)
                self.assertEqual(log['draft_lifecycle_status'], status)
                self.assertEqual(index['private_evidence'], {'preserved': True})
                for field in ('draft_id', 'message_id', 'thread_id', 'pdf', 'pdf_sha256', 'created_at', 'draft_payload_sha256'):
                    self.assertEqual(log[field], original[field])
                self.assertFalse(log.get('sent_date'))
                self.assertNotIn('sent_date', index)
                self.assertIsNotNone(find_duplicate_record(self.intake, self.root / 'index.json'))

    def test_packet_removal_without_original_payload_protects_every_child_and_period(self):
        children = [{**self.intake, 'service_period_label': 'morning'},
                    {**self.intake, 'case_number': '101/26.0TSTXX', 'service_period_label': 'afternoon'}]
        args = self.args(children=children)
        self.run_record(args)
        (self.root / 'original.json').unlink()
        self.run_record([*args[2:], '--case-number', self.intake['case_number'],
                         '--service-date', self.intake['service_date'], '--pdf', str(self.pdf),
                         '--recipient', 'court@example.test', '--status', 'archived'])
        self.assertEqual(len(self.rows('index.json')), 2)
        for child in children:
            duplicate = find_duplicate_record(child, self.root / 'index.json')
            self.assertEqual(duplicate['status'], 'drafted')
            self.assertEqual(duplicate['draft_lifecycle_status'], 'archived')
        self.assertIsNone(find_duplicate_record({**children[0], 'service_period_label': 'afternoon'}, self.root / 'index.json'))
        self.assertIsNone(find_duplicate_record({**children[0], 'service_date': '2026-01-16'}, self.root / 'index.json'))
        self.assertIsNotNone(find_duplicate_record({**children[0], 'case_number': '000100/26.0tstxx', 'service_period_label': ''}, self.root / 'index.json'))

    def test_unknown_archive_and_sent_retirement_are_rejected(self):
        args = self.args()
        self.assertIn('existing recorded unsent draft', self.run_record([*args, '--status', 'archived'], 2))
        self.assertFalse((self.root / 'log.json').exists())
        self.run_record(args)
        self.run_record([*args, '--status', 'sent', '--sent-date', '2026-01-16'])
        before = {name: (self.root / name).read_bytes() for name in ('log.json', 'index.json')}
        for status in ('archived', 'trashed', 'not_found', 'superseded'):
            with self.subTest(status=status):
                self.run_record([*args, '--status', status], 2)
                self.assertEqual({name: (self.root / name).read_bytes() for name in before}, before)

    def test_unrelated_historical_cleared_rows_are_not_migrated(self):
        historical = {**self.intake, 'case_number': '199/26.0TSTXX', 'draft_id': 'fictional-historical', 'status': 'trashed'}
        (self.root / 'index.json').write_text(json.dumps([historical]), encoding='utf-8')
        args = self.args()
        self.run_record(args)
        self.run_record([*args, '--status', 'archived'])
        self.assertEqual(self.rows('index.json')[0], historical)
        self.assertIsNone(find_duplicate_record(historical, self.root / 'index.json'))

    def test_accidental_recreation_blocks_but_complete_reasoned_replacement_works(self):
        args = self.args()
        self.run_record(args)
        self.run_record([*args, '--status', 'archived'])
        replacement = self.args(name='replacement')
        self.assertIn('correction mode', self.run_record(replacement, 2))
        correction = [*replacement, '--supersedes', 'fictional-original', '--notes', 'Intentional fictional replacement.']
        self.run_record(correction)
        self.run_record([*args, '--status', 'superseded', '--superseded-by', 'fictional-replacement'])
        original = next(row for row in self.rows('index.json') if row['draft_id'] == 'fictional-original')
        self.assertEqual(original['status'], 'superseded')
        self.assertFalse(original['duplicate_warning_retained'])
        self.assertEqual(original['draft_lifecycle_status'], 'superseded')
        self.assertEqual(find_duplicate_record(self.intake, self.root / 'index.json')['draft_id'], 'fictional-replacement')
        self.run_record([*args, '--status', 'trashed'])
        self.run_record(correction)
        original = next(row for row in self.rows('index.json') if row['draft_id'] == 'fictional-original')
        self.assertEqual(original['status'], 'trashed')
        self.assertFalse(original['duplicate_warning_retained'])
        self.assertEqual(find_duplicate_record(self.intake, self.root / 'index.json')['draft_id'], 'fictional-replacement')

    def test_superseded_label_without_complete_recorded_replacement_keeps_warning(self):
        children = [self.intake, {**self.intake, 'case_number': '101/26.0TSTXX'}]
        args = self.args(children=children)
        self.run_record(args)
        self.run_record([*args, '--status', 'superseded', '--superseded-by', 'fictional-missing'])
        for child in children:
            duplicate = find_duplicate_record(child, self.root / 'index.json')
            self.assertEqual(duplicate['status'], 'drafted')
            self.assertEqual(duplicate['draft_lifecycle_status'], 'superseded')
        self.run_record([*args, '--status', 'trashed'])
        self.assertTrue(all(row['duplicate_warning_retained'] for row in self.rows('index.json')))
        self.run_record(args, 2)

    def test_incomplete_replacement_index_cannot_release_any_packet_child(self):
        children = [self.intake, {**self.intake, 'case_number': '101/26.0TSTXX'}]
        args = self.args(children=children)
        self.run_record(args)
        replacement = self.args(children=children, name='replacement')
        self.run_record([*replacement, '--supersedes', 'fictional-original', '--notes', 'Complete fictional replacement.'])
        index = self.rows('index.json')
        index = [row for row in index if not (row['draft_id'] == 'fictional-replacement' and row['case_number'] == children[-1]['case_number'])]
        (self.root / 'index.json').write_text(json.dumps(index), encoding='utf-8')
        self.run_record([*args, '--status', 'superseded', '--superseded-by', 'fictional-replacement'])
        original = [row for row in self.rows('index.json') if row['draft_id'] == 'fictional-original']
        self.assertEqual(len(original), 2)
        self.assertTrue(all(row['status'] == 'drafted' and row['duplicate_warning_retained'] for row in original))

    def test_missing_log_after_creation_failure_still_blocks_another_draft(self):
        args = self.args()
        with patch('scripts.record_gmail_draft.write_log', side_effect=OSError('Fictional disk failure')):
            self.run_record(args, 2)
        self.assertFalse((self.root / 'log.json').exists())
        self.assertIsNotNone(find_duplicate_record(self.intake, self.root / 'index.json'))
        self.run_record(self.args(name='accidental'), 2)
        self.run_record(args)
        self.assertEqual(self.rows('log.json')[0]['status'], 'active')

    def test_failed_history_write_leaves_index_protected_and_retry_finishes(self):
        args = self.args()
        self.run_record(args)
        before = (self.root / 'log.json').read_bytes()
        with patch('scripts.record_gmail_draft.write_log', side_effect=OSError('Fictional disk failure')):
            self.run_record([*args, '--status', 'archived'], 2)
        self.assertEqual((self.root / 'log.json').read_bytes(), before)
        self.assertEqual(find_duplicate_record(self.intake, self.root / 'index.json')['status'], 'drafted')
        self.run_record([*args, '--status', 'archived'])
        self.assertEqual(self.rows('log.json')[0]['status'], 'archived')

    def test_failed_index_write_does_not_change_draft_history(self):
        args = self.args()
        self.run_record(args)
        before = {name: (self.root / name).read_bytes() for name in ('log.json', 'index.json')}
        with patch('scripts.record_gmail_draft.write_duplicate_index', side_effect=OSError('Fictional disk failure')):
            self.run_record([*args, '--status', 'archived'], 2)
        self.assertEqual({name: (self.root / name).read_bytes() for name in before}, before)


if __name__ == '__main__':
    unittest.main()
