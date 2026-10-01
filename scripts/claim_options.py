"""Pure claim choices and explicitly identified shared travel, without inference."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Any

try:
    from scripts.entity_rules import normalize_text
    from scripts.request_identity import request_identity_key
except ModuleNotFoundError:
    from entity_rules import normalize_text
    from request_identity import request_identity_key


class ClaimError(ValueError):
    pass


def claim_flags(intake: dict[str, Any]) -> tuple[bool, bool]:
    interpreting = intake.get('claim_interpreting', True)
    transport = intake.get('claim_transport', False)
    if not isinstance(interpreting, bool) or not isinstance(transport, bool):
        raise ClaimError('Choose both, interpreting-only, or travel-only; claim flags must be true or false.')
    return interpreting, transport


def validate_claims(intake: dict[str, Any]) -> tuple[bool, bool]:
    flags = claim_flags(intake)
    if not any(flags):
        raise ClaimError('Choose at least one claim: interpreting-only, travel-only, or both. Remove a request that claims neither.')
    return flags


def profile_binding(profile: dict[str, Any]) -> str:
    """Bind CLI travel to the actual generator profile without exposing it."""
    values = {key: profile.get(key, '') for key in ('applicant_name', 'address', 'iban', 'signature_name', 'default_origin')}
    return 'profile:' + hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def travel_binding(intake: dict[str, Any], *, personal_profile_key: str = '') -> tuple[str, str, str, str, str]:
    selected_date = str(intake.get('service_date') or ('' if intake.get('photo_metadata_date_requires_confirmation') else intake.get('photo_metadata_date')) or '').strip()
    try:
        if date.fromisoformat(selected_date).isoformat() != selected_date:
            raise ValueError
    except ValueError as exc:
        raise ClaimError('A shared trip needs one confirmed date. Correct the date or choose separate trips.') from exc
    transport = intake.get('transport') if isinstance(intake.get('transport'), dict) else {}
    venue = ' '.join(normalize_text(str(intake.get('service_place') or intake.get('service_entity') or '')).split())
    destination = ' '.join(normalize_text(str(transport.get('destination') or intake.get('transport_destination') or '')).split())
    profile = str(intake.get('personal_profile_id') or personal_profile_key or '').strip()
    origin = ' '.join(normalize_text(str(transport.get('origin') or '')).split())
    if not venue or not destination or not profile:
        raise ClaimError('A shared trip needs a clear physical venue, travel destination, and selected personal profile. Complete these details or choose separate trips.')
    return selected_date, venue, destination, profile, origin


def claim_metadata(intake: dict[str, Any], *, personal_profile_key: str = '') -> dict[str, Any]:
    interpreting, transport = validate_claims(intake)
    metadata: dict[str, Any] = {'claim_interpreting': interpreting, 'claim_transport': transport}
    group = intake.get('travel_group_id')
    if group not in (None, ''):
        if not isinstance(group, str) or not group.strip() or len(group) > 160:
            raise ClaimError('travel_group_id must be a nonempty, bounded string identifying one explicit visit.')
        metadata.update(travel_group_id=group.strip(), travel_group_binding=list(travel_binding(intake, personal_profile_key=personal_profile_key)))
    return metadata


def validate_shared_travel_groups(intakes: list[dict[str, Any]], *, personal_profile_key: str = '', prior_requests: list[dict[str, Any]] | None = None) -> None:
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for intake in intakes:
        metadata = claim_metadata(intake, personal_profile_key=personal_profile_key)
        if metadata.get('travel_group_id'):
            groups.setdefault(metadata['travel_group_id'], []).append((intake, metadata))
    for group, members in groups.items():
        bindings = {tuple(metadata['travel_group_binding']) for _, metadata in members}
        if len(bindings) != 1:
            raise ClaimError('Shared trip details conflict: every grouped request must have the same date, physical venue, destination, and personal profile. Correct the group or choose separate trips.')
        owners = [intake for intake, metadata in members if metadata['claim_transport']]
        if len(owners) > 1:
            raise ClaimError('More than one request claims transport for the same shared trip. Choose one travel owner or mark genuinely separate trips.')
        for prior in prior_requests or []:
            if prior.get('travel_group_id') != group:
                continue
            binding = prior.get('travel_group_binding')
            if (not isinstance(binding, list) or len(binding) != 5
                    or not all(isinstance(value, str) for value in binding)
                    or not all(value.strip() for value in binding[:4])
                    or tuple(binding) not in bindings or not isinstance(prior.get('claim_transport'), bool)):
                raise ClaimError('An already recorded shared-trip claim has conflicting or unclear details. Review that record before preparing this visit.')
            if prior['claim_transport'] and owners and request_identity_key(prior) != request_identity_key(owners[0]):
                raise ClaimError('Transport for this explicit shared trip is already recorded on another request. Keep this request interpreting-only or review the existing travel owner.')


def recorded_travel_requests(*collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepared files do not reserve travel; only blocking recorded states do."""
    requests = []
    for records in collections:
        for record in records:
            if not isinstance(record, dict) or str(record.get('status') or 'sent').lower() not in {'active', 'drafted', 'sent'}:
                continue
            children = record.get('underlying_requests')
            requests.extend(children if isinstance(children, list) and children else [record])
    return [request for request in requests if isinstance(request, dict) and request.get('travel_group_id')]


def validate_travel_payload_groups(requests: list[dict[str, Any]], *, prior_requests: list[dict[str, Any]] | None = None) -> None:
    """Recheck retained trip bindings immediately before recording or Gmail."""
    intakes = []
    for request in requests:
        intake = dict(request)
        if request.get('travel_group_id'):
            binding = request.get('travel_group_binding')
            if not isinstance(binding, list) or len(binding) != 5 or not all(isinstance(value, str) for value in binding):
                raise ClaimError('The prepared shared-trip binding is missing or invalid. Review and prepare the request again.')
            if str(request.get('service_date') or '') != binding[0]:
                raise ClaimError('The prepared shared-trip date differs from its request. Review and prepare again.')
            intake.update(service_place=binding[1], personal_profile_id=binding[3],
                          transport={'destination': binding[2], 'origin': binding[4]})
        intakes.append(intake)
    validate_shared_travel_groups(intakes, prior_requests=prior_requests)
