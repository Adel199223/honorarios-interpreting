from __future__ import annotations

import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (AppPaths, choose_service_profile, effective_intake_for_profile,
                                    prepare_intakes, recover_source_upload, review_intake_with_profile_evidence)
from pypdf import PdfReader
from scripts.generate_pdf import IntakeError
from scripts.intake_questions import missing_questions
from scripts.local_app_smoke import _synthetic_notification_pdf


class ServiceProfileSelectionTests(unittest.TestCase):
    def choose(self, profiles, *, requested="auto", text="Synthetic interpreting source"):
        return choose_service_profile(requested_profile=requested, extracted_text=text, ai_recovery={}, profiles=profiles)

    def test_generic_fallback_is_used_only_when_available(self):
        decision = self.choose({"court_mp_generic": {"defaults": {}}, "example": {"defaults": {}}})
        self.assertEqual(decision["profile_key"], "court_mp_generic")
        self.assertEqual(decision["mode"], "auto_fallback")
        self.assertFalse(decision["auto_applied"])

    def test_only_available_profile_is_a_visible_low_confidence_fallback(self):
        decision = self.choose({"example_interpreting": {"defaults": {}}}, text="Synthetic interpreting source")
        self.assertEqual(decision["profile_key"], "example_interpreting")
        self.assertEqual(decision["mode"], "auto_fallback")
        self.assertEqual(decision["confidence"], "low")
        self.assertIn("payment entity and recipient", decision["reason"])
        self.assertFalse(decision["auto_applied"])

    def test_multiple_profiles_without_a_match_do_not_choose_payment_defaults(self):
        decision = self.choose({"first": {"defaults": {}}, "second": {"defaults": {}}})
        self.assertEqual(decision["profile_key"], "")
        self.assertEqual(decision["confidence"], "low")
        self.assertIn("No profile defaults were applied", decision["reason"])

    def test_confident_available_match_remains_automatic(self):
        decision = self.choose({"beja_trabalho": {"defaults": {}}, "example": {"defaults": {}}}, text="Tribunal do Trabalho de Beja")
        self.assertEqual(decision["profile_key"], "beja_trabalho")
        self.assertEqual(decision["mode"], "auto_applied")
        self.assertTrue(decision["auto_applied"])

    def test_visible_named_station_overrides_its_parent_district_for_profile_choice(self):
        profiles = {'gnr_ferreira_falentejo': {'defaults': {}}, 'gnr_cuba': {'defaults': {}}}
        source = ('Guarda Nacional Republicana\nCOMANDO TERRITORIAL DE BEJA\n'
                  'DESTACAMENTO TERRITORIAL DE ALJUSTREL\nPOSTO TERRITORIAL DE FERREIRA DO ALENTEJO\n'
                  'AUTO DE COMPROMISSO\nProcesso 999/26.0EXAMPLE')
        for extracted, recovery in ((source, {}), ('', {'status': 'ok', 'raw_visible_text': source, 'fields': {}})):
            with self.subTest(extracted=bool(extracted)):
                decision = choose_service_profile(requested_profile='auto', extracted_text=extracted,
                                                  ai_recovery=recovery, profiles=profiles)
                self.assertEqual(decision['profile_key'], 'gnr_ferreira_falentejo')
                self.assertTrue(decision['auto_applied'])
        explicit = self.choose(profiles, requested='gnr_cuba', text=source)
        self.assertEqual(explicit['profile_key'], 'gnr_cuba')
        self.assertEqual(explicit['suggested_profile_key'], 'gnr_ferreira_falentejo')

    def test_station_suggestion_alone_multiple_stations_and_explicit_other_host_do_not_promote_it(self):
        profiles = {'gnr_ferreira_falentejo': {'defaults': {}}, 'gnr_cuba': {'defaults': {}}}
        source = 'GNR\nCOMANDO TERRITORIAL DE BEJA\nPOSTO TERRITORIAL DE FERREIRA DO ALENTEJO'
        two = self.choose(profiles, text=source + '\nPosto Territorial de Cuba')
        self.assertEqual(two['profile_key'], '')
        alternate = self.choose(profiles, text=source + '\nDiligência de interpretação realizada no Posto da GNR de Cuba.')
        self.assertEqual(alternate['profile_key'], 'gnr_cuba')
        ungrounded = choose_service_profile(requested_profile='auto', extracted_text='GNR Comando Territorial de Beja',
            ai_recovery={'status': 'ok', 'fields': {'service_place': 'Posto Territorial de Ferreira do Alentejo'}}, profiles=profiles)
        self.assertEqual(ungrounded['profile_key'], '')

    def test_ai_diagnostics_cannot_supply_physical_places_or_profile_agencies(self):
        profiles = {'gnr_ferreira_falentejo': {'defaults': {}}, 'court_mp_generic': {'defaults': {}},
                    'pj_medico_legal_beja': {'defaults': {}}}
        recovery = {'status': 'ok', 'raw_visible_text': (
            'NUIPC 999/26.0EXAMPLE\nGuarda Nacional Republicana\nCOMANDO TERRITORIAL DE BEJA\n'
            'DESTACAMENTO TERRITORIAL DE ALJUSTREL\nPOSTO TERRITORIAL DE FERREIRA DO ALENTEJO'),
            'fields': {'service_entity': 'Guarda Nacional Republicana - Posto Territorial de Ferreira do Alentejo',
                       'service_entity_type': 'gnr'},
            'warnings': ['A data é da fotografia, não de uma data de serviço no documento.',
                         'Não foi identificada Polícia Judiciária nem serviço no Hospital de Beja.'],
            'translation_indicators': ['Não há tradução efetuada no Hospital de Beja.']}
        original = copy.deepcopy(recovery)
        decision = choose_service_profile(requested_profile='auto', extracted_text='',
                                          ai_recovery=recovery, profiles=profiles)
        self.assertEqual(decision['profile_key'], 'gnr_ferreira_falentejo')
        self.assertTrue(decision['auto_applied'])
        self.assertEqual(recovery, original)
        recovery.update(raw_visible_text='Processo 999/26.0EXAMPLE', fields={})
        decision = choose_service_profile(requested_profile='auto', extracted_text='',
                                          ai_recovery=recovery, profiles=profiles)
        self.assertEqual(decision['profile_key'], 'court_mp_generic')
        self.assertFalse(decision['auto_applied'])

    def test_explicit_choice_is_kept_even_with_conflicting_evidence(self):
        decision = self.choose({"beja_trabalho": {"defaults": {}}, "example": {"defaults": {}}}, requested="example", text="Tribunal do Trabalho de Beja")
        self.assertEqual(decision["profile_key"], "example")
        self.assertEqual(decision["suggested_profile_key"], "beja_trabalho")
        self.assertEqual(decision["mode"], "explicit_profile")
        self.assertFalse(decision["auto_applied"])

    def test_empty_profiles_have_an_actionable_blocker(self):
        with self.assertRaisesRegex(IntakeError, "Add a service profile in References"):
            self.choose({})


class SyntheticUploadProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="honorarios-profile-selection-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = AppPaths(**runtime_path_overrides(self.root))
        photo = BytesIO()
        Image.new("RGB", (24, 24), "white").save(photo, format="PNG")
        self.photo = photo.getvalue()

    def notification_upload(self, *, profile='auto'):
        with patch('honorarios_app.services.recover_source_with_openai',
                   return_value={'status': 'disabled', 'attempted': False, 'fields': {}}), \
             patch('socket.socket.connect', side_effect=AssertionError('This regression must stay offline.')):
            return recover_source_upload(filename='synthetic-notice.pdf', content_type='application/pdf',
                content=_synthetic_notification_pdf('999/26.0SMOKE', '2026-05-04',
                                                   recipient_email='court@' + 'tribunais.org.pt'),
                source_kind='notification_pdf', profile_name=profile, ai_recovery_mode='off', paths=self.paths)

    def test_pdf_printed_venue_replaces_fallback_phrase_and_unknown_old_route(self):
        result = self.notification_upload()
        candidate = result['candidate_intake']
        self.assertEqual(candidate['service_place'], 'Posto Territorial de Serpa')
        self.assertEqual(candidate['service_entity'], candidate['service_place'])
        self.assertEqual(candidate['service_place_phrase'], 'no Posto Territorial de Serpa')
        self.assertEqual(candidate['transport']['destination'], candidate['service_place'])
        self.assertEqual(candidate['transport']['km_one_way'], '')
        self.assertEqual(result['review']['status'], 'needs_info')
        self.assertIn('transport.km_one_way', {row['field'] for row in result['review']['questions']})
        repeated = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(repeated['intake']['service_place_phrase'], candidate['service_place_phrase'])
        self.assertEqual(repeated['intake']['transport']['km_one_way'], '')
        with self.assertRaises(IntakeError):
            prepare_intakes([candidate], self.paths)
        self.assertFalse(list(self.paths.output_dir.glob('*.pdf')))

    def test_pdf_known_source_city_distance_and_rendered_wording_remain_coherent(self):
        profiles = json.loads(self.paths.personal_profiles.read_text(encoding='utf-8'))
        profiles['profiles'][0]['travel_distances_by_city']['Serpa'] = 37
        self.paths.personal_profiles.write_text(json.dumps(profiles), encoding='utf-8')
        saved = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))['example_interpreting']
        for profile_key in ('example_interpreting', 'court_mp_generic'):
            with self.subTest(profile_key=profile_key):
                self.paths.service_profiles.write_text(json.dumps({profile_key: saved}), encoding='utf-8')
                result = self.notification_upload()
                self.assertEqual(result['review']['status'], 'ready', result['review'])
                candidate = result['candidate_intake']
                repeated = review_intake_with_profile_evidence(candidate, self.paths)
                self.assertEqual(repeated['intake']['transport']['km_one_way'], 37)
                self.assertIn('no Posto Territorial de Serpa', repeated['draft_text'])
                self.assertNotIn('Example Police Station', repeated['draft_text'])
                prepared = prepare_intakes([repeated['intake']], self.paths)
                text = ' '.join(' '.join(page.extract_text() or '' for page in PdfReader(prepared['items'][0]['pdf']).pages).split())
                self.assertIn('Posto Territorial de Serpa', text)
                self.assertIn('37 km', text)
                self.assertNotIn('Example Police Station', text)
                self.assertNotIn('12 km', text)

    def test_pdf_keeps_selected_profile_routing_but_uses_its_printed_physical_host(self):
        defaults = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))['example_interpreting']['defaults']
        result = self.notification_upload(profile='example_interpreting')
        candidate = result['candidate_intake']
        self.assertEqual(candidate['auto_profile']['mode'], 'explicit_profile')
        self.assertIn('Posto Territorial de Serpa', candidate['source_text'])
        for field in ('payment_entity', 'addressee', 'recipient_email'):
            self.assertEqual(candidate[field], defaults[field], field)
        self.assertEqual(candidate['service_place'], 'Posto Territorial de Serpa')
        self.assertEqual(candidate['service_place_phrase'], 'no Posto Territorial de Serpa')
        self.assertEqual(candidate['transport']['destination'], 'Posto Territorial de Serpa')
        self.assertEqual(candidate['transport']['km_one_way'], '')
        self.assertEqual(result['review']['status'], 'needs_info')
        repeated = review_intake_with_profile_evidence(candidate, self.paths)
        self.assertEqual(repeated['intake']['service_place_phrase'], candidate['service_place_phrase'])

    def test_pdf_unknown_routing_and_later_manual_overrides_stay_authoritative(self):
        saved = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))['example_interpreting']
        self.paths.service_profiles.write_text(json.dumps({'first': saved, 'second': saved}), encoding='utf-8')
        result = self.notification_upload()
        candidate = result['candidate_intake']
        self.assertNotIn('payment_entity', candidate)
        self.assertEqual(result['review']['status'], 'needs_info')
        candidate.update(service_place='Hospital de Manual City', service_entity='Hospital de Manual City',
                         service_entity_type='other', service_place_phrase='no Hospital de Manual City')
        candidate['transport'].update(destination='Manual City', km_one_way=0)
        repeated = review_intake_with_profile_evidence(candidate, self.paths)['intake']
        self.assertEqual(repeated['service_place_phrase'], 'no Hospital de Manual City')
        self.assertEqual(repeated['transport']['destination'], 'Manual City')
        self.assertEqual(repeated['transport']['km_one_way'], 0)

    def test_saved_closing_city_applies_without_service_profile_or_photo_policy(self):
        profile = json.loads(self.paths.profile.read_text(encoding='utf-8'))
        profile['default_closing_city'] = 'Fictional Closing City'
        self.paths.profile.write_text(json.dumps(profile), encoding='utf-8')
        for kind in ('notification_pdf', 'photo', ''):
            with self.subTest(kind=kind):
                effective, _, provenance = effective_intake_for_profile({'source_kind': kind}, self.paths)
                self.assertEqual(effective['closing_city'], 'Fictional Closing City')
                self.assertIn('closing_city', provenance['applied'])
                self.assertNotIn('closing_city', {q['field'] for q in missing_questions(effective)})

    def test_station_profile_keeps_specific_travel_instead_of_general_city_distance(self):
        source = ('Guarda Nacional Republicana\nCOMANDO TERRITORIAL DE BEJA\n'
                  'DESTACAMENTO TERRITORIAL DE ALJUSTREL\nPOSTO TERRITORIAL DE FERREIRA DO ALENTEJO\n'
                  'AUTO DE COMPROMISSO\nIntérprete. Processo 999/26.0EXAMPLE')
        saved = json.loads(self.paths.service_profiles.read_text(encoding='utf-8'))['example_interpreting']
        saved['defaults'].update(service_place='Posto da GNR de Ferreira do Alentejo',
            service_entity='Guarda Nacional Republicana / Posto da GNR de Ferreira do Alentejo',
            service_entity_type='gnr', service_place_phrase='no Posto da GNR de Ferreira do Alentejo',
            transport={'destination':'Posto da GNR de Ferreira do Alentejo', 'km_one_way':50})
        self.paths.service_profiles.write_text(json.dumps({'gnr_ferreira_falentejo':saved,
            'court_mp_generic':{'defaults':{'service_entity_type':'court','entities_differ':False}}}), encoding='utf-8')
        profiles = json.loads(self.paths.personal_profiles.read_text(encoding='utf-8'))
        profiles['profiles'][0]['travel_distances_by_city']['Ferreira do Alentejo'] = 42
        self.paths.personal_profiles.write_text(json.dumps(profiles), encoding='utf-8')
        self.paths.ai_config.with_name('photo-defaults.local.json').write_text(json.dumps({
            'capture_date_is_service_date':True, 'photo_city_court':True, 'missing_venue_is_city_court':True,
            'city_courts':{'Ferreira do Alentejo':{'payment_entity':'Tribunal de Ferreira do Alentejo',
                'recipient_email':'fictional-ferreira@' + 'tribunais.org.pt'}},
        }), encoding='utf-8')
        recovery = {'status':'ok','attempted':False,'raw_visible_text':source,'fields':{
            'case_number':'999/26.0EXAMPLE','photo_metadata_date':'2026-07-13',
            'photo_metadata_city':'Ferreira do Alentejo', 'service_entity_type':'gnr',
            'service_entity':'Guarda Nacional Republicana - Posto Territorial de Ferreira do Alentejo'},
            'warnings':['A data é da fotografia, não de uma data de serviço no documento.'],
            'translation_indicators':[]}
        with patch('honorarios_app.services.recover_source_with_openai', return_value=recovery), \
             patch('socket.socket.connect', side_effect=AssertionError('This regression must stay offline.')):
            result = recover_source_upload(filename='synthetic-station.png', content_type='image/png',
                content=self.photo, source_kind='photo', profile_name='auto', ai_recovery_mode='off', paths=self.paths)
        candidate = result['candidate_intake']
        self.assertEqual(candidate['auto_profile']['profile_key'], 'gnr_ferreira_falentejo')
        self.assertTrue(candidate['auto_profile']['auto_applied'])
        self.assertEqual(candidate['transport']['km_one_way'], 50)
        self.assertEqual(candidate['transport']['destination'], 'Posto da GNR de Ferreira do Alentejo')
        self.assertIn('ferreira do alentejo', candidate['service_place'].lower())
        self.assertEqual(candidate['payment_entity'], 'Tribunal de Ferreira do Alentejo')
        self.assertFalse(result['send_allowed'])

    def test_closing_city_fallback_preserves_request_edit_and_deliberate_clear(self):
        for value, cleared in (('Chosen Closing City', []), ('', ['closing_city'])):
            with self.subTest(value=value):
                effective, _, provenance = effective_intake_for_profile({
                    'source_kind': 'notification_pdf', 'closing_city': value,
                    'review_cleared_fields': cleared,
                }, self.paths)
                self.assertEqual(effective['closing_city'], value)
                self.assertNotIn('closing_city', provenance['applied'])
                self.assertEqual('closing_city' in {q['field'] for q in missing_questions(effective)}, not bool(value))

    def upload(self, *, profile="auto", stub_ai=True):
        kwargs = dict(filename="synthetic-source.png", content_type="image/png", content=self.photo, source_kind="photo", profile_name=profile, visible_text="Synthetic interpreting service 999/26.0EXAMPLE on 2026-09-20", ai_recovery_mode="off", paths=self.paths)
        if not stub_ai:
            return recover_source_upload(**kwargs)
        with patch("honorarios_app.services.recover_source_with_openai", return_value={"status": "disabled", "fields": {}}):
            return recover_source_upload(**kwargs)

    def test_default_synthetic_auto_detect_upload_recovers_and_reviews(self):
        result = self.upload()
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["candidate_intake"]["payment_entity"], "Example Court")
        decision = result["source_evidence"]["auto_profile"]
        self.assertEqual(decision["profile_key"], "example_interpreting")
        self.assertEqual(decision["confidence"], "low")
        flag = next(flag for flag in result["source_evidence"]["attention"]["flags"] if flag["code"] == "profile_fallback")
        self.assertIn("payment entity and recipient", flag["detail"])
        self.assertFalse(result["send_allowed"])
        self.assertFalse(list(self.paths.output_dir.glob("*.pdf")))

    def test_ambiguous_upload_keeps_source_evidence_and_asks_for_payment(self):
        first = json.loads(self.paths.service_profiles.read_text(encoding="utf-8"))["example_interpreting"]
        second = copy.deepcopy(first)
        second["defaults"]["payment_entity"] = "Other Synthetic Court"
        second["defaults"]["recipient_email"] = "other@example.test"
        self.paths.service_profiles.write_text(json.dumps({"first": first, "second": second}), encoding="utf-8")
        result = self.upload()
        self.assertNotIn("payment_entity", result["candidate_intake"])
        self.assertNotIn("recipient_email", result["candidate_intake"])
        self.assertEqual(result["candidate_intake"]["case_number"], "999/26.0EXAMPLE")
        self.assertEqual(result["review"]["status"], "needs_info")
        self.assertIn("payment_entity", [question["field"] for question in result["review"]["questions"]])
        self.assertEqual(result["source_evidence"]["auto_profile"]["profile_key"], "")

    def test_missing_configuration_blocks_before_storing_upload_or_calling_ai(self):
        self.paths.service_profiles.unlink()
        with patch("honorarios_app.services.recover_source_with_openai") as provider:
            with self.assertRaisesRegex(IntakeError, "Service profiles are missing.*References"):
                self.upload(stub_ai=False)
            provider.assert_not_called()
        self.assertEqual(list(self.paths.source_upload_dir.iterdir()), [])

    def test_empty_configuration_blocks_before_storing_upload(self):
        self.paths.service_profiles.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(IntakeError, "No service profiles are available"):
            self.upload()
        self.assertEqual(list(self.paths.source_upload_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
