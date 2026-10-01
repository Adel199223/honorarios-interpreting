"""Fictional, offline upload/review checks for explicitly enabled photo defaults."""
from __future__ import annotations

import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from honorarios_app.ai_recovery import _prompt_for_source, should_attempt_ai_recovery
from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (
    AppPaths, apply_answer_to_intake, apply_numbered_answers, recover_source_upload,
    prepare_intakes, review_intake, review_intake_with_profile_evidence,
)
from scripts.generate_pdf import IntakeError, build_rendered_request


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
    def test_explicit_review_clears_survive_default_reapplication_and_ask_again(self):
        original = json.loads((Path(__file__).resolve().parents[1] / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        original['auto_profile'] = {'auto_applied': True, 'profile_key': 'example_interpreting'}
        for field in ('case_number', 'service_date', 'payment_entity', 'service_place', 'recipient_email', 'transport.km_one_way'):
            with self.subTest(field=field):
                row = copy.deepcopy(original)
                row['review_cleared_fields'] = [field]
                if field == 'transport.km_one_way':
                    row['transport']['km_one_way'] = ''
                else:
                    row[field] = ''
                first = review_intake_with_profile_evidence(row, self.paths)
                self.assertEqual(first['status'], 'needs_info')
                self.assertIn(field, [question['field'] for question in first['questions']])
                second = review_intake_with_profile_evidence(first['intake'], self.paths)
                self.assertIn(field, [question['field'] for question in second['questions']])
                answer = {'case_number': '710/26.0TSTXX', 'service_date': '2026-01-15',
                          'payment_entity': 'Example Court', 'service_place': 'Esquadra da PSP de Outra Cidade',
                          'recipient_email': DEFAULT_RECIPIENT, 'transport.km_one_way': '12'}[field]
                resolved = copy.deepcopy(second['intake'])
                apply_answer_to_intake(resolved, field, answer)
                final = review_intake_with_profile_evidence(resolved, self.paths)
                self.assertNotIn(field, final['intake'].get('review_cleared_fields', []))
                self.assertNotIn(field, [question['field'] for question in final['questions']])
                if field == 'service_place':
                    self.assertEqual(final['intake']['service_entity'], answer)
                    self.assertIn(answer, final['intake']['service_place_phrase'])

    def test_initial_missing_fields_still_receive_defaults_without_clear_intent(self):
        row = json.loads((Path(__file__).resolve().parents[1] / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        row['auto_profile'] = {'auto_applied': True, 'profile_key': 'example_interpreting'}
        row.update(payment_entity='', service_place='')
        row['transport']['km_one_way'] = ''
        result = review_intake_with_profile_evidence(row, self.paths)
        self.assertEqual(result['intake']['payment_entity'], 'Example Court')
        self.assertEqual(result['intake']['service_place'], 'Example Police Station')
        self.assertEqual(result['intake']['transport']['km_one_way'], 12)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-photo-default-public-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        destinations = json.loads(self.paths.known_destinations.read_text(encoding='utf-8'))
        destinations.append({'destination': CAPTURE_CITY, 'institution_examples': [CAPTURE_COURT],
                             'km_one_way': 12, 'notes': 'Fictional saved venue distance.'})
        write_json(self.paths.known_destinations, destinations)
        profiles = json.loads(self.paths.personal_profiles.read_text(encoding='utf-8'))
        profiles['profiles'][0]['travel_distances_by_city'][CAPTURE_CITY] = 12
        write_json(self.paths.personal_profiles, profiles)
        self.defaults_path = self.paths.ai_config.with_name('photo-defaults.local.json')
        # Nothing in these tests can reach a provider or Gmail, even accidentally.
        network = patch('socket.socket.connect', side_effect=AssertionError('Photo defaults tests must stay offline.'))
        network.start()
        self.addCleanup(network.stop)

    def enable(self, *, date=True, city=True, venue=False, mappings=None):
        write_json(self.defaults_path, {
            'capture_date_is_service_date': date,
            'photo_city_court': city,
            'missing_venue_is_city_court': venue,
            'city_courts': mappings if mappings is not None else {CAPTURE_CITY: court_record()},
        })

    def upload(self, *, metadata_date=CAPTURE_DATE, photo_city=CAPTURE_CITY,
               visible_text=SOURCE_TEXT, ai_fields=None, exif=False, source_kind='photo',
               service_profile='auto', exif_values=None):
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
            for tag, value in (exif_values or {}).items():
                metadata[tag] = value
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

    def test_photo_review_uses_already_saved_closing_city(self):
        self.enable()
        candidate = copy.deepcopy(self.upload()['candidate_intake'])
        candidate.pop('closing_city', None)
        profile = json.loads(self.paths.profile.read_text(encoding='utf-8'))
        profile['default_closing_city'] = 'Configured Closing City'
        write_json(self.paths.profile, profile)
        review = review_intake(candidate, self.paths)
        self.assertNotIn('closing_city', {q['field'] for q in review.get('questions', [])})
        self.assertEqual(review['effective_intake']['closing_city'], 'Configured Closing City')

    def test_city_directory_does_not_substitute_a_lone_specialized_court(self):
        self.enable(mappings={})
        write_json(self.paths.court_emails, [{'key':'fictional-labour', 'name':'Tribunal do Trabalho de Capture City', 'city':CAPTURE_CITY, 'email':CAPTURE_RECIPIENT}])
        result = self.upload()
        self.assertNotEqual(result['review']['status'], 'ready')
        self.assertIn('payment_entity', self.question_fields(result))
        self.assertFalse(result['candidate_intake'].get('recipient_email'))

    def test_clearing_visible_recipient_removes_hidden_alternate_contact(self):
        self.enable()
        candidate = copy.deepcopy(self.upload(service_profile='example_interpreting')['candidate_intake'])
        candidate.update(court_email=DEFAULT_RECIPIENT, court_email_key='example-court')
        apply_answer_to_intake(candidate, 'recipient_email', 'updated-contact@' + COURT_DOMAIN)
        candidate['recipient_email'] = ''
        review = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(review['status'], 'needs_info')
        self.assertIn('recipient_email', {q['field'] for q in review['questions']})
        self.assertFalse(review['intake'].get('court_email_key'))
        self.assertFalse(review['intake'].get('court_email'))

    def test_exif_capture_date_works_without_ai_date(self):
        self.enable()
        result = self.upload(exif=True)
        self.assertEqual(result['candidate_intake']['service_date'], CAPTURE_DATE)
        self.assertEqual(result['source']['metadata']['exif_date'], CAPTURE_DATE)
        self.assertEqual(result['review']['status'], 'ready')

    def test_nested_exif_original_date_wins_over_modification_in_actual_pdf(self):
        self.enable()
        result = self.upload(metadata_date=None, exif_values={
            34665: {36867: '2026:09:26 10:15:00', 36868: '2026:09:27 10:15:00'},
            306: '2026:09:30 15:00:00',
        })
        self.assertEqual(result['source']['metadata']['exif_date'], CAPTURE_DATE)
        self.assertEqual(result['candidate_intake']['service_date'], CAPTURE_DATE)
        self.assertEqual(result['review']['status'], 'ready')
        prepared = prepare_intakes([result['candidate_intake']], self.paths)
        text = '\n'.join(page.extract_text() for page in PdfReader(prepared['items'][0]['pdf']).pages)
        self.assertIn('26/09/2026', text)
        self.assertNotIn('30/09/2026', text)

    def test_modification_date_alone_cannot_supply_capture_or_service_date(self):
        self.enable()
        result = self.upload(metadata_date=None, exif_values={306: '2026:09:30 15:00:00'})
        self.assertNotIn('exif_date', result['source']['metadata'])
        self.assertFalse(result['candidate_intake'].get('service_date'))
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertIn('service_date', self.question_fields(result))
        self.assertTrue(any('modification date' in warning for warning in result['source']['metadata']['warnings']))

    def test_nested_digitized_date_is_used_only_without_original_date(self):
        self.enable()
        result = self.upload(metadata_date=None, exif_values={
            34665: {36868: '2026:09:26 10:15:00'}, 306: '2026:09:30 15:00:00',
        })
        self.assertEqual(result['candidate_intake']['service_date'], CAPTURE_DATE)

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

    def test_notification_appointment_reaches_actual_pdf_without_photo_date_contamination(self):
        self.enable(venue=True)
        text = (f'Processo {CASE_NUMBER}\nData: 16/09/2026\n'
                'Nomeado intérprete, deve comparecer no dia 24 de setembro de 2026, às 10:30,\n'
                'para a audiência no Tribunal de Example City.')
        self.assertFalse(should_attempt_ai_recovery('notification_pdf', 'auto', text))
        result = self.upload(source_kind='notification_pdf', visible_text=text,
                             service_profile='example_interpreting',
                             ai_fields={'service_date': '2026-09-16', 'photo_metadata_date': '2026-09-30'})
        candidate = result['candidate_intake']
        self.assertEqual(candidate['service_date'], '2026-09-24')
        self.assertNotIn('photo_metadata_date', candidate)
        self.assertNotIn('photo_defaults_applied', candidate)
        self.assertNotIn('service_date', self.question_fields(result))
        self.assertNotIn('service_date_source', self.question_fields(result))
        # Complete unrelated routing/claim fields as a user would; the source
        # date itself must reach generation without a manual date correction.
        candidate.update(payment_entity='Example Court', recipient_email=DEFAULT_RECIPIENT,
                         claim_transport=False, closing_city='Example City')
        prepared = prepare_intakes([candidate], self.paths)
        pdf_text = '\n'.join(page.extract_text() for page in PdfReader(prepared['items'][0]['pdf']).pages)
        self.assertIn('24/09/2026', pdf_text)
        self.assertNotIn('16/09/2026', pdf_text)
        self.assertNotIn('30/09/2026', pdf_text)

    def test_notification_issue_date_alone_cannot_use_ai_or_saved_profile_date(self):
        profiles = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))
        profiles['example_interpreting']['defaults'].update(
            service_date='2026-09-01', photo_metadata_date='2026-09-30')
        write_json(self.paths.service_profiles, profiles)
        result = self.upload(source_kind='notification_pdf', service_profile='example_interpreting',
                             visible_text=f'Processo {CASE_NUMBER}\nNomeação de intérprete\nData: 16-09-2026',
                             ai_fields={'service_date': '2026-09-16', 'photo_metadata_date': '2026-09-30'})
        self.assertFalse(result['candidate_intake'].get('service_date'))
        self.assertNotIn('photo_metadata_date', result['candidate_intake'])
        self.assertIn('service_date', self.question_fields(result))

    def test_scanned_notification_replayed_ocr_reads_both_pages_and_appointment_date(self):
        text = (f'Processo {CASE_NUMBER}\nCertificação Citius em: 16-09-2026\n'
                'Foi nomeado intérprete, devendo comparecer neste Tribunal no dia 24-09-2026 às 10:30.')
        data = BytesIO()
        document = canvas.Canvas(data)
        for page_text in (text, 'Fictional second page: court signature only.'):
            raster = Image.new('RGB', (600, 850), 'white')
            ImageDraw.Draw(raster).multiline_text((40, 50), page_text, fill='black')
            document.drawImage(ImageReader(raster), 0, 0, width=595, height=842)
            document.showPage()
        document.save()
        self.assertFalse(any((page.extract_text() or '').strip() for page in PdfReader(BytesIO(data.getvalue())).pages))
        recovery = {'status': 'ok', 'attempted': True, 'fields': {'service_date': '2026-09-24'},
                    'raw_visible_text': text, 'warnings': [], 'translation_indicators': []}
        with patch('honorarios_app.services.recover_source_with_openai', return_value=recovery) as provider:
            result = recover_source_upload(filename='fictional-scanned-notice.pdf', content_type='application/pdf',
                content=data.getvalue(), source_kind='notification_pdf', profile_name='example_interpreting',
                ai_recovery_mode='auto', paths=self.paths)
        self.assertEqual(result['candidate_intake']['service_date'], '2026-09-24')
        self.assertEqual(len(provider.call_args.kwargs['rendered_page_images']), 2)
        self.assertEqual(result['source']['metadata']['rendered_page_count'], 2)
        self.assertTrue(should_attempt_ai_recovery('notification_pdf', 'auto', ''))

    def test_source_specific_ai_prompt_explains_pdf_appointment_and_photo_policy(self):
        pdf_prompt = _prompt_for_source('notification_pdf', '')
        self.assertIn('including a future appointment', pdf_prompt)
        self.assertIn('leave photo_metadata_date and photo_metadata_city empty', pdf_prompt)
        photo_prompt = _prompt_for_source('photo', '')
        self.assertIn('Do not use the issue date, signing/closing date, a future appointment', photo_prompt)

    def test_notification_beyond_read_coverage_stops_before_ocr_or_preparation(self):
        for count, scanned, limit in ((9, False, 8), (4, True, 3), (4, 'last', 3)):
            with self.subTest(page_count=count, scanned=scanned):
                data = BytesIO()
                document = canvas.Canvas(data)
                for page_number in range(count):
                    if scanned is True or (scanned == 'last' and page_number == count - 1):
                        image = Image.new('RGB', (600, 850), 'white')
                        ImageDraw.Draw(image).text((40, 50), f'Fictional scanned page {page_number + 1}', fill='black')
                        document.drawImage(ImageReader(image), 0, 0, width=595, height=842)
                    else:
                        document.drawString(40, 790, f'Processo {CASE_NUMBER}. Servico de interpretacao realizado em 24/09/2026.')
                    document.showPage()
                document.save()
                with patch('honorarios_app.services.recover_source_with_openai') as provider, \
                     patch('honorarios_app.services.render_pdf_pages_for_source') as render:
                    with self.assertRaisesRegex(IntakeError, f'only the first {limit}'):
                        recover_source_upload(filename='fictional-over-limit.pdf', content_type='application/pdf',
                            content=data.getvalue(), source_kind='notification_pdf', paths=self.paths)
                    provider.assert_not_called()
                    render.assert_not_called()
                for directory in (self.paths.output_dir, self.paths.intake_output_dir, self.paths.manifest_dir):
                    self.assertEqual(list(directory.glob('*')), [])

    def test_complete_text_notification_at_eight_page_limit_remains_usable(self):
        data = BytesIO()
        document = canvas.Canvas(data)
        for page_number in range(8):
            document.drawString(40, 790, f'Processo {CASE_NUMBER}. Servico de interpretacao realizado em 24/09/2026.')
            document.drawString(40, 760, f'Fictional supporting page {page_number + 1}; same appointment and no additional requests.')
            document.showPage()
        document.save()
        with patch('honorarios_app.services.recover_source_with_openai', return_value={'status': 'disabled'}) as provider:
            result = recover_source_upload(filename='fictional-eight-pages.pdf', content_type='application/pdf',
                content=data.getvalue(), source_kind='notification_pdf', paths=self.paths, ai_recovery_mode='off')
        self.assertEqual(result['candidate_intake']['service_date'], '2026-09-24')
        self.assertEqual(result['source']['metadata']['pdf_page_count'], 8)
        self.assertEqual(provider.call_args.kwargs['rendered_page_images'], [])

    @staticmethod
    def hybrid_notification():
        first = (f'Processo {CASE_NUMBER}\nNomeado interprete, deve comparecer em 24-09-2026.\n'
                 'Tribunal de Example City. Fictional notification for a personally attended interpreting service.')
        second = 'Interprete: Example Person. Nova audiencia designada para 25-09-2026.'
        data = BytesIO()
        document = canvas.Canvas(data)
        for index, line in enumerate(first.splitlines()):
            document.drawString(40, 790 - index * 20, line)
        document.showPage()
        raster = Image.new('RGB', (600, 850), 'white')
        ImageDraw.Draw(raster).multiline_text((40, 50), second, fill='black')
        document.drawImage(ImageReader(raster), 0, 0, width=595, height=842)
        document.showPage()
        document.save()
        return data.getvalue(), first, second

    def test_hybrid_notification_reads_scanned_page_even_when_first_page_is_clear(self):
        content, first, second = self.hybrid_notification()
        self.assertFalse(should_attempt_ai_recovery('notification_pdf', 'auto', first))
        recovery = {'status': 'ok', 'attempted': True, 'fields': {'service_date': '2026-09-24'},
                    'raw_visible_text': first + '\n' + second, 'warnings': [], 'translation_indicators': []}
        with patch('honorarios_app.services.recover_source_with_openai', return_value=recovery) as provider:
            result = recover_source_upload(filename='fictional-hybrid.pdf', content_type='application/pdf',
                content=content, source_kind='notification_pdf', paths=self.paths)
        arguments = provider.call_args.kwargs
        self.assertEqual(arguments['source_metadata']['pdf_pages_without_useful_text'], [2])
        self.assertEqual(len(arguments['rendered_page_images']), 2)
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertFalse(result['candidate_intake'].get('service_date'))
        self.assertIn('service_date', self.question_fields(result))

    def test_hybrid_notification_cannot_prepare_from_only_readable_first_page_if_ai_fails(self):
        content, _first, _second = self.hybrid_notification()
        for status in ('skipped', 'unconfigured', 'unavailable', 'failed', 'ok'):
            with self.subTest(status=status):
                with patch('honorarios_app.services.recover_source_with_openai', return_value={
                        'status': status, 'raw_visible_text': '', 'fields': {}}):
                    with self.assertRaisesRegex(IntakeError, 'AI image reading did not complete'):
                        recover_source_upload(filename='fictional-hybrid.pdf', content_type='application/pdf',
                            content=content, source_kind='notification_pdf', paths=self.paths)
                for directory in (self.paths.output_dir, self.paths.intake_output_dir, self.paths.manifest_dir):
                    self.assertEqual(list(directory.glob('*')), [])

    def test_hybrid_notification_requires_every_page_to_render_before_provider_call(self):
        content, _first, _second = self.hybrid_notification()
        with patch('honorarios_app.services.render_pdf_pages_for_source', return_value=([
                self.root / 'fictional-page-1.png'], ['Fictional partial renderer failure.'])), \
             patch('honorarios_app.services.recover_source_with_openai') as provider:
            with self.assertRaisesRegex(IntakeError, 'not every page could be rendered'):
                recover_source_upload(filename='fictional-hybrid.pdf', content_type='application/pdf',
                    content=content, source_kind='notification_pdf', paths=self.paths)
        provider.assert_not_called()

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

    def missing_venue_upload(self, *, photo_city=CAPTURE_CITY, source_kind='photo', extra_fields=None):
        text = f'Processo {CASE_NUMBER}\nRegisto do serviço de interpretação presencial.'
        return self.upload(photo_city=photo_city, source_kind=source_kind,
            visible_text=text, ai_fields={
                'service_entity': '', 'service_entity_type': '', 'service_place': '',
                'service_place_phrase': '', 'locality': '', **(extra_fields or {}),
            })

    def test_missing_source_venue_uses_opted_in_photo_city_court_with_provenance(self):
        self.enable(venue=True)
        result = self.missing_venue_upload()
        candidate = result['candidate_intake']
        self.assertEqual(candidate['service_entity'], CAPTURE_COURT)
        self.assertEqual(candidate['service_entity_type'], 'court')
        self.assertEqual(candidate['service_place'], CAPTURE_COURT)
        self.assertFalse(candidate['entities_differ'])
        self.assertEqual(candidate['photo_defaults_applied']['service_place'], CAPTURE_COURT)
        self.assertEqual(result['review']['status'], 'ready', result['review'])
        evidence = result.get('source_evidence', {}).get('field_evidence', [])
        venue_evidence = [item for item in evidence if item['field'] == 'service_place'
                          and item.get('value') == CAPTURE_COURT]
        self.assertTrue(venue_evidence)
        self.assertTrue(any(item.get('source') == 'photo_default' for item in venue_evidence))

    def test_named_station_heading_survives_missing_ai_venue_field(self):
        self.enable(venue=True)
        result = self.upload(visible_text=f'POLICIA DE SEGURANCA PUBLICA\nESQUADRA DE Capture City\nProcesso {CASE_NUMBER}',
            ai_fields={'service_place': '', 'service_entity': 'Polícia de Segurança Pública — Esquadra de Capture City', 'locality': CAPTURE_CITY})
        self.assertEqual(result['candidate_intake']['service_place'], 'Esquadra de Capture City')
        self.assertEqual(result['candidate_intake']['service_entity_type'], 'psp')
        self.assertNotIn('service_place', result['candidate_intake']['photo_defaults_applied'])
        self.assertEqual(result['candidate_intake']['payment_entity'], CAPTURE_COURT)

    def test_multiple_station_headings_need_venue_choice(self):
        self.enable(venue=True)
        result = self.upload(visible_text=f'ESQUADRA DE Capture City\nPOSTO DA GNR DE Other City\nProcesso {CASE_NUMBER}',
            ai_fields={'service_place': '', 'service_entity': '', 'service_entity_type': '', 'locality': ''})
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertIn('service_entity', self.question_fields(result))
        self.assertFalse(result['candidate_intake'].get('service_place'))

    def test_repeated_venue_corrections_update_dependent_place_and_type(self):
        self.enable(venue=True)
        candidate = copy.deepcopy(self.missing_venue_upload()['candidate_intake'])
        apply_answer_to_intake(candidate, 'service_entity', 'Esquadra da PSP de Capture City')
        apply_answer_to_intake(candidate, 'service_entity', 'Posto da GNR de Second City')
        self.assertEqual(candidate['service_place'], 'Posto da GNR de Second City')
        self.assertEqual(candidate['service_entity_type'], 'gnr')
        self.assertFalse(candidate.get('service_place_phrase'))

    def test_missing_venue_policy_is_independent_of_photo_payer_policy(self):
        self.enable(city=False, venue=True)
        candidate = self.missing_venue_upload()['candidate_intake']
        self.assertEqual(candidate['service_place'], CAPTURE_COURT)
        self.assertEqual(candidate['payment_entity'], 'Example Court')

    def test_actual_psp_gnr_and_pj_host_locations_override_missing_venue_default(self):
        self.enable(venue=True)
        for place, entity_type, text, expected_entity in (
            ('Esquadra da PSP de Example City', 'psp',
             'Diligência de interpretação realizada na Esquadra da PSP de Example City.',
             'Esquadra da PSP de Example City'),
            ('Posto da GNR de Example City', 'gnr',
             'Diligência de interpretação realizada no Posto da GNR de Example City.',
             'Posto da GNR de Example City'),
            ('Esquadra de Example City', 'psp',
             'Polícia Judiciária. Diligência de interpretação realizada na Esquadra de Example City.',
             'Polícia Judiciária'),
        ):
            with self.subTest(place=place):
                result = self.upload(visible_text=f'Processo {CASE_NUMBER}\n{text}\nServiço de interpretação.',
                    ai_fields={'service_entity': place, 'service_entity_type': entity_type,
                               'service_place': place, 'service_place_phrase': place})
                candidate = result['candidate_intake']
                self.assertEqual(candidate['service_place'], place)
                self.assertEqual(candidate['service_entity'], expected_entity)
                self.assertNotIn('service_place', candidate['photo_defaults_applied'])
                self.assertFalse(self.question_fields(result) & {'service_place', 'service_entity'})
                apply_answer_to_intake(candidate, 'claim_transport', 'no')
                reviewed = review_intake_with_profile_evidence(candidate, self.paths)
                self.assertEqual(reviewed['status'], 'ready', reviewed)
                self.assertEqual(reviewed['intake']['service_place'], place)

    def test_venue_default_does_not_invent_city_or_contact(self):
        self.enable(venue=True)
        for city in (None, 'Unknown City', 'Capture City / Other City'):
            with self.subTest(city=city):
                result = self.missing_venue_upload(photo_city=city)
                self.assertEqual(result['review']['status'], 'needs_info')
                self.assertIn('payment_entity', self.question_fields(result))
                self.assertFalse(result['candidate_intake'].get('photo_defaults_applied', {}).get('service_place'))
        self.enable(venue=True, mappings={CAPTURE_CITY: {
            'payment_entity': CAPTURE_COURT, 'addressee': CAPTURE_COURT,
        }})
        result = self.missing_venue_upload()
        self.assertNotEqual(result['review']['status'], 'ready')
        self.assertNotEqual(result['review'].get('recipient'), DEFAULT_RECIPIENT)

    def test_disabled_venue_policy_and_pdf_preserve_prior_behavior(self):
        self.enable(venue=False)
        candidate = self.missing_venue_upload()['candidate_intake']
        self.assertNotEqual(candidate.get('service_place'), CAPTURE_COURT)
        self.assertNotIn('service_place', candidate['photo_defaults_applied'])
        self.enable(venue=True)
        candidate = self.missing_venue_upload(source_kind='notification_pdf')['candidate_intake']
        self.assertNotEqual(candidate.get('service_place'), CAPTURE_COURT)
        self.assertNotIn('service_place', candidate.get('photo_defaults_applied', {}))

    def test_manually_changed_venue_survives_later_profile_review(self):
        self.enable(venue=True)
        candidate = copy.deepcopy(self.missing_venue_upload()['candidate_intake'])
        place = 'Posto da GNR de Manual City'
        candidate.update(service_place=place, service_place_phrase=place,
                         service_entity=place, service_entity_type='gnr', entities_differ=True)
        review = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(review['status'], 'ready', review)
        self.assertEqual(review['intake']['service_place'], place)
        self.assertEqual(review['intake']['service_entity'], place)
        self.assertEqual(review['intake']['service_entity_type'], 'gnr')
        self.assertEqual(review['intake']['payment_entity'], CAPTURE_COURT)

    def test_cleared_default_venue_stays_missing_during_later_profile_review(self):
        self.enable(venue=True)
        candidate = copy.deepcopy(self.missing_venue_upload()['candidate_intake'])
        candidate.update(service_place='', service_place_phrase='', service_entity='', service_entity_type='')
        review = review_intake_with_profile_evidence(candidate, self.paths)
        for field in ('service_place', 'service_place_phrase', 'service_entity', 'service_entity_type'):
            self.assertFalse(review['intake'].get(field), field)
        self.assertEqual(review['status'], 'needs_info')
        self.assertTrue(self.question_fields({'review': review}) & {'service_place', 'service_entity'})

    def assert_changed_venue_paragraph(self, candidate, place, entity_type):
        review = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(review['status'], 'ready', review)
        effective = review['intake']
        self.assertEqual(effective['service_place'], place)
        self.assertEqual(effective['service_entity'], place)
        self.assertEqual(effective['service_entity_type'], entity_type)
        self.assertTrue(effective['entities_differ'])
        self.assertEqual(effective['payment_entity'], CAPTURE_COURT)
        profile = json.loads(self.paths.profile.read_text(encoding='utf-8'))
        paragraph = build_rendered_request(effective, profile).service_paragraph
        self.assertIn(place, paragraph)
        self.assertNotIn(CAPTURE_COURT, paragraph)
        return effective, paragraph

    def test_clearing_only_default_place_clears_dependent_venue_fields_and_pauses(self):
        self.enable(venue=True)
        candidate = copy.deepcopy(self.missing_venue_upload()['candidate_intake'])
        candidate['service_place'] = ''
        review = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(review['status'], 'needs_info')
        self.assertIn('service_entity', self.question_fields({'review': review}))
        for field in ('service_place', 'service_place_phrase', 'service_entity', 'service_entity_type'):
            self.assertFalse(review['intake'].get(field), field)
        self.assertEqual(review['intake']['payment_entity'], CAPTURE_COURT)
        self.assertEqual(review['intake']['recipient_email'], CAPTURE_RECIPIENT)

    def test_single_entity_answers_replace_place_type_and_default_pdf_wording(self):
        self.enable(venue=True)
        for place, entity_type, expected_clause in (
            ('Esquadra da PSP de Manual City', 'psp', 'na Esquadra da PSP de Manual City'),
            ('Posto da GNR de Manual City', 'gnr', 'no Posto da GNR de Manual City'),
        ):
            with self.subTest(place=place):
                candidate = copy.deepcopy(self.missing_venue_upload()['candidate_intake'])
                apply_answer_to_intake(candidate, 'service_entity', place)
                self.assertFalse(candidate.get('service_place_phrase'))
                effective, paragraph = self.assert_changed_venue_paragraph(candidate, place, entity_type)
                self.assertIn(expected_clause, paragraph)
                self.assertEqual(effective['photo_defaults_applied']['service_place'], CAPTURE_COURT)

    def test_numbered_entity_answer_resolves_cleared_default_without_restoring_court_venue(self):
        self.enable(venue=True)
        for place, entity_type in (
            ('Esquadra da PSP de Manual City', 'psp'),
            ('Posto da GNR de Manual City', 'gnr'),
        ):
            with self.subTest(place=place):
                candidate = copy.deepcopy(self.missing_venue_upload()['candidate_intake'])
                candidate['service_entity'] = ''
                initial = review_intake_with_profile_evidence(candidate, self.paths)
                questions = {item['field']: item['number'] for item in initial['questions']}
                self.assertIn('service_entity', questions)
                result = apply_numbered_answers({'intake': initial['intake'],
                    'answer_text': f"{questions['service_entity']}. {place}"}, self.paths)
                self.assertEqual(result['status'], 'ready', result)
                self.assert_changed_venue_paragraph(result['intake'], place, entity_type)

    def test_explicit_custom_venue_phrase_is_preserved_when_default_alias_changes(self):
        self.enable(venue=True)
        candidate = copy.deepcopy(self.missing_venue_upload()['candidate_intake'])
        place = 'Esquadra da PSP de Manual City'
        phrase = 'em diligência presencial realizada na Esquadra da PSP de Manual City'
        candidate['service_place_phrase'] = phrase
        candidate['service_entity'] = place
        effective, paragraph = self.assert_changed_venue_paragraph(candidate, place, 'psp')
        self.assertEqual(effective['service_place_phrase'], phrase)
        self.assertIn(phrase, paragraph)


if __name__ == '__main__':
    unittest.main()
