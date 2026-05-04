from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_pdf import ROOT
from scripts.public_release_gate import analyze_public_readiness


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
    _write_json(target_root / "data" / "court-emails.json", [{
        "key": "example-court",
        "name": "Example Court",
        "email": "court@example.test",
        "payment_entity_aliases": ["Example Court", "Example Ministério Público"],
        "source": "Synthetic public fixture.",
    }])
    _write_json(target_root / "data" / "known-destinations.json", [{
        "destination": "Example City",
        "institution_examples": ["Example Police Station"],
        "km_one_way": 12,
        "notes": "Synthetic public fixture.",
    }])
    _write_json(target_root / "data" / "service-profiles.json", {
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
                        "draft_text": "Número de processo: 999/26.0SMOKE\\n\\nPede deferimento,",
                        "send_allowed": False,
                    },
                    "send_allowed": False,
                }
            if url.endswith("/api/drafts/active-check"):
                return {"status": "clear", "send_allowed": False}
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
            browser_upload_photo=True,
            browser_upload_pdf=True,
            browser_correction_mode=True,
            browser_prepare_replacement=True,
            browser_apply_history=True,
            browser_runner=browser_runner,
        )
        self.assertEqual(report["status"], "ready", report)
        self.assertIn("browser_review_drawer", {check["name"] for check in report["checks"]})
        self.assertIn("browser_photo_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_pdf_upload_evidence", {check["name"] for check in report["checks"]})
        self.assertIn("browser_correction_mode", {check["name"] for check in report["checks"]})
        self.assertIn("browser_replacement_prepare", {check["name"] for check in report["checks"]})
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

    gate = analyze_public_readiness(target, require_git=False)
    return {
        "status": "created" if gate["public_ready"] else "blocked",
        "candidate_path": str(target),
        "gate": gate,
        "send_allowed": False,
    }


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
