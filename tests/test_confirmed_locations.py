"""Exact-source location memory, using fictional sources and contacts only."""
from copy import deepcopy
import hashlib
import unittest

from honorarios_app.confirmed_locations import PROOF_KEY, apply_confirmed_source_location

COURT_DOMAIN = 'tribunais' + '.org.pt'


def confirmation(**changes):
    return {'id': 'fictional-gnr-source', 'source_sha256': 'a' * 64, 'case_number': '810/26.0TSTXX',
            'allowed_service_dates': ['2026-10-03'], 'confirmation_date': '2026-11-01',
            'evidence_reference': 'reviewed-answer-3',
            'host': {'service_place': 'GNR de Fictional City', 'service_entity': 'Guarda Nacional Republicana',
                     'service_entity_type': 'gnr', 'entities_differ': True},
            'payment_route': {'payment_entity': 'Tribunal de Fictional Payer',
                              'addressee': 'Exmo. Senhor Juiz de Direito\nTribunal de Fictional Payer',
                              'recipient_email': 'fictional.judicial@' + COURT_DOMAIN},
            'travel': {'personal_profile_id': 'fictional-main', 'origin': 'Fictional Origin', 'destination': 'Fictional City', 'km_one_way': 105},
            **changes}


def intake(**changes):
    return {'source_kind': 'photo', 'source_sha256': 'a' * 64, 'case_number': '810/26.0TSTXX',
            'service_date': '2026-10-03', 'source_text': 'GUARDA NACIONAL REPUBLICANA\nProcesso 810/26.0TSTXX',
            'personal_profile_id': 'fictional-main', 'transport': {'origin': 'Fictional Origin'},
            'claim_interpreting': True, 'claim_transport': True, **changes}


class ConfirmedLocationTests(unittest.TestCase):
    def apply(self, source=None, records=None, **kwargs):
        preferences = {'confirmed_source_locations': [confirmation()] if records is None else records,
                       'photo_city_court': True, 'missing_venue_is_city_court': True,
                       'missing_gnr_venue_is_capture_city': True,
                       'city_courts': {'Fictional City': {'payment_entity': 'Tribunal de Fictional City',
                           'recipient_email': 'fictional.city@' + COURT_DOMAIN}}}
        preferences.update(kwargs.pop('preferences', {}))
        return apply_confirmed_source_location(source or intake(), preferences=preferences, directory=[], **kwargs)

    def test_exact_match_applies_only_confirmed_fact_groups_and_preserves_input(self):
        source, record = intake(), confirmation()
        before = deepcopy((source, record))
        result = self.apply(source, [record])
        self.assertEqual(result['status'], 'applied')
        candidate = result['intake']
        self.assertEqual(candidate['service_place'], 'GNR de Fictional City')
        self.assertEqual(candidate['service_entity_type'], 'gnr')
        self.assertTrue(candidate['entities_differ'])
        self.assertEqual(candidate['payment_entity'], 'Tribunal de Fictional Payer')
        self.assertEqual(candidate['transport'], {'origin': 'Fictional Origin', 'destination': 'Fictional City', 'km_one_way': 105})
        self.assertNotIn('photo_capture_city', candidate)
        self.assertNotIn('photo_metadata_city', candidate)
        for field in ('service_date', 'claim_interpreting', 'claim_transport'):
            self.assertEqual(candidate[field], source[field])
        self.assertNotIn('travel_group_id', candidate)
        proof = candidate[PROOF_KEY]
        self.assertEqual(proof['source_text_sha256'], hashlib.sha256(source['source_text'].encode()).hexdigest())
        self.assertIn('Previously confirmed for this source', proof['reason'])
        self.assertIn('not printed evidence', proof['reason'])
        self.assertEqual((source, record), before)

    def test_identity_matches_normalized_case_and_allowed_date_without_choosing_date(self):
        record = confirmation(allowed_service_dates=['2026-10-03', '2026-10-06'])
        for day in record['allowed_service_dates']:
            result = self.apply(intake(case_number='000810 / 26.0tstxx', service_date=day), [record])
            self.assertEqual(result['status'], 'applied')
            self.assertEqual(result['intake']['service_date'], day)
        for changes in ({'source_sha256': 'b' * 64}, {'case_number': '811/26.0TSTXX'},
                        {'service_date': '2026-10-04'}, {'service_date': ''}, {'source_kind': 'notification_pdf'}):
            with self.subTest(changes=changes):
                result = self.apply(intake(**changes), [record])
                self.assertEqual(result['status'], 'no_match')
                self.assertNotIn('service_place', result['intake'])

    def test_disabled_and_invalid_catalogs_never_partially_apply(self):
        self.assertEqual(self.apply(records=[])['status'], 'disabled')
        self.assertEqual(self.apply(preferences={'confirmed_source_locations': None})['status'], 'invalid_configuration')
        invalid = [{}, [confirmation()] * 129, [confirmation(), confirmation(id='duplicate-identity')],
                   [confirmation(), confirmation(source_sha256='b' * 64)]]
        for changes in ({'allowed_service_dates': []}, {'allowed_service_dates': ['2026-02-30']},
                        {'allowed_service_dates': ['2026-10-03', '2026-10-03']},
                        {'confirmation_date': '2026-2-01'}, {'evidence_reference': 'bad\nreference'},
                        {'source_sha256': 'a' * 63}, {'case_number': 'NPP 123'}, {'host': None},
                        {'service_date': '2026-10-03'}, {'claim_transport': True}, {'travel_group_id': 'group'},
                        {'payment_route': {'recipient_email': 'wrong@example.test'}},
                        {'travel': {'personal_profile_id': 'fictional-main', 'origin': 'Fictional Origin', 'destination': 'Fictional City', 'km_one_way': True}}):
            invalid.append([confirmation(**changes)])
        for catalog in invalid:
            with self.subTest(catalog=catalog):
                result = self.apply(records=catalog)
                self.assertEqual(result['status'], 'invalid_configuration')
                self.assertNotIn('service_place', result['intake'])

    def test_capture_city_reuses_saved_policy_without_fabricating_gps_or_source_text(self):
        record = {key: value for key, value in confirmation().items() if key not in {'host', 'payment_route', 'travel'}}
        record['capture_city'] = 'Fictional City'
        result = self.apply(records=[record])
        candidate = result['intake']
        self.assertEqual(candidate['photo_capture_city'], 'Fictional City')
        self.assertEqual(candidate['photo_capture_city_source_sha256'], 'a' * 64)
        self.assertEqual(candidate['payment_entity'], 'Tribunal de Fictional City')
        self.assertEqual(candidate['photo_defaults_applied']['photo_city_source'], 'user_confirmed_capture_city')
        self.assertNotIn('gps_coordinates', candidate)
        self.assertNotIn('photo_metadata_city', candidate)
        self.assertEqual(candidate['source_text'], intake()['source_text'])

    def test_existing_gps_or_explicit_capture_city_metadata_is_not_owned_or_revoked_by_memory(self):
        record = {key: value for key, value in confirmation().items() if key not in {'host', 'payment_route', 'travel'}}
        record['capture_city'] = 'Fictional City'
        for city_source in ('verified_gps_area', 'user_confirmed_capture_city'):
            source = intake(photo_defaults_applied={'photo_city': 'Fictional City', 'photo_city_source': city_source},
                            photo_capture_city_applied_fields={'independent': 'existing metadata'})
            if city_source == 'user_confirmed_capture_city':
                source.update(photo_capture_city='Fictional City', photo_capture_city_source_sha256='a' * 64)
            original = deepcopy(source)
            current = self.apply(source, [record])['intake']
            self.assertEqual(current['photo_defaults_applied'], original['photo_defaults_applied'])
            self.assertEqual(current['photo_capture_city_applied_fields'], original['photo_capture_city_applied_fields'])
            current['case_number'] = '811/26.0TSTXX'
            revoked = self.apply(current, [record])['intake']
            self.assertEqual(revoked['photo_defaults_applied'], original['photo_defaults_applied'])
            self.assertEqual(revoked['photo_capture_city_applied_fields'], original['photo_capture_city_applied_fields'])
        source = intake(photo_defaults_applied={'routing_status': 'missing_city', 'service_date': '2026-10-03'})
        owned = self.apply(source, [record])['intake']
        owned['case_number'] = '811/26.0TSTXX'
        revoked = self.apply(owned, [record])['intake']
        self.assertEqual(revoked['photo_defaults_applied'], source['photo_defaults_applied'])
        self.assertNotIn('photo_capture_city_applied_fields', revoked)
        self.assertNotIn('photo_capture_city', revoked)
        for mutation in ({'case_number': '811/26.0TSTXX'}, {'source_sha256': 'b' * 64}):
            owned = self.apply(source, [record])['intake']
            owned['photo_defaults_applied']['unrelated_later_review'] = 'preserve this'
            owned['photo_capture_city_applied_fields']['unrelated_later_distance'] = 9
            owned.update(mutation)
            revoked = self.apply(owned, [record])['intake']
            self.assertNotIn('photo_city', revoked['photo_defaults_applied'])
            self.assertEqual(revoked['photo_defaults_applied']['unrelated_later_review'], 'preserve this')
            self.assertEqual(revoked['photo_capture_city_applied_fields'], {'unrelated_later_distance': 9})

    def test_pj_source_agency_remains_distinct_from_gnr_host(self):
        record = confirmation(host={'service_place': 'Posto da GNR de Fictional City',
                                   'service_entity': 'Polícia Judiciária', 'service_entity_type': 'police',
                                   'entities_differ': True})
        result = self.apply(intake(source_text='Polícia Judiciária\nProcesso 810/26.0TSTXX'), [record])
        candidate = result['intake']
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(candidate['service_entity'], 'Polícia Judiciária')
        self.assertEqual(candidate['service_entity_type'], 'police')
        self.assertEqual(candidate['service_place'], 'Posto da GNR de Fictional City')
        self.assertIn('Polícia Judiciária', candidate['service_place_phrase'])
        self.assertIn('Posto da GNR', candidate['service_place_phrase'])

    def test_mp_source_agency_remains_distinct_from_confirmed_court_host(self):
        host = {'service_place': 'Tribunal de Fictional City', 'service_entity': 'Ministério Público',
                'service_entity_type': 'ministerio_publico', 'entities_differ': True}
        source = intake(source_text='MINISTÉRIO PÚBLICO\nProcuradoria do Juízo Local de Fictional City',
                        service_entity='Ministério Público — Procuradoria do Juízo Local de Fictional City',
                        service_entity_type='ministerio_publico')
        result = self.apply(source, [confirmation(host=host)])
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(result['intake']['service_place'], host['service_place'])
        self.assertEqual(result['intake']['service_entity'], source['service_entity'])
        self.assertEqual(result['intake']['service_entity_type'], 'ministerio_publico')
        self.assertTrue(result['intake']['entities_differ'])

    def test_named_host_or_agency_and_original_gps_city_conflicts_are_blocking_results(self):
        for source in (intake(source_text='GUARDA NACIONAL REPUBLICANA\nLocal da diligência: Hospital de Other City'),
                       intake(source_text='Polícia Judiciária\nProcesso 810/26.0TSTXX'),
                       intake(source_text='MINISTÉRIO PÚBLICO\nProcesso 810/26.0TSTXX')):
            result = self.apply(source)
            self.assertEqual(result['status'], 'source_conflict')
            self.assertTrue(result['conflicts'])
            self.assertNotIn('service_place', result['intake'])
        result = self.apply(intake(photo_defaults_applied={'photo_city_source': 'verified_gps_area', 'photo_city': 'Other City'}),
                            [confirmation(capture_city='Fictional City')])
        self.assertEqual(result['status'], 'source_conflict')

    def test_populated_source_host_conflict_is_not_mistaken_for_a_manual_override(self):
        source = intake(source_text='GUARDA NACIONAL REPUBLICANA\nLocal da diligência: Hospital de Other City',
                        service_place='Hospital de Other City')
        self.assertEqual(self.apply(source)['status'], 'source_conflict')
        source['review_cleared_fields'] = ['service_place']
        manual = self.apply(source)
        self.assertNotEqual(manual['status'], 'source_conflict')
        self.assertEqual(manual['intake']['service_place'], 'Hospital de Other City')

    def test_unresolved_structured_agency_or_host_phrase_cannot_form_a_partial_host_tuple(self):
        record = confirmation(host={'service_place': 'Tribunal de Fictional City', 'service_entity': 'Ministério Público',
                                    'service_entity_type': 'ministerio_publico', 'entities_differ': True})
        for changes in ({'service_entity': 'GNR', 'service_entity_type': 'gnr'},
                        {'service_place_phrase': 'em diligência realizada no Hospital de Other City'}):
            source = intake(source_text='MINISTÉRIO PÚBLICO\nProcesso 810/26.0TSTXX', **changes)
            self.assertEqual(self.apply(source, [record])['status'], 'source_conflict')
            source['review_cleared_fields'] = list(changes)
            manual = self.apply(source, [record])
            self.assertNotEqual(manual['status'], 'source_conflict')
            self.assertNotIn('service_place', manual['intake'])

    def test_explicit_profile_manual_host_and_clears_remain_authoritative(self):
        result = self.apply(intake(auto_profile={'mode': 'explicit_profile'}))
        self.assertEqual(result['status'], 'explicit_override')
        self.assertNotIn('service_place', result['intake'])
        for changes in ({'service_place': 'Manual host'}, {'service_place': '', 'review_cleared_fields': ['service_place']},
                        {'service_place': '', 'review_cleared_fields': ['service_entity']},
                        {'source_text': '', 'review_cleared_fields': ['source_text']}):
            with self.subTest(changes=changes):
                result = self.apply(intake(**changes))
                self.assertEqual(result['intake'].get('service_place'), changes['service_place'] if 'service_place' in changes else None)
                self.assertNotEqual(result['status'], 'source_conflict')

    def test_activating_explicit_profile_revokes_old_memory_but_preserves_new_manual_values(self):
        source = self.apply()['intake']
        source['auto_profile'] = {'mode': 'explicit_profile', 'profile_key': 'fictional-explicit'}
        result = self.apply(source)
        self.assertEqual(result['status'], 'explicit_override')
        self.assertNotIn('service_place', result['intake'])
        self.assertNotIn('payment_entity', result['intake'])
        self.assertNotIn('km_one_way', result['intake'].get('transport', {}))
        source.update(service_place='Manual selected-profile host', payment_entity='Tribunal de Manual Payer')
        manual = self.apply(source)['intake']
        self.assertEqual(manual['service_place'], source['service_place'])
        self.assertEqual(manual['payment_entity'], source['payment_entity'])
        self.assertNotIn(PROOF_KEY, manual)

    def test_only_positively_tracked_automatic_defaults_can_be_replaced(self):
        source = intake(service_place='Tribunal de Old City', service_entity='Tribunal de Old City',
                        service_entity_type='court', payment_entity='Tribunal de Old City', recipient_email='old@' + COURT_DOMAIN)
        automatic = {field: source[field] for field in ('service_place', 'service_entity', 'service_entity_type', 'payment_entity', 'recipient_email')}
        result = self.apply(source, automatic_fields=automatic)
        self.assertEqual(result['intake']['service_place'], 'GNR de Fictional City')
        self.assertEqual(result['intake']['payment_entity'], 'Tribunal de Fictional Payer')
        untouched = self.apply(source)['intake']
        self.assertEqual(untouched['service_place'], source['service_place'])
        self.assertEqual(untouched['payment_entity'], source['payment_entity'])

    def test_manual_override_equal_to_old_automatic_default_survives_repeated_reviews(self):
        automatic = {'service_place': 'Tribunal de Old City', 'payment_entity': 'Tribunal de Old City'}
        source = self.apply(intake(**automatic), automatic_fields=automatic)['intake']
        source.update(service_place=automatic['service_place'], payment_entity=automatic['payment_entity'])
        for _ in range(3):
            source = self.apply(source, automatic_fields=automatic)['intake']
            self.assertEqual(source['service_place'], automatic['service_place'])
            self.assertEqual(source['payment_entity'], automatic['payment_entity'])
            self.assertNotIn('km_one_way', source.get('transport', {}))
            self.assertNotIn('destination', source.get('transport', {}))
            self.assertIn('Tribunal de Old City', source['service_place_phrase'])

    def test_explicit_zero_and_personal_profile_switch_do_not_get_remembered_distance(self):
        zero = self.apply(intake(transport={'origin': 'Fictional Origin', 'destination': 'Fictional City', 'km_one_way': 0}),
                          automatic_fields={'transport.km_one_way': 0})['intake']
        self.assertEqual(zero['transport']['km_one_way'], 0)
        source = self.apply()['intake']
        source['personal_profile_id'] = 'different-origin-profile'
        switched = self.apply(source)['intake']
        self.assertNotIn('km_one_way', switched.get('transport', {}))
        self.assertEqual(switched['transport']['destination'], 'Fictional City')
        self.assertEqual(switched['service_place'], source['service_place'])

    def test_changed_origin_or_destination_revokes_only_unchanged_learned_distance(self):
        for field, value in (('origin', 'Different Origin'), ('destination', 'Different Destination')):
            with self.subTest(field=field):
                for km in (105, 0, 77):
                    source = self.apply()['intake']
                    source['transport'].update({field: value, 'km_one_way': km})
                    for _ in range(2):
                        source = self.apply(source)['intake']
                        self.assertEqual(source['transport'][field], value)
                        if km == 105:
                            self.assertNotIn('km_one_way', source['transport'])
                            self.assertTrue(source['source_transport_distance_pending'])
                        else:
                            self.assertEqual(source['transport']['km_one_way'], km)
        source = intake(transport={})
        self.assertNotIn('km_one_way', self.apply(source)['intake'].get('transport', {}))
        supplied = self.apply(source, personal_profile_origin='Fictional Origin')['intake']
        self.assertEqual(supplied['transport']['km_one_way'], 105)
        self.assertNotIn('origin', supplied['transport'])
        cleared = self.apply(intake(transport={}, review_cleared_fields=['transport.origin']),
                             personal_profile_origin='Fictional Origin')['intake']
        self.assertNotIn('km_one_way', cleared.get('transport', {}))
        source = self.apply(intake(transport={'origin': 'Fictional Origin', 'destination': 'Fictional City'}))['intake']
        self.assertNotIn('transport.destination', source[PROOF_KEY]['applied_fields'])
        source['transport']['destination'] = 'Old Generic Destination'
        for _ in range(2):
            source = self.apply(source, automatic_fields={'transport.destination': 'Old Generic Destination'})['intake']
            self.assertEqual(source['transport']['destination'], 'Old Generic Destination')
            self.assertNotIn('km_one_way', source['transport'])

    def test_catalog_revision_or_removal_revokes_old_unchanged_facts(self):
        source = self.apply()['intake']
        for records in ([], [confirmation(id='different', source_sha256='b' * 64)]):
            result = self.apply(source, records)
            self.assertIn(result['status'], {'disabled', 'no_match'})
            self.assertNotIn('service_place', result['intake'])
            self.assertNotIn('km_one_way', result['intake'].get('transport', {}))
            self.assertNotIn(PROOF_KEY, result['intake'])
            self.assertNotIn('service_place', self.apply(result['intake'], records)['intake'])
        changed = confirmation(host={**confirmation()['host'], 'service_place': 'GNR de Changed City'})
        updated = self.apply(source, [changed])['intake']
        self.assertEqual(updated['service_place'], 'GNR de Changed City')
        self.assertNotEqual(updated[PROOF_KEY]['confirmation_fingerprint'], source[PROOF_KEY]['confirmation_fingerprint'])
        manual = {**source, 'service_place': 'Manual replacement'}
        self.assertEqual(self.apply(manual, [])['intake']['service_place'], 'Manual replacement')
        self.assertEqual(self.apply(source, preferences={'confirmed_source_locations': None})['status'], 'invalid_configuration')

    def test_changed_identity_or_text_revokes_only_unchanged_memory_fields(self):
        source = self.apply()['intake']
        for changes in ({'source_sha256': 'b' * 64}, {'case_number': '811/26.0TSTXX'},
                        {'service_date': '2026-10-07'}, {'source_kind': 'notification_pdf'}):
            with self.subTest(changes=changes):
                result = self.apply({**source, **changes})
                self.assertEqual(result['status'], 'no_match')
                self.assertNotIn('service_place', result['intake'])
                self.assertNotIn('payment_entity', result['intake'])
                self.assertNotIn('km_one_way', result['intake'].get('transport', {}))
        edited = {**source, 'source_sha256': 'b' * 64, 'service_place': 'Manual replacement'}
        self.assertEqual(self.apply(edited)['intake']['service_place'], 'Manual replacement')
        text = 'GUARDA NACIONAL REPUBLICANA\nUpdated heading'
        reviewed = self.apply({**source, 'source_text': text})['intake']
        self.assertEqual(reviewed[PROOF_KEY]['source_text_sha256'], hashlib.sha256(text.encode()).hexdigest())

    def test_uncovered_sibling_never_inherits_first_child_confirmation(self):
        first = self.apply()['intake']
        sibling = {**first, 'case_number': '811/26.0TSTXX'}
        result = self.apply(sibling)
        self.assertEqual(result['status'], 'no_match')
        self.assertNotIn('service_place', result['intake'])
        self.assertNotIn('service_entity', result['intake'])
        self.assertNotIn('recipient_email', result['intake'])
        self.assertNotIn('km_one_way', result['intake'].get('transport', {}))

    def test_host_only_downstream_profile_travel_context_survives_repeated_review_and_revokes(self):
        record = confirmation()
        del record['travel']
        source = self.apply(records=[record])['intake']
        source['transport'].update(destination='Fictional City', km_one_way=39)
        proof = source[PROOF_KEY]
        proof['applied_fields'].update({'transport.destination': 'Fictional City', 'transport.km_one_way': 39})
        proof.update(travel_personal_profile_id='fictional-main', travel_origin='Fictional Origin',
                     travel_destination='Fictional City', travel_context_source='personal_profile')
        for _ in range(3):
            source = self.apply(source, [record])['intake']
            self.assertEqual(source[PROOF_KEY]['travel_context_source'], 'personal_profile')
            self.assertNotIn('travel', source[PROOF_KEY]['fact_groups'])
            self.assertEqual(source['transport']['km_one_way'], 39)
        for field in ('profile', 'origin', 'destination'):
            changed = deepcopy(source)
            if field == 'profile':
                changed['personal_profile_id'] = 'different-origin-profile'
            else:
                changed['transport'][field] = 'Different ' + field
            switched = self.apply(changed, [record])['intake']
            self.assertNotIn('km_one_way', switched['transport'])
            self.assertTrue(switched['source_transport_distance_pending'])
        sibling = self.apply({**source, 'case_number': '811/26.0TSTXX'}, [record])['intake']
        self.assertNotIn('km_one_way', sibling['transport'])
        self.assertNotIn('destination', sibling['transport'])

    def test_caller_supplied_proof_is_not_a_catalog_match_or_permission(self):
        source = intake(**{PROOF_KEY: {'source_sha256': 'a' * 64, 'applied_fields': []}})
        result = self.apply(source, records=[])
        self.assertEqual(result['status'], 'disabled')
        self.assertNotIn('service_place', result['intake'])
        self.assertNotIn(PROOF_KEY, result['intake'])

    def test_capture_city_on_confirmed_location_skips_court_defaults_when_photo_city_court_disabled(self):
        record = confirmation(capture_city='Fictional City')
        del record['payment_route']
        result = self.apply(intake(), records=[record], preferences={'photo_city_court': False})
        self.assertEqual(result['status'], 'applied')
        self.assertNotIn('payment_entity', result['intake'])
        self.assertNotIn('recipient_email', result['intake'])


if __name__ == '__main__':
    unittest.main()
