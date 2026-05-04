from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.generate_pdf import ROOT, DEFAULT_TEMPLATE


SYNTHETIC_DEFAULT_CASE = "999/26.0SMOKE"
SYNTHETIC_REPLACEMENT_CASE = "999/26.0REPL"
SYNTHETIC_SERVICE_DATE = "2026-05-04"
SYNTHETIC_COURT_EMAIL = "court@" + "tribunais.org.pt"


def runtime_path_overrides(runtime_root: str | Path) -> dict[str, Path]:
    root = Path(runtime_root).resolve()
    return {
        "profile": root / "config" / "profile.json",
        "template": DEFAULT_TEMPLATE,
        "service_profiles": root / "data" / "service-profiles.json",
        "duplicate_index": root / "data" / "duplicate-index.json",
        "email_config": root / "config" / "email.json",
        "court_emails": root / "data" / "court-emails.json",
        "known_destinations": root / "data" / "known-destinations.json",
        "draft_log": root / "data" / "gmail-draft-log.json",
        "profile_change_log": root / "data" / "profile-change-log.json",
        "output_dir": root / "output" / "pdf",
        "html_dir": root / "tmp" / "pdfs",
        "draft_output_dir": root / "output" / "email-drafts",
        "manifest_dir": root / "output" / "manifests",
        "render_dir": root / "output" / "previews",
        "intake_output_dir": root / "output" / "intakes",
        "source_upload_dir": root / "output" / "source-uploads",
        "packet_output_dir": root / "output" / "packets",
        "backup_output_dir": root / "output" / "backups",
        "integration_report_output_dir": root / "output" / "integration-reports",
        "ai_config": root / "config" / "ai.local.json",
        "google_photos_config": root / "config" / "google-photos.local.json",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def synthetic_profile() -> dict[str, Any]:
    return {
        "applicant_name": "Example Interpreter",
        "address": "Example Street 1, 1000-000 Example City",
        "default_origin": "Example City",
        "iban": "EXAMPLE0000000000000000000",
        "vat_irs_phrase": "Este serviço inclui a taxa de IVA de 23% e não está sujeito a retenção de IRS.",
        "payment_phrase": "O pagamento deverá ser efetuado para o seguinte IBAN:",
        "default_closing_city": "Example City",
        "default_closing_phrase": "Pede deferimento,",
        "signature_label": "O Requerente,",
        "signature_name": "Example Interpreter",
    }


def synthetic_email_config() -> dict[str, Any]:
    return {
        "default_to": SYNTHETIC_COURT_EMAIL,
        "subject": "Requerimento de honorários",
        "body": (
            "Bom dia,\n\n"
            "Venho por este meio requerer o pagamento dos honorários devidos.\n\n"
            "Poderão encontrar o requerimento em anexo.\n\n"
            "Melhores cumprimentos,\n\n"
            "Example Interpreter"
        ),
        "draft_only": True,
        "allowed_gmail_tool": "_create_draft",
        "forbidden_gmail_tools": ["_send_email", "_send_draft"],
    }


def synthetic_service_profiles() -> dict[str, Any]:
    return {
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
                "recipient_email": SYNTHETIC_COURT_EMAIL,
                "source_filename": "synthetic-source",
            },
            "source_text_template": "Synthetic interpreting service on {service_date}, case {case_number}.",
            "notes_template": "Synthetic isolated runtime profile.",
        }
    }


def synthetic_court_emails() -> list[dict[str, Any]]:
    return [{
        "key": "example-court",
        "name": "Example Court",
        "email": SYNTHETIC_COURT_EMAIL,
        "payment_entity_aliases": ["Example Court", "Example Ministério Público"],
        "source": "Synthetic isolated runtime fixture.",
    }]


def synthetic_known_destinations() -> list[dict[str, Any]]:
    return [{
        "destination": "Example City",
        "institution_examples": ["Example Police Station"],
        "km_one_way": 12,
        "notes": "Synthetic isolated runtime fixture.",
    }]


def active_draft_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    duplicate_records = [{
        "case_number": SYNTHETIC_REPLACEMENT_CASE,
        "service_date": SYNTHETIC_SERVICE_DATE,
        "status": "drafted",
        "draft_id": "draft-synthetic-active",
        "recipient": SYNTHETIC_COURT_EMAIL,
        "pdf": "synthetic-existing.pdf",
        "source_filename": "synthetic-existing.pdf",
        "notes": "Synthetic active draft used only by isolated replacement smoke.",
    }]
    draft_log_records = [{
        "draft_id": "draft-synthetic-active",
        "message_id": "message-synthetic-active",
        "thread_id": "thread-synthetic-active",
        "status": "active",
        "case_number": SYNTHETIC_REPLACEMENT_CASE,
        "service_date": SYNTHETIC_SERVICE_DATE,
        "recipient": SYNTHETIC_COURT_EMAIL,
        "pdf": "synthetic-existing.pdf",
        "payload": "synthetic-existing.draft.json",
        "notes": "Synthetic active draft used only by isolated replacement smoke.",
    }]
    return duplicate_records, draft_log_records


def create_synthetic_runtime(runtime_root: str | Path, *, seed_active_draft: bool = False) -> dict[str, Any]:
    root = Path(runtime_root).resolve()
    paths = runtime_path_overrides(root)
    root.mkdir(parents=True, exist_ok=True)

    _write_json(paths["profile"], synthetic_profile())
    _write_json(paths["email_config"], synthetic_email_config())
    _write_json(paths["service_profiles"], synthetic_service_profiles())
    _write_json(paths["court_emails"], synthetic_court_emails())
    _write_json(paths["known_destinations"], synthetic_known_destinations())
    _write_json(paths["profile_change_log"], [])
    _write_json(paths["ai_config"], {"model": "gpt-5.4-mini"})
    _write_json(paths["google_photos_config"], {
        "notes": "Synthetic isolated runtime. Configure real credentials only in private local files.",
    })

    duplicate_records: list[dict[str, Any]] = []
    draft_log_records: list[dict[str, Any]] = []
    if seed_active_draft:
        duplicate_records, draft_log_records = active_draft_records()
    _write_json(paths["duplicate_index"], duplicate_records)
    _write_json(paths["draft_log"], draft_log_records)

    for key in (
        "output_dir",
        "html_dir",
        "draft_output_dir",
        "manifest_dir",
        "render_dir",
        "intake_output_dir",
        "source_upload_dir",
        "packet_output_dir",
        "backup_output_dir",
        "integration_report_output_dir",
    ):
        paths[key].mkdir(parents=True, exist_ok=True)

    return {
        "runtime_root": str(root),
        "path_overrides": {key: str(value) for key, value in paths.items()},
        "seed_active_draft": seed_active_draft,
        "seed_active_draft_case": SYNTHETIC_REPLACEMENT_CASE if seed_active_draft else "",
        "default_case": SYNTHETIC_DEFAULT_CASE,
        "service_date": SYNTHETIC_SERVICE_DATE,
        "project_root": str(ROOT),
        "send_allowed": False,
    }
