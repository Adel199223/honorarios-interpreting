#!/usr/bin/env node
import { pathToFileURL } from "node:url";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const DEFAULT_BROWSER_CLIENT = "%USERPROFILE%/example-path";
const DEFAULT_CASE_NUMBER = "999/26.0SMOKE";
const DEFAULT_SERVICE_DATE = "2026-05-04";
const DEFAULT_PROFILE = "example_interpreting";
const PROFILE_FALLBACKS = [
  "gnr_serpa_judicial",
  "gnr_ferreira_falentejo",
  "gnr_beringel_beja_mp",
  "pj_gnr_ferreira",
  "pj_gnr_beja",
  "beja_trabalho",
  "gnr_cuba",
  "court_mp_generic",
];

function parseArgs(argv) {
  const args = {
    baseUrl: "http://127.0.0.1:8766",
    browserClient: (typeof process !== "undefined" && process.env && process.env.BROWSER_USE_CLIENT_MJS) || DEFAULT_BROWSER_CLIENT,
    profile: DEFAULT_PROFILE,
    caseNumber: DEFAULT_CASE_NUMBER,
    serviceDate: DEFAULT_SERVICE_DATE,
    correctionReason: "synthetic correction smoke check",
    json: false,
    uploadPhoto: false,
    uploadPdf: false,
    uploadSupportingAttachment: false,
    answerQuestions: false,
    correctionMode: false,
    prepareReplacement: false,
    preparePacket: false,
    recordHelper: false,
    applyHistory: false,
    timeoutMs: 10000,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    const next = () => {
      index += 1;
      if (index >= argv.length) throw new Error(`Missing value for ${item}`);
      return argv[index];
    };
    if (item === "--base-url") args.baseUrl = next();
    else if (item === "--browser-client") args.browserClient = next();
    else if (item === "--profile") args.profile = next();
    else if (item === "--case-number") args.caseNumber = next();
    else if (item === "--service-date") args.serviceDate = next();
    else if (item === "--correction-reason") args.correctionReason = next();
    else if (item === "--timeout-ms") args.timeoutMs = Number(next());
    else if (item === "--json") args.json = true;
    else if (item === "--upload-photo") args.uploadPhoto = true;
    else if (item === "--upload-pdf") args.uploadPdf = true;
    else if (item === "--upload-supporting-attachment") args.uploadSupportingAttachment = true;
    else if (item === "--answer-questions") args.answerQuestions = true;
    else if (item === "--correction-mode") args.correctionMode = true;
    else if (item === "--prepare-replacement") args.prepareReplacement = true;
    else if (item === "--prepare-packet") args.preparePacket = true;
    else if (item === "--record-helper") args.recordHelper = true;
    else if (item === "--apply-history") args.applyHistory = true;
    else if (item === "--help" || item === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${item}`);
  }
  return args;
}

function normalizeBaseUrl(baseUrl) {
  const value = String(baseUrl || "").trim();
  if (!value) throw new Error("base URL is required");
  const withScheme = /^https?:\/\//i.test(value) ? value : `http://${value}`;
  return withScheme.replace(/\/+$/, "");
}

function check(name, passed, message, details = {}) {
  return {
    name,
    status: passed ? "ready" : "blocked",
    message,
    details,
  };
}

function report(baseUrl, checks) {
  const failureCount = checks.filter((item) => item.status !== "ready").length;
  return {
    status: failureCount === 0 ? "ready" : "blocked",
    base_url: baseUrl,
    checks,
    failure_count: failureCount,
    send_allowed: false,
  };
}

async function bodyIncludes(tab, text, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  const expected = String(text).toLocaleLowerCase();
  while (Date.now() < deadline) {
    last = await tab.playwright.locator("body").innerText({ timeoutMs: Math.min(1000, timeoutMs) });
    if (last.toLocaleLowerCase().includes(expected)) return { ok: true, body: last };
    await tab.playwright.waitForTimeout(100);
  }
  return { ok: false, body: last };
}

async function expectBodyText(tab, text, timeoutMs) {
  const found = await bodyIncludes(tab, text, timeoutMs);
  if (!found.ok) throw new Error(`Expected page to include ${JSON.stringify(text)}.`);
}

async function expectSelectorText(tab, selector, text, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  const deadline = Date.now() + timeoutMs;
  let last = "";
  const expected = String(text).toLocaleLowerCase();
  while (Date.now() < deadline) {
    last = await locator.innerText({ timeoutMs: Math.min(1000, timeoutMs) });
    if (last.toLocaleLowerCase().includes(expected)) return;
    await tab.playwright.waitForTimeout(100);
  }
  throw new Error(`Expected ${selector} to include ${JSON.stringify(text)}; got ${JSON.stringify(last)}.`);
}

async function expectAnyBodyText(tab, texts, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  const expected = texts.map((item) => String(item).toLocaleLowerCase());
  let last = "";
  while (Date.now() < deadline) {
    last = await tab.playwright.locator("body").innerText({ timeoutMs: Math.min(1000, timeoutMs) });
    const lowered = last.toLocaleLowerCase();
    if (expected.some((item) => lowered.includes(item))) return;
    await tab.playwright.waitForTimeout(100);
  }
  throw new Error(`Expected page to include one of ${JSON.stringify(texts)}.`);
}

async function uniqueLocator(tab, selector, timeoutMs) {
  const locator = tab.playwright.locator(selector);
  await locator.waitFor({ state: "visible", timeoutMs });
  const count = await locator.count();
  if (count !== 1) throw new Error(`Expected ${selector} to match exactly one visible element; got ${count}.`);
  return locator;
}

async function inputLocator(tab, selector, timeoutMs) {
  const locator = tab.playwright.locator(selector);
  await locator.waitFor({ state: "attached", timeoutMs });
  const count = await locator.count();
  if (count !== 1) throw new Error(`Expected ${selector} to match exactly one input element; got ${count}.`);
  return locator;
}

async function fill(tab, selector, value, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  await locator.fill(value, { timeoutMs });
}

async function click(tab, selector, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  try {
    await locator.scrollIntoViewIfNeeded({ timeoutMs });
  } catch (_error) {
    // Browser/IAB locator adapters may not expose this Playwright helper.
  }
  await locator.click({ timeoutMs });
}

async function setSyntheticInputFile(tab, selector, filePath, timeoutMs) {
  const locator = await inputLocator(tab, selector, timeoutMs);
  if (typeof locator.setInputFiles !== "function") {
    throw new Error("Browser/IAB file-input capability is unavailable: locator.setInputFiles is not exposed.");
  }
  try {
    await locator.setInputFiles(filePath, { timeout: timeoutMs });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Browser/IAB file-input capability failed for ${selector}: ${message}`);
  }
}

async function select(tab, selector, value, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  let lastError = null;
  for (const option of [value, ...PROFILE_FALLBACKS]) {
    try {
      await locator.selectOption(option, { timeoutMs });
      return option;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error(`Could not select ${selector}.`);
}

async function setChecked(tab, selector, value, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  await locator.setChecked(value, { timeoutMs });
}

async function expectValueContains(tab, selector, value, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  const actual = await locator.getAttribute("value", { timeoutMs });
  if (!String(actual || "").includes(value)) {
    throw new Error(`Expected ${selector} value to contain ${JSON.stringify(value)}; got ${JSON.stringify(actual)}.`);
  }
}

function portugueseDate(value) {
  const parts = String(value || "").split("-");
  if (parts.length !== 3) return String(value || "");
  return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

function pdfEscape(value) {
  return String(value || "").replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

function simplePdfBytes(lines) {
  const textOps = lines
    .map((line, index) => `BT /F1 12 Tf 72 ${720 - index * 20} Td (${pdfEscape(line)}) Tj ET`)
    .join("\n");
  const objects = [
    "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
    "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
    "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    `5 0 obj\n<< /Length ${textOps.length} >>\nstream\n${textOps}\nendstream\nendobj\n`,
  ];
  let output = "%PDF-1.4\n";
  const offsets = [0];
  for (const object of objects) {
    offsets.push(output.length);
    output += object;
  }
  const xrefOffset = output.length;
  output += `xref\n0 ${objects.length + 1}\n`;
  output += "0000000000 65535 f \n";
  for (const offset of offsets.slice(1)) {
    output += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  output += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(output, "utf8");
}

function createSyntheticUploadFixtures(args) {
  const directory = mkdtempSync(join(tmpdir(), "honorarios-iab-upload-"));
  const photoPath = join(directory, "synthetic-photo.png");
  const pdfPath = join(directory, "synthetic-notification.pdf");
  const supportingPath = join(directory, "synthetic-declaracao.pdf");
  const pngBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=";
  writeFileSync(photoPath, Buffer.from(pngBase64, "base64"));
  const [year, month, day] = String(args.serviceDate || DEFAULT_SERVICE_DATE).split("-");
  writeFileSync(pdfPath, simplePdfBytes([
    `NUIPC ${args.caseNumber || DEFAULT_CASE_NUMBER}`,
    `Data/Hora da diligência: ${day}/${month}/${year} 10:00`,
    "Local: Posto Territorial de Serpa",
    "Email: court@example.test",
  ]));
  writeFileSync(supportingPath, simplePdfBytes([
    "DECLARAÇÃO",
    `NUIPC ${args.caseNumber || DEFAULT_CASE_NUMBER}`,
    `Presença em ${day}/${month}/${year}`,
    "Documento comprovativo sintético para Browser/IAB smoke.",
  ]));
  return { directory, photoPath, pdfPath, supportingPath };
}

function cleanupSyntheticUploadFixtures(fixtures) {
  if (!fixtures?.directory) return;
  try {
    rmSync(fixtures.directory, { recursive: true, force: true });
  } catch (_error) {
    // Temporary fixture cleanup is best-effort only.
  }
}

async function countLocator(tab, selector) {
  return tab.playwright.locator(selector).count();
}

async function openReferencesPanel(tab, timeoutMs) {
  const referencesButton = tab.playwright.locator('button[data-panel="references"]');
  try {
    await referencesButton.waitFor({ state: "visible", timeoutMs: Math.min(1000, timeoutMs) });
  } catch (_error) {
    await click(tab, "details.sidebar-more > summary", timeoutMs);
    await referencesButton.waitFor({ state: "visible", timeoutMs });
  }
  await referencesButton.click({ timeoutMs });
}

async function runStep(checks, name, successMessage, action) {
  try {
    await action();
    checks.push(check(name, true, successMessage));
    return true;
  } catch (error) {
    checks.push(check(name, false, error instanceof Error ? error.message : String(error)));
    return false;
  }
}

export async function runBrowserIabSmoke(options = {}) {
  const args = { ...parseArgs([]), ...options };
  const baseUrl = normalizeBaseUrl(args.baseUrl);
  const checks = [];
  let uploadFixtures = null;
  let reviewDrawerOpen = false;
  const finish = () => {
    cleanupSyntheticUploadFixtures(uploadFixtures);
    return report(baseUrl, checks);
  };
  const closeReviewDrawerIfOpen = async () => {
    if (!reviewDrawerOpen) return;
    await click(tab, "#interpretation-close-review", args.timeoutMs);
    reviewDrawerOpen = false;
  };

  if (!existsSync(args.browserClient)) {
    checks.push(check("browser_iab_runtime", false, `Browser client not found at ${args.browserClient}`));
    return finish();
  }

  const { setupAtlasRuntime } = await import(pathToFileURL(args.browserClient).href);
  const backend = "iab";
  await setupAtlasRuntime({ globals: globalThis, backend });
  await agent.browser.nameSession("🧪 honorários iab smoke");
  const tab = await agent.browser.tabs.new();
  uploadFixtures = args.uploadPhoto || args.uploadPdf || args.uploadSupportingAttachment ? createSyntheticUploadFixtures(args) : null;

  checks.push(check("browser_iab_runtime", true, "Browser/IAB runtime initialized.", { backend: "iab" }));

  if (!(await runStep(checks, "browser_homepage", "Browser/IAB loaded the app shell.", async () => {
    await tab.goto(`${baseUrl}/`);
    await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: args.timeoutMs });
    await expectBodyText(tab, "Start Interpretation Request", args.timeoutMs);
    await expectBodyText(tab, "Review Case Details", args.timeoutMs);
    await expectBodyText(tab, "Draft-only Gmail", args.timeoutMs);
  }))) {
    return finish();
  }

  if (!(await runStep(checks, "browser_review_drawer", "Browser/IAB opened review drawer with Portuguese draft text.", async () => {
    await select(tab, "#profile", args.profile, args.timeoutMs);
    await fill(tab, "#case_number", args.caseNumber, args.timeoutMs);
    await fill(tab, "#service_date", args.answerQuestions ? "" : args.serviceDate, args.timeoutMs);
    await click(tab, "#review-intake", args.timeoutMs);
    await expectBodyText(tab, "Next Safe Action", args.timeoutMs);
    if (args.answerQuestions) {
      await expectBodyText(tab, "Answer the numbered questions", args.timeoutMs);
      await uniqueLocator(tab, "#numbered-answers", args.timeoutMs);
      await expectBodyText(tab, "Apply numbered answers", args.timeoutMs);
    } else {
      await expectAnyBodyText(tab, ["Número de processo", "Possible duplicate found"], args.timeoutMs);
    }
    if (!args.correctionMode && !args.answerQuestions) {
      await expectBodyText(tab, "To:", args.timeoutMs);
    }
    reviewDrawerOpen = true;
  }))) {
    return finish();
  }

  if (args.answerQuestions) {
    if (!(await runStep(checks, "browser_answer_questions", "Browser/IAB applied numbered missing-info answers and reran review without preparing artifacts.", async () => {
      await fill(tab, "#numbered-answers", `1. ${args.serviceDate}`, args.timeoutMs);
      await click(tab, "#apply-numbered-answers", args.timeoutMs);
      await expectBodyText(tab, "Número de processo", args.timeoutMs);
      await expectBodyText(tab, portugueseDate(args.serviceDate), args.timeoutMs);
      await expectBodyText(tab, "To:", args.timeoutMs);
      reviewDrawerOpen = true;
    }))) {
      return finish();
    }
  }

  if (args.uploadPhoto) {
    if (!(await runStep(checks, "browser_photo_upload_evidence", "Browser/IAB uploaded a synthetic photo and showed Source Evidence without preparing artifacts.", async () => {
      await closeReviewDrawerIfOpen();
      await setSyntheticInputFile(tab, "#photo-file", uploadFixtures.photoPath, args.timeoutMs);
      await click(tab, "#photo-upload-form button[type=submit]", args.timeoutMs);
      await expectBodyText(tab, "Source Evidence", args.timeoutMs);
      await expectSelectorText(tab, "#source-evidence-body", "Filename", args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.uploadPdf) {
    if (!(await runStep(checks, "browser_pdf_upload_evidence", "Browser/IAB uploaded a synthetic notification PDF and surfaced candidate review fields without preparing artifacts.", async () => {
      await closeReviewDrawerIfOpen();
      await setSyntheticInputFile(tab, "#notification-file", uploadFixtures.pdfPath, args.timeoutMs);
      await click(tab, "#notification-upload-form button[type=submit]", args.timeoutMs);
      await expectBodyText(tab, "Source Evidence", args.timeoutMs);
      await expectSelectorText(tab, "#source-evidence-body", "Filename", args.timeoutMs);
      await expectValueContains(tab, "#case_number", args.caseNumber, args.timeoutMs);
      await expectValueContains(tab, "#service_date", args.serviceDate, args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.uploadSupportingAttachment) {
    if (!(await runStep(checks, "browser_supporting_attachment_upload_evidence", "Browser/IAB uploaded a synthetic declaration through the Supporting proof UI without preparing artifacts.", async () => {
      await closeReviewDrawerIfOpen();
      await setSyntheticInputFile(tab, "#supporting-attachment-file", uploadFixtures.supportingPath, args.timeoutMs);
      await click(tab, "#supporting-attachment-form button[type=submit]", args.timeoutMs);
      await expectSelectorText(tab, "#supporting-attachment-list", "synthetic-declaracao.pdf", args.timeoutMs);
      await expectBodyText(tab, "email body now mentions", args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (!args.prepareReplacement || args.preparePacket) {
    if (!(await runStep(checks, "browser_batch_queue", "Browser/IAB added the reviewed request to the batch queue without preparing artifacts.", async () => {
      await closeReviewDrawerIfOpen();
      await click(tab, "#add-current-to-batch", args.timeoutMs);
      await expectSelectorText(tab, "#batch-count-chip", "1 queued", args.timeoutMs);
      await expectBodyText(tab, "Packet item inspector", args.timeoutMs);
    }))) {
      return finish();
    }
    if (!(await runStep(checks, "browser_batch_preflight", "Browser/IAB ran non-writing batch preflight before artifact preparation.", async () => {
      await expectSelectorText(tab, "#batch-preflight-result", "Batch preflight", args.timeoutMs);
      await expectSelectorText(tab, "#batch-preflight-result", "Artifact effect", args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.correctionMode) {
    if (!(await runStep(checks, "browser_correction_mode", "Browser/IAB checked draft lifecycle and filled a correction reason without preparing a replacement.", async () => {
      if (!args.prepareReplacement) {
        await click(tab, "#review-intake", args.timeoutMs);
      }
      await expectBodyText(tab, "Correction mode", args.timeoutMs);
      await click(tab, "#check-active-drafts", args.timeoutMs);
      await expectBodyText(tab, "Draft lifecycle", args.timeoutMs);
      await fill(tab, "#correction_reason", args.correctionReason, args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.prepareReplacement) {
    if (!args.correctionMode) {
      checks.push(check("browser_replacement_prepare", false, "Replacement preparation smoke requires --correction-mode."));
      return finish();
    }
    if (!(await runStep(checks, "browser_replacement_prepare", "Browser/IAB prepared a replacement payload without recording a draft or calling Gmail.", async () => {
      await click(tab, "#prepare-replacement-draft", args.timeoutMs);
      await expectBodyText(tab, "Replacement payload prepared", args.timeoutMs);
      await expectBodyText(tab, "Draft-only Gmail", args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.preparePacket) {
    if (!(await runStep(checks, "browser_packet_prepare", "Browser/IAB prepared packet mode and exposed packet draft helpers.", async () => {
      await setChecked(tab, "#batch-packet-mode", true, args.timeoutMs);
      await click(tab, "#preflight-batch-intakes", args.timeoutMs);
      await expectSelectorText(tab, "#batch-preflight-result", "Batch preflight", args.timeoutMs);
      await click(tab, "#prepare-batch-intakes", args.timeoutMs);
      await expectBodyText(tab, "Packet draft recording helper", args.timeoutMs);
      await expectBodyText(tab, "Underlying duplicate blockers", args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.recordHelper) {
    checks.push(check("browser_record_helper", false, "Browser/IAB smoke intentionally does not autofill or record draft lifecycle forms."));
    return finish();
  }

  if (args.applyHistory) {
    if (!(await runStep(checks, "browser_apply_history", "Browser/IAB checked LegalPDF Apply History, detail, restore-plan, and guarded restore controls without writing.", async () => {
      // The References surface is independent from the intake drawer/batch flow.
      // Reload before checking it so prior drawer state cannot mask sidebar controls.
      await tab.goto(`${baseUrl}/`);
      await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: args.timeoutMs });
      await openReferencesPanel(tab, args.timeoutMs);
      await expectBodyText(tab, "LegalPDF Apply History", args.timeoutMs);
      await expectBodyText(tab, "LegalPDF Restore Plan", args.timeoutMs);
      await click(tab, "#refresh-legalpdf-apply-history", args.timeoutMs);
      await expectAnyBodyText(tab, ["No guarded LegalPDF import has been applied yet", "JSON report", "Pre-apply backup"], args.timeoutMs);
      const detailCount = await countLocator(tab, "[data-legalpdf-report-id]");
      if (detailCount > 0) {
        await tab.playwright.locator("[data-legalpdf-report-id]").first().click({ timeoutMs: args.timeoutMs });
        await expectBodyText(tab, "LegalPDF Apply Detail", args.timeoutMs);
        await expectAnyBodyText(tab, ["read-only", "Read-only"], args.timeoutMs);
      }
      const restoreCount = await countLocator(tab, "[data-legalpdf-restore-report-id]");
      if (restoreCount > 0) {
        await tab.playwright.locator("[data-legalpdf-restore-report-id]").first().click({ timeoutMs: args.timeoutMs });
        await expectBodyText(tab, "LegalPDF Restore Plan", args.timeoutMs);
        await expectAnyBodyText(tab, ["preview only", "read-only", "Read-only"], args.timeoutMs);
        await expectBodyText(tab, "Apply this restore locally", args.timeoutMs);
        await expectBodyText(tab, "Restore local references from backup", args.timeoutMs);
        await expectBodyText(tab, "RESTORE LEGALPDF APPLY BACKUP", args.timeoutMs);
        await uniqueLocator(tab, "#legalpdf-restore-reason", args.timeoutMs);
        await uniqueLocator(tab, "#legalpdf-restore-phrase", args.timeoutMs);
        await uniqueLocator(tab, "#confirm-legalpdf-restore", args.timeoutMs);
      }
    }))) {
      return finish();
    }
  }

  if (!(await runStep(checks, "browser_workspace_reset", "Browser/IAB reset the synthetic workspace after smoke checks.", async () => {
    await uniqueLocator(tab, "#reset-workspace", args.timeoutMs);
    await tab.goto(`${baseUrl}/?smoke-reset=${Date.now()}`);
    await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: args.timeoutMs });
    await expectSelectorText(tab, "#batch-count-chip", "0 queued", args.timeoutMs);
    await expectBodyText(tab, "Reset workspace", args.timeoutMs);
  }))) {
    return finish();
  }

  return finish();
}

async function main(argv = (typeof process !== "undefined" ? process.argv.slice(2) : [])) {
  const args = parseArgs(argv);
  if (args.help) {
    console.log("Usage: node scripts/browser_iab_smoke.mjs --base-url http://127.0.0.1:8766 --json [--upload-photo] [--upload-pdf] [--upload-supporting-attachment] [--answer-questions] [--correction-mode] [--prepare-replacement] [--prepare-packet] [--apply-history]");
    return 0;
  }
  const result = await runBrowserIabSmoke(args);
  console.log(JSON.stringify(result, null, 2));
  return result.status === "ready" ? 0 : 1;
}

const invokedAsCli = typeof process !== "undefined" && process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedAsCli) {
  main()
    .then((code) => {
      process.exitCode = code;
    })
    .catch((error) => {
      const message = error instanceof Error ? error.message : String(error);
      const baseUrl = "http://127.0.0.1:8766";
      console.log(JSON.stringify({
        status: "blocked",
        base_url: baseUrl,
        checks: [check("browser_iab_runtime", false, message)],
        failure_count: 1,
        send_allowed: false,
      }, null, 2));
      process.exitCode = 1;
    });
}
