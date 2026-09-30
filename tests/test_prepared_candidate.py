from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.build_public_candidate import COPY_DIRS, COPY_FILES, PUBLIC_PORTABLE_TESTS, build_public_candidate


ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXTENSIONS = {".py", ".ps1", ".mjs", ".js", ".html", ".css", ".md", ".json", ".txt", ".toml", ".yml", ".yaml"}


class PreparedCandidateTests(unittest.TestCase):
    def make_source_fixture(self, root: Path) -> Path:
        # The fixture contains allowlisted public source, never local config/data/output.
        source = Path(os.environ.get("HONORARIOS_PREPARATION_SOURCE", ROOT)).resolve()
        fixture = root / "source"
        fixture.mkdir()
        for relative in COPY_FILES:
            if (source / relative).is_file():
                shutil.copy2(source / relative, fixture / relative)
        for directory in COPY_DIRS:
            source_directory = source / directory
            if not source_directory.is_dir():
                continue
            for path in source_directory.rglob("*"):
                if not path.is_file() or path.suffix not in SOURCE_EXTENSIONS or "__pycache__" in path.parts:
                    continue
                target = fixture / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        names = (source / "tests" / "portable-suite.txt").read_text(encoding="utf-8").splitlines()
        tests = fixture / "tests"
        tests.mkdir()
        for name in names:
            self.assertIn(name, PUBLIC_PORTABLE_TESTS)
            shutil.copy2(source / "tests" / name, tests / name)
        # Exercise export of this regression too, without running the exported suite.
        self_name = "test_prepared_candidate.py"
        shutil.copy2(Path(__file__), tests / self_name)
        if self_name not in names:
            names.append(self_name)
        (tests / "portable-suite.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
        shutil.copy2(source / "tests" / "portable-groups.json", tests / "portable-groups.json")
        (tests / "test_unlisted_local.py").write_text('raise AssertionError("Unlisted local tests must never be copied or run.")\n', encoding="utf-8")
        return fixture

    def test_exported_candidate_keeps_environment_docs_and_public_test_manifest(self):
        with tempfile.TemporaryDirectory(prefix="honorarios-prepared-candidate-") as temporary:
            root = Path(temporary)
            source = self.make_source_fixture(root)
            candidate = root / "candidate"
            result = build_public_candidate(source, candidate)
            self.assertEqual(result["status"], "created", result["gate"])
            for name in (".python-version", ".node-version", "uv.lock", "agent.md", "APP_KNOWLEDGE.md"):
                with self.subTest(file=name):
                    self.assertTrue((candidate / name).is_file())
            for name in (".python-version", ".node-version", "uv.lock"):
                self.assertEqual((source / name).read_text(encoding="utf-8"), (candidate / name).read_text(encoding="utf-8"))
            manifest = candidate / "tests" / "portable-suite.txt"
            self.assertEqual(manifest.read_bytes(), (source / "tests" / "portable-suite.txt").read_bytes())
            self.assertEqual((candidate / "tests" / "portable-groups.json").read_bytes(), (source / "tests" / "portable-groups.json").read_bytes())
            names = manifest.read_text(encoding="utf-8").splitlines()
            self.assertIn("test_dev_environment.py", names)
            self.assertIn("test_installed_wheel.py", names)
            self.assertIn("test_prepared_candidate.py", names)
            self.assertTrue(all((candidate / "tests" / name).is_file() for name in names))
            self.assertFalse((candidate / "tests" / "test_unlisted_local.py").exists())
            completed = subprocess.run([sys.executable, "scripts/check_project_docs.py"], cwd=candidate, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_invalid_portable_manifest_is_rejected_before_target_reset(self):
        with tempfile.TemporaryDirectory(prefix="honorarios-candidate-manifest-") as temporary:
            root = Path(temporary)
            source = self.make_source_fixture(root)
            manifest = source / "tests" / "portable-suite.txt"
            target = root / "candidate"
            target.mkdir()
            marker = target / "preserve-me.txt"
            marker.write_text("Existing target remains untouched.\n", encoding="utf-8")
            for name in ("test_unlisted_local.py", "../test_private.py", "test_missing.py"):
                with self.subTest(name=name):
                    manifest.write_text(name + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Unsupported or missing public portable"):
                        build_public_candidate(source, target)
                    self.assertTrue(marker.is_file())

    def test_invalid_group_map_is_rejected_before_target_reset(self):
        with tempfile.TemporaryDirectory(prefix="honorarios-candidate-groups-") as temporary:
            root = Path(temporary)
            source = self.make_source_fixture(root)
            target = root / "candidate"
            target.mkdir()
            marker = target / "preserve-me.txt"
            marker.write_text("Existing target remains untouched.\n", encoding="utf-8")
            map_path = source / "tests" / "portable-groups.json"
            groups = json.loads(map_path.read_text(encoding="utf-8"))
            groups["email"] = ["test_unlisted_local.py"]
            map_path.write_text(json.dumps(groups), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unlisted files"):
                build_public_candidate(source, target)
            self.assertTrue(marker.is_file())


if __name__ == "__main__":
    unittest.main()
