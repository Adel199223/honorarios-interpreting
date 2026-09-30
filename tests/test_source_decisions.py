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
