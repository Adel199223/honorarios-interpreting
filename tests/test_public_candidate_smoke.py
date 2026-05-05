import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from honorarios_app.web import create_app
from scripts.local_app_smoke import run_smoke
from scripts.public_release_gate import analyze_public_readiness


class PublicCandidateSmokeTests(unittest.TestCase):
    def make_client(self):
        return TestClient(create_app())

    def test_homepage_exposes_browser_flow_landmarks(self):
        client = self.make_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.text
        for text in [
            "LegalPDF Honorários",
            "Start Interpretation Request",
            "Review Interpretation Request",
            "Google Photos selected-photo import",
            "Open Google Photos Picker",
            "Batch Queue",
            "Packet mode",
            "Packet item inspector",
            "Packet draft recording helper",
            "LegalPDF Integration Preview",
            "Build integration checklist",
            "Build adapter import plan",
            "LegalPDF Apply History",
            "LegalPDF Restore Plan",
            "Refresh apply history",
            "Draft-only Gmail",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, page)
        self.assertNotIn("_send_email", page)
        self.assertNotIn("_send_draft", page)

    def test_reference_endpoint_keeps_draft_only_contract(self):
        client = self.make_client()
        response = client.get("/api/reference")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["gmail"]["tool"], "_create_draft")
        self.assertFalse(data["gmail"]["send_allowed"])
        self.assertIn("example_interpreting", data["service_profiles"])

    def test_google_photos_status_is_secret_free(self):
        client = self.make_client()
        response = client.get("/api/google-photos/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["send_allowed"])
        self.assertTrue(data["manual_import_ready"])
        for raw_secret_key in [
            "client_secret",
            "access_token",
            "refresh_token",
            "media_base_url",
            "photo_url",
            "selected_media_id",
        ]:
            self.assertNotIn(raw_secret_key, data)
        dumped = json.dumps(data, sort_keys=True).lower()
        self.assertNotIn("gho_", dumped)
        self.assertNotIn("sk-", dumped)

    def test_legalpdf_integration_preview_report_and_checklist_are_read_only(self):
        root = Path(__file__).resolve().parents[1]
        profiles_path = root / "data" / "service-profiles.json"
        court_path = root / "data" / "court-emails.json"
        profiles_before = profiles_path.read_text(encoding="utf-8")
        courts_before = court_path.read_text(encoding="utf-8")
        client = self.make_client()
        backup = {
            "kind": "honorarios_local_backup",
            "schema_version": 1,
            "datasets": {
                "service_profiles": {
                    "legalpdf_synthetic": {
                        "description": "Synthetic LegalPDF profile.",
                        "defaults": {"payment_entity": "Example Court", "service_place": "Example Police Station"},
                    },
                    "new_public_profile": {
                        "description": "New synthetic profile.",
                        "defaults": {"payment_entity": "Example Court"},
                    },
                },
                "court_emails": [
                    {
                        "key": "example-court",
                        "name": "Example Court",
                        "email": "court-updated@example.test",
                        "payment_entity_aliases": ["Example Court"],
                        "source": "synthetic",
                    }
                ],
            },
        }
        payload = {
            "backup": backup,
            "profile_mapping_text": "legalpdf_synthetic = example_interpreting",
        }
        preview = client.post("/api/integration/import-preview", json=payload)
        report = client.post("/api/integration/import-report", json=payload)
        checklist = client.post("/api/integration/checklist", json=payload)
        plan = client.post("/api/integration/import-plan", json=payload)
        history = client.get("/api/integration/apply-history")
        for response in [preview, report, checklist, plan, history]:
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertFalse(data["send_allowed"])
        self.assertFalse(preview.json()["write_allowed"])
        self.assertFalse(report.json()["reference_write_allowed"])
        self.assertFalse(checklist.json()["write_allowed"])
        self.assertFalse(checklist.json()["managed_data_changed"])
        self.assertFalse(plan.json()["write_allowed"])
        self.assertFalse(plan.json()["managed_data_changed"])
        self.assertTrue(plan.json()["apply_endpoint_available"])
        self.assertFalse(history.json()["write_allowed"])
        self.assertFalse(history.json()["managed_data_changed"])
        self.assertEqual(history.json()["report_count"], 0)
        blocked_detail = client.get("/api/integration/apply-detail", params={"report_id": "../private"})
        self.assertEqual(blocked_detail.status_code, 400)
        self.assertFalse(blocked_detail.json()["send_allowed"])
        self.assertFalse(blocked_detail.json()["write_allowed"])
        self.assertFalse(blocked_detail.json()["managed_data_changed"])
        blocked_restore = client.get("/api/integration/apply-restore-plan", params={"report_id": "../private"})
        self.assertEqual(blocked_restore.status_code, 400)
        self.assertFalse(blocked_restore.json()["send_allowed"])
        self.assertFalse(blocked_restore.json()["write_allowed"])
        self.assertFalse(blocked_restore.json()["managed_data_changed"])
        self.assertFalse(blocked_restore.json()["restore_allowed"])
        blocked_restore_apply = client.post("/api/integration/apply-restore", json={"report_id": "../private"})
        self.assertEqual(blocked_restore_apply.status_code, 400)
        self.assertFalse(blocked_restore_apply.json()["send_allowed"])
        self.assertFalse(blocked_restore_apply.json()["write_allowed"])
        self.assertFalse(blocked_restore_apply.json()["managed_data_changed"])
        self.assertFalse(blocked_restore_apply.json()["restore_allowed"])
        blocked_apply = client.post("/api/integration/apply-import-plan", json=payload)
        self.assertEqual(blocked_apply.status_code, 400)
        self.assertFalse(blocked_apply.json()["send_allowed"])
        self.assertFalse(blocked_apply.json()["managed_data_changed"])
        self.assertIn("Integration Checklist", checklist.json()["checklist_markdown"])
        self.assertIn("legalpdf_synthetic -> example_interpreting", checklist.json()["checklist_markdown"])
        self.assertIn("Adapter Import Plan", plan.json()["plan_markdown"])
        self.assertEqual(profiles_path.read_text(encoding="utf-8"), profiles_before)
        self.assertEqual(court_path.read_text(encoding="utf-8"), courts_before)

    def test_local_app_smoke_runner_can_check_public_candidate_contract(self):
        client = self.make_client()

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
        )
        self.assertEqual(report["status"], "ready", report)
        self.assertFalse(report["send_allowed"])

    def test_local_app_smoke_runner_optional_interaction_contract_is_injectable(self):
        client = self.make_client()

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def post_json(url, payload):
            if url.endswith("/api/intake/from-profile"):
                intake = {
                    "case_number": payload["case_number"],
                    "service_date": payload["service_date"],
                    "recipient_email": "court@example.test",
                    "payment_entity": "Example Court",
                    "service_place": "Example Police Station",
                }
                return {
                    "status": "created",
                    "intake": intake,
                    "review": {
                        "status": "ready",
                        "draft_text": "Número de processo: 999/26.0SMOKE\n\nPede deferimento,",
                        "send_allowed": False,
                    },
                    "send_allowed": False,
                }
            if url.endswith("/api/drafts/active-check"):
                return {"status": "clear", "send_allowed": False}
            if url.endswith("/api/prepare/preflight"):
                return {
                    "status": "ready",
                    "artifact_effect": "none",
                    "write_allowed": False,
                    "send_allowed": False,
                    "packet_mode": True,
                    "items": [{
                        "status": "ready",
                        "case_number": "999/26.0SMOKE",
                        "service_date": "2026-05-04",
                        "recipient": "court@example.test",
                        "send_allowed": False,
                        "write_allowed": False,
                    }],
                }
            if url.endswith("/api/prepare"):
                return {
                    "status": "prepared",
                    "packet_mode": True,
                    "send_allowed": False,
                    "items": [{
                        "case_number": "999/26.0SMOKE",
                        "service_date": "2026-05-04",
                        "send_allowed": False,
                        "gmail_create_draft_ready": True,
                        "gmail_create_draft_args": {"attachment_files": ["/tmp/synthetic.pdf"]},
                    }],
                    "packet": {
                        "send_allowed": False,
                        "gmail_create_draft_ready": True,
                        "gmail_create_draft_args": {"attachment_files": ["/tmp/synthetic-packet.pdf"]},
                        "underlying_requests": [{"case_number": "999/26.0SMOKE", "service_date": "2026-05-04"}],
                    },
                }
            raise AssertionError(url)

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            post_json=post_json,
            interaction_checks=True,
        )
        self.assertEqual(report["status"], "ready", report)
        self.assertIn("workflow_batch_preflight", {check["name"] for check in report["checks"]})
        self.assertIn("workflow_prepare_packet_payload", {check["name"] for check in report["checks"]})

    def test_local_app_smoke_runner_browser_click_through_contract_is_injectable(self):
        client = self.make_client()
        seen_kwargs = {}

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def browser_runner(_base_url, **kwargs):
            seen_kwargs.update(kwargs)
            return {
                "status": "ready",
                "checks": [
                    {"name": "browser_review_drawer", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_answer_questions", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_photo_upload_evidence", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_pdf_upload_evidence", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_correction_mode", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_replacement_prepare", "status": "ready", "message": "ok", "details": {}},
                ],
                "failure_count": 0,
                "send_allowed": False,
            }

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            browser_click_through=True,
            browser_answer_questions=True,
            browser_upload_photo=True,
            browser_upload_pdf=True,
            browser_correction_mode=True,
            browser_prepare_replacement=True,
            browser_apply_history=True,
            browser_runner=browser_runner,
        )
        self.assertEqual(report["status"], "ready", report)
        self.assertIn("browser_review_drawer", {check["name"] for check in report["checks"]})
        self.assertIn("browser_answer_questions", {check["name"] for check in report["checks"]})
        self.assertIn("browser_photo_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_pdf_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_correction_mode", {check["name"] for check in report["checks"]})
        self.assertIn("browser_replacement_prepare", {check["name"] for check in report["checks"]})
        self.assertTrue(seen_kwargs["answer_questions"])
        self.assertTrue(seen_kwargs["upload_photo"])
        self.assertTrue(seen_kwargs["upload_pdf"])
        self.assertTrue(seen_kwargs["correction_mode"])
        self.assertTrue(seen_kwargs["prepare_replacement"])
        self.assertTrue(seen_kwargs["apply_history"])

    def test_candidate_privacy_gate_passes(self):
        report = analyze_public_readiness(Path(__file__).resolve().parents[1], require_git=False)
        self.assertTrue(report["public_ready"], report)


if __name__ == "__main__":
    unittest.main()
