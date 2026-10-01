import json
import subprocess
import sys
import tempfile
import urllib.error
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.web import create_app
from scripts.local_app_smoke import _post_expected_blocked_json, _synthetic_notification_pdf, run_smoke
from scripts.legalpdf_adapter_caller import synthetic_notification_pdf as adapter_notification_pdf


from test_public_candidate_smoke import PublicCandidateSmokeTests


class LocalBrowserBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-browser-boundary-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.app = create_app(**runtime_path_overrides(self.root))
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8765')
        self.addCleanup(self.client.close)
        network = patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('Boundary tests stay offline.'))
        network.start()
        self.addCleanup(network.stop)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}

    def test_loopback_addresses_and_matching_origins_keep_normal_actions_available(self):
        for base, origin in (
            ('http://127.0.0.1:8765', 'http://127.0.0.1:8765'),
            ('http://localhost:8765', 'http://LOCALHOST:8765'),
            ('http://[::1]:8765', 'http://[::1]:8765'),
            ('http://[0:0:0:0:0:0:0:1]:8765', 'http://[::1]:8765'),
            ('http://localhost', 'http://localhost:80'),
            ('https://localhost', 'https://localhost:443'),
        ):
            # The pinned TestClient transport cannot parse IPv6 URL authorities;
            # exercise the actual IPv6 Host/Origin headers through its IPv4 URL.
            client_base = 'http://127.0.0.1:8765' if '[' in base else base
            headers = {'Host': base.split('://', 1)[1], 'Origin': origin}
            with self.subTest(base=base), TestClient(self.app, base_url=client_base) as client:
                self.assertEqual(client.get('/api/health', headers=headers).status_code, 200)
                response = client.post('/api/backup/export', headers=headers)
                self.assertEqual(response.status_code, 200, response.text)

    def test_foreign_or_malformed_host_cannot_read_or_change_app_data(self):
        before = self.snapshot()
        for host in ('attacker.invalid:8765', '127.0.0.1.attacker.invalid', 'localhost.attacker.invalid',
                     '127.0.0.1@attacker.invalid', 'attacker.invalid@127.0.0.1', '127.0.0.1:bad',
                     '127.0.0.1:8765/path', '127.0.0.1:8765?query', '127.0.0.1:8765#fragment',
                     '127.0.0.1:8765?', '127.0.0.1:8765#',
                     '127.0.0.1:8765, attacker.invalid', '[::1]:99999', '127.0.0.1:', '0.0.0.0:8765'):
            with self.subTest(host=host):
                self.assertEqual(self.client.get('/api/reference', headers={'Host': host}).status_code, 400)
                self.assertEqual(self.client.post('/api/backup/export', headers={'Host': host}).status_code, 400)
        duplicate_host = [('Host', '127.0.0.1:8765'), ('Host', 'attacker.invalid')]
        self.assertEqual(self.client.get('/api/reference', headers=duplicate_host).status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_origin_simple_form_json_and_multipart_stop_before_writes(self):
        before = self.snapshot()
        headers = {'Origin': 'https://attacker.invalid'}
        requests = (
            ('/api/backup/export', {'content': b'', 'headers': headers}),
            ('/api/backup/export', {'data': {'unrelated': 'value'}, 'headers': headers}),
            ('/api/backup/export', {'json': {}, 'headers': headers}),
            ('/api/attachments/upload', {'files': {'file': ('fictional.pdf', b'%PDF-1.4\n', 'application/pdf')}, 'headers': headers}),
        )
        for route, options in requests:
            with self.subTest(route=route, payload_type=list(options)[0]):
                self.assertEqual(self.client.post(route, **options).status_code, 403)
                self.assertEqual(self.snapshot(), before)

    def test_origin_requires_exact_scheme_host_and_effective_port(self):
        before = self.snapshot()
        for origin in ('null', '', 'http://localhost:8765', 'https://127.0.0.1:8765',
                       'http://127.0.0.1:8766', 'http://127.0.0.1', 'http://127.0.0.1:8765/path',
                       'http://user@127.0.0.1:8765', 'http://127.0.0.1:8765 https://attacker.invalid'):
            with self.subTest(origin=origin):
                self.assertEqual(self.client.post('/api/backup/export', headers={'Origin': origin}).status_code, 403)
        duplicate = [('Origin', 'http://127.0.0.1:8765'), ('Origin', 'https://attacker.invalid')]
        self.assertEqual(self.client.post('/api/backup/export', headers=duplicate).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_no_origin_cli_works_but_cross_site_fetch_metadata_is_rejected(self):
        before = self.snapshot()
        response = self.client.post('/api/backup/export', headers={'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.post('/api/backup/export').status_code, 200)
        self.assertNotEqual(self.snapshot(), before)

    def test_cross_site_oauth_get_callback_keeps_existing_state_validation(self):
        before = self.snapshot()
        for provider in ('gmail', 'google-photos'):
            callback_name = 'gmail_api_oauth_callback' if provider == 'gmail' else 'google_photos_oauth_callback'
            with self.subTest(provider=provider), patch('honorarios_app.web.' + callback_name, return_value={'status': 'connected'}) as callback:
                response = self.client.get(f'/api/{provider}/oauth/callback?code=fictional-code&state=fictional-state',
                                           headers={'Origin': 'https://accounts.google.com', 'Sec-Fetch-Site': 'cross-site'})
                self.assertEqual(response.status_code, 200)
                callback.assert_called_once_with(code='fictional-code', state='fictional-state', paths=self.app.state.paths)
        self.assertEqual(self.snapshot(), before)


class PublicRuntimeTests(PublicCandidateSmokeTests):
    def test_health_endpoint_is_read_only_and_secret_free(self):
        client = self.make_client()
        project_root = Path(__file__).resolve().parents[1]

        response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        dumped = json.dumps(data, sort_keys=True)
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["app"], "LegalPDF Honorários")
        self.assertFalse(data["send_allowed"])
        self.assertFalse(data["write_allowed"])
        self.assertFalse(data["managed_data_changed"])
        self.assertIn("timestamp", data)
        for forbidden in [
            "client_secret",
            "access_token",
            "refresh_token",
            "draft-",
            "C:\\",
            str(project_root),
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dumped)
        self.assertFalse(data["isolated_runtime"])
        self.assertFalse(data["synthetic_runtime"])
        self.assertEqual(data["runtime"]["mode"], "local")


    def test_health_endpoint_attests_synthetic_isolated_runtime_without_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            create_synthetic_runtime(runtime_root, seed_active_draft=True)
            client = TestClient(create_app(**runtime_path_overrides(runtime_root)), base_url='http://127.0.0.1')

            response = client.get("/api/health")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            dumped = json.dumps(data, sort_keys=True)
            self.assertTrue(data["isolated_runtime"])
            self.assertTrue(data["synthetic_runtime"])
            self.assertEqual(data["runtime"]["mode"], "synthetic_isolated")
            self.assertEqual(data["runtime"]["attestation"], "honorarios_synthetic_runtime_v1")
            self.assertFalse(data["send_allowed"])
            self.assertFalse(data["write_allowed"])
            self.assertFalse(data["managed_data_changed"])
            self.assertNotIn(str(runtime_root), dumped)
            self.assertNotIn("C:\\", dumped)


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
        self.assertIn("runtime_doctor", keys)
        self.assertIn("isolated_supporting_attachment_smoke", keys)
        self.assertIn("isolated_source_upload_smoke", keys)
        self.assertIn("legalpdf_adapter_readiness", keys)
        self.assertIn("isolated_adapter_contract_smoke", keys)
        self.assertIn("isolated_gmail_api_smoke", keys)
        self.assertIn("browser_iab_smoke", keys)
        self.assertIn("browser_iab_upload_smoke", keys)
        self.assertIn("browser_iab_supporting_attachment_smoke", keys)
        self.assertIn("browser_iab_answer_apply_smoke", keys)
        self.assertIn("browser_iab_supporting_attachment_stale_smoke", keys)
        self.assertIn("browser_iab_record_helper_smoke", keys)
        self.assertIn("python_browser_record_helper_smoke", keys)
        self.assertIn("browser_iab_profile_proposal_smoke", keys)
        self.assertIn("browser_iab_recent_work_lifecycle_smoke", keys)
        self.assertIn("browser_iab_recent_work_reconciliation_smoke", keys)
        self.assertIn("browser_iab_manual_handoff_stale_smoke", keys)
        self.assertIn("browser_iab_gmail_api_smoke", keys)
        isolated_attachment = next(check for check in data["checks"] if check["key"] == "isolated_supporting_attachment_smoke")
        self.assertIn("scripts/isolated_app_smoke.py", isolated_attachment["command_template"])
        self.assertIn("--supporting-attachment-checks", isolated_attachment["command_template"])
        self.assertEqual(isolated_attachment["writes"], "temporary synthetic runtime only")
        runtime_doctor = next(check for check in data["checks"] if check["key"] == "runtime_doctor")
        self.assertIn("Python runtime doctor", runtime_doctor["label"])
        self.assertIn("scripts/runtime_doctor.py", runtime_doctor["command_template"])
        self.assertIn("--json", runtime_doctor["command_template"])
        self.assertEqual(runtime_doctor["writes"], "none")
        adapter_readiness = next(check for check in data["checks"] if check["key"] == "legalpdf_adapter_readiness")
        self.assertIn("scripts/legalpdf_adapter_caller.py", adapter_readiness["command_template"])
        self.assertIn("--readiness-only", adapter_readiness["command_template"])
        self.assertEqual(adapter_readiness["writes"], "none")
        isolated_adapter = next(check for check in data["checks"] if check["key"] == "isolated_adapter_contract_smoke")
        self.assertIn("--adapter-contract-checks", isolated_adapter["command_template"])
        self.assertIn("source upload", isolated_adapter["description"].lower())
        self.assertIn("numbered", isolated_adapter["description"].lower())
        self.assertIn("stale", isolated_adapter["description"].lower())
        self.assertIn("Manual Draft Handoff", isolated_adapter["description"])
        self.assertEqual(isolated_adapter["writes"], "temporary synthetic runtime only")
        isolated_gmail = next(check for check in data["checks"] if check["key"] == "isolated_gmail_api_smoke")
        self.assertIn("--gmail-api-checks", isolated_gmail["command_template"])
        self.assertIn("fake Gmail", isolated_gmail["description"])
        self.assertEqual(isolated_gmail["writes"], "temporary synthetic runtime only")
        browser_upload = next(check for check in data["checks"] if check["key"] == "browser_iab_upload_smoke")
        self.assertIn("--browser-upload-photo", browser_upload["command_template"])
        self.assertIn("--browser-upload-pdf", browser_upload["command_template"])
        self.assertEqual(browser_upload["writes"], "synthetic source-preview artifacts only")
        browser_review = next(check for check in data["checks"] if check["key"] == "browser_iab_smoke")
        self.assertIn("--browser-iab-click-through", browser_review["command_template"])
        self.assertEqual(browser_review["writes"], "none")
        browser_supporting = next(check for check in data["checks"] if check["key"] == "browser_iab_supporting_attachment_smoke")
        self.assertIn("--browser-upload-supporting-attachment", browser_supporting["command_template"])
        self.assertEqual(browser_supporting["writes"], "synthetic supporting-attachment artifact only")
        browser_answer_apply = next(check for check in data["checks"] if check["key"] == "browser_iab_answer_apply_smoke")
        self.assertIn("scripts/isolated_app_smoke.py", browser_answer_apply["command_template"])
        self.assertIn("--browser-iab-click-through", browser_answer_apply["command_template"])
        self.assertIn("--browser-answer-questions", browser_answer_apply["command_template"])
        self.assertIn("--browser-apply-history", browser_answer_apply["command_template"])
        self.assertIn("numbered", browser_answer_apply["description"].lower())
        self.assertIn("Apply History", browser_answer_apply["description"])
        self.assertEqual(browser_answer_apply["writes"], "temporary synthetic runtime only")
        browser_supporting_stale = next(check for check in data["checks"] if check["key"] == "browser_iab_supporting_attachment_stale_smoke")
        self.assertIn("--browser-supporting-attachment-stale", browser_supporting_stale["command_template"])
        self.assertIn("Supporting proof", browser_supporting_stale["description"])
        self.assertEqual(browser_supporting_stale["writes"], "temporary synthetic runtime only")
        browser_record_helper = next(check for check in data["checks"] if check["key"] == "browser_iab_record_helper_smoke")
        self.assertIn("--browser-record-helper", browser_record_helper["command_template"])
        self.assertIn("--browser-prepare-replacement", browser_record_helper["command_template"])
        self.assertIn("checklist", browser_record_helper["description"].lower())
        self.assertEqual(browser_record_helper["writes"], "temporary synthetic runtime only")
        python_record_helper = next(check for check in data["checks"] if check["key"] == "python_browser_record_helper_smoke")
        self.assertIn("--browser-click-through", python_record_helper["command_template"])
        self.assertNotIn("--browser-iab-click-through", python_record_helper["command_template"])
        self.assertIn("--browser-prepare-replacement", python_record_helper["command_template"])
        self.assertIn("--browser-record-helper", python_record_helper["command_template"])
        self.assertIn("Python Playwright", python_record_helper["description"])
        self.assertEqual(python_record_helper["writes"], "temporary synthetic runtime only")
        browser_profile_proposal = next(check for check in data["checks"] if check["key"] == "browser_iab_profile_proposal_smoke")
        self.assertIn("--browser-profile-proposal", browser_profile_proposal["command_template"])
        self.assertEqual(browser_profile_proposal["writes"], "none")
        browser_recent_work = next(check for check in data["checks"] if check["key"] == "browser_iab_recent_work_lifecycle_smoke")
        self.assertIn("--browser-recent-work-lifecycle", browser_recent_work["command_template"])
        self.assertIn("Recent Work", browser_recent_work["description"])
        self.assertEqual(browser_recent_work["writes"], "temporary synthetic runtime only")
        browser_recent_work_reconciliation = next(check for check in data["checks"] if check["key"] == "browser_iab_recent_work_reconciliation_smoke")
        self.assertIn("--browser-recent-work-reconciliation", browser_recent_work_reconciliation["command_template"])
        self.assertIn("users.drafts.get", browser_recent_work_reconciliation["description"])
        self.assertIn("not_found", browser_recent_work_reconciliation["description"])
        self.assertEqual(browser_recent_work_reconciliation["writes"], "temporary synthetic runtime only")
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
        self.assert_diagnostic_command_templates_are_parseable(data)


    def test_runtime_doctor_reports_python_and_dependencies_without_paths(self):
        from scripts.runtime_doctor import REQUIRED_RUNTIME_MODULES, run_runtime_doctor

        module_names = {item["module"] for item in REQUIRED_RUNTIME_MODULES}

        def fake_find_spec(module_name):
            return object() if module_name in module_names else None

        private_root = "C:" + "\\Users\\FA507"
        result = run_runtime_doctor(
            find_spec=fake_find_spec,
            version_info=(3, 11, 5),
            executable=private_root + "\\secret-project\\.venv\\Scripts\\python.exe",
        )

        self.assertEqual(result.status, "ready")
        self.assertTrue(result.python_ready)
        self.assertFalse(result.send_allowed)
        self.assertFalse(result.write_allowed)
        self.assertFalse(result.managed_data_changed)
        summary = result.safe_summary()
        self.assertEqual(summary["status"], "ready")
        self.assertEqual(summary["python_executable"], "python.exe")
        self.assertEqual(summary["missing_modules"], [])
        summary_text = json.dumps(summary, sort_keys=True)
        for secretish in [
            private_root,
            "secret-project",
            "access_token",
            "refresh_token",
            "client_secret",
            "sk-",
            "draft-",
            "gmail",
            "source_text",
        ]:
            with self.subTest(secretish=secretish):
                self.assertNotIn(secretish, summary_text)


    def test_runtime_doctor_blocks_missing_dependency(self):
        from scripts.runtime_doctor import run_runtime_doctor

        def fake_find_spec(module_name):
            return None if module_name == "fastapi" else object()

        result = run_runtime_doctor(
            find_spec=fake_find_spec,
            version_info=(3, 11, 5),
            executable="python.exe",
        )

        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.modules_ready)
        self.assertIn("fastapi", result.missing_modules)
        self.assertIn("runtime_module_fastapi", {check["name"] for check in result.checks})
        self.assertFalse(result.safe_summary()["module_ready"])


    def test_runtime_doctor_cli_outputs_secret_free_json(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "scripts" / "runtime_doctor.py"), "--json"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        data = json.loads(completed.stdout)
        self.assertIn(data["status"], {"ready", "blocked"})
        self.assertEqual(completed.returncode, 0 if data["status"] == "ready" else 1, completed.stderr)
        self.assertFalse(data["send_allowed"])
        self.assertFalse(data["write_allowed"])
        self.assertFalse(data["managed_data_changed"])
        dumped = json.dumps(data, sort_keys=True)
        self.assertNotIn("C:\\Users\\FA507", dumped)
        self.assertNotIn("_send_email", dumped)
        self.assertNotIn("_send_draft", dumped)


    def test_prepare_requires_current_preflight_review_before_artifacts(self):
        client = self.make_client()
        project_root = Path(__file__).resolve().parents[1]
        intake = json.loads((project_root / "examples" / "intake.synthetic.example.json").read_text(encoding="utf-8"))
        intake.pop("recipient_email", None)

        missing = client.post("/api/prepare", json={"intakes": [intake], "render_previews": False})

        preflight = client.post("/api/prepare/preflight", json={"intakes": [intake], "packet_mode": False}).json()
        stale_review = dict(preflight["preflight_review"])
        stale_review["preflight_review_token"] = "stale-token"
        stale = client.post("/api/prepare", json={
            "intakes": [intake],
            "render_previews": False,
            "preflight_review": stale_review,
        })
        current = client.post("/api/prepare", json={
            "intakes": [intake],
            "render_previews": False,
            "preflight_review": preflight["preflight_review"],
        })

        self.assertEqual(missing.status_code, 400)
        self.assertIn("preflight", missing.json()["message"].lower())
        self.assertEqual(stale.status_code, 400)
        self.assertIn("stale", stale.json()["message"].lower())
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["status"], "prepared")


    def test_public_readiness_endpoint_reports_tracked_gate(self):
        client = self.make_client()
        response = client.get("/api/public-readiness")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["public_repo_ready"], data)
        self.assertTrue(data["tracked_gate"]["public_repo_ready"], data)
        self.assertIn("workspace_gate", data)
        self.assertFalse(data["send_allowed"])
        dumped = json.dumps(data, sort_keys=True)
        self.assertNotIn("C:\\Users", dumped)
        self.assertNotIn("GOCSPX", dumped)
        self.assertNotIn("ya29.", dumped)
        for gate in [data["tracked_gate"], data["workspace_gate"]]:
            self.assertEqual(gate["root"], "project-root")
            for finding in gate.get("content_findings", []):
                self.assertEqual(finding.get("match_preview"), "[redacted]")


    def test_reference_endpoint_keeps_draft_only_contract(self):
        client = self.make_client()
        response = client.get("/api/reference")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["gmail"]["tool"], "_create_draft")
        self.assertFalse(data["gmail"]["send_allowed"])
        self.assertIn("example_interpreting", data["service_profiles"])


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
            "_openai_image_mime_type",
            "mimetypes.guess_type",
            "data:{mime};base64",
            "image/png",
            "image/webp",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, ai_recovery)
        self.assertNotIn("_send_email", ai_recovery)
        self.assertNotIn("_send_draft", ai_recovery)


    def test_local_app_smoke_runner_can_check_public_candidate_contract(self):
        client = self.make_client()

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            if path == "/api/health":
                return self.adapter_health_payload()
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


    def test_local_app_smoke_blocks_public_readiness_secret_previews(self):
        client = self.make_client()

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            if path == "/api/public-readiness":
                return {
                    "status": "ready",
                    "public_ready": True,
                    "send_allowed": False,
                    "tracked_gate": {
                        "status": "ready",
                        "public_repo_ready": True,
                        "send_allowed": False,
                        "root": "C:" + "\\Users\\FA507\\private-project",
                        "content_findings": [{
                            "kind": "google_client_secret",
                            "path": "config/gmail.local.json",
                            "line": 3,
                            "match_preview": "GOCSPX" + "-private-client-secret",
                        }],
                    },
                    "workspace_gate": {
                        "status": "blocked",
                        "public_ready": False,
                        "send_allowed": False,
                        "root": "project-root",
                        "content_findings": [],
                    },
                }
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
        )
        public_check = next(check for check in report["checks"] if check["name"] == "public_readiness_secret_free")
        self.assertEqual(report["status"], "blocked", report)
        self.assertEqual(public_check["status"], "blocked")
        self.assertIn("$.tracked_gate.root", public_check["details"]["exposed_paths"])
        self.assertIn("$.tracked_gate.content_findings[0].match_preview", public_check["details"]["exposed_paths"])


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
                    "preflight_review": {
                        "review_fingerprint": "preflight-fingerprint",
                        "preflight_review_token": "preflight-token",
                    },
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
                self.assertEqual(payload["preflight_review"]["preflight_review_token"], "preflight-token")
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


    def test_local_app_smoke_expected_blocked_helper_parses_http_400_json(self):
        def post_json(url, payload):
            body = json.dumps({
                "status": "blocked",
                "message": "Prepared review token is stale.",
                "send_allowed": False,
            }).encode("utf-8")
            raise urllib.error.HTTPError(url, 400, "Bad Request", {}, BytesIO(body))

        payload, error = _post_expected_blocked_json(
            post_json,
            "http://public-candidate.test/api/drafts/record",
            {"prepared_review_token": "stale-prepared-token"},
            "blocked_helper",
        )

        self.assertIsNone(error)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["send_allowed"])


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
        self.assertTrue(all(item[1]['ai_recovery'] == 'off' for item in seen_uploads))

    def test_synthetic_pdf_smoke_fixture_recovers_without_rendering_or_provider(self):
        client = self.make_client()
        for fixture in (_synthetic_notification_pdf, adapter_notification_pdf):
            with self.subTest(fixture=fixture.__module__), \
                 patch('honorarios_app.services.render_pdf_pages_for_source', side_effect=AssertionError('Clear smoke fixture must not need rendering')), \
                 patch('honorarios_app.ai_recovery.OpenAI', side_effect=AssertionError('Synthetic smoke cannot call a provider')) as provider:
                response = client.post('/api/sources/upload',
                    files={'file': ('fictional-smoke.pdf', fixture('999/26.0SMOKE', '2026-05-04'), 'application/pdf')},
                    data={'source_kind': 'notification_pdf', 'profile': 'example_interpreting', 'ai_recovery': 'off'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['candidate_intake']['case_number'], '999/26.0SMOKE')
                self.assertEqual(response.json()['candidate_intake']['service_date'], '2026-05-04')
                provider.assert_not_called()


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


    def test_local_app_smoke_blocks_iab_report_without_tab_cleanup(self):
        client = self.make_client()

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def browser_runner(_base_url, **_kwargs):
            return {
                "status": "ready",
                "checks": [{"name": "browser_iab_runtime", "status": "ready", "message": "ok", "details": {}}],
                "failure_count": 0,
                "send_allowed": False,
            }

        report = run_smoke(
            "http://public-candidate.test/",
            fetch_text=fetch_text,
            fetch_json=fetch_json,
            browser_click_through=True,
            browser_iab_click_through=True,
            browser_runner=browser_runner,
        )

        self.assertEqual(report["status"], "blocked", report)
        cleanup = next(check for check in report["checks"] if check["name"] == "browser_tab_cleanup")
        self.assertEqual(cleanup["status"], "blocked")
        self.assertIn("did not report", cleanup["message"])


    def test_local_app_smoke_raw_iab_handoff_reports_no_tab_cleanup(self):
        root = Path(__file__).resolve().parents[1]
        smoke_source = (root / "scripts" / "local_app_smoke.py").read_text(encoding="utf-8")
        raw_handoff_block = smoke_source.split('if os.environ.get("HONORARIOS_ALLOW_IAB_SUBPROCESS") != "1":', 1)[1].split("cmd = [", 1)[0]

        self.assertIn('"browser_iab_runtime"', raw_handoff_block)
        self.assertIn("node_repl_cell", raw_handoff_block)
        self.assertIn('"browser_tab_cleanup"', raw_handoff_block)
        self.assertIn("Browser/IAB did not create a disposable tab before stopping.", raw_handoff_block)
        self.assertIn('"cleanup_mode": "none"', raw_handoff_block)
        self.assertIn('"reason": "raw_subprocess_skipped"', raw_handoff_block)
        self.assertIn('"failure_count": 1', raw_handoff_block)


    def test_local_app_smoke_forwards_supporting_attachment_stale_to_python_runner(self):
        root = Path(__file__).resolve().parents[1]
        smoke_source = (root / "scripts" / "local_app_smoke.py").read_text(encoding="utf-8")
        python_runner_block = smoke_source.split("browser_report = run_browser_flow_smoke(", 1)[1].split(")", 1)[0]

        self.assertIn("supporting_attachment_stale=browser_supporting_attachment_stale", python_runner_block)
        self.assertNotIn("--browser-supporting-attachment-stale requires --browser-iab-click-through", smoke_source)


    def test_local_app_smoke_requires_full_diagnostics_command_set(self):
        root = Path(__file__).resolve().parents[1]
        smoke_source = (root / "scripts" / "local_app_smoke.py").read_text(encoding="utf-8")
        required_block = smoke_source.split("required_keys = {", 1)[1].split("}", 1)[0]
        for key in [
            "isolated_source_upload_smoke",
            "runtime_doctor",
            "browser_iab_smoke",
            "browser_iab_answer_apply_smoke",
            "browser_iab_record_helper_smoke",
            "python_browser_record_helper_smoke",
            "browser_iab_recent_work_reconciliation_smoke",
        ]:
            with self.subTest(key=key):
                self.assertIn(key, required_block)


    def test_local_app_default_port_is_consistent_across_public_guidance(self):
        root = Path(__file__).resolve().parents[1]
        default_base = "http://127.0.0.1:8765"
        stale_base = "http://127.0.0.1:" + "8766"
        checks = {
            "README.md": ["scripts/start_dev.ps1", "http://127.0.0.1:8878", "default remains `8765`"],
            "config/gmail.example.json": [f"{default_base}/api/gmail/oauth/callback"],
            "config/google-photos.example.json": [f"{default_base}/api/google-photos/oauth/callback"],
            "docs/next-thread-handoff.md": ["--port 8765", default_base],
            "docs/legalpdf-adapter-contract.md": [default_base],
            "docs/process-optimizations.md": [default_base],
            "honorarios_app/gmail_draft_api.py": [f"{default_base}/api/gmail/oauth/callback"],
            "honorarios_app/runtime.py": [f"{default_base}/api/gmail/oauth/callback"],
            "honorarios_app/services.py": [f"{default_base}/api/google-photos/oauth/callback"],
            "honorarios_app/static/app.js": [f"{default_base}/api/gmail/oauth/callback"],
            "honorarios_app/templates/index.html": [f"{default_base}/api/gmail/oauth/callback"],
            "scripts/browser_flow_smoke.py": [f'default="{default_base}"'],
            "scripts/browser_iab_smoke.mjs": [f'baseUrl: "{default_base}"', f"--base-url {default_base}"],
            "scripts/build_public_candidate.py": [f"{default_base}/api/gmail/oauth/callback", f"{default_base}/api/google-photos/oauth/callback"],
            "scripts/legalpdf_adapter_caller.py": [f'default="{default_base}"'],
            "scripts/local_app_smoke.py": [f'default="{default_base}"'],
        }

        for relative_path, expected_fragments in checks.items():
            with self.subTest(path=relative_path):
                text = (root / relative_path).read_text(encoding="utf-8")
                self.assertNotIn(stale_base, text)
                for fragment in expected_fragments:
                    self.assertIn(fragment, text)


    def test_public_repo_hook_readiness_command_is_documented(self):
        root = Path(__file__).resolve().parents[1]
        gate_source = (root / "scripts" / "public_repo_gate.py").read_text(encoding="utf-8")
        self.assertIn("analyze_hook_config", gate_source)
        self.assertIn("--hook-configured", gate_source)

        for relative_path in [
            "README.md",
            "docs/public-release-checklist.md",
            "docs/web-app-roadmap.md",
            "docs/next-thread-handoff.md",
        ]:
            with self.subTest(path=relative_path):
                text = (root / relative_path).read_text(encoding="utf-8")
                self.assertIn("python scripts/public_repo_gate.py --hook-configured --json", text)
