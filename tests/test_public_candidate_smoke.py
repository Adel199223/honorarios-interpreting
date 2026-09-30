import re
import shlex
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from honorarios_app.web import create_app


# Shared synthetic-only fixture helpers. Runnable cases live in focused modules.
class PublicCandidateSmokeTests(unittest.TestCase):
    def make_client(self):
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
        return TestClient(create_app(
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
        ))


    def preflight_prepare(self, client, payload):
        intakes = payload.get("intakes")
        if intakes is None and isinstance(payload.get("intake"), dict):
            intakes = [payload["intake"]]
        preflight_payload = {
            "intakes": intakes,
            "packet_mode": bool(payload.get("packet_mode", False)),
        }
        for key in ("correction_mode", "correction_reason"):
            if key in payload:
                preflight_payload[key] = payload[key]
        preflight = client.post("/api/prepare/preflight", json=preflight_payload)
        self.assertEqual(preflight.status_code, 200, preflight.text)
        preflight_data = preflight.json()
        self.assertEqual(preflight_data["status"], "ready", preflight.text)
        request_payload = dict(payload)
        request_payload["preflight_review"] = preflight_data["preflight_review"]
        return client.post("/api/prepare", json=request_payload)


    def adapter_health_payload(self, *, isolated_synthetic=False):
        payload = {
            "status": "ready",
            "app": "LegalPDF Honorários",
            "timestamp": "2026-05-10T00:00:00Z",
            "send_allowed": False,
            "write_allowed": False,
            "managed_data_changed": False,
        }
        if isolated_synthetic:
            payload.update({
                "isolated_runtime": True,
                "synthetic_runtime": True,
                "runtime": {
                    "mode": "synthetic_isolated",
                    "attestation": "honorarios_synthetic_runtime_v1",
                },
            })
        return payload


    def adapter_contract_payload(self):
        from scripts.legalpdf_adapter_caller import REQUIRED_ADAPTER_ENDPOINTS

        return {
            "status": "ready",
            "recommended_gmail_mode": "manual_handoff",
            "draft_only": True,
            "send_allowed": False,
            "write_allowed": False,
            "legalpdf_write_allowed": False,
            "managed_data_changed": False,
            "gmail_boundary": {"required_tool": "_create_draft", "draft_only": True, "send_allowed": False},
            "optional_gmail_draft_api_boundary": {
                "status": "optional",
                "create_endpoint": "/api/gmail/drafts/create",
                "verify_endpoint": "/api/gmail/drafts/verify",
                "create_action": "users.drafts.create",
                "verify_action": "users.drafts.get",
                "draft_only": True,
                "send_allowed": False,
                "verify_read_only": True,
                "verify_local_records_changed": False,
                "forbidden_actions": [
                    "users.messages.send",
                    "users.drafts.send",
                    "users.messages.trash",
                    "users.messages.delete",
                    "users.messages.list",
                    "users.drafts.delete",
                ],
            },
            "prepared_review_binding": {
                "preflight_response_field": "preflight_review",
                "prepare_request_field": "preflight_review",
                "prepare_response_field": "prepared_review",
                "handoff_required_fields": ["payload", "prepared_manifest", "prepared_review_token", "review_fingerprint"],
                "record_required_fields": ["payload", "prepared_manifest", "prepared_review_token", "review_fingerprint", "gmail_handoff_reviewed", "draft_id", "message_id", "thread_id"],
                "gmail_api_create_required_fields": ["payload", "prepared_manifest", "prepared_review_token", "review_fingerprint", "gmail_handoff_reviewed"],
                "stale_after_payload_or_manifest_change": True,
                "local_workflow_guard_only": True,
                "send_allowed": False,
            },
            "sequence": [{"endpoint": endpoint} for endpoint in REQUIRED_ADAPTER_ENDPOINTS],
        }


    def assert_diagnostic_command_templates_are_parseable(self, data):
        root = Path(__file__).resolve().parents[1]
        supported_scripts = {
            "scripts/local_app_smoke.py",
            "scripts/isolated_app_smoke.py",
            "scripts/legalpdf_adapter_caller.py",
            "scripts/runtime_doctor.py",
        }
        supported_flags = {}
        for script in supported_scripts:
            script_text = (root / script).read_text(encoding="utf-8")
            supported_flags[script] = set(re.findall(r'parser\.add_argument\(\s*"([^"]+)"', script_text, re.MULTILINE))
        for check in data["checks"]:
            with self.subTest(key=check["key"]):
                tokens = shlex.split(check["command_template"].format(base_url="http://127.0.0.1:8765"))
                self.assertGreaterEqual(len(tokens), 2)
                self.assertEqual(tokens[0], "python")
                self.assertIn(tokens[1], supported_scripts)
                self.assertTrue((root / tokens[1]).is_file())
                flags = [token.split("=", 1)[0] for token in tokens[2:] if token.startswith("--")]
                self.assertEqual([flag for flag in flags if flag not in supported_flags[tokens[1]]], [])
                self.assertNotIn("_send_email", " ".join(tokens))
                self.assertNotIn("_send_draft", " ".join(tokens))
