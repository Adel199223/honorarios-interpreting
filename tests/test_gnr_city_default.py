"""Independent synthetic boundaries for the user's opt-in GNR city policy."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from pypdf import PdfReader

from honorarios_app import services
from honorarios_app.photo_defaults import apply_capture_city_answer, apply_photo_defaults
from scripts.generate_pdf import IntakeError
import test_photo_defaults as fixtures


FLAG = 'missing_gnr_venue_is_capture_city'
GNR_PLACE = 'GNR de ' + fixtures.CAPTURE_CITY
HEADER = 'GUARDA NACIONAL REPUBLICANA\nComando Territorial de Header City\nNúcleo de Investigação'
TEXT = HEADER + '\nProcesso ' + fixtures.CASE_NUMBER + '\nAuto de compromisso do intérprete.'


class GnrCaptureCityDefaultTests(unittest.TestCase):
    upload = fixtures.PhotoDefaultTests.upload
    city_answer = fixtures.PhotoDefaultTests.city_answer
    question_fields = staticmethod(fixtures.PhotoDefaultTests.question_fields)

    def setUp(self):
        fixtures.PhotoDefaultTests.setUp(self)
        profiles = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))
        profiles['court_mp_generic'] = {'defaults': {
            'service_entity_type': 'court', 'entities_differ': False,
            'claim_transport': True, 'transport': {'round_trip_phrase': 'ida_volta'}}}
        fixtures.write_json(self.paths.service_profiles, profiles)

    def enable(self, enabled=True, **changes):
        preferences = {'capture_date_is_service_date': True, 'photo_city_court': True,
                       'missing_venue_is_city_court': True, FLAG: enabled,
                       'city_courts': {fixtures.CAPTURE_CITY: fixtures.court_record()}, **changes}
        fixtures.write_json(self.defaults_path, preferences)
        return preferences

    def gnr_upload(self, *, text=TEXT, fields=None, local_city=True, metadata_override=None, **kwargs):
        metadata = {'exif_date': fixtures.CAPTURE_DATE}
        capture_city = kwargs.get('photo_city', fixtures.CAPTURE_CITY)
        if local_city and capture_city is not None:
            metadata.update(photo_metadata_city=capture_city, photo_metadata_city_source='embedded_location_created')
        if metadata_override is not None:
            metadata = metadata_override
        with patch('honorarios_app.services.image_metadata_from_bytes', return_value=metadata):
            return self.upload(visible_text=text, independent_visible_text=False, ai_fields={
                'service_entity': 'Guarda Nacional Republicana — Comando Territorial de Header City',
                'service_entity_type': 'gnr', 'service_place': '', 'service_place_phrase': '', 'locality': '',
                **(fields or {})}, **kwargs)

    def test_photo_uses_capture_city_not_command_district_and_keeps_honest_bound_proof(self):
        self.enable()
        result = self.gnr_upload()
        intake = result['candidate_intake']
        self.assertEqual(result['review']['status'], 'ready', result['review'])
        self.assertEqual(intake['service_place'], GNR_PLACE)
        self.assertEqual(intake['service_entity'], GNR_PLACE)
        self.assertEqual(intake['service_entity_type'], 'gnr')
        self.assertTrue(intake['entities_differ'])
        self.assertEqual(intake['payment_entity'], fixtures.CAPTURE_COURT)
        self.assertEqual(intake['recipient_email'], fixtures.CAPTURE_RECIPIENT)
        self.assertEqual(intake['service_date'], fixtures.CAPTURE_DATE)
        self.assertEqual(intake['transport']['km_one_way'], 12)
        proof = intake['source_location_evidence']
        self.assertEqual(proof['source'], 'gnr_capture_city_default')
        self.assertEqual(proof['source_sha256'], intake['source_sha256'])
        self.assertEqual(proof['source_text_sha256'], hashlib.sha256(intake['source_text'].encode('utf-8')).hexdigest())
        self.assertEqual(proof['city'], fixtures.CAPTURE_CITY)
        self.assertEqual(proof['service_place'], GNR_PLACE)
        self.assertTrue(proof['editable'])
        self.assertNotIn('distance_m', proof)
        self.assertNotIn('service_place', self.question_fields(result))
        self.assertNotIn('Header City', intake['service_place_phrase'])
        prepared = services.prepare_intakes([intake], self.paths)
        pdf_text = ' '.join(' '.join(page.extract_text() or '' for page in PdfReader(prepared['items'][0]['pdf']).pages).split())
        self.assertIn(GNR_PLACE, pdf_text)
        self.assertNotIn('Header City', pdf_text)

    def test_automatic_fallback_venue_and_route_cannot_masquerade_as_user_edits(self):
        self.enable()
        profiles = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))
        profiles.pop('court_mp_generic')
        profiles['example_interpreting']['defaults']['transport'].update(destination='Old Profile City', km_one_way=99)
        fixtures.write_json(self.paths.service_profiles, profiles)
        result = self.gnr_upload()
        intake = result['candidate_intake']
        self.assertEqual(intake['auto_profile']['mode'], 'auto_fallback')
        self.assertEqual(intake['service_place'], GNR_PLACE)
        self.assertEqual(intake['transport']['km_one_way'], 12)
        self.assertNotEqual(intake['transport']['destination'], 'Old Profile City')

    def test_policy_requires_explicit_true_and_does_not_change_legacy_default(self):
        for setting in (False, None, 1, 'true'):
            with self.subTest(setting=setting):
                self.enable(setting)
                result = self.gnr_upload()
                self.assertFalse(result['candidate_intake'].get('service_place'))
                self.assertIn('service_place', self.question_fields(result))
                self.assertNotIn('source_location_evidence', result['candidate_intake'])

    def test_policy_remains_independent_of_the_court_venue_default(self):
        self.enable(missing_venue_is_city_court=False)
        result = self.gnr_upload()
        self.assertEqual(result['candidate_intake']['service_place'], GNR_PLACE)
        self.assertEqual(result['candidate_intake']['payment_entity'], fixtures.CAPTURE_COURT)

    def test_source_header_city_alone_cannot_supply_missing_capture_city(self):
        self.enable()
        result = self.gnr_upload(photo_city=None)
        self.assertFalse(result['candidate_intake'].get('service_place'))
        self.assertIn('photo_capture_city', self.question_fields(result))
        self.assertNotIn('source_location_evidence', result['candidate_intake'])

    def test_ai_city_without_local_capture_evidence_cannot_enable_gnr_default(self):
        self.enable()
        result = self.gnr_upload(local_city=False)
        self.assertFalse(result['candidate_intake'].get('service_place'))
        self.assertIn('service_place', self.question_fields(result))
        self.assertNotIn('source_location_evidence', result['candidate_intake'])

    def test_explicit_capture_city_answer_applies_without_another_provider_read(self):
        self.enable()
        result = self.gnr_upload(photo_city=None)
        answered = self.city_answer(result['candidate_intake'])
        self.assertEqual(answered['intake']['service_place'], GNR_PLACE)
        self.assertEqual(answered['intake']['source_location_evidence']['source'], 'gnr_capture_city_default')
        self.assertEqual(answered['intake']['service_date'], fixtures.CAPTURE_DATE)
        self.assertNotIn('service_place', {item['field'] for item in answered.get('questions', [])})
        self.assertFalse(any('does not establish the physical' in warning
                             for warning in answered['intake'].get('ai_recovery', {}).get('warnings', [])))

    def test_other_agencies_and_pj_context_cannot_use_the_gnr_policy(self):
        self.enable()
        variants = [('POLÍCIA DE SEGURANÇA PÚBLICA', 'Polícia de Segurança Pública', 'psp'),
                    ('MINISTÉRIO PÚBLICO\nProcuradoria da República', 'Ministério Público', 'ministerio_publico'),
                    ('POLÍCIA JUDICIÁRIA\nDiretoria do Sul', 'Polícia Judiciária', 'police'),
                    (HEADER + '\nDiligência da Polícia Judiciária', 'Guarda Nacional Republicana', 'gnr'),
                    (HEADER + '\nPOLÍCIA DE SEGURANÇA PÚBLICA', 'Guarda Nacional Republicana', 'gnr')]
        for heading, agency, kind in variants:
            with self.subTest(agency=agency, heading=heading):
                result = self.gnr_upload(text=heading + '\nProcesso ' + fixtures.CASE_NUMBER,
                                         fields={'service_entity': agency, 'service_entity_type': kind})
                self.assertNotEqual(result['candidate_intake'].get('service_place'), GNR_PLACE)
                self.assertNotEqual(result['candidate_intake'].get('source_location_evidence', {}).get('source'),
                                    'gnr_capture_city_default')

    def test_gnr_reference_in_court_prose_or_forwarded_quote_is_not_own_heading(self):
        self.enable()
        for text in ('Tribunal de Header City\nNotifique a Guarda Nacional Republicana.\nProcesso ' + fixtures.CASE_NUMBER,
                     'From: fictional@example.test\nForwarded message\n' + TEXT,
                     'Auto de compromisso\nO processo foi remetido pela Guarda Nacional Republicana.'):
            with self.subTest(text=text):
                result = self.gnr_upload(text=text)
                self.assertNotEqual(result['candidate_intake'].get('service_place'), GNR_PLACE)
                self.assertNotEqual(result['candidate_intake'].get('source_location_evidence', {}).get('source'),
                                    'gnr_capture_city_default')

    def test_named_station_and_other_physical_host_take_priority(self):
        self.enable()
        for venue, extra in [('Posto da GNR de Other City', '\nPosto da GNR de Other City'),
                             ('Hospital de Other City', '\nLocal da diligência: Hospital de Other City')]:
            with self.subTest(venue=venue):
                result = self.gnr_upload(text=HEADER + extra + '\nAuto de compromisso do intérprete.',
                                         fields={'service_place': venue, 'service_place_phrase': ''})
                self.assertEqual(result['candidate_intake']['service_place'], venue)
                self.assertNotEqual(result['candidate_intake'].get('source_location_evidence', {}).get('source'),
                                    'gnr_capture_city_default')

    def test_selected_profile_and_notification_pdf_do_not_receive_photo_policy(self):
        self.enable()
        selected = self.gnr_upload(service_profile='example_interpreting')
        self.assertNotEqual(selected['candidate_intake'].get('service_place'), GNR_PLACE)
        self.assertNotEqual(selected['candidate_intake'].get('source_location_evidence', {}).get('source'),
                            'gnr_capture_city_default')
        pdf = self.gnr_upload(source_kind='notification_pdf')
        self.assertNotEqual(pdf['candidate_intake'].get('service_place'), GNR_PLACE)
        self.assertNotIn('source_location_evidence', pdf['candidate_intake'])

    def test_capture_city_answer_preserves_explicit_blank_venue_profile_entity_and_type(self):
        preferences = self.enable()
        profiles = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))
        profiles['example_interpreting']['defaults'].update(
            service_place='', service_place_phrase='', service_entity='Chosen physical host',
            service_entity_type='other', entities_differ=True)
        fixtures.write_json(self.paths.service_profiles, profiles)
        result = self.gnr_upload(photo_city=None, service_profile='example_interpreting')
        intake = copy.deepcopy(result['candidate_intake'])
        apply_capture_city_answer(intake, fixtures.CAPTURE_CITY, preferences=preferences,
                                  directory=json.loads(self.paths.court_emails.read_text(encoding='utf-8')))
        intake = services.review_intake_with_profile_evidence(intake, self.paths)['intake']
        self.assertEqual(intake['service_entity'], 'Chosen physical host')
        self.assertEqual(intake['service_entity_type'], 'other')
        self.assertFalse(intake.get('service_place'))
        self.assertNotEqual(intake.get('source_location_evidence', {}).get('source'), 'gnr_capture_city_default')

    def test_capture_city_answer_preserves_manually_changed_agency_fields(self):
        self.enable()
        original = self.gnr_upload(photo_city=None)['candidate_intake']
        for changes in ({'service_entity': 'Chosen physical host'}, {'service_entity_type': 'other'}):
            with self.subTest(changes=changes):
                intake = {**copy.deepcopy(original), **changes}
                answered = self.city_answer(intake)['intake']
                for field, value in changes.items():
                    self.assertEqual(answered[field], value)
                self.assertFalse(answered.get('service_place'))
                self.assertNotEqual(answered.get('source_location_evidence', {}).get('source'), 'gnr_capture_city_default')

    def test_two_named_stations_remain_unresolved_instead_of_receiving_city_default(self):
        source = (HEADER + '\nPosto da GNR de Other City\nPosto da GNR de Third City\n'
                  'Processo ' + fixtures.CASE_NUMBER + '\nAUTO DE COMPROMISSO')
        for court_venue_enabled in (True, False):
            with self.subTest(court_venue_enabled=court_venue_enabled):
                self.enable(missing_venue_is_city_court=court_venue_enabled)
                result = self.gnr_upload(text=source)
                self.assertFalse(result['candidate_intake'].get('service_place'))
                self.assertEqual(result['review']['status'], 'needs_info')
                self.assertNotEqual(result['candidate_intake'].get('source_location_evidence', {}).get('source'),
                                    'gnr_capture_city_default')

    def test_conflicting_capture_cities_and_invalid_gps_status_leave_venue_unresolved(self):
        preferences = self.enable()
        recovery = {'status': 'ok', 'fields': {'service_entity': 'Guarda Nacional Republicana', 'service_entity_type': 'gnr'}}
        for meta in ({'photo_metadata_city': fixtures.CAPTURE_CITY, 'visible_metadata_city': 'Other City'},
                     {'photo_metadata_city': fixtures.CAPTURE_CITY, 'gps_city_match': {'status': 'ambiguous'}},
                     {'photo_metadata_city': fixtures.CAPTURE_CITY, 'gps_city_match': {'status': 'invalid_configuration'}}):
            with self.subTest(meta=meta):
                candidate = {'source_kind': 'photo', 'source_text': TEXT, 'source_sha256': 'b' * 64}
                apply_photo_defaults(candidate, preferences=preferences, metadata=meta,
                                     ai_recovery=copy.deepcopy(recovery), directory=[])
                self.assertNotEqual(candidate.get('service_place'), GNR_PLACE)
                self.assertNotEqual(candidate.get('source_location_evidence', {}).get('source'), 'gnr_capture_city_default')

    def test_manual_venue_edit_and_clear_survive_review_with_no_stale_location_phrase(self):
        self.enable()
        original = self.gnr_upload()['candidate_intake']
        changed = copy.deepcopy(original)
        changed['service_place'] = 'Posto da GNR de Manual City'
        reviewed = services.review_intake_with_profile_evidence(changed, self.paths)
        intake = reviewed['intake']
        self.assertEqual(intake['service_place'], 'Posto da GNR de Manual City')
        self.assertNotIn(GNR_PLACE, intake.get('service_place_phrase', ''))
        self.assertNotEqual(intake['transport'].get('km_one_way'), 12)
        cleared = copy.deepcopy(original)
        cleared.update(service_place='', review_cleared_fields=['service_place'])
        review = services.review_intake_with_profile_evidence(cleared, self.paths)
        self.assertFalse(review['intake'].get('service_place'))
        self.assertIn('service_place', {item['field'] for item in review.get('questions', [])})

    def test_claim_choice_and_manual_distance_are_not_reset_on_re_review(self):
        self.enable()
        intake = self.gnr_upload()['candidate_intake']
        intake.update(claim_interpreting=True, claim_transport=False)
        intake['transport']['km_one_way'] = 37
        reviewed = services.review_intake_with_profile_evidence(intake, self.paths)['intake']
        self.assertTrue(reviewed['claim_interpreting'])
        self.assertFalse(reviewed['claim_transport'])
        self.assertEqual(reviewed['transport']['km_one_way'], 37)

    def test_manual_zero_and_route_override_survive_a_later_venue_edit(self):
        self.enable()
        original = self.gnr_upload()['candidate_intake']
        for destination, km in ((GNR_PLACE, 0), ('Manual route', 37)):
            with self.subTest(destination=destination, km=km):
                intake = copy.deepcopy(original)
                intake['transport'].update(destination=destination, km_one_way=km)
                services.apply_answer_to_intake(intake, 'service_place', 'Posto da GNR de Manual City')
                reviewed = services.review_intake_with_profile_evidence(intake, self.paths)['intake']
                self.assertEqual(reviewed['transport']['km_one_way'], km)
                if destination == 'Manual route':
                    self.assertEqual(reviewed['transport']['destination'], destination)

    def test_changed_source_identity_text_entity_or_city_cannot_display_old_policy_proof(self):
        self.enable()
        original = self.gnr_upload()['candidate_intake']
        changes = [{'source_sha256': 'c' * 64}, {'source_text': 'Different source text'},
                   {'service_entity': 'GNR de Other City'}, {'service_entity_type': 'other'},
                   {'photo_capture_city': 'Other City'}]
        for changed in changes:
            with self.subTest(changed=changed):
                review = services.review_intake_with_profile_evidence({**copy.deepcopy(original), **changed}, self.paths)
                self.assertFalse(any(row.get('source') == 'gnr_capture_city_default'
                                     for row in review['review_evidence']['field_evidence']))

    def test_more_specific_verified_gps_source_venue_takes_priority_over_city_default(self):
        host = GNR_PLACE + ' — Unit A'
        preferences = self.enable()
        preferences['verified_gps_areas'] = [{'city': fixtures.CAPTURE_CITY, 'latitude': 0, 'longitude': 0,
                                             'radius_m': 200, 'source_url': 'https://places.example.test/city'}]
        preferences['verified_gps_venues'] = [{'id': 'fictional-unit', 'city': fixtures.CAPTURE_CITY,
            'service_entity_type': 'gnr', 'service_entity': GNR_PLACE, 'service_place': host,
            'latitude': 0, 'longitude': 0, 'radius_m': 100,
            'required_source_phrases': ['Guarda Nacional Republicana', 'Núcleo de Investigação', fixtures.CAPTURE_CITY],
            'source_urls': ['https://places.example.test/unit']}]
        fixtures.write_json(self.defaults_path, preferences)
        text = 'GUARDA NACIONAL REPUBLICANA\nNúcleo de Investigação de ' + fixtures.CAPTURE_CITY + '\nAuto de compromisso'
        result = self.gnr_upload(text=text, fields={'service_entity': GNR_PLACE},
            metadata_override={'exif_date': fixtures.CAPTURE_DATE,
                               'gps_coordinates': {'latitude': 0, 'longitude': 0, 'source': 'exif_gps'}})
        self.assertEqual(result['candidate_intake']['service_place'], host)
        self.assertEqual(result['candidate_intake']['source_location_evidence']['source'], 'verified_gps_source_venue')

    def test_default_does_not_relax_sent_or_explicit_exclusion_guards(self):
        self.enable()
        result = self.gnr_upload()
        original = result['candidate_intake']
        fixtures.write_json(self.paths.duplicate_index, [{'case_number': fixtures.CASE_NUMBER,
                            'service_date': fixtures.CAPTURE_DATE, 'status': 'sent'}])
        review = services.review_intake_with_profile_evidence(original, self.paths)
        self.assertEqual(review['status'], 'duplicate')
        with self.assertRaises(IntakeError):
            services.prepare_intakes([original], self.paths)
        fixtures.write_json(self.paths.duplicate_index, [])
        fixtures.write_json(self.paths.duplicate_index.with_name('paper-submissions.local.json'), {
            'schema_version': 1, 'excluded_cases': [{'case_number': fixtures.CASE_NUMBER,
                'service_date': fixtures.CAPTURE_DATE, 'completion_evidence': 'user_confirmed_done'}]})
        review = services.review_intake_with_profile_evidence(original, self.paths)
        self.assertEqual(review['status'], 'excluded')
        with self.assertRaises(IntakeError):
            services.prepare_intakes([original], self.paths)

    def beringel_upload(self, *, city='Beringel', named_host='', body_address=False, gps=True,
                        city_court=False, configured_courts=None):
        # Public recurring pattern, entirely synthetic request/GPS/applicant.
        preferences = self.enable(photo_city_court=city_court)
        if city_court:
            preferences['city_courts']['Beringel'] = fixtures.court_record(
                'Tribunal de Beringel', 'fictional-beringel@' + fixtures.COURT_DOMAIN)
        if configured_courts is not None:
            preferences['city_courts'] = configured_courts
        preferences['verified_gps_areas'] = [{'city': city, 'latitude': 0, 'longitude': 0,
                                             'radius_m': 200, 'source_url': 'https://places.example.test/city'}]
        fixtures.write_json(self.defaults_path, preferences)
        profiles = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))
        profiles['gnr_beringel_beja_mp'] = {'defaults': {
            'payment_entity': 'Ministério Público de Beja',
            'addressee': 'Exmo. Senhor Procurador da República\nMinistério Público de Beja',
            'recipient_email': 'fictional-beja-mp@' + fixtures.COURT_DOMAIN,
            'service_entity': 'Guarda Nacional Republicana / Destacamento de Trânsito de Beja',
            'service_entity_type': 'gnr', 'entities_differ': True, 'service_place': 'Beringel',
            'service_place_phrase': 'em diligência da Guarda Nacional Republicana realizada em Beringel',
            'claim_transport': True, 'transport': {'origin': 'Example City', 'destination': 'Beringel',
                                                  'km_one_way': 46, 'round_trip_phrase': 'ida_volta'}}}
        fixtures.write_json(self.paths.service_profiles, profiles)
        address = 'Rua de Exemplo, 79, 7800-804 BERINGEL, Portugal'
        text = ('GUARDA NACIONAL REPUBLICANA\nCOMANDO TERRITORIAL DE BEJA\n'
                'DESTACAMENTO DE TRÂNSITO DE BEJA\nNÚCLEO DE INVESTIGAÇÃO\n')
        if not body_address:
            text += address + '\n'
        if named_host:
            text += named_host + '\n'
        text += 'AUTO DE COMPROMISSO\nProcesso ' + fixtures.CASE_NUMBER
        if body_address:
            text += '\nMorada da testemunha: ' + address
        metadata = {'exif_date': fixtures.CAPTURE_DATE}
        if gps:
            metadata['gps_coordinates'] = {'latitude': 0, 'longitude': 0, 'source': 'exif_gps'}
        return self.gnr_upload(text=text, photo_city=city, metadata_override=metadata,
                               fields={'service_entity': 'Guarda Nacional Republicana — Destacamento de Trânsito de Beja',
                                       'service_place': named_host})

    def test_gps_capture_city_and_issuer_postal_address_select_only_existing_gnr_profile(self):
        result = self.beringel_upload()
        intake = result['candidate_intake']
        self.assertEqual(intake['auto_profile']['profile_key'], 'gnr_beringel_beja_mp')
        self.assertTrue(intake['auto_profile']['auto_applied'])
        self.assertEqual(intake['service_place'], 'GNR de Beringel')
        self.assertEqual(intake['payment_entity'], 'Ministério Público de Beja')
        self.assertEqual(intake['recipient_email'], 'fictional-beja-mp@' + fixtures.COURT_DOMAIN)
        self.assertEqual(intake['transport']['km_one_way'], 46)
        self.assertEqual(intake['source_location_evidence']['source'], 'gnr_capture_city_default')

    def test_postal_city_profile_cannot_use_mismatched_or_ai_only_capture_city_or_body_address(self):
        for changes in ({'city': 'Beja'}, {'gps': False}, {'body_address': True}):
            with self.subTest(changes=changes):
                result = self.beringel_upload(**changes)
                self.assertNotEqual(result['candidate_intake']['auto_profile']['profile_key'], 'gnr_beringel_beja_mp')

    def test_enabled_unique_capture_city_court_mapping_wins_over_existing_profile_payer(self):
        result = self.beringel_upload(city_court=True)
        intake = result['candidate_intake']
        self.assertNotEqual(intake['auto_profile']['profile_key'], 'gnr_beringel_beja_mp')
        self.assertEqual(intake['service_place'], 'GNR de Beringel')
        self.assertEqual(intake['payment_entity'], 'Tribunal de Beringel')
        self.assertEqual(intake['recipient_email'], 'fictional-beringel@' + fixtures.COURT_DOMAIN)

    def test_ambiguous_or_incomplete_configured_court_cannot_fall_back_to_profile_payer(self):
        court = fixtures.court_record('Tribunal de Beringel', 'fictional-beringel@' + fixtures.COURT_DOMAIN)
        mappings = [{'Beringel': court, 'BERINGEL': {**court, 'payment_entity': 'Other Court'}},
                    {'Beringel': {'payment_entity': 'Tribunal de Beringel'}}]
        for mapping in mappings:
            with self.subTest(mapping=mapping):
                intake = self.beringel_upload(city_court=True, configured_courts=mapping)['candidate_intake']
                self.assertNotEqual(intake['auto_profile']['profile_key'], 'gnr_beringel_beja_mp')
                self.assertNotEqual(intake.get('payment_entity'), 'Ministério Público de Beja')
                self.assertNotEqual(intake.get('recipient_email'), 'fictional-beja-mp@' + fixtures.COURT_DOMAIN)

    def test_known_profile_city_match_cannot_override_an_explicit_different_station(self):
        result = self.beringel_upload(named_host='Posto da GNR de Serpa')
        intake = result['candidate_intake']
        self.assertEqual(intake['service_place'], 'Posto da GNR de Serpa')
        self.assertNotEqual(intake['auto_profile']['profile_key'], 'gnr_beringel_beja_mp')


if __name__ == '__main__':
    unittest.main()
