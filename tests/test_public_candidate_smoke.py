import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from honorarios_app.web import create_app
from scripts.local_app_smoke import run_smoke
from scripts.public_release_gate import analyze_public_readiness


class PublicCandidateSmokeTests(unittest.TestCase):
    def make_client(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        root = Path(runtime.name)
        return TestClient(create_app(
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
        ))

    def test_homepage_exposes_browser_flow_landmarks(self):
        client = self.make_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.text
        for text in [
            "LegalPDF Honorários",
            "Start Interpretation Request",
            "Reset workspace",
            "Drop or paste a notification PDF, photo, or screenshot here",
            "Supporting proof / declarations",
            "Add supporting attachments",
            "Review Interpretation Request",
            "Google Photos selected-photo import",
            "Open Google Photos Picker",
            "Batch Queue",
            "Packet mode",
            "Packet item inspector",
            "Packet draft recording helper",
            "Gmail handoff checklist",
            "LegalPDF Integration Preview",
            "Build integration checklist",
            "Build adapter import plan",
            "LegalPDF Adapter Contract",
            "LegalPDF Apply History",
            "LegalPDF Restore Plan",
            "Refresh apply history",
            "Restore Confirmation Phrase",
            "RESTORE LOCAL HONORARIOS BACKUP",
            "Restore Reason",
            "Local Diagnostics",
            "Source upload smoke",
            "Supporting attachment smoke",
            "Copy isolated attachment smoke command",
            "Copy advanced Gmail API smoke command",
            "Copy Browser/IAB upload smoke command",
            "Copy Browser/IAB attachment smoke command",
            "Copy Browser/IAB Recent Work smoke command",
            "Preview destination diff",
            "Preview guarded destination",
            "Preview court-email diff",
            "Preview guarded court email",
            "Gmail Draft API",
            "Draft-only Gmail",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, page)
        self.assertNotIn("_send_email", page)
        self.assertNotIn("_send_draft", page)
        self.assertNotIn("messages.send", page)
        self.assertNotIn("drafts.send", page)

    def test_diagnostics_status_lists_safe_smoke_commands(self):
        client = self.make_client()
        response = client.get("/api/diagnostics/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ready")
        self.assertFalse(data["send_allowed"])
        self.assertFalse(data["write_allowed"])
        keys = {check["key"] for check in data["checks"]}
        self.assertIn("default_live_smoke", keys)
        self.assertIn("source_upload_smoke", keys)
        self.assertIn("supporting_attachment_smoke", keys)
        self.assertIn("isolated_supporting_attachment_smoke", keys)
        self.assertIn("isolated_gmail_api_smoke", keys)
        self.assertIn("browser_iab_upload_smoke", keys)
        self.assertIn("browser_iab_supporting_attachment_smoke", keys)
        self.assertIn("browser_iab_profile_proposal_smoke", keys)
        self.assertIn("browser_iab_recent_work_lifecycle_smoke", keys)
        self.assertIn("browser_iab_manual_handoff_stale_smoke", keys)
        self.assertIn("browser_iab_gmail_api_smoke", keys)
        isolated_attachment = next(check for check in data["checks"] if check["key"] == "isolated_supporting_attachment_smoke")
        self.assertIn("scripts/isolated_app_smoke.py", isolated_attachment["command_template"])
        self.assertIn("--supporting-attachment-checks", isolated_attachment["command_template"])
        self.assertEqual(isolated_attachment["writes"], "temporary synthetic runtime only")
        isolated_gmail = next(check for check in data["checks"] if check["key"] == "isolated_gmail_api_smoke")
        self.assertIn("--gmail-api-checks", isolated_gmail["command_template"])
        self.assertIn("fake Gmail", isolated_gmail["description"])
        self.assertEqual(isolated_gmail["writes"], "temporary synthetic runtime only")
        browser_upload = next(check for check in data["checks"] if check["key"] == "browser_iab_upload_smoke")
        self.assertIn("--browser-upload-photo", browser_upload["command_template"])
        self.assertIn("--browser-upload-pdf", browser_upload["command_template"])
        self.assertEqual(browser_upload["writes"], "none")
        browser_supporting = next(check for check in data["checks"] if check["key"] == "browser_iab_supporting_attachment_smoke")
        self.assertIn("--browser-upload-supporting-attachment", browser_supporting["command_template"])
        self.assertEqual(browser_supporting["writes"], "synthetic supporting-attachment artifact only")
        browser_profile_proposal = next(check for check in data["checks"] if check["key"] == "browser_iab_profile_proposal_smoke")
        self.assertIn("--browser-profile-proposal", browser_profile_proposal["command_template"])
        self.assertEqual(browser_profile_proposal["writes"], "none")
        browser_recent_work = next(check for check in data["checks"] if check["key"] == "browser_iab_recent_work_lifecycle_smoke")
        self.assertIn("--browser-recent-work-lifecycle", browser_recent_work["command_template"])
        self.assertIn("Recent Work", browser_recent_work["description"])
        self.assertEqual(browser_recent_work["writes"], "temporary synthetic runtime only")
        browser_manual_handoff_stale = next(check for check in data["checks"] if check["key"] == "browser_iab_manual_handoff_stale_smoke")
        self.assertIn("--browser-manual-handoff-stale", browser_manual_handoff_stale["command_template"])
        self.assertIn("Manual Draft Handoff", browser_manual_handoff_stale["description"])
        self.assertEqual(browser_manual_handoff_stale["writes"], "temporary synthetic runtime only")
        browser_gmail_api = next(check for check in data["checks"] if check["key"] == "browser_iab_gmail_api_smoke")
        self.assertIn("--browser-gmail-api-create", browser_gmail_api["command_template"])
        self.assertIn("fake Gmail", browser_gmail_api["description"])
        self.assertEqual(browser_gmail_api["writes"], "temporary synthetic runtime only")
        dumped = json.dumps(data, sort_keys=True)
        self.assertNotIn("C:\\Users\\FA507", dumped)
        self.assertNotIn("_send_email", dumped)
        self.assertNotIn("_send_draft", dumped)

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

    def test_fake_gmail_draft_create_records_synthetic_duplicate_only(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        root = Path(runtime.name)
        duplicate_index = root / "duplicate-index.json"
        draft_log = root / "gmail-draft-log.json"
        profile_change_log = root / "profile-change-log.json"
        duplicate_index.write_text("[]", encoding="utf-8")
        draft_log.write_text("[]", encoding="utf-8")
        profile_change_log.write_text("[]", encoding="utf-8")
        pdf = root / "synthetic.pdf"
        pdf.write_bytes(b"%PDF-1.4\nsynthetic")
        payload = {
            "payload_schema_version": 1,
            "gmail_tool": "_create_draft",
            "case_number": "999/26.0SMOKE",
            "service_date": "2026-05-04",
            "to": "court@example.test",
            "subject": "Requerimento de honorários",
            "body": "Bom dia,",
            "attachment_files": [str(pdf)],
            "attachment_basenames": ["synthetic.pdf"],
            "attachment_sha256": {},
            "gmail_create_draft_args": {
                "to": "court@example.test",
                "subject": "Requerimento de honorários",
                "body": "Bom dia,",
                "attachment_files": [str(pdf)],
            },
            "draft_only": True,
            "send_allowed": False,
            "gmail_create_draft_ready": True,
            "gmail_create_draft_blocker": "",
        }
        payload_path = root / "synthetic.draft.json"
        payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        previous = os.environ.get("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE")
        os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = "1"
        try:
            client = TestClient(create_app(
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
            response = client.post("/api/gmail/drafts/create", json={
                "payload": str(payload_path),
                "gmail_handoff_reviewed": True,
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

    def test_browser_js_keeps_legalpdf_restore_controls_guarded(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        smoke_js = (root / "scripts" / "browser_iab_smoke.mjs").read_text(encoding="utf-8")
        for text in [
            "Apply this restore locally",
            "Restore local references from backup",
            "RESTORE LEGALPDF APPLY BACKUP",
            "legalpdf-restore-reason",
            "legalpdf-restore-phrase",
            "confirm-legalpdf-restore",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, app_js)
                self.assertIn(text, smoke_js)
        for text in [
            "function renderSourceAttention",
            "Review Attention",
            "attention-flags",
            "attention-severity",
        ]:
            with self.subTest(source_attention=text):
                self.assertIn(text, app_js)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)
        self.assertNotIn("_send_email", smoke_js)
        self.assertNotIn("_send_draft", smoke_js)

    def test_browser_iab_smoke_attempts_guarded_upload_evidence(self):
        root = Path(__file__).resolve().parents[1]
        smoke_js = (root / "scripts" / "browser_iab_smoke.mjs").read_text(encoding="utf-8")
        for text in [
            "createSyntheticUploadFixtures",
            "setSyntheticInputFile",
            "setInputFiles",
            "#photo-file",
            "#notification-file",
            "#supporting-attachment-file",
            "#photo-upload-form button[type=submit]",
            "#notification-upload-form button[type=submit]",
            "#supporting-attachment-form button[type=submit]",
            "browser_photo_upload_evidence",
            "browser_pdf_upload_evidence",
            "browser_supporting_attachment_upload_evidence",
            "browser_record_helper",
            "browser_profile_proposal",
            "browser_recent_work_lifecycle",
            "browser_batch_stale_gating",
            "browser_legalpdf_import_gates",
            "data-use-profile-proposal",
            "#preview-profile-change",
            "#gmail-response-raw",
            "#autofill-record-from-prepared",
            "#record_draft_id",
            "Source Evidence",
            "Filename",
            "synthetic-declaracao.pdf",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, smoke_js)
        self.assertNotIn("Browser/IAB smoke does not drive local file-picker uploads yet", smoke_js)
        self.assertNotIn("_send_email", smoke_js)
        self.assertNotIn("_send_draft", smoke_js)

    def test_browser_js_invalidates_stale_prepared_payloads(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        for text in [
            "function clearPreparedArtifacts",
            "state.lastPrepared = null",
            "state.draftLifecycle = null",
            "record_payload",
            "record_draft_id",
            "record_message_id",
            "record_thread_id",
            "record_supersedes",
            "gmail-response-raw",
            "renderDraftLifecycle(null)",
            "syncActionGates(null)",
            "source changed",
            "review changed",
            "review reset",
            "intake form changed",
            "data-stale-reason",
            'removeAttribute("data-stale-reason")',
        ]:
            with self.subTest(text=text):
                self.assertIn(text, app_js)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)

    def test_browser_js_requires_handoff_review_before_one_click_record(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        page = (root / "honorarios_app" / "templates" / "index.html").read_text(encoding="utf-8")
        for text in [
            "Gmail handoff checklist",
            "I reviewed the PDF preview",
            "I used the exact `_create_draft` args shown above",
            "gmail_handoff_reviewed",
            "Review the PDF preview and exact Gmail args before local recording.",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, app_js + page)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)

    def test_openai_recovery_uses_strict_json_schema_contract(self):
        root = Path(__file__).resolve().parents[1]
        ai_recovery = (root / "honorarios_app" / "ai_recovery.py").read_text(encoding="utf-8")
        for text in [
            "AI_RECOVERY_RESPONSE_FORMAT",
            "AI_RECOVERY_SCHEMA_NAME",
            "AI_RECOVERY_PROMPT_VERSION",
            "AI_RECOVERY_FIELD_NAMES",
            '"prompt_version"',
            '"missing_fields"',
            '"type": "json_schema"',
            'AI_RECOVERY_SCHEMA_NAME = "honorarios_source_recovery"',
            '"name": AI_RECOVERY_SCHEMA_NAME',
            '"strict": True',
            '"raw_visible_text"',
            '"fields"',
            '"translation_indicators"',
            '"warnings"',
            '"service_entity_type"',
            '"additionalProperties": False',
            "text=AI_RECOVERY_RESPONSE_FORMAT",
            "Pattern examples",
            "Posto da GNR de Ferreira do Alentejo",
            "Posto da GNR de Beja",
            "Beringel",
            "Tribunal do Trabalho de Beja",
            "Gabinete Médico-Legal de Beja",
            "Hospital José Joaquim Fernandes",
            "número de palavras",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, ai_recovery)
        self.assertNotIn("_send_email", ai_recovery)
        self.assertNotIn("_send_draft", ai_recovery)

    def test_legalpdf_integration_preview_report_and_checklist_are_read_only(self):
        root = Path(__file__).resolve().parents[1]
        profiles_example_path = root / "data" / "service-profiles.example.json"
        court_example_path = root / "data" / "court-emails.example.json"
        profiles_overlay_path = root / "data" / "service-profiles.json"
        court_overlay_path = root / "data" / "court-emails.json"
        profiles_before = profiles_example_path.read_text(encoding="utf-8")
        courts_before = court_example_path.read_text(encoding="utf-8")
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
        contract = client.get("/api/integration/adapter-contract")
        for response in [preview, report, checklist, plan, history, contract]:
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
        self.assertEqual(contract.json()["recommended_gmail_mode"], "manual_handoff")
        self.assertFalse(contract.json()["write_allowed"])
        self.assertFalse(contract.json()["legalpdf_write_allowed"])
        self.assertFalse(contract.json()["managed_data_changed"])
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
        self.assertEqual(profiles_example_path.read_text(encoding="utf-8"), profiles_before)
        self.assertEqual(court_example_path.read_text(encoding="utf-8"), courts_before)
        self.assertFalse(profiles_overlay_path.exists())
        self.assertFalse(court_overlay_path.exists())

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

    def test_local_app_smoke_runner_source_upload_contract_is_injectable(self):
        client = self.make_client()
        seen_uploads = []

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def post_multipart(url, fields, filename, content, content_type):
            seen_uploads.append((url, dict(fields), filename, content_type, len(content)))
            if fields["source_kind"] == "photo":
                return {
                    "status": "uploaded",
                    "send_allowed": False,
                    "source": {"filename": filename, "send_allowed": False},
                    "candidate_intake": {},
                    "source_evidence": {
                        "filename": filename,
                        "attention": {
                            "status": "blocked",
                            "flag_count": 1,
                            "flags": [{"code": "missing_required_info", "severity": "blocked"}],
                        },
                    },
                }
            if fields["source_kind"] == "notification_pdf":
                return {
                    "status": "uploaded",
                    "send_allowed": False,
                    "source": {"filename": filename, "send_allowed": False},
                    "candidate_intake": {"case_number": "999/26.0SMOKE", "service_date": "2026-05-04"},
                    "source_evidence": {
                        "filename": filename,
                        "case_number": "999/26.0SMOKE",
                        "service_date": "2026-05-04",
                        "attention": {"status": "ready", "flag_count": 0, "flags": []},
                    },
                }
            raise AssertionError(fields)

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            post_multipart=post_multipart,
            source_upload_checks=True,
        )
        self.assertEqual(report["status"], "ready", report)
        self.assertIn("source_upload_photo_attention", {check["name"] for check in report["checks"]})
        self.assertIn("source_upload_pdf_evidence", {check["name"] for check in report["checks"]})
        self.assertEqual([item[1]["source_kind"] for item in seen_uploads], ["photo", "notification_pdf"])

    def test_local_app_smoke_runner_supporting_attachment_contract_is_injectable(self):
        client = self.make_client()
        seen_uploads = []

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def post_multipart(url, fields, filename, content, content_type):
            seen_uploads.append((url, dict(fields), filename, content_type, len(content)))
            if url.endswith("/api/attachments/upload"):
                return {
                    "status": "uploaded",
                    "send_allowed": False,
                    "attachment": {
                        "source_kind": "supporting_attachment",
                        "attachment_kind": "notification_pdf",
                        "filename": filename,
                        "stored_path": "/tmp/synthetic-declaracao.pdf",
                        "artifact_url": "/api/artifacts/sources/attachments/synthetic-declaracao.pdf",
                    },
                }
            raise AssertionError(url)

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            post_multipart=post_multipart,
            supporting_attachment_checks=True,
        )
        self.assertEqual(report["status"], "ready", report)
        self.assertIn("supporting_attachment_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertEqual(len(seen_uploads), 1)
        self.assertTrue(seen_uploads[0][0].endswith("/api/attachments/upload"))

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
                    {"name": "browser_supporting_attachment_upload_evidence", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_correction_mode", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_replacement_prepare", "status": "ready", "message": "ok", "details": {}},
                    {"name": "browser_record_helper", "status": "ready", "message": "ok", "details": {}},
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
            browser_upload_supporting_attachment=True,
            browser_correction_mode=True,
            browser_prepare_replacement=True,
            browser_record_helper=True,
            browser_apply_history=True,
            browser_runner=browser_runner,
        )
        self.assertEqual(report["status"], "ready", report)
        self.assertIn("browser_review_drawer", {check["name"] for check in report["checks"]})
        self.assertIn("browser_answer_questions", {check["name"] for check in report["checks"]})
        self.assertIn("browser_photo_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_pdf_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_supporting_attachment_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_correction_mode", {check["name"] for check in report["checks"]})
        self.assertIn("browser_replacement_prepare", {check["name"] for check in report["checks"]})
        self.assertIn("browser_record_helper", {check["name"] for check in report["checks"]})
        self.assertTrue(seen_kwargs["answer_questions"])
        self.assertTrue(seen_kwargs["upload_photo"])
        self.assertTrue(seen_kwargs["upload_pdf"])
        self.assertTrue(seen_kwargs["upload_supporting_attachment"])
        self.assertTrue(seen_kwargs["correction_mode"])
        self.assertTrue(seen_kwargs["prepare_replacement"])
        self.assertTrue(seen_kwargs["record_helper"])
        self.assertTrue(seen_kwargs["apply_history"])

    def test_candidate_privacy_gate_passes(self):
        report = analyze_public_readiness(Path(__file__).resolve().parents[1], require_git=False)
        self.assertTrue(report["public_ready"], report)


if __name__ == "__main__":
    unittest.main()
