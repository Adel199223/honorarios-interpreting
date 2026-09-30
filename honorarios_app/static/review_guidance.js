// Pure review guidance shared by the browser and synthetic behavior checks.
// Rendering and action gates stay in app.js; these helpers perform no I/O.

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
    service_date_source: "yes, use the photo date",
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
