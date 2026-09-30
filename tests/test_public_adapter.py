import json
import inspect
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch


from scripts.local_app_smoke import _adapter_questions_are_numbered, run_smoke


from test_public_candidate_smoke import PublicCandidateSmokeTests


class PublicAdapterTests(PublicCandidateSmokeTests):
    def test_legalpdf_integration_preview_report_and_checklist_are_read_only(self):
        root = Path(__file__).resolve().parents[1]
        profiles_example_path = root / "data" / "service-profiles.example.json"
        court_example_path = root / "data" / "court-emails.example.json"
        profiles_overlay_path = root / "data" / "service-profiles.json"
        court_overlay_path = root / "data" / "court-emails.json"
        profiles_before = profiles_example_path.read_text(encoding="utf-8")
        courts_before = court_example_path.read_text(encoding="utf-8")
        profiles_overlay_before = profiles_overlay_path.read_text(encoding="utf-8") if profiles_overlay_path.exists() else None
        court_overlay_before = court_overlay_path.read_text(encoding="utf-8") if court_overlay_path.exists() else None
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
        contract_data = contract.json()
        self.assertEqual(contract_data["contract_version"], "2026-05-10.optional-gmail-boundary.v4")
        self.assertEqual(contract_data["gmail_boundary"]["required_tool"], "_create_draft")
        self.assertTrue(contract_data["gmail_boundary"]["draft_only"])
        self.assertFalse(contract_data["gmail_boundary"]["send_allowed"])
        optional_boundary = contract_data["optional_gmail_draft_api_boundary"]
        self.assertEqual(optional_boundary["status"], "optional")
        self.assertEqual(optional_boundary["create_endpoint"], "/api/gmail/drafts/create")
        self.assertEqual(optional_boundary["verify_endpoint"], "/api/gmail/drafts/verify")
        self.assertEqual(optional_boundary["create_action"], "users.drafts.create")
        self.assertEqual(optional_boundary["verify_action"], "users.drafts.get")
        self.assertTrue(optional_boundary["draft_only"])
        self.assertFalse(optional_boundary["send_allowed"])
        self.assertTrue(optional_boundary["verify_read_only"])
        self.assertFalse(optional_boundary["verify_local_records_changed"])
        self.assertIn("users.drafts.send", optional_boundary["forbidden_actions"])
        self.assertIn("users.messages.send", optional_boundary["forbidden_actions"])
        binding = contract_data["prepared_review_binding"]
        self.assertEqual(binding["preflight_response_field"], "preflight_review")
        self.assertEqual(binding["prepare_request_field"], "preflight_review")
        self.assertEqual(binding["prepare_response_field"], "prepared_review")
        self.assertEqual(binding["handoff_required_fields"], [
            "payload",
            "prepared_manifest",
            "prepared_review_token",
            "review_fingerprint",
        ])
        self.assertEqual(binding["record_required_fields"], [
            "payload",
            "prepared_manifest",
            "prepared_review_token",
            "review_fingerprint",
            "gmail_handoff_reviewed",
            "draft_id",
            "message_id",
            "thread_id",
        ])
        self.assertTrue(binding["stale_after_payload_or_manifest_change"])
        self.assertTrue(binding["local_workflow_guard_only"])
        steps = {step["endpoint"]: step for step in contract_data["sequence"]}
        self.assertIn("preflight_review", steps["/api/prepare"]["required_request_fields"])
        self.assertIn("prepared_review.prepared_review_token", steps["/api/prepare"]["response_fields"])
        self.assertIn("prepared_review_token", steps["/api/gmail/manual-handoff"]["required_request_fields"])
        self.assertIn("review_fingerprint", steps["/api/drafts/record"]["required_request_fields"])
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
        if profiles_overlay_before is None:
            self.assertFalse(profiles_overlay_path.exists())
        else:
            self.assertEqual(profiles_overlay_path.read_text(encoding="utf-8"), profiles_overlay_before)
        if court_overlay_before is None:
            self.assertFalse(court_overlay_path.exists())
        else:
            self.assertEqual(court_overlay_path.read_text(encoding="utf-8"), court_overlay_before)


    def test_local_app_smoke_runner_adapter_contract_sequence_is_injectable(self):
        client = self.make_client()
        seen_posts = []
        seen_uploads = []

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            if path == "/api/health":
                return self.adapter_health_payload(isolated_synthetic=True)
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def post_json(url, payload):
            seen_posts.append(url)
            if url.endswith("/api/review"):
                intake = payload["intake"]
                self.assertEqual(intake["source_filename"], "synthetic-notification.pdf")
                self.assertNotIn("closing_date", intake)
                return {
                    "status": "needs_info",
                    "intake": intake,
                    "effective_intake": intake,
                    "questions": [{
                        "number": 1,
                        "field": "closing_date",
                        "question": "What date should appear in the closing line of the request?",
                        "answer_hint": "Use YYYY-MM-DD.",
                    }],
                    "question_text": "1. What date should appear in the closing line?",
                    "send_allowed": False,
                }
            if url.endswith("/api/review/apply-answers"):
                intake = dict(payload["intake"])
                self.assertEqual(intake["source_filename"], "synthetic-notification.pdf")
                self.assertIn("1. 2026-05-04", payload["answers"])
                intake["closing_date"] = "2026-05-04"
                return {
                    "status": "ready",
                    "intake": intake,
                    "effective_intake": intake,
                    "draft_text": "Número de processo: 999/26.0SMOKE\n\nPede deferimento,",
                    "recipient": "court@example.test",
                    "send_allowed": False,
                }
            if url.endswith("/api/prepare/preflight"):
                self.assertTrue(payload["packet_mode"])
                self.assertEqual(payload["intakes"][0]["closing_date"], "2026-05-04")
                return {
                    "status": "ready",
                    "artifact_effect": "none",
                    "write_allowed": False,
                    "send_allowed": False,
                    "packet_mode": True,
                    "preflight_review": {
                        "review_fingerprint": "preflight-fingerprint",
                        "preflight_review_token": "preflight-token",
                    },
                }
            if url.endswith("/api/prepare"):
                self.assertTrue(payload["packet_mode"])
                self.assertEqual(payload["preflight_review"]["preflight_review_token"], "preflight-token")
                self.assertEqual(payload["intakes"][0]["closing_date"], "2026-05-04")
                return {
                    "status": "prepared",
                    "packet_mode": True,
                    "send_allowed": False,
                    "prepared_review": {
                        "manifest": "/tmp/adapter-manifest.json",
                        "prepared_review_token": "prepared-token",
                        "review_fingerprint": "prepared-fingerprint",
                        "payload_paths": ["/tmp/adapter-packet.draft.json"],
                    },
                    "items": [{
                        "draft_payload": "/tmp/adapter.draft.json",
                        "gmail_create_draft_ready": True,
                        "gmail_create_draft_args": {"attachment_files": ["/tmp/adapter.pdf"]},
                        "send_allowed": False,
                    }],
                    "packet": {
                        "draft_payload": "/tmp/adapter-packet.draft.json",
                        "gmail_create_draft_ready": True,
                        "gmail_create_draft_args": {"attachment_files": ["/tmp/adapter-packet.pdf"]},
                        "underlying_requests": [{"case_number": "999/26.0SMOKE", "service_date": "2026-05-04"}],
                        "send_allowed": False,
                    },
                }
            if url.endswith("/api/gmail/manual-handoff"):
                self.assertEqual(payload["payload"], "/tmp/adapter-packet.draft.json")
                if payload["prepared_review_token"] == "stale-prepared-token":
                    return {
                        "status": "blocked",
                        "message": "Prepared review token is stale. Prepare the PDF again from the reviewed request.",
                        "mode": "manual_handoff",
                        "draft_only": True,
                        "send_allowed": False,
                        "write_allowed": False,
                    }
                self.assertEqual(payload["prepared_review_token"], "prepared-token")
                return {
                    "status": "ready",
                    "mode": "manual_handoff",
                    "gmail_tool": "_create_draft",
                    "copyable_prompt": "Create a Gmail draft only using `_create_draft`.",
                    "attachment_files": ["/tmp/adapter-packet.pdf"],
                    "send_allowed": False,
                    "write_allowed": False,
                }
            if url.endswith("/api/drafts/record"):
                self.assertTrue(payload["gmail_handoff_reviewed"])
                if payload["prepared_review_token"] == "stale-prepared-token":
                    return {
                        "status": "blocked",
                        "message": "Prepared review token is stale. Prepare the PDF again from the reviewed request.",
                        "send_allowed": False,
                    }
                self.assertEqual(payload["prepared_review_token"], "prepared-token")
                return {
                    "status": "recorded",
                    "draft_id": "draft-adapter-smoke",
                    "message_id": "message-adapter-smoke",
                    "thread_id": "thread-adapter-smoke",
                    "recorded_duplicate_count": 1,
                    "send_allowed": False,
                }
            raise AssertionError(url)

        def post_multipart(url, fields, filename, content, content_type):
            seen_uploads.append((url, dict(fields), filename, content_type, len(content)))
            self.assertTrue(url.endswith("/api/sources/upload"))
            self.assertEqual(fields["source_kind"], "notification_pdf")
            self.assertEqual(fields["profile"], "example_interpreting")
            self.assertEqual(filename, "synthetic-notification.pdf")
            self.assertEqual(content_type, "application/pdf")
            return {
                "status": "uploaded",
                "send_allowed": False,
                "candidate_intake": {
                    "profile": "example_interpreting",
                    "case_number": "999/26.0SMOKE",
                    "service_date": "2026-05-04",
                    "service_date_source": "user_confirmed",
                    "addressee": "Exmo. Senhor Procurador da República\nExample Court",
                    "payment_entity": "Example Court",
                    "service_entity": "Example Police / Example Police Station",
                    "service_entity_type": "police",
                    "entities_differ": True,
                    "service_place": "Example Police Station",
                    "service_place_phrase": "em diligência realizada no Example Police Station",
                    "claim_transport": True,
                    "transport": {
                        "origin": "Example City",
                        "destination": "Example City",
                        "km_one_way": 12,
                        "round_trip_phrase": "ida_volta",
                    },
                    "closing_city": "Example City",
                    "recipient_email": "court@example.test",
                    "source_filename": "synthetic-notification.pdf",
                },
                "source_evidence": {
                    "filename": "synthetic-notification.pdf",
                    "question_count": 1,
                    "attention": {
                        "status": "blocked",
                        "flag_count": 1,
                        "flags": [{"code": "missing_required_info", "severity": "blocked"}],
                    },
                },
            }

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            post_json=post_json,
            post_multipart=post_multipart,
            adapter_contract_checks=True,
        )

        self.assertEqual(report["status"], "ready", report)
        names = {check["name"] for check in report["checks"]}
        self.assertIn("adapter_contract_gmail_boundary", names)
        self.assertIn("adapter_contract_optional_gmail_draft_api_boundary", names)
        self.assertIn("adapter_contract_sequence", names)
        self.assertIn("adapter_source_upload_evidence", names)
        self.assertIn("adapter_review_missing_questions", names)
        self.assertIn("adapter_apply_answers_ready", names)
        self.assertIn("adapter_manual_handoff_packet", names)
        self.assertIn("adapter_manual_handoff_rejects_stale_review", names)
        self.assertIn("adapter_record_rejects_stale_review", names)
        self.assertIn("adapter_record_stale_no_local_write", names)
        self.assertIn("adapter_record_draft", names)
        self.assertIn("http://public-candidate.test/api/sources/upload", [item[0] for item in seen_uploads])
        self.assertIn("http://public-candidate.test/api/review/apply-answers", seen_posts)
        self.assertIn("http://public-candidate.test/api/gmail/manual-handoff", seen_posts)
        self.assertIn("http://public-candidate.test/api/drafts/record", seen_posts)


    def test_legalpdf_adapter_caller_shim_exports_safe_contract_helpers(self):
        from scripts.legalpdf_adapter_caller import (
            ADAPTER_HEALTH_ENDPOINT,
            REQUIRED_ADAPTER_ENDPOINTS,
            AdapterReadinessResult,
            LegalPdfAdapterCaller,
            adapter_questions_are_numbered,
            prepared_review_request_fields,
            run_adapter_readiness_result,
            stale_prepared_review_fields,
        )

        contract = {
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
        caller = LegalPdfAdapterCaller(
            "http://public-candidate.test/",
            fetch_json=lambda url: contract,
            post_json=lambda _url, _payload: {},
            post_multipart=lambda _url, _fields, _filename, _content, _content_type: {},
        )

        validation = caller.validate_contract(caller.fetch_contract())
        self.assertTrue(validation.ready, validation)
        self.assertFalse(validation.send_allowed)
        self.assertFalse(validation.write_allowed)
        self.assertFalse(validation.legalpdf_write_allowed)
        self.assertEqual(validation.missing_endpoints, [])
        self.assertTrue(validation.details["gmail_boundary_ready"])
        self.assertFalse(validation.details["gmail_boundary_send_allowed"])
        self.assertTrue(validation.details["gmail_boundary_draft_only"])
        self.assertTrue(validation.details["optional_gmail_draft_api_boundary_ready"])
        self.assertTrue(validation.details["optional_gmail_draft_api_boundary_present"])
        self.assertNotIn("/api/gmail/drafts/create", REQUIRED_ADAPTER_ENDPOINTS)
        self.assertNotIn("/api/gmail/drafts/verify", REQUIRED_ADAPTER_ENDPOINTS)
        self.assertTrue(adapter_questions_are_numbered(
            [{"number": 1, "field": "closing_date"}],
            "Please answer by number:\n1. Closing date?",
        ))

        prepared_fields = prepared_review_request_fields({
            "manifest": "/tmp/adapter-manifest.json",
            "prepared_review_token": "prepared-token",
            "review_fingerprint": "fingerprint",
        })
        self.assertEqual(prepared_fields["prepared_manifest"], "/tmp/adapter-manifest.json")
        self.assertEqual(prepared_fields["prepared_review_token"], "prepared-token")
        self.assertEqual(prepared_fields["review_fingerprint"], "fingerprint")
        stale_fields = stale_prepared_review_fields(prepared_fields)
        self.assertEqual(stale_fields["prepared_review_token"], "stale-prepared-token")
        self.assertEqual(stale_fields["prepared_manifest"], prepared_fields["prepared_manifest"])

        smoke_source = (Path(__file__).resolve().parents[1] / "scripts" / "local_app_smoke.py").read_text(encoding="utf-8")
        self.assertIn("from scripts.legalpdf_adapter_caller import", smoke_source)
        self.assertIn("run_synthetic_adapter_sequence(", smoke_source)

        seen_fetches = []

        def fetch_json(url):
            seen_fetches.append(url)
            if url.endswith(ADAPTER_HEALTH_ENDPOINT):
                return self.adapter_health_payload()
            if url.endswith("/api/integration/adapter-contract"):
                return contract
            raise AssertionError(url)

        readiness = run_adapter_readiness_result("http://public-candidate.test/", fetch_json=fetch_json)
        self.assertIsInstance(readiness, AdapterReadinessResult)
        self.assertEqual(readiness.status, "ready")
        self.assertTrue(readiness.health_ready)
        self.assertTrue(readiness.contract_ready)
        self.assertFalse(readiness.send_allowed)
        self.assertFalse(readiness.write_allowed)
        self.assertFalse(readiness.legalpdf_write_allowed)
        self.assertEqual(seen_fetches[:2], [
            "http://public-candidate.test/api/health",
            "http://public-candidate.test/api/integration/adapter-contract",
        ])
        summary = readiness.safe_summary()
        self.assertTrue(summary["health_ready"])
        self.assertTrue(summary["contract_ready"])
        self.assertFalse(summary["isolated_synthetic_runtime"])
        summary_text = json.dumps(summary, sort_keys=True)
        for secretish in ["copyable_prompt", "/tmp/adapter", "draft-", "access_token", "source_text"]:
            with self.subTest(secretish=secretish):
                self.assertNotIn(secretish, summary_text)


    def test_legalpdf_adapter_readiness_rejects_unsafe_health_before_contract(self):
        from scripts.legalpdf_adapter_caller import run_adapter_readiness_result

        seen_fetches = []

        def fetch_json(url):
            seen_fetches.append(url)
            if url.endswith("/api/health"):
                payload = self.adapter_health_payload()
                payload["send_allowed"] = True
                return payload
            if url.endswith("/api/integration/adapter-contract"):
                raise AssertionError("Contract should not be fetched when health is unsafe.")
            raise AssertionError(url)

        readiness = run_adapter_readiness_result("http://public-candidate.test/", fetch_json=fetch_json)

        self.assertEqual(readiness.status, "blocked")
        self.assertFalse(readiness.health_ready)
        self.assertFalse(readiness.contract_ready)
        self.assertTrue(readiness.send_allowed)
        self.assertEqual(seen_fetches, ["http://public-candidate.test/api/health"])
        names = {check["name"] for check in readiness.checks}
        self.assertIn("adapter_health_read_only", names)
        self.assertNotIn("adapter_contract_read_only", names)


    def test_legalpdf_adapter_caller_rejects_contract_without_prepared_review_fields(self):
        from scripts.legalpdf_adapter_caller import REQUIRED_ADAPTER_ENDPOINTS, LegalPdfAdapterCaller

        contract = {
            "status": "ready",
            "recommended_gmail_mode": "manual_handoff",
            "draft_only": True,
            "send_allowed": False,
            "write_allowed": False,
            "legalpdf_write_allowed": False,
            "managed_data_changed": False,
            "gmail_boundary": {"required_tool": "_create_draft", "draft_only": True, "send_allowed": False},
            "prepared_review_binding": {
                "preflight_response_field": "preflight_review",
                "prepare_request_field": "preflight_review",
                "prepare_response_field": "prepared_review",
                "handoff_required_fields": ["payload", "prepared_manifest", "prepared_review_token"],
                "record_required_fields": ["payload", "prepared_manifest", "prepared_review_token", "gmail_handoff_reviewed", "draft_id", "message_id", "thread_id"],
                "gmail_api_create_required_fields": ["payload", "prepared_manifest", "prepared_review_token", "gmail_handoff_reviewed"],
                "stale_after_payload_or_manifest_change": True,
                "local_workflow_guard_only": True,
                "send_allowed": False,
            },
            "sequence": [{"endpoint": endpoint} for endpoint in REQUIRED_ADAPTER_ENDPOINTS],
        }
        caller = LegalPdfAdapterCaller(
            "http://public-candidate.test/",
            fetch_json=lambda _url: contract,
            post_json=lambda _url, _payload: {},
            post_multipart=lambda _url, _fields, _filename, _content, _content_type: {},
        )

        validation = caller.validate_contract(caller.fetch_contract())

        self.assertFalse(validation.ready)
        self.assertEqual(validation.missing_endpoints, [])
        self.assertIn("review_fingerprint", validation.details["missing_prepared_review_fields"]["handoff_required_fields"])
        self.assertIn("review_fingerprint", validation.details["missing_prepared_review_fields"]["record_required_fields"])
        self.assertIn("review_fingerprint", validation.details["missing_prepared_review_fields"]["gmail_api_create_required_fields"])


    def test_legalpdf_adapter_caller_rejects_send_capable_gmail_boundary(self):
        from scripts.legalpdf_adapter_caller import REQUIRED_ADAPTER_ENDPOINTS, LegalPdfAdapterCaller

        base_contract = {
            "status": "ready",
            "recommended_gmail_mode": "manual_handoff",
            "draft_only": True,
            "send_allowed": False,
            "write_allowed": False,
            "legalpdf_write_allowed": False,
            "managed_data_changed": False,
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

        for gmail_boundary in [
            {"required_tool": "_create_draft", "send_allowed": True, "draft_only": True},
            {"required_tool": "_create_draft", "send_allowed": False},
            {"required_tool": "_create_draft", "send_allowed": False, "draft_only": False},
        ]:
            contract = {**base_contract, "gmail_boundary": gmail_boundary}
            caller = LegalPdfAdapterCaller(
                "http://public-candidate.test/",
                fetch_json=lambda _url, contract=contract: contract,
                post_json=lambda _url, _payload: {},
                post_multipart=lambda _url, _fields, _filename, _content, _content_type: {},
            )

            validation = caller.validate_contract(caller.fetch_contract())

            self.assertFalse(validation.ready, gmail_boundary)
            self.assertFalse(validation.details.get("gmail_boundary_ready", True), validation.details)


    def test_legalpdf_adapter_caller_rejects_unsafe_optional_gmail_draft_api_boundary(self):
        from scripts.legalpdf_adapter_caller import REQUIRED_ADAPTER_ENDPOINTS, LegalPdfAdapterCaller

        valid_optional_boundary = {
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
        }
        base_contract = {
            "status": "ready",
            "recommended_gmail_mode": "manual_handoff",
            "draft_only": True,
            "send_allowed": False,
            "write_allowed": False,
            "legalpdf_write_allowed": False,
            "managed_data_changed": False,
            "gmail_boundary": {"required_tool": "_create_draft", "draft_only": True, "send_allowed": False},
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

        unsafe_boundaries = [
            {**valid_optional_boundary, "send_allowed": True},
            {**valid_optional_boundary, "draft_only": False},
            {**valid_optional_boundary, "create_action": "users.messages.send"},
            {**valid_optional_boundary, "verify_action": "users.messages.list"},
            {**valid_optional_boundary, "verify_read_only": False},
            {**valid_optional_boundary, "verify_local_records_changed": True},
            {**valid_optional_boundary, "forbidden_actions": ["users.messages.send"]},
        ]
        for optional_boundary in unsafe_boundaries:
            contract = {**base_contract, "optional_gmail_draft_api_boundary": optional_boundary}
            caller = LegalPdfAdapterCaller(
                "http://public-candidate.test/",
                fetch_json=lambda _url, contract=contract: contract,
                post_json=lambda _url, _payload: {},
                post_multipart=lambda _url, _fields, _filename, _content, _content_type: {},
            )

            validation = caller.validate_contract(caller.fetch_contract())

            self.assertFalse(validation.ready, optional_boundary)
            self.assertFalse(validation.details.get("optional_gmail_draft_api_boundary_ready", True), validation.details)


    def test_legalpdf_adapter_caller_builds_reusable_http_transport(self):
        from scripts.legalpdf_adapter_caller import build_http_adapter_caller

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        seen_requests = []

        def fake_urlopen(request, timeout):
            seen_requests.append(request)
            return FakeResponse({"status": "ok", "method": request.get_method(), "timeout": timeout})

        with patch("scripts.legalpdf_adapter_caller.urllib.request.urlopen", side_effect=fake_urlopen):
            caller = build_http_adapter_caller("public-candidate.test/", timeout=7.5)
            contract = caller.fetch_contract()
            review = caller.review_intake({"case_number": "999/26.0SMOKE"})
            upload = caller.upload_source(
                {"source_kind": "notification_pdf", "profile": "example_interpreting"},
                "../synthetic-notification.pdf",
                b"%PDF synthetic",
                "application/pdf",
            )

        self.assertEqual(caller.base_url, "http://public-candidate.test")
        self.assertEqual(contract["method"], "GET")
        self.assertEqual(review["method"], "POST")
        self.assertEqual(upload["timeout"], 7.5)
        self.assertEqual(seen_requests[0].full_url, "http://public-candidate.test/api/integration/adapter-contract")
        json_body = seen_requests[1].data.decode("utf-8")
        self.assertIn('"case_number": "999/26.0SMOKE"', json_body)
        self.assertIn("application/json", seen_requests[1].headers["Content-type"])
        multipart_body = seen_requests[2].data
        self.assertIn(b'filename="synthetic-notification.pdf"', multipart_body)
        self.assertNotIn(b"../synthetic-notification.pdf", multipart_body)
        self.assertIn(b"%PDF synthetic", multipart_body)


    def test_legalpdf_adapter_caller_runs_full_synthetic_sequence(self):
        from scripts.legalpdf_adapter_caller import (
            REQUIRED_ADAPTER_ENDPOINTS,
            AdapterSequenceResult,
            run_synthetic_adapter_sequence_result,
        )

        seen_posts = []
        seen_uploads = []

        def fetch_json(url):
            if url.endswith("/api/health"):
                return self.adapter_health_payload(isolated_synthetic=True)
            if url.endswith("/api/integration/adapter-contract"):
                return {
                    "status": "ready",
                    "recommended_gmail_mode": "manual_handoff",
                    "draft_only": True,
                    "send_allowed": False,
                    "write_allowed": False,
                    "legalpdf_write_allowed": False,
                    "managed_data_changed": False,
                    "gmail_boundary": {"required_tool": "_create_draft", "draft_only": True, "send_allowed": False},
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
            if url.endswith("/api/history"):
                return {"draft_log": [], "duplicates": []}
            raise AssertionError(url)

        def post_json(url, payload):
            seen_posts.append(url)
            if url.endswith("/api/review"):
                intake = dict(payload["intake"])
                self.assertNotIn("closing_date", intake)
                return {
                    "status": "needs_info",
                    "intake": intake,
                    "effective_intake": intake,
                    "questions": [{"number": 1, "field": "closing_date", "question": "Closing date?"}],
                    "question_text": "1. Closing date?",
                    "send_allowed": False,
                }
            if url.endswith("/api/review/apply-answers"):
                intake = dict(payload["intake"])
                self.assertIn("1. 2026-05-04", payload["answers"])
                intake["closing_date"] = "2026-05-04"
                return {
                    "status": "ready",
                    "intake": intake,
                    "effective_intake": intake,
                    "draft_text": "Número de processo: 999/26.0SMOKE\n\nPede deferimento,",
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
                        "send_allowed": False,
                    },
                }
            if url.endswith("/api/prepare"):
                self.assertEqual(payload["preflight_review"]["preflight_review_token"], "preflight-token")
                return {
                    "status": "prepared",
                    "send_allowed": False,
                    "prepared_review": {
                        "manifest": "/tmp/adapter-manifest.json",
                        "prepared_review_token": "prepared-token",
                        "review_fingerprint": "prepared-fingerprint",
                        "payload_paths": ["/tmp/adapter-packet.draft.json"],
                        "send_allowed": False,
                    },
                    "items": [],
                    "packet": {
                        "draft_payload": "/tmp/adapter-packet.draft.json",
                        "gmail_create_draft_ready": True,
                        "gmail_create_draft_args": {"attachment_files": ["/tmp/adapter-packet.pdf"]},
                        "underlying_requests": [{"case_number": "999/26.0SMOKE", "service_date": "2026-05-04"}],
                        "send_allowed": False,
                    },
                }
            if url.endswith("/api/gmail/manual-handoff"):
                if payload["prepared_review_token"] == "stale-prepared-token":
                    return {
                        "status": "blocked",
                        "message": "Prepared review token is stale. Prepare the PDF again from the reviewed request.",
                        "send_allowed": False,
                    }
                return {
                    "status": "ready",
                    "mode": "manual_handoff",
                    "gmail_tool": "_create_draft",
                    "copyable_prompt": "Create a Gmail draft only using `_create_draft`.",
                    "attachment_files": ["/tmp/adapter-packet.pdf"],
                    "send_allowed": False,
                }
            if url.endswith("/api/drafts/record"):
                if payload["prepared_review_token"] == "stale-prepared-token":
                    return {
                        "status": "blocked",
                        "message": "Prepared review token is stale. Prepare the PDF again from the reviewed request.",
                        "send_allowed": False,
                    }
                return {
                    "status": "recorded",
                    "draft_id": "draft-adapter-smoke",
                    "message_id": "message-adapter-smoke",
                    "thread_id": "thread-adapter-smoke",
                    "recorded_duplicate_count": 1,
                    "send_allowed": False,
                }
            raise AssertionError(url)

        def post_multipart(url, fields, filename, content, content_type):
            seen_uploads.append(url)
            self.assertEqual(fields["source_kind"], "notification_pdf")
            self.assertEqual(filename, "synthetic-notification.pdf")
            self.assertEqual(content_type, "application/pdf")
            self.assertTrue(content.startswith(b"%PDF"))
            return {
                "status": "uploaded",
                "send_allowed": False,
                "candidate_intake": {
                    "profile": "example_interpreting",
                    "case_number": "999/26.0SMOKE",
                    "service_date": "2026-05-04",
                    "service_date_source": "document_text",
                    "addressee": "Exmo. Senhor Procurador da República\nExample Court",
                    "payment_entity": "Example Court",
                    "service_entity": "Example Police / Example Police Station",
                    "service_entity_type": "police",
                    "entities_differ": True,
                    "service_place": "Example Police Station",
                    "claim_transport": True,
                    "transport": {"origin": "Example City", "destination": "Example City", "km_one_way": 12},
                    "closing_city": "Example City",
                    "closing_date": "2026-05-09",
                    "recipient_email": "court@example.test",
                    "source_filename": "synthetic-notification.pdf",
                },
                "source_evidence": {
                    "attention": {
                        "status": "ready",
                        "flag_count": 0,
                        "flags": [],
                    },
                },
            }

        result = run_synthetic_adapter_sequence_result(
            "http://public-candidate.test/",
            fetch_json=fetch_json,
            post_json=post_json,
            post_multipart=post_multipart,
            profile="example_interpreting",
            case_number="999/26.0SMOKE",
            service_date="2026-05-04",
        )

        self.assertIsInstance(result, AdapterSequenceResult)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.failure_count, 0)
        self.assertFalse(result.send_allowed)
        self.assertFalse(result.write_allowed)
        self.assertFalse(result.legalpdf_write_allowed)
        summary = result.safe_summary()
        self.assertTrue(summary["isolated_synthetic_runtime"])
        self.assertTrue(summary["prepared_review_bound"])
        self.assertTrue(summary["manual_handoff_ready"])
        self.assertTrue(summary["stale_manual_handoff_blocked"])
        self.assertTrue(summary["stale_record_blocked"])
        self.assertTrue(summary["stale_record_no_local_write"])
        self.assertEqual(summary["recorded_duplicate_count"], 1)
        summary_text = json.dumps(summary, sort_keys=True)
        self.assertNotIn("copyable_prompt", summary_text)
        self.assertNotIn("/tmp/adapter-packet.draft.json", summary_text)

        checks = result.checks
        self.assertTrue(checks, checks)
        self.assertTrue(all(check["status"] == "ready" for check in checks), checks)
        names = {check["name"] for check in checks}
        self.assertIn("adapter_contract_prepared_review_binding", names)
        self.assertIn("adapter_prepare_ready", names)
        self.assertIn("adapter_manual_handoff_rejects_stale_review", names)
        self.assertIn("adapter_record_stale_no_local_write", names)
        self.assertIn("adapter_record_draft", names)
        self.assertIn("http://public-candidate.test/api/sources/upload", seen_uploads)
        self.assertIn("http://public-candidate.test/api/gmail/manual-handoff", seen_posts)
        self.assertIn("http://public-candidate.test/api/drafts/record", seen_posts)
        self.assertNotIn("http://public-candidate.test/api/gmail/drafts/create", seen_posts)


    def test_legalpdf_adapter_caller_runs_sequence_with_caller_supplied_source(self):
        from scripts.legalpdf_adapter_caller import (
            AdapterSourceInput,
            run_adapter_sequence_result,
        )

        seen_posts = []
        seen_uploads = []
        case_number = "321/26.0CALLER"
        service_date = "2026-05-06"

        def fetch_json(url):
            if url.endswith("/api/health"):
                return self.adapter_health_payload(isolated_synthetic=True)
            if url.endswith("/api/integration/adapter-contract"):
                return self.adapter_contract_payload()
            if url.endswith("/api/history"):
                return {"draft_log": [], "duplicates": []}
            raise AssertionError(url)

        def post_json(url, payload):
            seen_posts.append(url)
            if url.endswith("/api/review"):
                intake = dict(payload["intake"])
                self.assertNotIn("closing_date", intake)
                return {
                    "status": "needs_info",
                    "intake": intake,
                    "effective_intake": intake,
                    "questions": [{"number": 1, "field": "closing_date", "question": "Closing date?"}],
                    "question_text": "1. Closing date?",
                    "send_allowed": False,
                }
            if url.endswith("/api/review/apply-answers"):
                intake = dict(payload["intake"])
                self.assertIn(f"1. {service_date}", payload["answers"])
                intake["closing_date"] = service_date
                return {
                    "status": "ready",
                    "intake": intake,
                    "effective_intake": intake,
                    "draft_text": f"Número de processo: {case_number}\n\nPede deferimento,",
                    "send_allowed": False,
                }
            if url.endswith("/api/prepare/preflight"):
                return {
                    "status": "ready",
                    "artifact_effect": "none",
                    "write_allowed": False,
                    "send_allowed": False,
                    "preflight_review": {
                        "review_fingerprint": "caller-preflight-fingerprint",
                        "preflight_review_token": "caller-preflight-token",
                        "send_allowed": False,
                    },
                }
            if url.endswith("/api/prepare"):
                self.assertEqual(payload["preflight_review"]["preflight_review_token"], "caller-preflight-token")
                return {
                    "status": "prepared",
                    "send_allowed": False,
                    "prepared_review": {
                        "manifest": "/tmp/caller-adapter-manifest.json",
                        "prepared_review_token": "caller-prepared-token",
                        "review_fingerprint": "caller-prepared-fingerprint",
                        "payload_paths": ["/tmp/caller-adapter-packet.draft.json"],
                        "send_allowed": False,
                    },
                    "items": [],
                    "packet": {
                        "draft_payload": "/tmp/caller-adapter-packet.draft.json",
                        "gmail_create_draft_ready": True,
                        "gmail_create_draft_args": {"attachment_files": ["/tmp/caller-adapter-packet.pdf"]},
                        "underlying_requests": [{"case_number": case_number, "service_date": service_date}],
                        "send_allowed": False,
                    },
                }
            if url.endswith("/api/gmail/manual-handoff"):
                if payload["prepared_review_token"] == "stale-prepared-token":
                    return {"status": "blocked", "message": "Prepared review token is stale.", "send_allowed": False}
                return {
                    "status": "ready",
                    "mode": "manual_handoff",
                    "gmail_tool": "_create_draft",
                    "copyable_prompt": "Create a Gmail draft only using `_create_draft`.",
                    "attachment_files": ["/tmp/caller-adapter-packet.pdf"],
                    "send_allowed": False,
                }
            if url.endswith("/api/drafts/record"):
                if payload["prepared_review_token"] == "stale-prepared-token":
                    return {"status": "blocked", "message": "Prepared review token is stale.", "send_allowed": False}
                return {
                    "status": "recorded",
                    "draft_id": "draft-adapter-smoke",
                    "message_id": "message-adapter-smoke",
                    "thread_id": "thread-adapter-smoke",
                    "recorded_duplicate_count": 1,
                    "send_allowed": False,
                }
            raise AssertionError(url)

        def post_multipart(url, fields, filename, content, content_type):
            seen_uploads.append((url, dict(fields), filename, content, content_type))
            self.assertEqual(filename, "legalpdf-caller-source.pdf")
            self.assertEqual(content, b"%PDF caller-provided sanitized fixture")
            self.assertEqual(fields["adapter_trace_id"], "caller-smoke")
            return {
                "status": "uploaded",
                "send_allowed": False,
                "candidate_intake": {
                    "profile": "example_interpreting",
                    "case_number": case_number,
                    "service_date": service_date,
                    "addressee": "Exmo. Senhor Procurador da República\nExample Court",
                    "payment_entity": "Example Court",
                    "service_entity": "Example Police / Example Police Station",
                    "service_entity_type": "police",
                    "entities_differ": True,
                    "service_place": "Example Police Station",
                    "claim_transport": True,
                    "transport": {"origin": "Example City", "destination": "Example City", "km_one_way": 12},
                    "closing_city": "Example City",
                    "closing_date": "2026-05-09",
                    "recipient_email": "court@example.test",
                    "source_filename": filename,
                },
                "source_evidence": {"attention": {"status": "ready", "flag_count": 0, "flags": []}},
            }

        result = run_adapter_sequence_result(
            "http://public-candidate.test/",
            fetch_json=fetch_json,
            post_json=post_json,
            post_multipart=post_multipart,
            source=AdapterSourceInput(
                profile="example_interpreting",
                source_kind="notification_pdf",
                filename="../legalpdf-caller-source.pdf",
                content=b"%PDF caller-provided sanitized fixture",
                content_type="application/pdf",
                expected_case_number=case_number,
                expected_service_date=service_date,
                visible_metadata_text="sanitized caller metadata",
                extra_fields={"adapter_trace_id": "caller-smoke"},
            ),
        )

        self.assertEqual(result.status, "ready", result.checks)
        self.assertIn("http://public-candidate.test/api/sources/upload", [item[0] for item in seen_uploads])
        self.assertIn("http://public-candidate.test/api/drafts/record", seen_posts)
        summary_text = json.dumps(result.safe_summary(), sort_keys=True)
        self.assertNotIn("caller-provided sanitized fixture", summary_text)
        self.assertNotIn("legalpdf-caller-source.pdf", summary_text)


    def test_legalpdf_adapter_sequence_stops_before_upload_without_isolated_runtime(self):
        from scripts.legalpdf_adapter_caller import (
            AdapterSourceInput,
            run_adapter_sequence_result,
        )

        seen_uploads = []

        def fetch_json(url):
            if url.endswith("/api/health"):
                return self.adapter_health_payload()
            if url.endswith("/api/integration/adapter-contract"):
                return self.adapter_contract_payload()
            raise AssertionError(url)

        def post_multipart(url, fields, filename, content, content_type):
            seen_uploads.append(url)
            return {"status": "uploaded", "send_allowed": False, "candidate_intake": {}}

        result = run_adapter_sequence_result(
            "http://public-candidate.test/",
            fetch_json=fetch_json,
            post_json=lambda _url, _payload: {},
            post_multipart=post_multipart,
            source=AdapterSourceInput(
                profile="example_interpreting",
                source_kind="notification_pdf",
                filename="caller-source.pdf",
                content=b"%PDF caller source",
                expected_case_number="321/26.0CALLER",
                expected_service_date="2026-05-06",
            ),
        )

        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.safe_summary()["isolated_synthetic_runtime"])
        names = {check["name"] for check in result.checks}
        self.assertIn("adapter_isolated_synthetic_runtime_required", names)
        self.assertNotIn("adapter_source_upload_evidence", names)
        self.assertEqual(seen_uploads, [])


    def test_legalpdf_adapter_synthetic_sequence_stops_before_upload_when_readiness_blocks(self):
        from scripts.legalpdf_adapter_caller import run_synthetic_adapter_sequence

        seen_uploads = []

        def fetch_json(url):
            if url.endswith("/api/health"):
                payload = self.adapter_health_payload()
                payload["write_allowed"] = True
                return payload
            if url.endswith("/api/integration/adapter-contract"):
                return self.adapter_contract_payload()
            raise AssertionError(url)

        def post_multipart(url, fields, filename, content, content_type):
            seen_uploads.append(url)
            raise AssertionError("Synthetic sequence should stop before source upload when readiness blocks.")

        checks = run_synthetic_adapter_sequence(
            "http://public-candidate.test/",
            fetch_json=fetch_json,
            post_json=lambda _url, _payload: {},
            post_multipart=post_multipart,
            profile="example_interpreting",
            case_number="999/26.0SMOKE",
            service_date="2026-05-04",
        )

        names = {check["name"] for check in checks}
        self.assertIn("adapter_health_read_only", names)
        self.assertNotIn("adapter_source_upload_evidence", names)
        self.assertEqual(seen_uploads, [])


    def test_legalpdf_adapter_caller_cli_outputs_guarded_safe_summary(self):
        import scripts.legalpdf_adapter_caller as adapter

        self.assertTrue(hasattr(adapter, "main"), "Adapter caller should expose a CLI main()")
        self.assertTrue(
            hasattr(adapter, "run_synthetic_adapter_sequence_http"),
            "Adapter caller CLI should reuse the HTTP synthetic sequence helper.",
        )
        self.assertTrue(
            hasattr(adapter, "run_adapter_readiness_result"),
            "Adapter caller CLI should expose a read-only readiness probe.",
        )

        class FakeResult:
            status = "ready"

            def safe_summary(self):
                return {
                    "status": "ready",
                    "failure_count": 0,
                    "prepared_review_bound": True,
                    "manual_handoff_ready": True,
                    "send_allowed": False,
                    "write_allowed": False,
                    "legalpdf_write_allowed": False,
                }

        output = StringIO()
        with patch.object(adapter, "run_synthetic_adapter_sequence_http", return_value=FakeResult()) as run_sequence:
            with patch("sys.stdout", output):
                exit_code = adapter.main([
                    "--base-url",
                    "public-candidate.test/",
                    "--timeout",
                    "7.5",
                    "--profile",
                    "example_interpreting",
                    "--case-number",
                    "999/26.0SMOKE",
                    "--service-date",
                    "2026-05-04",
                    "--allow-synthetic-recording",
                ])

        self.assertEqual(exit_code, 0)
        run_sequence.assert_called_once_with(
            "public-candidate.test/",
            timeout=7.5,
            profile="example_interpreting",
            case_number="999/26.0SMOKE",
            service_date="2026-05-04",
        )
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["status"], "ready")
        self.assertTrue(summary["prepared_review_bound"])
        summary_text = json.dumps(summary, sort_keys=True)
        self.assertNotIn("copyable_prompt", summary_text)
        self.assertNotIn("/tmp/adapter-packet.draft.json", summary_text)

        with tempfile.TemporaryDirectory() as tmp:
            source_file = Path(tmp) / "caller-input.pdf"
            source_file.write_bytes(b"%PDF caller source")
            caller_output = StringIO()
            with patch.object(adapter, "run_adapter_sequence_http", return_value=FakeResult()) as run_caller_sequence:
                with patch.object(adapter, "run_synthetic_adapter_sequence_http") as blocked_synthetic:
                    with patch("sys.stdout", caller_output):
                        exit_code = adapter.main([
                            "--base-url",
                            "public-candidate.test/",
                            "--timeout",
                            "7.5",
                            "--profile",
                            "example_interpreting",
                            "--case-number",
                            "321/26.0CALLER",
                            "--service-date",
                            "2026-05-06",
                            "--source-file",
                            str(source_file),
                            "--source-kind",
                            "notification_pdf",
                            "--content-type",
                            "application/pdf",
                            "--visible-metadata-text",
                            "sanitized caller metadata",
                            "--source-field",
                            "adapter_trace_id=cli-smoke",
                            "--allow-synthetic-recording",
                            "--json",
                        ])

        self.assertEqual(exit_code, 0)
        blocked_synthetic.assert_not_called()
        run_caller_sequence.assert_called_once()
        _, caller_kwargs = run_caller_sequence.call_args
        self.assertEqual(caller_kwargs["base_url"], "public-candidate.test/")
        self.assertEqual(caller_kwargs["timeout"], 7.5)
        source = caller_kwargs["source"]
        self.assertIsInstance(source, adapter.AdapterSourceInput)
        self.assertEqual(source.profile, "example_interpreting")
        self.assertEqual(source.source_kind, "notification_pdf")
        self.assertEqual(source.filename, "caller-input.pdf")
        self.assertEqual(source.content, b"%PDF caller source")
        self.assertEqual(source.content_type, "application/pdf")
        self.assertEqual(source.expected_case_number, "321/26.0CALLER")
        self.assertEqual(source.expected_service_date, "2026-05-06")
        self.assertEqual(source.visible_metadata_text, "sanitized caller metadata")
        self.assertEqual(source.extra_fields, {"adapter_trace_id": "cli-smoke"})
        caller_summary = json.loads(caller_output.getvalue())
        self.assertEqual(caller_summary["status"], "ready")
        self.assertNotIn("caller-input.pdf", json.dumps(caller_summary, sort_keys=True))

        with tempfile.TemporaryDirectory() as tmp:
            source_file = Path(tmp) / "caller-input.pdf"
            source_file.write_bytes(b"%PDF caller source")
            with patch.object(adapter, "run_adapter_sequence_http") as blocked_caller_sequence:
                with patch("sys.stderr", StringIO()):
                    with self.assertRaises(SystemExit) as blocked:
                        adapter.main([
                            "--base-url",
                            "public-candidate.test/",
                            "--source-file",
                            str(source_file),
                        ])
        self.assertEqual(blocked.exception.code, 2)
        blocked_caller_sequence.assert_not_called()

        readiness_output = StringIO()
        with patch.object(adapter, "run_adapter_readiness_http", return_value=FakeResult()) as run_readiness:
            with patch.object(adapter, "run_synthetic_adapter_sequence_http") as blocked_sequence:
                with patch("sys.stdout", readiness_output):
                    exit_code = adapter.main([
                        "--base-url",
                        "public-candidate.test/",
                        "--timeout",
                        "7.5",
                        "--readiness-only",
                        "--json",
                    ])

        self.assertEqual(exit_code, 0)
        run_readiness.assert_called_once_with("public-candidate.test/", timeout=7.5)
        blocked_sequence.assert_not_called()
        readiness_summary = json.loads(readiness_output.getvalue())
        self.assertEqual(readiness_summary["status"], "ready")
        self.assertFalse(readiness_summary["send_allowed"])

        with patch.object(adapter, "run_synthetic_adapter_sequence_http") as blocked_run:
            with patch("sys.stderr", StringIO()):
                with self.assertRaises(SystemExit) as blocked:
                    adapter.main(["--base-url", "public-candidate.test/"])
        self.assertEqual(blocked.exception.code, 2)
        blocked_run.assert_not_called()


    def test_local_app_smoke_adapter_contract_wrapper_is_thin(self):
        import scripts.local_app_smoke as smoke

        source = inspect.getsource(smoke._run_adapter_contract_checks)
        self.assertIn("return run_synthetic_adapter_sequence(", source)
        for duplicated_sequence_detail in [
            "LegalPdfAdapterCaller(",
            "_prepared_review_request_fields",
            "stale_prepared_review_fields",
            "adapter_manual_handoff_rejects_stale_review",
            "adapter_record_rejects_stale_review",
        ]:
            self.assertNotIn(duplicated_sequence_detail, source)


    def test_local_app_smoke_reuses_adapter_http_transport(self):
        import scripts.local_app_smoke as smoke

        source = inspect.getsource(smoke)
        for helper in ["fetch_json_http", "post_json_http", "post_multipart_http"]:
            with self.subTest(helper=helper):
                self.assertIn(helper, source)
        self.assertNotIn("def _http_json(", source)
        self.assertNotIn("def _http_post_json(", source)
        self.assertNotIn("def _http_post_multipart(", source)


    def test_adapter_contract_smoke_requires_numbered_review_questions(self):
        self.assertTrue(_adapter_questions_are_numbered(
            [{"number": 1, "field": "closing_date"}],
            "Please answer by number:\n1. Closing date?",
        ))
        self.assertFalse(_adapter_questions_are_numbered(
            [{"field": "closing_date"}],
            "Please answer by number:\n1. Closing date?",
        ))
        self.assertFalse(_adapter_questions_are_numbered(
            [{"number": 1, "field": "closing_date"}],
            "Closing date?",
        ))
