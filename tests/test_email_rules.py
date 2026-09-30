"""Draft-only, recipient, attachment and duplicate-record rules; no providers."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main()
