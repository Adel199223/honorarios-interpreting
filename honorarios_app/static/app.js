const state = {
  reference: null,
  currentIntake: null,
  batchIntakes: [],
  batchSelectedIndex: null,
  batchPreflight: null,
  lastPrepared: null,
  aiStatus: null,
  googlePhotosStatus: null,
  gmailStatus: null,
  googlePhotosPicker: null,
  diagnosticsStatus: null,
  draftLifecycle: null,
  lastProfileProposal: null,
  localBackupPreview: null,
  legalPdfImportPreview: null,
  legalPdfPersonalProfileImportPreview: null,
  backupStatus: null,
  historyStatusFilter: "all",
  currentNextSafeAction: null,
  currentPersonalProfile: null,
  gmailCreateInFlight: false,
  gmailCreateCompletedPayload: "",
  lastGmailCreateConfirmation: null,
  lastManualHandoff: null,
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setStatus(status, message) {
  const pill = $("#status-pill");
  const summary = $("#review-status");
  const drawerStatus = $("#drawer-review-status");
  const normalized = status || "idle";

  pill.textContent = normalized.replaceAll("_", " ");
  pill.className = "status-chip";
  if (["ready", "prepared", "recorded", "verified"].includes(normalized)) {
    pill.classList.add("ready");
  } else if (["needs_info", "duplicate", "active_draft", "set_aside", "blocked", "reconciliation_mismatch"].includes(normalized)) {
    pill.classList.add("blocked");
  } else if (normalized === "error") {
    pill.classList.add("error");
  } else {
    pill.classList.add("info");
  }

  const text = message || "";
  summary.textContent = text;
  drawerStatus.textContent = text || "Review the Portuguese text, then create the PDF and Gmail draft payload.";
}

function setCard(element, message, kind = "") {
  if (!message) {
    element.className = "result-card hidden";
    element.textContent = "";
    return;
  }
  element.className = `result-card ${kind}`.trim();
  element.textContent = message;
}

function statusChipClass(status) {
  if (["ready", "prepared", "recorded", "clear", "active", "drafted", "sent"].includes(status)) return "ready";
  if (["needs_info", "duplicate", "active_draft", "set_aside", "blocked", "stale", "superseded", "trashed", "not_found", "reconciliation_mismatch"].includes(status)) return "blocked";
  if (status === "error") return "error";
  return "info";
}

const HISTORY_STATUS_FILTERS = ["all", "active", "drafted", "sent", "superseded", "trashed", "not_found"];

const SAFE_ACTION_GATES = {
  "apply-numbered-answers": {
    states: ["answer_questions"],
    reason: "Answer the numbered questions before continuing.",
  },
  "prepare-intake": {
    states: ["prepare_pdf"],
    reason: "Review a ready interpretation request before generating the PDF.",
  },
  "drawer-prepare-intake": {
    states: ["prepare_pdf"],
    reason: "Review a ready interpretation request before generating the PDF.",
  },
  "add-current-to-batch": {
    states: ["prepare_pdf"],
    reason: "Review a ready request before adding it to the batch queue.",
  },
  "prepare-batch-intakes": {
    states: [],
    reason: "Add at least one reviewed request to the batch queue first.",
  },
  "preflight-batch-intakes": {
    states: [],
    reason: "Add at least one reviewed request to the batch queue first.",
  },
  "prepare-replacement-draft": {
    states: ["choose_correction_mode"],
    reason: "Correction mode requires an active draft and a short correction reason.",
  },
  "copy-draft-args": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the PDF and Gmail draft payload before copying draft args.",
  },
  "build-manual-handoff": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the PDF and Gmail draft payload before building the manual handoff packet.",
  },
  "copy-manual-handoff-prompt": {
    states: ["review_gmail_draft_args"],
    reason: "Build the manual handoff packet before copying its prompt.",
  },
  "autofill-record-from-prepared": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the PDF and Gmail draft payload before autofilling record values.",
  },
  "record-parsed-prepared-draft": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the payload, create the Gmail draft manually, then paste the Gmail response.",
  },
  "create-gmail-api-draft": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the payload, review the PDF preview and exact Gmail args, then create the Gmail draft.",
  },
  "record-draft": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the payload and paste Gmail draft IDs before recording locally.",
  },
};

function setActionGate(id, enabled, reason = "", actionState = "idle") {
  const button = document.getElementById(id);
  if (!button) return;
  button.disabled = !enabled;
  button.setAttribute("aria-disabled", enabled ? "false" : "true");
  button.setAttribute("data-safe-action-state", actionState);
  button.classList.toggle("is-gated", !enabled);
  if (reason) {
    button.title = reason;
  } else {
    button.removeAttribute("title");
  }
}

function syncActionGates(action = state.currentNextSafeAction) {
  state.currentNextSafeAction = action || null;
  const actionState = String(action?.state || "idle");
  const actionDetail = String(action?.detail || "");
  Object.entries(SAFE_ACTION_GATES).forEach(([id, gate]) => {
    let enabled = (gate.states || []).includes(actionState);
    let blockedReason = gate.reason;
    if (id === "preflight-batch-intakes") {
      enabled = state.batchIntakes.length > 0;
    }
    if (id === "prepare-batch-intakes") {
      enabled = hasCurrentReadyBatchPreflight();
    }
    if (id === "prepare-replacement-draft") {
      enabled = enabled && Boolean($("#correction_reason")?.value.trim());
    }
    if (id === "apply-numbered-answers") {
      enabled = enabled && Boolean($("#numbered-answers")?.value.trim());
    }
    if (id === "record-parsed-prepared-draft") {
      const handoffReviewed = Boolean($("#gmail_handoff_reviewed")?.checked);
      if (!handoffReviewed) {
        blockedReason = "Review the PDF preview and exact Gmail args before local recording.";
      }
      enabled = enabled
        && Boolean($("#gmail-response-raw")?.value.trim())
        && handoffReviewed;
    }
    if (id === "build-manual-handoff") {
      enabled = enabled && Boolean(preparedRecordTarget()?.draft_payload);
    }
    if (id === "copy-manual-handoff-prompt") {
      enabled = enabled && Boolean(state.lastManualHandoff?.copyable_prompt);
    }
    if (id === "create-gmail-api-draft") {
      const handoffReviewed = Boolean($("#gmail_handoff_reviewed")?.checked);
      const connected = Boolean(state.gmailStatus?.connected);
      const targetPayload = preparedRecordTarget()?.draft_payload || "";
      if (!connected) {
        blockedReason = "Gmail Draft API is optional and not connected. Use Manual Draft Handoff now, or connect Gmail API before using this button.";
      } else if (!handoffReviewed) {
        blockedReason = "Review the PDF preview and exact Gmail args before creating the Gmail draft.";
      } else if (state.gmailCreateInFlight) {
        blockedReason = "Gmail draft creation is already in progress.";
      } else if (targetPayload && state.gmailCreateCompletedPayload === targetPayload) {
        blockedReason = "This prepared payload already created a Gmail draft. Change the request or prepare again before creating another.";
      }
      enabled = enabled
        && handoffReviewed
        && connected
        && Boolean(targetPayload)
        && !state.gmailCreateInFlight
        && state.gmailCreateCompletedPayload !== targetPayload;
    }
    if (id === "record-draft") {
      const targetPayload = preparedRecordTarget()?.draft_payload || "";
      if (targetPayload && state.gmailCreateCompletedPayload === targetPayload) {
        blockedReason = "This prepared payload was already recorded through Gmail Draft API. Change the request or prepare again before recording another draft.";
      }
      enabled = enabled
        && Boolean($("#record_payload")?.value.trim())
        && Boolean($("#record_draft_id")?.value.trim())
        && Boolean($("#record_message_id")?.value.trim())
        && (!targetPayload || state.gmailCreateCompletedPayload !== targetPayload);
    }
    setActionGate(id, enabled, enabled ? actionDetail : blockedReason, actionState);
  });
}

function clearPreparedArtifacts(reason = "stale prepared result") {
  state.lastPrepared = null;
  state.draftLifecycle = null;
  state.gmailCreateInFlight = false;
  state.gmailCreateCompletedPayload = "";
  state.lastGmailCreateConfirmation = null;
  state.lastManualHandoff = null;
  $("#prepare-results").innerHTML = "";
  $("#pdf-preview-panel").classList.add("hidden");
  $("#pdf-preview").innerHTML = "";
  $("#record_payload").value = "";
  $("#record_draft_id").value = "";
  $("#record_message_id").value = "";
  $("#record_thread_id").value = "";
  $("#record_supersedes").value = "";
  $("#gmail_handoff_reviewed").checked = false;
  $("#gmail-response-raw").value = "";
  const gmailResult = $("#gmail-api-result");
  if (gmailResult) {
    gmailResult.className = "result-card compact-result hidden";
    gmailResult.textContent = "";
  }
  const gmailVerifyResult = $("#gmail-verify-result");
  if (gmailVerifyResult) {
    gmailVerifyResult.className = "result-card compact-result hidden";
    gmailVerifyResult.textContent = "";
  }
  renderManualHandoffPacket(null);
  renderDraftLifecycle(null);
  syncActionGates(null);
  const message = String(reason || "").trim();
  if (message) {
    $("#prepare-results").setAttribute("data-stale-reason", message);
  }
}

function historyRecordStatus(record, defaultStatus = "") {
  return String(record?.status || defaultStatus || "").trim() || defaultStatus;
}

function filterHistoryRecords(records, defaultStatus = "") {
  const filter = state.historyStatusFilter || "all";
  const values = Array.isArray(records) ? records : [];
  if (filter === "all") return values;
  return values.filter((record) => historyRecordStatus(record, defaultStatus) === filter);
}

function indexedHistoryRecords(records, defaultStatus = "") {
  const filter = state.historyStatusFilter || "all";
  const values = Array.isArray(records) ? records : [];
  return values
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => filter === "all" || historyRecordStatus(item, defaultStatus) === filter)
    .reverse();
}

function historyStatusCounts() {
  const counts = Object.fromEntries(HISTORY_STATUS_FILTERS.map((status) => [status, 0]));
  const duplicates = state.reference?.duplicates || [];
  const draftLog = state.reference?.draft_log || [];
  duplicates.forEach((record) => {
    const status = historyRecordStatus(record, "sent");
    if (counts[status] !== undefined) counts[status] += 1;
  });
  draftLog.forEach((record) => {
    const status = historyRecordStatus(record, "");
    if (counts[status] !== undefined) counts[status] += 1;
  });
  counts.all = duplicates.length + draftLog.length;
  return counts;
}

function renderHistoryStatusFilters() {
  const box = $("#history-status-filters");
  if (!box) return;
  const counts = historyStatusCounts();
  box.innerHTML = HISTORY_STATUS_FILTERS.map((status) => {
    const active = state.historyStatusFilter === status;
    const label = status === "all" ? "All" : status;
    return `
      <button
        type="button"
        class="history-filter-chip status-chip ${active ? "ready is-active" : statusChipClass(status)}"
        data-history-status-filter="${escapeHtml(status)}"
        aria-pressed="${active ? "true" : "false"}">
        ${escapeHtml(label.replaceAll("_", " "))} · ${escapeHtml(counts[status] || 0)}
      </button>
    `;
  }).join("");
}

async function copyText(value) {
  const text = String(value || "");
  if (!text) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "readonly");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function todayIsoDate() {
  const date = new Date();
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 10);
}

function parseReferenceLines(value) {
  return String(value || "")
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function fillFormFromIntake(intake) {
  const values = {
    case_number: intake.case_number,
    service_date: intake.service_date,
    photo_metadata_date: intake.photo_metadata_date,
    service_period_label: intake.service_period_label,
    service_start_time: intake.service_start_time,
    service_end_time: intake.service_end_time,
    payment_entity: intake.payment_entity,
    recipient_email: intake.recipient_email,
    service_place: intake.service_place,
    km_one_way: intake.transport?.km_one_way,
    source_text: intake.source_text,
    personal_profile_id: intake.personal_profile_id,
    profile: intake.service_profile_key,
  };
  Object.entries(values).forEach(([id, value]) => {
    const input = $(`#${id}`);
    if (input && value !== undefined && value !== null && value !== "") {
      input.value = value;
    }
  });
  renderSupportingAttachmentList();
}

function mergeFormIntoCurrentIntake() {
  if (!state.currentIntake) return null;
  const payload = collectProfilePayload();
  const intake = { ...state.currentIntake };
  [
    "case_number",
    "service_date",
    "photo_metadata_date",
    "service_period_label",
    "service_start_time",
    "service_end_time",
    "payment_entity",
    "recipient_email",
    "service_place",
    "source_text",
    "personal_profile_id",
  ].forEach((key) => {
    if (payload[key]) intake[key] = payload[key];
  });
  if (payload.profile) {
    intake.service_profile_key = payload.profile;
  }
  if (payload.km_one_way) {
    intake.transport = { ...(intake.transport || {}), km_one_way: Number(payload.km_one_way) || payload.km_one_way };
  }
  state.currentIntake = intake;
  return intake;
}

function showAlert(message, kind = "") {
  setCard($("#alert"), message, kind);
}

function showQuestions(data) {
  const box = $("#questions");
  if (!data.questions || !data.questions.length) {
    box.className = "result-card hidden";
    box.innerHTML = "";
    return;
  }
  box.className = "result-card blocked";
  box.innerHTML = data.questions.map((question) => (
    `<div><strong>${question.number}.</strong> ${escapeHtml(question.question)} <span>${escapeHtml(question.answer_hint)}</span></div>`
  )).join("");
}

function renderNextSafeAction(action) {
  syncActionGates(action);
  const targets = [
    {
      card: $("#next-safe-action"),
      chip: $("#next-safe-action-chip"),
      body: $("#next-safe-action-body"),
    },
    {
      card: $("#drawer-next-safe-action"),
      chip: $("#drawer-next-safe-action-chip"),
      body: $("#drawer-next-safe-action-body"),
    },
  ];
  targets.forEach(({ card, chip, body }) => {
    if (!card || !chip || !body) return;
    if (!action) {
      card.className = "result-card next-safe-action-card hidden";
      chip.textContent = "Waiting";
      chip.className = "status-chip info";
      body.innerHTML = "";
      return;
    }
    const blocked = Boolean(action.blocked);
    card.className = `result-card next-safe-action-card ${blocked ? "blocked" : "ready"}`;
    chip.textContent = String(action.state || "next").replaceAll("_", " ");
    chip.className = `status-chip ${blocked ? "blocked" : "ready"}`;
    const targetButton = action.button_id
      ? `<div class="button-row compact-button-row"><button type="button" class="mini-button" data-next-action-target="${escapeHtml(action.button_id)}">Take me there</button></div>`
      : "";
    const whyText = action.why || "This suggested step explains why the app paused here and keeps risky actions gated until the review state changes.";
    const allowedText = action.allowed_next || action.title || "Review the current state before continuing.";
    const blockedText = action.blocked
      ? "PDF creation, Gmail draft creation, and local draft recording stay blocked until this step is resolved."
      : "Email sending is still blocked by design; any later Gmail or local record step must use reviewed draft-only data.";
    body.className = "next-safe-action-body";
    body.innerHTML = `
      <p class="safe-action-helper">This is the app's Suggested Next Step. It is not a separate task; it points to the next thing to review, answer, or click.</p>
      <div class="safe-action-summary-grid">
        <div>
          <span>Recommended next step</span>
          <strong>${escapeHtml(action.title || "Suggested next step")}</strong>
        </div>
        <div>
          <span>Why this appears</span>
          <p>${escapeHtml(whyText)}</p>
        </div>
        <div>
          <span>What is allowed now</span>
          <p>${escapeHtml(allowedText)}</p>
        </div>
        <div>
          <span>Still blocked</span>
          <p>${escapeHtml(blockedText)}</p>
        </div>
      </div>
      <p>${escapeHtml(action.detail || "Review the current state before continuing.")}</p>
      ${targetButton}
    `;
  });
}

function cloneIntake(intake) {
  return JSON.parse(JSON.stringify(intake || {}));
}

function batchIntakeKey(intake) {
  const period = String(intake?.service_period_label || "").trim().toLowerCase();
  return [
    String(intake?.case_number || "").trim().toUpperCase(),
    String(intake?.service_date || "").trim(),
    period,
  ].join("|");
}

function currentBatchPacketMode() {
  return Boolean($("#batch-packet-mode")?.checked);
}

function batchPreflightSignature(packetMode = currentBatchPacketMode(), intakes = state.batchIntakes) {
  return JSON.stringify({
    packet_mode: Boolean(packetMode),
    intakes: (Array.isArray(intakes) ? intakes : []).map(cloneIntake),
  });
}

function hasCurrentReadyBatchPreflight() {
  return state.batchPreflight?.status === "ready"
    && state.batchPreflight?.request_signature === batchPreflightSignature();
}

function pathBasename(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.split(/[\\/]/).filter(Boolean).pop() || text;
}

const SUPPORTING_ATTACHMENT_EMAIL_BODY = `Bom dia,

Venho por este meio, requerer o pagamento dos honorários devidos, em virtude de ter sido nomeado intérprete.

Poderão encontrar o requerimento de honorários e o(s) documento(s) comprovativo(s) em anexo.

Melhores cumprimentos,

Example Interpreter`;

function normalizeAttachmentList(value) {
  if (!value) return [];
  const values = Array.isArray(value) ? value : [value];
  return values.map((item) => String(item || "").trim()).filter(Boolean);
}

function ensureSupportingAttachmentEmailBody(intake) {
  if (!intake) return intake;
  const attachments = normalizeAttachmentList(intake.additional_attachment_files);
  if (attachments.length && !String(intake.email_body || "").trim()) {
    intake.email_body = SUPPORTING_ATTACHMENT_EMAIL_BODY;
  }
  return intake;
}

function mergeSupportingAttachmentsIntoIntake(intake, attachments = [], emailBody = "") {
  const target = { ...(intake || {}) };
  const existing = normalizeAttachmentList(target.additional_attachment_files);
  const incoming = normalizeAttachmentList(attachments);
  const merged = Array.from(new Set([...existing, ...incoming]));
  if (merged.length) {
    target.additional_attachment_files = merged;
  }
  if (emailBody && !String(target.email_body || "").trim()) {
    target.email_body = emailBody;
  }
  return ensureSupportingAttachmentEmailBody(target);
}

function renderSupportingAttachmentList() {
  const list = $("#supporting-attachment-list");
  if (!list) return;
  const attachments = normalizeAttachmentList(state.currentIntake?.additional_attachment_files);
  if (!attachments.length) {
    list.className = "supporting-attachment-list is-empty";
    list.textContent = "No supporting attachments yet.";
    return;
  }
  list.className = "supporting-attachment-list";
  list.innerHTML = attachments.map((file) => `
    <div class="supporting-attachment-item">
      <span>${escapeHtml(pathBasename(file))}</span>
      <code>${escapeHtml(file)}</code>
    </div>
  `).join("");
}

function addSupportingAttachmentToIntake(attachment) {
  const storedPath = String(attachment?.stored_path || "").trim();
  if (!storedPath) {
    throw new Error("Supporting attachment upload did not return a stored file path.");
  }
  if (!state.currentIntake) {
    state.currentIntake = removeEmpty(collectProfilePayload()) || {};
  }
  state.currentIntake = mergeSupportingAttachmentsIntoIntake(state.currentIntake, [storedPath]);
  clearPreparedArtifacts("supporting attachments changed");
  renderSupportingAttachmentList();
  syncActionGates();
  return state.currentIntake;
}

async function uploadSupportingAttachments(files) {
  const attachmentFiles = Array.from(files || []).filter(Boolean);
  if (!attachmentFiles.length) {
    throw new Error("Choose at least one supporting declaration or proof file first.");
  }
  if (!state.currentIntake) {
    await buildIntakeFromProfile();
  }
  const uploaded = [];
  for (const file of attachmentFiles) {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch("/api/attachments/upload", {
      method: "POST",
      body: form,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || data.message || `Supporting attachment upload failed: ${response.status}`);
    }
    addSupportingAttachmentToIntake(data.attachment);
    uploaded.push(data);
  }
  const count = uploaded.length;
  setDropStatus(`Added ${count} supporting attachment${count === 1 ? "" : "s"} for the draft payload.`, "ready");
  showAlert(`Added ${count} supporting attachment${count === 1 ? "" : "s"}. The email body now mentions the supporting document(s).`, "recorded");
  return uploaded;
}

function supportingAttachmentFiles(record) {
  if (!record) return [];
  const explicit = normalizeAttachmentList(record.additional_attachment_files);
  if (explicit.length) return explicit;
  const files = normalizeAttachmentList(record.attachment_files);
  const pdf = String(record.pdf || "").trim();
  if (!files.length) return [];
  if (!pdf) return files.slice(1);
  return files.filter((file) => file !== pdf);
}

function buildPacketRecordObject(packet) {
  return {
    payload: packet?.draft_payload || "",
    draft_id: "<paste Gmail draft id>",
    message_id: "<paste Gmail message id>",
    thread_id: "<paste Gmail thread id>",
    status: "active",
    gmail_tool: "_create_draft",
    send_allowed: false,
    underlying_requests: packet?.underlying_requests || [],
  };
}

function buildPacketRecordCommand(packet) {
  const payload = packet?.draft_payload || "<packet draft payload path>";
  return `python scripts/record_gmail_draft.py --payload "${payload}" --draft-id <draft-id> --message-id <message-id> --thread-id <thread-id>`;
}

function renderPacketRecordHelper(packet) {
  if (!packet) return "";
  const recordObject = buildPacketRecordObject(packet);
  const command = buildPacketRecordCommand(packet);
  const blockers = packet.underlying_requests || [];
  return `
    <div class="packet-record-helper">
      <div class="result-header">
        <div>
          <strong>Packet draft recording helper</strong>
          <p>After Gmail _create_draft returns IDs, use this to record the packet draft and all underlying duplicate blockers together.</p>
        </div>
        <span class="status-chip info">Record</span>
      </div>
      <div class="button-row compact-button-row">
        <button type="button" class="mini-button" data-copy-packet-record="json">Copy packet record JSON</button>
        <button type="button" class="mini-button" data-copy-packet-record="command">Copy packet record command</button>
      </div>
      <strong>Record command</strong>
      <pre class="draft-args">${escapeHtml(command)}</pre>
      <strong>Record JSON</strong>
      <pre class="draft-args">${escapeHtml(JSON.stringify(recordObject, null, 2))}</pre>
      <div class="underlying-duplicate-blockers">
        <strong>Underlying duplicate blockers</strong>
        ${blockers.length
          ? `<ul>${blockers.map((request) => {
              const period = request.service_period_label ? ` · ${request.service_period_label}` : "";
              return `<li><code>${escapeHtml(request.case_number || "case pending")}</code> · ${escapeHtml(request.service_date || "date pending")}${escapeHtml(period)}</li>`;
            }).join("")}</ul>`
          : "<p>No underlying requests returned for this packet.</p>"}
      </div>
    </div>
  `;
}

function getByPath(source, path) {
  return path.split(".").reduce((value, key) => {
    if (value && Object.prototype.hasOwnProperty.call(value, key)) {
      return value[key];
    }
    return undefined;
  }, source);
}

function firstStringAtPath(source, paths) {
  for (const path of paths) {
    const value = getByPath(source, path);
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function parseJsonFromText(text) {
  try {
    return JSON.parse(text);
  } catch (_) {
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(text.slice(start, end + 1));
      } catch (_) {
        return null;
      }
    }
  }
  return null;
}

function matchIdText(text, patterns) {
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) return match[1].trim().replace(/[",;]+$/g, "");
  }
  return "";
}

function parseGmailDraftIds(rawText) {
  const text = String(rawText || "").trim();
  if (!text) {
    throw new Error("Paste the Gmail _create_draft response before parsing IDs.");
  }

  const parsed = parseJsonFromText(text);
  const ids = {
    draft_id: parsed ? firstStringAtPath(parsed, [
      "draft_id",
      "draftId",
      "draft.id",
      "result.draft_id",
      "result.draftId",
      "result.draft.id",
      "id",
    ]) : "",
    message_id: parsed ? firstStringAtPath(parsed, [
      "message_id",
      "messageId",
      "message.id",
      "draft.message.id",
      "result.message_id",
      "result.messageId",
      "result.message.id",
      "result.draft.message.id",
    ]) : "",
    thread_id: parsed ? firstStringAtPath(parsed, [
      "thread_id",
      "threadId",
      "message.threadId",
      "message.thread_id",
      "draft.message.threadId",
      "draft.message.thread_id",
      "result.thread_id",
      "result.threadId",
      "result.message.threadId",
      "result.draft.message.threadId",
    ]) : "",
  };

  if (!ids.draft_id) {
    ids.draft_id = matchIdText(text, [
      /draft[_\s-]?id["':=\s]+([A-Za-z0-9_.:-]+)/i,
      /draftId["':=\s]+([A-Za-z0-9_.:-]+)/i,
    ]);
  }
  if (!ids.message_id) {
    ids.message_id = matchIdText(text, [
      /message[_\s-]?id["':=\s]+([A-Za-z0-9_.:-]+)/i,
      /messageId["':=\s]+([A-Za-z0-9_.:-]+)/i,
      /message\.id["':=\s]+([A-Za-z0-9_.:-]+)/i,
    ]);
  }
  if (!ids.thread_id) {
    ids.thread_id = matchIdText(text, [
      /thread[_\s-]?id["':=\s]+([A-Za-z0-9_.:-]+)/i,
      /threadId["':=\s]+([A-Za-z0-9_.:-]+)/i,
      /message\.threadId["':=\s]+([A-Za-z0-9_.:-]+)/i,
    ]);
  }

  if (!ids.draft_id && !ids.message_id && !ids.thread_id) {
    throw new Error("Could not find draft_id, message_id, or thread_id in the pasted Gmail response.");
  }
  return ids;
}

function applyParsedGmailDraftIds(ids) {
  if (ids.draft_id) $("#record_draft_id").value = ids.draft_id;
  if (ids.message_id) $("#record_message_id").value = ids.message_id;
  if (ids.thread_id) $("#record_thread_id").value = ids.thread_id;
  syncActionGates();
  return ids;
}

function preparedRecordTarget() {
  return state.lastPrepared?.packet || state.lastPrepared?.items?.[0] || null;
}

function currentPreparedReviewFields(payloadPath = "") {
  const review = state.lastPrepared?.prepared_review || null;
  if (!review) return {};
  const normalizedPayload = String(payloadPath || "").trim();
  const payloadPaths = Array.isArray(review.payload_paths) ? review.payload_paths : [];
  if (normalizedPayload && payloadPaths.length && !payloadPaths.includes(normalizedPayload)) {
    return {};
  }
  return removeEmpty({
    prepared_manifest: review.manifest,
    prepared_review_token: review.prepared_review_token,
    review_fingerprint: review.review_fingerprint,
  });
}

function renderManualHandoffPacket(packet) {
  const box = $("#manual-handoff-packet");
  if (!box) return;
  if (!packet) {
    box.className = "result-card compact-result hidden";
    box.innerHTML = "";
    return;
  }

  const status = String(packet.status || "ready");
  const chipClass = statusChipClass(status);
  const attachmentNames = Array.isArray(packet.attachment_basenames) ? packet.attachment_basenames : [];
  const hashes = packet.attachment_sha256 && typeof packet.attachment_sha256 === "object"
    ? packet.attachment_sha256
    : {};
  const hashRows = Object.entries(hashes).map(([file, hash]) => (
    `<li><code>${escapeHtml(pathBasename(file))}</code><span>${escapeHtml(hash)}</span></li>`
  )).join("");
  box.className = `result-card compact-result ${chipClass}`;
  box.innerHTML = `
    <div class="result-header compact-result-header">
      <div>
        <strong>${escapeHtml(packet.message || "Manual handoff packet ready.")}</strong>
        <p>Copy this prompt into the draft-only Gmail connector, then paste returned IDs back into this drawer.</p>
      </div>
      <span class="status-chip ${chipClass}">${escapeHtml(String(packet.mode || "manual_handoff").replaceAll("_", " "))}</span>
    </div>
    <div class="prepared-meta">
      <div>To: <code>${escapeHtml(packet.to || "")}</code></div>
      <div>Subject: <strong>${escapeHtml(packet.subject || "")}</strong></div>
      <div>Payload: <code>${escapeHtml(packet.payload_path || "")}</code></div>
      <div>Attachments: ${attachmentNames.length ? attachmentNames.map((name) => `<code>${escapeHtml(name)}</code>`).join(" ") : "none"}</div>
      <div>Attachment count: ${escapeHtml(packet.attachment_count || 0)}</div>
    </div>
    ${hashRows ? `
      <details class="attachment-hashes">
        <summary>Attachment hashes</summary>
        <ul>${hashRows}</ul>
      </details>
    ` : ""}
    <strong>Copy-ready handoff prompt</strong>
    <pre class="draft-args">${escapeHtml(packet.copyable_prompt || "")}</pre>
  `;
}

async function buildManualHandoffPacket() {
  const target = preparedRecordTarget();
  if (!target?.draft_payload) {
    throw new Error("Prepare a PDF and Gmail draft payload before building the manual handoff packet.");
  }
  const data = await requestJson("/api/gmail/manual-handoff", {
    method: "POST",
    body: JSON.stringify({
      payload: target.draft_payload,
      ...currentPreparedReviewFields(target.draft_payload),
    }),
  });
  state.lastManualHandoff = data;
  renderManualHandoffPacket(data);
  setStatus(data.status || "ready", data.message || "Manual handoff packet ready.");
  showAlert("Manual handoff packet ready to copy.", "recorded");
  syncActionGates();
  return data;
}

function preparedRecordNote(target) {
  if (!target) return "";
  if (target.packet_mode) {
    const count = target.underlying_requests?.length || 0;
    return `Prepared packet draft for ${count} underlying request${count === 1 ? "" : "s"}.`;
  }
  const parts = [target.case_number, target.service_date, target.service_period_label].filter(Boolean);
  return `Prepared draft for ${parts.join(" · ") || "reviewed request"}.`;
}

function autofillRecordFormFromPrepared() {
  const target = preparedRecordTarget();
  if (!target?.draft_payload) {
    throw new Error("Prepare a PDF and Gmail draft payload before autofilling the record form.");
  }

  const pastedIds = {
    draftId: $("#record_draft_id").value,
    messageId: $("#record_message_id").value,
    threadId: $("#record_thread_id").value,
  };

  $("#record_payload").value = target.draft_payload;
  $("#record_status").value = "active";
  if (!$("#record_notes").value.trim()) {
    $("#record_notes").value = preparedRecordNote(target);
  }

  $("#record_draft_id").value = pastedIds.draftId;
  $("#record_message_id").value = pastedIds.messageId;
  $("#record_thread_id").value = pastedIds.threadId;
  syncActionGates();
  return target;
}

async function recordFromParsedResponseAndPreparedPayload() {
  if (!$("#gmail_handoff_reviewed")?.checked) {
    throw new Error("Review the PDF preview and exact Gmail args before local recording.");
  }
  const ids = applyParsedGmailDraftIds(parseGmailDraftIds($("#gmail-response-raw").value));
  const target = autofillRecordFormFromPrepared();
  if (!ids.draft_id || !ids.message_id) {
    throw new Error("Parsed Gmail response must include draft_id and message_id before recording locally.");
  }
  const data = await recordPreparedDraftFromForm();
  return { ids, target, record: data };
}

function moveBatchIntake(fromIndex, toIndex) {
  const from = Number(fromIndex);
  const to = Number(toIndex);
  if (!Number.isInteger(from) || !Number.isInteger(to)) return false;
  if (from < 0 || from >= state.batchIntakes.length) return false;
  if (to < 0 || to >= state.batchIntakes.length) return false;
  if (from === to) return false;
  const [item] = state.batchIntakes.splice(from, 1);
  state.batchIntakes.splice(to, 0, item);
  state.batchPreflight = null;
  const selected = state.batchSelectedIndex;
  if (selected === from) {
    state.batchSelectedIndex = to;
  } else if (selected !== null && from < selected && to >= selected) {
    state.batchSelectedIndex = selected - 1;
  } else if (selected !== null && from > selected && to <= selected) {
    state.batchSelectedIndex = selected + 1;
  }
  renderBatchQueue();
  setStatus("ready", "Batch order updated for packet preparation.");
  return true;
}

function renderBatchItemInspector() {
  const card = $("#batch-item-inspector");
  const chip = $("#batch-item-inspector-chip");
  const body = $("#batch-item-inspector-body");
  if (!card || !chip || !body) return;
  const count = state.batchIntakes.length;
  if (!count) {
    state.batchSelectedIndex = null;
    card.className = "result-card packet-item-inspector empty-state";
    chip.textContent = "Select";
    chip.className = "status-chip info";
    body.textContent = "Select `Inspect` on a queued request to review its packet position, recipient, service place, kilometers, and attachment order.";
    return;
  }
  if (state.batchSelectedIndex === null || state.batchSelectedIndex >= count) {
    state.batchSelectedIndex = 0;
  }
  const index = state.batchSelectedIndex;
  const intake = state.batchIntakes[index];
  const attachments = supportingAttachmentFiles(intake);
  const sequence = [
    "Generated requerimento PDF",
    ...attachments.map((file) => pathBasename(file)),
  ];
  card.className = "result-card packet-item-inspector";
  chip.textContent = `Item ${index + 1} of ${count}`;
  chip.className = "status-chip ready";
  body.innerHTML = `
    <div class="inspector-grid">
      <div><span>Case</span><strong>${escapeHtml(intake.case_number || "case pending")}</strong></div>
      <div><span>Service date</span><strong>${escapeHtml(intake.service_date || "date pending")}</strong></div>
      <div><span>Period</span><strong>${escapeHtml(intake.service_period_label || "full service")}</strong></div>
      <div><span>Recipient</span><code>${escapeHtml(intake.recipient_email || "recipient pending")}</code></div>
      <div><span>Payment entity</span><strong>${escapeHtml(intake.payment_entity || "payment entity pending")}</strong></div>
      <div><span>Service place</span><strong>${escapeHtml(intake.service_place || "service place pending")}</strong></div>
      <div><span>Transport</span><strong>${escapeHtml(intake.transport?.destination || intake.service_place || "destination pending")} · ${escapeHtml(intake.transport?.km_one_way || "km pending")} km</strong></div>
      <div><span>Source</span><strong>${escapeHtml(intake.source_filename || intake.raw_case_number || "manual/reviewed intake")}</strong></div>
    </div>
    <div class="packet-sequence">
      <strong>Packet contents</strong>
      <ol>
        ${sequence.map((label, itemIndex) => (
          `<li>
            <span>${itemIndex === 0 ? "Generated requerimento PDF" : "Supporting attachment"}</span>
            <strong>${escapeHtml(label)}</strong>
          </li>`
        )).join("")}
      </ol>
    </div>
    <div class="supporting-attachments">
      <strong>Supporting attachments</strong>
      ${attachments.length
        ? `<ul>${attachments.map((file) => `<li><code>${escapeHtml(pathBasename(file))}</code></li>`).join("")}</ul>`
        : "<p>No supporting attachments queued for this request.</p>"}
    </div>
  `;
}

function renderBatchQueue() {
  const list = $("#batch-queue-list");
  const chip = $("#batch-count-chip");
  if (!list || !chip) return;
  const count = state.batchIntakes.length;
  chip.textContent = `${count} queued`;
  chip.className = `status-chip ${count ? "ready" : "info"}`;
  if (!count) {
    list.className = "result-card empty-state";
    list.textContent = "No requests queued yet.";
    renderBatchItemInspector();
    renderBatchPreflight();
    syncActionGates();
    return;
  }
  list.className = "result-card batch-list";
  list.innerHTML = state.batchIntakes.map((intake, index) => {
    const period = intake.service_period_label
      ? `${intake.service_period_label}${intake.service_start_time || intake.service_end_time ? ` ${intake.service_start_time || ""}-${intake.service_end_time || ""}` : ""}`
      : "full service";
    return `
      <div class="batch-item ${state.batchSelectedIndex === index ? "is-selected" : ""}" draggable="true" data-batch-index="${index}">
        <div class="batch-item-order">
          <span class="drag-handle" aria-hidden="true">::</span>
          <strong>${index + 1}</strong>
        </div>
        <div class="batch-item-main">
          <strong>${escapeHtml(intake.case_number || "case pending")}</strong>
          <div class="batch-item-meta">
            <span>${escapeHtml(intake.service_date || "date pending")}</span>
            <span>${escapeHtml(period)}</span>
            <span>${escapeHtml(intake.payment_entity || "payment entity pending")}</span>
            <code>${escapeHtml(intake.recipient_email || "recipient pending")}</code>
          </div>
        </div>
        <div class="batch-item-actions">
          <button type="button" class="mini-button" data-inspect-batch-index="${index}">Inspect</button>
          <button type="button" class="mini-button" data-move-batch-index="${index}" data-move-direction="up" ${index === 0 ? "disabled" : ""}>Move up</button>
          <button type="button" class="mini-button" data-move-batch-index="${index}" data-move-direction="down" ${index === state.batchIntakes.length - 1 ? "disabled" : ""}>Move down</button>
          <button type="button" class="mini-button" data-remove-batch-index="${index}">Remove</button>
        </div>
      </div>
    `;
  }).join("");
  renderBatchItemInspector();
  renderBatchPreflight();
  syncActionGates();
}

function renderBatchPreflight() {
  const card = $("#batch-preflight-result");
  if (!card) return;
  const data = state.batchPreflight;
  if (!data) {
    card.className = "result-card empty-state";
    card.textContent = state.batchIntakes.length
      ? "Run a non-writing batch preflight before preparing artifacts."
      : "Add reviewed requests, then run a non-writing batch preflight.";
    return;
  }
  if (data.request_signature !== batchPreflightSignature()) {
    card.className = "result-card blocked-card";
    card.innerHTML = `
      <div class="result-header">
        <div>
          <strong>Batch preflight is stale</strong>
          <p>The batch queue or packet mode changed after the last non-writing check. Run batch preflight again before preparing artifacts.</p>
        </div>
        <span class="status-chip blocked">stale</span>
      </div>
    `;
    return;
  }
  const status = data.status || "blocked";
  const items = Array.isArray(data.items) ? data.items : [];
  const blockers = Array.isArray(data.blockers) ? data.blockers : [];
  const packet = data.packet || null;
  card.className = `result-card ${status === "ready" ? "ready-card" : "blocked-card"}`;
  card.innerHTML = `
    <div class="result-header">
      <div>
        <strong>Batch preflight</strong>
        <p>${escapeHtml(data.message || "Preflight checked without writing files.")}</p>
      </div>
      <span class="status-chip ${statusChipClass(status)}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    <div class="data-grid">
      <div><span>Artifact effect</span><strong>${escapeHtml(data.artifact_effect || "none")}</strong></div>
      <div><span>Write allowed</span><strong>${data.write_allowed ? "yes" : "no"}</strong></div>
      <div><span>Send allowed</span><strong>${data.send_allowed ? "yes" : "no"}</strong></div>
      <div><span>Packet mode</span><strong>${data.packet_mode ? "yes" : "no"}</strong></div>
    </div>
    ${packet ? `
      <div class="data-item">
        <strong>Packet check</strong>
        <code>${escapeHtml(packet.recipient || packet.status || "")}</code>
        <span>${escapeHtml(packet.message || "")}</span>
      </div>
    ` : ""}
    ${blockers.length ? `
      <div class="supporting-attachments">
        <strong>Blockers</strong>
        <ul>${blockers.map((blocker) => `<li>${escapeHtml(blocker.message || "")}</li>`).join("")}</ul>
      </div>
    ` : ""}
    <div class="supporting-attachments">
      <strong>Queued request checks</strong>
      <ul>
        ${items.map((item) => `
          <li>
            <span class="status-chip ${statusChipClass(item.status || "blocked")}">${escapeHtml(item.status || "blocked")}</span>
            <strong>${escapeHtml(item.case_number || "case pending")}</strong>
            <span>${escapeHtml(item.service_date || "date pending")}</span>
            <code>${escapeHtml(item.recipient || "")}</code>
            <span>${escapeHtml(item.message || "")}</span>
          </li>
        `).join("")}
      </ul>
    </div>
  `;
}

function renderDraftLifecycle(data) {
  const chip = $("#draft-lifecycle-chip");
  const body = $("#draft-lifecycle-body");
  if (!chip || !body) return;
  const lifecycle = data || state.draftLifecycle;
  if (!lifecycle) {
    chip.textContent = "Check";
    chip.className = "status-chip info";
    body.textContent = "No active draft check yet.";
    return;
  }
  const status = lifecycle.status || "clear";
  chip.textContent = status.replaceAll("_", " ");
  chip.className = `status-chip ${statusChipClass(status)}`;
  const active = lifecycle.active_gmail_drafts || [];
  const duplicates = lifecycle.duplicate_records || (lifecycle.duplicate ? [lifecycle.duplicate] : []);
  const rows = [
    `<div>${escapeHtml(lifecycle.message || "Draft lifecycle checked.")}</div>`,
    `<div>Replacement allowed: <strong>${lifecycle.replacement_allowed ? "yes" : "no"}</strong></div>`,
  ];
  active.forEach((record) => {
    rows.push(`<div class="data-item"><strong>Active draft</strong><code>${escapeHtml(record.draft_id || "")}</code><span>${escapeHtml(record.recipient || "")}</span></div>`);
  });
  duplicates.forEach((record) => {
    rows.push(`<div class="data-item"><strong>${escapeHtml(record.status || "duplicate")}</strong><code>${escapeHtml(record.draft_id || record.pdf || "")}</code><span>${escapeHtml(record.recipient_email || record.recipient || "")}</span></div>`);
  });
  body.innerHTML = rows.join("");
  if (active.length && !$("#record_supersedes").value) {
    $("#record_supersedes").value = active.map((record) => record.draft_id).filter(Boolean).join(", ");
  } else if (!active.length && duplicates.length && !$("#record_supersedes").value) {
    $("#record_supersedes").value = duplicates.map((record) => record.draft_id).filter(Boolean).join(", ");
  }
}

function updateHomeReviewCard(data) {
  const card = $("#interpretation-review-home-result");
  const status = data.status || "idle";
  const title = data.case_number ? `${data.case_number} · ${data.service_date || "date pending"}` : status.replaceAll("_", " ");
  const recipient = data.recipient ? `<div>Recipient: <code>${escapeHtml(data.recipient)}</code></div>` : "";
  const duplicate = data.duplicate?.draft_id ? `<div>Existing draft: <code>${escapeHtml(data.duplicate.draft_id)}</code></div>` : "";
  const questions = data.questions?.length ? `<div>${data.questions.length} numbered question${data.questions.length === 1 ? "" : "s"} need an answer.</div>` : "";

  card.className = `result-card ${["ready", "prepared", "recorded"].includes(status) ? "ready" : ""}`.trim();
  if (["duplicate", "active_draft", "set_aside", "blocked", "needs_info"].includes(status)) {
    card.className = `result-card blocked`;
  }
  if (status === "error") {
    card.className = "result-card error";
  }
  card.innerHTML = `
    <div class="result-header">
      <div>
        <strong>${escapeHtml(title)}</strong>
        <p>${escapeHtml(data.message || "Review the recovered details before creating the PDF.")}</p>
      </div>
      <span class="status-chip ${status === "ready" ? "ready" : status === "error" ? "error" : status === "idle" ? "info" : "blocked"}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${recipient}
    ${duplicate}
    ${questions}
  `;
}

function renderFieldEvidence(fieldEvidence) {
  const entries = Array.isArray(fieldEvidence)
    ? fieldEvidence
    : Object.entries(fieldEvidence || {}).map(([field, item]) => ({ field, ...(item || {}) }));
  if (!entries.length) return "";
  const rows = entries.map((item) => {
    const confidence = String(item.confidence || "medium").toLowerCase().replace(/[^a-z0-9_-]/g, "");
    const status = String(item.status || "applied").toLowerCase().replace(/[^a-z0-9_-]/g, "");
    const rawValue = item.raw_value ? `<div><span>Raw</span><code>${escapeHtml(item.raw_value)}</code></div>` : "";
    const conflict = item.conflicts_with
      ? `<div><span>Conflict</span><code>${escapeHtml(item.conflicts_with.field || "field")} = ${escapeHtml(item.conflicts_with.value || "")}</code></div>`
      : "";
    const excerpt = item.excerpt ? `<p class="field-evidence-excerpt">${escapeHtml(item.excerpt)}</p>` : "";
    return `
      <div class="field-evidence-row">
        <div class="field-evidence-title">
          <strong>${escapeHtml(item.label || item.field || "Field")}</strong>
          <code>${escapeHtml(item.value || "not recovered")}</code>
        </div>
        <div class="field-evidence-meta">
          <span class="field-evidence-source">${escapeHtml(item.source || "unknown")}</span>
          <span class="field-evidence-confidence ${escapeHtml(confidence)}">${escapeHtml(item.confidence || "medium")}</span>
          <span class="field-evidence-status ${escapeHtml(status)}">${escapeHtml(item.status || "applied")}</span>
        </div>
        ${rawValue || conflict ? `<div class="field-evidence-extra">${rawValue}${conflict}</div>` : ""}
        ${item.reason ? `<p>${escapeHtml(item.reason)}</p>` : ""}
        ${excerpt}
      </div>
    `;
  }).join("");
  return `
    <div class="field-evidence-card">
      <div class="result-header compact-result-header">
        <div>
          <strong>Recovered Fields</strong>
          <p>Source and confidence for each value are evidence only; review and duplicate checks still decide the next step.</p>
        </div>
        <span class="status-chip info">Field Evidence</span>
      </div>
      <div class="field-evidence-grid">${rows}</div>
    </div>
  `;
}

function attentionChipClass(status) {
  if (status === "ready") return "ready";
  if (status === "blocked") return "blocked";
  if (status === "error") return "error";
  return "info";
}

function renderSourceAttention(attention) {
  const flags = Array.isArray(attention?.flags) ? attention.flags : [];
  const status = String(attention?.status || (flags.length ? "review" : "ready")).toLowerCase();
  const safeStatus = status.replace(/[^a-z0-9_-]/g, "");
  if (!flags.length) {
    return `
      <div class="source-attention-card attention-ready">
        <div class="result-header compact-result-header">
          <div>
            <strong>Review Attention</strong>
            <p>No upload attention flags. Continue with the normal review, duplicate, PDF, and draft-only checks.</p>
          </div>
          <span class="status-chip ready attention-severity">ready</span>
        </div>
      </div>
    `;
  }
  return `
    <div class="source-attention-card attention-${escapeHtml(safeStatus)}">
      <div class="result-header compact-result-header">
        <div>
          <strong>Review Attention</strong>
          <p>These flags summarize what needs human review before PDF or Gmail draft work.</p>
        </div>
        <span class="status-chip ${attentionChipClass(safeStatus)} attention-severity">${escapeHtml(status)}</span>
      </div>
      <div class="attention-flags">
        ${flags.map((flag) => {
          const severity = String(flag.severity || "review").toLowerCase().replace(/[^a-z0-9_-]/g, "");
          return `
            <div class="attention-flag ${escapeHtml(severity)}">
              <span class="attention-code">${escapeHtml(flag.code || "review")}</span>
              <strong>${escapeHtml(flag.title || "Review")}</strong>
              <p>${escapeHtml(flag.detail || "")}</p>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function renderSourceEvidence(data) {
  const box = $("#source-evidence");
  const body = $("#source-evidence-body");
  const reviewEvidence = data?.review_evidence || null;
  if (!data?.source && !reviewEvidence) {
    box.className = "result-card hidden";
    body.innerHTML = "";
    return;
  }
  const evidence = data.source_evidence || reviewEvidence || {};
  const source = data.source || {
    source_kind: "manual_review",
    filename: evidence.filename || "Manual review",
    artifact_url: "",
    sha256: "",
    metadata: {},
  };
  const metadata = source.metadata || {};
  const warnings = evidence.warnings || metadata.warnings || [];
  const profileDecision = evidence.auto_profile || data.candidate_intake?.auto_profile || {};
  const profileProposal = evidence.profile_proposal || data.profile_proposal || {};
  const profileSummary = profileDecision.profile_key
    ? `${profileDecision.mode || "auto"}: ${profileDecision.profile_key}${profileDecision.suggested_profile_key && profileDecision.suggested_profile_key !== profileDecision.profile_key ? ` (suggested ${profileDecision.suggested_profile_key})` : ""}`
    : "not decided";
  const fieldEvidence = renderFieldEvidence(evidence.field_evidence || []);
  const sourceAttention = renderSourceAttention(evidence.attention || {});
  const proposalPayload = profileProposal.payload || {};
  const proposal = profileProposal.status && profileProposal.status !== "not_needed"
    ? `<div class="profile-proposal-card">
        <strong>Profile proposal</strong>
        <p>${escapeHtml(profileProposal.reason || "A reusable profile can be proposed from this source.")}</p>
        <div><span>Key</span><code>${escapeHtml(proposalPayload.key || "pending")}</code></div>
        <div><span>Status</span><code>${escapeHtml(profileProposal.status || "")}</code></div>
        <div><span>Missing</span><code>${escapeHtml((profileProposal.missing || []).join(", ") || "none")}</code></div>
        <button type="button" class="mini-button" data-use-profile-proposal="true">Preview proposed profile</button>
      </div>`
    : "";
  const renderedPageUrls = evidence.rendered_page_urls || [];
  const preview = source.source_kind === "manual_review"
    ? `<div class="manual-evidence-placeholder">
        <strong>Manual review evidence</strong>
        <p>The app used the typed/pasted fields and source text to suggest service-profile defaults before any PDF or Gmail draft step.</p>
      </div>`
    : source.source_kind === "photo"
    ? `<img class="source-preview-image" src="${escapeHtml(source.artifact_url)}" alt="Uploaded source preview">`
    : renderedPageUrls.length
      ? `<div class="rendered-page-strip">
          <strong>Rendered PDF pages</strong>
          ${renderedPageUrls.map((url, index) => `<img class="source-preview-image rendered-page-image" src="${escapeHtml(url)}" alt="Rendered PDF page ${index + 1}">`).join("")}
          <a class="source-preview-link" href="${escapeHtml(source.artifact_url)}" target="_blank" rel="noreferrer">Open original PDF source</a>
        </div>`
      : `<a class="source-preview-link" href="${escapeHtml(source.artifact_url)}" target="_blank" rel="noreferrer">Open uploaded PDF source</a>`;
  body.innerHTML = `
    ${sourceAttention}
    <div class="source-evidence-layout">
      <div class="source-evidence-list">
        <div><span>Filename</span><strong>${escapeHtml(evidence.filename || source.filename)}</strong></div>
        <div><span>Case</span><code>${escapeHtml(evidence.case_number || "not recovered")}</code></div>
        <div><span>Raw case</span><code>${escapeHtml(evidence.raw_case_number || "")}</code></div>
        <div><span>Profile Decision</span><code>${escapeHtml(profileSummary)}</code></div>
        <div><span>Profile reason</span><code>${escapeHtml(profileDecision.reason || profileDecision.suggestion_reason || "")}</code></div>
        <div><span>Service date</span><code>${escapeHtml(evidence.service_date || "needs review")}</code></div>
        <div><span>Metadata date</span><code>${escapeHtml(evidence.photo_metadata_date || metadata.exif_date || metadata.visible_metadata_date || "")}</code></div>
        <div><span>Recipient</span><code>${escapeHtml(evidence.recipient_email || "profile/default")}</code></div>
        <div><span>AI Recovery</span><code>${escapeHtml(evidence.ai_status || "not attempted")}</code></div>
        <div><span>AI Schema</span><code>${escapeHtml(evidence.ai_schema_name || "")}</code></div>
        <div><span>AI Prompt</span><code>${escapeHtml(evidence.ai_prompt_version || "")}</code></div>
        <div><span>Warnings</span><code>${escapeHtml(warnings.join("; ") || "none")}</code></div>
        <div><span>Rendered pages</span><strong>${escapeHtml(evidence.rendered_page_count || renderedPageUrls.length || 0)}</strong></div>
        <div><span>Questions</span><strong>${escapeHtml(evidence.question_count || 0)}</strong></div>
        <div><span>SHA-256</span><code>${escapeHtml((source.sha256 || "").slice(0, 16))}</code></div>
        ${proposal}
      </div>
      <div>${preview}</div>
    </div>
    ${fieldEvidence}
  `;
  box.className = "result-card";
}

function renderAiRecovery(aiRecovery) {
  const box = $("#ai-recovery-evidence");
  const body = $("#ai-recovery-evidence-body");
  const chip = $("#ai-recovery-status-chip");
  if (!aiRecovery) {
    box.className = "result-card hidden";
    body.innerHTML = "";
    chip.textContent = "AI";
    chip.className = "status-chip info";
    return;
  }
  const status = aiRecovery.status || "unknown";
  const fields = aiRecovery.fields || {};
  const missingFields = aiRecovery.missing_fields || [];
  const warnings = aiRecovery.warnings || [];
  const indicators = aiRecovery.translation_indicators || [];
  const rawText = aiRecovery.raw_visible_text || "";
  chip.textContent = status.replaceAll("_", " ");
  chip.className = `status-chip ${status === "ok" ? "ready" : status === "failed" ? "error" : "info"}`;
  body.innerHTML = `
    <div class="source-evidence-list ai-recovery-list">
      <div><span>Provider</span><code>${escapeHtml(aiRecovery.provider || "openai")}</code></div>
      <div><span>Model</span><code>${escapeHtml(aiRecovery.model || "")}</code></div>
      <div><span>Schema</span><code>${escapeHtml(aiRecovery.schema_name || "")}</code></div>
      <div><span>Prompt version</span><code>${escapeHtml(aiRecovery.prompt_version || "")}</code></div>
      <div><span>Attempted</span><strong>${aiRecovery.attempted ? "yes" : "no"}</strong></div>
      <div><span>Reason</span><code>${escapeHtml(aiRecovery.reason || "")}</code></div>
      <div><span>Fields found</span><code>${escapeHtml(Object.keys(fields).join(", ") || "none")}</code></div>
      <div><span>Fields not found</span><code>${escapeHtml(missingFields.join(", ") || "none")}</code></div>
      <div><span>Warnings</span><code>${escapeHtml(warnings.join("; "))}</code></div>
      <div><span>Translation indicators</span><code>${escapeHtml(indicators.join("; "))}</code></div>
    </div>
    ${rawText ? `<details class="ai-raw-text"><summary>Raw visible text</summary><pre>${escapeHtml(rawText)}</pre></details>` : ""}
  `;
  box.className = "result-card";
}

function openReviewDrawer() {
  const backdrop = $("#interpretation-review-drawer-backdrop");
  backdrop.classList.remove("hidden");
  document.body.dataset.interpretationReviewDrawer = "open";
}

function closeReviewDrawer() {
  const backdrop = $("#interpretation-review-drawer-backdrop");
  backdrop.classList.add("hidden");
  document.body.dataset.interpretationReviewDrawer = "closed";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || data.message || `Request failed: ${response.status}`);
  }
  return data;
}

function inferDroppedSourceKind(file) {
  const name = String(file?.name || "").toLowerCase();
  const type = String(file?.type || "").toLowerCase();
  if (type === "application/pdf" || name.endsWith(".pdf")) return "notification_pdf";
  if (type.startsWith("image/") || /\.(png|jpe?g|webp|heic|heif|bmp|gif|tiff?)$/.test(name)) return "photo";
  throw new Error("Unsupported source type. Use a PDF, photo, or screenshot.");
}

function setDropStatus(message, kind = "info") {
  const status = $("#source-drop-status");
  if (!status) return;
  status.textContent = message;
  status.className = `field-hint source-drop-status ${kind}`.trim();
}

function getClipboardSourceFile(event) {
  const clipboard = event.clipboardData;
  if (!clipboard) return null;
  const files = Array.from(clipboard.files || []);
  const directFile = files.find((file) => {
    try {
      inferDroppedSourceKind(file);
      return true;
    } catch {
      return false;
    }
  });
  if (directFile) return directFile;
  for (const item of Array.from(clipboard.items || [])) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (!file) continue;
    try {
      inferDroppedSourceKind(file);
      return file;
    } catch {}
  }
  return null;
}

function isEditablePasteTarget(target) {
  if (!target || !(target instanceof Element)) return false;
  return Boolean(target.closest("input, textarea, select, [contenteditable='true'], [contenteditable='']"));
}

async function recoverLocalSourceFile(file, origin = "local source") {
  const sourceKind = inferDroppedSourceKind(file);
  setDropStatus(`Recovering ${file.name || origin}...`);
  await uploadSource(sourceKind, { file });
}

async function uploadSource(sourceKind, options = {}) {
  const fileInput = sourceKind === "notification_pdf"
    ? $("#notification-file")
    : sourceKind === "google_photos"
      ? $("#google-photos-file")
      : $("#photo-file");
  const file = options.file || fileInput.files?.[0];
  if (!file) {
    if (sourceKind === "notification_pdf") throw new Error("Choose a PDF first.");
    if (sourceKind === "google_photos") throw new Error("Choose a Google Photos image first.");
    throw new Error("Choose a photo or screenshot first.");
  }
  clearPreparedArtifacts("source changed");
  const googlePhotosMetadata = sourceKind === "google_photos" ? $("#google-photos-metadata").value.trim() : "";
  const visibleText = [$("#source_text").value.trim(), googlePhotosMetadata, options.visibleText || ""].filter(Boolean).join("\n\n");
  const form = new FormData();
  form.append("file", file);
  form.append("source_kind", sourceKind === "google_photos" ? "photo" : sourceKind);
  form.append("profile", $("#profile").value || "");
  form.append("personal_profile_id", $("#personal_profile_id").value || "");
  form.append("visible_text", visibleText);
  if (googlePhotosMetadata) {
    form.append("visible_metadata_text", googlePhotosMetadata);
  }
  form.append("ai_recovery", $("#ai_recovery_mode").value || "auto");
  const existingAttachments = normalizeAttachmentList(state.currentIntake?.additional_attachment_files);
  const existingEmailBody = String(state.currentIntake?.email_body || "").trim();

  const response = await fetch("/api/sources/upload", {
    method: "POST",
    body: form,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || data.message || `Upload failed: ${response.status}`);
  }
  state.currentIntake = mergeSupportingAttachmentsIntoIntake(data.candidate_intake, existingAttachments, existingEmailBody);
  if (data.review?.intake) {
    data.review.intake = state.currentIntake;
  }
  state.lastProfileProposal = data.profile_proposal || null;
  fillFormFromIntake(state.currentIntake);
  renderSourceEvidence(data);
  renderAiRecovery(data.ai_recovery);
  applyReview(data.review);
  setDropStatus(`Recovered ${file.name || "dropped source"} as ${sourceKind === "notification_pdf" ? "notification PDF" : "photo/screenshot"}.`, "ready");
  return data;
}

function bindSourceDropZone() {
  const dropZone = $("#source-drop-zone");
  if (!dropZone) return;
  const stop = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  ["dragenter", "dragover"].forEach((name) => {
    dropZone.addEventListener(name, (event) => {
      stop(event);
      dropZone.classList.add("is-dragover");
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      setDropStatus("Release to recover the local source. No PDF or Gmail draft will be created yet.");
    });
  });
  ["dragleave", "dragend"].forEach((name) => {
    dropZone.addEventListener(name, (event) => {
      stop(event);
      dropZone.classList.remove("is-dragover");
    });
  });
  dropZone.addEventListener("drop", async (event) => {
    stop(event);
    dropZone.classList.remove("is-dragover");
    const files = Array.from(event.dataTransfer.files || []);
    const file = files[0];
    if (!file) {
      setDropStatus("No local file was dropped.", "blocked");
      return;
    }
    try {
      await recoverLocalSourceFile(file, "dropped source");
      if (files.length > 1) {
        await uploadSupportingAttachments(files.slice(1));
      }
    } catch (error) {
      setDropStatus(error.message, "blocked");
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  dropZone.addEventListener("paste", async (event) => {
    const file = getClipboardSourceFile(event);
    if (!file) {
      setDropStatus("Clipboard does not contain a PDF, photo, or screenshot.", "blocked");
      return;
    }
    stop(event);
    try {
      await recoverLocalSourceFile(file, "pasted source");
    } catch (error) {
      setDropStatus(error.message, "blocked");
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  document.addEventListener("paste", async (event) => {
    if (dropZone.contains(event.target) || isEditablePasteTarget(event.target)) return;
    const file = getClipboardSourceFile(event);
    if (!file) return;
    stop(event);
    try {
      await recoverLocalSourceFile(file, "pasted source");
    } catch (error) {
      setDropStatus(error.message, "blocked");
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
}

async function loadReference() {
  state.reference = await requestJson("/api/reference");
  state.aiStatus = state.reference?.ai || null;
  state.gmailStatus = state.reference?.gmail?.api || null;
  state.backupStatus = state.reference?.backup || null;
  renderReference();
  renderAiStatus(state.aiStatus);
  renderGmailStatus(state.gmailStatus);
  renderBackupStatus(state.backupStatus);
}

async function loadAiStatus() {
  state.aiStatus = await requestJson("/api/ai/status");
  renderAiStatus(state.aiStatus);
}

async function loadBackupStatus() {
  state.backupStatus = await requestJson("/api/backup/status");
  renderBackupStatus(state.backupStatus);
  return state.backupStatus;
}

async function loadGooglePhotosStatus() {
  state.googlePhotosStatus = await requestJson("/api/google-photos/status");
  renderGooglePhotosStatus(state.googlePhotosStatus);
}

async function loadGmailStatus() {
  state.gmailStatus = await requestJson("/api/gmail/status");
  renderGmailStatus(state.gmailStatus);
  return state.gmailStatus;
}

function diagnosticCommand(check) {
  return String(check?.command_template || "").replaceAll("{base_url}", window.location.origin);
}

function renderDiagnosticsStatus(data) {
  const chip = $("#diagnostics-chip");
  const body = $("#diagnostics-result");
  if (!chip || !body) return;
  const status = data?.status || "blocked";
  const chipKind = statusChipClass(status);
  chip.textContent = status.replaceAll("_", " ");
  chip.className = `status-chip ${chipKind}`;
  const checks = Array.isArray(data?.checks) ? data.checks : [];
  const recommended = String(data?.recommended_next_check || "");
  body.className = `result-card compact-result ${chipKind}`;
  body.innerHTML = `
    <div class="result-header compact-result-header">
      <div>
        <strong>${escapeHtml(data?.message || "Diagnostics status is not loaded yet.")}</strong>
        <p>Commands are copied locally for PowerShell. The browser does not run shell commands or contact Gmail.</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    <div class="diagnostics-grid">
      ${checks.map((check) => {
        const key = String(check.key || "");
        const isRecommended = key && key === recommended;
        const command = diagnosticCommand(check);
        return `
          <div class="diagnostic-item ${isRecommended ? "is-recommended" : ""}">
            <div class="result-header compact-result-header">
              <div>
                <strong>${escapeHtml(check.label || key || "Diagnostic check")}</strong>
                <p>${escapeHtml(check.description || "")}</p>
              </div>
              ${isRecommended ? '<span class="status-chip ready">recommended</span>' : `<span class="status-chip info">${escapeHtml(check.effect || "safe")}</span>`}
            </div>
            <div class="diagnostic-meta">
              <span>Writes: ${escapeHtml(check.writes || "none")}</span>
            </div>
            <pre class="diagnostic-command">${escapeHtml(command)}</pre>
            <button type="button" class="mini-button" data-copy-diagnostic-command="${escapeHtml(key)}">Copy command</button>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

async function loadDiagnosticsStatus() {
  state.diagnosticsStatus = await requestJson("/api/diagnostics/status");
  renderDiagnosticsStatus(state.diagnosticsStatus);
  return state.diagnosticsStatus;
}

async function copyDiagnosticCommand(key) {
  if (!state.diagnosticsStatus) {
    await loadDiagnosticsStatus();
  }
  const check = (state.diagnosticsStatus?.checks || []).find((item) => item.key === key);
  if (!check) throw new Error("Diagnostic command is not available yet. Refresh diagnostics first.");
  await copyText(diagnosticCommand(check));
  showAlert(`Copied ${check.label || key} command.`, "recorded");
}

function renderGooglePhotosPickerResult(data, kind = "info") {
  const box = $("#google-photos-picker-result");
  if (!box) return;
  if (!data) {
    box.className = "result-card compact-result hidden";
    box.innerHTML = "";
    return;
  }
  const status = data.status || kind || "info";
  const chipKind = statusChipClass(status === "picker_session_created" || status === "media_items_ready" ? "ready" : status);
  const sessionId = data.session_id ? `<div>Session: <code>${escapeHtml(data.session_id)}</code></div>` : "";
  const selected = data.selected_count !== undefined ? `<div>Selected items: <strong>${escapeHtml(data.selected_count)}</strong></div>` : "";
  const filename = data.google_photos?.imported_filename || data.imported_filename || "";
  const imported = filename ? `<div>Imported: <code>${escapeHtml(filename)}</code></div>` : "";
  const items = (data.items || []).map((item) => (
    `<div class="data-item"><strong>${escapeHtml(item.filename || "Google Photos item")}</strong><span>${escapeHtml(item.mime_type || "")}</span></div>`
  )).join("");
  box.className = `result-card compact-result ${chipKind}`;
  box.innerHTML = `
    <div class="result-header">
      <div>
        <strong>${escapeHtml(data.message || status.replaceAll("_", " "))}</strong>
        <p>Google Photos import stays source-only and draft-safe.</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${sessionId}
    ${selected}
    ${imported}
    ${items}
  `;
}

function renderAiStatus(data) {
  const summary = $("#ai-status-summary");
  const pill = $("#ai-status-pill");
  if (!summary || !pill) return;
  const configured = Boolean(data?.configured);
  const keyConfigured = Boolean(data?.key_configured);
  pill.textContent = configured ? "ready" : keyConfigured ? "install needed" : "key missing";
  pill.className = `status-chip ${configured ? "ready" : "blocked"}`;
  if (configured) {
    summary.textContent = `OpenAI recovery is available through ${data.key_source || "configured key"} using ${data.model || "default model"}.`;
  } else if (keyConfigured && data?.package_available === false) {
    summary.textContent = "An OpenAI key is configured, but the openai Python package is not installed in this environment.";
  } else {
    summary.textContent = "Set OPENAI_API_KEY or config/ai.local.json to enable OCR/autofill. The key is never shown here.";
  }
}

function renderGooglePhotosStatus(data) {
  const summary = $("#google-photos-status-summary");
  const pill = $("#google-photos-status-pill");
  if (!summary || !pill) return;
  const connected = Boolean(data?.connected);
  const configured = Boolean(data?.configured);
  pill.textContent = connected ? "picker ready" : configured ? "oauth config" : "manual bridge";
  pill.className = `status-chip ${connected ? "ready" : "info"}`;
  if (connected) {
    summary.textContent = "Google Photos OAuth Picker is connected. Open the Picker, choose one photo, then import the selected item through the normal review flow.";
  } else if (configured) {
    summary.textContent = "Google Photos OAuth credentials are configured. Connect Google Photos OAuth, or use the selected-photo local import with pasted metadata.";
  } else {
    summary.textContent = data?.message || "OAuth Picker is not connected in this standalone app yet. Use selected-photo import with pasted metadata.";
  }
}

function renderGmailSetup(data) {
  const setup = data?.setup || {};
  const card = $("#gmail-setup-card");
  const chip = $("#gmail-setup-chip");
  const nextStep = $("#gmail-setup-next-step");
  const redirect = $("#gmail-redirect-uri");
  if (!card) return;
  const connected = Boolean(data?.connected);
  const configured = Boolean(data?.configured);
  const manualReady = Boolean(data?.manual_handoff_ready);
  const setupStatus = setup.status || (connected ? "ready" : manualReady ? "manual_handoff" : configured ? "connect" : "configure");
  const chipKind = connected ? "ready" : manualReady ? "info" : configured ? "info" : "blocked";
  if (chip) {
    chip.textContent = setupStatus;
    chip.className = `status-chip ${chipKind}`;
  }
  if (nextStep) {
    nextStep.textContent = setup.next_step || "Manual Draft Handoff is always available. Connect Gmail API only when you want optional in-app draft creation.";
  }
  if (redirect && !redirect.dataset.userEdited) {
    redirect.value = setup.redirect_uri || redirect.value || "http://127.0.0.1:8766/api/gmail/oauth/callback";
  }
}

function renderGmailStatus(data) {
  const summary = $("#gmail-api-status-summary");
  const pill = $("#gmail-api-status-pill");
  const drawerStatus = $("#gmail-api-drawer-status");
  const drawerChip = $("#gmail-api-drawer-chip");
  const manualStatus = $("#manual-handoff-status");
  const manualChip = $("#manual-handoff-chip");
  const deferredPanel = $("#gmail-api-deferred-panel");
  const connected = Boolean(data?.connected);
  const configured = Boolean(data?.configured);
  const manualReady = Boolean(data?.manual_handoff_ready);
  const recommendedMode = data?.recommended_mode || (connected ? "gmail_api" : "manual_handoff");
  const text = data?.message || "Gmail Draft API status is not loaded yet.";
  const chipText = recommendedMode === "gmail_api" ? "Gmail connected" : "Manual handoff";
  const chipKind = recommendedMode === "gmail_api" ? "ready" : manualReady ? "info" : "blocked";
  if (summary) {
    summary.textContent = recommendedMode === "gmail_api"
      ? `${text} Manual Draft Handoff remains available as a safe fallback.`
      : "Manual Draft Handoff is active: prepare the PDF and draft payload, use the exact _create_draft args, then record returned draft IDs locally.";
  }
  if (pill) {
    pill.textContent = chipText;
    pill.className = `status-chip ${chipKind}`;
  }
  if (manualStatus) {
    manualStatus.textContent = recommendedMode === "gmail_api"
      ? "Gmail API is connected. Manual Draft Handoff remains available as a safe fallback for recovery or connector-based drafting."
      : "Manual Draft Handoff is the supported primary mode when Gmail OAuth is not connected.";
  }
  if (manualChip) {
    manualChip.textContent = recommendedMode === "gmail_api" ? "Fallback" : "Recommended";
    manualChip.className = `status-chip ${recommendedMode === "gmail_api" ? "info" : "ready"}`;
  }
  if (deferredPanel) {
    deferredPanel.open = recommendedMode === "gmail_api";
  }
  if (drawerStatus) {
    drawerStatus.textContent = `${text} Scope: ${data?.scope || "gmail.compose"}. Direct in-app creation stays optional; no send action exists.`;
  }
  if (drawerChip) {
    drawerChip.textContent = connected ? "connected" : configured ? "optional" : "later";
    drawerChip.className = `status-chip ${chipKind}`;
  }
  renderGmailSetup(data);
  syncActionGates();
}

async function saveGmailConfig() {
  const resultBox = $("#gmail-config-result");
  const clientId = $("#gmail-client-id")?.value.trim() || "";
  const clientSecret = $("#gmail-client-secret")?.value.trim() || "";
  const redirectUri = $("#gmail-redirect-uri")?.value.trim() || "";
  if (!clientId || !clientSecret) {
    throw new Error("Paste both the Google OAuth client ID and client secret before saving Gmail config.");
  }
  const data = await requestJson("/api/gmail/config", {
    method: "POST",
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri,
    }),
  });
  $("#gmail-client-secret").value = "";
  state.gmailStatus = data.gmail || data;
  renderGmailStatus(state.gmailStatus);
  if (resultBox) {
    const setup = data.setup || {};
    resultBox.className = "result-card compact-result ready";
    resultBox.innerHTML = `
      <div class="result-header compact-result-header">
        <div>
          <strong>${escapeHtml(data.message || "Gmail config saved locally.")}</strong>
          <p>Secret-free status is refreshed. Next step: ${escapeHtml(setup.next_step || "connect Gmail OAuth")}.</p>
        </div>
        <span class="status-chip ready">saved</span>
      </div>
      <div>Config: <code>${escapeHtml(data.config_path || "config/gmail.local.json")}</code></div>
      ${data.backup_path ? `<div>Previous config backup: <code>${escapeHtml(data.backup_path)}</code></div>` : ""}
    `;
  }
  renderGmailApiResult({
    status: "saved",
    message: "Gmail OAuth config saved locally. The client secret was not returned.",
  }, "ready");
  return data;
}

async function startGmailOAuth() {
  const data = await requestJson("/api/gmail/oauth/start", { method: "POST" });
  state.gmailStatus = { ...(state.gmailStatus || {}), configured: true, connected: false };
  renderGmailStatus(state.gmailStatus);
  renderGmailApiResult({
    status: data.status,
    message: "Gmail OAuth window opened. Finish Google authorization, then return here and refresh status.",
  });
  if (data.authorization_url) {
    window.open(data.authorization_url, "_blank", "noopener,noreferrer");
  }
  return data;
}

function renderGmailApiResult(data, kind = "") {
  const box = $("#gmail-api-result");
  if (!box) return;
  if (!data) {
    box.className = "result-card compact-result hidden";
    box.textContent = "";
    return;
  }
  const confirmation = data.confirmation && typeof data.confirmation === "object" ? data.confirmation : data;
  const status = confirmation.status || data.status || kind || "info";
  const chipKind = statusChipClass(status === "created" ? "ready" : status);
  const duplicates = (
    confirmation.duplicate_records_created
    || data.duplicate_keys
    || data.record?.duplicate_keys
    || []
  )
    .map((item) => [item.case_number, item.service_date, item.service_period_label].filter(Boolean).join(" · "))
    .filter(Boolean)
    .join("; ");
  const hashes = confirmation.attachment_sha256 && typeof confirmation.attachment_sha256 === "object"
    ? Object.entries(confirmation.attachment_sha256)
    : [];
  box.className = `result-card compact-result ${chipKind}`;
  box.innerHTML = `
    <div class="result-header compact-result-header">
      <div>
        <strong>${escapeHtml(data.message || status.replaceAll("_", " "))}</strong>
        <p>Created as a Gmail draft only. Review and send manually in Gmail.</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${confirmation.fake_mode ? `<div><span class="status-chip info">synthetic smoke</span></div>` : ""}
    ${confirmation.draft_id ? `<div>Draft ID: <code>${escapeHtml(confirmation.draft_id)}</code></div>` : ""}
    ${confirmation.message_id ? `<div>Message ID: <code>${escapeHtml(confirmation.message_id)}</code></div>` : ""}
    ${confirmation.thread_id ? `<div>Thread ID: <code>${escapeHtml(confirmation.thread_id)}</code></div>` : ""}
    ${confirmation.to ? `<div>To: <code>${escapeHtml(confirmation.to)}</code></div>` : ""}
    ${confirmation.subject ? `<div>Subject: <strong>${escapeHtml(confirmation.subject)}</strong></div>` : ""}
    ${confirmation.attachment_basenames?.length ? `<div>Attachments: ${confirmation.attachment_basenames.map((item) => `<code>${escapeHtml(item)}</code>`).join(" ")}</div>` : ""}
    ${hashes.length ? `<details><summary>Attachment hashes</summary><pre class="draft-args">${escapeHtml(JSON.stringify(Object.fromEntries(hashes), null, 2))}</pre></details>` : ""}
    ${duplicates ? `<div>Duplicate protection: <strong>${escapeHtml(duplicates)}</strong></div>` : ""}
    ${confirmation.draft_log_path ? `<div>Draft log: <code>${escapeHtml(confirmation.draft_log_path)}</code></div>` : ""}
    ${confirmation.draft_id ? `
      <div class="button-row compact-button-row">
        <button type="button" class="mini-button" data-verify-created-draft="true">Verify created draft</button>
      </div>
    ` : ""}
  `;
}

function renderGmailVerifyResult(data, kind = "") {
  const box = $("#gmail-verify-result");
  if (!box) return;
  if (!data) {
    box.className = "result-card compact-result hidden";
    box.textContent = "";
    return;
  }
  const status = data.status || kind || "info";
  const chipKind = statusChipClass(status === "verified" ? "ready" : status === "not_found" || status === "reconciliation_mismatch" ? "blocked" : status);
  const mismatchRows = [];
  if (data.expected_message_id && data.message_id && data.message_id_matches === false) {
    mismatchRows.push(`Message ID differs from the local value: Gmail has ${data.message_id}.`);
  }
  if (data.expected_thread_id && data.thread_id && data.thread_id_matches === false) {
    mismatchRows.push(`Thread ID differs from the local value: Gmail has ${data.thread_id}.`);
  }
  box.className = `result-card compact-result ${chipKind}`;
  box.innerHTML = `
    <div class="result-header compact-result-header">
      <div>
        <strong>${escapeHtml(data.message || status.replaceAll("_", " "))}</strong>
        <p>Read-only Gmail draft verification. No local records were changed.</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${data.fake_mode ? `<div><span class="status-chip info">synthetic smoke</span></div>` : ""}
    ${data.draft_id ? `<div>Draft ID: <code>${escapeHtml(data.draft_id)}</code></div>` : ""}
    ${data.message_id ? `<div>Message ID: <code>${escapeHtml(data.message_id)}</code></div>` : ""}
    ${data.thread_id ? `<div>Thread ID: <code>${escapeHtml(data.thread_id)}</code></div>` : ""}
    ${data.to ? `<div>To: <code>${escapeHtml(data.to)}</code></div>` : ""}
    ${data.subject ? `<div>Subject: <strong>${escapeHtml(data.subject)}</strong></div>` : ""}
    ${mismatchRows.length ? `<ul>${mismatchRows.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    <div><span class="status-chip info">${escapeHtml(data.gmail_api_action || "users.drafts.get")}</span></div>
  `;
}

async function verifyGmailDraft() {
  const draftId = $("#record_draft_id")?.value.trim() || "";
  if (!draftId) {
    throw new Error("Paste or create a Gmail draft ID before verifying it.");
  }
  const data = await requestJson("/api/gmail/drafts/verify", {
    method: "POST",
    body: JSON.stringify(removeEmpty({
      draft_id: draftId,
      message_id: $("#record_message_id")?.value.trim() || "",
      thread_id: $("#record_thread_id")?.value.trim() || "",
    })),
  });
  renderGmailVerifyResult(data, data.status || "verified");
  setStatus(data.status || "verified", data.message || "Gmail draft verification completed.");
  return data;
}

async function verifyCreatedGmailDraft() {
  const confirmation = state.lastGmailCreateConfirmation || {};
  const draftId = String(confirmation.draft_id || $("#record_draft_id")?.value.trim() || "").trim();
  if (!draftId) {
    throw new Error("Create a Gmail draft before verifying the created draft.");
  }
  const data = await requestJson("/api/gmail/drafts/verify", {
    method: "POST",
    body: JSON.stringify(removeEmpty({
      draft_id: draftId,
      message_id: confirmation.message_id || $("#record_message_id")?.value.trim() || "",
      thread_id: confirmation.thread_id || $("#record_thread_id")?.value.trim() || "",
    })),
  });
  renderGmailVerifyResult(data, data.status || "verified");
  setStatus(data.status || "verified", data.message || "Gmail draft verification completed.");
  return data;
}

async function createGmailApiDraft() {
  if (state.gmailCreateInFlight) return null;
  if (!$("#gmail_handoff_reviewed")?.checked) {
    throw new Error("Review the PDF preview and exact Gmail args before creating a Gmail draft.");
  }
  const target = preparedRecordTarget();
  if (!target?.draft_payload) {
    throw new Error("Prepare a PDF and Gmail draft payload before creating a Gmail draft.");
  }
  const supersedes = $("#record_supersedes").value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const correctionReason = $("#correction_reason")?.value.trim() || "";
  state.gmailCreateInFlight = true;
  renderGmailApiResult({ status: "info", message: "Creating Gmail draft and recording duplicate protection..." }, "info");
  syncActionGates();
  try {
    const data = await requestJson("/api/gmail/drafts/create", {
      method: "POST",
      body: JSON.stringify(removeEmpty({
        payload: target.draft_payload,
        gmail_handoff_reviewed: true,
        supersedes,
        correction_reason: correctionReason,
        notes: correctionReason || $("#record_notes").value.trim() || preparedRecordNote(target),
        ...currentPreparedReviewFields(target.draft_payload),
      })),
    });
    $("#record_payload").value = target.draft_payload;
    $("#record_draft_id").value = data.draft_id || data.confirmation?.draft_id || "";
    $("#record_message_id").value = data.message_id || data.confirmation?.message_id || "";
    $("#record_thread_id").value = data.thread_id || data.confirmation?.thread_id || "";
    $("#record_status").value = "active";
    state.gmailCreateCompletedPayload = target.draft_payload;
    state.lastGmailCreateConfirmation = data.confirmation && typeof data.confirmation === "object" ? data.confirmation : data;
    renderGmailApiResult(data, "created");
    setStatus("recorded", "Gmail draft created and recorded locally. Review and send it manually in Gmail.");
    showAlert("Gmail draft created and duplicate protection updated.", "recorded");
    await loadReference();
    return data;
  } finally {
    state.gmailCreateInFlight = false;
    syncActionGates();
  }
}

async function startGooglePhotosOAuth() {
  const data = await requestJson("/api/google-photos/oauth/start", { method: "POST" });
  state.googlePhotosStatus = { ...(state.googlePhotosStatus || {}), configured: true, connected: false };
  renderGooglePhotosPickerResult({
    status: data.status,
    message: "OAuth window opened. Finish Google authorization, then return here and refresh status.",
  });
  if (data.authorization_url) {
    window.open(data.authorization_url, "_blank", "noopener,noreferrer");
  }
  return data;
}

async function createGooglePhotosPickerSession() {
  const data = await requestJson("/api/google-photos/picker/session", {
    method: "POST",
    body: JSON.stringify({ max_items: 1 }),
  });
  state.googlePhotosPicker = data;
  $("#google-photos-session-id").value = data.session_id || "";
  renderGooglePhotosPickerResult({
    ...data,
    message: "Picker session created. Choose one image in Google Photos, then check or import the selection.",
  });
  if (data.picker_uri) {
    window.open(data.picker_uri, "_blank", "noopener,noreferrer");
  }
  return data;
}

async function checkGooglePhotosPickerSelection() {
  const sessionId = $("#google-photos-session-id").value.trim();
  if (!sessionId) throw new Error("Create or paste a Google Photos Picker session first.");
  const data = await requestJson(`/api/google-photos/picker/session/${encodeURIComponent(sessionId)}`);
  state.googlePhotosPicker = { ...(state.googlePhotosPicker || {}), ...data };
  renderGooglePhotosPickerResult(data);
  return data;
}

async function importGooglePhotosPickerSelection() {
  const sessionId = $("#google-photos-session-id").value.trim();
  if (!sessionId) throw new Error("Create or paste a Google Photos Picker session first.");
  const payload = {
    session_id: sessionId,
    profile: $("#profile").value || "",
    visible_metadata_text: $("#google-photos-metadata").value.trim(),
    ai_recovery: $("#ai_recovery_mode").value || "auto",
  };
  const data = await requestJson("/api/google-photos/picker/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.currentIntake = data.candidate_intake;
  fillFormFromIntake(state.currentIntake);
  renderSourceEvidence(data);
  renderAiRecovery(data.ai_recovery);
  renderGooglePhotosPickerResult({
    ...data,
    status: "imported",
    message: "Google Photos image imported for review.",
  });
  applyReview(data.review);
  return data;
}

function renderPublicReadiness(data) {
  const chip = $("#public-readiness-chip");
  const body = $("#public-readiness-result");
  if (!chip || !body) return;
  const gate = data?.tracked_gate || data || {};
  const ready = Boolean(data?.tracked_gate ? gate.public_repo_ready : (gate.public_ready ?? gate.public_repo_ready));
  chip.textContent = ready ? "ready" : "blocked";
  chip.className = `status-chip ${ready ? "ready" : "blocked"}`;
  const pathBlockers = (gate.path_blockers || []).map((item) => item.path || item);
  const blockedPaths = [...pathBlockers, ...(gate.blocked_paths || [])].slice(0, 8);
  const metadataBlockers = (gate.metadata_blockers || []).slice(0, 8);
  const findings = (gate.content_findings || []).slice(0, 8);
  const gitBlockers = gate.git_blockers || [];
  const workspaceGate = data?.workspace_gate || null;
  const workspaceBlockedCount = Number(workspaceGate?.blocker_count || 0);
  const workspaceNote = workspaceGate
    ? `<div class="data-item"><strong>Local overlays</strong><span>${escapeHtml(data.workspace_privacy_note || "Full-workspace privacy gate is separate from tracked Git publishing.")}</span></div>
       <div class="data-item"><strong>Full workspace gate</strong><span>${escapeHtml(workspaceGate.public_ready ? "ready" : `blocked (${workspaceBlockedCount} blocker${workspaceBlockedCount === 1 ? "" : "s"})`)}</span></div>`
    : "";
  body.className = `result-card ${ready ? "ready" : "blocked"}`;
  body.innerHTML = `
    <div class="result-header">
      <div>
        <strong>${escapeHtml(data?.message || "Run the privacy gate before publishing.")}</strong>
        <p>${escapeHtml(gate?.blocker_count ?? data?.blocker_count ?? 0)} tracked blocker${Number(gate?.blocker_count || data?.blocker_count || 0) === 1 ? "" : "s"} found.</p>
      </div>
      <span class="status-chip ${ready ? "ready" : "blocked"}">${ready ? "ready" : "blocked"}</span>
    </div>
    ${workspaceNote}
    ${gitBlockers.map((item) => `<div class="data-item"><strong>Git</strong><span>${escapeHtml(item)}</span></div>`).join("")}
    ${blockedPaths.map((item) => `<div class="data-item"><strong>Private path</strong><code>${escapeHtml(item)}</code></div>`).join("")}
    ${metadataBlockers.map((item) => `<div class="data-item"><strong>Missing metadata</strong><code>${escapeHtml(item)}</code></div>`).join("")}
    ${findings.map((item) => `<div class="data-item"><strong>${escapeHtml(item.kind)}</strong><code>${escapeHtml(item.path)}:${escapeHtml(item.line)}</code></div>`).join("")}
  `;
}

async function runPublicReadiness() {
  const data = await requestJson("/api/public-readiness");
  renderPublicReadiness(data);
  return data;
}

async function buildPublicCandidate() {
  const data = await requestJson("/api/public-candidate/build", { method: "POST" });
  renderPublicReadiness({
    ...data.gate,
    message: `${data.gate.message} Candidate: ${data.candidate_path}`,
  });
  return data;
}

function formatBackupAge(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "No backup yet";
  const value = Number(seconds);
  if (value < 60) return "just now";
  if (value < 3600) return `${Math.floor(value / 60)} min ago`;
  if (value < 86400) return `${Math.floor(value / 3600)} h ago`;
  return `${Math.floor(value / 86400)} d ago`;
}

function renderBackupStatus(data) {
  const chip = $("#backup-status-chip");
  const body = $("#local-backup-status");
  if (!chip || !body) return;
  const status = data?.status || "recommended";
  const chipKind = statusChipClass(status);
  chip.textContent = status.replaceAll("_", " ");
  chip.className = `status-chip ${chipKind}`;
  const latest = data?.latest_backup_file
    ? `<div class="data-item"><strong>Backup file</strong><code>${escapeHtml(data.latest_backup_file)}</code></div>`
    : `<div class="data-item"><strong>Backup file</strong><span>No backup file found yet.</span></div>`;
  const age = `<div class="data-item"><strong>Age</strong><span>${escapeHtml(formatBackupAge(data?.latest_backup_age_seconds))}</span></div>`;
  const counts = data?.managed_counts || {};
  const countRows = Object.entries(counts).map(([key, value]) => (
    `<div class="data-item"><strong>${escapeHtml(key)}</strong><span>${escapeHtml(value)} record${Number(value) === 1 ? "" : "s"}</span></div>`
  )).join("");
  body.className = `result-card compact-result ${chipKind}`;
  body.innerHTML = `
    <div class="result-header">
      <div>
        <strong>Latest backup</strong>
        <p>${escapeHtml(data?.message || "Backup recommended before high-risk local edits.")}</p>
        <p>Backup recommended before high-risk local edits to profiles, court emails, destinations, or restores.</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${latest}
    ${age}
    ${countRows}
  `;
}

function maybeShowBackupReminder(actionName) {
  if (!state.backupStatus?.backup_recommended) return false;
  renderLocalBackupResult({
    status: "recommended",
    message: `Backup recommended before ${actionName}. Use Export backup first if this edit is not trivial.`,
    counts: state.backupStatus.managed_counts || {},
  }, "recommended");
  return true;
}

function renderLocalBackupResult(data, kind = "info") {
  const chip = $("#backup-status-chip");
  const body = $("#local-backup-result");
  if (!chip || !body) return;
  const status = data?.status || kind || "idle";
  const chipKind = statusChipClass(status === "exported" || status === "restored" ? "ready" : status);
  chip.textContent = status.replaceAll("_", " ");
  chip.className = `status-chip ${chipKind}`;
  const counts = data?.counts || {};
  const countRows = Object.entries(counts).map(([key, value]) => (
    `<div class="data-item"><strong>${escapeHtml(key)}</strong><span>${escapeHtml(value)} record${Number(value) === 1 ? "" : "s"}</span></div>`
  )).join("");
  const backupFile = data?.backup_file ? `<div class="data-item"><strong>Backup file</strong><code>${escapeHtml(data.backup_file)}</code></div>` : "";
  const preRestore = data?.pre_restore_backup_file ? `<div class="data-item"><strong>Pre-restore backup</strong><code>${escapeHtml(data.pre_restore_backup_file)}</code></div>` : "";
  const datasets = data?.dataset_names || data?.restored_datasets || [];
  const datasetRow = datasets.length ? `<div class="data-item"><strong>Datasets</strong><span>${escapeHtml(datasets.join(", "))}</span></div>` : "";
  const restoreRequirements = data?.restore_requirements?.confirmation_phrase
    ? `<div class="data-item"><strong>Required restore phrase</strong><code>${escapeHtml(data.restore_requirements.confirmation_phrase)}</code></div>`
    : "";
  const restoreReason = data?.restore_reason
    ? `<div class="data-item"><strong>Restore reason</strong><span>${escapeHtml(data.restore_reason)}</span></div>`
    : "";
  body.className = `result-card ${chipKind}`;
  body.innerHTML = `
    <div class="result-header">
      <div>
        <strong>${escapeHtml(data?.message || "No backup action has run yet.")}</strong>
        <p>Local backup actions never create or send Gmail messages.</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${backupFile}
    ${preRestore}
    ${datasetRow}
    ${restoreRequirements}
    ${restoreReason}
    ${countRows}
  `;
}

function localBackupJsonText() {
  const value = $("#local-backup-json").value.trim();
  if (!value) {
    throw new Error("Paste or export backup JSON before previewing a restore.");
  }
  return value;
}

async function exportLocalBackup() {
  const data = await requestJson("/api/backup/export", { method: "POST" });
  $("#local-backup-json").value = JSON.stringify(data.backup, null, 2);
  state.localBackupPreview = null;
  $("#confirm-local-backup-restore").checked = false;
  $("#local-backup-restore-phrase").value = "";
  $("#local-backup-restore-reason").value = "";
  renderLocalBackupResult(data, "exported");
  if (data.backup_status) {
    state.backupStatus = data.backup_status;
    renderBackupStatus(state.backupStatus);
  }
  return data;
}

async function previewLocalBackupImport() {
  const data = await requestJson("/api/backup/import-preview", {
    method: "POST",
    body: JSON.stringify({ backup_json: localBackupJsonText() }),
  });
  state.localBackupPreview = data;
  $("#confirm-local-backup-restore").checked = false;
  $("#local-backup-restore-phrase").value = "";
  $("#local-backup-restore-reason").value = "";
  renderLocalBackupResult(data, "ready");
  return data;
}

async function restoreLocalBackupImport() {
  maybeShowBackupReminder("restoring backup data");
  if (!state.localBackupPreview) {
    throw new Error("Preview backup import before restoring local data.");
  }
  if (!$("#confirm-local-backup-restore").checked) {
    throw new Error("Check the restore confirmation box before using Restore backup after preview.");
  }
  const confirmationPhrase = $("#local-backup-restore-phrase").value.trim();
  const restoreReason = $("#local-backup-restore-reason").value.trim();
  if (!confirmationPhrase) {
    throw new Error("Type the exact restore confirmation phrase before restoring local data.");
  }
  if (!restoreReason) {
    throw new Error("Add a short restore reason before restoring local data.");
  }
  const data = await requestJson("/api/backup/import", {
    method: "POST",
    body: JSON.stringify({
      backup_json: localBackupJsonText(),
      confirm_restore: true,
      confirmation_phrase: confirmationPhrase,
      restore_reason: restoreReason,
    }),
  });
  state.localBackupPreview = null;
  $("#confirm-local-backup-restore").checked = false;
  $("#local-backup-restore-phrase").value = "";
  $("#local-backup-restore-reason").value = "";
  renderLocalBackupResult(data, "restored");
  if (data.backup_status) {
    state.backupStatus = data.backup_status;
    renderBackupStatus(state.backupStatus);
  }
  await loadReference();
  return data;
}

function legalPdfImportJsonText() {
  const value = $("#legalpdf-import-json").value.trim();
  if (!value) {
    throw new Error("Paste a backup JSON before previewing a LegalPDF import.");
  }
  return value;
}

function renderImportDiffRows(rows, keyLabel) {
  if (!rows?.length) {
    return `<div class="data-item"><strong>${escapeHtml(keyLabel)}</strong><span>No records in this dataset.</span></div>`;
  }
  return rows.map((row) => {
    const label = row.source_key || row.key || row.target_key || "record";
    const target = row.target_key && row.target_key !== row.source_key
      ? ` -> ${row.target_key}`
      : "";
    const email = row.incoming_email ? ` · ${row.incoming_email}` : "";
    const changeCount = Number(row.change_count || 0);
    return `
      <div class="data-item import-diff-row">
        <strong>${escapeHtml(label)}${escapeHtml(target)}</strong>
        <span>
          <span class="status-chip ${statusChipClass(row.action)}">${escapeHtml(row.action || "preview")}</span>
          ${escapeHtml(row.incoming_description || row.name || "")}${escapeHtml(email)}
          ${changeCount ? ` · ${escapeHtml(changeCount)} change${changeCount === 1 ? "" : "s"}` : ""}
        </span>
      </div>
    `;
  }).join("");
}

function renderIntegrationChecklistRows(tasks) {
  if (!tasks?.length) {
    return `<div class="data-item"><strong>Integration checklist</strong><span>No adapter tasks were generated.</span></div>`;
  }
  return tasks.map((task) => {
    const key = task.source_key && task.source_key !== task.target_key
      ? `${task.source_key} -> ${task.target_key}`
      : task.target_key || task.source_key || "record";
    const changeCount = Number(task.change_count || 0);
    return `
      <div class="data-item import-diff-row">
        <strong>${escapeHtml(task.number || "")}. ${escapeHtml(task.title || "Review integration task")}</strong>
        <span>
          <span class="status-chip ${statusChipClass(task.action)}">${escapeHtml(task.action || "review")}</span>
          ${escapeHtml(task.category || "integration")} · ${escapeHtml(key)}
          ${changeCount ? ` · ${escapeHtml(changeCount)} change${changeCount === 1 ? "" : "s"}` : ""}
        </span>
        <span>${escapeHtml(task.detail || "")}</span>
      </div>
    `;
  }).join("");
}

function renderAdapterImportPlanRows(tasks) {
  if (!tasks?.length) {
    return `<div class="data-item"><strong>Adapter import plan</strong><span>No import-plan tasks were generated.</span></div>`;
  }
  return tasks.map((task) => {
    const key = task.source_key && task.source_key !== task.target_key
      ? `${task.source_key} -> ${task.target_key}`
      : task.target_key || task.source_key || "record";
    const blockers = task.blockers?.length
      ? `<span>${escapeHtml(task.blockers.join("; "))}</span>`
      : `<span>No blocking issue detected; still requires future review before any import.</span>`;
    const chipClass = task.blocking ? "blocked" : statusChipClass(task.action || "review");
    return `
      <div class="data-item import-diff-row">
        <strong>${escapeHtml(task.number || "")}. ${escapeHtml(task.title || "Review adapter import task")}</strong>
        <span>
          <span class="status-chip ${chipClass}">${task.blocking ? "blocked" : escapeHtml(task.action || "review")}</span>
          ${escapeHtml(task.category || "integration")} · ${escapeHtml(key)} · ${escapeHtml(task.merge_policy || "review_first")}
        </span>
        ${blockers}
      </div>
    `;
  }).join("");
}

function renderLegalPdfImportPreview(data, kind = "info") {
  const chip = $("#legalpdf-import-chip");
  const body = $("#legalpdf-import-preview-result");
  if (!chip || !body) return;
  const status = data?.status || kind || "idle";
  const chipKind = statusChipClass(status === "previewed" ? "ready" : status);
  chip.textContent = status.replaceAll("_", " ");
  chip.className = `status-chip ${chipKind}`;
  const counts = data?.counts || {};
  const countRows = Object.entries(counts).map(([key, value]) => (
    `<div class="data-item"><strong>${escapeHtml(key)}</strong><span>${escapeHtml(value)} record${Number(value) === 1 ? "" : "s"}</span></div>`
  )).join("");
  const datasets = data?.dataset_names?.length
    ? `<div class="data-item"><strong>Datasets</strong><span>${escapeHtml(data.dataset_names.join(", "))}</span></div>`
    : "";
  const markdownFile = data?.preview_report_markdown_file
    ? `<div class="data-item"><strong>Markdown report</strong><code>${escapeHtml(data.preview_report_markdown_file)}</code></div>`
    : "";
  const jsonFile = data?.preview_report_json_file
    ? `<div class="data-item"><strong>JSON report</strong><code>${escapeHtml(data.preview_report_json_file)}</code></div>`
    : "";
  const applyJsonFile = data?.apply_report_json_file
    ? `<div class="data-item"><strong>Apply report</strong><code>${escapeHtml(data.apply_report_json_file)}</code></div>`
    : "";
  const applyMarkdownFile = data?.apply_report_markdown_file
    ? `<div class="data-item"><strong>Apply Markdown report</strong><code>${escapeHtml(data.apply_report_markdown_file)}</code></div>`
    : "";
  const preApplyBackup = data?.pre_apply_backup_file
    ? `<div class="data-item"><strong>Pre-apply backup</strong><code>${escapeHtml(data.pre_apply_backup_file)}</code></div>`
    : "";
  const profileSummary = data?.profile_action_summary
    ? `<div class="data-item"><strong>Profile summary</strong><span>${escapeHtml(JSON.stringify(data.profile_action_summary))}</span></div>`
    : "";
  const courtSummary = data?.court_email_action_summary
    ? `<div class="data-item"><strong>Court email summary</strong><span>${escapeHtml(JSON.stringify(data.court_email_action_summary))}</span></div>`
    : "";
  const checklistRows = data?.checklist
    ? `
      <h4>Integration checklist</h4>
      <div class="data-list">${renderIntegrationChecklistRows(data.checklist)}</div>
      ${data.checklist_markdown ? `<details class="inline-details"><summary>Checklist Markdown</summary><pre class="draft-args">${escapeHtml(data.checklist_markdown)}</pre></details>` : ""}
    `
    : "";
  const adapterPlanRows = data?.adapter_plan_tasks
    ? `
      <h4>Adapter import plan</h4>
      <div class="data-list">${renderAdapterImportPlanRows(data.adapter_plan_tasks)}</div>
      ${data.blocking_count !== undefined ? `<div class="data-item"><strong>Blocking tasks</strong><span>${escapeHtml(data.blocking_count)}</span></div>` : ""}
      ${data.plan_markdown ? `<details class="inline-details"><summary>Adapter Plan Markdown</summary><pre class="draft-args">${escapeHtml(data.plan_markdown)}</pre></details>` : ""}
    `
    : "";
  const appliedProfiles = data?.applied_profiles?.length
    ? `
      <h4>Applied service profiles</h4>
      <div class="data-list">${data.applied_profiles.map((item) => `
        <div class="data-item">
          <strong>${escapeHtml(item.target_key || item.source_key || "profile")}</strong>
          <span>${escapeHtml(item.action || "applied")}${item.preserved_required_default_paths?.length ? ` · preserved ${escapeHtml(item.preserved_required_default_paths.join(", "))}` : ""}</span>
        </div>
      `).join("")}</div>
    `
    : "";
  const appliedCourts = data?.applied_court_emails?.length
    ? `
      <h4>Applied court emails</h4>
      <div class="data-list">${data.applied_court_emails.map((item) => `
        <div class="data-item">
          <strong>${escapeHtml(item.key || "court email")}</strong>
          <span>${escapeHtml(item.action || "applied")}</span>
        </div>
      `).join("")}</div>
    `
    : "";
  const changedText = data?.managed_data_changed
    ? "Local Honorários reference files were changed after explicit confirmation. LegalPDF Translate was not modified. Gmail is not involved."
    : "No local files were changed. This wizard cannot create or send Gmail messages.";
  body.className = `result-card ${chipKind}`;
  body.innerHTML = `
    <div class="result-header">
      <div>
        <strong>${escapeHtml(data?.message || "No LegalPDF integration preview has run yet.")}</strong>
        <p>${escapeHtml(changedText)}</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${datasets}
    ${markdownFile}
    ${jsonFile}
    ${applyJsonFile}
    ${applyMarkdownFile}
    ${preApplyBackup}
    ${countRows}
    ${profileSummary}
    <h4>Profile mappings</h4>
    <div class="data-list">${renderImportDiffRows(data?.profile_mappings || [], "Profiles")}</div>
    ${courtSummary}
    <h4>Court-email differences</h4>
    <div class="data-list">${renderImportDiffRows(data?.court_email_differences || [], "Court emails")}</div>
    ${checklistRows}
    ${adapterPlanRows}
    ${appliedProfiles}
    ${appliedCourts}
  `;
}

async function previewLegalPdfImport() {
  const data = await requestJson("/api/integration/import-preview", {
    method: "POST",
    body: JSON.stringify({
      backup_json: legalPdfImportJsonText(),
      profile_mapping_text: $("#legalpdf-profile-mapping").value,
    }),
  });
  state.legalPdfImportPreview = data;
  renderLegalPdfImportPreview(data, "ready");
  return data;
}

async function exportLegalPdfImportReport() {
  const data = await requestJson("/api/integration/import-report", {
    method: "POST",
    body: JSON.stringify({
      backup_json: legalPdfImportJsonText(),
      profile_mapping_text: $("#legalpdf-profile-mapping").value,
    }),
  });
  state.legalPdfImportPreview = data.preview || null;
  renderLegalPdfImportPreview({
    ...(data.preview || {}),
    status: data.status,
    message: data.message,
    preview_report_markdown_file: data.preview_report_markdown_file,
    preview_report_json_file: data.preview_report_json_file,
  }, "ready");
  return data;
}

async function buildLegalPdfIntegrationChecklist() {
  const data = await requestJson("/api/integration/checklist", {
    method: "POST",
    body: JSON.stringify({
      backup_json: legalPdfImportJsonText(),
      profile_mapping_text: $("#legalpdf-profile-mapping").value,
    }),
  });
  state.legalPdfImportPreview = data.preview || null;
  renderLegalPdfImportPreview({
    ...(data.preview || {}),
    status: data.status,
    message: data.message,
    checklist: data.checklist || [],
    checklist_markdown: data.checklist_markdown || "",
  }, "ready");
  return data;
}

async function buildLegalPdfAdapterImportPlan() {
  const data = await requestJson("/api/integration/import-plan", {
    method: "POST",
    body: JSON.stringify({
      backup_json: legalPdfImportJsonText(),
      profile_mapping_text: $("#legalpdf-profile-mapping").value,
    }),
  });
  state.legalPdfImportPreview = data.preview || null;
  renderLegalPdfImportPreview({
    ...(data.preview || {}),
    status: data.status,
    message: data.message,
    adapter_plan_tasks: data.tasks || [],
    blocking_count: data.blocking_count,
    plan_markdown: data.plan_markdown || "",
  }, "ready");
  return data;
}

async function applyLegalPdfAdapterImportPlan() {
  const data = await requestJson("/api/integration/apply-import-plan", {
    method: "POST",
    body: JSON.stringify({
      backup_json: legalPdfImportJsonText(),
      profile_mapping_text: $("#legalpdf-profile-mapping").value,
      confirm_apply: $("#confirm-legalpdf-import-apply")?.checked || false,
      confirmation_phrase: $("#legalpdf-apply-phrase")?.value || "",
      apply_reason: $("#legalpdf-apply-reason")?.value || "",
    }),
  });
  state.legalPdfImportPreview = data.plan?.preview || null;
  renderLegalPdfImportPreview({
    ...(data.plan?.preview || {}),
    status: data.status,
    message: data.message,
    adapter_plan_tasks: data.plan?.tasks || [],
    blocking_count: data.plan?.blocking_count,
    plan_markdown: data.plan?.plan_markdown || "",
    applied_profiles: data.applied_profiles || [],
    applied_court_emails: data.applied_court_emails || [],
    apply_report_json_file: data.apply_report_json_file || "",
    apply_report_markdown_file: data.apply_report_markdown_file || "",
    pre_apply_backup_file: data.pre_apply_backup_file || "",
    managed_data_changed: data.managed_data_changed,
  }, "ready");
  await loadReference();
  if (data.backup_status) {
    state.backupStatus = data.backup_status;
    renderBackupStatus(state.backupStatus);
  }
  await loadLegalPdfApplyHistory();
  return data;
}

function renderLegalPdfApplyHistory(data) {
  const card = $("#legalpdf-apply-history-result");
  const body = $("#legalpdf-apply-history-body");
  if (!card || !body) return;
  const reports = data?.reports || [];
  const rows = reports.length
    ? reports.map((report) => {
      const profiles = report.applied_profiles?.length
        ? report.applied_profiles.map((item) => `${item.target_key || item.source_key || "profile"} (${item.action || "applied"})`).join(", ")
        : "No profile changes";
      const courts = report.applied_court_emails?.length
        ? report.applied_court_emails.map((item) => `${item.key || "court email"} (${item.action || "applied"})`).join(", ")
        : "No court-email changes";
      const preserved = report.applied_profiles?.flatMap((item) => item.preserved_required_default_paths || []).filter(Boolean) || [];
      const reportId = report.report_id || pathBasename(report.report_json_file || "").replace(/\.json$/i, "");
      return `
        <div class="data-item import-diff-row">
          <strong>${escapeHtml(report.created_at || "LegalPDF import apply")}</strong>
          <span><span class="status-chip ${statusChipClass(report.status || "ready")}">${escapeHtml(report.status || "ready")}</span> ${escapeHtml(report.apply_reason || "No apply reason recorded.")}</span>
          <span><strong>Profiles:</strong> ${escapeHtml(profiles)}</span>
          <span><strong>Court emails:</strong> ${escapeHtml(courts)}</span>
          ${preserved.length ? `<span><strong>Preserved local defaults:</strong> ${escapeHtml([...new Set(preserved)].join(", "))}</span>` : ""}
          ${report.profile_change_ids?.length ? `<span><strong>Profile change IDs:</strong> ${escapeHtml(report.profile_change_ids.join(", "))}</span>` : ""}
          ${report.pre_apply_backup_file ? `<span><strong>Pre-apply backup:</strong> <code>${escapeHtml(report.pre_apply_backup_file)}</code></span>` : ""}
          ${report.report_json_file ? `<span><strong>JSON report:</strong> <code>${escapeHtml(report.report_json_file)}</code></span>` : ""}
          ${report.report_markdown_file ? `<span><strong>Markdown report:</strong> <code>${escapeHtml(report.report_markdown_file)}</code></span>` : ""}
          ${reportId ? `<button type="button" class="mini-button" data-legalpdf-report-id="${escapeHtml(reportId)}">Details</button>` : ""}
          ${reportId ? `<button type="button" class="mini-button" data-legalpdf-restore-report-id="${escapeHtml(reportId)}">Restore plan</button>` : ""}
        </div>
      `;
    }).join("")
    : `<div class="data-item"><strong>LegalPDF Apply History</strong><span>No guarded LegalPDF import has been applied yet.</span></div>`;
  card.classList.remove("hidden");
  body.innerHTML = `
    <div class="data-list">${rows}</div>
    <p class="field-hint">History is read-only. It shows summaries only, not the full import plan or source backup payload.</p>
  `;
}

function renderLegalPdfApplyDetail(data) {
  const body = $("#legalpdf-apply-detail-body");
  if (!body) return;
  const comparison = data?.comparison || {};
  const profileRows = (comparison.profiles || []).map((item) => `
    <div class="data-item import-diff-row">
      <strong>${escapeHtml(item.target_key || "profile")}</strong>
      <span><span class="status-chip ${statusChipClass(item.current_status || "ready")}">${escapeHtml(item.current_status || "unknown")}</span> ${item.current_matches_applied ? "matches applied hash" : "does not match applied hash"}</span>
      <span><strong>Action:</strong> ${escapeHtml(item.action || "")}</span>
      ${item.preserved_required_default_paths?.length ? `<span><strong>Preserved local defaults:</strong> ${escapeHtml(item.preserved_required_default_paths.join(", "))}</span>` : ""}
      <span><strong>Pre-apply hash:</strong> <code>${escapeHtml(item.pre_apply_hash || item.pre_apply_status || "unavailable")}</code></span>
      <span><strong>Applied hash:</strong> <code>${escapeHtml(item.applied_hash || "missing")}</code></span>
      <span><strong>Current hash:</strong> <code>${escapeHtml(item.current_hash || "missing")}</code></span>
    </div>
  `).join("");
  const courtRows = (comparison.court_emails || []).map((item) => `
    <div class="data-item import-diff-row">
      <strong>${escapeHtml(item.key || "court email")}</strong>
      <span><span class="status-chip ${statusChipClass(item.current_status || "ready")}">${escapeHtml(item.current_status || "unknown")}</span> ${item.current_matches_applied ? "matches applied hash" : "does not match applied hash"}</span>
      <span><strong>Action:</strong> ${escapeHtml(item.action || "")}</span>
      <span><strong>Pre-apply hash:</strong> <code>${escapeHtml(item.pre_apply_hash || item.pre_apply_status || "unavailable")}</code></span>
      <span><strong>Applied hash:</strong> <code>${escapeHtml(item.applied_hash || "missing")}</code></span>
      <span><strong>Current hash:</strong> <code>${escapeHtml(item.current_hash || "missing")}</code></span>
    </div>
  `).join("");
  body.innerHTML = `
    <div class="result-card ${data?.status === "ready" ? "ready" : "blocked"}">
      <div class="result-header">
        <div>
          <strong>LegalPDF Apply Detail</strong>
          <p>${escapeHtml(data?.message || "Read-only redacted comparison.")}</p>
        </div>
        <span class="status-chip ${statusChipClass(data?.status || "ready")}">${escapeHtml(data?.status || "ready")}</span>
      </div>
      <div class="data-list">
        <div class="data-item">
          <strong>${escapeHtml(data?.report?.report_id || "Apply report")}</strong>
          <span><strong>Backup available:</strong> ${data?.backup_available ? "yes" : "no"}</span>
          ${data?.report?.pre_apply_backup_file ? `<span><strong>Pre-apply backup:</strong> <code>${escapeHtml(data.report.pre_apply_backup_file)}</code></span>` : ""}
        </div>
        ${profileRows || `<div class="data-item"><strong>Profiles</strong><span>No profile comparison rows.</span></div>`}
        ${courtRows || `<div class="data-item"><strong>Court emails</strong><span>No court-email comparison rows.</span></div>`}
      </div>
      <p class="field-hint">This detail view is read-only. It shows hashes and statuses only, not raw backup records or the full import plan.</p>
    </div>
  `;
}

function renderLegalPdfRestorePlan(data) {
  const body = $("#legalpdf-apply-detail-body");
  if (!body) return;
  const plan = data?.restore_plan || {};
  const reportId = data?.report?.report_id || data?.source_apply_report_id || "";
  const profileRows = (plan.profiles || []).map((item) => `
    <div class="data-item import-diff-row">
      <strong>${escapeHtml(item.target_key || "profile")}</strong>
      <span><span class="status-chip ${statusChipClass(item.restore_action === "blocked" ? "blocked" : "ready")}">${escapeHtml(item.restore_action || "restore")}</span> ${item.would_change_current ? "would change current record" : "current already matches pre-apply state"}</span>
      <span><strong>Applied action:</strong> ${escapeHtml(item.applied_action || "")}</span>
      <span><strong>Backup record:</strong> ${escapeHtml(item.backup_record_status || "unknown")}</span>
      <span><strong>Current record:</strong> ${escapeHtml(item.current_record_status || "unknown")}</span>
      <span><strong>Pre-apply hash:</strong> <code>${escapeHtml(item.pre_apply_hash || item.backup_record_status || "unavailable")}</code></span>
      <span><strong>Current hash:</strong> <code>${escapeHtml(item.current_hash || "missing")}</code></span>
      ${item.blockers?.length ? `<span><strong>Blockers:</strong> ${escapeHtml(item.blockers.join(", "))}</span>` : ""}
    </div>
  `).join("");
  const courtRows = (plan.court_emails || []).map((item) => `
    <div class="data-item import-diff-row">
      <strong>${escapeHtml(item.key || "court email")}</strong>
      <span><span class="status-chip ${statusChipClass(item.restore_action === "blocked" ? "blocked" : "ready")}">${escapeHtml(item.restore_action || "restore")}</span> ${item.would_change_current ? "would change current record" : "current already matches pre-apply state"}</span>
      <span><strong>Applied action:</strong> ${escapeHtml(item.applied_action || "")}</span>
      <span><strong>Backup record:</strong> ${escapeHtml(item.backup_record_status || "unknown")}</span>
      <span><strong>Current record:</strong> ${escapeHtml(item.current_record_status || "unknown")}</span>
      <span><strong>Pre-apply hash:</strong> <code>${escapeHtml(item.pre_apply_hash || item.backup_record_status || "unavailable")}</code></span>
      <span><strong>Current hash:</strong> <code>${escapeHtml(item.current_hash || "missing")}</code></span>
      ${item.blockers?.length ? `<span><strong>Blockers:</strong> ${escapeHtml(item.blockers.join(", "))}</span>` : ""}
    </div>
  `).join("");
  const restoreControls = data?.status === "ready" && Number(data?.blocking_count || 0) === 0 && reportId
    ? `
      <div class="result-card blocked legalpdf-restore-confirmation">
        <div class="result-header">
          <div>
            <strong>Apply this restore locally</strong>
            <p>This writes only this app's reference files from the pre-apply backup. LegalPDF Translate was not modified, Gmail is not involved, and a pre-restore backup will be created first.</p>
          </div>
          <span class="status-chip blocked">Guarded write</span>
        </div>
        <div class="form-grid">
          <label for="legalpdf-restore-reason">
            Restore reason
            <input id="legalpdf-restore-reason" autocomplete="off" placeholder="Example: imported the wrong LegalPDF profile mapping">
          </label>
          <label for="legalpdf-restore-phrase">
            Confirmation phrase
            <input id="legalpdf-restore-phrase" autocomplete="off" placeholder="RESTORE LEGALPDF APPLY BACKUP">
          </label>
        </div>
        <label class="checkbox-row">
          <input id="confirm-legalpdf-restore" type="checkbox">
          <span>I reviewed the restore plan and want to restore this app's local reference data from the pre-apply backup.</span>
        </label>
        <div class="button-row compact-button-row">
          <button type="button" class="mini-button" data-legalpdf-apply-restore-report-id="${escapeHtml(reportId)}">Restore local references from backup</button>
        </div>
      </div>
    `
    : "";
  const restoreReport = data?.restore_report_json_file
    ? `
      <div class="result-card ready">
        <div class="result-header">
          <div>
            <strong>Restore report</strong>
            <p>Local restore finished with an audit report and a pre-restore backup.</p>
          </div>
          <span class="status-chip ready">${escapeHtml(data.status || "restored")}</span>
        </div>
        <div class="data-list">
          <div class="data-item"><strong>Restore report JSON</strong><code>${escapeHtml(data.restore_report_json_file)}</code></div>
          <div class="data-item"><strong>Pre-restore backup</strong><code>${escapeHtml(data.pre_restore_backup_file || "")}</code></div>
        </div>
      </div>
    `
    : "";
  body.innerHTML = `
    <div class="result-card ${data?.status === "ready" ? "ready" : "blocked"}">
      <div class="result-header">
        <div>
          <strong>LegalPDF Restore Plan</strong>
          <p>${escapeHtml(data?.message || "Read-only restore preview.")}</p>
        </div>
        <span class="status-chip ${statusChipClass(data?.status || "ready")}">${escapeHtml(data?.status || "ready")}</span>
      </div>
      <div class="data-list">
        <div class="data-item">
          <strong>${escapeHtml(data?.report?.report_id || "Apply report")}</strong>
          <span><strong>Restore allowed:</strong> ${data?.restore_allowed ? "yes" : "no - preview only"}</span>
          <span><strong>Backup available:</strong> ${data?.backup_available ? "yes" : "no"}</span>
          <span><strong>Blockers:</strong> ${escapeHtml(data?.blocking_count ?? 0)}</span>
        </div>
        ${profileRows || `<div class="data-item"><strong>Profiles</strong><span>No profile restore rows.</span></div>`}
        ${courtRows || `<div class="data-item"><strong>Court emails</strong><span>No court-email restore rows.</span></div>`}
      </div>
      <p class="field-hint">This restore plan is read-only. It shows hashes and intended actions only; no local files were changed and no LegalPDF data was touched.</p>
    </div>
    ${restoreControls}
    ${restoreReport}
  `;
}

async function loadLegalPdfApplyHistory() {
  const data = await requestJson("/api/integration/apply-history");
  renderLegalPdfApplyHistory(data);
  return data;
}

async function loadLegalPdfApplyDetail(reportId) {
  if (!reportId) throw new Error("Missing LegalPDF apply report id.");
  const data = await requestJson(`/api/integration/apply-detail?report_id=${encodeURIComponent(reportId)}`);
  renderLegalPdfApplyDetail(data);
  return data;
}

async function loadLegalPdfRestorePlan(reportId) {
  if (!reportId) throw new Error("Missing LegalPDF apply report id.");
  const data = await requestJson(`/api/integration/apply-restore-plan?report_id=${encodeURIComponent(reportId)}`);
  renderLegalPdfRestorePlan(data);
  return data;
}

async function applyLegalPdfRestore(reportId) {
  if (!reportId) throw new Error("Missing LegalPDF apply report id.");
  const payload = {
    report_id: reportId,
    confirm_restore: Boolean($("#confirm-legalpdf-restore")?.checked),
    confirmation_phrase: $("#legalpdf-restore-phrase")?.value.trim() || "",
    restore_reason: $("#legalpdf-restore-reason")?.value.trim() || "",
  };
  const data = await requestJson("/api/integration/apply-restore", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderLegalPdfRestorePlan(data);
  await loadReference();
  await loadBackupStatus();
  await loadLegalPdfApplyHistory();
  return data;
}

function historySourceRecords(source) {
  if (source === "duplicates") return state.reference?.duplicates || [];
  return state.reference?.draft_log || [];
}

function historyRecordByIndex(source, index) {
  const records = historySourceRecords(source);
  const record = records[Number(index)];
  if (!record) {
    throw new Error("History record is no longer available. Refresh Recent Work and try again.");
  }
  return record;
}

function isActiveDraftHistoryRecord(record, defaultStatus = "") {
  return ["active", "drafted"].includes(historyRecordStatus(record, defaultStatus));
}

function renderHistoryDraftActions(record, index, source, defaultStatus = "") {
  const draftId = String(record?.draft_id || "").trim();
  if (!draftId) return "";
  const messageId = String(record?.message_id || "").trim();
  const canMarkSent = isActiveDraftHistoryRecord(record, defaultStatus) && messageId;
  return `
    <div class="button-row compact-button-row history-row-actions">
      <button type="button" class="mini-button" data-history-verify-draft="${escapeHtml(index)}" data-history-source="${escapeHtml(source)}">Verify draft exists</button>
      ${canMarkSent ? `<button type="button" class="mini-button" data-history-mark-sent="${escapeHtml(index)}" data-history-source="${escapeHtml(source)}">Mark manually sent</button>` : ""}
    </div>
  `;
}

function renderHistoryDraftActionResult(data, kind = "") {
  const box = $("#history-draft-action-result");
  if (!box) return;
  if (!data) {
    box.className = "result-card compact-result hidden";
    box.textContent = "";
    return;
  }
  const status = data.status || kind || "info";
  const chipKind = statusChipClass(status === "verified" ? "ready" : status);
  const duplicateCount = Number(data.recorded_duplicate_count || data.duplicate_records_created?.length || 0);
  box.className = `result-card compact-result ${chipKind}`;
  box.innerHTML = `
    <div class="result-header compact-result-header">
      <div>
        <strong>${escapeHtml(data.message || status.replaceAll("_", " "))}</strong>
        <p>${status === "recorded" ? "Local bookkeeping only. Gmail was not contacted and no email was sent." : "Read-only Gmail draft verification. No local records were changed."}</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${data.draft_id ? `<div>Draft ID: <code>${escapeHtml(data.draft_id)}</code></div>` : ""}
    ${data.message_id ? `<div>Message ID: <code>${escapeHtml(data.message_id)}</code></div>` : ""}
    ${data.thread_id ? `<div>Thread ID: <code>${escapeHtml(data.thread_id)}</code></div>` : ""}
    ${data.sent_date ? `<div>Sent date: <strong>${escapeHtml(data.sent_date)}</strong></div>` : ""}
    ${data.gmail_api_action ? `<div><span class="status-chip info">${escapeHtml(data.gmail_api_action)}</span></div>` : ""}
    ${duplicateCount ? `<div>Duplicate records updated: <strong>${escapeHtml(duplicateCount)}</strong></div>` : ""}
  `;
}

function historyDraftStatusPayload(record, sentDate) {
  const payloadPath = String(record.payload || record.draft_payload || "").trim();
  return removeEmpty({
    payload: payloadPath,
    draft_payload: String(record.draft_payload || "").trim(),
    case_number: record.case_number,
    service_date: record.service_date,
    service_period_label: record.service_period_label,
    service_start_time: record.service_start_time,
    service_end_time: record.service_end_time,
    recipient: record.recipient || record.recipient_email,
    pdf: record.pdf,
    draft_id: record.draft_id,
    message_id: record.message_id,
    thread_id: record.thread_id,
    status: "sent",
    sent_date: sentDate,
    notes: `Marked manually sent from Recent Work on ${sentDate}.`,
  });
}

async function verifyHistoryDraft(index, source = "draft_log") {
  const record = historyRecordByIndex(source, index);
  const draftId = String(record.draft_id || "").trim();
  if (!draftId) throw new Error("This history row has no Gmail draft ID to verify.");
  const data = await requestJson("/api/gmail/drafts/verify", {
    method: "POST",
    body: JSON.stringify(removeEmpty({
      draft_id: draftId,
      message_id: record.message_id,
      thread_id: record.thread_id,
    })),
  });
  renderHistoryDraftActionResult(data, data.status || "verified");
  setStatus(data.status || "verified", data.message || "Gmail draft verification completed.");
  return data;
}

async function markHistoryDraftSent(index, source = "draft_log") {
  const record = historyRecordByIndex(source, index);
  const draftId = String(record.draft_id || "").trim();
  const messageId = String(record.message_id || "").trim();
  if (!draftId || !messageId) {
    throw new Error("This history row needs both draft ID and message ID before it can be marked sent.");
  }
  const sentDateInput = $("#history-sent-date");
  const sentDate = (sentDateInput?.value || todayIsoDate()).trim();
  if (sentDateInput && !sentDateInput.value) sentDateInput.value = sentDate;
  if (!sentDate) throw new Error("Choose the sent date before marking this draft as sent.");
  const confirmed = window.confirm(`Mark Gmail draft ${draftId} as manually sent on ${sentDate}? This is local bookkeeping only; it does not contact Gmail.`);
  if (!confirmed) return null;
  const data = await requestJson("/api/drafts/status", {
    method: "POST",
    body: JSON.stringify(historyDraftStatusPayload(record, sentDate)),
  });
  renderHistoryDraftActionResult({ ...data, sent_date: sentDate, message: `Marked ${draftId} as manually sent.` }, "recorded");
  setStatus("recorded", `Marked Gmail draft ${draftId} as manually sent locally.`);
  showAlert("Marked draft as sent locally. Duplicate protection now keeps the sent status.", "recorded");
  await loadReference();
  return data;
}

function renderReference() {
  const profiles = state.reference?.service_profiles || {};
  const profileSelect = $("#profile");
  const duplicateRecords = indexedHistoryRecords(state.reference?.duplicates || [], "sent");
  const draftLogRecords = indexedHistoryRecords(state.reference?.draft_log || [], "");
  profileSelect.innerHTML = `<option value="">Auto-detect profile - recommended for uploads</option>` + Object.entries(profiles)
    .map(([key, value]) => `<option value="${escapeHtml(key)}">${escapeHtml(key)} - ${escapeHtml(value.description || "")}</option>`)
    .join("");
  renderPersonalProfiles();

  $("#profile-list").innerHTML = Object.entries(profiles).map(([key, value]) => (
    `<div class="data-item">
      <strong>${escapeHtml(key)}</strong>
      <span>${escapeHtml(value.description || "")}</span>
      <button type="button" class="mini-button" data-edit-profile="${escapeHtml(key)}">Edit guarded profile</button>
    </div>`
  )).join("") || `<div class="data-item">No service profiles found.</div>`;

  $("#court-list").innerHTML = (state.reference?.court_emails || []).map((item, index) => (
    `<div class="data-item">
      <strong>${escapeHtml(item.key || item.email)}</strong>
      <span>${escapeHtml(item.name || "")}</span>
      <code>${escapeHtml(item.email || "")}</code>
      <button type="button" class="mini-button" data-edit-court="${index}">Edit</button>
    </div>`
  )).join("");

  $("#destination-list").innerHTML = (state.reference?.known_destinations || []).map((item, index) => (
    `<div class="data-item">
      <strong>${escapeHtml(item.name || item.destination || item.city || "Destination")}</strong>
      <span>${escapeHtml(item.km_one_way ?? item.km ?? "")} km</span>
      <button type="button" class="mini-button" data-edit-destination="${index}">Edit</button>
    </div>`
  )).join("");

  renderHistoryStatusFilters();

  $("#duplicate-list").innerHTML = duplicateRecords.length ? duplicateRecords.map(({ item, index }) => (
    `<div class="data-item">
      <strong>${escapeHtml(item.case_number)} · ${escapeHtml(item.service_date)}</strong>
      <span class="status-chip ${statusChipClass(item.status || "sent")}">${escapeHtml(item.status || "sent")}</span>
      <code>${escapeHtml(item.draft_id || item.pdf || "")}</code>
      ${renderHistoryDraftActions(item, index, "duplicates", "sent")}
    </div>`
  )).join("") : `<div class="data-item empty-history-item">No duplicate records for the selected history filter.</div>`;

  $("#draft-log-list").innerHTML = draftLogRecords.length ? draftLogRecords.map(({ item, index }) => (
    `<div class="data-item">
      <strong>${escapeHtml(item.case_number)} · ${escapeHtml(item.service_date)}</strong>
      <span class="status-chip ${statusChipClass(item.status || "")}">${escapeHtml(item.status || "")}</span>
      <code>${escapeHtml(item.draft_id || "")}</code>
      ${renderHistoryDraftActions(item, index, "draft_log", "")}
    </div>`
  )).join("") : `<div class="data-item empty-history-item">No Gmail draft records for the selected history filter.</div>`;

  $("#profile-change-list").innerHTML = (state.reference?.profile_change_log || [])
    .map((item, index) => ({ item, index }))
    .reverse()
    .map(({ item, index }) => (
    `<div class="data-item">
      <strong>${escapeHtml(item.record_key || item.profile_key || "")} · ${escapeHtml(item.action || "")}</strong>
      ${item.reference_kind ? `<span class="status-chip info">${escapeHtml(item.reference_kind)}</span>` : ""}
      <span>${escapeHtml((item.changes || []).length)} change(s)</span>
      <code>${escapeHtml(item.reason || item.changed_at || "")}</code>
      <div class="button-row">
        ${item.reference_kind
          ? `<span class="field-hint">Reference edit recorded for audit.</span>`
          : `<button type="button" class="mini-button" data-preview-profile-rollback="${index}">Preview rollback</button>
             <button type="button" class="mini-button" data-restore-profile-rollback="${index}">Restore previous profile</button>`}
      </div>
    </div>`
  )).join("");
}

function collectDestinationReferencePayload() {
  return {
    destination: $("#destination_name").value.trim(),
    km_one_way: $("#destination_km").value.trim(),
    institution_examples: parseReferenceLines($("#destination_examples").value),
    notes: $("#destination_notes").value.trim(),
    change_reason: $("#destination_change_reason").value.trim(),
  };
}

function collectCourtEmailReferencePayload() {
  return {
    key: $("#court_key").value.trim(),
    name: $("#court_name").value.trim(),
    email: $("#court_email").value.trim(),
    payment_entity_aliases: parseReferenceLines($("#court_aliases").value),
    source: $("#court_source").value.trim(),
    change_reason: $("#court_change_reason").value.trim(),
  };
}

function renderReferencePreview(data, cardSelector, textSelector) {
  const card = $(cardSelector);
  const text = $(textSelector);
  card.classList.remove("hidden");
  const change = data.reference_change || {};
  text.textContent = JSON.stringify({
    status: data.status,
    kind: data.kind,
    action: change.action,
    record_key: change.record_key,
    reason: change.reason,
    changes: change.changes || [],
    record: data.record || {},
    write_allowed: data.write_allowed === true,
    send_allowed: data.send_allowed === true,
  }, null, 2);
}

async function previewDestinationReference() {
  const data = await requestJson("/api/reference/destinations/preview", {
    method: "POST",
    body: JSON.stringify(removeEmpty(collectDestinationReferencePayload())),
  });
  renderReferencePreview(data, "#destination-preview-card", "#destination-preview-text");
  setStatus("ready", `Previewed destination ${data.record.destination}. Nothing was saved.`);
  showAlert("Destination diff previewed. Nothing was saved.", "recorded");
}

async function saveDestinationReference() {
  maybeShowBackupReminder("saving destinations");
  const payload = collectDestinationReferencePayload();
  const data = await requestJson("/api/reference/destinations", {
    method: "POST",
    body: JSON.stringify(removeEmpty(payload)),
  });
  renderReferencePreview(data, "#destination-preview-card", "#destination-preview-text");
  setStatus("recorded", `Saved destination ${data.record.destination}.`);
  showAlert(`Saved destination ${data.record.destination}.`, "recorded");
  await loadReference();
}

async function previewCourtEmailReference() {
  const data = await requestJson("/api/reference/court-emails/preview", {
    method: "POST",
    body: JSON.stringify(removeEmpty(collectCourtEmailReferencePayload())),
  });
  renderReferencePreview(data, "#court-email-preview-card", "#court-email-preview-text");
  setStatus("ready", `Previewed court email ${data.record.email}. Nothing was saved.`);
  showAlert("Court-email diff previewed. Nothing was saved.", "recorded");
}

async function saveCourtEmailReference() {
  maybeShowBackupReminder("saving court emails");
  const payload = collectCourtEmailReferencePayload();
  const data = await requestJson("/api/reference/court-emails", {
    method: "POST",
    body: JSON.stringify(removeEmpty(payload)),
  });
  renderReferencePreview(data, "#court-email-preview-card", "#court-email-preview-text");
  setStatus("recorded", `Saved court email ${data.record.email}.`);
  showAlert(`Saved court email ${data.record.email}.`, "recorded");
  await loadReference();
}

function collectServiceProfileReferencePayload() {
  return {
    key: $("#profile_key").value.trim(),
    description: $("#profile_description").value.trim(),
    service_date_source: $("#profile_service_date_source").value,
    addressee: $("#profile_addressee").value.trim(),
    payment_entity: $("#profile_payment_entity").value.trim(),
    recipient_email: $("#profile_recipient_email").value.trim(),
    court_email_key: $("#profile_court_email_key").value.trim(),
    service_entity: $("#profile_service_entity").value.trim(),
    service_entity_type: $("#profile_service_entity_type").value,
    entities_differ: $("#profile_entities_differ").checked,
    service_place: $("#profile_service_place").value.trim(),
    service_place_phrase: $("#profile_service_place_phrase").value.trim(),
    claim_transport: $("#profile_claim_transport").checked,
    transport_destination: $("#profile_transport_destination").value.trim(),
    km_one_way: $("#profile_km_one_way").value.trim(),
    closing_city: $("#profile_closing_city").value.trim(),
    source_text_template: $("#profile_source_text_template").value.trim(),
    notes_template: $("#profile_notes_template").value.trim(),
    change_reason: $("#profile_change_reason").value.trim(),
  };
}

async function previewServiceProfileReference() {
  const data = await requestJson("/api/reference/service-profiles/preview", {
    method: "POST",
    body: JSON.stringify(removeEmpty(collectServiceProfileReferencePayload())),
  });
  renderProfilePreview(data);
  setStatus("ready", `Previewed guarded service profile ${data.key}.`);
  showAlert("Profile diff previewed. Nothing was saved.", "recorded");
}

async function saveServiceProfileReference() {
  maybeShowBackupReminder("saving a service profile");
  const payload = collectServiceProfileReferencePayload();
  const data = await requestJson("/api/reference/service-profiles", {
    method: "POST",
    body: JSON.stringify(removeEmpty(payload)),
  });
  renderProfilePreview(data);
  setStatus("recorded", `Saved guarded service profile ${data.key}.`);
  showAlert(`Saved guarded service profile ${data.key}.`, "recorded");
  await loadReference();
}

async function previewProfileRollback(index) {
  const data = await requestJson("/api/reference/service-profiles/rollback-preview", {
    method: "POST",
    body: JSON.stringify(removeEmpty({
      change_index: index,
      reason: $("#profile_change_reason").value.trim(),
    })),
  });
  renderProfilePreview(data);
  setStatus("ready", `Previewed rollback for ${data.key}.`);
  showAlert("Rollback previewed. Nothing was saved.", "recorded");
}

async function restoreProfileRollback(index) {
  maybeShowBackupReminder("restoring a service profile");
  const data = await requestJson("/api/reference/service-profiles/rollback", {
    method: "POST",
    body: JSON.stringify(removeEmpty({
      change_index: index,
      reason: $("#profile_change_reason").value.trim(),
    })),
  });
  renderProfilePreview(data);
  setStatus("recorded", `Restored previous profile for ${data.key}.`);
  showAlert(`Restored previous profile for ${data.key}.`, "recorded");
  await loadReference();
}

function fillDestinationReferenceForm(index) {
  const item = state.reference?.known_destinations?.[index];
  if (!item) return;
  $("#destination_name").value = item.destination || item.name || item.city || "";
  $("#destination_km").value = item.km_one_way ?? item.km ?? "";
  $("#destination_examples").value = (item.institution_examples || []).join("\n");
  $("#destination_notes").value = item.notes || "";
  $("#destination_change_reason").value = "";
  $("#destination-preview-card").classList.add("hidden");
}

function fillCourtEmailReferenceForm(index) {
  const item = state.reference?.court_emails?.[index];
  if (!item) return;
  $("#court_key").value = item.key || "";
  $("#court_name").value = item.name || "";
  $("#court_email").value = item.email || "";
  $("#court_aliases").value = (item.payment_entity_aliases || []).join("\n");
  $("#court_source").value = item.source || "";
  $("#court_change_reason").value = "";
  $("#court-email-preview-card").classList.add("hidden");
}

function fillServiceProfileReferenceForm(key) {
  const item = state.reference?.service_profiles?.[key];
  if (!item) return;
  const defaults = item.defaults || {};
  const transport = defaults.transport || {};
  $("#profile_key").value = key;
  $("#profile_description").value = item.description || "";
  $("#profile_service_date_source").value = defaults.service_date_source || "user_confirmed";
  $("#profile_addressee").value = defaults.addressee || "";
  $("#profile_payment_entity").value = defaults.payment_entity || "";
  $("#profile_recipient_email").value = defaults.recipient_email || "";
  $("#profile_court_email_key").value = defaults.court_email_key || "";
  $("#profile_service_entity").value = defaults.service_entity || "";
  $("#profile_service_entity_type").value = defaults.service_entity_type || "court";
  $("#profile_entities_differ").checked = Boolean(defaults.entities_differ);
  $("#profile_service_place").value = defaults.service_place || "";
  $("#profile_service_place_phrase").value = defaults.service_place_phrase || "";
  $("#profile_claim_transport").checked = defaults.claim_transport !== false;
  $("#profile_transport_destination").value = transport.destination || "";
  $("#profile_km_one_way").value = transport.km_one_way ?? "";
  $("#profile_closing_city").value = defaults.closing_city || "";
  $("#profile_source_text_template").value = item.source_text_template || "";
  $("#profile_notes_template").value = item.notes_template || "";
  $("#profile_change_reason").value = "";
}

function fillServiceProfileProposalForm(proposal) {
  const payload = proposal?.payload || {};
  if (!payload.key) {
    throw new Error("No proposed profile is available from the latest source.");
  }
  $("#profile_key").value = payload.key || "";
  $("#profile_description").value = payload.description || "";
  $("#profile_service_date_source").value = payload.service_date_source || "user_confirmed";
  $("#profile_addressee").value = payload.addressee || "";
  $("#profile_payment_entity").value = payload.payment_entity || "";
  $("#profile_recipient_email").value = payload.recipient_email || "";
  $("#profile_court_email_key").value = payload.court_email_key || "";
  $("#profile_service_entity").value = payload.service_entity || "";
  $("#profile_service_entity_type").value = payload.service_entity_type || "court";
  $("#profile_entities_differ").checked = Boolean(payload.entities_differ);
  $("#profile_service_place").value = payload.service_place || "";
  $("#profile_service_place_phrase").value = payload.service_place_phrase || "";
  $("#profile_claim_transport").checked = payload.claim_transport !== false;
  $("#profile_transport_destination").value = payload.transport_destination || "";
  $("#profile_km_one_way").value = payload.km_one_way ?? "";
  $("#profile_closing_city").value = payload.closing_city || "";
  $("#profile_source_text_template").value = payload.source_text_template || "";
  $("#profile_notes_template").value = payload.notes_template || "";
  $("#profile_change_reason").value = payload.change_reason || "Proposed from uploaded source evidence; review before saving.";
}

function renderProfilePreview(data) {
  const card = $("#profile-preview-card");
  const text = $("#profile-preview-text");
  if (!data) {
    card.classList.add("hidden");
    text.textContent = "";
    return;
  }
  const preview = data.preview || data;
  const change = data.profile_change || null;
  const changeLines = change
    ? [
        `Profile change: ${change.action || ""}`,
        `Reason: ${change.reason || ""}`,
        ...(change.changes || []).map((item) => `${item.change}: ${item.path}\n  before: ${JSON.stringify(item.before)}\n  after: ${JSON.stringify(item.after)}`),
        "",
      ]
    : [];
  card.classList.remove("hidden");
  text.textContent = [
    ...changeLines,
    preview.draft_text || preview.question_text || JSON.stringify(preview.sample_intake || preview, null, 2),
  ].join("\n");
}

function personalProfilesData() {
  return state.reference?.personal_profiles || { profiles: [], primary_profile_id: "" };
}

function personalProfileName(profile) {
  return profile?.display_name || profile?.document_name_override || `${profile?.first_name || ""} ${profile?.last_name || ""}`.trim() || profile?.id || "Profile";
}

function renderPersonalProfileSelector() {
  const select = $("#personal_profile_id");
  if (!select) return;
  const data = personalProfilesData();
  const primary = data.primary_profile_id || "";
  const options = (data.profiles || []).map((profile) => {
    const id = profile.id || "";
    const suffix = id === primary ? " (main)" : "";
    return `<option value="${escapeHtml(id)}">${escapeHtml(personalProfileName(profile) + suffix)}</option>`;
  }).join("");
  select.innerHTML = options || `<option value="">Main profile</option>`;
  if (state.currentIntake?.personal_profile_id) {
    select.value = state.currentIntake.personal_profile_id;
  } else if (primary) {
    select.value = primary;
  }
}

function renderPersonalProfiles() {
  const data = personalProfilesData();
  const profiles = data.profiles || [];
  const primaryId = data.primary_profile_id || "";
  const main = data.main_profile || profiles.find((profile) => profile.id === primaryId) || profiles[0] || {};
  const count = $("#personal-profile-count");
  if (count) count.textContent = `${profiles.length} profile(s) ready.`;
  const primaryCard = $("#personal-profile-primary-card");
  if (primaryCard) {
    primaryCard.innerHTML = `
      <div class="profile-record-card-header">
        <div>
          <p class="eyebrow">Main Profile Summary</p>
          <strong>${escapeHtml(personalProfileName(main))}</strong>
          <p>${escapeHtml(main.email || main.phone_number || "Add email or phone details to use them in Gmail replies.")}</p>
          <span>Travel origin: ${escapeHtml(main.travel_origin_label || "")}</span>
          <span>${escapeHtml(String(Object.keys(main.travel_distances_by_city || {}).length))} saved city distance(s).</span>
        </div>
        <span class="status-chip ready">Main profile</span>
      </div>`;
  }
  const list = $("#personal-profile-list");
  if (list) {
    list.innerHTML = profiles.map((profile) => `
      <div class="profile-record-card">
        <div class="profile-record-card-header">
          <div>
            <p class="eyebrow">Profile Record</p>
            <strong>${escapeHtml(personalProfileName(profile))}</strong>
            <p>${escapeHtml(profile.email || profile.phone_number || "Add email or phone details to use them in Gmail replies.")}</p>
            <span>Travel origin: ${escapeHtml(profile.travel_origin_label || "")}</span>
            <span>${escapeHtml(String(Object.keys(profile.travel_distances_by_city || {}).length))} saved city distance(s).</span>
          </div>
          ${profile.id === primaryId ? `<span class="status-chip ready">Main profile</span>` : ""}
        </div>
        <p>Edit this profile's contact, payment, and travel details.</p>
        <div class="button-row">
          <button type="button" class="mini-button" data-edit-personal-profile="${escapeHtml(profile.id || "")}">Edit</button>
          <button type="button" class="mini-button" data-main-personal-profile="${escapeHtml(profile.id || "")}" ${profile.id === primaryId ? "disabled" : ""}>Main profile</button>
          <button type="button" class="mini-button" data-delete-personal-profile="${escapeHtml(profile.id || "")}" ${profiles.length <= 1 ? "disabled" : ""}>Delete profile</button>
        </div>
      </div>
    `).join("") || `<div class="data-item">No profiles yet.</div>`;
  }
  renderPersonalProfileSelector();
}

function openPersonalProfileDrawer(profile) {
  const profileData = profile || {};
  state.currentPersonalProfile = { ...profileData, travel_distances_by_city: { ...(profileData.travel_distances_by_city || {}) } };
  $("#pp_id").value = state.currentPersonalProfile.id || "";
  $("#pp_first_name").value = state.currentPersonalProfile.first_name || "";
  $("#pp_last_name").value = state.currentPersonalProfile.last_name || "";
  $("#pp_document_name_override").value = state.currentPersonalProfile.document_name_override || "";
  $("#pp_email").value = state.currentPersonalProfile.email || "";
  $("#pp_phone_number").value = state.currentPersonalProfile.phone_number || "";
  $("#pp_travel_origin_label").value = state.currentPersonalProfile.travel_origin_label || "Marmelar";
  $("#pp_postal_address").value = state.currentPersonalProfile.postal_address || "";
  $("#pp_iban").value = state.currentPersonalProfile.iban || "";
  $("#pp_iva_text").value = state.currentPersonalProfile.iva_text || "23%";
  $("#pp_irs_text").value = state.currentPersonalProfile.irs_text || "Sem retenção";
  $("#pp_make_main").checked = state.currentPersonalProfile.id === personalProfilesData().primary_profile_id;
  $("#personal-profile-drawer-title").textContent = state.currentPersonalProfile.id ? "Edit Profile" : "Add Profile";
  $("#personal-profile-drawer-summary").textContent = `Editing ${personalProfileName(state.currentPersonalProfile)}. Update the details, then save.`;
  syncPersonalDistanceJson();
  renderPersonalDistanceList();
  $("#personal-profile-drawer-backdrop").classList.remove("hidden");
  $("#personal-profile-drawer-backdrop").setAttribute("aria-hidden", "false");
}

function closePersonalProfileDrawer() {
  $("#personal-profile-drawer-backdrop").classList.add("hidden");
  $("#personal-profile-drawer-backdrop").setAttribute("aria-hidden", "true");
}

function currentPersonalProfileFromForm() {
  let distances = state.currentPersonalProfile?.travel_distances_by_city || {};
  const rawJson = $("#pp_distances_json").value.trim();
  if (rawJson) {
    try {
      const parsed = JSON.parse(rawJson);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) distances = parsed;
    } catch (_error) {
      // Keep the interactive list as source of truth when advanced JSON is malformed.
    }
  }
  return {
    id: $("#pp_id").value.trim(),
    first_name: $("#pp_first_name").value.trim(),
    last_name: $("#pp_last_name").value.trim(),
    document_name_override: $("#pp_document_name_override").value.trim(),
    email: $("#pp_email").value.trim(),
    phone_number: $("#pp_phone_number").value.trim(),
    postal_address: $("#pp_postal_address").value.trim(),
    iban: $("#pp_iban").value.trim(),
    iva_text: $("#pp_iva_text").value.trim(),
    irs_text: $("#pp_irs_text").value.trim(),
    travel_origin_label: $("#pp_travel_origin_label").value.trim(),
    travel_distances_by_city: distances,
  };
}

function syncPersonalDistanceJson() {
  $("#pp_distances_json").value = JSON.stringify(state.currentPersonalProfile?.travel_distances_by_city || {}, null, 2);
}

function renderPersonalDistanceList() {
  const list = $("#pp_distance_list");
  const distances = state.currentPersonalProfile?.travel_distances_by_city || {};
  const rows = Object.entries(distances).map(([city, km]) => `
    <div class="profile-distance-row">
      <div>
        <strong>${escapeHtml(city)}</strong>
        <span>${escapeHtml(km)} km one way</span>
      </div>
      <button type="button" class="mini-button" data-delete-profile-distance="${escapeHtml(city)}">Delete destination</button>
    </div>
  `).join("");
  list.innerHTML = rows || `<div class="data-item">No saved city distances yet.</div>`;
}

function addPersonalDistance() {
  if (!state.currentPersonalProfile) state.currentPersonalProfile = { travel_distances_by_city: {} };
  const city = $("#pp_distance_city").value.trim();
  const km = Number($("#pp_distance_km").value);
  if (!city || !Number.isFinite(km) || km < 0) {
    throw new Error("Add a city and a valid one-way distance.");
  }
  state.currentPersonalProfile.travel_distances_by_city = {
    ...(state.currentPersonalProfile.travel_distances_by_city || {}),
    [city]: Math.round(km),
  };
  $("#pp_distance_city").value = "";
  $("#pp_distance_km").value = "";
  syncPersonalDistanceJson();
  renderPersonalDistanceList();
}

async function saveCurrentPersonalProfile() {
  maybeShowBackupReminder("saving a personal profile");
  const data = await requestJson("/api/profiles/save", {
    method: "POST",
    body: JSON.stringify({ profile: currentPersonalProfileFromForm(), make_main: $("#pp_make_main").checked }),
  });
  state.reference.personal_profiles = data.profiles;
  renderPersonalProfiles();
  setStatus("recorded", data.message || "Personal profile saved.");
  showAlert(data.message || "Personal profile saved.", "recorded");
  closePersonalProfileDrawer();
  await loadReference();
}

async function setMainPersonalProfile(profileId = "") {
  const id = profileId || $("#pp_id").value.trim();
  if (!id) throw new Error("Choose a profile first.");
  const data = await requestJson("/api/profiles/set-main", {
    method: "POST",
    body: JSON.stringify({ profile_id: id }),
  });
  state.reference.personal_profiles = data.profiles;
  renderPersonalProfiles();
  showAlert(data.message || "Main profile updated.", "recorded");
  await loadReference();
}

async function deletePersonalProfile(profileId = "") {
  const id = profileId || $("#pp_id").value.trim();
  if (!id) throw new Error("Choose a profile first.");
  maybeShowBackupReminder("deleting a personal profile");
  const data = await requestJson("/api/profiles/delete", {
    method: "POST",
    body: JSON.stringify({ profile_id: id }),
  });
  state.reference.personal_profiles = data.profiles;
  renderPersonalProfiles();
  showAlert(data.message || "Personal profile deleted.", "recorded");
  closePersonalProfileDrawer();
  await loadReference();
}

function renderLegalPdfPersonalProfileImport(data) {
  const card = $("#legalpdf-personal-profile-import-card");
  const body = $("#legalpdf-personal-profile-import-body");
  card.classList.remove("hidden");
  const changes = (data?.changes || []).map((item) => `
    <div class="data-item">
      <strong>${escapeHtml(item.display_name || item.profile_id || "")}</strong>
      <span>${escapeHtml(item.action || "")}</span>
      <code>${escapeHtml(item.profile_id || "")}</code>
    </div>
  `).join("");
  body.innerHTML = `
    <p>${escapeHtml(data?.message || "Preview LegalPDF profile copy before applying.")}</p>
    <div class="data-list">${changes || `<div class="data-item">No profile changes found.</div>`}</div>
    <p class="field-hint">Confirmation phrase: ${escapeHtml(data?.confirmation_phrase || "COPY LEGALPDF PROFILES")}</p>
  `;
}

async function previewLegalPdfPersonalProfiles() {
  const data = await requestJson("/api/profiles/import-legalpdf-preview", {
    method: "POST",
    body: JSON.stringify({}),
  });
  state.legalPdfPersonalProfileImportPreview = data;
  renderLegalPdfPersonalProfileImport(data);
  showAlert("LegalPDF personal profile import previewed. No files were changed.", "recorded");
  showPanel("profiles");
}

async function applyLegalPdfPersonalProfiles() {
  maybeShowBackupReminder("copying LegalPDF personal profiles");
  const data = await requestJson("/api/profiles/import-legalpdf", {
    method: "POST",
    body: JSON.stringify({
      confirm_import: Boolean($("#confirm_legalpdf_personal_import").checked),
      confirmation_phrase: $("#legalpdf_personal_import_phrase").value.trim(),
      import_reason: $("#legalpdf_personal_import_reason").value.trim(),
    }),
  });
  state.reference.personal_profiles = data.profiles;
  renderPersonalProfiles();
  renderLegalPdfPersonalProfileImport({ ...data, confirmation_phrase: "COPY LEGALPDF PROFILES" });
  showAlert(data.message || "LegalPDF personal profiles copied locally.", "recorded");
  await loadReference();
}

function collectProfilePayload() {
  return {
    personal_profile_id: $("#personal_profile_id").value,
    profile: $("#profile").value,
    case_number: $("#case_number").value.trim(),
    service_date: $("#service_date").value,
    photo_metadata_date: $("#photo_metadata_date").value,
    service_period_label: $("#service_period_label").value.trim(),
    service_start_time: $("#service_start_time").value.trim(),
    service_end_time: $("#service_end_time").value.trim(),
    payment_entity: $("#payment_entity").value.trim(),
    recipient_email: $("#recipient_email").value.trim(),
    service_place: $("#service_place").value.trim(),
    km_one_way: $("#km_one_way").value.trim(),
    source_text: $("#source_text").value.trim(),
  };
}

function removeEmpty(value) {
  if (Array.isArray(value)) {
    return value.map(removeEmpty).filter((item) => item !== undefined);
  }
  if (value && typeof value === "object") {
    const output = {};
    Object.entries(value).forEach(([key, entry]) => {
      const cleaned = removeEmpty(entry);
      if (cleaned !== undefined) output[key] = cleaned;
    });
    return Object.keys(output).length ? output : undefined;
  }
  if (value === "" || value === null || value === undefined) return undefined;
  return value;
}

async function buildIntakeFromProfile() {
  const payload = removeEmpty(collectProfilePayload());
  if (!payload.profile) {
    payload.profile = "court_mp_generic";
  }
  const existingAttachments = normalizeAttachmentList(state.currentIntake?.additional_attachment_files);
  const existingEmailBody = String(state.currentIntake?.email_body || "").trim();
  const data = await requestJson("/api/intake/from-profile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.currentIntake = mergeSupportingAttachmentsIntoIntake(data.intake, existingAttachments, existingEmailBody);
  fillFormFromIntake(state.currentIntake);
  applyReview(data.review);
}

async function reviewIntake() {
  if (!state.currentIntake) {
    await buildIntakeFromProfile();
    return;
  }
  mergeFormIntoCurrentIntake();
  const data = await requestJson("/api/review", {
    method: "POST",
    body: JSON.stringify({ intake: state.currentIntake }),
  });
  applyReview(data);
}

async function applyNumberedAnswers() {
  if (!state.currentIntake) {
    await buildIntakeFromProfile();
  }
  mergeFormIntoCurrentIntake();
  const answers = $("#numbered-answers").value.trim();
  if (!answers) {
    throw new Error("Paste numbered answers before applying them.");
  }
  const data = await requestJson("/api/review/apply-answers", {
    method: "POST",
    body: JSON.stringify({ intake: state.currentIntake, answers }),
  });
  state.currentIntake = data.intake || state.currentIntake;
  fillFormFromIntake(state.currentIntake);
  applyReview(data);
  const applied = data.applied_fields?.length
    ? data.applied_fields.join(", ")
    : "no matching fields";
  showAlert(`Applied numbered answers: ${applied}.`, data.status === "ready" ? "recorded" : "blocked");
  openReviewDrawer();
  return data;
}

async function activeCheck() {
  if (!state.currentIntake) {
    await buildIntakeFromProfile();
  }
  mergeFormIntoCurrentIntake();
  const data = await requestJson("/api/drafts/active-check", {
    method: "POST",
    body: JSON.stringify({ intake: state.currentIntake }),
  });
  state.draftLifecycle = data;
  renderDraftLifecycle(data);
  return data;
}

async function addCurrentIntakeToBatch() {
  if (!state.currentIntake) {
    await buildIntakeFromProfile();
  }
  mergeFormIntoCurrentIntake();
  const review = await requestJson("/api/review", {
    method: "POST",
    body: JSON.stringify({ intake: state.currentIntake }),
  });
  applyReview(review);
  if (review.status !== "ready") {
    throw new Error("Only a ready reviewed request can be added to the batch queue.");
  }
  const intake = cloneIntake(state.currentIntake);
  const key = batchIntakeKey(intake);
  const existingIndex = state.batchIntakes.findIndex((queued) => batchIntakeKey(queued) === key);
  if (existingIndex >= 0) {
    state.batchIntakes[existingIndex] = intake;
    state.batchSelectedIndex = existingIndex;
  } else {
    state.batchIntakes.push(intake);
    state.batchSelectedIndex = state.batchIntakes.length - 1;
  }
  state.batchPreflight = null;
  renderBatchQueue();
  setStatus("ready", `${intake.case_number || "Request"} added to the batch queue.`);
  showAlert("Batch queue updated. Prepare the package when all related requests are queued.", "recorded");
  try {
    await preflightBatchIntakes({ openDrawer: false, showResultAlert: false });
  } catch (_error) {
    renderBatchPreflight();
  }
}

async function prepareBatchIntakes() {
  if (!state.batchIntakes.length) {
    throw new Error("Add at least one ready request to the batch queue first.");
  }
  if (!hasCurrentReadyBatchPreflight()) {
    renderBatchPreflight();
    throw new Error("Run a current ready batch preflight before preparing artifacts.");
  }
  const packetMode = currentBatchPacketMode();
  const intakes = state.batchIntakes.map(cloneIntake);
  const data = await requestJson("/api/prepare", {
    method: "POST",
    body: JSON.stringify({
      intakes,
      render_previews: true,
      packet_mode: packetMode,
      preflight_review: state.batchPreflight?.preflight_review || null,
    }),
  });
  state.lastPrepared = data;
  const modeText = packetMode ? "as one packet PDF" : "as separate Gmail draft payloads";
  setStatus(data.status, `${state.batchIntakes.length} queued request${state.batchIntakes.length === 1 ? "" : "s"} prepared ${modeText}.`);
  showAlert("", "");
  renderPrepared(data);
  openReviewDrawer();
  await loadReference();
}

async function preflightBatchIntakes(options = {}) {
  if (!state.batchIntakes.length) {
    throw new Error("Add at least one ready request to the batch queue first.");
  }
  const openDrawerAfter = options.openDrawer !== false;
  const showResultAlert = options.showResultAlert !== false;
  const packetMode = currentBatchPacketMode();
  const intakes = state.batchIntakes.map(cloneIntake);
  const requestSignature = batchPreflightSignature(packetMode, intakes);
  const data = await requestJson("/api/prepare/preflight", {
    method: "POST",
    body: JSON.stringify({ intakes, packet_mode: packetMode }),
  });
  state.batchPreflight = { ...data, request_signature: requestSignature };
  renderBatchPreflight();
  renderNextSafeAction(data.next_safe_action || null);
  const modeText = packetMode ? "packet mode" : "separate-payload mode";
  setStatus(data.status, `Batch preflight checked in ${modeText}; no PDFs or draft payloads were created.`);
  if (showResultAlert) {
    if (data.status === "blocked") {
      showAlert(data.message || "Batch preflight blocked.", "blocked");
    } else {
      showAlert("Batch preflight clear. Review once more before preparing artifacts.", "recorded");
    }
  }
  if (openDrawerAfter) {
    openReviewDrawer();
  }
  return data;
}

function applyReview(data) {
  clearPreparedArtifacts("review changed");
  if (data.effective_intake || data.intake) {
    state.currentIntake = data.effective_intake || data.intake;
    fillFormFromIntake(state.currentIntake);
  }
  if (data.review_evidence) {
    state.lastProfileProposal = data.profile_proposal || data.review_evidence.profile_proposal || null;
    renderSourceEvidence(data);
  }
  setStatus(data.status, data.message);
  showQuestions(data);
  renderNextSafeAction(data.next_safe_action || null);
  const alertNeeded = ["duplicate", "active_draft", "set_aside", "error"].includes(data.status);
  showAlert(alertNeeded ? data.message : "", data.status === "error" ? "error" : "blocked");
  updateHomeReviewCard(data);
  $("#draft-text").textContent = data.draft_text || data.question_text || "The Portuguese draft will appear here before the PDF is created.";
  const profileText = data.personal_profile?.personal_profile_name ? ` · Profile: ${data.personal_profile.personal_profile_name}` : "";
  $("#recipient-summary").textContent = data.recipient ? `To: ${data.recipient}${profileText}` : `Recipient appears here after review.${profileText}`;
  if (data.active_gmail_drafts || data.duplicate) {
    state.draftLifecycle = {
      status: ["duplicate", "active_draft"].includes(data.status) ? "blocked" : data.status,
      message: data.message,
      active_gmail_drafts: data.active_gmail_drafts || [],
      duplicate: data.duplicate || null,
      duplicate_records: data.duplicate ? [data.duplicate] : [],
      replacement_allowed: data.status === "duplicate" && data.duplicate?.status === "drafted" || data.status === "active_draft",
      send_allowed: false,
    };
    renderDraftLifecycle(state.draftLifecycle);
  }

  if (["ready", "needs_info", "duplicate", "active_draft", "set_aside"].includes(data.status)) {
    openReviewDrawer();
  }
}

async function prepareIntake(options = {}) {
  if (!state.currentIntake) {
    await buildIntakeFromProfile();
  }
  mergeFormIntoCurrentIntake();
  const requestPayload = { intakes: [state.currentIntake], render_previews: true };
  if (options.correctionMode) {
    requestPayload.correction_mode = true;
    requestPayload.correction_reason = ($("#correction_reason").value || "").trim();
    if (!requestPayload.correction_reason) {
      throw new Error("Correction mode requires a reason before preparing a replacement draft.");
    }
  }
  const preflightPayload = {
    intakes: [cloneIntake(state.currentIntake)],
    packet_mode: false,
  };
  if (requestPayload.correction_mode) {
    preflightPayload.correction_mode = true;
    preflightPayload.correction_reason = requestPayload.correction_reason;
  }
  const preflight = await requestJson("/api/prepare/preflight", {
    method: "POST",
    body: JSON.stringify(preflightPayload),
  });
  renderNextSafeAction(preflight.next_safe_action || null);
  if (preflight.status !== "ready" || !preflight.preflight_review) {
    const message = preflight.message || "Run a current ready preflight before preparing artifacts.";
    setStatus(preflight.status || "blocked", message);
    showAlert(message, "blocked");
    openReviewDrawer();
    throw new Error(message);
  }
  requestPayload.preflight_review = preflight.preflight_review;
  const data = await requestJson("/api/prepare", {
    method: "POST",
    body: JSON.stringify(requestPayload),
  });
  state.lastPrepared = data;
  setStatus(data.status, "PDF and Gmail draft payload prepared. Review before using Gmail _create_draft.");
  showAlert("", "");
  renderPrepared(data);
  openReviewDrawer();
  await loadReference();
}

function renderPrepared(data) {
  const items = data.items || [];
  const packet = data.packet || null;
  const first = items[0];
  state.lastManualHandoff = null;
  $("#prepare-results").removeAttribute("data-stale-reason");
  $("#gmail_handoff_reviewed").checked = false;
  renderManualHandoffPacket(null);
  renderNextSafeAction(data.next_safe_action || null);
  const previewPanel = $("#pdf-preview-panel");
  const previewBox = $("#pdf-preview");
  const packetPreviews = packet
    ? (packet.png_preview_urls || []).slice(0, 1).map((url) => ({ url, item: packet, label: "Packet PDF" }))
    : [];
  const itemPreviews = items.flatMap((item) => (
    (item.png_preview_urls || []).slice(0, 1).map((url) => ({ url, item }))
  ));
  const previewImages = [...packetPreviews, ...itemPreviews];
  if (previewImages.length) {
    previewPanel.classList.remove("hidden");
    previewBox.innerHTML = previewImages.map(({ url, item }) => (
      `<figure class="pdf-preview-figure">
        <img class="pdf-preview-image" src="${escapeHtml(url)}" alt="Generated PDF preview for ${escapeHtml(item.case_number)}">
        <figcaption>${escapeHtml(item.case_number || "packet")} · ${escapeHtml(item.service_date || "packet")} ${item.packet_mode ? "· packet" : ""}</figcaption>
      </figure>`
    )).join("");
  } else if (packet?.preview_warning || first?.preview_warning) {
    previewPanel.classList.remove("hidden");
    previewBox.innerHTML = `<div class="result-card blocked">${escapeHtml(packet?.preview_warning || first.preview_warning)}</div>`;
  } else {
    previewPanel.classList.add("hidden");
    previewBox.innerHTML = "";
  }
  const packetCard = packet ? `
    <div class="result-card prepared packet-prepared-card">
      <div class="result-header">
        <div>
          <strong>Combined packet PDF · ${escapeHtml(packet.underlying_requests?.length || items.length)} request${(packet.underlying_requests?.length || items.length) === 1 ? "" : "s"}</strong>
          <p>Prepared for Gmail _create_draft with one attachment. No send action exists here.</p>
        </div>
        <span class="status-chip ready">packet ready</span>
      </div>
      <div class="prepared-meta">
        <div>Recipient: <code>${escapeHtml(packet.recipient)}</code></div>
        <div>Packet PDF: <code>${escapeHtml(packet.pdf)}</code></div>
        <div>Packet payload: <code>${escapeHtml(packet.draft_payload)}</code></div>
        <div>Attachment count: ${escapeHtml(packet.attachment_count)}</div>
        <div>Underlying requests: ${escapeHtml(packet.underlying_requests?.length || 0)}</div>
      </div>
      <strong>Exact gmail_create_draft_args</strong>
      <pre class="draft-args">${escapeHtml(JSON.stringify(packet.gmail_create_draft_args || {}, null, 2))}</pre>
      <div class="packet-sequence prepared-packet-sequence">
        <strong>Packet contents</strong>
        ${renderPreparedPacketContents(items)}
      </div>
      ${renderPacketRecordHelper(packet)}
    </div>
  ` : "";
  const itemCards = items.map((item) => (
    `<div class="result-card prepared">
      <div class="result-header">
        <div>
          <strong>${escapeHtml(item.case_number)} · ${escapeHtml(item.service_date)}</strong>
          <p>${packet ? "Source PDF generated for the packet." : "Prepared for Gmail _create_draft. No send action exists here."}</p>
        </div>
        <span class="status-chip ready">prepared</span>
      </div>
      <div class="prepared-meta">
        <div>Recipient: <code>${escapeHtml(item.recipient)}</code></div>
        <div>PDF: <code>${escapeHtml(item.pdf)}</code></div>
        <div>Payload: <code>${escapeHtml(item.draft_payload)}</code></div>
        <div>Attachment count: ${escapeHtml(item.attachment_count)}</div>
      </div>
      <strong>Exact gmail_create_draft_args</strong>
      <pre class="draft-args">${escapeHtml(JSON.stringify(item.gmail_create_draft_args || {}, null, 2))}</pre>
    </div>`
  )).join("");
  $("#prepare-results").innerHTML = packetCard + itemCards;
  if (packet?.draft_payload || first?.draft_payload) {
    $("#record_payload").value = packet?.draft_payload || first.draft_payload;
  }
  if (data.correction_mode) {
    renderDraftLifecycle({
      status: "blocked",
      message: `Replacement payload prepared. Reason: ${data.correction_reason || "not provided"}`,
      active_gmail_drafts: first?.active_gmail_drafts || first?.draft_lifecycle?.active_gmail_drafts || [],
      duplicate_records: first?.draft_lifecycle?.duplicate_records || [],
      replacement_allowed: true,
      send_allowed: false,
    });
  }
  syncActionGates();
}

function renderPreparedPacketContents(items) {
  if (!items?.length) return "<p>No prepared request items were returned.</p>";
  return items.map((item, index) => {
    const supporting = supportingAttachmentFiles(item);
    const period = item.service_period_label
      ? ` · ${item.service_period_label}${item.service_start_time || item.service_end_time ? ` ${item.service_start_time || ""}-${item.service_end_time || ""}` : ""}`
      : "";
    const contents = [
      `<li><span>Generated requerimento PDF</span><strong>${escapeHtml(pathBasename(item.pdf))}</strong></li>`,
      ...supporting.map((file) => `<li><span>Supporting attachment</span><strong>${escapeHtml(pathBasename(file))}</strong></li>`),
    ].join("");
    return `
      <div class="packet-content-item">
        <div class="packet-content-heading">
          <strong>${index + 1}. ${escapeHtml(item.case_number || "case pending")} · ${escapeHtml(item.service_date || "date pending")}${escapeHtml(period)}</strong>
          <span class="status-chip info">${supporting.length} supporting</span>
        </div>
        <ol>${contents}</ol>
      </div>
    `;
  }).join("");
}

function draftRecordPayloadFromForm() {
  const supersedes = $("#record_supersedes").value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const payloadPath = $("#record_payload").value.trim();
  return {
    payload: payloadPath,
    draft_id: $("#record_draft_id").value.trim(),
    message_id: $("#record_message_id").value.trim(),
    thread_id: $("#record_thread_id").value.trim(),
    status: $("#record_status").value,
    sent_date: $("#record_sent_date").value,
    notes: $("#record_notes").value.trim(),
    supersedes,
    ...currentPreparedReviewFields(payloadPath),
  };
}

async function finishDraftRecord(data) {
  setStatus(data.status, `Recorded Gmail draft ${data.draft_id}.`);
  const superseded = data.superseded_drafts?.length ? ` Superseded: ${data.superseded_drafts.join(", ")}.` : "";
  const blockerCount = Number(data.recorded_duplicate_count || 0);
  const duplicateKeys = (data.duplicate_keys || [])
    .map((item) => [item.case_number, item.service_date, item.service_period_label].filter(Boolean).join(" · "))
    .filter(Boolean);
  const blockerText = blockerCount
    ? ` The duplicate index now protects ${blockerCount} duplicate blocker${blockerCount === 1 ? "" : "s"}${duplicateKeys.length ? `: ${duplicateKeys.join("; ")}` : ""}.`
    : " The duplicate index now protects this case/date.";
  showAlert(`Draft recorded locally.${blockerText}${superseded}`, "recorded");
  await loadReference();
  return data;
}

async function recordPreparedDraftFromForm() {
  const payloadPath = $("#record_payload").value.trim();
  const payload = {
    ...draftRecordPayloadFromForm(),
    gmail_handoff_reviewed: true,
    ...currentPreparedReviewFields(payloadPath),
  };
  const data = await requestJson("/api/drafts/record", {
    method: "POST",
    body: JSON.stringify(removeEmpty(payload)),
  });
  return finishDraftRecord(data);
}

async function recordDraft() {
  const payload = draftRecordPayloadFromForm();
  const data = await requestJson("/api/drafts/status", {
    method: "POST",
    body: JSON.stringify(removeEmpty(payload)),
  });
  return finishDraftRecord(data);
}

function resetReview({ closeDrawer = true } = {}) {
  state.currentIntake = null;
  clearPreparedArtifacts("review reset");
  state.draftLifecycle = null;
  state.googlePhotosPicker = null;
  $("#intake-form").reset();
  $("#notification-upload-form").reset();
  $("#photo-upload-form").reset();
  $("#google-photos-upload-form").reset();
  $("#supporting-attachment-form").reset();
  renderSourceEvidence(null);
  renderAiRecovery(null);
  renderSupportingAttachmentList();
  renderGooglePhotosPickerResult(null);
  renderBatchQueue();
  renderDraftLifecycle(null);
  renderNextSafeAction(null);
  $("#correction_reason").value = "";
  $("#numbered-answers").value = "";
  $("#record_supersedes").value = "";
  $("#record_sent_date").value = "";
  $("#record_notes").value = "";
  $("#record-form").reset();
  $("#draft-text").textContent = "The Portuguese draft will appear here before the PDF is created.";
  $("#recipient-summary").textContent = "Recipient appears here after review.";
  $("#interpretation-review-home-result").className = "result-card empty-state";
  $("#interpretation-review-home-result").textContent = "Upload a notification PDF or screenshot to recover the case details, or start a blank request.";
  showAlert("", "");
  showQuestions({});
  setStatus("idle", "Upload a notification or start a blank request to begin.");
  if (closeDrawer) closeReviewDrawer();
}

function resetWorkspace() {
  state.batchIntakes = [];
  state.batchSelectedIndex = null;
  state.batchPreflight = null;
  const packetMode = $("#batch-packet-mode");
  if (packetMode) packetMode.checked = false;
  try {
    resetReview({ closeDrawer: false });
  } catch (error) {
    console.error("Workspace review reset failed", error);
  }
  state.batchIntakes = [];
  state.batchSelectedIndex = null;
  state.batchPreflight = null;
  if (packetMode) packetMode.checked = false;
  renderBatchQueue();
  renderBatchPreflight();
  showPanel("new-job");
  setStatus("idle", "Workspace reset. Upload a notification or start a blank request to begin.");
  showAlert("Workspace reset. Batch queue cleared.", "recorded");
  closeReviewDrawer();
}

window.honorariosResetWorkspace = (event) => {
  event?.preventDefault?.();
  event?.stopPropagation?.();
  resetWorkspace();
};

function normalizePanelName(panelName) {
  const normalized = String(panelName || "").replace(/^#/, "").trim();
  if (normalized === "profile") return "profiles";
  return ["new-job", "profiles", "references", "history"].includes(normalized) ? normalized : "new-job";
}

function syncPanelHash(panelName) {
  const targetHash = `#${panelName}`;
  if (window.location.hash === targetHash) return;
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${targetHash}`);
}

function showPanel(panelName, options = {}) {
  const panel = normalizePanelName(panelName);
  document.querySelectorAll(".nav-button[data-panel]").forEach((item) => {
    item.classList.toggle("active", item.dataset.panel === panel);
    item.classList.toggle("is-active", item.dataset.panel === panel);
  });
  ["new-job", "profiles", "references", "history"].forEach((panelId) => {
    $(`#panel-${panelId}`).classList.toggle("hidden", panelId !== panel);
  });
  if (options.updateHash !== false) {
    syncPanelHash(panel);
  }
}

function bindNavigation() {
  document.querySelectorAll(".nav-button[data-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      showPanel(button.dataset.panel);
    });
  });
}

function bindActions() {
  bindSourceDropZone();
  $("#intake-form").addEventListener("input", () => clearPreparedArtifacts("intake form changed"));
  $("#intake-form").addEventListener("change", () => clearPreparedArtifacts("intake form changed"));
  const resetControl = $("#reset-workspace");
  if (resetControl) {
    resetControl.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      resetWorkspace();
    });
  }
  document.addEventListener("click", (event) => {
    const clickTarget = event.target?.closest ? event.target : event.target?.parentElement;
    const resetButton = clickTarget?.closest("#reset-workspace");
    if (!resetButton) return;
    event.preventDefault();
    resetWorkspace();
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-next-action-target]");
    if (!button) return;
    const target = document.getElementById(button.dataset.nextActionTarget || "");
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    if (typeof target.focus === "function") target.focus({ preventScroll: true });
  });
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-diagnostic-command]");
    if (!button) return;
    try {
      await copyDiagnosticCommand(button.dataset.copyDiagnosticCommand || "");
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  [
    "correction_reason",
    "numbered-answers",
    "gmail-response-raw",
    "record_payload",
    "record_draft_id",
    "record_message_id",
    "record_thread_id",
    "gmail_handoff_reviewed",
  ].forEach((id) => {
    const input = document.getElementById(id);
    if (!input) return;
    input.addEventListener("input", () => syncActionGates());
    input.addEventListener("change", () => syncActionGates());
  });
  $("#refresh-reference").addEventListener("click", async () => {
    await loadReference();
    await loadAiStatus().catch(() => {});
    await loadGooglePhotosStatus().catch(() => {});
    await loadGmailStatus().catch(() => {});
    await loadBackupStatus().catch(() => {});
    await loadDiagnosticsStatus().catch(() => {});
  });
  $("#run-public-readiness").addEventListener("click", async () => {
    try {
      await runPublicReadiness();
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#build-public-candidate").addEventListener("click", async () => {
    try {
      await buildPublicCandidate();
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#refresh-diagnostics").addEventListener("click", async () => {
    try {
      await loadDiagnosticsStatus();
      showAlert("Local diagnostics refreshed.", "recorded");
    } catch (error) {
      renderDiagnosticsStatus({ status: "blocked", message: error.message, checks: [] });
      showAlert(error.message, "blocked");
    }
  });
  $("#export-local-backup").addEventListener("click", async () => {
    try {
      const data = await exportLocalBackup();
      showAlert(`Local backup exported to ${data.backup_file}.`, "recorded");
    } catch (error) {
      renderLocalBackupResult({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#copy-local-backup").addEventListener("click", async () => {
    try {
      await copyText(localBackupJsonText());
      showAlert("Copied local backup JSON.", "recorded");
    } catch (error) {
      renderLocalBackupResult({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#preview-local-backup-import").addEventListener("click", async () => {
    try {
      await previewLocalBackupImport();
      showAlert("Backup import preview is valid. No local files were changed.", "recorded");
    } catch (error) {
      state.localBackupPreview = null;
      renderLocalBackupResult({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#restore-local-backup").addEventListener("click", async () => {
    try {
      const data = await restoreLocalBackupImport();
      showAlert(`Backup restored locally. Pre-restore backup: ${data.pre_restore_backup_file}.`, "recorded");
    } catch (error) {
      renderLocalBackupResult({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#preview-legalpdf-import").addEventListener("click", async () => {
    try {
      await previewLegalPdfImport();
      showAlert("LegalPDF import preview is ready. No local files were changed.", "recorded");
    } catch (error) {
      state.legalPdfImportPreview = null;
      renderLegalPdfImportPreview({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#export-legalpdf-import-report").addEventListener("click", async () => {
    try {
      const data = await exportLegalPdfImportReport();
      showAlert(`LegalPDF preview report exported to ${data.preview_report_markdown_file}.`, "recorded");
    } catch (error) {
      renderLegalPdfImportPreview({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#build-legalpdf-integration-checklist").addEventListener("click", async () => {
    try {
      const data = await buildLegalPdfIntegrationChecklist();
      showAlert(`Integration checklist built with ${data.checklist.length} task${data.checklist.length === 1 ? "" : "s"}. No local files were changed.`, "recorded");
    } catch (error) {
      renderLegalPdfImportPreview({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#build-legalpdf-adapter-import-plan").addEventListener("click", async () => {
    try {
      const data = await buildLegalPdfAdapterImportPlan();
      const blockerText = data.blocking_count
        ? ` ${data.blocking_count} blocker${data.blocking_count === 1 ? "" : "s"} require review.`
        : " No blockers were detected.";
      showAlert(`Adapter import plan built.${blockerText} No local files were changed.`, "recorded");
    } catch (error) {
      renderLegalPdfImportPreview({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#apply-legalpdf-import-plan").addEventListener("click", async () => {
    try {
      maybeShowBackupReminder("applying a reviewed LegalPDF import plan");
      const data = await applyLegalPdfAdapterImportPlan();
      const profileCount = data.applied_profiles?.length || 0;
      const courtCount = data.applied_court_emails?.length || 0;
      showAlert(`Applied ${profileCount} profile change${profileCount === 1 ? "" : "s"} and ${courtCount} court email change${courtCount === 1 ? "" : "s"} locally. LegalPDF was not modified.`, "recorded");
    } catch (error) {
      renderLegalPdfImportPreview({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#refresh-legalpdf-apply-history").addEventListener("click", async () => {
    try {
      const data = await loadLegalPdfApplyHistory();
      showAlert(`Loaded ${data.report_count || 0} LegalPDF apply report${Number(data.report_count || 0) === 1 ? "" : "s"}.`, "recorded");
    } catch (error) {
      renderLegalPdfApplyHistory({ reports: [], status: "blocked", message: error.message });
      showAlert(error.message, "blocked");
    }
  });
  $("#legalpdf-apply-history-result").addEventListener("click", async (event) => {
    const applyRestoreButton = event.target.closest("[data-legalpdf-apply-restore-report-id]");
    const restoreButton = event.target.closest("[data-legalpdf-restore-report-id]");
    const button = event.target.closest("[data-legalpdf-report-id]");
    if (!button && !restoreButton && !applyRestoreButton) return;
    try {
      if (applyRestoreButton) {
        maybeShowBackupReminder("restoring a LegalPDF apply backup");
        const data = await applyLegalPdfRestore(applyRestoreButton.dataset.legalpdfApplyRestoreReportId);
        showAlert(`Restored local LegalPDF import changes for ${data.source_apply_report_id || "the selected apply report"}. LegalPDF Translate was not modified.`, "recorded");
        return;
      }
      if (restoreButton) {
        const data = await loadLegalPdfRestorePlan(restoreButton.dataset.legalpdfRestoreReportId);
        showAlert(`Loaded read-only restore plan for ${data.report?.report_id || "LegalPDF apply report"}.`, "recorded");
        return;
      }
      const data = await loadLegalPdfApplyDetail(button.dataset.legalpdfReportId);
      showAlert(`Loaded redacted compare detail for ${data.report?.report_id || "LegalPDF apply report"}.`, "recorded");
    } catch (error) {
      if (restoreButton || applyRestoreButton) {
        renderLegalPdfRestorePlan({ status: "blocked", message: error.message, restore_plan: { profiles: [], court_emails: [] } });
      } else {
        renderLegalPdfApplyDetail({ status: "blocked", message: error.message, comparison: { profiles: [], court_emails: [] } });
      }
      showAlert(error.message, "blocked");
    }
  });
  $("#add-personal-profile").addEventListener("click", async () => {
    try {
      const data = await requestJson("/api/profiles/new");
      openPersonalProfileDrawer(data.profile || {});
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#copy-legalpdf-personal-profiles").addEventListener("click", async () => {
    try {
      await previewLegalPdfPersonalProfiles();
      $("#legalpdf-personal-profile-import-card").classList.remove("hidden");
      openPersonalProfileDrawer(personalProfilesData().main_profile || {});
    } catch (error) {
      showPanel("profiles");
      $("#legalpdf-personal-profile-import-card").classList.remove("hidden");
      renderLegalPdfPersonalProfileImport({ status: "blocked", message: error.message, changes: [] });
      showAlert(error.message, "blocked");
    }
  });
  $("#personal-profile-close").addEventListener("click", closePersonalProfileDrawer);
  $("#pp_close_bottom").addEventListener("click", closePersonalProfileDrawer);
  $("#personal-profile-drawer-backdrop").addEventListener("click", (event) => {
    if (event.target?.id === "personal-profile-drawer-backdrop") closePersonalProfileDrawer();
  });
  $("#personal-profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveCurrentPersonalProfile();
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#pp_set_main").addEventListener("click", async () => {
    try {
      await setMainPersonalProfile();
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#pp_delete").addEventListener("click", async () => {
    try {
      await deletePersonalProfile();
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#pp_add_distance").addEventListener("click", () => {
    try {
      addPersonalDistance();
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#pp_distance_list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-delete-profile-distance]");
    if (!button || !state.currentPersonalProfile) return;
    const city = button.dataset.deleteProfileDistance || "";
    delete state.currentPersonalProfile.travel_distances_by_city?.[city];
    syncPersonalDistanceJson();
    renderPersonalDistanceList();
  });
  $("#personal-profile-list").addEventListener("click", async (event) => {
    const editButton = event.target.closest("[data-edit-personal-profile]");
    const mainButton = event.target.closest("[data-main-personal-profile]");
    const deleteButton = event.target.closest("[data-delete-personal-profile]");
    try {
      if (editButton) {
        const profile = (personalProfilesData().profiles || []).find((item) => item.id === editButton.dataset.editPersonalProfile);
        openPersonalProfileDrawer(profile || {});
      } else if (mainButton) {
        await setMainPersonalProfile(mainButton.dataset.mainPersonalProfile);
      } else if (deleteButton) {
        await deletePersonalProfile(deleteButton.dataset.deletePersonalProfile);
      }
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#preview-legalpdf-personal-profiles").addEventListener("click", async () => {
    try {
      await previewLegalPdfPersonalProfiles();
    } catch (error) {
      renderLegalPdfPersonalProfileImport({ status: "blocked", message: error.message, changes: [] });
      showAlert(error.message, "blocked");
    }
  });
  $("#apply-legalpdf-personal-profiles").addEventListener("click", async () => {
    try {
      await applyLegalPdfPersonalProfiles();
    } catch (error) {
      renderLegalPdfPersonalProfileImport({ status: "blocked", message: error.message, changes: [] });
      showAlert(error.message, "blocked");
    }
  });
  $("#service-profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveServiceProfileReference();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#preview-profile-change").addEventListener("click", async () => {
    try {
      await previewServiceProfileReference();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#profile-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-edit-profile]");
    if (!button) return;
    fillServiceProfileReferenceForm(button.dataset.editProfile);
  });
  $("#source-evidence").addEventListener("click", (event) => {
    const button = event.target.closest("[data-use-profile-proposal]");
    if (!button) return;
    try {
      fillServiceProfileProposalForm(state.lastProfileProposal);
      showPanel("references");
      showAlert("Proposed profile loaded into the guarded profile editor. Preview it before saving.", "recorded");
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#profile-change-list").addEventListener("click", async (event) => {
    const previewButton = event.target.closest("[data-preview-profile-rollback]");
    const restoreButton = event.target.closest("[data-restore-profile-rollback]");
    if (!previewButton && !restoreButton) return;
    try {
      const index = Number((previewButton || restoreButton).dataset.previewProfileRollback ?? (previewButton || restoreButton).dataset.restoreProfileRollback);
      if (previewButton) {
        await previewProfileRollback(index);
      } else {
        await restoreProfileRollback(index);
      }
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#destination-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveDestinationReference();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#preview-destination-change").addEventListener("click", async () => {
    try {
      await previewDestinationReference();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#court-email-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveCourtEmailReference();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#preview-court-email-change").addEventListener("click", async () => {
    try {
      await previewCourtEmailReference();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#destination-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-edit-destination]");
    if (!button) return;
    fillDestinationReferenceForm(Number(button.dataset.editDestination));
  });
  $("#court-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-edit-court]");
    if (!button) return;
    fillCourtEmailReferenceForm(Number(button.dataset.editCourt));
  });
  $("#history-status-filters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-status-filter]");
    if (!button) return;
    const filter = button.dataset.historyStatusFilter || "all";
    if (!HISTORY_STATUS_FILTERS.includes(filter)) return;
    state.historyStatusFilter = filter;
    renderReference();
  });
  const handleHistoryDraftAction = async (event) => {
    const verifyButton = event.target.closest("[data-history-verify-draft]");
    const markSentButton = event.target.closest("[data-history-mark-sent]");
    const button = verifyButton || markSentButton;
    if (!button) return;
    event.preventDefault();
    try {
      button.disabled = true;
      const source = button.dataset.historySource || "draft_log";
      if (verifyButton) {
        await verifyHistoryDraft(button.dataset.historyVerifyDraft, source);
      } else {
        await markHistoryDraftSent(button.dataset.historyMarkSent, source);
      }
    } catch (error) {
      renderHistoryDraftActionResult({ status: "blocked", message: error.message }, "blocked");
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    } finally {
      button.disabled = false;
    }
  };
  $("#duplicate-list").addEventListener("click", handleHistoryDraftAction);
  $("#draft-log-list").addEventListener("click", handleHistoryDraftAction);
  $("#notification-upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await uploadSource("notification_pdf");
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  $("#photo-upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await uploadSource("photo");
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  $("#google-photos-upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await uploadSource("google_photos");
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  $("#supporting-attachment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await uploadSupportingAttachments($("#supporting-attachment-file").files);
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  $("#google-photos-oauth-start").addEventListener("click", async () => {
    try {
      await startGooglePhotosOAuth();
      setStatus("ready", "Google Photos OAuth flow opened in a separate tab.");
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      renderGooglePhotosPickerResult({ status: "blocked", message: error.message }, "blocked");
    }
  });
  $("#gmail-redirect-uri").addEventListener("input", () => {
    $("#gmail-redirect-uri").dataset.userEdited = "true";
  });
  $("#save-gmail-config").addEventListener("click", async () => {
    try {
      await saveGmailConfig();
    setStatus("ready", "Gmail OAuth config saved locally. Manual Draft Handoff remains ready. Connect Gmail Draft API when you want optional direct drafting.");
    } catch (error) {
      const resultBox = $("#gmail-config-result");
      if (resultBox) {
        resultBox.className = "result-card compact-result blocked";
        resultBox.textContent = error.message;
      }
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#connect-gmail-oauth").addEventListener("click", async () => {
    try {
      await startGmailOAuth();
    } catch (error) {
      renderGmailApiResult({ status: "blocked", message: error.message }, "blocked");
      showAlert(error.message, "blocked");
    }
  });
  $("#create-gmail-api-draft").addEventListener("click", async () => {
    try {
      await createGmailApiDraft();
    } catch (error) {
      renderGmailApiResult({ status: "blocked", message: error.message }, "blocked");
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#verify-gmail-draft").addEventListener("click", async () => {
    try {
      await verifyGmailDraft();
    } catch (error) {
      renderGmailVerifyResult({ status: "blocked", message: error.message }, "blocked");
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#gmail-api-result").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-verify-created-draft]");
    if (!button) return;
    try {
      await verifyCreatedGmailDraft();
    } catch (error) {
      renderGmailVerifyResult({ status: "blocked", message: error.message }, "blocked");
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#google-photos-picker-start").addEventListener("click", async () => {
    try {
      await createGooglePhotosPickerSession();
      setStatus("ready", "Google Photos Picker opened. Choose one photo, then import it for review.");
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      renderGooglePhotosPickerResult({ status: "blocked", message: error.message }, "blocked");
    }
  });
  $("#google-photos-picker-check").addEventListener("click", async () => {
    try {
      const data = await checkGooglePhotosPickerSelection();
      setStatus(data.selected_count ? "ready" : "idle", data.selected_count ? "Google Photos selection is ready to import." : "No Google Photos selection is available yet.");
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      renderGooglePhotosPickerResult({ status: "blocked", message: error.message }, "blocked");
    }
  });
  $("#google-photos-picker-import").addEventListener("click", async () => {
    try {
      await importGooglePhotosPickerSelection();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
      renderGooglePhotosPickerResult({ status: "blocked", message: error.message }, "blocked");
    }
  });
  $("#build-profile").addEventListener("click", async () => {
    try {
      await buildIntakeFromProfile();
    } catch (error) {
      setStatus("error", error.message);
      showAlert(error.message, "error");
      updateHomeReviewCard({ status: "error", message: error.message });
    }
  });
  $("#review-intake").addEventListener("click", async () => {
    try {
      await reviewIntake();
    } catch (error) {
      setStatus("error", error.message);
      showAlert(error.message, "error");
      updateHomeReviewCard({ status: "error", message: error.message });
    }
  });
  $("#apply-numbered-answers").addEventListener("click", async () => {
    try {
      await applyNumberedAnswers();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#prepare-intake").addEventListener("click", async () => {
    try {
      await prepareIntake();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  $("#drawer-prepare-intake").addEventListener("click", async () => {
    try {
      await prepareIntake();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#add-current-to-batch").addEventListener("click", async () => {
    try {
      await addCurrentIntakeToBatch();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  $("#prepare-batch-intakes").addEventListener("click", async () => {
    try {
      await prepareBatchIntakes();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  $("#preflight-batch-intakes").addEventListener("click", async () => {
    try {
      await preflightBatchIntakes();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
      updateHomeReviewCard({ status: "blocked", message: error.message });
    }
  });
  $("#clear-batch-queue").addEventListener("click", () => {
    state.batchIntakes = [];
    state.batchSelectedIndex = null;
    state.batchPreflight = null;
    $("#batch-packet-mode").checked = false;
    renderBatchQueue();
    setStatus("idle", "Batch queue cleared.");
    showAlert("Batch queue cleared.", "recorded");
  });
  $("#batch-packet-mode").addEventListener("change", () => {
    state.batchPreflight = null;
    renderBatchPreflight();
    syncActionGates();
  });
  $("#batch-queue-list").addEventListener("click", (event) => {
    const inspectButton = event.target.closest("[data-inspect-batch-index]");
    if (inspectButton) {
      state.batchSelectedIndex = Number(inspectButton.dataset.inspectBatchIndex);
      renderBatchQueue();
      showAlert("Packet item inspector updated.", "recorded");
      return;
    }
    const moveButton = event.target.closest("[data-move-batch-index]");
    if (moveButton) {
      const index = Number(moveButton.dataset.moveBatchIndex);
      const direction = moveButton.dataset.moveDirection === "up" ? -1 : 1;
      if (moveBatchIntake(index, index + direction)) {
        showAlert("Batch order updated. Packet mode will use this order.", "recorded");
      }
      return;
    }
    const button = event.target.closest("[data-remove-batch-index]");
    if (!button) return;
    const removedIndex = Number(button.dataset.removeBatchIndex);
    state.batchIntakes.splice(removedIndex, 1);
    state.batchPreflight = null;
    if (state.batchSelectedIndex === removedIndex) {
      state.batchSelectedIndex = state.batchIntakes.length ? Math.min(removedIndex, state.batchIntakes.length - 1) : null;
    } else if (state.batchSelectedIndex !== null && state.batchSelectedIndex > removedIndex) {
      state.batchSelectedIndex -= 1;
    }
    renderBatchQueue();
    setStatus("idle", "Removed request from the batch queue.");
  });
  $("#batch-queue-list").addEventListener("dragstart", (event) => {
    const row = event.target.closest("[data-batch-index]");
    if (!row) return;
    event.dataTransfer.setData("text/plain", row.dataset.batchIndex);
    event.dataTransfer.effectAllowed = "move";
    row.classList.add("is-dragging");
  });
  $("#batch-queue-list").addEventListener("dragend", (event) => {
    const row = event.target.closest("[data-batch-index]");
    if (row) row.classList.remove("is-dragging");
  });
  $("#batch-queue-list").addEventListener("dragover", (event) => {
    if (event.target.closest("[data-batch-index]")) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    }
  });
  $("#batch-queue-list").addEventListener("drop", (event) => {
    const row = event.target.closest("[data-batch-index]");
    if (!row) return;
    event.preventDefault();
    const fromIndex = Number(event.dataTransfer.getData("text/plain"));
    const toIndex = Number(row.dataset.batchIndex);
    if (moveBatchIntake(fromIndex, toIndex)) {
      showAlert("Batch order updated. Packet mode will use this order.", "recorded");
    }
  });
  $("#prepare-results").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-packet-record]");
    if (!button) return;
    try {
      const packet = state.lastPrepared?.packet;
      if (!packet) throw new Error("Prepare a packet PDF before copying packet record values.");
      const mode = button.dataset.copyPacketRecord;
      const value = mode === "command"
        ? buildPacketRecordCommand(packet)
        : JSON.stringify(buildPacketRecordObject(packet), null, 2);
      await copyText(value);
      showAlert(`Copied packet record ${mode === "command" ? "command" : "JSON"}.`, "recorded");
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#check-active-drafts").addEventListener("click", async () => {
    try {
      const data = await activeCheck();
      setStatus(data.status, data.message);
      if (data.status === "blocked") {
        showAlert(data.message, "blocked");
      }
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#prepare-replacement-draft").addEventListener("click", async () => {
    try {
      await prepareIntake({ correctionMode: true });
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#copy-draft-args").addEventListener("click", async () => {
    try {
      const target = preparedRecordTarget();
      await copyText(JSON.stringify(target?.gmail_create_draft_args || {}, null, 2));
      showAlert("Copied Gmail draft args JSON.", "recorded");
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#build-manual-handoff").addEventListener("click", async () => {
    try {
      await buildManualHandoffPacket();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#copy-manual-handoff-prompt").addEventListener("click", async () => {
    try {
      if (!state.lastManualHandoff?.copyable_prompt) {
        throw new Error("Build the manual handoff packet before copying its prompt.");
      }
      await copyText(state.lastManualHandoff.copyable_prompt);
      showAlert("Copied manual handoff prompt.", "recorded");
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#parse-gmail-response").addEventListener("click", () => {
    try {
      const ids = applyParsedGmailDraftIds(parseGmailDraftIds($("#gmail-response-raw").value));
      const found = [
        ids.draft_id ? "draft_id" : "",
        ids.message_id ? "message_id" : "",
        ids.thread_id ? "thread_id" : "",
      ].filter(Boolean).join(", ");
      showAlert(`Parsed Gmail IDs: ${found}.`, "recorded");
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#autofill-record-from-prepared").addEventListener("click", () => {
    try {
      const target = autofillRecordFormFromPrepared();
      const label = target.packet_mode ? "packet" : "prepared";
      showAlert(`Record form autofilled from ${label} payload; pasted Gmail IDs were preserved.`, "recorded");
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#record-parsed-prepared-draft").addEventListener("click", async () => {
    try {
      const result = await recordFromParsedResponseAndPreparedPayload();
      showAlert(`Gmail draft response and prepared payload recorded locally for ${result.record.draft_id}.`, "recorded");
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#copy-record-values").addEventListener("click", async () => {
    try {
      const recordValues = {
        payload: $("#record_payload").value.trim(),
        draft_id: $("#record_draft_id").value.trim(),
        message_id: $("#record_message_id").value.trim(),
        thread_id: $("#record_thread_id").value.trim(),
        status: $("#record_status").value,
        sent_date: $("#record_sent_date").value,
        supersedes: $("#record_supersedes").value.split(",").map((item) => item.trim()).filter(Boolean),
        notes: $("#record_notes").value.trim(),
      };
      await copyText(JSON.stringify(removeEmpty(recordValues), null, 2));
      showAlert("Copied draft lifecycle record values.", "recorded");
    } catch (error) {
      showAlert(error.message, "blocked");
    }
  });
  $("#record-draft").addEventListener("click", async () => {
    try {
      await recordDraft();
    } catch (error) {
      setStatus("blocked", error.message);
      showAlert(error.message, "blocked");
    }
  });
  $("#interpretation-clear-review").addEventListener("click", resetReview);
  $("#interpretation-close-review").addEventListener("click", closeReviewDrawer);
  $("#interpretation-close-review-footer").addEventListener("click", closeReviewDrawer);
  $("#interpretation-review-drawer-backdrop").addEventListener("click", (event) => {
    if (event.target.id === "interpretation-review-drawer-backdrop") {
      closeReviewDrawer();
    }
  });
}

bindNavigation();
bindActions();
window.addEventListener("hashchange", () => showPanel(window.location.hash, { updateHash: false }));
showPanel(window.location.hash || "new-job", { updateHash: false });
renderBatchQueue();
loadReference().catch((error) => {
  setStatus("error", error.message);
  showAlert(error.message, "error");
  updateHomeReviewCard({ status: "error", message: error.message });
});
loadAiStatus().catch(() => {});
loadGooglePhotosStatus().catch(() => {});
loadGmailStatus().catch(() => {});
loadBackupStatus().catch(() => {});
loadDiagnosticsStatus().catch(() => {});
loadLegalPdfApplyHistory().catch(() => {});
