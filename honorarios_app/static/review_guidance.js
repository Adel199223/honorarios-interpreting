// Pure review guidance shared by the browser and synthetic behavior checks.
// Rendering and action gates stay in app.js. Helpers perform no direct I/O;
// the async guard accepts an injected request and checks its result's context.

const GUIDED_STEP_BY_STATE = {
  idle: 1,
  answer_questions: 3,
  set_aside_translation: 2,
  stop_duplicate_sent: 2,
  choose_correction_mode: 2,
  fix_blocker: 2,
  prepare_pdf: 4,
  prepare_batch: 4,
  review_gmail_draft_args: 5,
};

export function guidedStepForState(stateName = "idle") {
  return GUIDED_STEP_BY_STATE[String(stateName || "idle")] || 2;
}

export function isWorkflowResponseCurrent(capturedRevision, currentRevision, capturedPrepared = undefined, currentPrepared = undefined) {
  return capturedRevision === currentRevision
    && (capturedPrepared === undefined || capturedPrepared === currentPrepared);
}

export async function awaitWorkflowResponse(request, captured, readCurrent) {
  const isCurrent = () => {
    const current = readCurrent();
    return isWorkflowResponseCurrent(captured.revision, current.revision, captured.prepared, current.prepared);
  };
  try {
    const result = await request();
    return isCurrent() ? result : null;
  } catch (error) {
    if (!isCurrent()) return null;
    throw error;
  }
}

export function projectWorkflowGuidance({ status = "idle", hasPrepared = false, handoffReady = false, recorded = false, stale = false, preparing = false } = {}) {
  if (stale) {
    return {
      phase: "stale", status: "stale", actionState: "fix_blocker",
      headline: "Details changed; review the request again.",
      needed: "Review the changed details before preparing a new PDF or using a handoff.",
      safety: "Any earlier prepared files are no longer current. Draft actions stay blocked until you review and prepare again.",
    };
  }
  if (preparing) {
    return {
      phase: "preparing", status: "preparing", actionState: "prepare_pdf",
      headline: "Preparing the reviewed request.",
      needed: "Wait for preparation to finish, then inspect the PDF and draft payload.",
      safety: "Preparation is in progress. The draft handoff is not available yet.",
    };
  }
  if (hasPrepared && recorded) {
    return {
      phase: "recorded", status: "recorded", actionState: "review_gmail_draft_args",
      headline: "The draft IDs were recorded locally.",
      needed: "Review the draft in Gmail and send it manually when you are satisfied.",
      safety: "Local draft bookkeeping is complete. This app has not sent the email.",
    };
  }
  if (hasPrepared && handoffReady) {
    return {
      phase: "handoff_ready", status: "ready", actionState: "review_gmail_draft_args",
      headline: "The PDF and copy-ready manual handoff are ready.",
      needed: "Inspect the PDF, recipient and attachments, then use the exact handoff and record the returned draft IDs.",
      safety: "The local PDF and draft payload were created. Building this handoff did not contact Gmail or record a draft.",
    };
  }
  if (hasPrepared) {
    return {
      phase: "prepared", status: "prepared", actionState: "review_gmail_draft_args",
      headline: "The PDF and draft payload were prepared locally.",
      needed: "Inspect the PDF preview, recipient and attachments before the draft handoff.",
      safety: "Preparation created local files. It did not create a Gmail draft or record draft IDs.",
    };
  }
  return { phase: "review", status, actionState: "", headline: "", needed: "", safety: "No PDF, Gmail draft, or local record was created by this review." };
}

export function profileFallbackNotice(data = {}, intake = {}) {
  const decision = data.review_evidence?.auto_profile || data.source_evidence?.auto_profile || intake.auto_profile || {};
  if (decision.mode !== "auto_fallback") return null;
  const photoCourt = intake.photo_defaults_applied;
  const photoCourtApplied = photoCourt?.routing_status === "applied" && photoCourt.payment_entity === intake.payment_entity;
  return {
    confidence: decision.confidence || "low",
    profile: decision.profile_key || "No profile selected",
    reason: photoCourtApplied
      ? `No recurring service profile matched. Your saved photo-city default selected the court for ${photoCourt.photo_city}. You can edit an exception.`
      : decision.reason || "No confident service-profile match was found. Check the payment entity and recipient before preparing.",
    paymentEntity: intake.payment_entity || "Needs an answer",
    recipient: data.recipient || intake.recipient_email || "Needs an answer",
  };
}

export function reviewFactOrigin(field, value, data = {}, intake = {}) {
  if (!String(value || "").trim()) return { kind: "missing", label: "Needs an answer" };
  if (field === "service_date" && ["user_confirmed", "user_confirmed_exception", "document_text_user_confirmed", "photo_metadata_user_confirmed"].includes(intake.service_date_source)) {
    return { kind: "manual", label: "You confirmed this date" };
  }
  const photoDefault = intake.photo_defaults_applied?.[field];
  if (photoDefault && String(photoDefault).trim().toLowerCase() === String(value).trim().toLowerCase()) {
    const label = field === "service_date" ? "Your photo-date default · editable"
      : field === "service_place" ? "Your photo-city court venue default · editable"
      : "Your photo-city court default · editable";
    return { kind: "default", label };
  }
  const evidence = data.review_evidence || data.source_evidence || {};
  const fields = Array.isArray(evidence.field_evidence)
    ? evidence.field_evidence
    : Object.entries(evidence.field_evidence || {}).map(([key, entry]) => ({ field: key, ...entry }));
  const entry = fields.find(item => item.field === field && String(item.value || "").trim().toLowerCase() === String(value).trim().toLowerCase());
  if (entry?.status === "conflicts_with_metadata") return { kind: "conflict", label: "Date conflict · answer the question" };
  const source = String(entry?.source || "");
  if (source.startsWith("openai")) {
    return { kind: "ai", label: entry.confidence === "low" ? "AI suggestion · check source" : "AI-read · check source" };
  }
  if (["deterministic_text", "document_text", "visible_email", "document_text_and_photo_metadata"].includes(source)) {
    return { kind: "source", label: "From source text · check it" };
  }
  if (source === "user_confirmed") return { kind: "manual", label: "You confirmed this date" };
  if (source === "photo_default") return { kind: "default", label: "Your saved photo default · editable" };
  if (source === "service_profile") return { kind: "default", label: "Profile default · check it" };
  if (source === "known_destination") return { kind: "default", label: "Saved place/distance · check it" };
  if (["image_metadata", "visible_google_photos_metadata"].includes(source)) {
    return { kind: "metadata", label: "Capture date · needs confirmation" };
  }
  return { kind: "unknown", label: "Check this value" };
}

export function beginnerReviewFacts(data = {}, intake = {}) {
  const serviceDate = data.service_date || intake.service_date || "";
  const captureOrigin = reviewFactOrigin("photo_metadata_date", intake.photo_metadata_date, data, intake);
  const captureLabel = captureOrigin.kind === "ai"
    ? captureOrigin.label.startsWith("AI suggestion") ? "AI-suggested photo date · needs confirmation" : "AI-read photo date · needs confirmation"
    : "Photo date · needs confirmation";
  const values = [
    ["case_number", "Case number", data.case_number || intake.case_number],
    ["service_date", "Service date", serviceDate || intake.photo_metadata_date],
    ["payment_entity", "Payment entity", intake.payment_entity],
    ["service_place", "Service place", intake.service_place],
    ["recipient_email", "Recipient email", data.recipient || intake.recipient_email],
  ];
  return values.map(([field, label, value]) => ({
    field, label, value: value || "",
    origin: field === "service_date" && !serviceDate && intake.photo_metadata_date
      ? { kind: captureOrigin.kind === "ai" ? "ai" : "metadata", label: captureLabel }
      : reviewFactOrigin(field, value, data, intake),
  }));
}

export function retainCaptureDateOrigin(data = {}, previous = {}) {
  const intake = data.effective_intake || data.intake || data.candidate_intake || {};
  const priorIntake = previous.effective_intake || previous.intake || previous.candidate_intake || {};
  if (!intake.source_sha256 || intake.source_sha256 !== priorIntake.source_sha256 || !intake.photo_metadata_date || intake.photo_metadata_date !== priorIntake.photo_metadata_date) return data;
  const fields = data.review_evidence?.field_evidence;
  const priorFields = (previous.review_evidence || previous.source_evidence)?.field_evidence;
  if (!Array.isArray(fields) || !Array.isArray(priorFields)) return data;
  const original = priorFields.find(item => item.field === "photo_metadata_date"
    && item.value === intake.photo_metadata_date && item.confidence === "high"
    && ["image_metadata", "visible_google_photos_metadata"].includes(item.source));
  if (!original || !fields.some(item => item.field === "photo_metadata_date" && item.value === original.value)) return data;
  // Only keep the origin of the same immutable source/date. Current review,
  // conflicts and generation permissions always come from the new response.
  return { ...data, review_evidence: { ...data.review_evidence, field_evidence: fields.map(item =>
    item.field === "photo_metadata_date" && item.value === original.value ? { ...original } : item) } };
}

export function todayIsoDate() {
  const date = new Date();
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 10);
}

export function friendlyQuestionTitle(action) {
  const detail = String(action?.detail || "");
  const match = detail.match(/(\d+)\s+numbered question/i);
  const countText = match ? `${match[1]} question${match[1] === "1" ? "" : "s"}` : "the questions";
  return `Answer ${countText} before PDF creation`;
}

export function shortDateLabel(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return text;
  const date = new Date(`${text}T00:00:00`);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function humanList(items) {
  const clean = items.map((item) => String(item || "").trim()).filter(Boolean);
  if (!clean.length) return "";
  if (clean.length === 1) return clean[0];
  if (clean.length === 2) return `${clean[0]} and ${clean[1]}`;
  return `${clean.slice(0, -1).join(", ")}, and ${clean[clean.length - 1]}`;
}

export function questionNeedsServiceDate(questions) {
  return questions.some((question) => ["service_date", "service_date_source"].includes(String(question.field || "")));
}

export function questionFieldLabel(question) {
  const field = String(question?.field || "").trim();
  const labels = {
    addressee: "recipient",
    case_number: "case number",
    claim_transport: "transport decision",
    closing_city: "closing city",
    closing_date: "closing date",
    entities_differ: "whether payment and service entities differ",
    payment_entity: "payment entity",
    recipient_email: "recipient email",
    service_date: "service date",
    service_date_source: "service date confirmation",
    service_entity: "service entity",
    service_entity_type: "service entity type",
    service_place: "service place",
    transport: "transport decision",
    transport_destination: "transport destination",
    "transport.destination": "transport destination",
    destination_name: "transport destination",
    km_one_way: "one-way kilometers",
    "transport.km_one_way": "one-way kilometers",
  };
  if (labels[field]) return labels[field];
  const questionText = String(question?.question || "").toLowerCase();
  if (questionText.includes("transport destination")) return "transport destination";
  if (questionText.includes("kilometer") || questionText.includes("quilómetro")) return "one-way kilometers";
  if (questionText.includes("closing line")) return "closing city";
  const number = String(question?.number || "").trim();
  return number ? `question ${number}` : "missing information";
}

export function questionAnswerExample(question) {
  const number = String(question?.number || "").trim() || "1";
  const field = String(question?.field || "").trim();
  const examples = {
    addressee: "Tribunal Judicial de Beja",
    case_number: "398/24.5T8BJA",
    claim_transport: "yes",
    closing_city: "Beja",
    closing_date: todayIsoDate(),
    entities_differ: "no",
    payment_entity: "Tribunal Judicial de Beja",
    recipient_email: "court@example.test",
    service_date: "2026-05-08",
    service_date_source: "document",
    service_entity: "GNR Beringel",
    service_entity_type: "gnr",
    service_place: "Beringel",
    transport: "yes, 34 km",
    transport_destination: "Beja",
    "transport.destination": "Beja",
    destination_name: "Beja",
    km_one_way: "39",
    "transport.km_one_way": "39",
  };
  const questionText = String(question?.question || "").toLowerCase();
  let example = examples[field] || "";
  if (!example && questionText.includes("transport destination")) example = "Beja";
  if (!example && (questionText.includes("kilometer") || questionText.includes("quilómetro"))) example = "39";
  if (!example && questionText.includes("closing line")) example = "Beja";
  return `${number}. ${example || "short answer"}`;
}

export function beginnerFoundLabels(data, intake) {
  const labels = [];
  if (data.case_number || intake.case_number) labels.push("case number");
  if (data.service_date || intake.service_date) labels.push("service date");
  if (!data.service_date && !intake.service_date && intake.photo_metadata_date) {
    labels.push(`photo metadata date (${shortDateLabel(intake.photo_metadata_date)})`);
  }
  if (intake.service_place) labels.push("service place");
  if (data.recipient || intake.recipient_email) labels.push("recipient");
  if (intake.auto_profile?.profile_key || intake.service_profile_key) labels.push("service profile suggestion");
  return labels;
}

export function beginnerNeededLabels(questions) {
  const labels = [];
  questions.forEach((question) => {
    const label = questionFieldLabel(question);
    if (label && !labels.includes(label)) labels.push(label);
  });
  return labels;
}

function copySourceCase(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

export function mergeSourceReviewEvidence(review = {}, previous = {}) {
  const source = { ...copySourceCase(previous), ...copySourceCase(review.source_evidence) };
  const evidence = { ...source, ...copySourceCase(review.review_evidence) };
  // Review values and attention belong to the selected case and latest check.
  // The immutable uploaded file and its preview still belong to the source.
  ["filename", "kind", "source_kind", "sha256", "artifact_url", "metadata", "rendered_page_urls", "rendered_page_count"].forEach((field) => {
    if (Object.prototype.hasOwnProperty.call(source, field)) evidence[field] = source[field];
  });
  return evidence;
}

export function sourceCaseCandidatesFromUpload(data = {}) {
  const candidates = Array.isArray(data.case_candidates) ? data.case_candidates : [];
  if (candidates.length <= 1) return [];
  // Preserve unresolved rows as well as readable cases. The server's ordinary
  // review decides whether each one is ready; the browser never guesses a case.
  return candidates.map((candidate) => {
    const intake = copySourceCase(candidate.candidate_intake);
    const review = copySourceCase(candidate.review);
    return {
      candidate_intake: intake,
      review: { ...review, candidate_intake: intake,
        source: review.source || copySourceCase(data.source),
        source_evidence: mergeSourceReviewEvidence(review, data.source_evidence) },
      answers: "",
      needs_review: false,
    };
  });
}

export function sourceCaseReadiness(candidate = {}) {
  const review = candidate.review || {};
  const status = candidate.needs_review ? "needs_review" : String(review.status || "blocked");
  return { status, ready: claimMode(candidate.candidate_intake) !== "neither" && !candidate.needs_review && review.status === "ready"
    && Boolean(String(candidate.candidate_intake?.case_number || "").trim())
    && !(Array.isArray(review.questions) && review.questions.length)
    && review.next_safe_action?.blocked !== true };
}

export function claimMode(intake = {}) {
  const interpreting = intake.claim_interpreting !== false;
  const transport = intake.claim_transport !== false;
  return interpreting ? (transport ? "both" : "interpreting_only") : (transport ? "travel_only" : "neither");
}

export function claimModeLabel(intake = {}) {
  return { both: "Interpreting + travel", interpreting_only: "Interpreting only", travel_only: "Travel only", neither: "Choose a claim" }[claimMode(intake)];
}

export function intakeWithClaimMode(intake, mode) {
  if (!["both", "interpreting_only", "travel_only"].includes(mode)) throw new Error("Choose interpreting + travel, interpreting only, or travel only.");
  return { ...copySourceCase(intake), claim_interpreting: mode !== "travel_only", claim_transport: mode !== "interpreting_only" };
}

export function sharedSourceTravelEligibility(candidates = []) {
  if (candidates.length < 2) return { eligible: false, reason: "A shared trip needs more than one case from this source." };
  const fields = ["source_sha256", "service_date", "service_place"];
  for (const field of fields) {
    const values = candidates.map((candidate) => String(candidate.candidate_intake?.[field] || "").trim().replace(/\s+/g, " ").toLowerCase());
    if (!values[0] || values.some((value) => !value || value !== values[0])) {
      return { eligible: false, reason: "Shared trip paused: every case must have the same source, service date and physical venue. Correct the visit details, or choose Separate trips." };
    }
  }
  const profiles = candidates.map((candidate) => String(candidate.candidate_intake?.personal_profile_id || "").trim());
  const destinations = candidates.map((candidate) => String(candidate.candidate_intake?.transport?.destination || "").trim().replace(/\s+/g, " ").toLowerCase());
  const origins = candidates.map((candidate) => String(candidate.candidate_intake?.transport?.origin || "").trim().replace(/\s+/g, " ").toLowerCase());
  if (!profiles[0] || !destinations[0] || new Set(profiles).size > 1 || new Set(destinations).size > 1 || new Set(origins).size > 1) {
    return { eligible: false, reason: "Shared trip paused: personal profiles, travel origins or destinations differ or need review. Correct the visit details, or choose Separate trips." };
  }
  return { eligible: true, reason: "" };
}

export function sourceTravelGroupId(candidates = []) {
  const hashes = candidates.map((candidate) => String(candidate.candidate_intake?.source_sha256 || "").trim());
  return hashes.length > 1 && hashes[0] && hashes.every((hash) => hash === hashes[0]) ? `source-trip-${hashes[0]}` : "";
}

export function sourceCasesWithTravelChoice(candidates, mode, ownerIndex = 0, groupId = "") {
  const copied = copySourceCase(candidates);
  if (!["shared", "separate", "none"].includes(mode)) throw new Error("Choose one shared trip, separate trips, or no travel.");
  if (mode === "shared") {
    const eligibility = sharedSourceTravelEligibility(candidates);
    if (!eligibility.eligible) return { candidates: copied, blocked_reason: eligibility.reason };
    if ((ownerIndex !== null && (!Number.isInteger(ownerIndex) || !copied[ownerIndex])) || !groupId) throw new Error("Choose which case carries the shared trip.");
  }
  copied.forEach((candidate, index) => {
    const intake = candidate.candidate_intake;
    const before = JSON.stringify(intake);
    intake.claim_interpreting = intake.claim_interpreting !== false;
    intake.claim_transport = mode === "separate" || (mode === "shared" && index === ownerIndex);
    if (mode === "shared") intake.travel_group_id = groupId;
    else delete intake.travel_group_id;
    if (before !== JSON.stringify(intake)) candidate.needs_review = true;
  });
  return { candidates: copied, blocked_reason: "" };
}

export function sourceCasesMatchSharedTravelChoice(candidates, ownerIndex, groupId) {
  return Boolean(groupId) && sharedSourceTravelEligibility(candidates).eligible
    && (ownerIndex === null || (Number.isInteger(ownerIndex) && Boolean(candidates[ownerIndex])))
    && candidates.every((candidate, index) => candidate.candidate_intake?.travel_group_id === groupId
      && candidate.candidate_intake?.claim_transport === (index === ownerIndex));
}

export async function reviewSourceCaseCandidates(candidates, requestReview, isCurrent = () => true) {
  const reviewed = [];
  for (const candidate of candidates) {
    if (!isCurrent()) return null;
    const intake = copySourceCase(candidate.candidate_intake);
    let result;
    try {
      result = await requestReview(intake);
    } catch (error) {
      if (!isCurrent()) return null;
      throw error;
    }
    if (!isCurrent()) return null;
    let review = retainCaptureDateOrigin({ ...result,
      source: result.source || candidate.review?.source }, candidate.review);
    review = { ...review, source_evidence: mergeSourceReviewEvidence(review, candidate.review?.source_evidence) };
    reviewed.push({ ...copySourceCase(candidate),
      candidate_intake: copySourceCase(review.effective_intake || review.intake || intake),
      review, needs_review: false });
  }
  return reviewed;
}

export function browserRequestIdentityKey(intake = {}) {
  const caseNumber = String(intake.case_number || "").replace(/\s+/g, "").toUpperCase().replace(/^0+(?=\d)/, "");
  return [caseNumber, String(intake.service_date || "").trim(),
    String(intake.service_period_label || "").trim().replace(/\s+/g, " ").toLowerCase()].join("|");
}

export function preparedFirstRequestReview(prepared = {}, reviews = []) {
  return preparedRequestReview(prepared, reviews, 0);
}

export function preparedRequestReview(prepared = {}, reviews = [], index = 0) {
  const first = prepared?.items?.[index];
  if (!first) return null;
  // The prepared manifest is the snapshot used to create these PDFs. A current
  // source selection can belong to another request and must not supply facts.
  const intake = copySourceCase(prepared.prepared_review_material?.effective_intakes?.[index]
    || first.effective_intake || first.intake || {
      case_number: first.case_number || "", service_date: first.service_date || "",
      payment_entity: first.payment_entity || "", service_place: first.service_place || "",
      recipient_email: first.recipient || "",
      claim_interpreting: first.claim_interpreting !== false, claim_transport: first.claim_transport !== false,
    });
  const matched = reviews.find((review) => {
    const candidate = review?.effective_intake || review?.intake || review?.candidate_intake || {};
    return browserRequestIdentityKey(candidate) === browserRequestIdentityKey(intake)
      && String(candidate.source_sha256 || "") === String(intake.source_sha256 || "");
  }) || {};
  return { ...copySourceCase(matched), intake, effective_intake: intake,
    case_number: first.case_number || intake.case_number || "",
    service_date: first.service_date || intake.service_date || "",
    recipient: first.recipient || intake.recipient_email || "", questions: [] };
}

export function duplicateSourceCaseIndices(candidates = []) {
  const firstByIdentity = new Map();
  const duplicates = new Set();
  candidates.forEach((candidate, index) => {
    const intake = candidate.candidate_intake || {};
    if (!String(intake.case_number || "").trim()) return;
    const identity = browserRequestIdentityKey(intake);
    if (firstByIdentity.has(identity)) {
      duplicates.add(firstByIdentity.get(identity));
      duplicates.add(index);
    } else {
      firstByIdentity.set(identity, index);
    }
  });
  return [...duplicates].sort((left, right) => left - right);
}
