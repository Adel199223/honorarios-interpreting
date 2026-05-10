from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_pdf import ROOT
from scripts.public_release_gate import analyze_public_readiness
from scripts.public_repo_gate import analyze_tracked


COPY_DIRS = [
    ".circleci",
    ".github",
    "docs",
    "honorarios_app",
    "scripts",
    "templates",
]
COPY_FILES = [
    ".gitignore",
    "pyproject.toml",
    "README.md",
    "requirements.txt",
]
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".mjs", ".py", ".toml", ".txt", ".yml", ".yaml"}
SANITIZERS = [
    (re.compile(r"\b[A-Z0-9._%+\-]+@tribunais\.org\.pt\b", re.IGNORECASE), "court@example.test"),
    (re.compile(r"\bPT\d{23}\b", re.IGNORECASE), "EXAMPLE_IBAN"),
    (re.compile(r"\bAdel\s+Belghali\b", re.IGNORECASE), "Example Interpreter"),
    (re.compile(r"Rua\s+Lu[íi]s\s+de\s+Cam[õo]es\s+n[ºo.]?\s*6,\s*7960-011\s*Marmelar,\s*Pedr[óo]g[ãa]o,\s*Vidigueira", re.IGNORECASE), "Example Street 1, 1000-000 Example City"),
    (re.compile(r"C:[\\/]+Users[\\/]+FA507[^\s\"'`<>]+", re.IGNORECASE), "%USERPROFILE%/example-path"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{8,}\b"), "sk-example"),
    (re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{8,}\b"), "GOCSPX-example"),
]


def _ensure_safe_target(source_root: Path, target_root: Path) -> None:
    source = source_root.resolve()
    target = target_root.resolve()
    if source == target:
        raise ValueError("Public candidate target cannot be the project root.")
    try:
        source.relative_to(target)
    except ValueError:
        pass
    else:
        raise ValueError("Public candidate target cannot contain the source project root.")


def sanitize_text(text: str) -> str:
    sanitized = text
    for pattern, replacement in SANITIZERS:
        sanitized = pattern.sub(lambda _match, value=replacement: value, sanitized)
    return sanitized


def _copy_and_sanitize_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in TEXT_SUFFIXES:
        target.write_text(sanitize_text(source.read_text(encoding="utf-8", errors="ignore")), encoding="utf-8")
    else:
        shutil.copy2(source, target)


def _copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    for path in source.rglob("*"):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
            continue
        relative = path.relative_to(source)
        _copy_and_sanitize_file(path, target / relative)


def _reset_target(target: Path) -> None:
    if not target.exists():
        target.mkdir(parents=True)
        return
    if not (target / ".git").exists():
        shutil.rmtree(target)
        target.mkdir(parents=True)
        return

    for child in target.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _git_run(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _candidate_tracked_gate(target: Path) -> dict[str, Any] | None:
    if not (target / ".git").exists():
        return None
    probe = _git_run(target, ["rev-parse", "--is-inside-work-tree"])
    if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
        return None

    refresh = _git_run(target, ["add", "-A"])
    if refresh.returncode != 0:
        message = refresh.stderr.strip() or refresh.stdout.strip() or "Unable to refresh candidate Git index."
        return {
            "status": "blocked",
            "public_repo_ready": False,
            "mode": "tracked",
            "root": str(target),
            "errors": [message],
            "scanned_count": 0,
            "scanned_paths": [],
            "path_blockers": [],
            "content_findings": [],
            "blocker_count": 1,
            "message": "Public candidate Git index refresh failed.",
            "send_allowed": False,
        }
    return analyze_tracked(target)


def _merge_candidate_gates(
    workspace_gate: dict[str, Any],
    tracked_gate: dict[str, Any] | None,
) -> dict[str, Any]:
    if tracked_gate is None:
        return workspace_gate

    combined = dict(workspace_gate)
    combined["tracked_gate"] = tracked_gate
    tracked_ready = bool(tracked_gate.get("public_repo_ready"))
    workspace_ready = bool(workspace_gate.get("public_ready"))
    combined["public_ready"] = workspace_ready and tracked_ready
    combined["status"] = "ready" if combined["public_ready"] else "blocked"
    combined["blocker_count"] = int(workspace_gate.get("blocker_count", 0)) + int(tracked_gate.get("blocker_count", 0))
    if not combined["public_ready"]:
        combined["message"] = (
            "Public candidate build is blocked until both the working tree and preserved Git index pass privacy gates."
        )
    return combined


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_synthetic_runtime_files(target_root: Path) -> None:
    _write_json(target_root / "config" / "profile.example.json", {
        "applicant_name": "Example Interpreter",
        "address": "Example Street 1, 1000-000 Example City",
        "default_origin": "Example City",
        "iban": "EXAMPLE_IBAN",
        "vat_irs_phrase": "Este serviço inclui a taxa de IVA de 23% e não está sujeito a retenção de IRS.",
        "payment_phrase": "O pagamento deverá ser efetuado para o seguinte IBAN:",
        "default_closing_city": "Example City",
        "default_closing_phrase": "Pede deferimento,",
        "signature_label": "O Requerente,",
        "signature_name": "Example Interpreter",
    })
    _write_json(target_root / "config" / "profiles.example.json", {
        "schema_version": 1,
        "primary_profile_id": "primary",
        "profiles": [{
            "id": "primary",
            "first_name": "Example",
            "last_name": "Interpreter",
            "document_name_override": "Example Interpreter",
            "email": "interpreter@example.test",
            "phone_number": "",
            "postal_address": "Example Street 1, 1000-000 Example City",
            "iban": "EXAMPLE_IBAN",
            "iva_text": "23%",
            "irs_text": "Sem retenção",
            "travel_origin_label": "Example City",
            "travel_distances_by_city": {
                "Example City": 12,
            },
        }],
    })
    _write_json(target_root / "config" / "email.example.json", {
        "default_to": "court@example.test",
        "subject": "Requerimento de honorários",
        "body": "Bom dia,\n\nVenho por este meio requerer o pagamento dos honorários devidos.\n\nPoderão encontrar o requerimento em anexo.\n\nMelhores cumprimentos,\n\nExample Interpreter",
        "draft_only": True,
        "allowed_gmail_tool": "_create_draft",
        "forbidden_gmail_tools": ["_send_email", "_send_draft"],
    })
    _write_json(target_root / "config" / "google-photos.example.json", {
        "client_id": "example-client-id.apps.googleusercontent.com",
        "client_secret": "example-client-secret",
        "redirect_uri": "http://127.0.0.1:8766/api/google-photos/oauth/callback",
        "token_path": "config/google-photos-token.local.json",
        "notes": "Copy to config/google-photos.local.json for private local use. Do not commit real credentials or tokens.",
    })
    _write_json(target_root / "config" / "gmail.example.json", {
        "client_id": "example-client-id.apps.googleusercontent.com",
        "client_secret": "example-client-secret",
        "redirect_uri": "http://127.0.0.1:8766/api/gmail/oauth/callback",
        "token_path": "config/gmail-token.local.json",
        "notes": "Copy to config/gmail.local.json for private local use. Do not commit real credentials or OAuth tokens.",
    })
    _write_json(target_root / "data" / "court-emails.example.json", [{
        "key": "example-court",
        "name": "Example Court",
        "email": "court@example.test",
        "payment_entity_aliases": ["Example Court", "Example Ministério Público"],
        "source": "Synthetic public fixture.",
    }])
    _write_json(target_root / "data" / "known-destinations.example.json", [{
        "destination": "Example City",
        "institution_examples": ["Example Police Station"],
        "km_one_way": 12,
        "notes": "Synthetic public fixture.",
    }])
    _write_json(target_root / "data" / "service-profiles.example.json", {
        "example_interpreting": {
            "description": "Synthetic in-person interpreting service profile.",
            "defaults": {
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
                "source_filename": "synthetic-source",
            },
            "source_text_template": "Synthetic interpreting service on {service_date}, case {case_number}.",
            "notes_template": "Synthetic public profile.",
        }
    })
    _write_json(target_root / "examples" / "intake.synthetic.example.json", {
        "case_number": "100/26.0TSTXX",
        "service_date": "2026-01-15",
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
        "recipient_email": "court@example.test",
        "closing_city": "Example City",
        "closing_date": "2026-01-16",
        "source_text": "Synthetic public example.",
    })
    (target_root / "data" / "README.md").write_text(
        "Synthetic public seed data only. Real local data belongs in ignored local JSON files.\n",
        encoding="utf-8",
    )


def _write_smoke_tests(target_root: Path) -> None:
    tests_dir = target_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_public_candidate_smoke.py").write_text(
        """import json
import os
import inspect
import subprocess
import tempfile
import unittest
import urllib.error
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from honorarios_app.web import create_app
from scripts.local_app_smoke import _adapter_questions_are_numbered, _post_expected_blocked_json, run_smoke
from scripts.build_public_candidate import build_public_candidate
from scripts.public_release_gate import analyze_public_readiness


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
            "Copy isolated source upload smoke command",
            "Copy isolated attachment smoke command",
            "Copy advanced Gmail API smoke command",
            "Copy Browser/IAB review smoke command",
            "Copy Browser/IAB upload smoke command",
            "Copy Browser/IAB attachment smoke command",
            "Copy Browser/IAB answers/apply smoke command",
            "Copy Browser/IAB attachment stale smoke command",
            "Copy Browser/IAB record helper smoke command",
            "Copy Python browser record helper smoke command",
            "Copy Browser/IAB Recent Work smoke command",
            "Public GitHub Readiness",
            "Run tracked Git gate",
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
            "C:\\\\",
            str(project_root),
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, dumped)

    def test_public_docs_list_browser_iab_answers_apply_diagnostics(self):
        root = Path(__file__).resolve().parents[1]
        docs = {
            "README.md": (root / "README.md").read_text(encoding="utf-8"),
            "docs/web-app-roadmap.md": (root / "docs" / "web-app-roadmap.md").read_text(encoding="utf-8"),
            "docs/process-optimizations.md": (root / "docs" / "process-optimizations.md").read_text(encoding="utf-8"),
        }
        for relative, text in docs.items():
            with self.subTest(relative=relative):
                self.assertIn("Browser/IAB answers/apply", text)
                self.assertIn("--browser-answer-questions", text)
                self.assertIn("--browser-apply-history", text)

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
        self.assertIn("isolated_source_upload_smoke", keys)
        self.assertIn("isolated_supporting_attachment_smoke", keys)
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
        self.assertIn("browser_iab_manual_handoff_stale_smoke", keys)
        self.assertIn("browser_iab_gmail_api_smoke", keys)
        isolated_attachment = next(check for check in data["checks"] if check["key"] == "isolated_supporting_attachment_smoke")
        self.assertIn("scripts/isolated_app_smoke.py", isolated_attachment["command_template"])
        self.assertIn("--supporting-attachment-checks", isolated_attachment["command_template"])
        self.assertEqual(isolated_attachment["writes"], "temporary synthetic runtime only")
        isolated_source = next(check for check in data["checks"] if check["key"] == "isolated_source_upload_smoke")
        self.assertIn("scripts/isolated_app_smoke.py", isolated_source["command_template"])
        self.assertIn("--source-upload-checks", isolated_source["command_template"])
        self.assertEqual(isolated_source["writes"], "temporary synthetic runtime only")
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
        browser_manual_handoff_stale = next(check for check in data["checks"] if check["key"] == "browser_iab_manual_handoff_stale_smoke")
        self.assertIn("--browser-manual-handoff-stale", browser_manual_handoff_stale["command_template"])
        self.assertIn("Manual Draft Handoff", browser_manual_handoff_stale["description"])
        self.assertEqual(browser_manual_handoff_stale["writes"], "temporary synthetic runtime only")
        browser_gmail_api = next(check for check in data["checks"] if check["key"] == "browser_iab_gmail_api_smoke")
        self.assertIn("--browser-gmail-api-create", browser_gmail_api["command_template"])
        self.assertIn("fake Gmail", browser_gmail_api["description"])
        self.assertEqual(browser_gmail_api["writes"], "temporary synthetic runtime only")
        dumped = json.dumps(data, sort_keys=True)
        self.assertNotIn("C:\\\\Users\\\\FA507", dumped)
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
        self.assertIn(data["status"], {"ready", "blocked"})
        self.assertEqual(data["public_ready"], data["public_repo_ready"])
        self.assertEqual(data["mode"], "tracked_git_public_repo")
        self.assertIn("tracked_gate", data)
        self.assertIn("workspace_gate", data)
        self.assertFalse(data["send_allowed"])
        dumped = json.dumps(data, sort_keys=True)
        self.assertNotIn("C:\\\\Users", dumped)
        self.assertNotIn("GOCSPX", dumped)
        self.assertNotIn("ya29.", dumped)
        self.assertNotIn("sk-", dumped)
        for gate in [data["tracked_gate"], data["workspace_gate"]]:
            self.assertEqual(gate["root"], "project-root")
            for finding in gate.get("content_findings", []):
                self.assertEqual(finding.get("match_preview"), "[redacted]")
        if data["tracked_gate"].get("errors"):
            self.assertFalse(data["tracked_gate"]["public_repo_ready"])
        else:
            self.assertTrue(data["tracked_gate"]["public_repo_ready"], data)
        if data["workspace_gate"].get("git_blockers"):
            self.assertIn("Workspace is not a git repository.", data["workspace_gate"]["git_blockers"])
        else:
            self.assertTrue(data["workspace_gate"]["public_ready"], data)

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

    def test_recent_work_missing_draft_reconciliation_stays_local_only(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        response = self.make_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("data-history-status-filter=\\"not_found\\"", response.text)
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
        pdf.write_bytes(b"%PDF-1.4\\nmissing")
        previous = os.environ.get("HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE")
        os.environ["HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE"] = "1"
        try:
            client = TestClient(create_app(
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
            client = TestClient(create_app(
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
            client = TestClient(create_app(
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

    def test_browser_js_keeps_legalpdf_restore_controls_guarded(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        smoke_js = (root / "scripts" / "browser_iab_smoke.mjs").read_text(encoding="utf-8")
        for text in [
            "/api/health",
            "serverConnection",
            "renderServerConnectionStatus",
            "setServerDisconnected",
            "syncServerConnectionGates",
        ]:
            with self.subTest(stale_guard=text):
                self.assertIn(text, app_js)
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
        flow_py = (root / "scripts" / "browser_flow_smoke.py").read_text(encoding="utf-8")
        for text in [
            "createSyntheticUploadFixtures",
            "/api/health",
            "browser_health_check",
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
            "browser_supporting_attachment_stale",
            "browser_record_helper",
            "browser_profile_proposal",
            "browser_recent_work_lifecycle",
            "browser_batch_stale_gating",
            "browser_legalpdf_import_gates",
            "/api/gmail/status",
            "fake_mode",
            "draft_only",
            "draft_create_ready",
            "browser_gmail_api_status_required",
            "browser_gmail_api_fake_mode_required",
            "browser_local_diagnostics",
            "#refresh-diagnostics",
            "#diagnostics-result",
            "#copy-isolated-source-upload-smoke-command",
            "#copy-isolated-adapter-contract-smoke-command",
            "#copy-browser-iab-review-smoke-command",
            "#copy-browser-iab-answer-apply-smoke-command",
            "#copy-browser-iab-supporting-attachment-stale-smoke-command",
            "#copy-browser-iab-record-helper-smoke-command",
            "#copy-python-browser-record-helper-smoke-command",
            "isolated_source_upload_smoke",
            "isolated_adapter_contract_smoke",
            "browser_iab_smoke",
            "browser_iab_answer_apply_smoke",
            "browser_iab_supporting_attachment_stale_smoke",
            "browser_iab_record_helper_smoke",
            "python_browser_record_helper_smoke",
            "--source-upload-checks",
            "--adapter-contract-checks",
            "--browser-answer-questions",
            "--browser-apply-history",
            "--supporting-attachment-stale",
            "--browser-record-helper",
            "supportingAttachmentStale",
            "supporting attachments changed",
            "data-use-profile-proposal",
            "#preview-profile-change",
            "#gmail-response-raw",
            "#autofill-record-from-prepared",
            "#record_draft_id",
            'expectButtonDisabled(tab, "#record-parsed-prepared-draft"',
            'expectButtonEnabled(tab, "#record-parsed-prepared-draft"',
            "Review the PDF preview and exact Gmail args before local recording.",
            "Source Evidence",
            "Filename",
            "synthetic-declaracao.pdf",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, smoke_js)
        self.assertLess(
            smoke_js.index("browser_gmail_api_fake_mode_required"),
            smoke_js.index('click(tab, "#create-gmail-api-draft"'),
        )
        gmail_block = smoke_js.split("if (args.gmailApiCreate)", 1)[1].split(
            'if (!args.prepareReplacement || args.preparePacket)',
            1,
        )[0]
        self.assertLess(
            gmail_block.index("data-verify-created-draft"),
            gmail_block.index('fill(tab, "#record_draft_id", "draft-mismatch-smoke"'),
        )
        self.assertLess(
            gmail_block.index('fill(tab, "#record_draft_id", "draft-mismatch-smoke"'),
            gmail_block.index('click(tab, "#verify-gmail-draft"'),
        )
        for text in [
            'fill(tab, "#record_message_id", "local-message-smoke"',
            'fill(tab, "#record_thread_id", "local-thread-smoke"',
            'expectSelectorText(tab, "#gmail-verify-result", "reconciliation mismatch"',
            'expectSelectorText(tab, "#gmail-verify-result", "Message ID differs"',
            'expectSelectorText(tab, "#gmail-verify-result", "Thread ID differs"',
            'expectSelectorText(tab, "#gmail-verify-result", "No local records were changed"',
            'expectSelectorText(tab, "#gmail-verify-result", "users.drafts.get"',
        ]:
            with self.subTest(gmail_mismatch=text):
                self.assertIn(text, gmail_block)
        self.assertNotIn('click(tab, "#record-parsed-prepared-draft"', gmail_block)
        self.assertNotIn('click(tab, "#record-draft"', gmail_block)
        self.assertNotIn('click(tab, "[data-history-mark-sent', gmail_block)
        for text in [
            'driver.expect_button_disabled("#record-parsed-prepared-draft")',
            "Review the PDF preview and exact Gmail args before local recording.",
            '_expect_record_value("#record_payload", ".draft.json")',
            'driver.check("#gmail_handoff_reviewed")',
            'driver.expect_button_enabled("#record-parsed-prepared-draft")',
            'driver.expect_selector_attribute_contains("#prepare-results", "data-stale-reason", "intake form changed")',
            "record_helper_should_mutate_prepared_state = not (manual_handoff_stale or supporting_attachment_stale)",
            "browser_supporting_attachment_stale",
            'driver.set_input_file("#supporting-attachment-file", supporting_upload_path)',
            'driver.expect_button_disabled("#copy-manual-handoff-prompt")',
            'driver.expect_selector_value_equals("#record_payload", "")',
            'driver.expect_selector_attribute_contains("#prepare-results", "data-stale-reason", "supporting attachments changed")',
            "locator = self._page.get_by_text(text, exact=False)",
            "for index in range(locator.count())",
            "locator.nth(index).is_visible",
            "self._page.wait_for_timeout(100)",
            "Expected visible text",
            "deadline = time.monotonic()",
            "text.lower() in last_content.lower()",
            "last_content",
            "elif correction_mode:",
            "if not prepare_replacement or prepare_packet:",
            'wait_for(state="attached"',
        ]:
            with self.subTest(browser_flow=text):
                self.assertIn(text, flow_py)
        flow_value_block = flow_py.split("def expect_selector_value", 1)[1].split("def expect_button_disabled", 1)[0]
        self.assertNotIn('wait_for(state="visible"', flow_value_block)
        self.assertNotIn("get_by_text(text, exact=False).wait_for", flow_py)
        self.assertNotIn("get_by_text(text, exact=False).first().wait_for", flow_py)
        self.assertNotIn("get_by_text(text, exact=False).first.wait_for", flow_py)
        flow_homepage_block = flow_py.split('if not _safe_step(checks, "browser_homepage"', 1)[1].split('def _review_drawer()', 1)[0]
        self.assertNotIn('driver.expect_text("Suggested Next Step")', flow_homepage_block)
        flow_reset_block = flow_py.split('if not _safe_step(checks, "browser_workspace_reset"', 1)[1].split("finally:", 1)[0]
        self.assertLess(flow_reset_block.index("_close_review_drawer_if_open()"), flow_reset_block.index('driver.click("#reset-workspace")'))
        self.assertNotIn("Browser/IAB smoke does not drive local file-picker uploads yet", smoke_js)
        self.assertNotIn('click(tab, "[data-history-mark-not-found', smoke_js)
        self.assertNotIn("_send_email", smoke_js)
        self.assertNotIn("_send_draft", smoke_js)
        self.assertNotIn('driver.click("#record-parsed-prepared-draft")', flow_py)
        self.assertNotIn('driver.click("#record-draft")', flow_py)
        self.assertNotIn('driver.click("#create-gmail-api-draft")', flow_py)

    def test_browser_js_prefights_single_prepare_before_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")
        prepare_body = app_js.split("async function prepareIntake", 1)[1].split("function renderPrepared", 1)[0]

        preflight_index = prepare_body.index('requestJson("/api/prepare/preflight"')
        prepare_index = prepare_body.index('requestJson("/api/prepare"')
        self.assertLess(preflight_index, prepare_index)
        self.assertIn("requestPayload.preflight_review = preflight.preflight_review", prepare_body)
        self.assertIn("preflightPayload.correction_reason = requestPayload.correction_reason", prepare_body)
        self.assertIn('packet_mode: false', prepare_body)

    def test_browser_js_routes_one_click_recording_through_strict_prepared_endpoint(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "honorarios_app" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("async function recordPreparedDraftFromForm", app_js)
        one_click_body = app_js.split("async function recordFromParsedResponseAndPreparedPayload", 1)[1].split("function ", 1)[0]
        self.assertIn("await recordPreparedDraftFromForm()", one_click_body)
        self.assertNotIn("await recordDraft()", one_click_body)
        prepared_record_body = app_js.split("async function recordPreparedDraftFromForm", 1)[1].split("async function ", 1)[0]
        self.assertIn('requestJson("/api/drafts/record"', prepared_record_body)
        self.assertIn("gmail_handoff_reviewed: true", prepared_record_body)
        self.assertIn("...currentPreparedReviewFields(payloadPath)", prepared_record_body)
        manual_record_body = app_js.split("async function recordDraft()", 1)[1].split("function ", 1)[0]
        self.assertIn('requestJson("/api/drafts/status"', manual_record_body)
        self.assertNotIn("_send_email", app_js)
        self.assertNotIn("_send_draft", app_js)

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
            "supporting attachments changed",
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
        self.assertEqual(
            profiles_overlay_path.read_text(encoding="utf-8") if profiles_overlay_path.exists() else None,
            profiles_overlay_before,
        )
        self.assertEqual(
            court_overlay_path.read_text(encoding="utf-8") if court_overlay_path.exists() else None,
            court_overlay_before,
        )

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
                        "draft_text": "Número de processo: 999/26.0SMOKE\\n\\nPede deferimento,",
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

    def test_local_app_smoke_runner_adapter_contract_sequence_is_injectable(self):
        client = self.make_client()
        seen_posts = []
        seen_uploads = []

        def fetch_text(url):
            path = "/" if url.endswith("/") else url.split("http://public-candidate.test", 1)[-1]
            return client.get(path).text

        def fetch_json(url):
            path = url.split("http://public-candidate.test", 1)[-1]
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
                    "draft_text": "Número de processo: 999/26.0SMOKE\\n\\nPede deferimento,",
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
                    "addressee": "Exmo. Senhor Procurador da República\\nExample Court",
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
            REQUIRED_ADAPTER_ENDPOINTS,
            LegalPdfAdapterCaller,
            adapter_questions_are_numbered,
            prepared_review_request_fields,
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
            "Please answer by number:\\n1. Closing date?",
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
                    "draft_text": "Número de processo: 999/26.0SMOKE\\n\\nPede deferimento,",
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
                    "addressee": "Exmo. Senhor Procurador da República\\nExample Court",
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

    def test_legalpdf_adapter_caller_cli_outputs_guarded_safe_summary(self):
        import scripts.legalpdf_adapter_caller as adapter

        self.assertTrue(hasattr(adapter, "main"), "Adapter caller should expose a CLI main()")
        self.assertTrue(
            hasattr(adapter, "run_synthetic_adapter_sequence_http"),
            "Adapter caller CLI should reuse the HTTP synthetic sequence helper.",
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

    def test_adapter_contract_smoke_requires_numbered_review_questions(self):
        self.assertTrue(_adapter_questions_are_numbered(
            [{"number": 1, "field": "closing_date"}],
            "Please answer by number:\\n1. Closing date?",
        ))
        self.assertFalse(_adapter_questions_are_numbered(
            [{"field": "closing_date"}],
            "Please answer by number:\\n1. Closing date?",
        ))
        self.assertFalse(_adapter_questions_are_numbered(
            [{"number": 1, "field": "closing_date"}],
            "Closing date?",
        ))

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
                    {"name": "browser_supporting_attachment_stale", "status": "ready", "message": "ok", "details": {}},
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
            browser_supporting_attachment_stale=True,
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
        self.assertTrue(seen_kwargs["supporting_attachment_stale"])
        self.assertTrue(seen_kwargs["record_helper"])
        self.assertTrue(seen_kwargs["apply_history"])

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
            "browser_iab_smoke",
            "browser_iab_answer_apply_smoke",
            "browser_iab_record_helper_smoke",
            "python_browser_record_helper_smoke",
        ]:
            with self.subTest(key=key):
                self.assertIn(key, required_block)

    def test_isolated_app_smoke_forwards_browser_iab_answer_and_apply_flags(self):
        root = Path(__file__).resolve().parents[1]
        smoke_source = (root / "scripts" / "isolated_app_smoke.py").read_text(encoding="utf-8")
        smoke_call_block = smoke_source.split("report = smoke_runner(", 1)[1].split(")", 1)[0]
        main_call_block = smoke_source.split("report = run_isolated_app_smoke(", 1)[1].split(")", 1)[0]

        self.assertIn("browser_answer_questions: bool = False", smoke_source)
        self.assertIn("browser_apply_history: bool = False", smoke_source)
        self.assertIn("browser_answer_questions=browser_answer_questions", smoke_call_block)
        self.assertIn("browser_apply_history=browser_apply_history", smoke_call_block)
        self.assertIn('parser.add_argument("--browser-answer-questions"', smoke_source)
        self.assertIn('parser.add_argument("--browser-apply-history"', smoke_source)
        self.assertIn("browser_answer_questions=args.browser_answer_questions", main_call_block)
        self.assertIn("browser_apply_history=args.browser_apply_history", main_call_block)

    def test_candidate_privacy_gate_passes(self):
        report = analyze_public_readiness(Path(__file__).resolve().parents[1], require_git=False)
        self.assertTrue(report["public_ready"], report)

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


if __name__ == "__main__":
    unittest.main()
""",
        encoding="utf-8",
    )


def _write_public_repo_metadata(target_root: Path) -> None:
    (target_root / "LICENSE").write_text(
        "MIT License\n\n"
        "Copyright (c) 2026 Honorários Interpreting contributors\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        "of this software and associated documentation files (the \"Software\"), to deal\n"
        "in the Software without restriction, including without limitation the rights\n"
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
        "copies of the Software, and to permit persons to whom the Software is\n"
        "furnished to do so, subject to the following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all\n"
        "copies or substantial portions of the Software.\n\n"
        "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n"
        "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
        "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
        "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
        "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
        "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
        "SOFTWARE.\n",
        encoding="utf-8",
    )
    (target_root / "SECURITY.md").write_text(
        "# Security Policy\n\n"
        "This project prepares legal fee-request PDFs and Gmail draft payloads. It must not send email automatically.\n\n"
        "## Reporting\n\n"
        "Please report security issues through GitHub Security Advisories or by opening a private maintainer contact channel before publishing details.\n\n"
        "## Local Data\n\n"
        "Keep real profile data, payment details, court emails, generated PDFs, source photos, draft logs, duplicate indexes, and API keys out of public commits. Use the `.example.json` files as templates for local ignored files.\n",
        encoding="utf-8",
    )
    (target_root / "CONTRIBUTING.md").write_text(
        "# Contributing\n\n"
        "Use synthetic fixtures only. Do not commit real case numbers, court email addresses, Gmail draft IDs, generated PDFs, source screenshots, IBANs, addresses, or local API keys.\n\n"
        "Before opening a pull request, run:\n\n"
        "```powershell\n"
        "python -m unittest discover tests\n"
        "python scripts/public_release_gate.py --no-require-git --json\n"
        "```\n\n"
        "The Gmail workflow is draft-only. Do not add UI, API, scripts, or tests that send email automatically.\n",
        encoding="utf-8",
    )


def build_public_candidate(source_root: str | Path = ROOT, target_root: str | Path | None = None) -> dict[str, Any]:
    source = Path(source_root).resolve()
    target = Path(target_root or (source / "output" / "public-candidate")).resolve()
    _ensure_safe_target(source, target)
    _reset_target(target)

    for relative in COPY_FILES:
        source_file = source / relative
        if source_file.exists():
            _copy_and_sanitize_file(source_file, target / relative)
    for relative in COPY_DIRS:
        _copy_tree(source / relative, target / relative)

    shutil.rmtree(target / "tests", ignore_errors=True)
    shutil.rmtree(target / ".playwright-mcp", ignore_errors=True)
    _write_synthetic_runtime_files(target)
    _write_smoke_tests(target)
    _write_public_repo_metadata(target)

    workspace_gate = analyze_public_readiness(target, require_git=False)
    tracked_gate = _candidate_tracked_gate(target)
    gate = _merge_candidate_gates(workspace_gate, tracked_gate)
    status = "created" if gate["public_ready"] else "blocked"
    result = {
        "status": status,
        "candidate_path": str(target),
        "gate": gate,
        "send_allowed": False,
    }
    if tracked_gate is not None:
        result["tracked_gate"] = tracked_gate
        result["workspace_gate"] = workspace_gate
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a sanitized public candidate tree.")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_public_candidate(args.source, args.target)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Candidate: {result['candidate_path']}")
        print(result["gate"]["message"])
        print(f"Blockers: {result['gate']['blocker_count']}")
    return 0 if result["gate"]["public_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
