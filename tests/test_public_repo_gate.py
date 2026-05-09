import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_public_candidate import build_public_candidate
from scripts.create_intake import load_profiles
from scripts.generate_pdf import load_json, resolve_json_path
from scripts.public_release_gate import analyze_public_readiness
from scripts.public_repo_gate import CandidateFile, analyze_candidates


ROOT = Path(__file__).resolve().parents[1]


class PublicRepoGateTests(unittest.TestCase):
    def write_public_metadata(self, root: Path) -> None:
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / "README.md").write_text("Synthetic public candidate.", encoding="utf-8")
        (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (root / "SECURITY.md").write_text("Report security issues privately.", encoding="utf-8")
        (root / "CONTRIBUTING.md").write_text("Use synthetic fixtures only.", encoding="utf-8")
        (root / ".github" / "workflows" / "python-package.yml").write_text("name: test\n", encoding="utf-8")

    def test_blocks_local_runtime_paths(self):
        report = analyze_candidates([
            CandidateFile("config/gmail.local.json", b"{}"),
            CandidateFile("output/email-drafts/example.draft.json", b"{}"),
            CandidateFile("data/service-profiles.json", b"{}"),
        ])

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(len(report["path_blockers"]), 3)

    def test_blocks_sensitive_content(self):
        access_token = ("ya29." + "privateAccessTokenValue").encode("utf-8")
        court_email = ("beja.ministeriopublico@" + "tribunais.org.pt").encode("utf-8")

        report = analyze_candidates([
            CandidateFile("README.md", b"token=" + access_token + b"\n"),
            CandidateFile("docs/example.md", b"recipient=" + court_email + b"\n"),
        ])

        self.assertEqual(report["status"], "blocked")
        kinds = {finding["kind"] for finding in report["content_findings"]}
        self.assertIn("google_access_token", kinds)
        self.assertIn("real_court_email", kinds)

    def test_allows_synthetic_public_fixtures(self):
        report = analyze_candidates([
            CandidateFile("config/gmail.example.json", b'{"client_secret": "example-client-secret"}'),
            CandidateFile("data/court-emails.example.json", b'{"email": "court@example.test"}'),
        ])

        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["path_blockers"])
        self.assertFalse(report["content_findings"])

    def test_public_release_gate_blocks_real_reference_overlay_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_public_metadata(root)
            data_dir = root / "data"
            data_dir.mkdir()
            for relative in [
                "data/court-emails.json",
                "data/known-destinations.json",
                "data/service-profiles.json",
            ]:
                (root / relative).write_text("{}", encoding="utf-8")

            report = analyze_public_readiness(root, require_git=False)

        self.assertFalse(report["public_ready"])
        for relative in [
            "data/court-emails.json",
            "data/known-destinations.json",
            "data/service-profiles.json",
        ]:
            with self.subTest(relative=relative):
                self.assertIn(relative, report["blocked_paths"])

    def test_public_candidate_writes_reference_examples_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "candidate"

            result = build_public_candidate(ROOT, target)

            self.assertTrue(result["gate"]["public_ready"], result["gate"])
            for name in [
                "court-emails",
                "known-destinations",
                "service-profiles",
            ]:
                with self.subTest(name=name):
                    self.assertTrue((target / "data" / f"{name}.example.json").exists())
                    self.assertFalse((target / "data" / f"{name}.json").exists())

    def test_default_json_reads_fall_back_to_example_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_path = root / "config" / "profile.json"
            profile_example_path = root / "config" / "profile.example.json"
            profiles_path = root / "data" / "service-profiles.json"
            profiles_example_path = root / "data" / "service-profiles.example.json"
            profile_example_path.parent.mkdir(parents=True)
            profiles_example_path.parent.mkdir(parents=True)
            profile_example_path.write_text(json.dumps({"applicant_name": "Example Applicant"}), encoding="utf-8")
            profiles_example_path.write_text(json.dumps({"example": {"payment_entity": "Example Court"}}), encoding="utf-8")

            self.assertEqual(resolve_json_path(profile_path), profile_example_path)
            self.assertEqual(load_json(profile_path)["applicant_name"], "Example Applicant")
            self.assertEqual(load_profiles(profiles_path)["example"]["payment_entity"], "Example Court")


if __name__ == "__main__":
    unittest.main()
