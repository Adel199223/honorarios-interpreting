const state = {
  reference: null,
  currentIntake: null,
  batchIntakes: [],
  batchSelectedIndex: null,
  lastPrepared: null,
  aiStatus: null,
  googlePhotosStatus: null,
  googlePhotosPicker: null,
  draftLifecycle: null,
  lastProfileProposal: null,
  localBackupPreview: null,
  legalPdfImportPreview: null,
  backupStatus: null,
  historyStatusFilter: "all",
  currentNextSafeAction: null,
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
  if (["ready", "prepared", "recorded"].includes(normalized)) {
    pill.classList.add("ready");
  } else if (["needs_info", "duplicate", "active_draft", "set_aside", "blocked"].includes(normalized)) {
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
  if (["needs_info", "duplicate", "active_draft", "set_aside", "blocked", "superseded", "trashed", "not_found"].includes(status)) return "blocked";
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
  "prepare-replacement-draft": {
    states: ["choose_correction_mode"],
    reason: "Correction mode requires an active draft and a short correction reason.",
  },
  "copy-draft-args": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the PDF and Gmail draft payload before copying draft args.",
  },
  "autofill-record-from-prepared": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the PDF and Gmail draft payload before autofilling record values.",
  },
  "record-parsed-prepared-draft": {
    states: ["review_gmail_draft_args"],
    reason: "Prepare the payload, create the Gmail draft manually, then paste the Gmail response.",
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
    if (id === "prepare-batch-intakes") {
      enabled = state.batchIntakes.length > 0;
    }
    if (id === "prepare-replacement-draft") {
      enabled = enabled && Boolean($("#correction_reason")?.value.trim());
    }
    if (id === "apply-numbered-answers") {
      enabled = enabled && Boolean($("#numbered-answers")?.value.trim());
    }
    if (id === "record-parsed-prepared-draft") {
      enabled = enabled && Boolean($("#gmail-response-raw")?.value.trim());
    }
    if (id === "record-draft") {
      enabled = enabled
        && Boolean($("#record_payload")?.value.trim())
        && Boolean($("#record_draft_id")?.value.trim())
        && Boolean($("#record_message_id")?.value.trim());
    }
    setActionGate(id, enabled, enabled ? actionDetail : gate.reason, actionState);
  });
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
  };
  Object.entries(values).forEach(([id, value]) => {
    const input = $(`#${id}`);
    if (input && value !== undefined && value !== null && value !== "") {
      input.value = value;
    }
  });
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
  ].forEach((key) => {
    if (payload[key]) intake[key] = payload[key];
  });
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
      ? `<div class="button-row compact-button-row"><button type="button" class="mini-button" data-next-action-target="${escapeHtml(action.button_id)}">Go to this step</button></div>`
      : "";
    body.className = "next-safe-action-body";
    body.innerHTML = `
      <strong>${escapeHtml(action.title || "Next safe action")}</strong>
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

function pathBasename(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.split(/[\\/]/).filter(Boolean).pop() || text;
}

function normalizeAttachmentList(value) {
  if (!value) return [];
  const values = Array.isArray(value) ? value : [value];
  return values.map((item) => String(item || "").trim()).filter(Boolean);
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
  const ids = applyParsedGmailDraftIds(parseGmailDraftIds($("#gmail-response-raw").value));
  const target = autofillRecordFormFromPrepared();
  if (!ids.draft_id || !ids.message_id) {
    throw new Error("Parsed Gmail response must include draft_id and message_id before recording locally.");
  }
  const data = await recordDraft();
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
  syncActionGates();
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

function renderSourceEvidence(data) {
  const box = $("#source-evidence");
  const body = $("#source-evidence-body");
  if (!data?.source) {
    box.className = "result-card hidden";
    body.innerHTML = "";
    return;
  }
  const evidence = data.source_evidence || {};
  const source = data.source;
  const metadata = source.metadata || {};
  const warnings = evidence.warnings || metadata.warnings || [];
  const profileDecision = evidence.auto_profile || data.candidate_intake?.auto_profile || {};
  const profileProposal = evidence.profile_proposal || data.profile_proposal || {};
  const profileSummary = profileDecision.profile_key
    ? `${profileDecision.mode || "auto"}: ${profileDecision.profile_key}${profileDecision.suggested_profile_key && profileDecision.suggested_profile_key !== profileDecision.profile_key ? ` (suggested ${profileDecision.suggested_profile_key})` : ""}`
    : "not decided";
  const fieldEvidence = renderFieldEvidence(evidence.field_evidence || []);
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
  const preview = source.source_kind === "photo"
    ? `<img class="source-preview-image" src="${escapeHtml(source.artifact_url)}" alt="Uploaded source preview">`
    : renderedPageUrls.length
      ? `<div class="rendered-page-strip">
          <strong>Rendered PDF pages</strong>
          ${renderedPageUrls.map((url, index) => `<img class="source-preview-image rendered-page-image" src="${escapeHtml(url)}" alt="Rendered PDF page ${index + 1}">`).join("")}
          <a class="source-preview-link" href="${escapeHtml(source.artifact_url)}" target="_blank" rel="noreferrer">Open original PDF source</a>
        </div>`
      : `<a class="source-preview-link" href="${escapeHtml(source.artifact_url)}" target="_blank" rel="noreferrer">Open uploaded PDF source</a>`;
  body.innerHTML = `
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
  const warnings = aiRecovery.warnings || [];
  const indicators = aiRecovery.translation_indicators || [];
  const rawText = aiRecovery.raw_visible_text || "";
  chip.textContent = status.replaceAll("_", " ");
  chip.className = `status-chip ${status === "ok" ? "ready" : status === "failed" ? "error" : "info"}`;
  body.innerHTML = `
    <div class="source-evidence-list ai-recovery-list">
      <div><span>Provider</span><code>${escapeHtml(aiRecovery.provider || "openai")}</code></div>
      <div><span>Model</span><code>${escapeHtml(aiRecovery.model || "")}</code></div>
      <div><span>Attempted</span><strong>${aiRecovery.attempted ? "yes" : "no"}</strong></div>
      <div><span>Reason</span><code>${escapeHtml(aiRecovery.reason || "")}</code></div>
      <div><span>Fields found</span><code>${escapeHtml(Object.keys(fields).join(", ") || "none")}</code></div>
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

async function uploadSource(sourceKind) {
  const fileInput = sourceKind === "notification_pdf"
    ? $("#notification-file")
    : sourceKind === "google_photos"
      ? $("#google-photos-file")
      : $("#photo-file");
  const file = fileInput.files?.[0];
  if (!file) {
    if (sourceKind === "notification_pdf") throw new Error("Choose a PDF first.");
    if (sourceKind === "google_photos") throw new Error("Choose a Google Photos image first.");
    throw new Error("Choose a photo or screenshot first.");
  }
  const googlePhotosMetadata = sourceKind === "google_photos" ? $("#google-photos-metadata").value.trim() : "";
  const visibleText = [$("#source_text").value.trim(), googlePhotosMetadata].filter(Boolean).join("\n\n");
  const form = new FormData();
  form.append("file", file);
  form.append("source_kind", sourceKind === "google_photos" ? "photo" : sourceKind);
  form.append("profile", $("#profile").value || "");
  form.append("visible_text", visibleText);
  if (googlePhotosMetadata) {
    form.append("visible_metadata_text", googlePhotosMetadata);
  }
  form.append("ai_recovery", $("#ai_recovery_mode").value || "auto");

  const response = await fetch("/api/sources/upload", {
    method: "POST",
    body: form,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || data.message || `Upload failed: ${response.status}`);
  }
  state.currentIntake = data.candidate_intake;
  state.lastProfileProposal = data.profile_proposal || null;
  fillFormFromIntake(state.currentIntake);
  renderSourceEvidence(data);
  renderAiRecovery(data.ai_recovery);
  applyReview(data.review);
  return data;
}

async function loadReference() {
  state.reference = await requestJson("/api/reference");
  state.aiStatus = state.reference?.ai || null;
  state.backupStatus = state.reference?.backup || null;
  renderReference();
  renderAiStatus(state.aiStatus);
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
  const ready = Boolean(data?.public_ready);
  chip.textContent = ready ? "ready" : "blocked";
  chip.className = `status-chip ${ready ? "ready" : "blocked"}`;
  const blockedPaths = (data?.blocked_paths || []).slice(0, 8);
  const metadataBlockers = (data?.metadata_blockers || []).slice(0, 8);
  const findings = (data?.content_findings || []).slice(0, 8);
  const gitBlockers = data?.git_blockers || [];
  body.className = `result-card ${ready ? "ready" : "blocked"}`;
  body.innerHTML = `
    <div class="result-header">
      <div>
        <strong>${escapeHtml(data?.message || "Run the privacy gate before publishing.")}</strong>
        <p>${escapeHtml(data?.blocker_count ?? 0)} blocker${Number(data?.blocker_count || 0) === 1 ? "" : "s"} found.</p>
      </div>
      <span class="status-chip ${ready ? "ready" : "blocked"}">${ready ? "ready" : "blocked"}</span>
    </div>
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
  const data = await requestJson("/api/backup/import", {
    method: "POST",
    body: JSON.stringify({ backup_json: localBackupJsonText(), confirm_restore: true }),
  });
  state.localBackupPreview = null;
  $("#confirm-local-backup-restore").checked = false;
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
  body.className = `result-card ${chipKind}`;
  body.innerHTML = `
    <div class="result-header">
      <div>
        <strong>${escapeHtml(data?.message || "No LegalPDF integration preview has run yet.")}</strong>
        <p>No local files were changed. This wizard is preview-only and cannot create or send Gmail messages.</p>
      </div>
      <span class="status-chip ${chipKind}">${escapeHtml(status.replaceAll("_", " "))}</span>
    </div>
    ${datasets}
    ${markdownFile}
    ${jsonFile}
    ${countRows}
    ${profileSummary}
    <h4>Profile mappings</h4>
    <div class="data-list">${renderImportDiffRows(data?.profile_mappings || [], "Profiles")}</div>
    ${courtSummary}
    <h4>Court-email differences</h4>
    <div class="data-list">${renderImportDiffRows(data?.court_email_differences || [], "Court emails")}</div>
    ${checklistRows}
    ${adapterPlanRows}
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

function renderReference() {
  const profiles = state.reference?.service_profiles || {};
  const profileSelect = $("#profile");
  const duplicateRecords = filterHistoryRecords(state.reference?.duplicates || [], "sent").slice().reverse();
  const draftLogRecords = filterHistoryRecords(state.reference?.draft_log || [], "").slice().reverse();
  profileSelect.innerHTML = `<option value="">Auto-detect profile - recommended for uploads</option>` + Object.entries(profiles)
    .map(([key, value]) => `<option value="${escapeHtml(key)}">${escapeHtml(key)} - ${escapeHtml(value.description || "")}</option>`)
    .join("");

  $("#profile-list").innerHTML = Object.entries(profiles).map(([key, value]) => (
    `<div class="data-item">
      <strong>${escapeHtml(key)}</strong>
      <span>${escapeHtml(value.description || "")}</span>
      <button type="button" class="mini-button" data-edit-profile="${escapeHtml(key)}">Edit guarded profile</button>
    </div>`
  )).join("");

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

  $("#duplicate-list").innerHTML = duplicateRecords.length ? duplicateRecords.map((item) => (
    `<div class="data-item"><strong>${escapeHtml(item.case_number)} · ${escapeHtml(item.service_date)}</strong><span class="status-chip ${statusChipClass(item.status || "sent")}">${escapeHtml(item.status || "sent")}</span><code>${escapeHtml(item.draft_id || item.pdf || "")}</code></div>`
  )).join("") : `<div class="data-item empty-history-item">No duplicate records for the selected history filter.</div>`;

  $("#draft-log-list").innerHTML = draftLogRecords.length ? draftLogRecords.map((item) => (
    `<div class="data-item"><strong>${escapeHtml(item.case_number)} · ${escapeHtml(item.service_date)}</strong><span class="status-chip ${statusChipClass(item.status || "")}">${escapeHtml(item.status || "")}</span><code>${escapeHtml(item.draft_id || "")}</code></div>`
  )).join("") : `<div class="data-item empty-history-item">No Gmail draft records for the selected history filter.</div>`;

  $("#profile-change-list").innerHTML = (state.reference?.profile_change_log || [])
    .map((item, index) => ({ item, index }))
    .reverse()
    .map(({ item, index }) => (
    `<div class="data-item">
      <strong>${escapeHtml(item.profile_key || "")} · ${escapeHtml(item.action || "")}</strong>
      <span>${escapeHtml((item.changes || []).length)} change(s)</span>
      <code>${escapeHtml(item.reason || item.changed_at || "")}</code>
      <div class="button-row">
        <button type="button" class="mini-button" data-preview-profile-rollback="${index}">Preview rollback</button>
        <button type="button" class="mini-button" data-restore-profile-rollback="${index}">Restore previous profile</button>
      </div>
    </div>`
  )).join("");
}

async function saveDestinationReference() {
  maybeShowBackupReminder("saving destinations");
  const payload = {
    destination: $("#destination_name").value.trim(),
    km_one_way: $("#destination_km").value.trim(),
    institution_examples: parseReferenceLines($("#destination_examples").value),
    notes: $("#destination_notes").value.trim(),
  };
  const data = await requestJson("/api/reference/destinations", {
    method: "POST",
    body: JSON.stringify(removeEmpty(payload)),
  });
  setStatus("recorded", `Saved destination ${data.record.destination}.`);
  showAlert(`Saved destination ${data.record.destination}.`, "recorded");
  await loadReference();
}

async function saveCourtEmailReference() {
  maybeShowBackupReminder("saving court emails");
  const payload = {
    key: $("#court_key").value.trim(),
    name: $("#court_name").value.trim(),
    email: $("#court_email").value.trim(),
    payment_entity_aliases: parseReferenceLines($("#court_aliases").value),
    source: $("#court_source").value.trim(),
  };
  const data = await requestJson("/api/reference/court-emails", {
    method: "POST",
    body: JSON.stringify(removeEmpty(payload)),
  });
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
}

function fillCourtEmailReferenceForm(index) {
  const item = state.reference?.court_emails?.[index];
  if (!item) return;
  $("#court_key").value = item.key || "";
  $("#court_name").value = item.name || "";
  $("#court_email").value = item.email || "";
  $("#court_aliases").value = (item.payment_entity_aliases || []).join("\n");
  $("#court_source").value = item.source || "";
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

function collectProfilePayload() {
  return {
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
  const data = await requestJson("/api/intake/from-profile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.currentIntake = data.intake;
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
  renderBatchQueue();
  setStatus("ready", `${intake.case_number || "Request"} added to the batch queue.`);
  showAlert("Batch queue updated. Prepare the package when all related requests are queued.", "recorded");
}

async function prepareBatchIntakes() {
  if (!state.batchIntakes.length) {
    throw new Error("Add at least one ready request to the batch queue first.");
  }
  const packetMode = Boolean($("#batch-packet-mode")?.checked);
  const data = await requestJson("/api/prepare", {
    method: "POST",
    body: JSON.stringify({ intakes: state.batchIntakes, render_previews: true, packet_mode: packetMode }),
  });
  state.lastPrepared = data;
  const modeText = packetMode ? "as one packet PDF" : "as separate Gmail draft payloads";
  setStatus(data.status, `${state.batchIntakes.length} queued request${state.batchIntakes.length === 1 ? "" : "s"} prepared ${modeText}.`);
  showAlert("", "");
  renderPrepared(data);
  openReviewDrawer();
  await loadReference();
}

function applyReview(data) {
  setStatus(data.status, data.message);
  showQuestions(data);
  renderNextSafeAction(data.next_safe_action || null);
  const alertNeeded = ["duplicate", "active_draft", "set_aside", "error"].includes(data.status);
  showAlert(alertNeeded ? data.message : "", data.status === "error" ? "error" : "blocked");
  updateHomeReviewCard(data);
  $("#draft-text").textContent = data.draft_text || data.question_text || "The Portuguese draft will appear here before the PDF is created.";
  $("#recipient-summary").textContent = data.recipient ? `To: ${data.recipient}` : "Recipient appears here after review.";
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

  if (["ready", "duplicate", "active_draft", "set_aside"].includes(data.status)) {
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

async function recordDraft() {
  const supersedes = $("#record_supersedes").value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const payload = {
    payload: $("#record_payload").value.trim(),
    draft_id: $("#record_draft_id").value.trim(),
    message_id: $("#record_message_id").value.trim(),
    thread_id: $("#record_thread_id").value.trim(),
    status: $("#record_status").value,
    sent_date: $("#record_sent_date").value,
    notes: $("#record_notes").value.trim(),
    supersedes,
  };
  const data = await requestJson("/api/drafts/status", {
    method: "POST",
    body: JSON.stringify(removeEmpty(payload)),
  });
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

function resetReview() {
  state.currentIntake = null;
  state.lastPrepared = null;
  state.draftLifecycle = null;
  state.googlePhotosPicker = null;
  $("#intake-form").reset();
  $("#notification-upload-form").reset();
  $("#photo-upload-form").reset();
  $("#google-photos-upload-form").reset();
  $("#prepare-results").innerHTML = "";
  renderSourceEvidence(null);
  renderAiRecovery(null);
  renderGooglePhotosPickerResult(null);
  renderBatchQueue();
  renderDraftLifecycle(null);
  renderNextSafeAction(null);
  syncActionGates(null);
  $("#correction_reason").value = "";
  $("#numbered-answers").value = "";
  $("#record_supersedes").value = "";
  $("#record_sent_date").value = "";
  $("#record_notes").value = "";
  $("#pdf-preview-panel").classList.add("hidden");
  $("#pdf-preview").innerHTML = "";
  $("#record-form").reset();
  $("#draft-text").textContent = "The Portuguese draft will appear here before the PDF is created.";
  $("#recipient-summary").textContent = "Recipient appears here after review.";
  $("#interpretation-review-home-result").className = "result-card empty-state";
  $("#interpretation-review-home-result").textContent = "Upload a notification PDF or screenshot to recover the case details, or start a blank request.";
  showAlert("", "");
  showQuestions({});
  setStatus("idle", "Upload a notification or start a blank request to begin.");
  closeReviewDrawer();
}

function showPanel(panelName) {
  document.querySelectorAll(".nav-button[data-panel]").forEach((item) => {
    item.classList.toggle("active", item.dataset.panel === panelName);
    item.classList.toggle("is-active", item.dataset.panel === panelName);
  });
  ["new-job", "references", "history"].forEach((panel) => {
    $(`#panel-${panel}`).classList.toggle("hidden", panel !== panelName);
  });
}

function bindNavigation() {
  document.querySelectorAll(".nav-button[data-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      showPanel(button.dataset.panel);
    });
  });
}

function bindActions() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-next-action-target]");
    if (!button) return;
    const target = document.getElementById(button.dataset.nextActionTarget || "");
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    if (typeof target.focus === "function") target.focus({ preventScroll: true });
  });
  [
    "correction_reason",
    "numbered-answers",
    "gmail-response-raw",
    "record_payload",
    "record_draft_id",
    "record_message_id",
    "record_thread_id",
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
    await loadBackupStatus().catch(() => {});
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
  $("#court-email-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await saveCourtEmailReference();
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
  $("#clear-batch-queue").addEventListener("click", () => {
    state.batchIntakes = [];
    state.batchSelectedIndex = null;
    $("#batch-packet-mode").checked = false;
    renderBatchQueue();
    setStatus("idle", "Batch queue cleared.");
    showAlert("Batch queue cleared.", "recorded");
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
renderBatchQueue();
loadReference().catch((error) => {
  setStatus("error", error.message);
  showAlert(error.message, "error");
  updateHomeReviewCard({ status: "error", message: error.message });
});
loadAiStatus().catch(() => {});
loadGooglePhotosStatus().catch(() => {});
loadBackupStatus().catch(() => {});
