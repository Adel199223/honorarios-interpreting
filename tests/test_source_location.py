"""Synthetic-only coverage for optional GPS plus source venue inference."""
from copy import deepcopy
import hashlib
import math
import unittest

from honorarios_app.gps_city import EARTH_RADIUS_M
from honorarios_app.source_location import propose_verified_source_venue


def venue(**overrides):
    return {'id': 'fictional-unit', 'city': 'Fictional City', 'service_entity_type': 'gnr',
            'service_entity': 'GNR de Fictional City', 'service_place': 'GNR de Fictional City — Unit A',
            'latitude': 0, 'longitude': 0, 'radius_m': 200,
            'required_source_phrases': ['guarda nacional republicana', 'nucleo de investigacao',
                                        'rua de exemplo', 'fictional city'],
            'source_urls': ['https://places.example.test/unit-a'], **overrides}


def intake(**overrides):
    return {'source_kind': 'photo', 'source_sha256': 'a' * 64,
            'service_entity': 'Guarda Nacional Republicana', 'service_entity_type': 'gnr',
            'source_text': 'GUARDA NACIONAL REPUBLICANA\nNúcleo de Investigação\nRua de Exemplo\nFictional City\nAuto de compromisso',
            **overrides}


def metadata(**overrides):
    return {'gps_coordinates': {'latitude': 0, 'longitude': 0, 'source': 'exif_gps'},
            'gps_city_match': {'status': 'matched', 'city': 'Fictional City'}, **overrides}


class VerifiedSourceVenueTests(unittest.TestCase):

    def test_corroborated_header_accepts_admin_labels_but_rejects_quotes_and_abbreviated_police(self):
        entry = venue(id='fictional-mp', service_entity_type='ministerio_publico',
            service_entity='Ministério Público de Fictional City', service_place='Tribunal de Fictional City',
            required_source_phrases=['ministerio publico', 'local criminal', 'inqueritos de fictional city'])
        first = '[…]radoria da República da Comarca de Fictional City'
        unit = '[…]Local Criminal- 1ª Sec Inquéritos de Fictional City'
        text = 'Processo: 710/26.0TSTXX\nReferência: 12345678\n' + first + '\n' + unit + '\n[…]argo da Rua Antiga'
        candidate = intake(service_entity='Ministério Público', service_entity_type='ministerio_publico', source_text=text)
        self.assertTrue(self.propose(candidate, entries=[entry]))
        for clue in ('GNR', 'PSP', 'PJ', 'Judiciária', 'Nacional Republicana', 'Segurança Pública'):
            with self.subTest(competing=clue):
                self.assertEqual(self.propose({**candidate, 'source_text': text + '\n' + clue}, entries=[entry]), {})
        for left, right in (('"', '"'), ('“', '”'), ('«', '»'), ("'", "'")):
            with self.subTest(quotes=left):
                self.assertEqual(self.propose({**candidate, 'source_text': left + first + right + '\n' + left + unit + right}, entries=[entry]), {})
        cropped_entity = {**candidate, 'service_entity': first}
        self.assertTrue(self.propose(cropped_entity, entries=[entry]))
        self.assertEqual(self.propose({**cropped_entity, 'service_entity': first + ' OTHER'}, entries=[entry]), {})

    def test_cropped_mp_can_correct_only_exact_untouched_generic_fallback_without_agency_fields(self):
        entry = venue(id='fictional-mp', service_entity_type='ministerio_publico',
            service_entity='Ministério Público de Fictional City', service_place='Tribunal de Fictional City',
            required_source_phrases=['ministerio publico', 'local criminal', 'inqueritos de fictional city'])
        text = ('[…]radoria da República da Comarca de Fictional City\n'
                '[…]Local Criminal- 1ª Sec Inquéritos de Fictional City')
        fallback = {'service_entity': 'Tribunal genérico', 'service_entity_type': 'court'}
        candidate = intake(**fallback, source_text=text, auto_profile={'mode': 'auto_fallback'},
                           ai_recovery={'status': 'skipped', 'fields': {}})
        propose = lambda row, defaults=fallback: propose_verified_source_venue(
            row, metadata=metadata(), preferences={'verified_gps_venues': [entry]}, fallback_defaults=defaults)
        self.assertTrue(propose(candidate))
        self.assertEqual(propose(candidate, None), {})
        for changes in ({'service_entity': 'Tribunal de Manual City'},
                        {'service_entity_type': 'gnr'}, {'auto_profile': {'mode': 'explicit_profile'}},
                        {'ai_recovery': {'fields': {'service_entity_type': 'court'}}},
                        {'review_cleared_fields': ['service_entity_type']}):
            with self.subTest(changes=changes):
                self.assertEqual(propose({**candidate, **changes}), {})

    def test_corroborated_cropped_mp_heading_uses_verified_physical_court_without_rewriting_text(self):
        entry = venue(id='fictional-new-court', city='Fictional City',
            service_entity_type='ministerio_publico', service_entity='Ministério Público de Fictional City',
            service_place='Tribunal de Fictional City', radius_m=50,
            required_source_phrases=['ministerio publico', 'local criminal', 'sec inqueritos de fictional city'])
        for label in ('Procuradoria', '[…]radoria', '…curadoria'):
            text = (f'{label} da República da Comarca de Fictional City\n'
                    '[…]Local Criminal- 1ª Sec Inquéritos de Fictional City\n'
                    '[…]argo da Rua Antiga\nProcesso de exemplo')
            candidate = intake(service_entity='Ministério Público', service_entity_type='ministerio_publico',
                               source_text=text)
            before = deepcopy(candidate)
            result = self.propose(candidate, entries=[entry])
            self.assertEqual(result['service_place'], 'Tribunal de Fictional City')
            self.assertEqual(result['service_entity_type'], 'ministerio_publico')
            proof = result['source_location_evidence']
            self.assertNotIn('ministerio publico', proof['matched_source_phrases'])
            self.assertEqual(proof['source_text_sha256'], hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(proof['source_agency_corroboration']['derived_agency_type'], 'ministerio_publico')
            self.assertIn('República', proof['source_agency_corroboration']['raw_excerpts'][0])
            self.assertIn('not printed in full', proof['reason'])
            self.assertEqual(candidate, before)

    def test_cropped_mp_heading_requires_two_own_specific_same_city_lines_and_real_gps(self):
        entry = venue(id='fictional-new-court', service_entity_type='ministerio_publico',
            service_entity='Ministério Público de Fictional City', service_place='Tribunal de Fictional City',
            required_source_phrases=['ministerio publico', 'local criminal', 'sec inqueritos de fictional city'])
        first = '[…]radoria da República da Comarca de Fictional City'
        second = '[…]Local Criminal- 1ª Sec Inquéritos de Fictional City'
        good = first + '\n' + second
        variants = (first, second, 'radoria\n' + second, first + '\nLocal Criminal de Fictional City',
                    good.replace('de Fictional City', 'de Other City', 1),
                    'Processo de exemplo\n' + good, 'Notifique-se:\n' + good,
                    '> ' + first + '\n' + second, 'Mensagem original\n' + good,
                    'Tribunal de Fictional City\n' + good,
                    good + '\nGuarda Nacional Republicana')
        for text in variants:
            with self.subTest(text=text):
                self.assertEqual(self.propose(intake(service_entity='Ministério Público',
                    service_entity_type='ministerio_publico', source_text=text), entries=[entry]), {})
        candidate = intake(service_entity='Ministério Público', service_entity_type='ministerio_publico', source_text=good)
        self.assertEqual(self.propose(candidate, meta=metadata(gps_coordinates=None), entries=[entry]), {})
        self.assertEqual(self.propose(candidate, meta=metadata(gps_coordinates={
            'latitude': 1, 'longitude': 1, 'source': 'exif_gps'}), entries=[entry]), {})
        self.assertEqual(self.propose(candidate, entries=[entry, {**entry, 'id': 'second'}]), {})
        for field in ('service_place', 'service_entity'):
            self.assertEqual(self.propose({**candidate, 'review_cleared_fields': [field]}, entries=[entry]), {})
        self.assertEqual(self.propose({**candidate, 'service_place': 'Manual building'}, entries=[entry]), {})

    def test_user_confirmed_photo_venue_geometry_has_tight_bound_and_honest_provenance(self):
        entry = venue(id='fictional-confirmed', radius_m=50, geometry_basis='user_confirmed_photo_venue',
            confirmation_source_sha256='b' * 64, confirmation_date='2026-11-13')
        result = self.propose(entries=[entry])
        proof = result['source_location_evidence']
        self.assertEqual(proof['geometry_basis'], 'user_confirmed_photo_venue')
        self.assertEqual(proof['confirmation_source_sha256'], 'b' * 64)
        self.assertIn('user-confirmed photo location', proof['reason'])
        self.assertIn('not a surveyed building footprint', proof['reason'])
        for change in ({'radius_m': 50.01}, {'confirmation_source_sha256': ''},
                       {'confirmation_source_sha256': None}, {'confirmation_date': 'not-a-date'},
                       {'geometry_basis': 'guessed_from_city'}):
            self.assertEqual(self.propose(entries=[{**entry, **change}]), {})
    def propose(self, candidate=None, meta=None, entries=None):
        return propose_verified_source_venue(intake() if candidate is None else candidate,
            metadata=metadata() if meta is None else meta,
            preferences={'verified_gps_venues': [venue()] if entries is None else entries})

    def test_specific_source_and_original_gps_propose_editable_bound_venue_without_mutation(self):
        candidate, meta, preferences = intake(), metadata(), {'verified_gps_venues': [venue()]}
        before = deepcopy((candidate, meta, preferences))
        result = propose_verified_source_venue(candidate, metadata=meta, preferences=preferences)
        self.assertEqual(result['service_place'], venue()['service_place'])
        self.assertTrue(result['entities_differ'])
        proof = result['source_location_evidence']
        self.assertEqual(proof['source_sha256'], candidate['source_sha256'])
        self.assertEqual(proof['source_text_sha256'], hashlib.sha256(candidate['source_text'].encode('utf-8')).hexdigest())
        self.assertEqual(proof['source'], 'verified_gps_source_venue')
        self.assertEqual(proof['service_entity'], result['service_entity'])
        self.assertEqual(proof['service_entity_type'], result['service_entity_type'])
        self.assertEqual(proof['distance_m'], 0)
        self.assertEqual(proof['source_urls'], venue()['source_urls'])
        self.assertTrue(proof['editable'])
        self.assertIn('not a printed venue', proof['reason'])
        self.assertEqual((candidate, meta, preferences), before)
        self.assertNotIn('payment_entity', result)
        self.assertNotIn('recipient_email', result)
        self.assertNotIn('transport', result)
        proof['source_urls'].append('https://fictional.example.test/changed')
        self.assertEqual((candidate, meta, preferences), before)

    def test_missing_catalog_and_nonphoto_or_unbound_source_do_not_infer(self):
        self.assertEqual(propose_verified_source_venue(intake(), metadata=metadata(), preferences={}), {})
        for changed in ({'source_kind': 'pdf'}, {'source_kind': 'manual'}, {'source_sha256': ''}, {'source_sha256': 'not-a-hash'}):
            with self.subTest(changed=changed):
                self.assertEqual(self.propose(intake(**changed)), {})

    def test_existing_venue_phrase_explicit_profile_or_user_clear_are_authoritative(self):
        for changed in ({'service_place': 'Other building'}, {'service_place_phrase': 'nas instalações de Other building'},
                        {'auto_profile': {'mode': 'explicit_profile'}},
                        *({'review_cleared_fields': [field]} for field in ('service_place', 'service_entity', 'source_text'))):
            with self.subTest(changed=changed):
                self.assertEqual(self.propose(intake(**changed)), {})

    def test_printed_physical_venue_is_never_overwritten(self):
        for ending in ('\nLocal da diligência: Hospital de Other City', '\nLocal da diligência: GNR de Fictional City'):
            with self.subTest(ending=ending):
                self.assertEqual(self.propose(intake(source_text=intake()['source_text'] + ending)), {})

    def test_different_capture_city_in_each_supported_evidence_path_blocks(self):
        variants = [metadata(photo_metadata_city='Other City'), metadata(visible_metadata_city='Other City'),
                    metadata(photo_metadata_city_candidates=['Fictional City', 'Other City']),
                    metadata(gps_city_match={'status': 'matched', 'city': 'Other City'})]
        for meta in variants:
            with self.subTest(meta=meta):
                self.assertEqual(self.propose(meta=meta), {})
        self.assertEqual(self.propose(intake(photo_capture_city='Other City')), {})
        self.assertEqual(self.propose(intake(ai_recovery={'fields': {'photo_metadata_city': 'Other City'}})), {})

    def test_ambiguous_invalid_or_malformed_city_evidence_blocks(self):
        for status in ('ambiguous', 'invalid_gps', 'invalid_configuration', 'conflicting_city_evidence', 'unexpected'):
            with self.subTest(status=status):
                self.assertEqual(self.propose(meta=metadata(gps_city_match={'status': status})), {})
        for meta in (metadata(gps_city_match='city'), metadata(gps_city_match={'status': []}), metadata(gps_city_match={'status': 'matched'}),
                     metadata(photo_metadata_city_candidates='city'), metadata(photo_metadata_city=123)):
            self.assertEqual(self.propose(meta=meta), {})

    def test_missing_invalid_or_nonoriginal_gps_does_not_infer(self):
        for gps in (None, {}, {'latitude': 0, 'longitude': 0},
                    {'latitude': 0, 'longitude': 0, 'source': 'user_entered'},
                    *({'latitude': bad, 'longitude': 0, 'source': 'exif_gps'} for bad in (True, '0', 91, math.nan, math.inf, 10**1000))):
            with self.subTest(gps=str(gps)[:100]):
                self.assertEqual(self.propose(meta=metadata(gps_coordinates=gps)), {})

    def test_boundary_and_no_nearest_venue_fallback(self):
        for distance, expected in ((199.99, True), (200.01, False), (1000, False)):
            with self.subTest(distance=distance):
                gps = {'latitude': math.degrees(distance / EARTH_RADIUS_M), 'longitude': 0, 'source': 'exif_gps'}
                self.assertEqual(bool(self.propose(meta=metadata(gps_coordinates=gps))), expected)

    def test_two_matching_venues_are_ambiguous_even_in_same_city(self):
        for second in (venue(id='other-unit'), venue(id='other-unit', service_place='GNR de Fictional City — Unit B')):
            self.assertEqual(self.propose(entries=[venue(), second]), {})

    def test_source_specificity_requires_all_phrases_and_correct_agency(self):
        for phrase in venue()['required_source_phrases']:
            text = intake()['source_text']
            # Normalize both accents and source phrasing only to remove a clue.
            from scripts.entity_rules import normalize_text
            text = normalize_text(text).replace(phrase, '')
            with self.subTest(phrase=phrase):
                self.assertEqual(self.propose(intake(source_text=text)), {})
        for changed in ({'service_entity_type': 'psp'}, {'service_entity': 'Polícia de Segurança Pública'}, {'source_text': 'Fictional City'},
                        {'source_text': intake()['source_text'].replace('GUARDA NACIONAL REPUBLICANA', 'POLÍCIA DE SEGURANÇA PÚBLICA')},
                        {'source_text': intake()['source_text'].replace('Fictional City', 'Other City')},
                        {'source_text': 'GUARDA NACIONAL REPUBLICANA\nComando Territorial de Fictional City'}):
            with self.subTest(changed=changed):
                self.assertEqual(self.propose(intake(**changed)), {})

    def test_quoted_forwarded_body_or_conflicting_source_agencies_do_not_infer(self):
        header = intake()['source_text']
        for text in ('Tribunal de Fictional City\n' + header, 'From: example@example.test\n' + header,
                     'Mensagem original\n' + header, 'Auto de declarações\n' + header,
                     header.replace('Auto de compromisso', 'Polícia de Segurança Pública')):
            with self.subTest(text=text):
                self.assertEqual(self.propose(intake(source_text=text)), {})

    def test_normalized_whitespace_accents_and_raw_ocr_fallback_preserve_evidence(self):
        text = intake()['source_text'].replace('Núcleo de Investigação', 'NÚCLEO  DE\nINVESTIGAÇÃO')
        self.assertTrue(self.propose(intake(source_text=text)))
        fallback = self.propose(intake(source_text='', ai_recovery={'raw_visible_text': text}))
        self.assertEqual(fallback['source_location_evidence']['source_text_sha256'], hashlib.sha256(text.encode('utf-8')).hexdigest())

    def test_mp_specific_unit_supported_without_inventing_court_or_travel(self):
        entry = venue(id='fictional-mp', service_entity_type='ministerio_publico',
                      service_entity='Ministério Público — DIAP Regional de Fictional City',
                      service_place='DIAP Regional de Fictional City',
                      required_source_phrases=['ministerio publico', 'diap regional de fictional city'])
        candidate = intake(service_entity='Ministério Público', service_entity_type='ministerio_publico',
                           source_text='Ministério Público\nDIAP Regional de Fictional City\nProcesso de exemplo')
        result = self.propose(candidate, entries=[entry])
        self.assertEqual(result['service_place'], entry['service_place'])
        self.assertFalse(result['entities_differ'])
        self.assertNotIn('payment_entity', result)

    def test_generic_court_type_can_be_corrected_only_by_matching_agency_name_and_own_heading(self):
        entry = venue(id='fictional-mp', service_entity_type='ministerio_publico',
                      service_entity='DIAP Regional de Fictional City', service_place='DIAP Regional de Fictional City',
                      required_source_phrases=['ministerio publico', 'diap regional de fictional city'])
        candidate = intake(service_entity='DIAP Regional de Fictional City', service_entity_type='court',
                           auto_profile={'mode': 'auto_fallback'},
                           source_text='Ministério Público\nDIAP Regional de Fictional City')
        result = self.propose(candidate, entries=[entry])
        self.assertEqual(result['service_entity_type'], 'ministerio_publico')
        self.assertEqual(result['source_location_evidence']['source_agency_type'], 'ministerio_publico')
        self.assertEqual(candidate['service_entity_type'], 'court')
        for changes in ({'auto_profile': {'mode': 'explicit_profile'}}, {'auto_profile': {'mode': 'auto_match'}},
                        {'service_entity': 'Tribunal de Fictional City'}, {'service_entity_type': 'psp'},
                        {'service_entity': ''}, {'source_text': 'DIAP Regional de Fictional City'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.propose({**candidate, **changes}, entries=[entry]), {})

    def test_bad_catalog_fails_closed_as_a_whole(self):
        invalid = [None, {}, 'venues', [], [venue()] * 101, [venue(), venue()]]
        for field, values in {
            'id': ['', 'node\n', 123], 'city': ['', '123', 'City\n'],
            'service_entity_type': ['court', 'other', [], None],
            'service_entity': ['PSP de Fictional City'],
            'service_place': ['GNR de Other City'],
            'latitude': [True, '0', 91, math.nan, 10**1000], 'longitude': [-181, math.inf],
            'radius_m': [0, -1, True, '200', 200.01, math.nan, math.inf],
            'required_source_phrases': [[], ['beja'], ['guarda nacional republicana', 'fictional city'], ['guarda nacional republicana', 'nucleo de investigacao'], ['guarda nacional republicana']*2],
            'source_urls': [[], ['http://places.example.test/'], ['https://user:password@places.example.test/'], ['https://:@places.example.test/'], ['https:///invalid'], ['https://places.example.test/\x00']],
        }.items():
            invalid.extend([venue(), venue(**{field: value})] for value in values)
        for entries in invalid:
            with self.subTest(entries=str(entries)[:150]):
                result = propose_verified_source_venue(intake(), metadata=metadata(), preferences={'verified_gps_venues': entries})
                self.assertEqual(result, {})


class ReusableVerifiedGpsCityTests(unittest.TestCase):
    def entry(self, kind='ministerio_publico', **changes):
        return venue(id='fictional-reusable-' + kind, radius_m=50,
            geometry_basis='user_confirmed_photo_venue', confirmation_source_sha256='a' * 64,
            confirmation_date='2026-11-01', source_city_basis='verified_gps',
            service_entity_type=kind,
            service_entity='Ministério Público de Fictional City' if kind == 'ministerio_publico' else 'Polícia Judiciária',
            service_place='Tribunal de Fictional City' if kind == 'ministerio_publico' else 'Posto da GNR de Fictional City',
            required_source_phrases=['ministerio publico', 'local criminal'] if kind == 'ministerio_publico'
                else ['policia judiciaria', 'diretoria do sul'], **changes)

    def source(self, kind='ministerio_publico', **changes):
        if kind == 'ministerio_publico':
            label = 'MINISTÉRIO PÚBLICO - Procuradoria da'
            text = label + '\nProcuradoria do Juízo Local Criminal-\nProcesso: 981/26.0TSTXX'
        else:
            label = 'POLÍCIA JUDICIÁRIA'
            text = 'MINISTÉRIO DA JUSTIÇA\n' + label + '\nDIRETORIA DO SUL\nNUIPC: 981/26.0TSTXX'
        return intake(source_sha256='b' * 64, case_number='981/26.0TSTXX', service_date='2026-11-13',
                      service_entity=label, service_entity_type=kind, source_text=text, **changes)

    def propose(self, candidate=None, meta=None, entries=None):
        return propose_verified_source_venue(candidate if candidate is not None else self.source(),
            metadata=metadata() if meta is None else meta,
            preferences={'verified_gps_venues': entries if entries is not None else [self.entry()]})

    def test_new_photo_identity_and_day_use_original_gps_without_exact_source_memory(self):
        for kind in ('ministerio_publico', 'police'):
            with self.subTest(kind=kind):
                source, entry = self.source(kind), self.entry(kind)
                before = deepcopy(source)
                self.assertNotIn('fictional city', source['source_text'].lower())
                result = self.propose(source, entries=[entry])
                self.assertEqual(result['service_place'], entry['service_place'])
                self.assertEqual(result['service_entity_type'], kind)
                self.assertEqual(result['service_entity'], source['service_entity'])
                proof = result['source_location_evidence']
                self.assertEqual(proof['source_sha256'], 'b' * 64)
                self.assertEqual(proof['confirmation_source_sha256'], 'a' * 64)
                self.assertEqual(proof['source_city_basis'], 'verified_gps')
                self.assertEqual(source, before)
                for field in ('payment_entity', 'recipient_email', 'transport', 'service_date', 'claim_transport'):
                    self.assertNotIn(field, result)

    def test_reusable_mode_requires_complete_user_point_and_fifty_meter_cap(self):
        invalid = ({'source_city_basis': 'nearest_city'}, {'radius_m': 50.01},
                   {'geometry_basis': 'public_building'}, {'confirmation_source_sha256': 'a' * 63},
                   {'confirmation_date': '2026-02-30'})
        for changes in invalid:
            with self.subTest(changes=changes):
                row = {**self.entry(), **changes}
                self.assertEqual(self.propose(entries=[row]), {})
        row = self.entry()
        for field in ('geometry_basis', 'confirmation_source_sha256', 'confirmation_date'):
            missing = {key: value for key, value in row.items() if key != field}
            self.assertEqual(self.propose(entries=[missing]), {})
        legacy_without_city = {key: value for key, value in row.items() if key != 'source_city_basis'}
        self.assertEqual(self.propose(entries=[legacy_without_city]), {})

    def test_verified_city_agreement_original_coordinates_and_inside_radius_are_all_required(self):
        for status in ('disabled', 'missing_gps', 'outside_verified_areas', 'ambiguous', 'invalid_configuration'):
            self.assertEqual(self.propose(meta=metadata(gps_city_match={'status': status})), {})
        for meta in (metadata(gps_city_match={'status': 'matched', 'city': 'Other City'}), metadata(gps_coordinates=None),
                     metadata(gps_coordinates={'latitude': 0, 'longitude': 0, 'source': 'typed'})):
            self.assertEqual(self.propose(meta=meta), {})
        for distance, expected in ((49.99, True), (50.01, False)):
            gps = {'latitude': math.degrees(distance / EARTH_RADIUS_M), 'longitude': 0, 'source': 'exif_gps'}
            self.assertEqual(bool(self.propose(meta=metadata(gps_coordinates=gps))), expected)

    def test_own_agency_and_unit_required_not_quotes_recipients_or_narrative(self):
        for kind in ('ministerio_publico', 'police'):
            source = self.source(kind)
            text = source['source_text']
            variants = ('Tribunal de Fictional City\n' + text, 'From: example@example.test\n' + text,
                        'Mensagem original\n' + text, 'Auto de declarações\n' + text,
                        '\n'.join('"' + line + '"' for line in text.splitlines()),
                        'O tribunal menciona o seguinte:\n' + text,
                        text.replace('Local Criminal', 'Trabalho').replace('DIRETORIA DO SUL', 'Outra unidade'))
            for variant in variants:
                with self.subTest(kind=kind, text=variant):
                    self.assertEqual(self.propose({**source, 'source_text': variant}, entries=[self.entry(kind)]), {})
        recipient = 'Ao MINISTÉRIO PÚBLICO\nProcuradoria do Juízo Local Criminal-'
        self.assertEqual(self.propose({**self.source(), 'source_text': recipient}), {})

    def test_conflicting_issuer_city_or_own_agency_blocks_but_body_police_mention_is_context(self):
        source = self.source()
        for text in ('MINISTÉRIO PÚBLICO - Procuradoria da República da Comarca de Other City\nProcuradoria do Juízo Local Criminal-',
                     source['source_text'].replace('Procuradoria do Juízo Local Criminal-', 'Procuradoria do Juízo Local Criminal de Other City'),
                     source['source_text'].replace('Processo:', 'GUARDA NACIONAL REPUBLICANA\nProcesso:')):
            self.assertEqual(self.propose({**source, 'source_text': text}), {})
        body = source['source_text'] + '\nI. Vistos os autos.\nII. O militar da GNR apresentou requerimento.'
        self.assertTrue(self.propose({**source, 'source_text': body}))

    def test_cropped_two_line_mp_corroboration_retained_with_truthful_raw_excerpts(self):
        first = '[…]radoria da República da Comarca de Fictional City'
        unit = '[…]Local Criminal- 1ª Sec Inquéritos de Fictional City'
        source = {**self.source(), 'source_text': first + '\n' + unit, 'service_entity': 'Ministério Público'}
        result = self.propose(source)
        proof = result['source_location_evidence']
        self.assertNotIn('ministerio publico', proof['matched_source_phrases'])
        self.assertEqual(proof['source_agency_corroboration']['raw_excerpts'], [first, unit])
        self.assertNotIn('Ministério Público', '\n'.join(proof['source_agency_corroboration']['raw_excerpts']))

    def test_manual_clears_explicit_profiles_and_named_hosts_still_win(self):
        for changes in ({'auto_profile': {'mode': 'explicit_profile'}}, {'service_place': 'Manual host'},
                        {'service_place_phrase': 'Manual venue clause'}, {'review_cleared_fields': ['service_place']},
                        {'review_cleared_fields': ['service_entity']}, {'review_cleared_fields': ['source_text']}):
            self.assertEqual(self.propose({**self.source(), **changes}), {})
        text = self.source()['source_text'] + '\nLocal da diligência: Hospital de Other City'
        self.assertEqual(self.propose({**self.source(), 'source_text': text}), {})

    def test_multiple_matching_legacy_and_reusable_targets_remain_ambiguous(self):
        text = ('Ministério Público\nProcuradoria do Juízo Local Criminal de Fictional City\n'
                'Sec Inquéritos de Fictional City\nProcesso: 981/26.0TSTXX')
        legacy = venue(id='fictional-old-mp', service_entity_type='ministerio_publico',
            service_entity='Ministério Público de Fictional City', service_place='Ministério Público de Fictional City',
            required_source_phrases=['ministerio publico', 'local criminal de fictional city'])
        self.assertEqual(self.propose({**self.source(), 'source_text': text, 'service_entity': 'Ministério Público'},
                                     entries=[legacy, self.entry()]), {})

    def test_narrative_between_agency_and_unit_and_unbound_entity_are_not_reusable_headings(self):
        source = self.source()
        text = 'MINISTÉRIO PÚBLICO\nSegue apenas a transcrição da entidade referida:\nProcuradoria do Juízo Local Criminal-'
        self.assertEqual(self.propose({**source, 'source_text': text}), {})
        for entity in ('Manual agency', 'Ministério Público de Other City'):
            self.assertEqual(self.propose({**source, 'service_entity': entity}), {})
        current = {**source, 'service_entity': 'Procuradoria do Juízo Local Criminal-'}
        self.assertEqual(self.propose(current)['service_entity'], current['service_entity'])

    def test_clipped_section_and_bounded_one_line_signature_keep_own_header_evidence(self):
        for unit in ('Procuradoria do Juízo Local Criminal - Secção',
                     'Procuradoria do Juízo Local Criminal - Sec',
                     'Procuradoria do Juízo Local Criminal - Secção de Inquéritos de Fictional City'):
            for prefix in ('', 'Assinado em 19-11-2026, por Pessoa Exemplo, Procurador da República\n'):
                text = prefix + 'MINISTÉRIO PÚBLICO\n' + unit + '\nProcesso: 981/26.0TSTXX'
                self.assertTrue(self.propose({**self.source(), 'source_text': text, 'service_entity': 'Ministério Público'}))
        for prefix in ('Assinado em data desconhecida, por Pessoa Exemplo, Procurador da República',
                       'Assinado em 19-11-2026, por Pessoa Exemplo, informa o seguinte:',
                       '“Assinado em 19-11-2026, por Pessoa Exemplo, Procurador da República”'):
            self.assertEqual(self.propose({**self.source(), 'source_text': prefix+'\nMINISTÉRIO PÚBLICO\nProcuradoria do Juízo Local Criminal-',
                                          'service_entity': 'Ministério Público'}), {})


if __name__ == '__main__':
    unittest.main()
