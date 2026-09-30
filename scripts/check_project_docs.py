"""Check the small documentation routing map and its local links without reading private data."""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = json.loads((ROOT / 'docs/assistant/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported documentation manifest schema.')
    keys = (
        'runbook', 'app_knowledge', 'handoff', 'development_environment',
        'validation', 'integration_readiness', 'adapter_contract',
        'plan_lifecycle', 'workflow_acceptance', 'user_guide', 'current_plan',
    )
    paths = [ROOT / manifest[key] for key in keys] + [ROOT / 'README.md', ROOT / 'CONTRIBUTING.md']
    paths += [ROOT / name for name in manifest.get('historical_references', [])]
    errors = []
    for path in paths:
        if not path.resolve().is_relative_to(ROOT.resolve()) or not path.is_file():
            errors.append('Missing or unsafe documentation path.')
            continue
        for link in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            target = unquote(link.split('#', 1)[0].strip('<>'))
            if not target or re.match(r'[a-zA-Z]+:', target):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(ROOT.resolve()) or not resolved.exists():
                errors.append(f'{path.relative_to(ROOT).as_posix()}: broken local link {target}')
    for error in errors:
        print(error)
    print(f'Documentation routing: {"blocked" if errors else "ready"} ({len(paths)} documents)')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
