#!/usr/bin/env node
import { pathToFileURL } from "node:url";
import { existsSync } from "node:fs";

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

  if (!existsSync(args.browserClient)) {
    checks.push(check("browser_iab_runtime", false, `Browser client not found at ${args.browserClient}`));
    return report(baseUrl, checks);
  }

  if (args.uploadPhoto) {
    checks.push(check("browser_photo_upload_evidence", false, "Browser/IAB smoke does not drive local file-picker uploads yet; use the Python Playwright upload smoke for this surface."));
  }
  if (args.uploadPdf) {
    checks.push(check("browser_pdf_upload_evidence", false, "Browser/IAB smoke does not drive local file-picker uploads yet; use the Python Playwright upload smoke for this surface."));
  }
  if (args.uploadPhoto || args.uploadPdf) {
    return report(baseUrl, checks);
  }

  const { setupAtlasRuntime } = await import(pathToFileURL(args.browserClient).href);
  const backend = "iab";
  await setupAtlasRuntime({ globals: globalThis, backend });
  await agent.browser.nameSession("🧪 honorários iab smoke");
  const tab = await agent.browser.tabs.new();

  checks.push(check("browser_iab_runtime", true, "Browser/IAB runtime initialized.", { backend: "iab" }));

  if (!(await runStep(checks, "browser_homepage", "Browser/IAB loaded the app shell.", async () => {
    await tab.goto(`${baseUrl}/`);
    await tab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: args.timeoutMs });
    await expectBodyText(tab, "Start Interpretation Request", args.timeoutMs);
    await expectBodyText(tab, "Review Case Details", args.timeoutMs);
    await expectBodyText(tab, "Draft-only Gmail", args.timeoutMs);
  }))) {
    return report(baseUrl, checks);
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
  }))) {
    return report(baseUrl, checks);
  }

  if (args.answerQuestions) {
    if (!(await runStep(checks, "browser_answer_questions", "Browser/IAB applied numbered missing-info answers and reran review without preparing artifacts.", async () => {
      await fill(tab, "#numbered-answers", `1. ${args.serviceDate}`, args.timeoutMs);
      await click(tab, "#apply-numbered-answers", args.timeoutMs);
      await expectBodyText(tab, "Número de processo", args.timeoutMs);
      await expectBodyText(tab, portugueseDate(args.serviceDate), args.timeoutMs);
      await expectBodyText(tab, "To:", args.timeoutMs);
    }))) {
      return report(baseUrl, checks);
    }
  }

  if (!args.prepareReplacement || args.preparePacket) {
    if (!(await runStep(checks, "browser_batch_queue", "Browser/IAB added the reviewed request to the batch queue without preparing artifacts.", async () => {
      await click(tab, "#interpretation-close-review", args.timeoutMs);
      await click(tab, "#add-current-to-batch", args.timeoutMs);
      await expectSelectorText(tab, "#batch-count-chip", "1 queued", args.timeoutMs);
      await expectBodyText(tab, "Packet item inspector", args.timeoutMs);
    }))) {
      return report(baseUrl, checks);
    }
    if (!(await runStep(checks, "browser_batch_preflight", "Browser/IAB ran non-writing batch preflight before artifact preparation.", async () => {
      await expectSelectorText(tab, "#batch-preflight-result", "Batch preflight", args.timeoutMs);
      await expectSelectorText(tab, "#batch-preflight-result", "Artifact effect", args.timeoutMs);
    }))) {
      return report(baseUrl, checks);
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
      return report(baseUrl, checks);
    }
  }

  if (args.prepareReplacement) {
    if (!args.correctionMode) {
      checks.push(check("browser_replacement_prepare", false, "Replacement preparation smoke requires --correction-mode."));
      return report(baseUrl, checks);
    }
    if (!(await runStep(checks, "browser_replacement_prepare", "Browser/IAB prepared a replacement payload without recording a draft or calling Gmail.", async () => {
      await click(tab, "#prepare-replacement-draft", args.timeoutMs);
      await expectBodyText(tab, "Replacement payload prepared", args.timeoutMs);
      await expectBodyText(tab, "Draft-only Gmail", args.timeoutMs);
    }))) {
      return report(baseUrl, checks);
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
      return report(baseUrl, checks);
    }
  }

  if (args.recordHelper) {
    checks.push(check("browser_record_helper", false, "Browser/IAB smoke intentionally does not autofill or record draft lifecycle forms."));
    return report(baseUrl, checks);
  }

  if (args.applyHistory) {
    if (!(await runStep(checks, "browser_apply_history", "Browser/IAB checked LegalPDF Apply History, detail, and restore-plan surfaces without writing.", async () => {
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
      }
    }))) {
      return report(baseUrl, checks);
    }
  }

  return report(baseUrl, checks);
}

async function main(argv = (typeof process !== "undefined" ? process.argv.slice(2) : [])) {
  const args = parseArgs(argv);
  if (args.help) {
    console.log("Usage: node scripts/browser_iab_smoke.mjs --base-url http://127.0.0.1:8766 --json [--answer-questions] [--correction-mode] [--prepare-replacement] [--prepare-packet] [--apply-history]");
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
