"""Fictional source decision oracles and consequential evaluator safeguards."""
from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import evaluate_source_quality as evaluator
from scripts.source_parsing import explicit_service_places, service_date_evidence

CORPUS = evaluator.load_corpus()


class SourceDecisionTests(unittest.TestCase):
    """Each case compares actual upload/review decisions with a frozen oracle."""


def _scenario_test(case):
    def test(self):
        result = evaluator.evaluate_case(case, CORPUS['environment'])
        self.assertTrue(result['passed'], json.dumps(result, ensure_ascii=False, indent=2))
    test.__doc__ = 'Fictional source decision: ' + case['id']
    return test


for _case in CORPUS['cases']:
    setattr(SourceDecisionTests, 'test_' + _case['id'], _scenario_test(_case))


class SourceDateLineWrappingTests(unittest.TestCase):
    def test_performed_date_connector_spans_one_wrapped_line(self):
        evidence = service_date_evidence(
            'Documento emitido em 18/09/2026.\n'
            'Declara-se que o serviço de interpretação foi realizado em\n'
            '26/09/2026 no Tribunal do Trabalho de Beja. Assinatura: 2026-09-30.')
        self.assertEqual(evidence.value, '2026-09-26')
        self.assertFalse(evidence.needs_confirmation)

    def test_wrapped_issue_label_does_not_supply_service_date(self):
        evidence = service_date_evidence('Documento emitido em\n30/09/2026.')
        self.assertEqual(evidence.value, '')
        self.assertEqual(evidence.candidates, ('2026-09-30',))
        self.assertTrue(evidence.needs_confirmation)

    def test_unrelated_heading_does_not_label_next_line_date(self):
        evidence = service_date_evidence(
            'Documento emitido em 18/09/2026.\n'
            'Serviço de interpretação\n26/09/2026. Assinatura: 2026-09-30.')
        self.assertEqual(evidence.value, '')
        self.assertTrue(evidence.needs_confirmation)

    def test_blank_line_keeps_service_label_separate(self):
        evidence = service_date_evidence(
            'Documento emitido em 18/09/2026.\n'
            'Serviço de interpretação realizado em\n\n26/09/2026.')
        self.assertEqual(evidence.value, '')
        self.assertTrue(evidence.needs_confirmation)

    def test_terminal_sentence_keeps_later_unlabelled_date_separate(self):
        evidence = service_date_evidence(
            'Documento emitido em 18/09/2026.\n'
            'Serviço de interpretação realizado.\n26/09/2026.')
        self.assertEqual(evidence.value, '')
        self.assertTrue(evidence.needs_confirmation)


class SourcePlaceRoleTests(unittest.TestCase):
    def test_court_host_on_line_after_wrapped_service_date_label(self):
        self.assertEqual(explicit_service_places(
            'Declara-se que o serviço de interpretação foi realizado em\n'
            '26/09/2026 no Tribunal do Trabalho de Beja.'), ('Tribunal do Trabalho de Beja',))

    def test_court_host_after_wrapped_place_preposition(self):
        self.assertEqual(explicit_service_places(
            'Declara-se que o serviço de interpretação foi realizado em 26/09/2026 no\n'
            'Tribunal do Trabalho de Beja.'), ('Tribunal do Trabalho de Beja',))

    def test_wrapped_psp_institution_and_city_are_preserved(self):
        for text, place in (
            ('Serviço de interpretação realizado em 26/09/2026 na\nEsquadra da PSP de Serpa.', 'Esquadra da PSP de Serpa'),
            ('Serviço de interpretação realizado em\nSerpa.', 'Serpa'),
        ):
            with self.subTest(place=place):
                self.assertEqual(explicit_service_places(text), (place,))

    def test_blank_line_does_not_bridge_place_preposition_to_heading(self):
        self.assertEqual(explicit_service_places(
            'Serviço de interpretação realizado em 26/09/2026 no\n\nTribunal do Trabalho de Beja.'), ())

    def test_completed_sentence_does_not_bind_standalone_host_heading(self):
        self.assertEqual(explicit_service_places(
            'Serviço de interpretação realizado em 26/09/2026.\nTribunal do Trabalho de Beja.'), ())

    def test_procedural_scope_is_not_a_physical_location(self):
        self.assertEqual(explicit_service_places(
            'Serviço de interpretação prestado no âmbito do processo 100/26.0TSTXX em 26/09/2026.'), ())

    def test_service_day_and_procedural_scope_are_not_locations(self):
        self.assertEqual(explicit_service_places(
            'Diligência de interpretação realizada no dia 26/09/2026 no âmbito do processo 100/26.0TSTXX.'), ())

    def test_named_gnr_host_survives_procedural_tail(self):
        self.assertEqual(explicit_service_places(
            'Prestou serviço de interpretação no Posto da GNR de Beja no âmbito do processo 100/26.0TSTXX em 26/09/2026.'),
            ('Posto da GNR de Beja',))

    def test_date_phrase_is_not_a_physical_location(self):
        self.assertEqual(explicit_service_places(
            'Serviço de interpretação prestado na data de 26/09/2026.'), ())

    def test_service_period_is_not_a_physical_location(self):
        self.assertEqual(explicit_service_places(
            'Serviço de interpretação prestado no período da manhã em 26/09/2026.'), ())

    def test_hospital_host_survives_date_tail(self):
        self.assertEqual(explicit_service_places(
            'Serviço de interpretação prestado no Hospital de Faro na data de 26/09/2026.'),
            ('Hospital de Faro',))

    def test_labour_court_host_survives_period_tail(self):
        self.assertEqual(explicit_service_places(
            'Diligência de interpretação realizada no Tribunal do Trabalho de Beja no período da manhã.'),
            ('Tribunal do Trabalho de Beja',))


class SourceEvaluationTests(unittest.TestCase):
    def observation(self):
        return {
            'candidate': {'case_number': '710/26.0TSTXX', 'service_date': '2026-09-26'},
            'effective': {}, 'extracted': {}, 'profile': {},
            'review': {'status': 'ready', 'send_allowed': False}, 'question_fields': [],
            'managed_data_unchanged': True, 'generated_artifact_count': 0,
        }

    def test_corruption_cannot_shrink_or_relabel_corpus(self):
        mutations = [
            lambda corpus: corpus.update(fictional=False),
            lambda corpus: corpus['cases'].append(copy.deepcopy(corpus['cases'][0])),
            lambda corpus: corpus.update(cases=[corpus['cases'][0]]),
            lambda corpus: corpus['cases'][0]['expected'].pop('review_status'),
        ]
        with tempfile.TemporaryDirectory(prefix='honorarios-quality-schema-') as temporary:
            path = Path(temporary) / 'corpus.json'
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    value = copy.deepcopy(CORPUS)
                    mutation(value)
                    path.write_text(json.dumps(value), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        evaluator.load_corpus(path)

    def test_confident_wrong_date_counts_as_critical_false_readiness(self):
        case = copy.deepcopy(CORPUS['cases'][1])
        observation = self.observation()
        observation['candidate']['service_date'] = '2026-09-30'
        result = evaluator.score_observation(case, observation)
        report = evaluator.summarize([result])
        self.assertEqual(report['critical_false_readiness_count'], 1)
        self.assertFalse(result['passed'])
        self.assertFalse(report['production_accuracy_established'])

    def test_false_ready_missing_required_date_question_is_counted(self):
        case = next(case for case in CORPUS['cases'] if case['id'] == 'date_issue_only')
        result = evaluator.score_observation(case, self.observation())
        report = evaluator.summarize([result])
        self.assertEqual(report['critical_false_readiness_count'], 1)
        self.assertEqual(report['missing_required_question_count'], 1)
        self.assertEqual(result['missing_questions'], ['service_date'])

    def test_correct_abstention_and_wrong_field_are_distinct(self):
        case = next(case for case in CORPUS['cases'] if case['id'] == 'date_issue_only')
        observation = self.observation()
        observation['candidate'].pop('service_date')
        observation['review']['status'] = 'needs_info'
        observation['question_fields'] = ['service_date']
        result = evaluator.score_observation(case, observation)
        self.assertTrue(result['passed'])
        self.assertFalse(result['critical_false_readiness'])

    def test_unnecessary_clarification_is_measured(self):
        observation = self.observation()
        observation['review']['status'] = 'needs_info'
        observation['question_fields'] = ['service_date']
        result = evaluator.score_observation(CORPUS['cases'][1], observation)
        self.assertEqual(evaluator.summarize([result])['unnecessary_clarification_count'], 1)
        self.assertFalse(result['critical_false_readiness'])

    def test_managed_writes_artifacts_and_send_flags_fail_evaluation(self):
        for key, value in (('managed_data_unchanged', False), ('generated_artifact_count', 1)):
            observation = self.observation()
            observation[key] = value
            result = evaluator.score_observation(CORPUS['cases'][1], observation)
            self.assertIn(key, [failure['check'] for failure in result['failures']])
        observation = self.observation()
        observation['review']['send_allowed'] = True
        result = evaluator.score_observation(CORPUS['cases'][1], observation)
        self.assertIn('send_allowed', [failure['check'] for failure in result['failures']])

    def test_injected_recovery_stays_offline_and_uses_explicit_corrections(self):
        case = copy.deepcopy(CORPUS['cases'][1])
        case['input']['source_text'] = 'Processo 710/26.0TSTXX\nData ilegível.'
        case['input']['intake_overrides'] = {'service_date': '2026-09-26', 'service_date_source': 'user_confirmed'}
        replay = {'status': 'ok', 'attempted': True, 'fields': {'service_date': '2026-09-30'}}
        observed = evaluator.observe_case(case, CORPUS['environment'], replayed_ai=replay)
        self.assertEqual(observed['candidate']['ai_recovery']['fields']['service_date'], '2026-09-30')
        self.assertEqual(observed['candidate']['service_date'], '2026-09-26')
        self.assertEqual(observed['provider_calls'], 0)
        self.assertTrue(observed['managed_data_unchanged'])

    def test_case_filter_cannot_silently_ignore_unknown_cases(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            evaluator.main(['--case', 'not-in-corpus'])
        self.assertEqual(error.exception.code, 2)
        with patch.object(evaluator, 'evaluate_case') as evaluate, redirect_stdout(StringIO()):
            evaluate.return_value = evaluator.score_observation(CORPUS['cases'][1], self.observation())
            self.assertEqual(evaluator.main(['--case', 'court_clear_eu', '--json']), 0)
        self.assertEqual(evaluate.call_count, 1)
        self.assertEqual(evaluate.call_args.args[0]['id'], 'court_clear_eu')


if __name__ == '__main__':
    unittest.main()
