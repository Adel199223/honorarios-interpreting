"""Draft-only, recipient, attachment and duplicate-record rules; no providers."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from pypdf import PdfReader

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import AppPaths, prepare_intakes
from scripts.build_email_draft import build_email_payload, resolve_recipient, validate_draft_payload
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


if __name__ == '__main__':
    unittest.main()
