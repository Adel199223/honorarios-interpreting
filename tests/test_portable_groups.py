"""Group membership, dispatch and private-fixture exclusion regressions."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import run_portable_tests as runner

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'quick': ['test_portable_groups.py', 'test_intake_rules.py', 'test_pdf_rules.py', 'test_email_rules.py',
              'test_source_evidence.py', 'test_service_profile_selection.py', 'test_review_guidance.py', 'test_claim_options.py', 'test_claim_options_ui.py'],
    'intake': ['test_intake_rules.py', 'test_source_evidence.py', 'test_service_profile_selection.py', 'test_public_runtime.py',
               'test_source_decisions.py', 'test_public_ai_recovery.py', 'test_multi_case_sources.py', 'test_claim_options.py'],
    'quality': ['test_source_decisions.py', 'test_photo_defaults.py', 'test_multi_case_sources.py'],
    'pdf': ['test_pdf_rules.py', 'test_claim_options.py'],
    'email': ['test_email_rules.py', 'test_public_email.py', 'test_claim_options.py'],
    'ui': ['test_browser_iab_smoke.py', 'test_review_guidance.py', 'test_public_ui.py', 'test_claim_options_ui.py'],
    'package': ['test_dev_environment.py', 'test_installed_wheel.py', 'test_prepared_candidate.py',
                'test_public_repo_gate.py', 'test_public_publication.py'],
    'integration': ['test_public_adapter.py'],
}


class PortableGroupTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-group-regression-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / 'source'
        (source / 'tests').mkdir(parents=True)
        names = sorted(runner.PUBLIC_TEST_FILES)
        for name in names:
            (source / 'tests' / name).write_text('# Explicit public fixture\n', encoding='utf-8')
        for relative in runner.PUBLIC_EVALUATION_FILES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}', encoding='utf-8')
        groups = {**copy.deepcopy(EXPECTED), 'full': names}
        (source / 'tests/portable-suite.txt').write_text('\n'.join(names) + '\n', encoding='utf-8')
        self.write_groups(source, groups)
        return root, source, groups

    @staticmethod
    def write_groups(root, groups):
        (root / 'tests/portable-groups.json').write_text(json.dumps(groups), encoding='utf-8')

    def test_every_group_has_exact_reviewed_membership(self):
        names, full = runner.load_selection(ROOT)
        self.assertEqual(set(names), runner.PUBLIC_TEST_FILES)
        self.assertEqual(full, names)
        self.assertEqual(set(EXPECTED) | {'full'}, set(runner.GROUP_NAMES))
        for group, expected in EXPECTED.items():
            with self.subTest(group=group):
                self.assertEqual(runner.load_selection(ROOT, group)[1], expected)

    def test_full_loads_each_test_once_and_focused_groups_have_cases(self):
        # The loader can expose accidental inherited test duplication after splits.
        sys.path.insert(0, str(ROOT / 'tests'))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / 'tests')))
        def ids(suite):
            result = []
            for item in suite:
                result.extend(ids(item) if isinstance(item, unittest.TestSuite) else [item.id()])
            return result
        all_ids = []
        for name in runner.load_selection(ROOT)[1]:
            all_ids += ids(unittest.defaultTestLoader.loadTestsFromName(name[:-3]))
        self.assertEqual(len(all_ids), len(set(all_ids)))
        for group in EXPECTED:
            self.assertTrue(any(unittest.defaultTestLoader.loadTestsFromName(name[:-3]).countTestCases()
                                for name in runner.load_selection(ROOT, group)[1]), group)

    def test_runner_dispatches_only_selected_group_modules(self):
        selected = EXPECTED['pdf']
        with patch.object(runner.unittest.defaultTestLoader, 'loadTestsFromName', return_value=unittest.TestSuite()) as loader, \
             patch.object(runner.unittest, 'TextTestRunner') as reporter, redirect_stdout(StringIO()):
            reporter.return_value.run.return_value.wasSuccessful.return_value = True
            self.assertEqual(runner.run_suite('pdf'), 0)
        self.assertEqual([call.args[0] for call in loader.call_args_list], [name[:-3] for name in selected])

    def test_default_and_explicit_group_are_forwarded_to_isolated_child(self):
        for args, expected in (([], 'full'), (['--group', 'email'], 'email')):
            with self.subTest(args=args), patch.object(runner, 'copy_portable_checkout'), \
                 patch.object(runner.subprocess, 'run') as process:
                process.return_value.returncode = 0
                self.assertEqual(runner.main(args), 0)
                command = process.call_args.args[0]
                self.assertEqual(command[-3:], ['--isolated-child', '--group', expected])
                self.assertEqual(Path(process.call_args.kwargs['cwd']).name, 'source')

    def test_provider_and_private_runtime_environment_is_removed(self):
        env = {'OPENAI_API_KEY': 'fictional', 'GMAIL_CLIENT_SECRET': 'fictional', 'GOOGLE_TOKEN': 'fictional',
               'HONORARIOS_RUNTIME_ROOT': 'fictional-private-root', 'honorarios_fake_gmail': '1',
               'PYTHONPATH': 'fictional-import-path', 'PYTHONHOME': 'fictional-python',
               'HONORARIOS_UV_EXECUTABLE': 'uv', 'PATH': 'safe-path'}
        self.assertEqual(runner.isolated_environment(env), {'HONORARIOS_UV_EXECUTABLE': 'uv', 'PATH': 'safe-path'})
        self.assertEqual(len(env), 9)

    def test_unlisted_private_tests_and_runtime_files_are_never_copied(self):
        root, source, _ = self.fixture()
        (source / 'tests/test_local_private.py').write_text('raise AssertionError("must never import")\n', encoding='utf-8')
        for directory in ('config', 'data', 'output', '.venv311'):
            (source / directory).mkdir()
            (source / directory / 'private.json').write_text('fictional-private-overlay', encoding='utf-8')
        target = root / 'target'
        runner.copy_portable_checkout(source, target)
        self.assertFalse((target / 'tests/test_local_private.py').exists())
        for directory in ('config', 'data', 'output', '.venv311'):
            self.assertFalse((target / directory / 'private.json').exists())
        self.assertTrue((target / 'tests/portable-groups.json').is_file())
        self.assertTrue((target / 'examples/source-quality-cases.json').is_file())

    def test_unlisted_evaluation_data_is_never_copied(self):
        root, source, _ = self.fixture()
        (source / 'examples/private-source.json').write_text('fictional private sentinel', encoding='utf-8')
        target = root / 'target'
        runner.copy_portable_checkout(source, target)
        self.assertFalse((target / 'examples/private-source.json').exists())
        self.assertTrue((target / 'examples/source-quality-cases.json').is_file())

    def test_missing_evaluation_fixture_fails_before_copy(self):
        root, source, _ = self.fixture()
        (source / 'examples/source-quality-cases.json').unlink()
        target = root / 'target'
        with self.assertRaisesRegex(ValueError, 'Missing public evaluation fixture'):
            runner.copy_portable_checkout(source, target)
        self.assertFalse(target.exists())

    def test_unsafe_manifest_fails_before_any_copy_or_git_mutation(self):
        root, source, _ = self.fixture()
        for name in ('../test_private.py', 'test_local_private.py', 'test_missing.py'):
            with self.subTest(name=name):
                (source / 'tests/portable-suite.txt').write_text(name + '\n', encoding='utf-8')
                target = root / 'target'
                with self.assertRaisesRegex(ValueError, 'Unsupported or missing public'):
                    runner.copy_portable_checkout(source, target)
                self.assertFalse(target.exists())

    def test_reduced_manifest_cannot_silently_shrink_full(self):
        _, source, _ = self.fixture()
        (source / 'tests/portable-suite.txt').write_text('test_pdf_rules.py\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'complete public code allowlist'):
            runner.load_selection(source)

    def test_unselected_group_with_private_duplicate_or_missing_members_fails(self):
        _, source, groups = self.fixture()
        for members in (['test_local_private.py'], ['test_pdf_rules.py', 'test_pdf_rules.py'], []):
            with self.subTest(members=members):
                changed = copy.deepcopy(groups)
                changed['email'] = members
                self.write_groups(source, changed)
                with self.assertRaises(ValueError):
                    runner.load_selection(source, 'pdf')

    def test_full_group_cannot_omit_or_reorder_manifest_members(self):
        _, source, groups = self.fixture()
        for members in (groups['full'][:-1], list(reversed(groups['full']))):
            changed = copy.deepcopy(groups)
            changed['full'] = members
            self.write_groups(source, changed)
            with self.assertRaisesRegex(ValueError, 'full group must match'):
                runner.load_selection(source)

    def test_unknown_group_is_rejected_before_environment_copy(self):
        with patch.object(runner, 'copy_portable_checkout') as copier:
            with self.assertRaises(SystemExit) as error, redirect_stderr(StringIO()):
                runner.main(['--group', 'private'])
        self.assertEqual(error.exception.code, 2)
        copier.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'PowerShell entrypoint guard is Windows-only')
    def test_full_validator_refuses_a_reduced_group(self):
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                 str(ROOT / 'scripts/validate_dev.ps1'), '-Full', '-Group', 'quick'],
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('-Full requires the complete full test group', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
