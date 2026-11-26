"""Fictional exact-source location answers through ordinary upload and review."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import AppPaths, recover_source_upload, review_intake_with_profile_evidence
from honorarios_app.source_location import propose_verified_source_venue


CASE = '810/26.0TSTXX'
DAY = '2026-10-03'
CITY = 'Fictional City'
COURT = 'Tribunal de Fictional City'
COURT_DOMAIN = 'tribunais' + '.org.pt'
RECIPIENT = 'fictional.city@' + COURT_DOMAIN


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


class ConfirmedLocationIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='confirmed-location-integration-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        profiles = json.loads(self.paths.personal_profiles.read_text(encoding='utf-8'))
        self.profile = profiles['profiles'][0]
        self.profile['travel_distances_by_city'][CITY] = 39
        save(self.paths.personal_profiles, profiles)
        save(self.paths.service_profiles, {'court_mp_generic': {'defaults': {
            'service_entity_type': 'court', 'entities_differ': False,
            'claim_transport': True, 'transport': {'round_trip_phrase': 'ida_volta'}}}})
        self.preferences = {'capture_date_is_service_date': True, 'photo_city_court': True,
            'missing_venue_is_city_court': True,
            'city_courts': {CITY: {'payment_entity': COURT, 'addressee': COURT, 'recipient_email': RECIPIENT}}}
        directory = json.loads(self.paths.court_emails.read_text(encoding='utf-8'))
        directory.append({'payment_entity': COURT, 'recipient_email': RECIPIENT})
        save(self.paths.court_emails, directory)
        raw = BytesIO()
        image = Image.new('RGB', (80, 100), 'white')
        exif = image.getexif()
        exif[36867] = DAY.replace('-', ':') + ' 10:30:00'
        image.save(raw, format='JPEG', exif=exif)
        self.content = raw.getvalue()
        self.source_hash = hashlib.sha256(self.content).hexdigest()
        offline = patch('socket.socket.connect', side_effect=AssertionError('Offline synthetic check'))
        offline.start()
        self.addCleanup(offline.stop)

    def entry(self, kind='ministerio_publico', **changes):
        agency = {'ministerio_publico': 'Ministério Público', 'police': 'Polícia Judiciária',
                  'gnr': 'Guarda Nacional Republicana'}[kind]
        return {'id': 'fictional-saved-source', 'source_sha256': self.source_hash, 'case_number': CASE,
            'allowed_service_dates': [DAY], 'confirmation_date': '2026-11-13',
            'evidence_reference': 'fictional-confirmation', 'capture_city': CITY,
            'host': {'service_place': COURT if kind == 'ministerio_publico' else f'Posto da GNR de {CITY}',
                     'service_entity': agency, 'service_entity_type': kind, 'entities_differ': True},
            'payment_route': {'payment_entity': COURT, 'addressee': COURT, 'recipient_email': RECIPIENT},
            **changes}

    def upload(self, record=None, text=None, content=None):
        self.preferences['confirmed_source_locations'] = [record or self.entry()]
        save(self.paths.ai_config.with_name('photo-defaults.local.json'), self.preferences)
        text = text or f'MINISTÉRIO PÚBLICO\nProcesso: {CASE}\nAuto de interrogatório de arguido.'
        return recover_source_upload(filename='fictional.jpg', content_type='image/jpeg',
            content=content or self.content, source_kind='photo', profile_name='auto', visible_text=text,
            ai_recovery_mode='off', paths=self.paths)

    def review(self, candidate):
        return review_intake_with_profile_evidence(deepcopy(candidate), self.paths)

    def test_no_gps_ai_off_upload_then_review_preserves_saved_host_and_original_mp_agency(self):
        text = f'Assinatura digital\r\nMINISTÉRIO PÚBLICO\r\nProcesso: {CASE}\r\nAuto de interrogatório.'
        uploaded = self.upload(text=text)
        self.assertEqual(uploaded['ai_recovery']['status'], 'skipped')
        candidate = uploaded['candidate_intake']
        for index in range(3):
            with self.subTest(review=index):
                reviewed = self.review(candidate)
                candidate = reviewed['intake']
                self.assertEqual(candidate['source_sha256'], self.source_hash)
                self.assertEqual(candidate['source_text'], text)
                self.assertEqual(candidate['service_date'], DAY)
                self.assertEqual(candidate['service_place'], COURT)
                self.assertEqual(candidate['service_entity_type'], 'ministerio_publico')
                self.assertIn('Público', candidate['service_entity'])
                self.assertTrue(candidate['entities_differ'])
                self.assertEqual(candidate['payment_entity'], COURT)
                self.assertEqual(candidate['recipient_email'], RECIPIENT)
                self.assertEqual(candidate['transport']['destination'], CITY)
                self.assertEqual(candidate['transport']['km_one_way'], 39)
                self.assertNotIn('missing_noncourt_venue', candidate)
                proof = candidate['confirmed_source_location_evidence']
                self.assertNotIn('travel', proof['fact_groups'])
                self.assertEqual(proof['applied_fields']['transport.km_one_way'], 39)
                fields = reviewed['review_evidence']['field_evidence']
                host = next(row for row in fields if row['field'] == 'service_place')
                self.assertEqual(host['source'], 'previously_confirmed_source_location')
                self.assertIn('Saved for reuse on', host['reason'])
                agency = next(row for row in fields if row['field'] == 'confirmed_source_agency')
                self.assertNotEqual(agency['source'], 'previously_confirmed_source_location')
                self.assertNotIn('photo_metadata_city', candidate)

    def test_pj_host_and_payer_remain_distinct_and_manual_clear_stays_cleared(self):
        text = f'POLÍCIA JUDICIÁRIA\nDIRETORIA DO SUL\nNUIPC: {CASE}\nAUTO DE INTERROGATÓRIO DE ARGUIDO'
        candidate = self.upload(self.entry('police'), text)['candidate_intake']
        for _ in range(2):
            candidate = self.review(candidate)['intake']
            self.assertEqual(candidate['service_entity'], 'Polícia Judiciária')
            self.assertEqual(candidate['service_entity_type'], 'police')
            self.assertEqual(candidate['service_place'], f'Posto da GNR de {CITY}')
            self.assertEqual(candidate['payment_entity'], COURT)
            self.assertEqual(candidate['transport']['km_one_way'], 39)
        candidate['service_place'] = ''
        candidate['review_cleared_fields'] = ['service_place']
        for _ in range(2):
            reviewed = self.review(candidate)
            candidate = reviewed['intake']
            self.assertEqual(candidate['service_place'], '')
            self.assertNotIn('physical_host', candidate['confirmed_source_location_evidence']['fact_groups'])

    def test_source_case_or_date_change_revokes_learned_host_and_downstream_travel(self):
        original = self.upload()['candidate_intake']
        original = self.review(original)['intake']
        for changes in ({'case_number': '811/26.0TSTXX'}, {'service_date': '2026-10-04'},
                        {'source_sha256': 'b' * 64}):
            with self.subTest(changes=changes):
                candidate = deepcopy(original)
                candidate.update(changes)
                reviewed = self.review(candidate)
                current = reviewed['intake']
                self.assertNotEqual(current.get('service_place'), COURT)
                self.assertNotEqual((current.get('transport') or {}).get('km_one_way'), 39)
                self.assertNotIn('confirmed_source_location_evidence', current)

    def test_manual_host_route_and_zero_are_not_reasserted_on_repeated_reviews(self):
        text = f'POLÍCIA JUDICIÁRIA\nNUIPC {CASE}\nAUTO DE INTERROGATÓRIO'
        candidate = self.upload(self.entry('police'), text)['candidate_intake']
        candidate.update(service_place=COURT, service_place_phrase='', payment_entity='Example Court')
        candidate['transport'].update(destination='Manual City', km_one_way=0)
        for _ in range(3):
            candidate = self.review(candidate)['intake']
            self.assertEqual(candidate['service_place'], COURT)
            self.assertEqual(candidate['payment_entity'], 'Example Court')
            self.assertEqual(candidate['transport']['destination'], 'Manual City')
            self.assertEqual(candidate['transport']['km_one_way'], 0)
            self.assertNotIn('physical_host', candidate['confirmed_source_location_evidence']['fact_groups'])

    def test_same_photo_learned_case_does_not_leak_to_uncovered_case(self):
        text = f'MINISTÉRIO PÚBLICO\nProcesso {CASE}\nProcesso 811/26.0TSTXX\nAuto de interrogatório.'
        result = self.upload(text=text)
        rows = {row['candidate_intake']['case_number']: row['candidate_intake']
                for row in result['case_candidates']}
        self.assertEqual(rows[CASE]['service_place'], COURT)
        self.assertNotEqual(rows['811/26.0TSTXX'].get('service_place'), COURT)
        self.assertNotEqual(rows['811/26.0TSTXX'].get('transport', {}).get('km_one_way'), 39)
        self.assertNotIn('confirmed_source_location_evidence', rows['811/26.0TSTXX'])

    def test_invalid_catalog_and_conflicting_source_hold_review_visibly(self):
        uploaded = self.upload()
        self.preferences['confirmed_source_locations'][0]['allowed_service_dates'] = ['2026-02-30']
        save(self.paths.ai_config.with_name('photo-defaults.local.json'), self.preferences)
        reviewed = self.review(uploaded['candidate_intake'])
        self.assertEqual(reviewed['status'], 'error')
        self.assertIn('Saved source-location confirmation needs review', reviewed['message'])
        self.assertFalse(reviewed['send_allowed'])
        conflict = self.entry('police')
        uploaded = self.upload(conflict, f'GUARDA NACIONAL REPUBLICANA\nProcesso {CASE}')
        self.assertEqual(uploaded['review']['status'], 'error')

    def test_confirmed_distance_is_profile_and_origin_bound_without_global_lookup(self):
        record = self.entry('gnr', travel={'personal_profile_id': self.profile['id'],
            'origin': self.profile['travel_origin_label'], 'destination': CITY, 'km_one_way': 105})
        candidate = self.upload(record, f'GUARDA NACIONAL REPUBLICANA\nProcesso {CASE}')['candidate_intake']
        self.assertEqual(candidate['transport']['km_one_way'], 105)
        self.assertEqual(self.review(candidate)['intake']['transport']['km_one_way'], 105)
        for origin in ('Different Origin', ''):
            changed = deepcopy(candidate)
            changed['transport']['origin'] = origin
            if not origin:
                changed['review_cleared_fields'] = ['transport.origin']
            reviewed = self.review(changed)['intake']
            self.assertNotEqual(reviewed['transport'].get('km_one_way'), 105)
            self.assertNotIn('travel', reviewed['confirmed_source_location_evidence']['fact_groups'])

    def test_full_mp_agency_grounded_by_photo_policy_retries_same_verified_venue_rule(self):
        self.preferences['verified_gps_areas'] = [{'city': CITY, 'latitude': 0, 'longitude': 0,
            'radius_m': 100, 'source_url': 'https://places.example.test/fictional-city'}]
        self.preferences['verified_gps_venues'] = [{'id': 'fictional-mp-court', 'city': CITY,
            'service_entity': f'Ministério Público de {CITY}', 'service_entity_type': 'ministerio_publico',
            'service_place': COURT, 'latitude': 0, 'longitude': 0, 'radius_m': 50,
            'source_urls': ['https://places.example.test/fictional-premises'],
            'required_source_phrases': ['ministerio publico', 'local criminal', f'inqueritos de {CITY}']}]
        save(self.paths.ai_config.with_name('photo-defaults.local.json'), self.preferences)
        profiles = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))
        profiles['explicit_court'] = {'defaults': {'service_entity_type': 'court',
            'service_entity': 'Explicit Court', 'service_place': 'Explicit Service Venue'}}
        save(self.paths.service_profiles, profiles)
        text = (f'MINISTÉRIO PÚBLICO - Procuradoria da República da Comarca de {CITY}\n'
                f'Procuradoria do Juízo Local Criminal- 1ª Sec Inquéritos de {CITY}\n'
                f'Palácio da Justiça de {CITY} - Praça Fictional\nProcesso {CASE}\n'
                'NOTA DE NOTIFICAÇÃO\nPara comparecer no Juízo Local Criminal.\n'
                'Condenado no pagamento das despesas ocasionadas pela sua não comparência.')
        for gps, profile, suffix in (({'latitude': 0, 'longitude': 0}, 'auto', ''),
                                     ({'latitude': .01, 'longitude': 0}, 'auto', ''),
                                     (None, 'auto', ''),
                                     ({'latitude': 0, 'longitude': 0}, 'explicit_court', ''),
                                     ({'latitude': 0, 'longitude': 0}, 'auto',
                                      '\nDiligência realizada no Posto da GNR de Other City.')):
            with self.subTest(gps=gps, profile=profile, suffix=suffix):
                metadata = {'exif_date': DAY}
                if gps:
                    metadata['gps_coordinates'] = {**gps, 'source': 'exif_gps'}
                calls = []
                def trace(candidate, **kwargs):
                    calls.append(deepcopy(candidate))
                    return propose_verified_source_venue(candidate, **kwargs)
                with patch('honorarios_app.services.image_metadata_from_bytes', return_value=metadata), \
                     patch('honorarios_app.services.propose_verified_source_venue', side_effect=trace):
                    uploaded = recover_source_upload(filename='fictional.jpg', content_type='image/jpeg',
                        content=self.content, source_kind='photo', profile_name=profile,
                        visible_text=text+suffix, ai_recovery_mode='off', paths=self.paths)
                candidate = uploaded['candidate_intake']
                positive = gps == {'latitude': 0, 'longitude': 0} and profile == 'auto' and not suffix
                if positive:
                    self.assertEqual(calls[0].get('service_entity_type'), 'court')
                    self.assertFalse(calls[0].get('service_entity'))
                    self.assertEqual(calls[-1]['service_entity_type'], 'ministerio_publico')
                    self.assertEqual(candidate['service_place'], COURT)
                    self.assertEqual(candidate['service_entity_type'], 'ministerio_publico')
                    self.assertTrue(candidate['entities_differ'])
                    self.assertEqual(candidate['payment_entity'], COURT)
                    self.assertEqual(candidate['transport']['km_one_way'], 39)
                    self.assertEqual(candidate['source_location_evidence']['source'], 'verified_gps_source_venue')
                    edited = deepcopy(candidate)
                    edited['service_place'] = ''
                    edited['review_cleared_fields'] = ['service_place']
                    self.assertEqual(self.review(edited)['intake']['service_place'], '')
                elif profile == 'auto':
                    self.assertNotEqual(candidate.get('service_place'), COURT)
                else:
                    # An explicit generic court profile may use its ordinary
                    # city-court default, but cannot acquire the MP/GPS proof.
                    self.assertEqual(candidate['auto_profile']['mode'], 'explicit_profile')
                    self.assertNotIn('source_location_evidence', candidate)
                    self.assertEqual(len(calls), 1)
                self.assertEqual(candidate['source_text'], text+suffix)
                self.assertNotIn('confirmed_source_location_evidence', candidate)

    def test_reusable_venues_apply_to_new_originals_cases_and_days_without_source_memory(self):
        geometry = {'geometry_basis': 'user_confirmed_photo_venue',
                    'confirmation_source_sha256': 'a' * 64, 'confirmation_date': '2026-11-01',
                    'source_city_basis': 'verified_gps', 'radius_m': 50,
                    'source_urls': ['https://places.example.test/location-context']}
        self.preferences.update(confirmed_source_locations=[], verified_gps_areas=[{
            'city': CITY, 'latitude': .0015, 'longitude': 0, 'radius_m': 400,
            'source_url': 'https://places.example.test/city-context'}], verified_gps_venues=[
            {'id': 'reusable-mp', 'city': CITY, 'latitude': 0, 'longitude': 0,
             'service_entity': f'Ministério Público de {CITY}', 'service_entity_type': 'ministerio_publico',
             'service_place': COURT, 'required_source_phrases': ['ministerio publico', 'local criminal'], **geometry},
            {'id': 'reusable-pj-host', 'city': CITY, 'latitude': .003, 'longitude': 0,
             'service_entity': 'Polícia Judiciária', 'service_entity_type': 'police',
             'service_place': f'Posto da GNR de {CITY}',
             'required_source_phrases': ['policia judiciaria', 'diretoria do sul'], **geometry},
            # This old MP point overlaps the PJ host. Its different agency does
            # not turn a uniquely matching PJ source into ambiguous premises.
            {'id': 'old-mp', 'city': CITY, 'latitude': .003, 'longitude': 0, 'radius_m': 100,
             'service_entity': f'Ministério Público de {CITY}', 'service_entity_type': 'ministerio_publico',
             'service_place': f'Ministério Público de {CITY}',
             'required_source_phrases': ['ministerio publico', f'local criminal de {CITY}'],
             'source_urls': ['https://places.example.test/old-mp']}])
        save(self.paths.ai_config.with_name('photo-defaults.local.json'), self.preferences)
        variants = [
            ('ministerio_publico', 'MINISTÉRIO PÚBLICO - Procuradoria da\nProcuradoria do Juízo Local Criminal-', ''),
            ('ministerio_publico', 'MINISTÉRIO PÚBLICO\nProcuradoria do Juízo Local Criminal - Secção', ''),
            ('ministerio_publico', 'Assinado em 19-11-2026, por Pessoa Exemplo, Procurador da República\n'
             f'MINISTÉRIO PÚBLICO\nProcuradoria do Juízo Local Criminal - Secção de Inquéritos de {CITY}', ''),
            ('ministerio_publico', 'Assinado em 30-10-2026, por\nPessoa Exemplo, Procurador da República\n'
             f'MINISTÉRIO PÚBLICO\nProcuradoria do Juízo Local Criminal- 1ª Sec Inquéritos de {CITY}', ''),
            ('ministerio_publico', f'MINISTÉRIO PÚBLICO\nProcuradoria do Juízo Local Criminal de {CITY}',
             '\nI. Vistos os autos.\nII. O militar da GNR apresentou requerimento.'),
            ('ministerio_publico', f'[…]radoria da República da Comarca de {CITY}\n'
             f'[…]Local Criminal- 1ª Sec Inquéritos de {CITY}', ''),
            ('police', 'MINISTÉRIO DA JUSTIÇA\nPOLÍCIA JUDICIÁRIA\nDIRETORIA DO SUL', ''),
            ('police', 'MINISTÉRIO DA JUSTIÇA\nPOLÍCIA JUDICIÁRIA\nDIRETORIA DO SUL', ''),
        ]
        hashes = set()
        for index, (kind, header, body) in enumerate(variants):
            case, day = f'{981+index}/26.0TSTXX', f'2026-11-{13+index:02d}'
            text = header + f'\nProcesso: {case}' + body
            if index % 2:
                text = text.replace('\n', '\r\n')
            raw = BytesIO()
            image = Image.new('RGB', (80, 100), (index, 0, 0))
            exif = image.getexif()
            exif[36867] = day.replace('-', ':') + ' 10:30:00'
            image.save(raw, format='JPEG', exif=exif)
            content = raw.getvalue()
            metadata = {'exif_date': day, 'gps_coordinates': {
                'latitude': .003 if kind == 'police' else 0, 'longitude': 0, 'source': 'exif_gps'}}
            with self.subTest(index=index), patch('honorarios_app.services.image_metadata_from_bytes', return_value=metadata):
                result = recover_source_upload(filename=f'new-original-{index}.jpg', content_type='image/jpeg',
                    content=content, source_kind='photo', profile_name='auto', visible_text=text,
                    ai_recovery_mode='off', paths=self.paths)
            candidate = result['candidate_intake']
            for flag in ('claim_interpreting', 'claim_transport'):
                if not isinstance(candidate.get(flag), bool):
                    candidate[flag] = True  # Same standing choice as normal browser adoption.
            for _ in range(2):
                reviewed = self.review(candidate)
                candidate = reviewed['intake']
                self.assertEqual(candidate['case_number'], case)
                self.assertEqual(candidate['service_date'], day)
                self.assertEqual(candidate['source_text'], text)
                self.assertEqual(candidate['source_sha256'], hashlib.sha256(content).hexdigest())
                self.assertEqual(candidate['service_entity_type'], kind)
                self.assertEqual(candidate['service_place'], f'Posto da GNR de {CITY}' if kind == 'police' else COURT)
                self.assertEqual(candidate['payment_entity'], COURT)
                self.assertEqual(candidate['recipient_email'], RECIPIENT)
                self.assertEqual(candidate['transport']['km_one_way'], 39)
                self.assertNotEqual(candidate['transport']['km_one_way'], 105)
                self.assertTrue(candidate['entities_differ'])
                self.assertNotIn('confirmed_source_location_evidence', candidate)
                proof = candidate['source_location_evidence']
                self.assertEqual(proof['source_sha256'], candidate['source_sha256'])
                self.assertNotEqual(proof['source_sha256'], proof['confirmation_source_sha256'])
                fields = reviewed['review_evidence']['field_evidence']
                host = next(row for row in fields if row['field'] == 'service_place')
                self.assertEqual(host['source'], 'reusable_verified_gps_source_venue')
                self.assertIn('previously user-confirmed venue point', host['reason'])
                self.assertNotIn('support the postal address', host['reason'])
                heading = next(row for row in fields if row['field'] == 'source_venue_header')
                self.assertTrue(all(line in text for line in heading['value'].splitlines()))
            hashes.add(candidate['source_sha256'])
        self.assertEqual(len(hashes), len(variants))


if __name__ == '__main__':
    unittest.main()
