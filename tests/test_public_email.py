import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from honorarios_app.web import create_app
from scripts.local_app_smoke import run_smoke


from test_public_candidate_smoke import PublicCandidateSmokeTests


class PublicEmailTests(PublicCandidateSmokeTests):
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


    def test_gmail_status_is_secret_free_and_draft_only(self):
        client = self.make_client()
        response = client.get("/api/gmail/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["gmail_api_action"], "users.drafts.create")
        self.assertTrue(data["draft_only"])
        self.assertFalse(data["send_allowed"])
        for raw_secret_key in [
            "client_secret",
            "access_token",
            "refresh_token",
            "authorization",
            "token",
        ]:
            self.assertNotIn(raw_secret_key, data)


    def test_recent_work_missing_draft_reconciliation_stays_local_only(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        response = self.make_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("data-history-status-filter=\"not_found\"", response.text)
        self.assertIn("async function verifyHistoryDraft", app_js)
        self.assertIn("async function markHistoryDraftNotFound", app_js)
        self.assertIn("lastHistoryDraftVerification", app_js)
        self.assertIn("data-history-mark-not-found", app_js)
        self.assertIn("Verify this draft as not_found before marking it locally.", app_js)
        self.assertIn("Marked not_found from Recent Work after Gmail draft verification returned not_found.", app_js)
        self.assertIn("Local bookkeeping only. Gmail was not contacted and no email was sent.", app_js)
        self.assertIn('status: "not_found"', app_js)
        self.assertIn('"/api/gmail/drafts/verify"', app_js)
        self.assertIn('"/api/gmail/drafts/reconcile-not-found"', app_js)
        self.assertIn('"/api/drafts/status"', app_js)
        self.assertIn("confirm_not_found", app_js)
        self.assertIn("reconciliation_reason", app_js)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)
        self.assertNotIn("messages.send", app_js)
        self.assertNotIn("drafts.send", app_js)


    def test_fake_gmail_not_found_reconciliation_records_only_local_status(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        root = Path(runtime.name)
        project_root = Path(__file__).resolve().parents[1]
        duplicate_index = root / "duplicate-index.json"
        draft_log = root / "gmail-draft-log.json"
        profile_change_log = root / "profile-change-log.json"
        pdf = root / "request.pdf"
        duplicate_index.write_text("[]", encoding="utf-8")
        draft_log.write_text("[]", encoding="utf-8")
        profile_change_log.write_text("[]", encoding="utf-8")
        pdf.write_bytes(b"%PDF-1.4\nmissing")
        previous = os.environ.get("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE")
        os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = "1"
        try:
            client = TestClient(base_url='http://127.0.0.1', app=create_app(
                profile=project_root / "config" / "profile.example.json",
                personal_profiles=project_root / "config" / "profiles.example.json",
                email_config=project_root / "config" / "email.example.json",
                service_profiles=project_root / "data" / "service-profiles.example.json",
                court_emails=project_root / "data" / "court-emails.example.json",
                known_destinations=project_root / "data" / "known-destinations.example.json",
                duplicate_index=duplicate_index,
                draft_log=draft_log,
                profile_change_log=profile_change_log,
                output_dir=root / "pdf",
                html_dir=root / "html",
                draft_output_dir=root / "email-drafts",
                manifest_dir=root / "manifests",
                render_dir=root / "previews",
                intake_output_dir=root / "intakes",
                source_upload_dir=root / "source-uploads",
                packet_output_dir=root / "packets",
                backup_output_dir=root / "backups",
                integration_report_output_dir=root / "integration-reports",
                gmail_config=root / "gmail.local.json",
            ))
            response = client.post("/api/gmail/drafts/reconcile-not-found", json={
                "confirm_not_found": True,
                "reconciliation_reason": "Synthetic missing draft reconciliation.",
                "case_number": "999/26.0TEST",
                "service_date": "2026-05-06",
                "recipient": "court@example.test",
                "pdf": str(pdf),
                "draft_id": "draft-missing",
                "message_id": "message-missing",
                "thread_id": "thread-missing",
            })
        finally:
            if previous is None:
                os.environ.pop("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE", None)
            else:
                os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = previous

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["status"], "recorded")
        self.assertEqual(data["lifecycle_status"], "not_found")
        self.assertEqual(data["verification"]["status"], "not_found")
        self.assertEqual(data["gmail_api_action"], "users.drafts.get")
        self.assertTrue(data["local_records_changed"])
        self.assertFalse(data["send_allowed"])
        self.assertEqual(json.loads(draft_log.read_text(encoding="utf-8"))[0]["status"], "not_found")
        self.assertEqual(json.loads(duplicate_index.read_text(encoding="utf-8"))[0]["status"], "not_found")


    def test_fake_gmail_mismatch_verification_is_read_only(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        root = Path(runtime.name)
        project_root = Path(__file__).resolve().parents[1]
        duplicate_index = root / "duplicate-index.json"
        draft_log = root / "gmail-draft-log.json"
        profile_change_log = root / "profile-change-log.json"
        duplicate_index.write_text("[]", encoding="utf-8")
        draft_log.write_text("[]", encoding="utf-8")
        profile_change_log.write_text("[]", encoding="utf-8")
        previous = os.environ.get("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE")
        os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = "1"
        try:
            client = TestClient(base_url='http://127.0.0.1', app=create_app(
                profile=project_root / "config" / "profile.example.json",
                personal_profiles=project_root / "config" / "profiles.example.json",
                email_config=project_root / "config" / "email.example.json",
                service_profiles=project_root / "data" / "service-profiles.example.json",
                court_emails=project_root / "data" / "court-emails.example.json",
                known_destinations=project_root / "data" / "known-destinations.example.json",
                duplicate_index=duplicate_index,
                draft_log=draft_log,
                profile_change_log=profile_change_log,
                output_dir=root / "pdf",
                html_dir=root / "html",
                draft_output_dir=root / "email-drafts",
                manifest_dir=root / "manifests",
                render_dir=root / "previews",
                intake_output_dir=root / "intakes",
                source_upload_dir=root / "source-uploads",
                packet_output_dir=root / "packets",
                backup_output_dir=root / "backups",
                integration_report_output_dir=root / "integration-reports",
                gmail_config=root / "gmail.local.json",
            ))
            response = client.post("/api/gmail/drafts/verify", json={
                "draft_id": "draft-mismatch-smoke",
                "message_id": "local-message-smoke",
                "thread_id": "local-thread-smoke",
            })
        finally:
            if previous is None:
                os.environ.pop("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE", None)
            else:
                os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = previous

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["status"], "reconciliation_mismatch")
        self.assertEqual(data["gmail_api_action"], "users.drafts.get")
        self.assertTrue(data["read_only"])
        self.assertFalse(data["send_allowed"])
        self.assertFalse(data["write_allowed"])
        self.assertFalse(data["managed_data_changed"])
        self.assertFalse(data["local_records_changed"])
        self.assertFalse(data["message_id_matches"])
        self.assertFalse(data["thread_id_matches"])
        self.assertEqual(json.loads(draft_log.read_text(encoding="utf-8")), [])
        self.assertEqual(json.loads(duplicate_index.read_text(encoding="utf-8")), [])


    def test_fake_gmail_draft_create_records_synthetic_duplicate_only(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        root = Path(runtime.name)
        project_root = Path(__file__).resolve().parents[1]
        duplicate_index = root / "duplicate-index.json"
        draft_log = root / "gmail-draft-log.json"
        profile_change_log = root / "profile-change-log.json"
        duplicate_index.write_text("[]", encoding="utf-8")
        draft_log.write_text("[]", encoding="utf-8")
        profile_change_log.write_text("[]", encoding="utf-8")
        intake = json.loads((project_root / "examples" / "intake.synthetic.example.json").read_text(encoding="utf-8"))
        intake.pop("recipient_email", None)
        previous = os.environ.get("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE")
        os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = "1"
        try:
            client = TestClient(base_url='http://127.0.0.1', app=create_app(
                profile=project_root / "config" / "profile.example.json",
                personal_profiles=project_root / "config" / "profiles.example.json",
                email_config=project_root / "config" / "email.example.json",
                service_profiles=project_root / "data" / "service-profiles.example.json",
                court_emails=project_root / "data" / "court-emails.example.json",
                known_destinations=project_root / "data" / "known-destinations.example.json",
                duplicate_index=duplicate_index,
                draft_log=draft_log,
                profile_change_log=profile_change_log,
                output_dir=root / "pdf",
                html_dir=root / "html",
                draft_output_dir=root / "email-drafts",
                manifest_dir=root / "manifests",
                render_dir=root / "previews",
                intake_output_dir=root / "intakes",
                source_upload_dir=root / "source-uploads",
                packet_output_dir=root / "packets",
                backup_output_dir=root / "backups",
                integration_report_output_dir=root / "integration-reports",
                gmail_config=root / "gmail.local.json",
            ))
            prepared = self.preflight_prepare(client, {
                "intakes": [intake],
                "render_previews": False,
            })
            self.assertEqual(prepared.status_code, 200, prepared.text)
            prepared_data = prepared.json()
            item = prepared_data["items"][0]
            review = prepared_data["prepared_review"]
            response = client.post("/api/gmail/drafts/create", json={
                "payload": item["draft_payload"],
                "gmail_handoff_reviewed": True,
                "prepared_manifest": review["manifest"],
                "prepared_review_token": review["prepared_review_token"],
                "review_fingerprint": review["review_fingerprint"],
            })
        finally:
            if previous is None:
                os.environ.pop("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE", None)
            else:
                os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = previous
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["confirmation"]["fake_mode"])
        self.assertEqual(data["confirmation"]["recorded_duplicate_count"], 1)
        self.assertEqual(json.loads(duplicate_index.read_text(encoding="utf-8"))[0]["status"], "drafted")


    def test_local_app_smoke_gmail_api_checks_require_draft_only_status_before_posts(self):
        client = self.make_client()
        seen_post_urls = []

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            if path == "/api/gmail/status":
                return {
                    "provider": "gmail_api",
                    "configured": True,
                    "connected": True,
                    "draft_create_ready": True,
                    "manual_handoff_ready": True,
                    "recommended_mode": "gmail_api",
                    "fake_mode": True,
                    "gmail_api_action": "users.drafts.create",
                    "draft_only": False,
                    "send_allowed": False,
                    "message": "Fake Gmail status is missing the draft-only contract. Manual Draft Handoff remains available as a safe fallback.",
                    "setup": {
                        "status": "connected",
                        "next_step": "Manual Draft Handoff remains available as a safe fallback.",
                    },
                }
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def post_json(url, payload):
            seen_post_urls.append(url)
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
                    "review": {"status": "ready", "draft_text": "Número de processo: 999/26.0SMOKE"},
                    "send_allowed": False,
                }
            if url.endswith("/api/prepare/preflight"):
                return {
                    "status": "ready",
                    "artifact_effect": "none",
                    "write_allowed": False,
                    "send_allowed": False,
                    "preflight_review": {
                        "review_fingerprint": "preflight-fingerprint",
                        "preflight_review_token": "preflight-token",
                    },
                }
            if url.endswith("/api/prepare"):
                return {
                    "status": "prepared",
                    "send_allowed": False,
                    "prepared_review": {
                        "manifest": "/tmp/synthetic-manifest.json",
                        "prepared_review_token": "prepared-token",
                        "review_fingerprint": "prepared-fingerprint",
                        "payload_paths": ["/tmp/synthetic.draft.json"],
                    },
                    "items": [{
                        "draft_payload": "/tmp/synthetic.draft.json",
                        "gmail_create_draft_ready": True,
                        "gmail_create_draft_args": {"attachment_files": ["/tmp/synthetic.pdf"]},
                    }],
                }
            if url.endswith("/api/gmail/drafts/create"):
                return {
                    "status": "created",
                    "draft_id": "draft-smoke",
                    "message_id": "message-smoke",
                    "send_allowed": False,
                    "confirmation": {"fake_mode": True, "recorded_duplicate_count": 1},
                }
            raise AssertionError(url)

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            post_json=post_json,
            gmail_api_checks=True,
        )

        self.assertEqual(report["status"], "blocked", report)
        self.assertFalse(report["send_allowed"])
        self.assertEqual(seen_post_urls, [])
        gate = next(check for check in report["checks"] if check["name"] == "gmail_api_status_required")
        self.assertTrue(gate["details"]["fake_mode"])
        self.assertFalse(gate["details"]["draft_only"])


    def test_local_app_smoke_gmail_api_checks_verify_mismatch_read_only(self):
        client = self.make_client()
        seen_post_urls = []

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            if path == "/api/gmail/status":
                return {
                    "provider": "gmail_api",
                    "configured": True,
                    "connected": True,
                    "draft_create_ready": True,
                    "manual_handoff_ready": True,
                    "recommended_mode": "gmail_api",
                    "fake_mode": True,
                    "gmail_api_action": "users.drafts.create",
                    "draft_only": True,
                    "send_allowed": False,
                    "message": "Fake Gmail Draft API is connected. Manual Draft Handoff remains available as a safe fallback.",
                    "setup": {
                        "status": "connected",
                        "next_step": "Manual Draft Handoff remains available as a safe fallback.",
                    },
                }
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def post_json(url, payload):
            seen_post_urls.append(url)
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
                    "review": {"status": "ready", "draft_text": "Número de processo: 999/26.0SMOKE"},
                    "send_allowed": False,
                }
            if url.endswith("/api/prepare/preflight"):
                return {
                    "status": "ready",
                    "artifact_effect": "none",
                    "write_allowed": False,
                    "send_allowed": False,
                    "preflight_review": {
                        "review_fingerprint": "preflight-fingerprint",
                        "preflight_review_token": "preflight-token",
                    },
                }
            if url.endswith("/api/prepare"):
                return {
                    "status": "prepared",
                    "send_allowed": False,
                    "prepared_review": {
                        "manifest": "/tmp/synthetic-manifest.json",
                        "prepared_review_token": "prepared-token",
                        "review_fingerprint": "prepared-fingerprint",
                        "payload_paths": ["/tmp/synthetic.draft.json"],
                    },
                    "items": [{
                        "draft_payload": "/tmp/synthetic.draft.json",
                        "gmail_create_draft_ready": True,
                        "gmail_create_draft_args": {"attachment_files": ["/tmp/synthetic.pdf"]},
                    }],
                }
            if url.endswith("/api/gmail/drafts/create"):
                return {
                    "status": "created",
                    "draft_id": "draft-smoke",
                    "message_id": "message-smoke",
                    "send_allowed": False,
                    "confirmation": {"fake_mode": True, "recorded_duplicate_count": 1},
                }
            if url.endswith("/api/gmail/drafts/verify"):
                self.assertEqual(payload["draft_id"], "draft-mismatch-smoke")
                self.assertEqual(payload["message_id"], "local-message-smoke")
                self.assertEqual(payload["thread_id"], "local-thread-smoke")
                return {
                    "status": "reconciliation_mismatch",
                    "exists": True,
                    "verified": True,
                    "read_only": True,
                    "draft_only": True,
                    "send_allowed": False,
                    "write_allowed": False,
                    "managed_data_changed": False,
                    "local_records_changed": False,
                    "gmail_api_action": "users.drafts.get",
                    "draft_id": "draft-mismatch-smoke",
                    "message_id": "message-smoke-remote",
                    "thread_id": "thread-smoke-remote",
                    "expected_message_id": "local-message-smoke",
                    "expected_thread_id": "local-thread-smoke",
                    "message_id_matches": False,
                    "thread_id_matches": False,
                }
            raise AssertionError(url)

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            post_json=post_json,
            gmail_api_checks=True,
        )

        self.assertEqual(report["status"], "ready", report)
        self.assertIn("http://public-candidate.test/api/gmail/drafts/verify", seen_post_urls)
        check = next(check for check in report["checks"] if check["name"] == "gmail_api_verify_mismatch_read_only")
        self.assertEqual(check["status"], "ready")
        self.assertFalse(check["details"]["local_records_changed"])
