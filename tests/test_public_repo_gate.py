import json
import tempfile
import unittest
from pathlib import Path

from scripts.create_intake import load_profiles
from scripts.generate_pdf import load_json, resolve_json_path
from scripts.public_repo_gate import CandidateFile, analyze_candidates


class PublicRepoGateTests(unittest.TestCase):
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
