"""Behavior checks for browser guidance, using fictional inputs and no browser state."""
from pathlib import Path
import json
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReviewGuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module_url = (ROOT / "honorarios_app/static/review_guidance.js").as_uri()
        script = "import * as g from " + json.dumps(module_url) + ";\n" + """
const prepared = {payload:'fictional.payload.json'};
const replacedPrepared = {payload:'fictional.payload.json'};
let revision = 1;
let applied = [];
let releaseOldPreparation;
const oldPreparationResponse = new Promise(resolve => { releaseOldPreparation = resolve; });
const capturedRevision = revision;
const oldPreparation = g.awaitWorkflowResponse(() => oldPreparationResponse, {revision:capturedRevision}, () => ({revision}));
revision += 1; // A source/intake edit invalidates the request while the response is pending.
releaseOldPreparation('obsolete prepared handoff');
const oldPreparationValue = await oldPreparation;
if (oldPreparationValue) applied.push(oldPreparationValue);
let releaseOldHandoff;
const oldHandoffResponse = new Promise(resolve => { releaseOldHandoff = resolve; });
let selectedPrepared = prepared;
const handoffRevision = revision;
const oldHandoff = g.awaitWorkflowResponse(() => oldHandoffResponse, {revision:handoffRevision,prepared}, () => ({revision,prepared:selectedPrepared}));
selectedPrepared = replacedPrepared; // Even an identical path belongs to a different prepared snapshot.
releaseOldHandoff('obsolete copy-ready prompt');
const oldHandoffValue = await oldHandoff;
if (oldHandoffValue) applied.push(oldHandoffValue);
const freshRevision = revision;
const freshValue = await g.awaitWorkflowResponse(() => Promise.resolve('current reviewed handoff'), {revision:freshRevision,prepared:replacedPrepared}, () => ({revision,prepared:selectedPrepared}));
if (freshValue) applied.push(freshValue);
let rejectObsolete;
const obsoleteFailure = new Promise((resolve,reject) => { rejectObsolete = reject; });
const obsoleteRequest = g.awaitWorkflowResponse(() => obsoleteFailure, {revision}, () => ({revision}));
revision += 1;
rejectObsolete(new Error('Obsolete failure must not reach the current-screen catch handler'));
const staleErrorResult = await obsoleteRequest;
let currentError = '';
try {
  await g.awaitWorkflowResponse(() => Promise.reject(new Error('Current synthetic blocker')), {revision}, () => ({revision}));
} catch (error) {
  currentError = error.message;
}
const input = {status:'ready',hasPrepared:true,handoffReady:true,recorded:true,stale:true};
const inputBefore = JSON.stringify(input);
const staleProjection = g.projectWorkflowGuidance(input);
console.log(JSON.stringify({
  stages: ['idle','answer_questions','set_aside_translation','prepare_pdf',
    'review_gmail_draft_args','unknown'].map(g.guidedStepForState),
  labels: [g.questionFieldLabel({field:'transport.km_one_way'}),
    g.questionFieldLabel({number:7,question:'Unknown fictional detail'})],
  examples: [g.questionAnswerExample({number:3,field:'service_date_source'}),
    g.questionAnswerExample({number:4,field:'closing_date'}),
    g.questionAnswerExample({number:5,field:'recipient_email'})],
  titles: [g.friendlyQuestionTitle({detail:'1 numbered question remains.'}),
    g.friendlyQuestionTitle({detail:'3 numbered questions remain.'})],
  needed: g.beginnerNeededLabels([{field:'service_date'},{field:'service_date'},
    {field:'recipient_email'}]),
  found: g.beginnerFoundLabels({}, {case_number:'FICT-001',
    photo_metadata_date:'2026-09-28', service_place:'Fictional Place'}),
  list: [g.humanList([]),g.humanList(['date']),g.humanList(['date','place']),
    g.humanList(['date','','place','recipient'])],
  needsDate: [g.questionNeedsServiceDate([{field:'service_date_source'}]),
    g.questionNeedsServiceDate([{field:'recipient_email'}])],
  literal: g.shortDateLabel('<fictional date>'),
  today: g.todayIsoDate(),
  workflow: [
    g.projectWorkflowGuidance({status:'ready'}),
    g.projectWorkflowGuidance({status:'ready',preparing:true}),
    g.projectWorkflowGuidance({status:'ready',hasPrepared:true}),
    g.projectWorkflowGuidance({hasPrepared:true,handoffReady:true}),
    g.projectWorkflowGuidance({hasPrepared:true,handoffReady:true,recorded:true}),
    staleProjection,
    g.projectWorkflowGuidance({handoffReady:true,recorded:true})
  ],
  workflowSteps: ['prepare_pdf','review_gmail_draft_args','fix_blocker'].map(g.guidedStepForState),
  guards: [
    g.isWorkflowResponseCurrent(3,3),
    g.isWorkflowResponseCurrent(3,4),
    g.isWorkflowResponseCurrent(3,3,prepared,prepared),
    g.isWorkflowResponseCurrent(3,3,prepared,replacedPrepared),
    g.isWorkflowResponseCurrent(3,3,prepared,null),
    g.isWorkflowResponseCurrent(3,4,prepared,prepared)
  ],
  asyncApplied: applied,
  staleErrorResult,
  currentError,
  projectionPreservesInput: inputBefore === JSON.stringify(input),
  fallback: [
    g.profileFallbackNotice({}, {auto_profile:{mode:'auto_fallback',profile_key:'fictional',confidence:'low',reason:'Only available profile; review its recipient.'},payment_entity:'Fictional Court',recipient_email:'court@example.test'}),
    g.profileFallbackNotice({recipient:'reviewed@example.test',source_evidence:{auto_profile:{mode:'auto_fallback',reason:'No confident match.'}}},{}),
    g.profileFallbackNotice({}, {auto_profile:{mode:'explicit_profile',profile_key:'kept'}}),
    g.profileFallbackNotice({}, {auto_profile:{mode:'auto_fallback',reason:'<fictional evidence>'}})
  ]
}));
"""
        result = subprocess.run(["node", "--input-type=module", "-"], input=script,
                                text=True, capture_output=True, check=True, cwd=ROOT)
        cls.result = json.loads(result.stdout)

    def test_guided_progress_uses_review_states(self):
        self.assertEqual(self.result["stages"], [1, 3, 2, 4, 5, 2])

    def test_numbered_questions_keep_date_confirmation_and_safe_examples(self):
        self.assertEqual(self.result["labels"], ["one-way kilometers", "question 7"])
        self.assertEqual(self.result["examples"][0], "3. yes, use the photo date")
        self.assertEqual(self.result["examples"][1], "4. " + self.result["today"])
        self.assertEqual(self.result["examples"][2], "5. court@example.test")
        self.assertEqual(self.result["titles"], ["Answer 1 question before PDF creation",
                                                "Answer 3 questions before PDF creation"])

    def test_metadata_date_is_presented_as_evidence_without_claiming_service_date(self):
        labels = self.result["found"]
        self.assertIn("case number", labels)
        self.assertIn("service place", labels)
        self.assertNotIn("service date", labels)
        self.assertTrue(any(value.startswith("photo metadata date (") for value in labels))
        self.assertEqual(self.result["needsDate"], [True, False])

    def test_labels_are_deduplicated_and_literals_remain_text(self):
        self.assertEqual(self.result["needed"], ["service date", "recipient email"])
        self.assertEqual(self.result["list"], ["", "date", "date and place",
                                             "date, place, and recipient"])
        self.assertEqual(self.result["literal"], "<fictional date>")

    def test_home_guidance_distinguishes_review_preparation_handoff_and_recording(self):
        values = self.result["workflow"]
        self.assertEqual([value["phase"] for value in values], ["review", "preparing", "prepared", "handoff_ready", "recorded", "stale", "review"])
        self.assertIn("by this review", values[0]["safety"])
        self.assertIn("in progress", values[1]["safety"])
        self.assertIn("created local files", values[2]["safety"])
        self.assertIn("did not create a Gmail draft", values[2]["safety"])
        self.assertIn("copy-ready", values[3]["headline"])
        self.assertIn("did not contact Gmail", values[3]["safety"])
        self.assertIn("recorded locally", values[4]["headline"])
        self.assertIn("has not sent", values[4]["safety"])
        self.assertEqual(self.result["workflowSteps"], [4, 5, 2])

    def test_stale_state_takes_precedence_over_previous_prepared_and_recorded_flags(self):
        stale = self.result["workflow"][5]
        self.assertEqual(stale["actionState"], "fix_blocker")
        self.assertIn("no longer current", stale["safety"])
        self.assertIn("review", stale["headline"])
        self.assertTrue(self.result["projectionPreservesInput"])

    def test_response_guard_checks_revision_and_prepared_snapshot_identity(self):
        self.assertEqual(self.result["guards"], [True, False, True, False, False, False])
        self.assertEqual(self.result["asyncApplied"], ["current reviewed handoff"], "Late preparation and handoff responses must not restore obsolete draft controls.")

    def test_late_errors_are_discarded_but_current_failures_reach_the_handler(self):
        self.assertIsNone(self.result["staleErrorResult"])
        self.assertEqual(self.result["currentError"], "Current synthetic blocker")

    def test_fallback_projection_preserves_the_warning_and_payment_recipient_review(self):
        single, ambiguous, explicit, literal = self.result["fallback"]
        self.assertEqual(single["confidence"], "low")
        self.assertEqual(single["paymentEntity"], "Fictional Court")
        self.assertEqual(single["recipient"], "court@example.test")
        self.assertIn("review its recipient", single["reason"])
        self.assertEqual(ambiguous["profile"], "No profile selected")
        self.assertEqual(ambiguous["paymentEntity"], "Needs an answer")
        self.assertEqual(ambiguous["recipient"], "reviewed@example.test")
        self.assertIsNone(explicit)
        self.assertEqual(literal["reason"], "<fictional evidence>")
