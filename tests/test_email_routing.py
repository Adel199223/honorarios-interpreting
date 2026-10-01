"""Fictional saved-contact routing regressions; no private data or providers."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import AppPaths, preflight_intakes, prepare_intakes, review_intake
from scripts.build_email_draft import expected_email_for_payment_entity, resolve_recipient, validate_draft_payload
from scripts.generate_pdf import IntakeError

ROOT = Path(__file__).resolve().parents[1]
COURT_DOMAIN = 'tribunais' + '.org.pt'
REGIONAL_EMAIL = 'fictional-region@' + COURT_DOMAIN
LOCAL_EMAIL = 'fictional-local@' + COURT_DOMAIN
OTHER_EMAIL = 'fictional-other@' + COURT_DOMAIN
PAYER = 'Tribunal Judicial da Comarca de Cidade Fictícia - Juízo Local Criminal de Vila Fictícia'


class EmailRoutingTests(unittest.TestCase):
    def setUp(self):
        self.directory = [
            {'key': 'fictional-region', 'name': 'Tribunal Judicial da Comarca de Cidade Fictícia',
             'email': REGIONAL_EMAIL, 'payment_entity_aliases': ['Tribunal Judicial da Comarca de Cidade Fictícia']},
            {'key': 'fictional-local', 'name': PAYER, 'email': LOCAL_EMAIL,
             'payment_entity_aliases': [PAYER, 'Juízo Local Criminal de Vila Fictícia']},
            {'key': 'fictional-other', 'name': 'Tribunal de Outra Cidade', 'email': OTHER_EMAIL,
             'payment_entity_aliases': ['Tribunal de Outra Cidade']},
        ]
        self.config = {'default_to': REGIONAL_EMAIL, 'body': 'Fictional attachment.', 'subject': 'Fictional request'}
        self.intake = {'payment_entity': PAYER, 'service_place': 'Esquadra da PSP de Outro Local'}
        guard = patch('socket.socket.connect', side_effect=AssertionError('Synthetic routing tests forbid network calls'))
        guard.start()
        self.addCleanup(guard.stop)

    def resolve(self, **fields):
        return resolve_recipient({**self.intake, **fields}, self.config, self.directory)

    def test_exact_local_alias_beats_first_broad_comarca_and_is_order_independent(self):
        for directory in (self.directory, list(reversed(self.directory))):
            self.assertEqual(expected_email_for_payment_entity(self.intake, directory), LOCAL_EMAIL)
            self.assertEqual(resolve_recipient(self.intake, self.config, directory), (LOCAL_EMAIL, 'payment_entity_directory'))

    def test_most_specific_local_alias_wins_inside_titled_addressee(self):
        intake = {'addressee': 'Exmo. Senhor Procurador da República\n' + PAYER + '\nSecretaria',
                  'service_place': 'Tribunal de Outra Cidade'}
        self.assertEqual(resolve_recipient(intake, self.config, self.directory), (LOCAL_EMAIL, 'payment_entity_directory'))

    def test_alias_matching_preserves_word_boundaries(self):
        directory = [{'key': 'one', 'email': LOCAL_EMAIL, 'payment_entity_aliases': ['Tribunal de Vila']}]
        self.assertIsNone(expected_email_for_payment_entity({'payment_entity': 'Tribunal de Vilafranca'}, directory))

    def test_case_accents_and_generic_title_do_not_change_exact_payer(self):
        self.assertEqual(self.resolve(payment_entity='EXMO. SENHOR ' + PAYER.upper()), (LOCAL_EMAIL, 'payment_entity_directory'))

    def test_explicit_email_precedes_single_unrelated_footer(self):
        self.assertEqual(self.resolve(recipient_email=LOCAL_EMAIL, source_text='Contacto: ' + OTHER_EMAIL),
                         (LOCAL_EMAIL, 'recipient_email'))

    def test_explicit_email_and_saved_key_each_resolve_multiple_footer_contacts(self):
        footer = 'Contactos de rodapé: ' + REGIONAL_EMAIL + ' / ' + OTHER_EMAIL
        self.assertEqual(self.resolve(recipient_email=LOCAL_EMAIL, source_text=footer), (LOCAL_EMAIL, 'recipient_email'))
        self.assertEqual(self.resolve(court_email_key='fictional-local', source_text=footer), (LOCAL_EMAIL, 'court_email_key'))

    def test_selected_key_does_not_define_its_own_expected_payer(self):
        with self.assertRaisesRegex(IntakeError, 'Recipient does not match the payment entity'):
            self.resolve(court_email_key='fictional-region')
        self.assertEqual(self.resolve(court_email_key='fictional-region', recipient_override_reason='Fictional exceptional payment office confirmed.'),
                         (REGIONAL_EMAIL, 'court_email_key'))

    def test_selected_key_still_requires_payer_agreement_when_explicit_email_is_present(self):
        with self.assertRaisesRegex(IntakeError, 'Recipient does not match the payment entity'):
            self.resolve(recipient_email=LOCAL_EMAIL, court_email_key='fictional-other')

    def test_explicit_recipient_mismatch_does_not_get_hidden_by_correct_key_or_footer(self):
        with self.assertRaisesRegex(IntakeError, 'Recipient does not match the payment entity'):
            self.resolve(recipient_email=OTHER_EMAIL, court_email_key='fictional-local', source_text=LOCAL_EMAIL)
        self.assertEqual(self.resolve(recipient_email=OTHER_EMAIL, court_email_key='fictional-local',
                                      court_email_override_reason='Fictional confirmed alternate payment office.'),
                         (OTHER_EMAIL, 'recipient_email'))

    def test_two_unknown_payer_explicit_contacts_must_be_reconciled(self):
        with self.assertRaisesRegex(IntakeError, 'Explicit recipient fields.*disagree'):
            self.resolve(payment_entity='Unknown Fictional Court', recipient_email=LOCAL_EMAIL, court_email=OTHER_EMAIL)

    def test_unknown_selected_key_cannot_silently_use_footer_or_default(self):
        with self.assertRaisesRegex(IntakeError, 'Unknown court_email_key'):
            self.resolve(court_email_key='missing', source_text=LOCAL_EMAIL)

    def test_conflicting_duplicate_saved_key_pauses_instead_of_first_record_winning(self):
        directory = self.directory + [{**self.directory[1], 'email': OTHER_EMAIL}]
        with self.assertRaisesRegex(IntakeError, 'conflicting or missing saved emails'):
            resolve_recipient({**self.intake, 'court_email_key': 'fictional-local'}, self.config, directory)

    def test_tied_payer_aliases_pause_even_when_contact_key_is_selected(self):
        directory = self.directory + [{'key': 'fictional-conflict', 'email': OTHER_EMAIL, 'payment_entity_aliases': [PAYER]}]
        for fields in ({}, {'court_email_key': 'fictional-local'}, {'recipient_email': LOCAL_EMAIL}):
            with self.subTest(fields=fields), self.assertRaisesRegex(IntakeError, 'paying court matches conflicting'):
                resolve_recipient({**self.intake, **fields}, self.config, directory)
        intake = {**self.intake, 'court_email_key': 'fictional-local',
                  'recipient_override_reason': 'Fictional local office confirmed despite duplicate contact entry.'}
        self.assertEqual(resolve_recipient(intake, self.config, directory), (LOCAL_EMAIL, 'court_email_key'))

    def test_duplicate_aliases_with_same_email_are_not_a_false_conflict(self):
        directory = self.directory + [{**self.directory[1], 'key': 'same-local-email'}]
        self.assertEqual(resolve_recipient(self.intake, self.config, directory), (LOCAL_EMAIL, 'payment_entity_directory'))

    def test_multiple_source_contacts_without_explicit_selection_still_ask(self):
        with self.assertRaisesRegex(IntakeError, 'Multiple court emails'):
            self.resolve(source_text=LOCAL_EMAIL + ' ' + OTHER_EMAIL)

    def test_single_source_contact_is_validated_against_independent_payer(self):
        self.assertEqual(self.resolve(source_text='Contacto: ' + LOCAL_EMAIL), (LOCAL_EMAIL, 'source_text'))
        with self.assertRaisesRegex(IntakeError, 'Recipient does not match the payment entity'):
            self.resolve(source_text='Contacto: ' + OTHER_EMAIL)

    def test_unknown_payer_can_still_use_legacy_generic_default(self):
        self.assertEqual(self.resolve(payment_entity='Unknown Fictional Court'), (REGIONAL_EMAIL, 'default_to'))

    def test_photo_cleared_recipient_does_not_resurrect_alias_source_or_default(self):
        intake = {**self.intake, 'recipient_email': '', 'court_email': '', 'court_email_key': '',
                  'photo_defaults_applied': {'routing_status': 'missing'}, 'source_text': LOCAL_EMAIL}
        before = copy.deepcopy(intake)
        with self.assertRaisesRegex(IntakeError, 'photo-city court recipient is missing'):
            resolve_recipient(intake, self.config, self.directory)
        self.assertEqual(intake, before)

    def test_explicit_photo_contact_still_validates_independent_payer(self):
        policy = {'routing_status': 'manual'}
        self.assertEqual(self.resolve(photo_defaults_applied=policy, court_email_key='fictional-local'),
                         (LOCAL_EMAIL, 'court_email_key'))
        with self.assertRaisesRegex(IntakeError, 'Recipient does not match the payment entity'):
            self.resolve(photo_defaults_applied=policy, court_email_key='fictional-other')


class EmailRoutingWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fictional-contact-routing-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        self.directory = [
            {'key': 'fictional-region', 'email': REGIONAL_EMAIL,
             'payment_entity_aliases': ['Tribunal Judicial da Comarca de Cidade Fictícia']},
            {'key': 'fictional-local', 'email': LOCAL_EMAIL, 'payment_entity_aliases': [PAYER]},
        ]
        self.paths.court_emails.write_text(json.dumps(self.directory), encoding='utf-8')
        self.intake = json.loads((ROOT / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        self.intake.pop('recipient_email')
        self.intake.update(payment_entity=PAYER, addressee=PAYER)
        guard = patch('socket.socket.connect', side_effect=AssertionError('Synthetic routing workflow forbids network calls'))
        guard.start()
        self.addCleanup(guard.stop)

    def assert_no_artifacts(self):
        for directory in (self.paths.output_dir, self.paths.draft_output_dir, self.paths.intake_output_dir, self.paths.manifest_dir):
            self.assertFalse(directory.exists() and any(directory.iterdir()), str(directory))

    def test_saved_payer_contact_reaches_review_preflight_and_draft_payload_without_changing_claims(self):
        before = copy.deepcopy(self.intake)
        review = review_intake(self.intake, self.paths)
        self.assertEqual(review['status'], 'ready')
        preflight = preflight_intakes([self.intake], self.paths)
        self.assertEqual(preflight['status'], 'ready')
        self.assertEqual(preflight['items'][0]['recipient'], LOCAL_EMAIL)
        result = prepare_intakes([self.intake], self.paths)
        item = result['items'][0]
        payload = json.loads(Path(item['draft_payload']).read_text(encoding='utf-8'))
        self.assertEqual(payload['to'], LOCAL_EMAIL)
        self.assertEqual(payload['recipient_source'], 'payment_entity_directory')
        self.assertEqual(payload['gmail_create_draft_args']['to'], LOCAL_EMAIL)
        self.assertFalse(payload['send_allowed'])
        self.assertTrue(payload['draft_only'])
        self.assertTrue(payload['claim_interpreting'])
        self.assertTrue(payload['claim_transport'])
        self.assertEqual(validate_draft_payload(payload), [])
        self.assertEqual(self.intake, before)

    def test_wrong_selected_key_blocks_review_preflight_and_preparation_before_files(self):
        self.intake['court_email_key'] = 'fictional-region'
        self.assertEqual(review_intake(self.intake, self.paths)['status'], 'error')
        self.assertEqual(preflight_intakes([self.intake], self.paths)['status'], 'blocked')
        with self.assertRaisesRegex(IntakeError, 'Recipient does not match the payment entity'):
            prepare_intakes([self.intake], self.paths)
        self.assert_no_artifacts()


if __name__ == '__main__':
    unittest.main()
