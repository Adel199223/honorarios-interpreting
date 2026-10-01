"""Pure source evidence for review; never validates, writes data or calls providers.

The service layer supplies recovered candidate values and its domain-review result.
These helpers explain provenance and attention without deciding whether generation
or draft creation is allowed. Runtime paths and optional providers stay outside
this module.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import unicodedata

from scripts.request_identity import normalize_case_number
from scripts.source_parsing import explicit_service_places
from .source_cases import source_case_rows


FIELD_EVIDENCE_LABELS = {
    "profile_key": "Profile",
    "case_number": "Case number",
    "service_date": "Service date",
    "photo_metadata_date": "Metadata date",
    "recipient_email": "Recipient email",
    "payment_entity": "Payment entity",
    "service_entity": "Service entity",
    "service_entity_type": "Service entity type",
    "service_place": "Service place",
    "service_place_phrase": "Service place phrase",
    "transport_destination": "Transport destination",
    "km_one_way": "Kilometers one way",
}
CONFIRMED_SERVICE_DATE_SOURCES = frozenset({
    "user_confirmed", "user_confirmed_exception", "document_text_user_confirmed", "photo_metadata_user_confirmed",
})


def _date_text_variants(value: Any) -> list[str]:
    text = str(value or "").strip()
    variants = [text] if text else []
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return variants
    variants.extend([
        parsed.strftime("%d/%m/%Y"),
        parsed.strftime("%d-%m-%Y"),
    ])
    return variants


def _text_contains_value(text: str, value: Any) -> bool:
    folded_text = fold_match_text(text)
    for variant in _date_text_variants(value):
        if variant and fold_match_text(variant) in folded_text:
            return True
    normalized_case = normalize_case_number(str(value or "")) if "/" in str(value or "") else ""
    if normalized_case and fold_match_text(normalized_case) in folded_text:
        return True
    return False


def _line_excerpt(text: str, value: Any) -> str:
    source = str(text or "")
    if not source.strip() or value in (None, ""):
        return ""
    variants = [str(value)]
    variants.extend(_date_text_variants(value))
    if "/" in str(value):
        variants.append(normalize_case_number(str(value)))
    for line in source.splitlines():
        folded_line = fold_match_text(line)
        if any(variant and fold_match_text(variant) in folded_line for variant in variants):
            return line.strip()[:220]
    return ""


def _field_evidence_entry(
    field: str,
    value: Any,
    *,
    source: str,
    confidence: str,
    status: str = "applied",
    reason: str = "",
    raw_value: Any = "",
    excerpt: str = "",
    conflicts_with: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "field": field,
        "label": FIELD_EVIDENCE_LABELS.get(field, field.replace("_", " ").title()),
        "value": value,
        "source": source,
        "confidence": confidence,
        "status": status,
        "reason": reason,
    }
    if raw_value not in (None, ""):
        entry["raw_value"] = raw_value
    if excerpt:
        entry["excerpt"] = excerpt
    if conflicts_with:
        entry["conflicts_with"] = conflicts_with
    return entry


def _profile_default(profiles: dict[str, Any], profile_key: str, field: str) -> Any:
    profile = profiles.get(profile_key) if isinstance(profiles, dict) else {}
    defaults = profile.get("defaults") if isinstance(profile, dict) else {}
    if not isinstance(defaults, dict):
        return ""
    if field == "km_one_way":
        transport = defaults.get("transport") if isinstance(defaults.get("transport"), dict) else {}
        return transport.get("km_one_way", "")
    if field == "transport_destination":
        transport = defaults.get("transport") if isinstance(defaults.get("transport"), dict) else {}
        return transport.get("destination", "")
    return defaults.get(field, "")


def _field_from_candidate(candidate: dict[str, Any], field: str) -> Any:
    if field == "km_one_way":
        transport = candidate.get("transport") if isinstance(candidate.get("transport"), dict) else {}
        return transport.get("km_one_way", "")
    if field == "transport_destination":
        transport = candidate.get("transport") if isinstance(candidate.get("transport"), dict) else {}
        return transport.get("destination", "")
    return candidate.get(field, "")


def _ai_field_value(ai_recovery: dict[str, Any], field: str) -> str:
    ai_fields = ai_recovery.get("fields") if isinstance(ai_recovery, dict) else {}
    if not isinstance(ai_fields, dict):
        return ""
    aliases = {
        "case_number": ("raw_case_number", "source_case_number", "case_number"),
        "recipient_email": ("court_email", "recipient_email"),
        "km_one_way": ("km_one_way", "transport_km_one_way", "one_way_km"),
        "transport_destination": ("transport_destination", "destination", "locality", "city"),
        "service_place": ("service_place", "locality"),
        "source_document_timestamp": ("source_document_timestamp", "document_timestamp"),
    }.get(field, (field,))
    for alias in aliases:
        value = str(ai_fields.get(alias) or "").strip()
        if value:
            return value
    return ""


def _values_match(left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return False
    left_text = str(left).strip()
    right_text = str(right).strip()
    if "/" in left_text and "/" in right_text:
        return normalize_case_number(left_text).casefold() == normalize_case_number(right_text).casefold()
    return fold_match_text(left_text) == fold_match_text(right_text)


def _ai_source_for_field(field: str, value: Any, raw_visible_text: str, metadata_date: str) -> tuple[str, str, str]:
    if field == "service_date" and metadata_date and str(value or "").strip() == metadata_date:
        return "openai_and_photo_metadata", "medium", "AI suggested this service date and it matches the capture date. Agreement does not confirm when the service happened; check the source and confirm the date."
    if _text_contains_value(raw_visible_text, value):
        return "openai_ocr", "medium", "AI read this value in its recovered text. That text is from the same AI response, not independent confirmation; check the original source."
    return "openai_ocr", "low", "AI suggested this value without a matching excerpt in its recovered text. It may be inferred; check and correct it against the original source."


def _independent_source_text(candidate: dict[str, Any], raw_visible_text: str) -> str:
    # Later reviews reparse source_text, which includes AI OCR. A repeated AI
    # claim must not become independent evidence merely by matching a pattern.
    text = str(candidate.get("source_text") or "")
    ai_text = str(raw_visible_text or "").strip()
    return text.replace(ai_text, "").strip() if ai_text else text


def build_field_evidence(
    *,
    candidate: dict[str, Any],
    deterministic_fields: dict[str, Any],
    metadata: dict[str, Any],
    ai_recovery: dict[str, Any],
    profile_decision: dict[str, Any],
    profiles: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen_fields: set[str] = set()
    profile_key = str(profile_decision.get("profile_key") or "").strip()
    profile_mode = str(profile_decision.get("mode") or "").strip()
    profile_source = {
        "auto_applied": "auto_profile",
        "explicit_profile": "explicit_profile",
        "auto_fallback": "fallback_profile",
    }.get(profile_mode, "profile")
    if profile_key:
        evidence.append(_field_evidence_entry(
            "profile_key",
            profile_key,
            source=profile_source,
            confidence=str(profile_decision.get("confidence") or ("high" if profile_mode == "explicit_profile" else "medium")),
            reason=str(profile_decision.get("reason") or profile_decision.get("suggestion_reason") or "Service profile selected for this intake."),
        ))
        seen_fields.add("profile_key")

    raw_visible_text = str(ai_recovery.get("raw_visible_text") or "")
    independent_text = _independent_source_text(candidate, raw_visible_text)
    metadata_date = str(metadata.get("exif_date") or metadata.get("visible_metadata_date") or candidate.get("photo_metadata_date") or "").strip()

    def add(field: str, value: Any, *, source: str, confidence: str, reason: str, raw_value: Any = "", excerpt: str = "") -> None:
        if field in seen_fields or value in (None, ""):
            return
        status = "applied"
        conflicts_with = None
        if field == "service_date" and metadata_date and str(value or "").strip() != metadata_date:
            status = "conflicts_with_metadata"
            conflicts_with = {
                "field": "photo_metadata_date",
                "value": metadata_date,
            }
        evidence.append(_field_evidence_entry(
            field,
            value,
            source=source,
            confidence=confidence,
            status=status,
            reason=reason,
            raw_value=raw_value,
            excerpt=excerpt,
            conflicts_with=conflicts_with,
        ))
        seen_fields.add(field)

    if metadata_date:
        metadata_source = _photo_metadata_date_source(candidate, metadata, ai_recovery)
        ai_metadata = metadata_source == "openai_ocr"
        metadata_verified = bool(metadata.get("exif_date") or metadata.get("visible_metadata_date")) and not ai_metadata
        add(
            "photo_metadata_date",
            metadata_date,
            source=metadata_source,
            confidence="high" if metadata_verified else "medium",
            reason=(
                "AI read a possible capture date. Check the original metadata; a capture date does not confirm the service date."
                if ai_metadata
                else "Visible Google Photos metadata supplied a capture date, not confirmation of the service date."
                if metadata_source == "visible_google_photos_metadata"
                else "Image metadata supplied a capture date, not confirmation of the service date."
                if metadata_verified
                else "A capture-date candidate was supplied for review. Check its origin and confirm whether the service happened then."
            ),
        )

    if 'source_case_numbers' in candidate and candidate.get('case_number'):
        case = normalize_case_number(candidate['case_number'])
        for text, source, confidence in ((independent_text, 'deterministic_text', 'high'),
                                         (raw_visible_text, 'openai_ocr', 'medium')):
            matched = next((row for row in source_case_rows(text, {}) if row['case_number'] == case), None)
            if matched:
                add('case_number', case, source=source, confidence=confidence,
                    raw_value=matched['raw_case_number'], excerpt=_line_excerpt(text, matched['raw_case_number']),
                    reason='This separately reviewed case reference matched the visible source text. Check it against the original photo.' if source == 'deterministic_text' else
                           'AI read this separately reviewed case reference in the photo. Check it against the original image; a repeated pattern is not independent confirmation.')
                break
    station = candidate.get('source_station_place')
    if station and _values_match(candidate.get('service_place'), station):
        for text, source, confidence in ((independent_text, 'document_text', 'high'),
                                         (raw_visible_text, 'openai_ocr', 'medium')):
            if _text_contains_value(text, station):
                add('service_place', station, source=source, confidence=confidence,
                    excerpt=_line_excerpt(text, station), reason='The source names this specific police station. Check the venue for this appointment; the city-court fallback was not used.')
                break

    court_label = candidate.get('court_label_preference') or {}
    if isinstance(court_label, dict):
        for field, original in (court_label.get('original_fields') or {}).items():
            if field in {'payment_entity', 'service_entity', 'service_place'} and candidate.get(field) == court_label.get('label'):
                add(field, candidate[field], source='saved_court_label', confidence='medium', raw_value=original,
                    reason='Your saved short court label matches this ordinary court and its exact recipient. The original source wording is retained; you can edit this label.')
    photo_defaults = candidate.get("photo_defaults_applied") or {}
    if isinstance(photo_defaults, dict):
        for field in ("service_date", "payment_entity", "recipient_email", "service_place"):
            value = photo_defaults.get(field)
            if value and _values_match(candidate.get(field), value) and not (
                field == "service_date" and str(candidate.get("service_date_source") or "") in CONFIRMED_SERVICE_DATE_SOURCES
            ):
                reason = (
                    "Your saved photo-date default uses the capture day as the interpreting day. You can edit an exception."
                    if field == "service_date" else
                    "Your saved missing-venue default uses the capture-city court when the source supplies no service building. You can edit an exception. This is your default, not a venue printed on the document."
                    if field == "service_place" else
                    f"Your saved photo-city default selects the configured court/contact for {photo_defaults.get('photo_city', '')}. This is your default, not a payer stated on the document."
                )
                if field == "service_date" and photo_defaults.get("original_service_date"):
                    reason += f" The source also suggested {photo_defaults['original_service_date']}; the photo default takes priority."
                add(field, value, source="photo_default", confidence="medium", reason=reason)

    if str(candidate.get("service_date_source") or "").strip().lower() in CONFIRMED_SERVICE_DATE_SOURCES:
        add("service_date", candidate.get("service_date"), source="user_confirmed", confidence="high", reason="You explicitly supplied or confirmed the service date. Source, conflict and duplicate checks still apply.")

    deterministic_sources = {
        "case_number": "deterministic_text",
        "service_date": "document_text",
        "recipient_email": "visible_email",
        "service_place": "known_destination",
        "transport_destination": "known_destination",
        "km_one_way": "known_destination",
    }
    deterministic_reasons = {
        "case_number": "A local pattern matched the visible NUIPC/process number.",
        "service_date": "A local date pattern matched the uploaded source text.",
        "recipient_email": "A local email pattern matched the uploaded source text.",
        "service_place": "A known destination matched the uploaded source text.",
        "transport_destination": "A known destination matched the uploaded source text.",
        "km_one_way": "A known destination supplied the stored one-way distance.",
    }
    for field in ("case_number", "service_date", "recipient_email", "service_place", "transport_destination", "km_one_way"):
        value = _field_from_candidate(candidate, field)
        deterministic_value = deterministic_fields.get(field)
        if field in {"transport_destination", "km_one_way"}:
            deterministic_value = deterministic_fields.get(field)
        if deterministic_value not in (None, "") and _values_match(value, deterministic_value):
            ai_value = _ai_field_value(ai_recovery, field)
            if ai_recovery.get("status") == "ok" and not _text_contains_value(independent_text, deterministic_value):
                if _text_contains_value(raw_visible_text, deterministic_value):
                    source, confidence, reason = _ai_source_for_field(field, value, raw_visible_text, metadata_date)
                    add(field, value, source=source, confidence=confidence, reason=reason, excerpt=_line_excerpt(raw_visible_text, deterministic_value))
                    continue
                if ai_value and _values_match(value, normalize_case_number(ai_value) if field == "case_number" else ai_value):
                    continue
            source = deterministic_sources[field]
            reason = deterministic_reasons[field]
            if field == "service_date" and metadata_date and str(value or "").strip() == metadata_date:
                source = "document_text_and_photo_metadata"
            if field == "service_place" and any(_values_match(value, place) for place in explicit_service_places(independent_text)):
                source = "document_text"
                reason = "A local pattern identified this physical service place in the source text. Check the building and city before preparing."
            add(
                field,
                value,
                source=source,
                confidence="medium" if source == "known_destination" else "high",
                reason=reason,
                raw_value=deterministic_fields.get("raw_case_number", "") if field == "case_number" else "",
                excerpt=_line_excerpt(str(candidate.get("source_text") or ""), deterministic_value),
            )

    ai_status = str(ai_recovery.get("status") or "")
    if ai_status == "ok":
        for field in (
            "case_number",
            "service_date",
            "recipient_email",
            "payment_entity",
            "service_entity",
            "service_entity_type",
            "service_place",
            "service_place_phrase",
            "transport_destination",
            "km_one_way",
        ):
            value = _field_from_candidate(candidate, field)
            ai_value = _ai_field_value(ai_recovery, field)
            if ai_value and _values_match(value, normalize_case_number(ai_value) if field == "case_number" else ai_value):
                source, confidence, reason = _ai_source_for_field(field, value, raw_visible_text, metadata_date)
                add(
                    field,
                    value,
                    source=source,
                    confidence=confidence,
                    reason=reason,
                    raw_value=ai_value if field == "case_number" else "",
                    excerpt=_line_excerpt(raw_visible_text, ai_value),
                )

    for field in (
        "payment_entity",
        "recipient_email",
        "service_entity",
        "service_entity_type",
        "service_place",
        "service_place_phrase",
        "transport_destination",
        "km_one_way",
    ):
        value = _field_from_candidate(candidate, field)
        default_value = _profile_default(profiles, profile_key, field)
        if default_value not in (None, "") and _values_match(value, default_value):
            add(
                field,
                value,
                source="service_profile",
                confidence="low" if profile_source == "fallback_profile" else "medium",
                reason=f"Service profile {profile_key} supplied this default. A recurring profile does not confirm this source; check the value before preparing.",
            )

    return evidence


def build_profile_evidence(profile_decision: dict[str, Any]) -> dict[str, Any]:
    signals = [
        {
            "text": str(signal),
            "source": "source_text_or_openai_ocr",
        }
        for signal in profile_decision.get("signals", [])
        if str(signal).strip()
    ]
    return {
        "mode": profile_decision.get("mode", ""),
        "profile_key": profile_decision.get("profile_key", ""),
        "suggested_profile_key": profile_decision.get("suggested_profile_key", ""),
        "confidence": profile_decision.get("confidence", ""),
        "reason": profile_decision.get("reason", ""),
        "suggestion_reason": profile_decision.get("suggestion_reason", ""),
        "auto_applied": bool(profile_decision.get("auto_applied")),
        "signals": signals,
    }


def _attention_flag(code: str, severity: str, title: str, detail: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
    }


def _friendly_photo_metadata_detail(candidate: dict[str, Any], ai_recovery: dict[str, Any]) -> str:
    metadata_date = str(candidate.get("photo_metadata_date") or "").strip()
    if not metadata_date or str(candidate.get("service_date") or "").strip():
        return ""
    try:
        parsed = datetime.strptime(metadata_date, "%Y-%m-%d")
        date_label = f"{parsed.strftime('%B')} {parsed.day}"
    except ValueError:
        date_label = metadata_date
    fields = ai_recovery.get("fields") if isinstance(ai_recovery, dict) else {}
    locality = ""
    if isinstance(fields, dict):
        locality = str(fields.get("locality") or fields.get("service_place") or "").strip()
    if not locality:
        locality = str(candidate.get("service_place") or "").strip()
    place_text = f" in {locality}" if locality else ""
    return f"Photo metadata appears to be {date_label}{place_text}. Confirm whether this was the service date."


def build_source_attention(
    *,
    candidate: dict[str, Any],
    review: dict[str, Any],
    ai_recovery: dict[str, Any],
    profile_decision: dict[str, Any],
    profile_proposal: dict[str, Any],
    field_evidence: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    flags: list[dict[str, Any]] = []
    review_status = str(review.get("status") or "").strip()

    if review_status == "set_aside":
        flags.append(_attention_flag(
            "translation_set_aside",
            "blocked",
            "Translation or word-count source",
            "This source was set aside before questions or PDF generation.",
        ))
    elif review_status == "needs_info":
        question_count = len(review.get("questions") or [])
        flags.append(_attention_flag(
            "missing_required_info",
            "blocked",
            "Missing required information",
            f"{question_count} numbered question{'s' if question_count != 1 else ''} must be answered before generation.",
        ))
    elif review_status == "duplicate":
        flags.append(_attention_flag(
            "duplicate_request",
            "blocked",
            "Possible duplicate",
            "A drafted or sent request already matches this case/date/period.",
        ))
    elif review_status == "active_draft":
        flags.append(_attention_flag(
            "active_draft",
            "blocked",
            "Active draft exists",
            "Use correction mode only if this is an intentional replacement.",
        ))
    elif review_status == "error":
        flags.append(_attention_flag(
            "review_error",
            "blocked",
            "Review error",
            str(review.get("message") or "The intake could not be reviewed safely."),
        ))

    metadata_detail = _friendly_photo_metadata_detail(candidate, ai_recovery)
    if metadata_detail:
        flags.append(_attention_flag(
            "photo_metadata_needs_confirmation",
            "review",
            "Confirm photo date",
            metadata_detail,
        ))

    date_conflicts = [item for item in field_evidence if str(item.get("status") or "") == "conflicts_with_metadata"]
    if date_conflicts:
        service_date = str(candidate.get("service_date") or "").strip()
        confirmed = (
            service_date
            and str(candidate.get("service_date_source") or "").strip().lower() in CONFIRMED_SERVICE_DATE_SOURCES
            and all(str(item.get("value") or "").strip() == service_date for item in date_conflicts)
        )
        if confirmed:
            capture_date = str(candidate.get("photo_metadata_date") or date_conflicts[0].get("conflicts_with", {}).get("value") or "").strip()
            flags.append(_attention_flag(
                "date_conflict_resolved", "info", "Service date choice confirmed",
                f"You confirmed {service_date} as the service date. The photo date {capture_date} remains capture evidence; no further date answer is needed for this difference.",
            ))
        else:
            flags.append(_attention_flag(
                "date_conflict", "blocked", "Date conflict",
                "The recovered service date conflicts with image metadata and needs confirmation.",
            ))

    cleaned_warnings = [str(item).strip() for item in warnings if str(item).strip()]
    if cleaned_warnings:
        flags.append(_attention_flag(
            "source_warnings",
            "review",
            "Inspect source quality",
            "; ".join(cleaned_warnings[:3]),
        ))

    ai_status = str(ai_recovery.get("status") or "").strip()
    if ai_status in {"failed", "unavailable"}:
        flags.append(_attention_flag(
            "ai_recovery_issue",
            "review",
            "AI recovery issue",
            str(ai_recovery.get("reason") or "AI recovery did not produce usable evidence."),
        ))
    elif ai_status == "ok":
        missing_ai_fields = {str(field) for field in ai_recovery.get("missing_fields", [])}
        critical_missing: list[str] = []
        critical_map = {
            "case_number": "case_number",
            "service_date": "service_date",
            "payment_entity": "payment_entity",
            "court_email": "recipient_email",
            "service_place": "service_place",
        }
        for ai_field, intake_field in critical_map.items():
            if intake_field == "service_date" and metadata_detail:
                continue
            if ai_field in missing_ai_fields and not str(candidate.get(intake_field) or "").strip():
                critical_missing.append(intake_field)
        if critical_missing:
            flags.append(_attention_flag(
                "ai_missing_critical_fields",
                "review",
                "AI missed critical fields",
                "Still missing from the candidate: " + ", ".join(critical_missing),
            ))

    if str(profile_decision.get("mode") or "") == "auto_fallback":
        flags.append(_attention_flag(
            "profile_fallback",
            "review",
            "Review service profile fallback",
            str(profile_decision.get("reason") or "Auto-detect did not find a high-confidence service profile."),
        ))

    if str(profile_proposal.get("status") or "") not in {"", "not_needed"}:
        flags.append(_attention_flag(
            "profile_proposal",
            "review",
            "Reusable profile proposal",
            "A new recurring pattern can be previewed in the guarded profile editor.",
        ))

    status = "ready"
    if any(flag["severity"] == "blocked" for flag in flags):
        status = "blocked"
    elif any(flag["severity"] == "review" for flag in flags):
        status = "review"

    return {
        "status": status,
        "flag_count": len(flags),
        "flags": flags,
    }


def combine_text_parts(*parts: str) -> str:
    seen: set[str] = set()
    output: list[str] = []
    for part in parts:
        cleaned = str(part or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return "\n\n".join(output)


def fold_match_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _photo_metadata_date_source(candidate: dict[str, Any], metadata: dict[str, Any], ai_recovery: dict[str, Any]) -> str:
    metadata_date = str(metadata.get("exif_date") or metadata.get("visible_metadata_date") or candidate.get("photo_metadata_date") or "").strip()
    if not metadata_date:
        return "image_metadata"
    if str(metadata.get("exif_date") or "").strip() == metadata_date:
        return "image_metadata"
    if _ai_field_value(ai_recovery, "photo_metadata_date") == metadata_date:
        return "openai_ocr"
    if str(metadata.get("visible_metadata_date") or "").strip() == metadata_date:
        return "visible_google_photos_metadata"
    return "image_metadata"
