import contextlib
import io
import json
import tempfile
import os
import socket
import subprocess
import shutil
import sys
import unittest
import venv
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


@unittest.skipUnless(os.name == 'nt', 'Windows environment setup helper')
class SetupHelperTests(unittest.TestCase):
    """Exercise the real helper against synthetic environments and offline tool doubles."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / 'scripts'
        self.scripts.mkdir()
        shutil.copy2(Path(__file__).resolve().parents[1] / 'scripts/setup_dev_env.ps1', self.scripts)
        (self.root / '.python-version').write_text('3.11.9\n')
        (self.root / '.node-version').write_text('24.14.0\n')
        (self.root / 'pyproject.toml').write_text('[tool.uv]\nrequired-version="==0.12.20"\n')
        self.log = self.root / 'calls.log'
        (self.scripts / 'check_dev_environment.py').write_text(
            'import os, pathlib, sys\n'
            'with pathlib.Path(os.environ["SETUP_TEST_LOG"]).open("a") as log:\n'
            '    log.write("existing-check\\n")\n'
            'sys.exit(3 if os.environ.get("SETUP_TEST_BLOCKED") else 0)\n', encoding='utf-8')
        self.bin = self.root / 'tools'
        self.bin.mkdir()
        (self.bin / 'uv.cmd').write_text(
            '@echo off\n'
            '>> "%SETUP_TEST_LOG%" echo uv %*\n'
            'if "%~1"=="--version" (\n'
            '  echo uv 0.12.20\n'
            '  exit /b 0\n'
            ')\n'
            'if "%~1"=="python" exit /b 87\n'
            'exit /b 0\n', encoding='utf-8')
        (self.bin / 'node.cmd').write_text('@echo off\necho v24.14.0\nexit /b 0\n', encoding='utf-8')
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'SETUP_TEST_LOG': str(self.log)}
        self.env.pop('SETUP_TEST_BLOCKED', None)

    def create_environment(self, name='.venv311'):
        path = self.root / name
        venv.EnvBuilder(with_pip=False).create(path)
        return path

    def run_setup(self, *args):
        return subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
             str(self.scripts / 'setup_dev_env.ps1'), *args],
            cwd=self.root, env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=30)

    def calls(self):
        return self.log.read_text(encoding='utf-8').splitlines() if self.log.exists() else []

    def test_healthy_existing_environment_uses_its_base_without_uv_discovery(self):
        for name in ('.venv311', '.venv311-check'):
            with self.subTest(name=name):
                path = self.create_environment(name)
                base = subprocess.check_output(
                    [str(path / 'Scripts/python.exe'), '-I', '-c', 'import sys; print(sys._base_executable)'],
                    text=True, encoding='utf-8').strip()
                result = self.run_setup('-VenvName', name)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = self.calls()
                self.assertFalse(any(line.startswith('uv python') for line in calls))
                sync = next(line for line in calls if line.startswith('uv sync '))
                self.assertIn(base, sync)
                self.assertLess(calls.index('existing-check'), next(i for i, line in enumerate(calls) if line.startswith('uv lock ')))
                self.log.unlink()

    def test_invalid_existing_environment_is_preserved_with_or_without_override(self):
        path = self.create_environment()
        sentinel = path / 'preserve.txt'
        sentinel.write_bytes(b'existing environment remains untouched')
        original_cfg = (path / 'pyvenv.cfg').read_bytes()
        self.env['SETUP_TEST_BLOCKED'] = '1'
        for args in ((), ('-PythonExecutable', sys.executable)):
            with self.subTest(args=args):
                result = self.run_setup(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('exit 3', result.stderr)
                self.assertEqual(self.calls(), ['uv --version', 'existing-check'])
                self.assertEqual(sentinel.read_bytes(), b'existing environment remains untouched')
                self.assertEqual((path / 'pyvenv.cfg').read_bytes(), original_cfg)
                self.log.unlink()

    def test_explicit_interpreter_override_takes_priority_after_existing_check(self):
        self.create_environment()
        result = self.run_setup('-PythonExecutable', sys.executable)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertFalse(any(line.startswith('uv python') for line in calls))
        for line in calls:
            if line.startswith(('uv lock ', 'uv sync ')):
                self.assertIn(sys.executable, line)

    def test_incomplete_existing_directory_stops_without_interpreter_discovery(self):
        path = self.root / '.venv311'
        path.mkdir()
        sentinel = path / 'keep.txt'
        sentinel.write_bytes(b'not an environment')
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('has been preserved', result.stderr)
        self.assertEqual(self.calls(), ['uv --version'])
        self.assertEqual(sentinel.read_bytes(), b'not an environment')

    def test_existing_base_still_requires_exact_pin_before_lock_or_sync(self):
        self.create_environment()
        (self.root / '.python-version').write_text('3.11.8\n')
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('AssertionError', result.stderr)
        self.assertEqual(self.calls(), ['uv --version', 'existing-check'])

    def test_missing_environment_keeps_non_downloading_discovery(self):
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exit 87', result.stderr)
        self.assertEqual(self.calls(), ['uv --version', 'uv python find 3.11.9 --no-project --no-python-downloads'])
        self.assertFalse((self.root / '.venv311').exists())


@unittest.skipUnless(os.name == 'nt', 'Windows synthetic launcher child boundary')
class SyntheticLauncherEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honorarios-launcher-boundary-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        shutil.copy2(Path(__file__).resolve().parents[1] / 'scripts/start_dev.ps1', scripts)
        (scripts / 'check_dev_environment.py').write_text('import sys\nsys.exit(0)\n', encoding='utf-8')
        venv.EnvBuilder(with_pip=False).create(self.root / '.venv311')
        package = self.root / 'honorarios_app'
        package.mkdir()
        (package / '__init__.py').write_text('', encoding='utf-8')
        self.child_report = self.root / 'child.json'
        self.parent_report = self.root / 'parent.json'
        self.runtime = self.root / 'runtime'
        self.values = {
            'OPENAI_API_KEY': 'synthetic-key-not-a-provider-secret',
            'GMAIL_CLIENT_SECRET': 'synthetic-secret',
            'GOOGLE_PHOTOS_TOKEN_PATH': 'synthetic-outside-token.json',
            'HONORARIOS_RUNTIME_ROOT': 'synthetic-wrong-runtime',
            'HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE': '1',
            'PYTHONPATH': str(self.root / 'unused-modules'),
            'PYTHONHOME': sys.base_prefix,
            'HONORARIOS_UV_EXECUTABLE': 'synthetic-uv-tool',
            'LAUNCHER_UNRELATED_VALUE': 'preserved',
        }
        self.env = {**os.environ, **self.values, 'LAUNCHER_CHILD_REPORT': str(self.child_report)}
        (package / 'web.py').write_text(
            'import json, os, pathlib, sys\n'
            f'names = {list(self.values)!r}\n'
            'pathlib.Path(os.environ["LAUNCHER_CHILD_REPORT"]).write_text(json.dumps({\n'
            ' "environment": {name: os.environ.get(name) for name in names}, "args": sys.argv[1:]}), encoding="utf-8")\n'
            'sys.exit(int(os.environ.get("LAUNCHER_CHILD_EXIT", "0")))\n', encoding='utf-8')

    def create_marker(self):
        from honorarios_app.runtime import create_synthetic_runtime
        create_synthetic_runtime(self.runtime)

    def run_launcher(self, *args):
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        driver = self.root / 'driver.ps1'
        driver.write_text(
            "$failure = $null\ntry {\n  & " + quote(self.root / 'scripts/start_dev.ps1') +
            f' -Port {port} -RuntimeRoot ' + quote(self.runtime) + ' ' + ' '.join(args) +
            "\n} catch { $failure = $_.Exception.Message } finally {\n  $report = @{}\n" +
            '  foreach ($name in @(' + ','.join(quote(name) for name in self.values) + ')) {\n' +
            "    $report[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')\n  }\n" +
            '  $report | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath ' + quote(self.parent_report) +
            '\n}\nif ($failure) { Write-Error $failure; exit 1 }\n', encoding='utf-8')
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(driver)],
                                cwd=self.root, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(self.parent_report.read_text(encoding='utf-8-sig')), self.values)
        return result

    def assert_isolated_child(self):
        report = json.loads(self.child_report.read_text(encoding='utf-8'))
        retained = {'HONORARIOS_UV_EXECUTABLE', 'LAUNCHER_UNRELATED_VALUE'}
        self.assertEqual(report['environment'], {name: value if name in retained else None for name, value in self.values.items()})
        self.assertEqual(report['args'].count('--runtime-root'), 1)
        runtime_arg = report['args'][report['args'].index('--runtime-root') + 1]
        self.assertEqual(Path(runtime_arg).resolve(), self.runtime.resolve())
        return report

    def test_new_synthetic_child_strips_provider_environment_and_restores_parent(self):
        result = self.run_launcher('-Synthetic')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('--init-synthetic-runtime', self.assert_isolated_child()['args'])

    def test_existing_marked_runtime_is_isolated_without_reinitialization(self):
        self.create_marker()
        before = {path.relative_to(self.runtime): path.read_bytes() for path in self.runtime.rglob('*') if path.is_file()}
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('--init-synthetic-runtime', self.assert_isolated_child()['args'])
        self.assertEqual(before, {path.relative_to(self.runtime): path.read_bytes() for path in self.runtime.rglob('*') if path.is_file()})

    def test_child_failure_and_check_only_restore_parent_environment(self):
        self.create_marker()
        self.env['LAUNCHER_CHILD_EXIT'] = '23'
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Server exited with code 23', result.stderr)
        self.assert_isolated_child()
        self.child_report.unlink()
        result = self.run_launcher('-CheckOnly')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.child_report.exists())

    def test_ordinary_runtime_keeps_provider_environment(self):
        self.runtime.mkdir()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.child_report.read_text(encoding='utf-8'))['environment'], self.values)

    def test_invalid_marker_refuses_launch_without_touching_environment(self):
        self.create_marker()
        marker_path = self.runtime / 'config/synthetic-runtime.local.json'
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
        marker['synthetic_runtime'] = 'true'
        marker_path.write_text(json.dumps(marker), encoding='utf-8')
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('marker is invalid', ' '.join(result.stderr.split()))
        self.assertFalse(self.child_report.exists())


if __name__ == '__main__':
    unittest.main()
