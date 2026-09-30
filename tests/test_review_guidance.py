"""Behavior checks for browser guidance, using fictional inputs and no browser state."""
from pathlib import Path
import json
import subprocess
import unittest

from honorarios_app.services import apply_answer_to_intake
from scripts.generate_pdf import get_service_date_value

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
const originalCapture = {field:'photo_metadata_date',value:'2026-09-28',source:'image_metadata',confidence:'high',reason:'EXIF capture date'};
const originalReview = {intake:{source_sha256:'fictional-source-hash',photo_metadata_date:'2026-09-28'},source_evidence:{field_evidence:[originalCapture]}};
const nextReview = {status:'ready',intake:{source_sha256:'fictional-source-hash',photo_metadata_date:'2026-09-28'},review_evidence:{field_evidence:[{...originalCapture,source:'openai_ocr',confidence:'medium'}],attention:{status:'ready',flags:[{code:'date_conflict_resolved'}]}}};
const originInputsBefore = JSON.stringify([originalReview,nextReview]);
const retainedCapture = g.retainCaptureDateOrigin(nextReview,originalReview);
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
  ],
  facts: g.beginnerReviewFacts({source_evidence:{field_evidence:[
    {field:'case_number',value:'123/26.0SYNTH',source:'openai_ocr',confidence:'medium'},
    {field:'payment_entity',value:'Fictional Court',source:'service_profile',confidence:'medium'},
    {field:'service_place',value:'Fictional Office',source:'openai_ocr',confidence:'low'},
    {field:'recipient_email',value:'court@example.test',source:'visible_email',confidence:'high'}
  ]}}, {case_number:'123/26.0SYNTH',photo_metadata_date:'2026-09-28',payment_entity:'Fictional Court',service_place:'Fictional Office',recipient_email:'court@example.test'}),
  origins: [
    g.reviewFactOrigin('service_date','2026-09-28',{}, {service_date_source:'photo_metadata_user_confirmed'}),
    g.reviewFactOrigin('case_number','123/26.0SYNTH',{source_evidence:{field_evidence:[{field:'case_number',value:'old value',source:'deterministic_text'}]}}),
    g.reviewFactOrigin('case_number','123/26.0SYNTH',{source_evidence:{field_evidence:[{field:'case_number',value:'123/26.0SYNTH',source:'openai_ocr',confidence:'high'}]}}),
    g.reviewFactOrigin('payment_entity',''),
    g.reviewFactOrigin('service_date','2026-09-28',{source_evidence:{field_evidence:[{field:'service_date',value:'2026-09-28',source:'openai_ocr',status:'conflicts_with_metadata'}]}}),
    g.reviewFactOrigin('recipient_email','typed@example.test')
  ],
  photoDateFacts: ['openai_ocr','image_metadata'].map(source => g.beginnerReviewFacts({source_evidence:{field_evidence:[
    {field:'photo_metadata_date',value:'2026-09-28',source,confidence:'medium'}
  ]}}, {photo_metadata_date:'2026-09-28'})[1]),
  savedPhotoOrigins: [
    g.reviewFactOrigin('service_date','2026-09-28',{}, {service_date_source:'photo_metadata',photo_defaults_applied:{service_date:'2026-09-28'}}),
    g.reviewFactOrigin('payment_entity','Fictional Court',{}, {photo_defaults_applied:{payment_entity:'Fictional Court'}}),
    g.reviewFactOrigin('recipient_email','court@example.test',{}, {photo_defaults_applied:{recipient_email:'court@example.test'}}),
    g.reviewFactOrigin('service_date','2026-09-29',{}, {service_date_source:'user_confirmed',photo_defaults_applied:{service_date:'2026-09-28'}}),
    g.reviewFactOrigin('payment_entity','Different Court',{}, {photo_defaults_applied:{payment_entity:'Fictional Court'}})
  ],
  savedPhotoFallback: g.profileFallbackNotice({}, {auto_profile:{mode:'auto_fallback',reason:'Confirm the missing payer.'},payment_entity:'Fictional Court',photo_defaults_applied:{routing_status:'applied',payment_entity:'Fictional Court',photo_city:'Fictional City'}}),
  retainedCapture,
  differentCapture: g.retainCaptureDateOrigin({...nextReview,intake:{...nextReview.intake,photo_metadata_date:'2026-09-29'}},originalReview),
  differentSource: g.retainCaptureDateOrigin({...nextReview,intake:{...nextReview.intake,source_sha256:'different-source-hash'}},originalReview),
  unverifiedCapture: g.retainCaptureDateOrigin(nextReview,{...originalReview,source_evidence:{field_evidence:[{...originalCapture,source:'openai_ocr',confidence:'medium'}]}}),
  originsPreserveInputs: originInputsBefore === JSON.stringify([originalReview,nextReview])
}));
"""
        result = subprocess.run(["node", "--input-type=module", "-"], input=script,
                                text=True, encoding="utf-8", capture_output=True, check=True, cwd=ROOT)
        cls.result = json.loads(result.stdout)

    def test_guided_progress_uses_review_states(self):
        self.assertEqual(self.result["stages"], [1, 3, 2, 4, 5, 2])

    def test_saved_photo_defaults_are_not_labeled_as_document_proof_or_individual_confirmation(self):
        origins = self.result['savedPhotoOrigins']
        self.assertTrue(all(item['kind'] == 'default' for item in origins[:3]))
        self.assertIn('photo-date default', origins[0]['label'])
        self.assertIn('photo-city court default', origins[1]['label'])
        self.assertEqual(origins[3]['kind'], 'manual')
        self.assertNotEqual(origins[4]['kind'], 'default')

    def test_photo_default_fallback_explains_actual_selection(self):
        reason = self.result['savedPhotoFallback']['reason']
        self.assertIn('Fictional City', reason)
        self.assertIn('saved photo-city default', reason)
        self.assertNotIn('missing payer', reason)

    def test_numbered_questions_keep_date_confirmation_and_safe_examples(self):
        self.assertEqual(self.result["labels"], ["one-way kilometers", "question 7"])
        self.assertEqual(self.result["examples"][0], "3. document")
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

    def test_date_confirmation_example_is_accepted_without_switching_to_capture_date(self):
        intake = {"service_date": "2026-09-26", "photo_metadata_date": "2026-09-28", "service_date_source": "document_text"}
        answer = self.result["examples"][0].split(".", 1)[1].strip()
        apply_answer_to_intake(intake, "service_date_source", answer)
        self.assertEqual(intake["service_date_source"], "document_text_user_confirmed")
        self.assertEqual(get_service_date_value(intake), "2026-09-26")
        self.assertEqual(intake["photo_metadata_date"], "2026-09-28")

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

    def test_key_fact_summary_covers_payment_and_preserves_unverified_ai_origins(self):
        facts = self.result["facts"]
        self.assertEqual([fact["field"] for fact in facts], ["case_number", "service_date", "payment_entity", "service_place", "recipient_email"])
        self.assertEqual([fact["origin"]["kind"] for fact in facts], ["ai", "metadata", "default", "ai", "source"])
        self.assertEqual(facts[0]["origin"]["label"], "AI-read · check source")
        self.assertEqual(facts[3]["origin"]["label"], "AI suggestion · check source")
        self.assertEqual(facts[1]["value"], "2026-09-28")
        self.assertIn("needs confirmation", facts[1]["origin"]["label"])

    def test_summary_does_not_call_unknown_corrected_or_old_ai_values_confirmed(self):
        manual, changed, old_ai, missing, conflict, typed = self.result["origins"]
        self.assertEqual(manual["kind"], "manual")
        self.assertEqual(changed, {"kind": "unknown", "label": "Check this value"})
        self.assertEqual(typed, changed, "Absence of AI provenance is not proof of manual confirmation.")
        self.assertEqual(old_ai, {"kind": "ai", "label": "AI-read · check source"})
        self.assertEqual(missing["kind"], "missing")
        self.assertEqual(conflict["kind"], "conflict")

    def test_photo_date_candidate_retains_ai_origin_until_service_date_confirmation(self):
        ai_date, metadata_date = self.result["photoDateFacts"]
        self.assertEqual(ai_date["origin"], {"kind": "ai", "label": "AI-read photo date · needs confirmation"})
        self.assertEqual(metadata_date["origin"], {"kind": "metadata", "label": "Photo date · needs confirmation"})
        self.assertEqual(ai_date["value"], metadata_date["value"])

    def test_manual_rerun_retains_known_capture_origin_without_restoring_stale_review(self):
        result = self.result["retainedCapture"]
        self.assertEqual(result["review_evidence"]["field_evidence"][0]["source"], "image_metadata")
        self.assertEqual(result["review_evidence"]["attention"], {"status": "ready", "flags": [{"code": "date_conflict_resolved"}]})
        self.assertEqual(result["status"], "ready")
        self.assertTrue(self.result["originsPreserveInputs"])

    def test_changed_source_date_or_unverified_origin_does_not_inherit_old_metadata(self):
        for key in ("differentCapture", "differentSource", "unverifiedCapture"):
            with self.subTest(key=key):
                fields = self.result[key]["review_evidence"]["field_evidence"]
                self.assertEqual(fields[0]["source"], "openai_ocr")
                self.assertEqual(fields[0]["confidence"], "medium")


class MultiCaseReviewGuidanceTests(unittest.TestCase):
    def run_guidance(self, body):
        module_url = (ROOT / 'honorarios_app/static/review_guidance.js').as_uri()
        script = 'import * as g from ' + json.dumps(module_url) + ';\n' + body
        result = subprocess.run(['node', '--input-type=module', '-e', script],
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_upload_case_list_retains_unreadable_rows_and_clones_source_state(self):
        result = self.run_guidance("""
const data = {source_evidence:{filename:'fictional-five.jpg'},case_candidates:[
  {candidate_intake:{case_number:'710/26.0TSTXX',source_sha256:'shared'},review:{status:'ready',questions:[]}},
  {candidate_intake:{case_number:'',raw_case_number:'711/??.0TSTXX',source_sha256:'shared'},review:{status:'needs_info',questions:[{field:'case_number'}]}}
]};
const before = JSON.stringify(data);
const candidates = g.sourceCaseCandidatesFromUpload(data);
candidates[0].candidate_intake.case_number = 'changed locally';
console.log(JSON.stringify({count:candidates.length,raw:candidates[1].candidate_intake.raw_case_number,
  canonical:candidates[1].candidate_intake.case_number,evidence:candidates[1].review.source_evidence,
  unchanged:JSON.stringify(data)===before,legacy:g.sourceCaseCandidatesFromUpload({candidate_intake:{case_number:'single'}}),
  singleton:g.sourceCaseCandidatesFromUpload({case_candidates:[data.case_candidates[0]]})}));
""")
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['raw'], '711/??.0TSTXX')
        self.assertEqual(result['canonical'], '')
        self.assertEqual(result['evidence']['filename'], 'fictional-five.jpg')
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['legacy'], [])
        self.assertEqual(result['singleton'], [])

    def test_bulk_case_readiness_requires_current_complete_normal_review(self):
        result = self.run_guidance("""
const ready = {candidate_intake:{case_number:'710/26.0TSTXX'},review:{status:'ready',questions:[]}};
const variants = [ready,{...ready,needs_review:true},
  {...ready,review:{status:'ready',questions:[{field:'recipient_email'}]}},
  {...ready,review:{status:'duplicate',questions:[]}},
  {...ready,review:{status:'ready',questions:[],next_safe_action:{blocked:true}}},
  {...ready,candidate_intake:{case_number:''}}];
const before = JSON.stringify(variants);
console.log(JSON.stringify({states:variants.map(g.sourceCaseReadiness),unchanged:JSON.stringify(variants)===before}));
""")
        self.assertEqual([state['ready'] for state in result['states']], [True, False, False, False, False, False])
        self.assertEqual(result['states'][1]['status'], 'needs_review')
        self.assertTrue(result['unchanged'])

    def test_bulk_refresh_does_not_queue_a_case_whose_recipient_was_cleared(self):
        result = self.run_guidance("""
const candidates = [710,711,712,713,714].map(number => ({
  candidate_intake:{case_number:`${number}/26.0TSTXX`,recipient_email:number===711?'':'court@example.test'},
  review:{status:'ready',questions:[],source_evidence:{filename:'fictional-five.jpg'}},needs_review:true}));
const before = JSON.stringify(candidates);
const calls = [];
const refreshed = await g.reviewSourceCaseCandidates(candidates, async intake => {
  calls.push(intake.case_number);
  return {status:intake.recipient_email?'ready':'needs_info',
    questions:intake.recipient_email?[]:[{field:'recipient_email'}],
    effective_intake:{...intake,service_date:'2026-09-26'}};
});
console.log(JSON.stringify({calls,states:refreshed.map(g.sourceCaseReadiness),
  cleared:refreshed[1].candidate_intake.recipient_email,effective:refreshed[0].candidate_intake.service_date,
  evidence:refreshed[1].review.source_evidence,unchanged:JSON.stringify(candidates)===before}));
""")
        self.assertEqual(len(result['calls']), 5)
        self.assertEqual([row['ready'] for row in result['states']], [True, False, True, True, True])
        self.assertEqual(result['cleared'], '')
        self.assertEqual(result['effective'], '2026-09-26')
        self.assertEqual(result['evidence']['filename'], 'fictional-five.jpg')
        self.assertTrue(result['unchanged'])

    def test_bulk_refresh_discards_stale_results_and_stale_errors(self):
        result = self.run_guidance("""
const candidates = [710,711].map(number => ({candidate_intake:{case_number:`${number}/26.0TSTXX`},review:{status:'ready'}}));
let current = true, calls = 0;
const stale = await g.reviewSourceCaseCandidates(candidates, async intake => {
  calls += 1; current = false; return {status:'ready',intake};
}, () => current);
current = true;
const staleError = await g.reviewSourceCaseCandidates(candidates, async () => {
  current = false; throw new Error('obsolete synthetic error');
}, () => current);
let currentError = '';
try { await g.reviewSourceCaseCandidates(candidates, async () => {throw new Error('current synthetic blocker');}); }
catch (error) {currentError = error.message;}
console.log(JSON.stringify({stale,staleError,calls,currentError}));
""")
        self.assertIsNone(result['stale'])
        self.assertIsNone(result['staleError'])
        self.assertEqual(result['calls'], 1)
        self.assertEqual(result['currentError'], 'current synthetic blocker')

    def test_browser_queue_identity_matches_normalized_backend_request_identity(self):
        result = self.run_guidance("""
const first = {case_number:'00710 / 26.0tstxx',service_date:' 2026-09-26 ',service_period_label:' Manhã   Inicial '};
const same = {case_number:'710/26.0TSTXX',service_date:'2026-09-26',service_period_label:'manhã inicial'};
const other = {...same,case_number:'711/26.0TSTXX'};
console.log(JSON.stringify([first,same,other].map(g.browserRequestIdentityKey)));
""")
        self.assertEqual(result[0], result[1])
        self.assertNotEqual(result[1], result[2])

    def test_venue_default_label_stops_claiming_a_manual_or_cleared_venue(self):
        result = self.run_guidance("""
const intake = {photo_defaults_applied:{service_place:'Tribunal de Capture City'}};
console.log(JSON.stringify(['Tribunal de Capture City','Esquadra de Manual City',''].map(value =>
  g.reviewFactOrigin('service_place',value,{},intake))));
""")
        self.assertEqual(result[0], {'kind': 'default', 'label': 'Your photo-city court venue default · editable'})
        self.assertNotEqual(result[1]['kind'], 'default')
        self.assertEqual(result[2]['kind'], 'missing')
