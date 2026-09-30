import contextlib
import io
import tempfile
import os
import socket
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.check_dev_environment import evaluate_environment
from scripts.runtime_doctor import main as doctor_main
from scripts.run_portable_tests import PUBLIC_EVALUATION_FILES, copy_portable_checkout
from scripts.public_release_gate import _iter_scannable_files, _matches_existing_paths


class DevelopmentEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.python-version').write_text('3.11.9\n')
        (self.root / '.node-version').write_text('24.14.0\n')
        (self.root / 'pyproject.toml').write_text('[project]\ndependencies=["fastapi>=0.115"]\n[project.optional-dependencies]\ndev=["pytest==9.0.2"]\n[tool.uv]\nrequired-version="==0.12.20"\n')
        (self.root / 'uv.lock').write_text('[[package]]\nname="fastapi"\nversion="0.136.1"\n[[package]]\nname="pytest"\nversion="9.0.2"\n')

    def evaluate(self, **changes):
        args = dict(python_version='3.11.9', prefix=self.root / '.venv311', distributions={'fastapi': '0.136.1', 'pytest': '9.0.2'}, probe=lambda tool: {'uv':'0.12.20', 'node':'24.14.0'}[tool])
        args.update(changes)
        return evaluate_environment(self.root, **args)

    def test_supported_environment_is_read_only_and_secret_free(self):
        report = self.evaluate()
        self.assertEqual(report['status'], 'ready')
        self.assertFalse(report['write_allowed'])
        self.assertFalse(report['managed_data_changed'])
        self.assertNotIn(str(self.root), str(report))

    def test_wrong_global_python_is_blocked(self):
        report = self.evaluate(python_version='3.14.4', prefix=self.root.parent)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual([c['name'] for c in report['checks'] if c['status']=='blocked'], ['python', 'project_environment'])

    def test_changed_package_version_is_blocked(self):
        report = self.evaluate(distributions={'fastapi':'0.137.0', 'pytest':'9.0.2'})
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual([c['name'] for c in report['checks'] if c['status']=='blocked'], ['package:fastapi'])

    def test_missing_required_dependency_is_blocked(self):
        self.assertEqual(self.evaluate(distributions={'pytest':'9.0.2'})['status'], 'blocked')

    def test_unavailable_tool_is_blocked_without_leaking_exception(self):
        def unavailable(tool):
            raise FileNotFoundError('private machine path')
        report = self.evaluate(probe=unavailable)
        self.assertEqual(report['status'], 'blocked')
        self.assertNotIn('private machine path', str(report))

    def test_runtime_doctor_cli_rejects_blocked_readiness(self):
        for status, code in [('blocked', 1), ('ready', 0)]:
            with self.subTest(status=status), patch('scripts.runtime_doctor.run_runtime_doctor', return_value=SimpleNamespace(status=status, safe_summary=lambda: {'status':status})), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(doctor_main(['--json']), code)

    def test_portable_checkout_omits_private_overlays_and_unlisted_tests(self):
        source = self.root / 'source'
        target = self.root / 'isolated'
        (source / 'tests').mkdir(parents=True)
        (source / 'config').mkdir()
        (source / 'data').mkdir()
        project_tests = Path(__file__).resolve().parent
        names = (project_tests / 'portable-suite.txt').read_text(encoding='utf-8').splitlines()
        (source / 'tests/portable-suite.txt').write_text('\n'.join(names) + '\n', encoding='utf-8')
        (source / 'tests/portable-groups.json').write_text((project_tests / 'portable-groups.json').read_text(encoding='utf-8'), encoding='utf-8')
        for name in names:
            (source / 'tests' / name).write_text('# Synthetic public fixture\n', encoding='utf-8')
        for relative in PUBLIC_EVALUATION_FILES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}', encoding='utf-8')
        (source / 'tests/test_private.py').write_text('do not copy')
        (source / 'config/profile.json').write_text('private synthetic sentinel')
        (source / 'config/ai.local.json').write_text('private synthetic sentinel')
        (source / 'data/duplicate-index.json').write_text('private synthetic sentinel')
        (source / 'config/profile.example.json').write_text('{}')
        copy_portable_checkout(source, target)
        self.assertTrue((target / 'config/profile.example.json').is_file())
        self.assertTrue((target / 'tests/test_pdf_rules.py').is_file())
        for path in ('config/profile.json','config/ai.local.json','data/duplicate-index.json','tests/test_private.py'):
            self.assertFalse((target / path).exists(), path)

    def test_release_scan_skips_environment_and_worktrees_but_still_blocks_release(self):
        (self.root / 'README.md').write_text('Public source')
        for name in ('.venv311', '.venv311-reconstruction', '.worktrees', '.tmp-test'):
            folder = self.root / name / 'nested'
            folder.mkdir(parents=True)
            (folder / 'private-sentinel.json').write_text('do not scan')
        scanned = _iter_scannable_files(self.root)
        self.assertFalse(any('private-sentinel' in str(path) for path in scanned))
        self.assertIn(self.root / 'README.md', scanned)
        blockers = _matches_existing_paths(self.root)
        for name in ('.venv311/', '.venv311-reconstruction/', '.worktrees/', '.tmp-test/'):
            self.assertIn(name, blockers)

    @unittest.skipUnless(os.name == 'nt', 'Windows coexistence launcher')
    def test_synthetic_launcher_refuses_populated_runtime_without_changing_files(self):
        sentinel = self.root / 'existing-record.json'
        sentinel.write_bytes(b'preserve existing records')
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(project_root / 'scripts/start_dev.ps1'), '-Synthetic', '-RuntimeRoot', str(self.root), '-CheckOnly'], cwd=project_root, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('new or empty', result.stderr)
        self.assertEqual(sentinel.read_bytes(), b'preserve existing records')

    @unittest.skipUnless(os.name == 'nt', 'Windows coexistence launcher')
    def test_launcher_refuses_occupied_port(self):
        project_root = Path(__file__).resolve().parents[1]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(project_root / 'scripts/start_dev.ps1'), '-Port', str(port), '-CheckOnly'], cwd=project_root, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('occupied', result.stderr)


if __name__ == '__main__':
    unittest.main()
