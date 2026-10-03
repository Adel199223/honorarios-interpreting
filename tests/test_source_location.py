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


if __name__ == '__main__':
    unittest.main()
