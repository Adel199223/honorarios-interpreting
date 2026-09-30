"""Run only the explicitly public synthetic suite; local private regressions stay separate."""
from __future__ import annotations
import re
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_suite() -> int:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'tests'))
    names = (ROOT / 'tests' / 'portable-suite.txt').read_text(encoding='utf-8').splitlines()
    if not names or len(set(names)) != len(names):
        raise ValueError('Portable test manifest must be nonempty and unique.')
    suite = unittest.TestSuite()
    for name in names:
        if not re.fullmatch(r'test_[a-z0-9_]+\.py', name) or not (ROOT / 'tests' / name).is_file():
            raise ValueError('Invalid or missing portable test file: ' + name)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name[:-3]))
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


def copy_portable_checkout(source: Path, target: Path) -> None:
    """Copy source/assets and explicitly public fixtures, never private runtime overlays."""
    source_files = [source / name for name in (
        '.gitignore', '.python-version', '.node-version', 'pyproject.toml', 'uv.lock',
        'requirements.txt', 'README.md', 'CONTRIBUTING.md', 'LICENSE', 'SECURITY.md',
        'agent.md', 'APP_KNOWLEDGE.md', '.githooks/pre-commit',
        'config/email.example.json', 'config/profile.example.json', 'config/profiles.example.json',
        'config/gmail.example.json', 'config/google-photos.example.json',
        'data/court-emails.example.json', 'data/known-destinations.example.json',
        'data/service-profiles.example.json', 'examples/intake.synthetic.example.json',
    )]
    extensions = {'.py','.ps1','.mjs','.js','.css','.html','.md','.json','.yml','.yaml'}
    for directory in ('honorarios_app', 'scripts', 'templates', 'docs', '.github', '.circleci'):
        source_files += [p for p in (source / directory).rglob('*') if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts]
    manifest = source / 'tests/portable-suite.txt'
    names = manifest.read_text(encoding='utf-8').splitlines()
    source_files.append(manifest)
    for name in names:
        if not re.fullmatch(r'test_[a-z0-9_]+\.py', name):
            raise ValueError('Unsafe portable test name.')
        source_files.append(source / 'tests' / name)
    for path in source_files:
        if not path.exists():
            if path.parent.name == 'tests':
                raise ValueError('Missing portable test file: ' + path.name)
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError('Linked files cannot enter the portable checkout.')
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    subprocess.run(['git', 'init', '--quiet', str(target)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(target), 'add', '--all'], check=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.isolated_child:
        return run_suite()
    env = dict(os.environ)
    for name in list(env):
        if name in ('OPENAI_API_KEY', 'PYTHONPATH', 'PYTHONHOME') or name.startswith(('GMAIL_', 'GOOGLE_', 'HONORARIOS_')) and name != 'HONORARIOS_UV_EXECUTABLE':
            env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix='honorarios-portable-tests-') as temporary:
        target = Path(temporary) / 'source'
        copy_portable_checkout(ROOT, target)
        result = subprocess.run([sys.executable, str(target / 'scripts/run_portable_tests.py'), '--isolated-child'], cwd=target, env=env)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
