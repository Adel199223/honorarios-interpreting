// Only editable work survives reload. Server review and artifact permissions never do.
const omitted = new Set([
  "prepared_review", "preflight_review", "prepared_review_token", "review_fingerprint",
  "gmail_handoff_reviewed", "draft_id", "message_id", "thread_id", "draft_payload",
  "payload_paths", "manifest", "pdf", "pdf_sha256", "attachment_sha256",
  "png_preview_urls", "preview_url", "download_url", "artifact_url",
]);

export function workspaceInputCopy(value) {
  if (Array.isArray(value)) return value.map(workspaceInputCopy);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !omitted.has(key) && !key.endsWith("_url") && key !== "__proto__"
      && !/token|secret|credential|password|authorization|api_key|raw_response|provider_response/i.test(key))
    .map(([key, item]) => [key, workspaceInputCopy(item)]));
  return value;
}

export function workspaceReviewEvidence(review = {}) {
  return workspaceInputCopy(Object.fromEntries(["source", "source_evidence", "review_evidence", "ai_recovery"]
    .filter(key => review[key]).map(key => [key, review[key]])));
}

export function workspaceDraftSnapshot(state, fields = {}) {
  return {
    schema_version: 1,
    current_intake: workspaceInputCopy(state.currentIntake),
    current_evidence: workspaceReviewEvidence(state.lastReview || {}),
    source_cases: (state.sourceCaseCandidates || []).map(row => ({
      candidate_intake: workspaceInputCopy(row.candidate_intake),
      evidence: workspaceReviewEvidence(row.review || {}), answers: String(row.answers || ""),
      queued_key: String(row.queued_key || ""),
    })),
    selected_case: state.sourceCaseSelectedIndex,
    travel_choice: workspaceInputCopy(state.sourceTravelChoice),
    batch_intakes: (state.batchIntakes || []).map(workspaceInputCopy),
    answers: String(fields.answers || ""),
    email_grouping: fields.email_grouping === "individual" ? "individual" : "source",
    packet_mode: fields.packet_mode === true,
    manual_fields: fields.manual_fields ? workspaceInputCopy(fields.manual_fields) : null,
  };
}

export function workspaceDraftHasWork(snapshot) {
  return Boolean(snapshot?.current_intake || snapshot?.manual_fields || snapshot?.source_cases?.length || snapshot?.batch_intakes?.length);
}

export function workspaceDraftStorageKey(workspaceId) {
  if (!/^[a-f0-9]{64}$/.test(String(workspaceId || ""))) throw new Error("Workspace identity is unavailable; unfinished work cannot be saved yet.");
  return `honorarios.unfinished.v1.${workspaceId}`;
}

export function readWorkspaceDraft(storage, workspaceId) {
  const raw = storage.getItem(workspaceDraftStorageKey(workspaceId));
  if (!raw) return null;
  const value = JSON.parse(raw);
  if (value?.schema_version !== 1 || value.workspace_id !== workspaceId || !value.snapshot
      || value.snapshot.schema_version !== 1 || !Array.isArray(value.snapshot.source_cases)
      || !Array.isArray(value.snapshot.batch_intakes)) throw new Error("Saved unfinished work could not be read. It has been kept; discard it explicitly to start a new saved session.");
  return value;
}

export function writeWorkspaceDraft(storage, workspaceId, snapshot) {
  const record = { schema_version: 1, workspace_id: workspaceId, saved_at: new Date().toISOString(), snapshot };
  // setItem either replaces the complete value or leaves the previous one intact.
  storage.setItem(workspaceDraftStorageKey(workspaceId), JSON.stringify(record));
  return record;
}
