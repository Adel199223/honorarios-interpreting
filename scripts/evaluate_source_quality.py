"""Score fictional source decisions offline; this is not an OCR accuracy claim."""
from __future__ import annotations

import argparse
import copy
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.services import (
    AppPaths, apply_numbered_answers, deep_merge, effective_intake_for_profile,
    extract_candidate_fields, recover_source_upload, review_intake,
)

CORPUS_PATH = ROOT / 'examples' / 'source-quality-cases.json'
FAMILIES = frozenset({
    'court_only', 'source_dates', 'capture_dates', 'pj_gnr', 'pj_hospital',
    'source_cities', 'profile_city', 'work_classification', 'travel', 'recipient',
})
CRITICAL_FIELDS = frozenset({
    'case_number', 'service_date', 'payment_entity', 'service_place', 'recipient_email',
    'recipient', 'transport.destination', 'transport.km_one_way',
})


def materialize_case(value: Any) -> Any:
    """Resolve public placeholders to fictional validator-compatible recipients."""
    if isinstance(value, str):
        domain = 'tribunais' + '.org.pt'
        return value.replace('{{court_primary}}', 'fictional-quality-primary@' + domain).replace(
            '{{court_other}}', 'fictional-quality-other@' + domain)
    if isinstance(value, list):
        return [materialize_case(item) for item in value]
    if isinstance(value, dict):
        return {key: materialize_case(item) for key, item in value.items()}
    return value


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, Any]:
    corpus = json.loads(path.read_text(encoding='utf-8'))
    if corpus.get('schema_version') != 1 or corpus.get('fictional') is not True:
        raise ValueError('Only versioned fictional source-decision corpora are supported.')
    cases = corpus.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('The corpus needs nonempty cases.')
    ids = [case.get('id') for case in cases]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Corpus IDs must be nonempty and unique.')
    if set(corpus.get('families', [])) != FAMILIES or {case.get('family') for case in cases} != FAMILIES:
        raise ValueError('The corpus must cover exactly the ten reviewed scenario families.')
    for case in cases:
        if not isinstance(case.get('input', {}).get('source_text'), str):
            raise ValueError('Each case needs explicit fictional source text.')
        expected = case.get('expected', {})
        if expected.get('review_status') not in {'ready', 'needs_info', 'set_aside', 'error'}:
            raise ValueError('Each case needs an explicit review-status oracle.')
        if not isinstance(expected.get('candidate_fields'), dict) or not isinstance(expected.get('question_fields'), list):
            raise ValueError('Each case needs field and question oracles.')
    return corpus


def nested_value(data: dict[str, Any], key: str) -> Any:
    value: Any = data
    for part in key.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def remove_nested(data: dict[str, Any], key: str) -> None:
    parts = key.split('.')
    value = data
    for part in parts[:-1]:
        value = value.get(part)
        if not isinstance(value, dict):
            return
    value.pop(parts[-1], None)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def observe_case(case: dict[str, Any], environment: dict[str, Any], *,
                 replayed_ai: dict[str, Any] | None = None,
                 visible_text: str | None = None) -> dict[str, Any]:
    """Run real upload/review in disposable data; injected recovery never calls AI."""
    case = materialize_case(case)
    environment = materialize_case(environment)
    source = case['input']
    with tempfile.TemporaryDirectory(prefix='honorarios-source-quality-') as temporary, \
         patch('socket.socket.connect', side_effect=AssertionError('Source decision evaluation must stay offline.')):
        root = Path(temporary)
        create_synthetic_runtime(root)
        paths = AppPaths(**runtime_path_overrides(root))
        _write_json(paths.service_profiles, environment['service_profiles'])
        _write_json(paths.known_destinations, environment['known_destinations'])
        _write_json(paths.court_emails, environment['court_emails'])
        profiles = environment['personal_profiles']
        _write_json(paths.personal_profiles, {
            'schema_version': 1, 'primary_profile_id': profiles[0]['id'], 'profiles': profiles,
        })
        before = {path: path.read_bytes() for path in (
            paths.service_profiles, paths.known_destinations, paths.court_emails,
            paths.personal_profiles, paths.duplicate_index, paths.draft_log,
        )}
        image = Image.new('RGB', (400, 600), 'white')
        content = BytesIO()
        exif = image.getexif()
        if source.get('metadata_date'):
            exif[36867] = source['metadata_date'].replace('-', ':') + ' 10:15:00'
        image.save(content, format='JPEG', exif=exif)
        text = source['source_text'] if visible_text is None else materialize_case(visible_text)
        replay = materialize_case(replayed_ai or source.get('replayed_ai') or {
            'status': 'disabled', 'attempted': False, 'fields': {},
        })
        with patch('honorarios_app.services.recover_source_with_openai', return_value=copy.deepcopy(replay)) as provider:
            upload = recover_source_upload(
                filename=case['id'] + '.jpg', content_type='image/jpeg', content=content.getvalue(),
                source_kind='photo', profile_name=source.get('profile', 'auto'),
                personal_profile_id=source.get('personal_profile_id', ''), visible_text=text,
                ai_recovery_mode='off', paths=paths,
            )
            provider.assert_called_once()
        candidate = copy.deepcopy(upload['candidate_intake'])
        for key in source.get('remove_candidate_fields', []):
            remove_nested(candidate, key)
        candidate = deep_merge(candidate, source.get('intake_overrides', {}))
        review = review_intake(candidate, paths)
        answers = source.get('answers') or {}
        if answers:
            numbers = {question['field']: question['number'] for question in review.get('questions', [])}
            if any(key not in numbers for key in answers):
                raise ValueError('Expected answer field was not asked: ' + case['id'])
            applied = apply_numbered_answers({
                'intake': candidate,
                'answer_text': '\n'.join(f'{numbers[key]}. {value}' for key, value in answers.items()),
            }, paths)
            candidate = applied['intake']
            review = applied
        effective, _, _ = effective_intake_for_profile(candidate, paths)
        # Inspect meaningful decisions and field values, not temp paths or timestamps.
        observation = {
            'candidate': candidate, 'extracted': extract_candidate_fields(text, paths),
            'effective': effective, 'review': review, 'profile': upload['source_evidence']['auto_profile'],
            'question_fields': [question['field'] for question in review.get('questions', [])],
            'managed_data_unchanged': all(path.read_bytes() == value for path, value in before.items()),
            'generated_artifact_count': sum(len(list(directory.rglob('*'))) for directory in (
                paths.output_dir, paths.draft_output_dir, paths.intake_output_dir,
            )),
            'provider_calls': 0, 'input_kind': 'provided_text_or_replayed_recovery',
        }
        return observation


def score_observation(case: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    expected = materialize_case(case['expected'])
    failures: list[dict[str, Any]] = []
    checks = 0
    def check(label: str, actual: Any, wanted: Any, *, critical: bool = False) -> None:
        nonlocal checks
        checks += 1
        if actual != wanted:
            failures.append({'check': label, 'expected': wanted, 'actual': actual, 'critical': critical})
    for name, section in (
        ('candidate_fields', 'candidate'), ('extracted_fields', 'extracted'),
        ('effective_fields', 'effective'), ('profile_fields', 'profile'), ('review_fields', 'review'),
    ):
        for field, value in expected.get(name, {}).items():
            check(section + '.' + field, nested_value(observation[section], field), value,
                  critical=field in CRITICAL_FIELDS)
    for field in expected.get('absent_candidate_fields', []):
        value = nested_value(observation['candidate'], field)
        check('candidate.absent.' + field, value in (None, ''), True, critical=field in CRITICAL_FIELDS)
    check('review.status', observation['review']['status'], expected['review_status'], critical=True)
    required = set(expected['question_fields'])
    actual_questions = set(observation['question_fields'])
    check('questions.required', sorted(required - actual_questions), [])
    if expected['review_status'] != 'needs_info':
        check('questions.unexpected', sorted(actual_questions), [])
    if expected.get('message_contains'):
        check('review.message', expected['message_contains'] in observation['review'].get('message', ''), True)
    for text in expected.get('draft_text_excludes', []):
        check('draft.excludes.' + text, text not in observation['review'].get('draft_text', ''), True)
    check('managed_data_unchanged', observation['managed_data_unchanged'], True)
    check('generated_artifact_count', observation['generated_artifact_count'], 0)
    check('send_allowed', observation['review'].get('send_allowed'), False)
    ready = observation['review']['status'] == 'ready'
    return {
        'id': case['id'], 'family': case['family'], 'passed': not failures,
        'checks': checks, 'passed_checks': checks - len(failures), 'failures': failures,
        'expected_status': expected['review_status'], 'actual_status': observation['review']['status'],
        'expected_question_fields': sorted(required), 'actual_question_fields': sorted(actual_questions),
        'missing_questions': sorted(required - actual_questions),
        'critical_false_readiness': ready and any(failure['critical'] for failure in failures),
        'unnecessary_clarification': expected['review_status'] == 'ready' and observation['review']['status'] == 'needs_info',
    }


def evaluate_case(case: dict[str, Any], environment: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    environment = environment if environment is not None else load_corpus()['environment']
    return score_observation(case, observe_case(case, environment, **kwargs))


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    checks = sum(item['checks'] for item in results)
    passed = sum(item['passed_checks'] for item in results)
    return {
        'schema_version': 1, 'benchmark': 'fictional_source_decisions',
        'provider_calls': 0, 'production_accuracy_established': False,
        'limitation': 'Provided fictional text/replayed recovery tests decision handling, not OCR/model accuracy or production documents.',
        'case_count': len(results), 'passed_cases': sum(item['passed'] for item in results),
        'check_count': checks, 'passed_checks': passed,
        'check_pass_rate': passed / checks if checks else 0,
        'critical_false_readiness_count': sum(item['critical_false_readiness'] for item in results),
        'missing_required_question_count': sum(len(item['missing_questions']) for item in results),
        'unnecessary_clarification_count': sum(item['unnecessary_clarification'] for item in results),
        'families': {family: {'cases': sum(item['family'] == family for item in results),
                              'passed': sum(item['family'] == family and item['passed'] for item in results)}
                     for family in sorted({item['family'] for item in results})},
        'results': results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Print the repeatable scorecard as JSON.')
    parser.add_argument('--case', action='append', default=[], help='Evaluate selected corpus IDs only.')
    args = parser.parse_args(argv)
    corpus = load_corpus()
    unknown = set(args.case) - {case['id'] for case in corpus['cases']}
    if unknown:
        parser.error('Unknown case IDs: ' + ', '.join(sorted(unknown)))
    cases = [case for case in corpus['cases'] if not args.case or case['id'] in args.case]
    report = summarize([evaluate_case(case, corpus['environment']) for case in cases])
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Fictional source decisions: {report['passed_cases']}/{report['case_count']} cases pass; "
              f"{report['critical_false_readiness_count']} critical false-ready decisions; "
              f"{report['missing_required_question_count']} missing required questions.")
        for item in report['results']:
            if not item['passed']:
                print(item['id'] + ': ' + ', '.join(failure['check'] for failure in item['failures']))
        print(report['limitation'])
    return 0 if report['passed_cases'] == report['case_count'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
