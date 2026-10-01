"""Fictional claim-choice and explicit shared-trip UI state regressions."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

APP_HARNESS = r"""
import fs from 'node:fs';
import vm from 'node:vm';
const elements = new Map();
const element = selector => {
  if (!elements.has(selector)) {
    elements.set(selector,{checked:false,textContent:'',innerHTML:'',disabled:false,
    className:'',dataset:{},classList:{add(){},remove(){},toggle(){},contains(){return false;}},
    setAttribute(){},getAttribute(){return ''},removeAttribute(){},focus(){},scrollIntoView(){},reset(){},
    querySelector(s){return element(s)},querySelectorAll(){return []}});
    Object.defineProperty(elements.get(selector),'value',{get(){return this._value||''},set(value){this._value=String(value??'')}});
  }
  return elements.get(selector);
};
const calls = [];
let holdReview = null;
let rejectCase = '';
let reviewTransform = row => row;
const context = {...g,console,FormData,JSON,Map,Set,Date,window:{},document:{querySelector:element,
  querySelectorAll(){return []},getElementById:id=>element('#'+id),body:{dataset:{}}},fetch:async(url,options)=>{
  if (url==='/api/intake/from-profile') return {ok:true,json:async()=>({intake:{...makeIntake(720),claim_interpreting:false,claim_transport:false},review:{status:'ready'}})};
  if (url!=='/api/review') throw new Error('Unexpected synthetic route: '+url);
  const intake = reviewTransform(JSON.parse(options.body).intake); calls.push(JSON.parse(JSON.stringify(intake)));
  if (holdReview) await holdReview;
  const valid = g.claimMode(intake)!=='neither' && intake.case_number!==rejectCase;
  return {ok:true,json:async()=>({status:valid?'ready':'needs_info',intake,effective_intake:intake,
    questions:valid?[]:[{field:'claim_options',text:'Choose a claim'}],
    next_safe_action:{state:valid?'prepare_pdf':'answer_questions',blocked:!valid},
    review_evidence:{case_number:intake.case_number,attention:{status:valid?'ready':'blocked',flags:[]}}})};
}};
let app = fs.readFileSync('honorarios_app/static/app.js','utf8').replace(/^import \{[\s\S]*?\} from "\.\/review_guidance\.js";/,'');
app = app.slice(0,app.lastIndexOf('\nbindNavigation();'));
app += '\nthis.api={state,adoptUploadedSource,selectSourceCase,refreshSourceClaimReviews,changeSourceTravelChoice,changeRequestClaimMode,addSourceCasesToBatch,clearPreparedArtifacts,renderBatchItemInspector,refreshHomeWorkflow,sourceCaseDetailsChanged,fillFormFromIntake,resetReview,buildIntakeFromProfile,renderMetadataDateActions};';
vm.runInNewContext(app,context);
const a = context.api;
const intake = number => ({case_number:`${number}/26.0TSTXX`,service_date:'2026-10-01',service_place:'Court Test City',
  payment_entity:'Court Test City',recipient_email:'court@example.test',source_sha256:'fictional-source-hash',
  personal_profile_id:'main',transport:{destination:'Test City',km_one_way:41},source_filename:'fictional.jpg'});
const makeIntake = intake;
const upload = numbers => {
  const rows = numbers.map(number=>({candidate_intake:intake(number),review:{status:'ready',questions:[],next_safe_action:{state:'prepare_pdf',blocked:false}}}));
  return {candidate_intake:rows[0].candidate_intake,review:rows[0].review,case_candidates:rows,
    source:{sha256:'fictional-source-hash',source_kind:'photo',filename:'fictional.jpg'}};
};
"""


class ClaimOptionsUiTests(unittest.TestCase):
    def run_js(self, body, app=False):
        module_url = (ROOT / 'honorarios_app/static/review_guidance.js').as_uri()
        script = 'import * as g from ' + json.dumps(module_url) + ';\n'
        script += (APP_HARNESS if app else '') + body
        result = subprocess.run(['node', '--input-type=module', '-'], input=script, text=True,
                                encoding='utf-8', capture_output=True, timeout=20, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_three_explicit_choices_preserve_facts_and_legacy_default(self):
        result = self.run_js("""
const intake={case_number:'710/26.0TSTXX',service_place:'Court Test',transport:{destination:'Test City',km_one_way:41}};
const before=JSON.stringify(intake);
console.log(JSON.stringify({default:g.claimMode(intake),choices:['both','interpreting_only','travel_only'].map(mode=>g.intakeWithClaimMode(intake,mode)),unchanged:before===JSON.stringify(intake)}));
""")
        self.assertEqual(result['default'], 'both')
        self.assertEqual([(row['claim_interpreting'], row['claim_transport']) for row in result['choices']], [(True, True), (True, False), (False, True)])
        self.assertTrue(result['unchanged'])
        for row in result['choices']:
            self.assertEqual(row['transport'], {'destination': 'Test City', 'km_one_way': 41})

    def test_explicit_shared_owner_moves_without_turning_interpreting_on(self):
        result = self.run_js("""
const rows=[710,711,712].map(number=>({candidate_intake:{case_number:`${number}/26.0TSTXX`,source_sha256:'same-source',service_date:'2026-10-01',service_place:'Court Test',personal_profile_id:'main',transport:{destination:'Test City',km_one_way:41}},answers:`answer-${number}`,review:{status:'ready'}}));
rows[0].candidate_intake.claim_interpreting=false;
const before=JSON.stringify(rows);
const first=g.sourceCasesWithTravelChoice(rows,'shared',0,'explicit-visit');
const moved=g.sourceCasesWithTravelChoice(first.candidates,'shared',2,'explicit-visit');
const separate=g.sourceCasesWithTravelChoice(moved.candidates,'separate');
const none=g.sourceCasesWithTravelChoice(moved.candidates,'none');
console.log(JSON.stringify({first:first.candidates,moved:moved.candidates,separate:separate.candidates,none:none.candidates,unchanged:before===JSON.stringify(rows),blocked:g.sourceCaseReadiness(moved.candidates[0]).ready}));
""")
        self.assertEqual([row['candidate_intake']['claim_transport'] for row in result['first']], [True, False, False])
        self.assertEqual([row['candidate_intake']['claim_transport'] for row in result['moved']], [False, False, True])
        self.assertFalse(result['moved'][0]['candidate_intake']['claim_interpreting'])
        self.assertFalse(result['blocked'])
        self.assertEqual({row['candidate_intake']['travel_group_id'] for row in result['moved']}, {'explicit-visit'})
        self.assertTrue(all(row['candidate_intake']['claim_transport'] for row in result['separate']))
        self.assertTrue(all('travel_group_id' not in row['candidate_intake'] for row in result['separate']))
        self.assertTrue(all(not row['candidate_intake']['claim_transport'] for row in result['none']))
        self.assertEqual([row['answers'] for row in result['moved']], ['answer-710', 'answer-711', 'answer-712'])
        self.assertTrue(result['unchanged'])

    def test_conflicting_or_missing_visit_facts_pause_without_dropping_travel(self):
        result = self.run_js("""
const base={source_sha256:'source-one',service_date:'2026-10-01',service_place:'Court Test',personal_profile_id:'main',claim_transport:true,transport:{destination:'Test City'}};
const variants=[{service_date:'2026-10-02'},{service_place:'Police Test'},{source_sha256:'source-two'},{personal_profile_id:'alternate'},{transport:{destination:'Other City'}},{service_date:''},{personal_profile_id:''},{transport:{destination:''}},{transport:{destination:'Test City',origin:'Other origin'}}];
console.log(JSON.stringify(variants.map(change=>{const rows=[{candidate_intake:base},{candidate_intake:{...base,...change}}];const before=JSON.stringify(rows);const result=g.sourceCasesWithTravelChoice(rows,'shared',0,'trip');return {blocked:result.blocked_reason,unchanged:before===JSON.stringify(result.candidates),original:before===JSON.stringify(rows)};})));
""")
        self.assertTrue(all(row['blocked'] and row['unchanged'] and row['original'] for row in result))

    def test_actual_source_defaults_refresh_and_owner_change_preserve_edits_queue_and_answers(self):
        result = self.run_js("""
a.state.batchIntakes=[{...intake(900),source_sha256:'older-source'}];
a.adoptUploadedSource(upload([710,711,712,713,714]));
a.selectSourceCase(0,{persist:false,focus:false});
await a.refreshSourceClaimReviews();
const initial=a.state.sourceCaseCandidates.map(row=>g.claimMode(row.candidate_intake));
a.state.sourceCaseCandidates[2].answers='1. fictional answer';
a.state.sourceCaseCandidates[2].candidate_intake.service_period_label='morning';
a.selectSourceCase(2,{persist:false,focus:false});
a.state.lastPrepared={items:[{draft_payload:'old-payload'}]};
a.state.batchPreflight={status:'ready'};
const reviewed=await a.changeSourceTravelChoice('shared',2);
const invalidated=!a.state.lastPrepared&&!a.state.batchPreflight;
await a.addSourceCasesToBatch();
console.log(JSON.stringify({initial,modes:a.state.sourceCaseCandidates.map(row=>g.claimMode(row.candidate_intake)),answers:a.state.sourceCaseCandidates[2].answers,period:a.state.sourceCaseCandidates[2].candidate_intake.service_period_label,invalidated,reviewed:reviewed.length,calls:calls.length,queue:a.state.batchIntakes,packet:element('#batch-packet-mode').checked}));
""", app=True)
        self.assertEqual(result['initial'], ['both'] + ['interpreting_only'] * 4)
        self.assertEqual(result['modes'], ['interpreting_only', 'interpreting_only', 'both', 'interpreting_only', 'interpreting_only'])
        self.assertEqual(result['answers'], '1. fictional answer')
        self.assertEqual(result['period'], 'morning')
        self.assertTrue(result['invalidated'])
        self.assertEqual(result['reviewed'], 5)
        self.assertEqual(result['calls'], 15)
        self.assertEqual(len(result['queue']), 6)
        self.assertEqual(result['queue'][0]['case_number'], '900/26.0TSTXX')
        self.assertEqual(sum(row.get('claim_transport', True) for row in result['queue'][1:]), 1)
        self.assertFalse(result['packet'])

    def test_transfer_from_travel_only_owner_blocks_neither_and_never_partially_queues(self):
        result = self.run_js("""
a.adoptUploadedSource(upload([710,711]));
a.selectSourceCase(0,{persist:false,focus:false});
await a.refreshSourceClaimReviews();
await a.changeRequestClaimMode('travel_only');
a.selectSourceCase(1,{persist:false,focus:false});
await a.changeRequestClaimMode('both');
const rows=a.state.sourceCaseCandidates.map(row=>({mode:g.claimMode(row.candidate_intake),ready:g.sourceCaseReadiness(row).ready}));
let error='';try{await a.addSourceCasesToBatch();}catch(e){error=e.message;}
a.state.batchIntakes=[a.state.sourceCaseCandidates[0].candidate_intake];
a.state.batchSelectedIndex=0;a.renderBatchItemInspector();
console.log(JSON.stringify({rows,error,queueCount:a.state.batchIntakes.length,inspector:element('#batch-item-inspector-body').innerHTML}));
""", app=True)
        self.assertEqual(result['rows'], [{'mode': 'neither', 'ready': False}, {'mode': 'both', 'ready': True}])
        self.assertIn('Resolve and review every case', result['error'])
        self.assertEqual(result['queueCount'], 1)
        self.assertIn('Not claimed in this request', result['inspector'])
        self.assertNotIn('41 km', result['inspector'])

    def test_stale_claim_review_cannot_restore_old_facts_or_update_queue(self):
        result = self.run_js("""
a.adoptUploadedSource(upload([710,711]));a.selectSourceCase(0,{persist:false,focus:false});await a.refreshSourceClaimReviews();
let release;holdReview=new Promise(resolve=>{release=resolve});
const pending=a.changeSourceTravelChoice('shared',1);
a.clearPreparedArtifacts('fictional edit while review pending');
a.state.sourceCaseCandidates[1].candidate_intake.service_place='Corrected Police Test';
a.state.sourceCaseCandidates[1].needs_review=true;
release();const result=await pending;
console.log(JSON.stringify({discarded:result===null,venue:a.state.sourceCaseCandidates[1].candidate_intake.service_place,dirty:a.state.sourceCaseCandidates[1].needs_review,queue:a.state.batchIntakes.length}));
""", app=True)
        self.assertEqual(result, {'discarded': True, 'venue': 'Corrected Police Test', 'dirty': True, 'queue': 0})

    def test_visit_edit_pauses_existing_group_until_explicit_separate_choice(self):
        result = self.run_js("""
a.adoptUploadedSource(upload([710,711]));a.selectSourceCase(0,{persist:false,focus:false});await a.refreshSourceClaimReviews();
const group=a.state.sourceCaseCandidates[0].candidate_intake.travel_group_id;
element('#service_place').value='Police Other City';
a.sourceCaseDetailsChanged();
const paused={caption:element('#source-travel-caption').textContent,flags:a.state.sourceCaseCandidates.map(row=>row.candidate_intake.claim_transport),markers:a.state.sourceCaseCandidates.map(row=>row.candidate_intake.travel_group_id),dirty:a.state.sourceCaseCandidates.map(row=>row.needs_review)};
await a.changeSourceTravelChoice('separate',0);
console.log(JSON.stringify({group,paused,separate:a.state.sourceCaseCandidates.map(row=>row.candidate_intake),queue:a.state.batchIntakes.length}));
""", app=True)
        self.assertIn('Shared trip paused', result['paused']['caption'])
        self.assertEqual(result['paused']['flags'], [True, False])
        self.assertEqual(result['paused']['markers'], [result['group'], result['group']])
        self.assertEqual(result['paused']['dirty'], [True, True])
        self.assertTrue(all('travel_group_id' not in row for row in result['separate']))
        self.assertTrue(all(row['claim_transport'] for row in result['separate']))
        self.assertEqual(result['separate'][0]['service_place'], 'Police Other City')
        self.assertEqual(result['queue'], 0)

    def test_single_request_choices_and_new_manual_request_use_fresh_reviews(self):
        result = self.run_js("""
a.state.currentIntake=intake(710);a.fillFormFromIntake(a.state.currentIntake);
const modes=[];for(const mode of ['interpreting_only','travel_only','both']){await a.changeRequestClaimMode(mode);modes.push(g.claimMode(a.state.currentIntake));}
const facts=a.state.currentIntake.service_place;
a.state.currentIntake.claim_interpreting=false;
await a.buildIntakeFromProfile({openDrawer:false});
console.log(JSON.stringify({modes,facts,manual:g.claimMode(a.state.currentIntake),calls:calls.map(row=>[row.claim_interpreting,row.claim_transport]),manualLabel:element('#request-claim-mode').value}));
""", app=True)
        self.assertEqual(result['modes'], ['interpreting_only', 'travel_only', 'both'])
        self.assertEqual(result['facts'], 'Court Test City')
        self.assertEqual(result['manual'], 'both')
        self.assertEqual(result['manualLabel'], 'both')
        self.assertEqual(result['calls'], [[True, False], [False, True], [True, True], [True, True]])

    def test_fresh_review_new_blocker_keeps_existing_queue_atomic(self):
        result = self.run_js("""
a.state.batchIntakes=[{...intake(900),source_sha256:'older-source'}];
a.adoptUploadedSource(upload([710,711,712]));a.selectSourceCase(0,{persist:false,focus:false});await a.refreshSourceClaimReviews();
const before=JSON.stringify(a.state.batchIntakes);rejectCase='711/26.0TSTXX';
let message='';try{await a.addSourceCasesToBatch();}catch(e){message=e.message;}
console.log(JSON.stringify({message,unchanged:before===JSON.stringify(a.state.batchIntakes),selected:a.state.sourceCaseSelectedIndex,dirty:a.state.sourceCaseCandidates.map(row=>g.sourceCaseReadiness(row).ready)}));
""", app=True)
        self.assertIn('fresh check', result['message'])
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['selected'], 1)
        self.assertEqual(result['dirty'], [True, False, True])

    def test_corrected_missing_dates_reconcile_saved_shared_owner_before_queue(self):
        result = self.run_js("""
const data=upload([710,711]);data.case_candidates.forEach(row=>{row.candidate_intake.service_date=''});
a.adoptUploadedSource(data);a.selectSourceCase(0,{persist:false,focus:false});
const initial=a.state.sourceCaseCandidates.map(row=>({travel:row.candidate_intake.claim_transport,group:row.candidate_intake.travel_group_id||''}));
a.state.sourceCaseCandidates.forEach(row=>{row.candidate_intake.service_date='2026-10-01'});
a.selectSourceCase(0,{persist:false,focus:false});await a.refreshSourceClaimReviews();await a.addSourceCasesToBatch();
const queued=a.state.batchIntakes.map(row=>({travel:row.claim_transport,group:row.travel_group_id}));
// If a ready row's marker is lost later, Add all applies the chosen policy
// and requires another review; it cannot silently queue ungrouped travel.
delete a.state.sourceCaseCandidates[1].candidate_intake.travel_group_id;
a.selectSourceCase(1,{persist:false,focus:false});const before=JSON.stringify(a.state.batchIntakes);
let message='';try{await a.addSourceCasesToBatch();}catch(error){message=error.message;}
console.log(JSON.stringify({initial,queued,message,unchanged:before===JSON.stringify(a.state.batchIntakes)}));
""", app=True)
        self.assertEqual(result['initial'], [{'travel': True, 'group': ''}, {'travel': True, 'group': ''}])
        self.assertEqual([row['travel'] for row in result['queued']], [True, False])
        self.assertEqual({row['group'] for row in result['queued']}, {'source-trip-fictional-source-hash'})
        self.assertIn('Review all case choices', result['message'])
        self.assertTrue(result['unchanged'])

    def test_reconciliation_preserves_unclaimed_owner_and_excluded_interpreting(self):
        result = self.run_js("""
const data=upload([710,711]);data.case_candidates.forEach(row=>{row.candidate_intake.service_date=''});
a.adoptUploadedSource(data);a.state.sourceTravelChoice.ownerIndex=null;
a.state.sourceCaseCandidates.forEach(row=>{row.candidate_intake.service_date='2026-10-01'});
a.state.sourceCaseCandidates[0].candidate_intake.claim_interpreting=false;
a.selectSourceCase(0,{persist:false,focus:false});await a.refreshSourceClaimReviews();
console.log(JSON.stringify({owner:a.state.sourceTravelChoice.ownerIndex,rows:a.state.sourceCaseCandidates.map(row=>({mode:g.claimMode(row.candidate_intake),travel:row.candidate_intake.claim_transport,interpreting:row.candidate_intake.claim_interpreting,group:row.candidate_intake.travel_group_id,ready:g.sourceCaseReadiness(row).ready}))}));
""", app=True)
        self.assertIsNone(result['owner'])
        self.assertEqual([row['travel'] for row in result['rows']], [False, False])
        self.assertFalse(result['rows'][0]['interpreting'])
        self.assertEqual(result['rows'][0]['mode'], 'neither')
        self.assertFalse(result['rows'][0]['ready'])
        self.assertTrue(all(row['group'] == 'source-trip-fictional-source-hash' for row in result['rows']))

    def test_same_uploaded_source_has_stable_group_distinct_sources_do_not(self):
        result = self.run_js("""
const groups=[];for(const hash of ['source-one','source-one','source-two','']){const data=upload([710,711]);data.case_candidates.forEach(row=>{row.candidate_intake.source_sha256=hash});a.adoptUploadedSource(data);groups.push({id:a.state.sourceTravelChoice.groupId,rows:a.state.sourceCaseCandidates.map(row=>row.candidate_intake.travel_group_id||'')});}
console.log(JSON.stringify(groups));
""", app=True)
        self.assertEqual(result[0]['id'], result[1]['id'])
        self.assertNotEqual(result[0]['id'], result[2]['id'])
        self.assertTrue(all(row == 'source-trip-source-one' for row in result[0]['rows']))
        self.assertEqual(result[3], {'id': '', 'rows': ['', '']})

    def test_fresh_review_cannot_remove_group_marker_and_then_queue_travel(self):
        result = self.run_js("""
a.adoptUploadedSource(upload([710,711]));a.selectSourceCase(0,{persist:false,focus:false});await a.refreshSourceClaimReviews();
reviewTransform=row=>{delete row.travel_group_id;return row};const before=JSON.stringify(a.state.batchIntakes);
let message='';try{await a.addSourceCasesToBatch();}catch(error){message=error.message;}
console.log(JSON.stringify({message,unchanged:before===JSON.stringify(a.state.batchIntakes),ready:a.state.sourceCaseCandidates.map(row=>g.sourceCaseReadiness(row).ready)}));
""", app=True)
        self.assertIn('fresh review changed shared trip details', result['message'])
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['ready'], [False, False])

    def test_travel_only_metadata_date_confirms_attendance_without_inferring_work(self):
        result = self.run_js("""
const questions=[{field:'service_date'}];
console.log(JSON.stringify({travel:a.renderMetadataDateActions({photo_metadata_date:'2026-10-01',claim_interpreting:false,claim_transport:true},questions),both:a.renderMetadataDateActions({photo_metadata_date:'2026-10-01'},questions)}));
""", app=True)
        self.assertIn('attended the visit then', result['travel'])
        self.assertNotIn('interpreting service happened then', result['travel'])
        self.assertIn('interpreting service happened then', result['both'])

    def test_new_source_resets_claim_choice_and_prepared_summary_keeps_immutable_mode(self):
        result = self.run_js("""
a.state.currentIntake={...intake(700),claim_interpreting:false,claim_transport:true};
a.adoptUploadedSource({candidate_intake:{...intake(710),claim_transport:false},review:{status:'ready'}});
const freshMode=g.claimMode(a.state.currentIntake);
const prepared={...intake(900),claim_interpreting:false,claim_transport:true};
a.state.lastReview={intake:a.state.currentIntake,status:'ready'};
a.state.lastPrepared={items:[{...prepared,recipient:prepared.recipient_email,draft_payload:'fictional'}],prepared_review_material:{effective_intakes:[prepared]}};
a.refreshHomeWorkflow();
const home=element('#interpretation-review-home-result').innerHTML;
a.state.batchIntakes=[prepared];a.resetReview();
console.log(JSON.stringify({freshMode,home,resetChoice:element('#request-claim-mode').value,group:a.state.sourceTravelChoice,queue:a.state.batchIntakes.length}));
""", app=True)
        self.assertEqual(result['freshMode'], 'both')
        self.assertIn('Travel only', result['home'])
        self.assertNotIn('Interpreting + travel', result['home'])
        self.assertEqual(result['resetChoice'], 'both')
        self.assertIsNone(result['group'])
        self.assertEqual(result['queue'], 1)

    def test_claim_controls_are_visible_in_normal_review_and_use_safe_owner_labels(self):
        template = (ROOT / 'honorarios_app/templates/index.html').read_text(encoding='utf-8')
        review = template.split('id="interpretation-seed-panel"', 1)[1].split('id="batch-queue-panel"', 1)[0]
        self.assertIn('id="request-claim-mode"', review)
        self.assertIn('id="source-travel-mode"', review)
        self.assertIn('id="source-travel-owner"', review)
        self.assertIn('Travel only requests travel expenses without asking for interpreting fees.', review)
        self.assertIn('Interpreting only requests interpreting fees without travel expenses.', review)
        self.assertNotIn('no interpreting work took place', review)
        self.assertNotIn('covered elsewhere', review)
        result = self.run_js("""
const data=upload([710,711]);data.case_candidates[1].candidate_intake.case_number='<img src=x onerror=alert(1)>';
a.adoptUploadedSource(data);a.selectSourceCase(0,{persist:false,focus:false});
console.log(JSON.stringify({options:element('#source-travel-owner').innerHTML}));
""", app=True)
        self.assertIn('&lt;img', result['options'])
        self.assertNotIn('<img', result['options'])


if __name__ == '__main__':
    unittest.main()
