import subprocess
import tempfile
from pathlib import Path


from scripts.build_public_candidate import build_public_candidate
from scripts.public_repo_gate import analyze_tracked


from test_public_candidate_smoke import PublicCandidateSmokeTests


class PublicPublicationTests(PublicCandidateSmokeTests):
    def test_candidate_privacy_gate_passes(self):
        report = analyze_tracked(Path(__file__).resolve().parents[1])
        self.assertTrue(report["public_repo_ready"], report)


    def test_public_candidate_builder_refreshes_preserved_git_index(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "candidate"
            target.mkdir()
            subprocess.run(["git", "init"], cwd=target, capture_output=True, text=True, check=True)
            (target / "data").mkdir()
            (target / "data" / "service-profiles.json").write_text("{}", encoding="utf-8")
            subprocess.run(
                ["git", "add", "data/service-profiles.json"],
                cwd=target,
                capture_output=True,
                text=True,
                check=True,
            )

            before = subprocess.run(
                ["git", "ls-files"],
                cwd=target,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn("data/service-profiles.json", before)

            result = build_public_candidate(root, target)

            after = subprocess.run(
                ["git", "ls-files"],
                cwd=target,
                capture_output=True,
                text=True,
                check=True,
            ).stdout

        self.assertEqual(result["status"], "created", result)
        self.assertTrue(result["gate"]["public_ready"], result)
        self.assertIn("tracked_gate", result)
        self.assertTrue(result["tracked_gate"]["public_repo_ready"], result["tracked_gate"])
        self.assertNotIn("data/service-profiles.json", after)
        self.assertIn("data/service-profiles.example.json", after)

