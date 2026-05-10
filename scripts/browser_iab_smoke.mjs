#!/usr/bin/env node
import { pathToFileURL } from "node:url";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const DEFAULT_BROWSER_CLIENTS = [
  "%USERPROFILE%/example-path",
  "%USERPROFILE%/example-path",
];
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
  const defaultBrowserClient = DEFAULT_BROWSER_CLIENTS.find((candidate) => existsSync(candidate)) || DEFAULT_BROWSER_CLIENTS[0];
  const args = {
    baseUrl: "http://127.0.0.1:8765",
    browserClient: (typeof process !== "undefined" && process.env && process.env.BROWSER_USE_CLIENT_MJS) || defaultBrowserClient,
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
    profileProposal: false,
    gmailApiCreate: false,
    manualHandoffStale: false,
    supportingAttachmentStale: false,
    recentWorkLifecycle: false,
    recentWorkReconciliation: false,
    keepOpen: false,
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
    else if (item === "--profile-proposal") args.profileProposal = true;
    else if (item === "--gmail-api-create") args.gmailApiCreate = true;
    else if (item === "--manual-handoff-stale") args.manualHandoffStale = true;
    else if (item === "--supporting-attachment-stale") args.supportingAttachmentStale = true;
    else if (item === "--recent-work-lifecycle") args.recentWorkLifecycle = true;
    else if (item === "--recent-work-reconciliation") args.recentWorkReconciliation = true;
    else if (item === "--keep-open") args.keepOpen = true;
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

async function fetchJson(baseUrl, path, timeoutMs) {
  if (typeof fetch !== "function") {
    throw new Error("Fetch API is unavailable; cannot confirm Browser/IAB safety status.");
  }
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      headers: { Accept: "application/json" },
      signal: controller?.signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function check(name, passed, message, details = {}) {
  return {
    name,
    status: passed ? "ready" : "blocked",
    message,
    details,
  };
}

function browserGmailApiStatusRequiredCheck(gmailStatus) {
  const details = {
    fake_mode: gmailStatus?.fake_mode === true,
    draft_only: gmailStatus?.draft_only === true,
    draft_create_ready: gmailStatus?.draft_create_ready === true,
    gmail_api_action: gmailStatus?.gmail_api_action,
    send_allowed: gmailStatus?.send_allowed,
  };
  const passed = (
    details.fake_mode
    && details.draft_only
    && details.draft_create_ready
    && details.gmail_api_action === "users.drafts.create"
    && details.send_allowed === false
  );
  return check(
    "browser_gmail_api_status_required",
    passed,
    passed
      ? "Browser/IAB confirmed fake, draft-only, create-ready users.drafts.create status before clicking Gmail draft creation."
      : "Browser/IAB Gmail draft-create smoke requires fake, draft-only, create-ready users.drafts.create status before clicking Create Gmail Draft.",
    details,
  );
}

function browserRecentWorkReconciliationStatusRequiredCheck(gmailStatus) {
  const details = {
    fake_mode: gmailStatus?.fake_mode === true,
    draft_only: gmailStatus?.draft_only === true,
    gmail_readonly_verify_action: gmailStatus?.gmail_readonly_verify_action,
    send_allowed: gmailStatus?.send_allowed,
  };
  const passed = (
    details.fake_mode
    && details.draft_only
    && details.gmail_readonly_verify_action === "users.drafts.get"
    && details.send_allowed === false
  );
  return check(
    "browser_recent_work_reconciliation_status_required",
    passed,
    passed
      ? "Browser/IAB confirmed fake, draft-only users.drafts.get status before Recent Work reconciliation."
      : "Browser/IAB Recent Work reconciliation smoke requires fake, draft-only users.drafts.get status.",
    details,
  );
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

function forbiddenSendActionTerms() {
  return [
    ["_send", "email"].join("_"),
    ["_send", "draft"].join("_"),
    ["messages", "send"].join("."),
    ["drafts", "send"].join("."),
  ];
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

async function expectSelectorTextExcludes(tab, selector, texts, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  const actual = await locator.innerText({ timeoutMs });
  for (const text of texts) {
    if (actual.includes(text)) {
      throw new Error(`Expected ${selector} to redact ${JSON.stringify(text)}.`);
    }
  }
}

async function expectClipboardText(tab, text, timeoutMs) {
  if (!tab.clipboard?.readText) {
    throw new Error("Browser/IAB clipboard read capability is unavailable.");
  }
  const deadline = Date.now() + timeoutMs;
  let actual = "";
  while (Date.now() < deadline) {
    actual = await tab.clipboard.readText();
    if (String(actual || "").includes(text)) return actual;
    await tab.playwright.waitForTimeout(100);
  }
  throw new Error(`Expected clipboard to include ${JSON.stringify(text)}; got ${JSON.stringify(actual)}.`);
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

async function attachedLocator(tab, selector, timeoutMs) {
  const locator = tab.playwright.locator(selector);
  await locator.waitFor({ state: "attached", timeoutMs });
  const count = await locator.count();
  if (count !== 1) throw new Error(`Expected ${selector} to match exactly one attached element; got ${count}.`);
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
  const locator = await attachedLocator(tab, selector, timeoutMs);
  const readChecked = async () => {
    if (typeof locator.isChecked === "function") {
      return { known: true, value: await locator.isChecked() };
    }
    if (typeof locator.evaluateAll === "function") {
      return { known: true, value: await locator.evaluateAll((nodes) => Boolean(nodes[0]?.checked)) };
    }
    return { known: false, value: null };
  };
  let setCheckedFailed = false;
  try {
    if (typeof locator.scrollIntoViewIfNeeded === "function") {
      await locator.scrollIntoViewIfNeeded({ timeoutMs });
    }
    await locator.setChecked(value, { timeout: timeoutMs });
  } catch (_error) {
    // The Browser/IAB adapter can fail checkbox state changes even when the
    // visible label works. Fall through to the label/click path and verify.
    setCheckedFailed = true;
  }
  const current = await readChecked();
  if (setCheckedFailed || (current.known && current.value !== value)) {
    const id = selector.startsWith("#") ? selector.slice(1) : "";
    const labelSelector = id ? `label[for="${id}"]` : "";
    const target = labelSelector ? await uniqueLocator(tab, labelSelector, timeoutMs) : locator;
    await target.click({ timeoutMs });
  }
  const verified = await readChecked();
  if (verified.known && verified.value !== value) {
    throw new Error(`Click did not change checked state to ${value}\nlocator.setChecked(${value}) failed for selector ${selector}`);
  }
}

async function expectValueContains(tab, selector, value, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  let actual = "";
  if (typeof locator.inputValue === "function") {
    actual = await locator.inputValue({ timeout: timeoutMs });
  } else if (typeof locator.evaluateAll === "function") {
    actual = await locator.evaluateAll((nodes) => {
      const first = nodes[0];
      if (!first) return "";
      return first.value || first.getAttribute?.("value") || "";
    });
  } else {
    actual = await locator.getAttribute("value", { timeout: timeoutMs });
  }
  if (!actual && typeof tab.playwright.domSnapshot === "function") {
    const snapshot = await tab.playwright.domSnapshot();
    if (String(snapshot || "").includes(value)) return;
  }
  if (!String(actual || "").includes(value)) {
    throw new Error(`Expected ${selector} value to contain ${JSON.stringify(value)}; got ${JSON.stringify(actual)}.`);
  }
}

async function expectValueEquals(tab, selector, value, timeoutMs) {
  const locator = await uniqueLocator(tab, selector, timeoutMs);
  let actual = "";
  if (typeof locator.inputValue === "function") {
    actual = await locator.inputValue({ timeout: timeoutMs });
  } else if (typeof locator.evaluateAll === "function") {
    actual = await locator.evaluateAll((nodes) => {
      const first = nodes[0];
      if (!first) return "";
      return first.value || first.getAttribute?.("value") || "";
    });
  } else {
    actual = await locator.getAttribute("value", { timeout: timeoutMs });
  }
  if (String(actual || "") !== String(value || "")) {
    throw new Error(`Expected ${selector} value to equal ${JSON.stringify(value)}; got ${JSON.stringify(actual)}.`);
  }
}

async function expectAttributeContains(tab, selector, attribute, value, timeoutMs) {
  const locator = await attachedLocator(tab, selector, timeoutMs);
  const actual = await locator.getAttribute(attribute, { timeoutMs });
  if (!String(actual || "").includes(value)) {
    throw new Error(`Expected ${selector} ${attribute} to contain ${JSON.stringify(value)}; got ${JSON.stringify(actual)}.`);
  }
}

async function expectChecked(tab, selector, expected, timeoutMs) {
  const locator = await attachedLocator(tab, selector, timeoutMs);
  let actual = null;
  if (typeof locator.isChecked === "function") {
    actual = await locator.isChecked({ timeout: timeoutMs });
  } else if (typeof locator.evaluateAll === "function") {
    actual = await locator.evaluateAll((nodes) => Boolean(nodes[0]?.checked));
  }
  if (actual !== expected) {
    throw new Error(`Expected ${selector} checked state to be ${expected}; got ${actual}.`);
  }
}

async function expectButtonDisabled(tab, selector, timeoutMs) {
  const locator = await attachedLocator(tab, selector, timeoutMs);
  const disabled = await locator.getAttribute("disabled", { timeoutMs });
  const ariaDisabled = await locator.getAttribute("aria-disabled", { timeoutMs });
  if (disabled === null && ariaDisabled !== "true") {
    throw new Error(`Expected ${selector} to be disabled or aria-disabled.`);
  }
}

async function expectButtonEnabled(tab, selector, timeoutMs) {
  const locator = await attachedLocator(tab, selector, timeoutMs);
  const disabled = await locator.getAttribute("disabled", { timeoutMs });
  const ariaDisabled = await locator.getAttribute("aria-disabled", { timeoutMs });
  if (disabled !== null || ariaDisabled === "true") {
    throw new Error(`Expected ${selector} to be enabled.`);
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

async function expectLocatorCountAtLeast(tab, selector, minimum, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let count = 0;
  while (Date.now() < deadline) {
    count = await countLocator(tab, selector);
    if (count >= minimum) return;
    await tab.playwright.waitForTimeout(100);
  }
  throw new Error(`Expected ${selector} to match at least ${minimum} element(s); got ${count}.`);
}

async function openHistoryPanel(tab, timeoutMs) {
  await click(tab, 'button[data-panel="history"]', timeoutMs);
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
  let tab = null;
  let existingTabIds = new Set();
  let runnerCreatedTab = false;
  let runnerTabCleanupMode = "close";
  const finish = async () => {
    cleanupSyntheticUploadFixtures(uploadFixtures);
    uploadFixtures = null;
    if (!args.keepOpen && runnerCreatedTab && tab) {
      try {
        if (runnerTabCleanupMode === "blank") {
          await tab.goto("about:blank");
          checks.push(check("browser_tab_cleanup", true, "Browser/IAB reset the sole disposable smoke tab to about:blank.", { keep_open: false, cleanup_mode: "blank" }));
        } else {
          await tab.close();
          checks.push(check("browser_tab_cleanup", true, "Browser/IAB closed the disposable smoke tab.", { keep_open: false, cleanup_mode: "close" }));
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        checks.push(check("browser_tab_cleanup", false, `Browser/IAB could not close the disposable smoke tab: ${message}`, { keep_open: false }));
      }
    } else if (args.keepOpen && runnerCreatedTab && tab) {
      checks.push(check("browser_tab_cleanup", true, "Browser/IAB kept the disposable smoke tab open for debugging.", { keep_open: true }));
    } else {
      checks.push(check("browser_tab_cleanup", true, "Browser/IAB did not create a disposable tab before stopping.", { keep_open: Boolean(args.keepOpen) }));
    }
    return report(baseUrl, checks);
  };
  const closeReviewDrawerIfOpen = async () => {
    if (!reviewDrawerOpen) return;
    await click(tab, "#interpretation-close-review", args.timeoutMs);
    reviewDrawerOpen = false;
  };

  if (!(await runStep(checks, "browser_health_check", "Browser/IAB confirmed the local app health endpoint before UI interaction.", async () => {
    const health = await fetchJson(baseUrl, "/api/health", args.timeoutMs);
    if (
      health?.status !== "ready"
      || health?.app !== "LegalPDF Honorários"
      || health?.send_allowed !== false
      || health?.write_allowed !== false
      || health?.managed_data_changed !== false
    ) {
      throw new Error("Browser/IAB health check returned an unsafe or unexpected response.");
    }
  }))) {
    return finish();
  }

  if (!existsSync(args.browserClient)) {
    checks.push(check("browser_iab_runtime", false, `Browser client not found at ${args.browserClient}`));
    return finish();
  }

  const { setupAtlasRuntime } = await import(pathToFileURL(args.browserClient).href);
  const backend = "iab";
  await setupAtlasRuntime({ globals: globalThis });
  const browserSession = agent.browser || (agent.browsers ? await agent.browsers.get("iab") : null);
  if (!browserSession) {
    checks.push(check("browser_iab_runtime", false, "Browser/IAB runtime did not expose an in-app browser session."));
    return finish();
  }
  await browserSession.nameSession("🧪 honorários iab smoke");
  try {
    existingTabIds = new Set((await browserSession.tabs.list()).map((item) => String(item.id)));
  } catch (error) {
    checks.push(check("browser_iab_runtime", false, error instanceof Error ? error.message : String(error)));
    return finish();
  }
  try {
    tab = await browserSession.tabs.new();
    if (existingTabIds.has(String(tab.id))) {
      checks.push(check(
        "browser_iab_runtime",
        false,
        "Browser/IAB did not allocate a disposable smoke tab; refusing to drive an existing tab.",
        { existing_tab_count: existingTabIds.size, tab_id: String(tab.id) },
      ));
      return finish();
    }
    runnerCreatedTab = true;
    const tabsAfterCreate = await browserSession.tabs.list();
    if (tabsAfterCreate.length <= 1) {
      runnerTabCleanupMode = "blank";
    }
  } catch (error) {
    checks.push(check("browser_iab_runtime", false, error instanceof Error ? error.message : String(error)));
    return finish();
  }
  uploadFixtures = args.uploadPhoto || args.uploadPdf || args.uploadSupportingAttachment || args.supportingAttachmentStale ? createSyntheticUploadFixtures(args) : null;

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

  if (args.recentWorkLifecycle) {
    if (!(await runStep(checks, "browser_recent_work_lifecycle", "Browser/IAB verified Recent Work lifecycle controls without clicking Gmail or local status writes.", async () => {
      await openHistoryPanel(tab, args.timeoutMs);
      await expectBodyText(tab, "Duplicate And Draft History", args.timeoutMs);
      await expectBodyText(tab, "Draft lifecycle actions", args.timeoutMs);
      await expectBodyText(tab, "Local bookkeeping", args.timeoutMs);
      await uniqueLocator(tab, "#history-sent-date", args.timeoutMs);
      await expectLocatorCountAtLeast(tab, "[data-history-status-filter]", 7, args.timeoutMs);
      await expectBodyText(tab, "draft-synthetic-active", args.timeoutMs);
      await expectLocatorCountAtLeast(tab, "[data-history-verify-draft]", 1, args.timeoutMs);
      await expectLocatorCountAtLeast(tab, "[data-history-mark-sent]", 1, args.timeoutMs);
      await expectBodyText(tab, "Verify draft exists", args.timeoutMs);
      await expectBodyText(tab, "Mark manually sent", args.timeoutMs);
      await fill(tab, "#history-sent-date", args.serviceDate, args.timeoutMs);
      await click(tab, '[data-history-status-filter="drafted"]', args.timeoutMs);
      await expectBodyText(tab, "draft-synthetic-active", args.timeoutMs);
    }))) {
      return finish();
    }

    if (!(await runStep(checks, "browser_workspace_reset", "Browser/IAB reset the synthetic workspace after Recent Work lifecycle smoke.", async () => {
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

  if (args.recentWorkReconciliation) {
    let gmailStatus = null;
    if (!(await runStep(checks, "browser_recent_work_reconciliation_fake_mode_required", "Browser/IAB confirmed fake Gmail mode before Recent Work reconciliation.", async () => {
      gmailStatus = await fetchJson(baseUrl, "/api/gmail/status", args.timeoutMs);
      if (gmailStatus.fake_mode !== true) {
        throw new Error("Browser/IAB Recent Work reconciliation smoke requires fake Gmail mode before clicking Verify draft exists.");
      }
    }))) {
      return finish();
    }
    const statusGate = browserRecentWorkReconciliationStatusRequiredCheck(gmailStatus);
    checks.push(statusGate);
    if (statusGate.status !== "ready") {
      return finish();
    }
    if (!(await runStep(checks, "browser_recent_work_reconciliation", "Browser/IAB verified Recent Work Gmail reconciliation through read-only users.drafts.get without local status writes.", async () => {
      await openHistoryPanel(tab, args.timeoutMs);
      await expectBodyText(tab, "Duplicate And Draft History", args.timeoutMs);
      await expectBodyText(tab, "draft-missing-active", args.timeoutMs);
      await click(tab, "button[data-history-source=\"draft_log\"][data-history-verify-draft]", args.timeoutMs);
      await expectSelectorText(tab, "#history-draft-action-result", "Read-only Gmail draft verification", args.timeoutMs);
      await expectSelectorText(tab, "#history-draft-action-result", "not_found", args.timeoutMs);
      await expectSelectorText(tab, "#history-draft-action-result", "users.drafts.get", args.timeoutMs);
      await expectSelectorText(tab, "#history-draft-action-result", "No local records were changed", args.timeoutMs);
      await expectBodyText(tab, "Mark not_found locally", args.timeoutMs);
    }))) {
      return finish();
    }

    if (!(await runStep(checks, "browser_workspace_reset", "Browser/IAB reset the synthetic workspace after Recent Work reconciliation smoke.", async () => {
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

  if (args.profileProposal) {
    if (!(await runStep(checks, "browser_profile_proposal", "Browser/IAB previewed a proposed service profile in the guarded editor without saving.", async () => {
      await select(tab, "#profile", "court_mp_generic", args.timeoutMs);
      await fill(tab, "#case_number", "111/26.0TEST", args.timeoutMs);
      await fill(tab, "#service_date", args.serviceDate, args.timeoutMs);
      await fill(tab, "#payment_entity", "Ministério Público de Beja", args.timeoutMs);
      await fill(tab, "#recipient_email", "court@example.test", args.timeoutMs);
      await fill(tab, "#service_place", "Posto Territorial de Vidigueira", args.timeoutMs);
      await fill(tab, "#km_one_way", "12", args.timeoutMs);
      await fill(tab, "#source_text", "Guarda Nacional Republicana. Posto Territorial de Vidigueira. Ministério Público de Beja. Diligência de interpretação.", args.timeoutMs);
      await click(tab, "#review-intake", args.timeoutMs);
      await expectBodyText(tab, "Source Evidence", args.timeoutMs);
      await expectBodyText(tab, "Profile proposal", args.timeoutMs);
      await expectBodyText(tab, "Preview proposed profile", args.timeoutMs);
      reviewDrawerOpen = true;
      await closeReviewDrawerIfOpen();
      await click(tab, "[data-use-profile-proposal=\"true\"]", args.timeoutMs);
      await expectBodyText(tab, "Service profiles", args.timeoutMs);
      await expectValueContains(tab, "#profile_key", "vidigueira", args.timeoutMs);
      await expectValueContains(tab, "#profile_recipient_email", "court@example.test", args.timeoutMs);
      await expectValueContains(tab, "#profile_payment_entity", "Ministério Público de Beja", args.timeoutMs);
      await expectValueContains(tab, "#profile_service_place", "Posto Territorial de Vidigueira", args.timeoutMs);
      await expectValueContains(tab, "#profile_km_one_way", "12", args.timeoutMs);
      await click(tab, "#preview-profile-change", args.timeoutMs);
      await expectSelectorText(tab, "#profile-preview-card", "Preview guarded profile", args.timeoutMs);
    }))) {
      return finish();
    }

    if (!(await runStep(checks, "browser_legalpdf_import_gates", "Browser/IAB confirmed LegalPDF import controls are preview/phrase/reason guarded and read-only by default.", async () => {
      await expectBodyText(tab, "LegalPDF Integration Preview", args.timeoutMs);
      await uniqueLocator(tab, "#legalpdf-apply-reason", args.timeoutMs);
      await uniqueLocator(tab, "#legalpdf-apply-phrase", args.timeoutMs);
      await uniqueLocator(tab, "#confirm-legalpdf-import-apply", args.timeoutMs);
      await uniqueLocator(tab, "#apply-legalpdf-import-plan", args.timeoutMs);
      await expectAttributeContains(tab, "#legalpdf-apply-phrase", "placeholder", "APPLY LEGALPDF IMPORT PLAN", args.timeoutMs);
      await expectBodyText(tab, "never touches LegalPDF", args.timeoutMs);
      await expectAnyBodyText(tab, ["No guarded LegalPDF import has been applied yet", "JSON report", "Pre-apply backup"], args.timeoutMs);
    }))) {
      return finish();
    }

    if (!(await runStep(checks, "browser_workspace_reset", "Browser/IAB reset the synthetic workspace after profile-proposal smoke checks.", async () => {
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

  if (!(await runStep(checks, "browser_review_drawer", "Browser/IAB opened review drawer with Portuguese draft text.", async () => {
    await select(tab, "#profile", args.profile, args.timeoutMs);
    await fill(tab, "#case_number", args.caseNumber, args.timeoutMs);
    await fill(tab, "#service_date", args.answerQuestions ? "" : args.serviceDate, args.timeoutMs);
    await click(tab, "#review-intake", args.timeoutMs);
    await expectBodyText(tab, "Suggested Next Step", args.timeoutMs);
    await expectBodyText(tab, "Suggested Next Step", args.timeoutMs);
    await expectBodyText(tab, "not a separate task", args.timeoutMs);
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

  if (args.gmailApiCreate) {
    let gmailStatus = null;
    if (!(await runStep(checks, "browser_gmail_api_fake_mode_required", "Browser/IAB confirmed fake Gmail mode before clicking Gmail draft creation.", async () => {
      gmailStatus = await fetchJson(baseUrl, "/api/gmail/status", args.timeoutMs);
      if (gmailStatus.fake_mode !== true) {
        throw new Error("Browser/IAB Gmail draft-create smoke requires fake Gmail mode before clicking Create Gmail Draft.");
      }
    }))) {
      return finish();
    }
    const statusGate = browserGmailApiStatusRequiredCheck(gmailStatus);
    checks.push(statusGate);
    if (statusGate.status !== "ready") {
      return finish();
    }
    if (!(await runStep(checks, "browser_gmail_api_create", "Browser/IAB created and verified a synthetic Gmail draft through the fake Gmail API path.", async () => {
      await click(tab, "#drawer-prepare-intake", args.timeoutMs);
      await expectBodyText(tab, "PDF and Gmail draft payload prepared", args.timeoutMs);
      await expectBodyText(tab, "Exact gmail_create_draft_args", args.timeoutMs);
      await setChecked(tab, "#gmail_handoff_reviewed", true, args.timeoutMs);
      await click(tab, "#create-gmail-api-draft", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-api-result", "draft-smoke", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-api-result", "Verify created draft", args.timeoutMs);
      await click(tab, "[data-verify-created-draft=\"true\"]", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-verify-result", "Read-only Gmail draft verification", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-verify-result", "Gmail draft exists", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-verify-result", "users.drafts.get", args.timeoutMs);
      await fill(tab, "#record_draft_id", "draft-mismatch-smoke", args.timeoutMs);
      await fill(tab, "#record_message_id", "local-message-smoke", args.timeoutMs);
      await fill(tab, "#record_thread_id", "local-thread-smoke", args.timeoutMs);
      await click(tab, "#verify-gmail-draft", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-verify-result", "reconciliation mismatch", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-verify-result", "Message ID differs", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-verify-result", "Thread ID differs", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-verify-result", "No local records were changed", args.timeoutMs);
      await expectSelectorText(tab, "#gmail-verify-result", "users.drafts.get", args.timeoutMs);
    }))) {
      return finish();
    }

    if (!(await runStep(checks, "browser_workspace_reset", "Browser/IAB reset the synthetic workspace after fake Gmail draft smoke.", async () => {
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
    if (!args.preparePacket) {
      if (!(await runStep(checks, "browser_batch_stale_gating", "Browser/IAB marked batch preflight stale and kept artifact-producing actions gated after packet-mode changes.", async () => {
        await setChecked(tab, "#batch-packet-mode", true, args.timeoutMs);
        await expectSelectorText(tab, "#batch-preflight-result", "Run a non-writing batch preflight", args.timeoutMs);
        await expectButtonDisabled(tab, "#prepare-batch-intakes", args.timeoutMs);
        await setChecked(tab, "#batch-packet-mode", false, args.timeoutMs);
        await expectSelectorText(tab, "#batch-preflight-result", "Run a non-writing batch preflight", args.timeoutMs);
        await expectButtonDisabled(tab, "#prepare-batch-intakes", args.timeoutMs);
      }))) {
        return finish();
      }
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
      reviewDrawerOpen = true;
      await closeReviewDrawerIfOpen();
      await click(tab, "#prepare-batch-intakes", args.timeoutMs);
      await expectSelectorText(tab, "#prepare-results", "Packet draft recording helper", args.timeoutMs);
      await expectSelectorText(tab, "#prepare-results", "Underlying duplicate blockers", args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.recordHelper) {
    if (!args.prepareReplacement && !args.preparePacket) {
      checks.push(check("browser_record_helper", false, "Record-helper smoke requires a prepared replacement or packet payload."));
      return finish();
    }
    const recordHelperShouldMutatePreparedState = !args.manualHandoffStale && !args.supportingAttachmentStale;
    if (!(await runStep(checks, "browser_record_helper", "Browser/IAB parsed Gmail IDs and autofilled the local record form without recording a draft.", async () => {
      const fakeResponse = '{"id":"draft-smoke","message":{"id":"message-smoke","threadId":"thread-smoke"}}';
      await fill(tab, "#gmail-response-raw", fakeResponse, args.timeoutMs);
      await click(tab, "#parse-gmail-response", args.timeoutMs);
      await expectButtonDisabled(tab, "#record-parsed-prepared-draft", args.timeoutMs);
      await expectAttributeContains(tab, "#record-parsed-prepared-draft", "title", "Review the PDF preview and exact Gmail args before local recording.", args.timeoutMs);
      await click(tab, "#autofill-record-from-prepared", args.timeoutMs);
      await expectValueContains(tab, "#record_draft_id", "draft-smoke", args.timeoutMs);
      await expectValueContains(tab, "#record_message_id", "message-smoke", args.timeoutMs);
      await expectValueContains(tab, "#record_thread_id", "thread-smoke", args.timeoutMs);
      await expectValueContains(tab, "#record_payload", ".draft.json", args.timeoutMs);
      await expectButtonDisabled(tab, "#record-parsed-prepared-draft", args.timeoutMs);
      await setChecked(tab, "#gmail_handoff_reviewed", true, args.timeoutMs);
      await expectButtonEnabled(tab, "#record-parsed-prepared-draft", args.timeoutMs);
      if (recordHelperShouldMutatePreparedState) {
        await fill(tab, "#source_text", `Stale state marker ${Date.now()}`, args.timeoutMs);
        await expectAttributeContains(tab, "#prepare-results", "data-stale-reason", "intake form changed", args.timeoutMs);
      }
    }))) {
      return finish();
    }
  }

  if (args.supportingAttachmentStale) {
    if (!args.prepareReplacement && !args.preparePacket) {
      checks.push(check("browser_supporting_attachment_stale", false, "Supporting attachment stale smoke requires a prepared replacement or packet payload."));
      return finish();
    }
    if (!(await runStep(checks, "browser_supporting_attachment_stale", "Browser/IAB cleared prepared Gmail surfaces after a Supporting proof upload changed the attachment set.", async () => {
      await setChecked(tab, "#gmail_handoff_reviewed", true, args.timeoutMs);
      await click(tab, "#build-manual-handoff", args.timeoutMs);
      await expectSelectorText(tab, "#manual-handoff-packet", "Manual handoff packet ready", args.timeoutMs);
      await setSyntheticInputFile(tab, "#supporting-attachment-file", uploadFixtures.supportingPath, args.timeoutMs);
      await click(tab, "#supporting-attachment-form button[type=submit]", args.timeoutMs);
      await expectSelectorText(tab, "#supporting-attachment-list", "synthetic-declaracao.pdf", args.timeoutMs);
      await expectAttributeContains(tab, "#manual-handoff-packet", "class", "hidden", args.timeoutMs);
      await expectButtonDisabled(tab, "#copy-manual-handoff-prompt", args.timeoutMs);
      await expectButtonDisabled(tab, "#record-parsed-prepared-draft", args.timeoutMs);
      await expectButtonDisabled(tab, "#create-gmail-api-draft", args.timeoutMs);
      await expectChecked(tab, "#gmail_handoff_reviewed", false, args.timeoutMs);
      await expectValueEquals(tab, "#record_payload", "", args.timeoutMs);
      await expectValueEquals(tab, "#record_draft_id", "", args.timeoutMs);
      await expectValueEquals(tab, "#record_message_id", "", args.timeoutMs);
      await expectValueEquals(tab, "#record_thread_id", "", args.timeoutMs);
      await expectValueEquals(tab, "#gmail-response-raw", "", args.timeoutMs);
      await expectAttributeContains(tab, "#prepare-results", "data-stale-reason", "supporting attachments changed", args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.manualHandoffStale) {
    if (!args.prepareReplacement && !args.preparePacket) {
      checks.push(check("browser_manual_handoff_stale", false, "Manual handoff stale smoke requires a prepared replacement or packet payload."));
      return finish();
    }
    if (!(await runStep(checks, "browser_manual_handoff_stale", "Browser/IAB cleared the Manual Draft Handoff packet and kept record helpers gated after intake changes.", async () => {
      await click(tab, "#build-manual-handoff", args.timeoutMs);
      await expectSelectorText(tab, "#manual-handoff-packet", "Manual handoff packet ready", args.timeoutMs);
      await fill(tab, "#source_text", `Manual handoff stale marker ${Date.now()}`, args.timeoutMs);
      await expectAttributeContains(tab, "#manual-handoff-packet", "class", "hidden", args.timeoutMs);
      await expectButtonDisabled(tab, "#copy-manual-handoff-prompt", args.timeoutMs);
      await expectButtonDisabled(tab, "#record-parsed-prepared-draft", args.timeoutMs);
      await expectAttributeContains(tab, "#prepare-results", "data-stale-reason", "intake form changed", args.timeoutMs);
    }))) {
      return finish();
    }
  }

  if (args.applyHistory) {
    if (!(await runStep(checks, "browser_public_readiness_gate", "Browser/IAB checked the Public GitHub Readiness panel and confirmed redacted gate output.", async () => {
      // The References surface is independent from the intake drawer/batch flow.
      // Reload before checking it so prior drawer state cannot mask sidebar controls.
      await tab.goto(`${baseUrl}/`);
      await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: args.timeoutMs });
      await openReferencesPanel(tab, args.timeoutMs);
      await expectBodyText(tab, "Public GitHub Readiness", args.timeoutMs);
      await click(tab, "#run-public-readiness", args.timeoutMs);
      await expectSelectorText(tab, "#public-readiness-result", "Tracked Git content is ready for the public repo.", args.timeoutMs);
      await expectSelectorText(tab, "#public-readiness-result", "Local overlays", args.timeoutMs);
      await expectSelectorText(tab, "#public-readiness-result", "Full workspace gate", args.timeoutMs);
      await expectSelectorTextExcludes(tab, "#public-readiness-result", [
        "GOCSPX",
        "ya29.",
        "sk-",
        "gho_",
        "ghp_",
        ["C:", "Users"].join("\\"),
        ["C:", "Users"].join("/"),
      ], args.timeoutMs);
    }))) {
      return finish();
    }

    if (!(await runStep(checks, "browser_local_diagnostics", "Browser/IAB refreshed Local Diagnostics and copied readiness/isolated smoke commands without running them.", async () => {
      await expectBodyText(tab, "Local Diagnostics", args.timeoutMs);
      await uniqueLocator(tab, "#copy-isolated-source-upload-smoke-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-isolated-source-upload-smoke-command", "data-copy-diagnostic-command", "isolated_source_upload_smoke", args.timeoutMs);
      await uniqueLocator(tab, "#copy-legalpdf-adapter-readiness-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-legalpdf-adapter-readiness-command", "data-copy-diagnostic-command", "legalpdf_adapter_readiness", args.timeoutMs);
      await uniqueLocator(tab, "#copy-isolated-adapter-contract-smoke-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-isolated-adapter-contract-smoke-command", "data-copy-diagnostic-command", "isolated_adapter_contract_smoke", args.timeoutMs);
      await uniqueLocator(tab, "#copy-browser-iab-review-smoke-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-browser-iab-review-smoke-command", "data-copy-diagnostic-command", "browser_iab_smoke", args.timeoutMs);
      await uniqueLocator(tab, "#copy-browser-iab-answer-apply-smoke-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-browser-iab-answer-apply-smoke-command", "data-copy-diagnostic-command", "browser_iab_answer_apply_smoke", args.timeoutMs);
      await uniqueLocator(tab, "#copy-browser-iab-supporting-attachment-stale-smoke-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-browser-iab-supporting-attachment-stale-smoke-command", "data-copy-diagnostic-command", "browser_iab_supporting_attachment_stale_smoke", args.timeoutMs);
      await uniqueLocator(tab, "#copy-browser-iab-record-helper-smoke-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-browser-iab-record-helper-smoke-command", "data-copy-diagnostic-command", "browser_iab_record_helper_smoke", args.timeoutMs);
      await uniqueLocator(tab, "#copy-python-browser-record-helper-smoke-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-python-browser-record-helper-smoke-command", "data-copy-diagnostic-command", "python_browser_record_helper_smoke", args.timeoutMs);
      await uniqueLocator(tab, "#copy-browser-iab-recent-work-reconciliation-smoke-command", args.timeoutMs);
      await expectAttributeContains(tab, "#copy-browser-iab-recent-work-reconciliation-smoke-command", "data-copy-diagnostic-command", "browser_iab_recent_work_reconciliation_smoke", args.timeoutMs);
      await click(tab, "#refresh-diagnostics", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "Local diagnostics are available", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "Isolated source upload smoke", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--source-upload-checks", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "LegalPDF adapter readiness", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--readiness-only", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "LegalPDF adapter contract smoke", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--adapter-contract-checks", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "Browser/IAB review smoke", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--browser-iab-click-through", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "answers and apply history smoke", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--browser-answer-questions", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--browser-apply-history", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "Supporting proof stale smoke", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--browser-supporting-attachment-stale", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "record helper smoke", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--browser-record-helper", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "Python browser record helper smoke", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--browser-click-through", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "Recent Work reconciliation smoke", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "--browser-recent-work-reconciliation", args.timeoutMs);
      await expectSelectorText(tab, "#diagnostics-result", "The browser does not run shell commands or contact Gmail.", args.timeoutMs);
      const forbiddenSendActions = forbiddenSendActionTerms();
      await expectSelectorTextExcludes(tab, "#diagnostics-result", forbiddenSendActions, args.timeoutMs);
      await click(tab, "#copy-isolated-source-upload-smoke-command", args.timeoutMs);
      const clipboardText = await expectClipboardText(tab, "python scripts/isolated_app_smoke.py --source-upload-checks --json", args.timeoutMs);
      await click(tab, "#copy-legalpdf-adapter-readiness-command", args.timeoutMs);
      const adapterReadinessClipboardText = await expectClipboardText(tab, `python scripts/legalpdf_adapter_caller.py --base-url ${baseUrl} --readiness-only --json`, args.timeoutMs);
      await click(tab, "#copy-isolated-adapter-contract-smoke-command", args.timeoutMs);
      const adapterClipboardText = await expectClipboardText(tab, "python scripts/isolated_app_smoke.py --adapter-contract-checks --json", args.timeoutMs);
      await click(tab, "#copy-browser-iab-review-smoke-command", args.timeoutMs);
      const browserReviewClipboardText = await expectClipboardText(tab, "--browser-iab-click-through --json", args.timeoutMs);
      await click(tab, "#copy-browser-iab-answer-apply-smoke-command", args.timeoutMs);
      const answerApplyClipboardText = await expectClipboardText(tab, "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-answer-questions --browser-apply-history --json", args.timeoutMs);
      await click(tab, "#copy-browser-iab-supporting-attachment-stale-smoke-command", args.timeoutMs);
      const supportingStaleClipboardText = await expectClipboardText(tab, "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-correction-mode --browser-prepare-replacement --browser-supporting-attachment-stale --json", args.timeoutMs);
      await click(tab, "#copy-browser-iab-record-helper-smoke-command", args.timeoutMs);
      const recordHelperClipboardText = await expectClipboardText(tab, "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-correction-mode --browser-prepare-replacement --browser-record-helper --json", args.timeoutMs);
      await click(tab, "#copy-python-browser-record-helper-smoke-command", args.timeoutMs);
      const pythonRecordHelperClipboardText = await expectClipboardText(tab, "python scripts/isolated_app_smoke.py --browser-click-through --browser-correction-mode --browser-prepare-replacement --browser-record-helper --json", args.timeoutMs);
      await click(tab, "#copy-browser-iab-recent-work-reconciliation-smoke-command", args.timeoutMs);
      const recentWorkReconciliationClipboardText = await expectClipboardText(tab, "python scripts/isolated_app_smoke.py --browser-iab-click-through --browser-recent-work-reconciliation --json", args.timeoutMs);
      for (const forbidden of forbiddenSendActions) {
        if (clipboardText.includes(forbidden) || adapterReadinessClipboardText.includes(forbidden) || adapterClipboardText.includes(forbidden) || browserReviewClipboardText.includes(forbidden) || answerApplyClipboardText.includes(forbidden) || supportingStaleClipboardText.includes(forbidden) || recordHelperClipboardText.includes(forbidden) || pythonRecordHelperClipboardText.includes(forbidden) || recentWorkReconciliationClipboardText.includes(forbidden)) {
          throw new Error(`Expected copied diagnostics command to omit ${forbidden}.`);
        }
      }
    }))) {
      return finish();
    }

    if (!(await runStep(checks, "browser_apply_history", "Browser/IAB checked LegalPDF Apply History, detail, restore-plan, and guarded restore controls without writing.", async () => {
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
    console.log("Usage: node scripts/browser_iab_smoke.mjs --base-url http://127.0.0.1:8765 --json [--upload-photo] [--upload-pdf] [--upload-supporting-attachment] [--answer-questions] [--correction-mode] [--prepare-replacement] [--prepare-packet] [--record-helper] [--manual-handoff-stale] [--supporting-attachment-stale] [--recent-work-lifecycle] [--recent-work-reconciliation] [--apply-history] [--profile-proposal] [--gmail-api-create] [--keep-open]");
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
      const baseUrl = "http://127.0.0.1:8765";
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
