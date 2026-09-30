"""Fictional, offline upload/review checks for explicitly enabled photo defaults."""
from __future__ import annotations

import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from reportlab.pdfgen import canvas

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (
    AppPaths, apply_answer_to_intake, apply_numbered_answers, recover_source_upload,
    review_intake, review_intake_with_profile_evidence,
)


CASE_NUMBER = '710/26.0TSTXX'
CAPTURE_DATE = '2026-09-26'
PRINTED_DATE = '2026-09-18'
CAPTURE_CITY = 'Capture City'
CAPTURE_COURT = 'Tribunal de Capture City'
COURT_DOMAIN = 'tribunais' + '.org.pt'
CAPTURE_RECIPIENT = 'fictional-capture@' + COURT_DOMAIN
DEFAULT_RECIPIENT = 'court@' + COURT_DOMAIN
SOURCE_TEXT = (
    'POLICIA DE SEGURANCA PUBLICA\nCOMANDO DISTRITAL DE Header City\n'
    'Esquadra de Example City\n'
    f'Processo {CASE_NUMBER}\nServico de interpretacao presencial.'
)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def court_record(entity=CAPTURE_COURT, recipient=CAPTURE_RECIPIENT):
    return {'payment_entity': entity, 'addressee': entity, 'recipient_email': recipient}


class PhotoDefaultTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-photo-default-public-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        self.defaults_path = self.paths.ai_config.with_name('photo-defaults.local.json')
        # Nothing in these tests can reach a provider or Gmail, even accidentally.
        network = patch('socket.socket.connect', side_effect=AssertionError('Photo defaults tests must stay offline.'))
        network.start()
        self.addCleanup(network.stop)

    def enable(self, *, date=True, city=True, mappings=None):
        write_json(self.defaults_path, {
            'capture_date_is_service_date': date,
            'photo_city_court': city,
            'city_courts': mappings if mappings is not None else {CAPTURE_CITY: court_record()},
        })

    def upload(self, *, metadata_date=CAPTURE_DATE, photo_city=CAPTURE_CITY,
               visible_text=SOURCE_TEXT, ai_fields=None, exif=False, source_kind='photo',
               service_profile='auto'):
        if source_kind == 'notification_pdf':
            content = BytesIO()
            document = canvas.Canvas(content)
            for index, line in enumerate(visible_text.splitlines()):
                document.drawString(60, 780 - index * 18, line)
            document.save()
            filename, content_type = 'fictional-notification.pdf', 'application/pdf'
        else:
            content = BytesIO()
            image = Image.new('RGB', (600, 900), 'white')
            metadata = image.getexif()
            if exif and metadata_date:
                metadata[36867] = metadata_date.replace('-', ':') + ' 10:15:00'
            image.save(content, format='JPEG', exif=metadata)
            filename, content_type = 'fictional-photo.jpg', 'image/jpeg'
        fields = {
            'case_number': CASE_NUMBER,
            'service_entity': 'Esquadra de Example City',
            'service_entity_type': 'psp',
            'service_place': 'Esquadra de Example City',
            'locality': 'Example City',
        }
        if metadata_date and not exif:
            fields['photo_metadata_date'] = metadata_date
        if photo_city is not None:
            fields['photo_metadata_city'] = photo_city
        fields.update(ai_fields or {})
        recovery = {
            'status': 'ok', 'attempted': True, 'provider': 'fictional-replayed-recovery',
            'fields': fields, 'raw_visible_text': visible_text,
            'warnings': [], 'translation_indicators': [],
        }
        managed = [*self.root.joinpath('config').glob('*.json'), *self.root.joinpath('data').glob('*.json')]
        before = {path: path.read_bytes() for path in managed}
        with patch('honorarios_app.services.recover_source_with_openai', return_value=recovery) as provider:
            result = recover_source_upload(
                filename=filename, content_type=content_type, content=content.getvalue(),
                source_kind=source_kind, profile_name=service_profile,
                visible_text=visible_text if source_kind == 'photo' else '',
                ai_recovery_mode='off', paths=self.paths,
            )
            provider.assert_called_once()
        self.assertEqual({path: path.read_bytes() for path in managed}, before)
        for directory in (self.paths.output_dir, self.paths.draft_output_dir,
                          self.paths.intake_output_dir, self.paths.manifest_dir):
            self.assertEqual(list(directory.rglob('*')), [])
        self.assertFalse(result['send_allowed'])
        self.assertFalse(result['review']['send_allowed'])
        return result

    @staticmethod
    def question_fields(result):
        return {question['field'] for question in result['review'].get('questions', [])}

    def test_capture_date_default_removes_repeated_date_question(self):
        self.enable()
        result = self.upload()
        candidate = result['candidate_intake']
        self.assertEqual(candidate['service_date'], CAPTURE_DATE)
        self.assertEqual(candidate['service_date_source'], 'photo_metadata')
        self.assertFalse(candidate.get('photo_metadata_date_requires_confirmation'))
        self.assertNotIn('service_date', self.question_fields(result))
        self.assertNotIn('service_date_source', self.question_fields(result))
        self.assertEqual(result['review']['status'], 'ready')
        self.assertEqual(result['review']['service_date'], CAPTURE_DATE)
        self.assertEqual(candidate['photo_defaults_applied']['service_date'], CAPTURE_DATE)

    def test_exif_capture_date_works_without_ai_date(self):
        self.enable()
        result = self.upload(exif=True)
        self.assertEqual(result['candidate_intake']['service_date'], CAPTURE_DATE)
        self.assertEqual(result['source']['metadata']['exif_date'], CAPTURE_DATE)
        self.assertEqual(result['review']['status'], 'ready')

    def test_user_photo_default_takes_priority_over_different_printed_service_date(self):
        self.enable()
        text = SOURCE_TEXT + '\nServico de interpretacao realizado em 18/09/2026.'
        result = self.upload(visible_text=text, ai_fields={'service_date': PRINTED_DATE})
        self.assertEqual(result['candidate_intake']['service_date'], CAPTURE_DATE)
        self.assertEqual(result['review']['service_date'], CAPTURE_DATE)
        self.assertEqual(result['review']['status'], 'ready')
        self.assertNotIn('service_date_source', self.question_fields(result))

    def test_absent_configuration_preserves_capture_confirmation(self):
        result = self.upload()
        self.assertFalse(self.defaults_path.exists())
        self.assertEqual(result['candidate_intake'].get('service_date', ''), '')
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertIn('service_date', self.question_fields(result))

    def test_disabled_defaults_preserve_existing_behavior(self):
        self.enable(date=False, city=False)
        result = self.upload()
        self.assertEqual(result['candidate_intake'].get('service_date', ''), '')
        self.assertEqual(result['candidate_intake']['payment_entity'], 'Example Court')
        self.assertIn('service_date', self.question_fields(result))

    def test_pdf_keeps_document_date_and_payer_when_photo_defaults_are_enabled(self):
        self.enable()
        text = SOURCE_TEXT + '\nServico de interpretacao realizado em 18/09/2026.'
        result = self.upload(source_kind='notification_pdf', visible_text=text)
        self.assertEqual(result['candidate_intake']['service_date'], PRINTED_DATE)
        self.assertEqual(result['candidate_intake']['payment_entity'], 'Example Court')
        self.assertNotEqual(result['candidate_intake'].get('recipient_email'), CAPTURE_RECIPIENT)

    def test_capture_city_selects_its_court_instead_of_district_or_service_city(self):
        self.enable(mappings={
            CAPTURE_CITY: court_record(),
            'Example City': court_record('Tribunal de Example City', 'fictional-service@' + COURT_DOMAIN),
            'Header City': court_record('Tribunal de Header City', 'fictional-header@' + COURT_DOMAIN),
        })
        result = self.upload(ai_fields={'payment_entity': 'Comando Distrital de Header City'})
        candidate = result['candidate_intake']
        self.assertEqual(candidate['payment_entity'], CAPTURE_COURT)
        self.assertEqual(candidate['addressee'], CAPTURE_COURT)
        self.assertEqual(candidate['recipient_email'], CAPTURE_RECIPIENT)
        self.assertIn('Example City', candidate['service_place'])
        self.assertNotIn(CAPTURE_CITY, candidate['service_place'])
        self.assertNotIn('Header City', candidate['service_place'])
        self.assertTrue(candidate['entities_differ'])
        self.assertEqual(result['review']['recipient'], CAPTURE_RECIPIENT)

    def test_capture_city_overrides_automatic_profile_and_different_source_court(self):
        self.enable()
        profiles = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))
        profile_court = 'Tribunal de Profile City'
        profiles['example_interpreting']['defaults'].update(
            payment_entity=profile_court, addressee=profile_court,
            recipient_email='fictional-profile@' + COURT_DOMAIN,
            court_email_key='example-court', court_email=DEFAULT_RECIPIENT)
        write_json(self.paths.service_profiles, profiles)
        source_court = 'Tribunal de Other Source City'
        source_recipient = 'fictional-source@' + COURT_DOMAIN
        text = SOURCE_TEXT + f'\n{profile_court}\n{source_court}\nEmail: {source_recipient}'
        result = self.upload(visible_text=text, ai_fields={
            'payment_entity': source_court, 'court_email': source_recipient,
        })
        candidate = result['candidate_intake']
        self.assertEqual(candidate['payment_entity'], CAPTURE_COURT)
        self.assertEqual(candidate['addressee'], CAPTURE_COURT)
        self.assertEqual(candidate['recipient_email'], CAPTURE_RECIPIENT)
        self.assertFalse(candidate.get('court_email'))
        self.assertFalse(candidate.get('court_email_key'))
        self.assertEqual(result['review']['status'], 'ready')
        self.assertEqual(result['review']['recipient'], CAPTURE_RECIPIENT)
        self.assertIn(source_court, candidate['source_text'])

    def test_date_only_preference_does_not_replace_existing_court(self):
        self.enable(city=False)
        result = self.upload()
        self.assertEqual(result['candidate_intake']['service_date'], CAPTURE_DATE)
        self.assertEqual(result['candidate_intake']['payment_entity'], 'Example Court')

    def test_explicit_service_profile_preserves_per_request_court_exception(self):
        self.enable()
        result = self.upload(service_profile='example_interpreting')
        self.assertEqual(result['candidate_intake']['service_date'], CAPTURE_DATE)
        self.assertEqual(result['candidate_intake']['payment_entity'], 'Example Court')
        self.assertEqual(result['review']['recipient'], DEFAULT_RECIPIENT)

    def test_city_only_preference_keeps_date_confirmation(self):
        self.enable(date=False)
        result = self.upload()
        self.assertEqual(result['candidate_intake']['payment_entity'], CAPTURE_COURT)
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertIn('service_date', self.question_fields(result))

    def test_missing_capture_date_still_pauses(self):
        self.enable()
        result = self.upload(metadata_date=None)
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertIn('service_date', self.question_fields(result))
        self.assertEqual(result['candidate_intake'].get('service_date', ''), '')

    def test_conflicting_exif_and_ai_capture_dates_need_a_choice(self):
        self.enable()
        result = self.upload(exif=True, ai_fields={'photo_metadata_date': '2026-09-27'})
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertTrue(self.question_fields(result) & {'service_date', 'service_date_source'})
        self.assertEqual(result['candidate_intake'].get('service_date', ''), '')

    def test_conflicting_exif_and_visible_capture_dates_need_a_choice(self):
        self.enable()
        result = self.upload(exif=True, visible_text=SOURCE_TEXT + '\nGoogle Photos Sep 27, 2026 10:15 AM')
        self.assertEqual(result['source']['metadata']['visible_metadata_date'], '2026-09-27')
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertTrue(self.question_fields(result) & {'service_date', 'service_date_source'})
        self.assertEqual(result['candidate_intake'].get('service_date', ''), '')

    def test_missing_or_unknown_capture_city_cannot_inherit_profile_payer(self):
        self.enable()
        for city in (None, '', 'Unknown City', 'Capture City / Other City'):
            with self.subTest(city=city):
                result = self.upload(photo_city=city,
                    ai_fields={'payment_entity': 'Comando Distrital de Header City'})
                self.assertEqual(result['review']['status'], 'needs_info')
                self.assertIn('payment_entity', self.question_fields(result))
                candidate = result['candidate_intake']
                self.assertFalse(candidate.get('payment_entity'))
                self.assertFalse(candidate.get('recipient_email'))
                self.assertNotIn('recipient', result['review'])

    def test_duplicate_normalized_city_mapping_cannot_choose_first_court(self):
        self.enable(mappings={
            'Capture City': court_record(),
            'capture city': court_record('Tribunal Alternativo', 'fictional-other@' + COURT_DOMAIN),
        })
        result = self.upload()
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertIn('payment_entity', self.question_fields(result))
        self.assertFalse(result['candidate_intake'].get('payment_entity'))

    def test_court_without_confirmed_recipient_cannot_use_unrelated_default_email(self):
        self.enable(mappings={CAPTURE_CITY: {
            'payment_entity': CAPTURE_COURT, 'addressee': CAPTURE_COURT,
        }})
        result = self.upload()
        self.assertNotEqual(result['review']['status'], 'ready')
        self.assertNotEqual(result['review'].get('recipient'), DEFAULT_RECIPIENT)

    def test_duplicate_detection_uses_capture_default_not_printed_date(self):
        self.enable()
        write_json(self.paths.duplicate_index, [{
            'case_number': CASE_NUMBER, 'service_date': CAPTURE_DATE, 'status': 'sent',
            'recipient': CAPTURE_RECIPIENT,
        }])
        text = SOURCE_TEXT + '\nServico de interpretacao realizado em 18/09/2026.'
        result = self.upload(visible_text=text)
        self.assertEqual(result['review']['status'], 'duplicate')
        self.assertEqual(result['review']['duplicate']['service_date'], CAPTURE_DATE)

    def test_manual_later_date_and_payer_edits_survive_review(self):
        self.enable()
        candidate = copy.deepcopy(self.upload()['candidate_intake'])
        apply_answer_to_intake(candidate, 'service_date', '2026-09-27')
        candidate.update(payment_entity='Example Court', addressee='Example Court',
                         recipient_email=DEFAULT_RECIPIENT)
        review = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(review['status'], 'ready')
        self.assertEqual(review['service_date'], '2026-09-27')
        self.assertEqual(review['payment_entity'], 'Example Court')
        self.assertEqual(review['recipient'], DEFAULT_RECIPIENT)
        self.assertEqual(review['intake']['service_date_source'], 'user_confirmed')

    def test_cleared_photo_default_date_stays_missing_after_profile_review(self):
        self.enable()
        candidate = copy.deepcopy(self.upload()['candidate_intake'])
        candidate.update(service_date='', photo_metadata_date_requires_confirmation=True)
        review = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(review['status'], 'needs_info')
        self.assertEqual(review['intake'].get('service_date', ''), '')
        self.assertTrue(review['intake']['photo_metadata_date_requires_confirmation'])
        self.assertIn('service_date', {question['field'] for question in review['questions']})

    def test_cleared_explicit_profile_recipient_stays_missing_after_profile_review(self):
        self.enable()
        candidate = copy.deepcopy(self.upload(service_profile='example_interpreting')['candidate_intake'])
        candidate['recipient_email'] = ''
        review = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(review['status'], 'needs_info')
        self.assertEqual(review['intake'].get('recipient_email', ''), '')
        self.assertIn('recipient_email', {question['field'] for question in review['questions']})
        self.assertNotIn('recipient', review)

    def test_changed_payer_clears_previous_mapped_address_contact_and_key(self):
        self.enable()
        candidate = copy.deepcopy(self.upload()['candidate_intake'])
        candidate.update(court_email=CAPTURE_RECIPIENT, court_email_key='capture-court')
        apply_answer_to_intake(candidate, 'payment_entity', 'Example Court')
        self.assertEqual(candidate['payment_entity'], 'Example Court')
        self.assertNotIn(CAPTURE_COURT, candidate.get('addressee', ''))
        for field in ('recipient_email', 'court_email', 'court_email_key'):
            self.assertFalse(candidate.get(field), field)
        review = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(review['intake']['payment_entity'], 'Example Court')
        self.assertNotEqual(review.get('recipient'), CAPTURE_RECIPIENT)

    def test_manual_answer_resolves_unknown_photo_city_without_reapplying_default(self):
        self.enable()
        uploaded = self.upload(photo_city='Unknown City')
        questions = {item['field']: item['number'] for item in uploaded['review']['questions']}
        self.assertIn('payment_entity', questions)
        candidate = uploaded['candidate_intake']
        answer = f"{questions['payment_entity']}. Example Court"
        applied = apply_numbered_answers({'intake': candidate, 'answer_text': answer}, self.paths)
        self.assertEqual(applied['intake']['payment_entity'], 'Example Court')
        self.assertNotIn('payment_entity', {q['field'] for q in applied.get('questions', [])})
        self.assertFalse(applied['send_allowed'])


if __name__ == '__main__':
    unittest.main()
