"""Run explicitly public synthetic tests in an isolated source-only checkout."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUP_NAMES = ('quick', 'intake', 'quality', 'pdf', 'email', 'ui', 'package', 'integration', 'full')
# This code allowlist is independent of editable manifests. Never import arbitrary
# test names from a caller or copy ignored/private regression files.
PUBLIC_TEST_FILES = frozenset({
    'test_browser_iab_smoke.py', 'test_public_candidate_smoke.py',
    'test_public_runtime.py', 'test_public_ui.py', 'test_public_email.py',
    'test_public_adapter.py', 'test_public_publication.py',
    'test_public_repo_gate.py', 'test_dev_environment.py',
    'test_installed_wheel.py', 'test_prepared_candidate.py',
    'test_intake_rules.py', 'test_pdf_rules.py', 'test_email_rules.py',
    'test_portable_groups.py',
    'test_source_evidence.py', 'test_service_profile_selection.py', 'test_review_guidance.py',
    'test_source_decisions.py', 'test_public_ai_recovery.py',
    'test_photo_defaults.py', 'test_multi_case_sources.py', 'test_claim_options.py', 'test_claim_options_ui.py', 'test_email_routing.py', 'test_email_routing_ui.py',
    'test_source_email_groups.py',
})
PUBLIC_EVALUATION_FILES = frozenset({'examples/source-quality-cases.json'})


def load_selection(root: Path, group: str = 'full') -> tuple[list[str], list[str]]:
    """Validate every group before copying anything, including unselected groups."""
    if group not in GROUP_NAMES:
        raise ValueError('Unknown portable test group: ' + group)
    for relative in PUBLIC_EVALUATION_FILES:
        path = root / relative
        if not path.is_file():
            raise ValueError('Missing public evaluation fixture: ' + relative)
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Linked fixtures cannot enter the public suite.')
    tests_root = root / 'tests'
    if tests_root.is_symlink() or not tests_root.resolve().is_relative_to(root.resolve()):
        raise ValueError('Linked test directories cannot enter the public suite.')
    manifest = tests_root / 'portable-suite.txt'
    groups_file = tests_root / 'portable-groups.json'
    for path in (manifest, groups_file):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Linked manifests cannot enter the public suite.')
    names = manifest.read_text(encoding='utf-8').splitlines()
    if not names or len(set(names)) != len(names):
        raise ValueError('Public portable test manifest must be nonempty and unique.')
    for name in names:
        path = tests_root / name
        if name not in PUBLIC_TEST_FILES or not path.is_file():
            raise ValueError('Unsupported or missing public portable test file: ' + name)
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Linked test files cannot enter the public suite.')
    if set(names) != PUBLIC_TEST_FILES:
        raise ValueError('Portable manifest must contain the complete public code allowlist.')
    groups = json.loads(groups_file.read_text(encoding='utf-8'))
    if not isinstance(groups, dict) or set(groups) != set(GROUP_NAMES):
        raise ValueError('Portable group map must declare exactly the supported groups.')
    for group_name, members in groups.items():
        if not isinstance(members, list) or not members or any(not isinstance(name, str) for name in members):
            raise ValueError('Portable groups must contain nonempty file lists: ' + group_name)
        if len(set(members)) != len(members) or any(name not in names for name in members):
            raise ValueError('Portable group contains duplicate or unlisted files: ' + group_name)
    if groups['full'] != names:
        raise ValueError('The full group must match the complete portable manifest in order.')
    covered = {name for key, members in groups.items() if key != 'full' for name in members}
    # The test-free fixture base is an import dependency, copied for every group.
    if covered != set(names) - {'test_public_candidate_smoke.py'}:
        raise ValueError('Every runnable public file needs a focused group.')
    return names, groups[group]


def run_suite(group: str = 'full') -> int:
    _, names = load_selection(ROOT, group)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'tests'))
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name[:-3]))
    print(f'Portable test group: {group} ({suite.countTestCases()} tests)', flush=True)
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


def copy_portable_checkout(source: Path, target: Path) -> None:
    """Copy source/assets and explicitly public fixtures, never private runtime overlays."""
    names, _ = load_selection(source)
    source_files = [source / name for name in (
        '.gitignore', '.python-version', '.node-version', 'pyproject.toml', 'uv.lock',
        'requirements.txt', 'README.md', 'CONTRIBUTING.md', 'LICENSE', 'SECURITY.md',
        'agent.md', 'APP_KNOWLEDGE.md', '.githooks/pre-commit',
        'config/email.example.json', 'config/profile.example.json', 'config/profiles.example.json',
        'config/gmail.example.json', 'config/google-photos.example.json',
        'data/court-emails.example.json', 'data/known-destinations.example.json',
        'data/service-profiles.example.json', 'examples/intake.synthetic.example.json',
        'tests/portable-suite.txt', 'tests/portable-groups.json',
    )]
    extensions = {'.py','.ps1','.mjs','.js','.css','.html','.md','.json','.yml','.yaml'}
    for directory in ('honorarios_app', 'scripts', 'templates', 'docs', '.github', '.circleci'):
        source_files += [p for p in (source / directory).rglob('*') if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts]
    source_files += [source / 'tests' / name for name in names]
    source_files += [source / relative for relative in PUBLIC_EVALUATION_FILES]
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


def isolated_environment(environ: dict[str, str]) -> dict[str, str]:
    env = dict(environ)
    for name in list(env):
        upper = name.upper()
        if upper in ('OPENAI_API_KEY', 'PYTHONPATH', 'PYTHONHOME') or (
            upper.startswith(('GMAIL_', 'GOOGLE_', 'HONORARIOS_')) and upper != 'HONORARIOS_UV_EXECUTABLE'
        ):
            env.pop(name, None)
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--group', choices=GROUP_NAMES, default='full')
    args = parser.parse_args(argv)
    if args.isolated_child:
        return run_suite(args.group)
    load_selection(ROOT, args.group)
    with tempfile.TemporaryDirectory(prefix='honorarios-portable-tests-') as temporary:
        target = Path(temporary) / 'source'
        copy_portable_checkout(ROOT, target)
        result = subprocess.run(
            [sys.executable, str(target / 'scripts/run_portable_tests.py'), '--isolated-child', '--group', args.group],
            cwd=target, env=isolated_environment(dict(os.environ)),
        )
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
