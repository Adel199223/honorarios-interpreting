import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from honorarios_app.web import create_app
from scripts.public_release_gate import analyze_public_readiness


class PublicCandidateSmokeTests(unittest.TestCase):
    def test_homepage_loads(self):
        client = TestClient(create_app())
        response = client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('LegalPDF Honorários', response.text)

    def test_candidate_privacy_gate_passes(self):
        report = analyze_public_readiness(Path(__file__).resolve().parents[1], require_git=False)
        self.assertTrue(report['public_ready'], report)


if __name__ == '__main__':
    unittest.main()
