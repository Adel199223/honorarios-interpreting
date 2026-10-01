"""Saved recipients and immutable prepared email targets, with fictional data only."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
import fs from 'node:fs';import vm from 'node:vm';
const elements=new Map();
const element=selector=>{
  if(!elements.has(selector)){
    elements.set(selector,{id:selector.slice(1),listeners:{},checked:false,disabled:false,textContent:'',innerHTML:'',className:'',dataset:{},
      addEventListener(event,listener){this.listeners[event]=listener;},
      classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return ''},removeAttribute(){},
      focus(){},scrollIntoView(){},reset(){},querySelector(s){return element(s)},querySelectorAll(){return []}});
    Object.defineProperty(elements.get(selector),'value',{get(){return this._value||''},set(v){this._value=String(v??'')}});
  }return elements.get(selector);
};
const calls=[],copied=[];let deferred=null;let responseOverride=null;let responseFailure=null;
const context={...g,console,JSON,Map,Set,Date,window:{},referenceLoads:0,navigator:{clipboard:{writeText:async text=>copied.push(text)}},
  document:{querySelector:element,querySelectorAll(){return []},getElementById:id=>element('#'+id),body:{dataset:{}}},
  fetch:async(url,options)=>{
    const body=options?.body?JSON.parse(options.body):{};calls.push({url,body});if(deferred)await deferred;
    if(responseFailure)return {ok:false,status:409,json:async()=>({detail:responseFailure})};
    let result={};
    if(url==='/api/review')result={status:'needs_info',intake:body.intake,effective_intake:body.intake,questions:[{field:'recipient_email'}],next_safe_action:{state:'answer_questions',blocked:true}};
    else if(url==='/api/gmail/manual-handoff')result={status:'ready',payload_path:body.payload,to:body.payload.includes('beta')?'beta@example.test':'alpha@example.test',copyable_prompt:'prompt:'+body.payload};
    else if(url==='/api/drafts/active-check')result={status:'clear',message:body.intake.case_number};
    else if(url==='/api/gmail/drafts/create')result={status:'created',draft_id:'draft:'+body.payload,message_id:'message:'+body.payload,confirmation:{draft_id:'draft:'+body.payload,to:'selected@example.test'}};
    else if(url==='/api/gmail/drafts/verify')result={status:'verified',draft_id:body.draft_id};
    else if(url==='/api/drafts/record'||url==='/api/drafts/status')result={status:'recorded',draft_id:body.draft_id};
    else throw new Error('Unexpected synthetic route '+url);
    return {ok:true,json:async()=>responseOverride||result};
  }};
const fullApp=fs.readFileSync('honorarios_app/static/app.js','utf8').replace(/^import \{[\s\S]*?\} from "\.\/review_guidance\.js";/,'');
let app=fullApp.slice(0,fullApp.lastIndexOf('\nbindNavigation();'));
const listenerSource=(id,event='click')=>{
  const start=fullApp.indexOf(`$("${id}").addEventListener("${event}",`);
  if(start<0)throw new Error('Missing production event handler '+id);
  return fullApp.slice(start,fullApp.indexOf('\n  });',start)+6);
};
['#check-active-drafts','#create-gmail-api-draft','#record-draft','#record-parsed-prepared-draft'].forEach(id=>{app+='\n'+listenerSource(id);});
app+='\n'+listenerSource('#saved-court-email','change');
const intakeStart=fullApp.indexOf('  const intakeChanged =');
app+='\n'+fullApp.slice(intakeStart,fullApp.indexOf('  $("#source-case-list").addEventListener',intakeStart));
app+='\nloadReference=async()=>{referenceLoads+=1};this.api={state,fillFormFromIntake,mergeFormIntoCurrentIntake,renderSavedCourtEmailOptions,chooseSavedCourtEmail,renderReference,renderPrepared,selectPreparedEmailTarget,preparedRecordTarget,preparedTargetIntake,copyPreparedDraftArgs,buildManualHandoffPacket,autofillRecordFormFromPrepared,currentPreparedReviewFields,recordPreparedDraftFromForm,recordDraft,activeCheck,createGmailApiDraft,renderGmailApiResult,verifyGmailDraft,verifyCreatedGmailDraft,clearPreparedArtifacts,refreshHomeWorkflow};';
vm.runInNewContext(app,context);const a=context.api;
const intake=(n,city)=>({case_number:`${n}/26.0TSTXX`,service_date:'2026-10-01',service_place:'Police '+city,payment_entity:'Court '+city,recipient_email:city.toLowerCase()+'@example.test',source_sha256:city+'-source',personal_profile_id:'main'});
const alpha=intake(710,'Alpha'),beta=intake(711,'Beta');
const prepare=()=>({status:'prepared',items:[alpha,beta].map((row,i)=>({...row,recipient:row.recipient_email,pdf:`/fictional/${i?'beta':'alpha'}.pdf`,draft_payload:`/fictional/${i?'beta':'alpha'}.json`,attachment_count:1,png_preview_urls:[`/fictional/${i?'beta':'alpha'}.png`],gmail_create_draft_args:{to:row.recipient_email,subject:row.case_number,attachment_files:[`/fictional/${i?'beta':'alpha'}.pdf`]}})),prepared_review_material:{effective_intakes:[alpha,beta]},prepared_review:{manifest:'/fictional/prepared.json',prepared_review_token:'fictional-token',review_fingerprint:'fictional-fingerprint',payload_paths:['/fictional/alpha.json','/fictional/beta.json']},next_safe_action:{state:'review_gmail_draft_args',blocked:false}});
"""


class EmailRoutingUiTests(unittest.TestCase):
    def run_js(self, body):
        script='import * as g from '+json.dumps((ROOT/'honorarios_app/static/review_guidance.js').as_uri())+';\n'+HARNESS+body
        result=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=20,cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_saved_picker_matches_filled_email_refreshes_and_escapes_without_rewriting_text(self):
        result=self.run_js("""
a.state.reference={court_emails:[{key:'alpha',name:'Court <Alpha>',email:'alpha@example.test'},{key:'beta',name:'Court Beta',email:'beta@example.test'}]};
a.state.currentIntake=alpha;a.fillFormFromIntake(alpha);const matched=element('#saved-court-email').value;
element('#recipient_email').value='custom@example.test';a.renderSavedCourtEmailOptions();const custom=element('#recipient_email').value;
a.state.reference.court_emails.push({key:'new',email:'new@example.test'});a.renderSavedCourtEmailOptions();
console.log(JSON.stringify({matched,custom,value:element('#saved-court-email').value,options:element('#saved-court-email').innerHTML,payer:a.state.currentIntake.payment_entity,venue:a.state.currentIntake.service_place}));
""")
        self.assertEqual(result['matched'],'alpha@example.test')
        self.assertEqual(result['custom'],'custom@example.test')
        self.assertEqual(result['value'],'')
        self.assertIn('&lt;Alpha&gt;',result['options'])
        self.assertIn('new@example.test',result['options'])
        self.assertEqual(result['payer'],'Court Alpha')
        self.assertEqual(result['venue'],'Police Alpha')

    def test_recipient_selection_changes_only_recipient_clears_aliases_and_reruns_review(self):
        result=self.run_js("""
a.state.reference={court_emails:[{email:'beta@example.test'}]};a.state.currentIntake={...alpha,court_email:'alpha@example.test',court_email_key:'alpha',recipient_override_reason:'old',court_email_override_reason:'old'};a.fillFormFromIntake(a.state.currentIntake);
a.renderPrepared(prepare());await a.chooseSavedCourtEmail('beta@example.test');
console.log(JSON.stringify({intake:a.state.currentIntake,calls,prepared:a.state.lastPrepared,status:a.state.lastReview.status}));
""")
        self.assertEqual(result['intake']['recipient_email'],'beta@example.test')
        self.assertEqual(result['intake']['payment_entity'],'Court Alpha')
        self.assertEqual(result['intake']['service_place'],'Police Alpha')
        for field in ['court_email','court_email_key','recipient_override_reason','court_email_override_reason']:
            self.assertEqual(result['intake'][field],'')
        self.assertIsNone(result['prepared'])
        self.assertEqual([call['url'] for call in result['calls']],['/api/review'])
        self.assertEqual(result['status'],'needs_info')

    def test_same_saved_recipient_selection_clears_stale_hidden_choices_before_review(self):
        result=self.run_js("""
a.state.currentIntake={...alpha,court_email:'beta@example.test',court_email_key:'beta',recipient_override_reason:'old',court_email_override_reason:'old'};a.fillFormFromIntake(a.state.currentIntake);
await a.chooseSavedCourtEmail('alpha@example.test');
console.log(JSON.stringify({intake:calls[0].body.intake,payer:a.state.currentIntake.payment_entity,venue:a.state.currentIntake.service_place}));
""")
        self.assertEqual(result['intake']['recipient_email'],'alpha@example.test')
        for field in ['court_email','court_email_key','recipient_override_reason','court_email_override_reason']:
            self.assertEqual(result['intake'].get(field,''),'')
        self.assertEqual(result['payer'],'Court Alpha')
        self.assertEqual(result['venue'],'Police Alpha')

    def test_picker_input_then_change_preserves_choice_and_reviews_recipient_mismatch(self):
        result=self.run_js("""
a.state.reference={court_emails:[{email:'alpha@example.test'},{email:'beta@example.test'}]};a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);a.renderPrepared(prepare());
const picker=element('#saved-court-email'),form=element('#intake-form');picker.value='beta@example.test';
form.listeners.input({target:picker});const afterInput=picker.value;
await picker.listeners.change({target:picker});form.listeners.change({target:picker});
console.log(JSON.stringify({afterInput,selected:picker.value,recipient:element('#recipient_email').value,reviewed:calls[0].body.intake,payer:a.state.currentIntake.payment_entity,venue:a.state.currentIntake.service_place,prepared:a.state.lastPrepared,status:a.state.lastReview.status}));
""")
        self.assertEqual(result['afterInput'],'beta@example.test')
        self.assertEqual(result['selected'],'beta@example.test')
        self.assertEqual(result['recipient'],'beta@example.test')
        self.assertEqual(result['reviewed']['recipient_email'],'beta@example.test')
        self.assertEqual(result['reviewed']['payment_entity'],'Court Alpha')
        self.assertEqual(result['payer'],'Court Alpha')
        self.assertEqual(result['venue'],'Police Alpha')
        self.assertIsNone(result['prepared'])
        self.assertEqual(result['status'],'needs_info')

    def test_selected_target_uses_exact_snapshot_args_attachment_preview_and_home_facts(self):
        result=self.run_js("""
a.state.currentIntake={...alpha,case_number:'999/26.0TSTXX'};const prepared=prepare();const before=JSON.stringify(prepared);a.renderPrepared(prepared);a.selectPreparedEmailTarget(1);await a.copyPreparedDraftArgs();
console.log(JSON.stringify({target:a.preparedRecordTarget(),snapshot:a.preparedTargetIntake(),copied:JSON.parse(copied[0]),summary:element('#prepared-email-target-summary').textContent,preview:element('#prepared-email-target-preview').innerHTML,home:element('#interpretation-review-home-result').innerHTML,unchanged:before===JSON.stringify(prepared),source:a.state.currentIntake.case_number,calls:calls.length}));
""")
        self.assertEqual(result['target']['draft_payload'],'/fictional/beta.json')
        self.assertEqual(result['snapshot']['case_number'],'711/26.0TSTXX')
        self.assertEqual(result['copied']['to'],'beta@example.test')
        self.assertEqual(result['copied']['attachment_files'],['/fictional/beta.pdf'])
        self.assertIn('beta@example.test',result['summary'])
        self.assertIn('beta.pdf',result['summary'])
        self.assertIn('/fictional/beta.png',result['preview'])
        self.assertIn('Court Beta',result['home'])
        self.assertNotIn('Court Alpha',result['home'])
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['source'],'999/26.0TSTXX')
        self.assertEqual(result['calls'],0)

    def test_target_switch_clears_handoff_ids_checklist_correction_and_retains_pdfs(self):
        result=self.run_js("""
const prepared=prepare();a.renderPrepared(prepared);await a.buildManualHandoffPacket();a.state.locallyRecordedPayload='/fictional/alpha.json';a.state.gmailCreateCompletedPayload='/fictional/alpha.json';
['record_draft_id','record_message_id','record_thread_id','record_supersedes','record_sent_date','gmail-response-raw','correction_reason'].forEach(id=>element('#'+id).value='old');element('#gmail_handoff_reviewed').checked=true;
a.selectPreparedEmailTarget(1);
console.log(JSON.stringify({preparedSame:a.state.lastPrepared===prepared,items:a.state.lastPrepared.items.length,handoff:a.state.lastManualHandoff,ids:['record_draft_id','record_message_id','record_thread_id','record_supersedes','record_sent_date','gmail-response-raw','correction_reason'].map(id=>element('#'+id).value),reviewed:element('#gmail_handoff_reviewed').checked,payload:element('#record_payload').value,recorded:a.state.locallyRecordedPayload,completed:a.state.gmailCreateCompletedPayload}));
""")
        self.assertTrue(result['preparedSame'])
        self.assertEqual(result['items'],2)
        self.assertIsNone(result['handoff'])
        self.assertEqual(result['ids'],['']*7)
        self.assertFalse(result['reviewed'])
        self.assertEqual(result['payload'],'/fictional/beta.json')
        self.assertEqual(result['recorded'],'')
        self.assertEqual(result['completed'],'')

    def test_typed_recipient_clear_does_not_restore_hidden_old_contact(self):
        result=self.run_js("""
a.state.currentIntake={...alpha,court_email:'alpha@example.test',court_email_key:'alpha'};a.fillFormFromIntake(a.state.currentIntake);element('#recipient_email').value='';a.mergeFormIntoCurrentIntake();
console.log(JSON.stringify({recipient:a.state.currentIntake.recipient_email,email:a.state.currentIntake.court_email,key:a.state.currentIntake.court_email_key,payer:a.state.currentIntake.payment_entity}));
""")
        self.assertEqual(result,{'recipient':'','email':'','key':'','payer':'Court Alpha'})

    def test_record_form_rejects_payload_from_other_prepared_target(self):
        result=self.run_js("""
a.renderPrepared(prepare());a.selectPreparedEmailTarget(1);element('#record_payload').value='/fictional/alpha.json';let error='';try{await a.recordPreparedDraftFromForm();}catch(e){error=e.message;}
console.log(JSON.stringify({error,calls:calls.length}));
""")
        self.assertIn('Select the prepared email',result['error'])
        self.assertEqual(result['calls'],0)

    def test_handoff_record_api_and_lifecycle_are_bound_to_selected_payload_and_intake(self):
        result=self.run_js("""
a.state.currentIntake=alpha;a.renderPrepared(prepare());a.selectPreparedEmailTarget(1);await a.buildManualHandoffPacket();await a.activeCheck();
element('#record_draft_id').value='fictional-draft';element('#record_message_id').value='fictional-message';element('#gmail_handoff_reviewed').checked=true;await a.recordPreparedDraftFromForm();
await a.createGmailApiDraft();
console.log(JSON.stringify({calls,recorded:a.state.locallyRecordedPayload,ids:element('#record_draft_id').value,betaFields:a.currentPreparedReviewFields('/fictional/beta.json'),alphaFields:a.currentPreparedReviewFields('/fictional/alpha.json')}));
""")
        by_route={call['url']:call['body'] for call in result['calls']}
        for route in ['/api/gmail/manual-handoff','/api/drafts/record','/api/gmail/drafts/create']:
            self.assertEqual(by_route[route]['payload'],'/fictional/beta.json')
            self.assertEqual(by_route[route]['prepared_review_token'],'fictional-token')
        self.assertEqual(by_route['/api/drafts/active-check']['intake']['case_number'],'711/26.0TSTXX')
        self.assertEqual(result['recorded'],'/fictional/beta.json')
        self.assertEqual(result['ids'],'draft:/fictional/beta.json')
        self.assertEqual(result['alphaFields'],{})

    def test_late_handoff_and_verification_results_cannot_repopulate_switched_target(self):
        result=self.run_js("""
a.renderPrepared(prepare());let release;deferred=new Promise(resolve=>release=resolve);const old=a.buildManualHandoffPacket();a.selectPreparedEmailTarget(1);release();const handoff=await old;
element('#record_draft_id').value='beta-draft';deferred=new Promise(resolve=>release=resolve);const verification=a.verifyGmailDraft();a.selectPreparedEmailTarget(0);release();const verify=await verification;
console.log(JSON.stringify({discarded:handoff===null&&verify===null,handoff:a.state.lastManualHandoff,confirmation:a.state.lastGmailCreateConfirmation,ids:element('#record_draft_id').value}));
""")
        self.assertEqual(result,{'discarded':True,'handoff':None,'confirmation':None,'ids':''})

    def test_late_api_create_reports_prior_effect_without_applying_old_ids(self):
        result=self.run_js("""
a.renderPrepared(prepare());element('#gmail_handoff_reviewed').checked=true;let release;deferred=new Promise(resolve=>release=resolve);const pending=a.createGmailApiDraft();a.selectPreparedEmailTarget(1);release();const completed=await pending;
console.log(JSON.stringify({completed:completed.status,ids:element('#record_draft_id').value,payload:element('#record_payload').value,recorded:a.state.locallyRecordedPayload,inFlight:a.state.gmailCreateInFlight,alert:element('#alert').textContent,referenceLoads:context.referenceLoads}));
""")
        self.assertEqual(result['completed'],'created')
        self.assertEqual(result['ids'],'')
        self.assertEqual(result['payload'],'/fictional/beta.json')
        self.assertEqual(result['recorded'],'')
        self.assertFalse(result['inFlight'])
        self.assertIn('earlier selected email was created',result['alert'])
        self.assertEqual(result['referenceLoads'],1)

    def test_active_check_click_discards_late_response_without_blocking_new_target(self):
        result=self.run_js("""
a.renderPrepared(prepare());let release;deferred=new Promise(resolve=>release=resolve);const pending=element('#check-active-drafts').listeners.click();a.selectPreparedEmailTarget(1);
element('#status-pill').textContent='new-target';element('#alert').textContent='new-target-alert';release();await pending;
console.log(JSON.stringify({status:element('#status-pill').textContent,alert:element('#alert').textContent,payload:element('#record_payload').value,caseChecked:calls[0].body.intake.case_number}));
""")
        self.assertEqual(result,{'status':'new-target','alert':'new-target-alert','payload':'/fictional/beta.json','caseChecked':'710/26.0TSTXX'})

    def test_create_click_reports_prior_target_http_failure_without_blocking_new_target(self):
        result=self.run_js("""
a.renderPrepared(prepare());element('#gmail_handoff_reviewed').checked=true;let release;deferred=new Promise(resolve=>release=resolve);const pending=element('#create-gmail-api-draft').listeners.click();a.selectPreparedEmailTarget(1);
element('#status-pill').textContent='new-target';element('#gmail-api-result').innerHTML='new-target-panel';responseFailure='Earlier Alpha request is already drafted';release();await pending;
console.log(JSON.stringify({status:element('#status-pill').textContent,panel:element('#gmail-api-result').innerHTML,alert:element('#alert').textContent,payload:element('#record_payload').value,createdPayload:calls[0].body.payload,inFlight:a.state.gmailCreateInFlight}));
""")
        self.assertEqual(result['status'],'new-target')
        self.assertEqual(result['panel'],'new-target-panel')
        self.assertIn('earlier selected email request failed',result['alert'])
        self.assertIn('Earlier Alpha request is already drafted',result['alert'])
        self.assertEqual(result['payload'],'/fictional/beta.json')
        self.assertEqual(result['createdPayload'],'/fictional/alpha.json')
        self.assertFalse(result['inFlight'])

    def test_create_click_current_target_http_failure_still_blocks(self):
        result=self.run_js("""
a.renderPrepared(prepare());element('#gmail_handoff_reviewed').checked=true;responseFailure='Selected request is already drafted';await element('#create-gmail-api-draft').listeners.click();
console.log(JSON.stringify({status:element('#status-pill').textContent,panel:element('#gmail-api-result').innerHTML,alert:element('#alert').textContent}));
""")
        self.assertEqual(result['status'],'blocked')
        self.assertIn('Selected request is already drafted',result['panel'])
        self.assertIn('No Gmail draft creation was confirmed',result['panel'])
        self.assertNotIn('Created as a Gmail draft only',result['panel'])
        self.assertEqual(result['alert'],'Selected request is already drafted')

    def test_gmail_result_confirms_creation_only_after_created_response_with_draft_id(self):
        result=self.run_js("""
const cases=[{status:'blocked',message:'Google OAuth token exchange failed: invalid_grant - Bad Request'}, {status:'error',message:'Creation response could not be read'}, {status:'info',message:'Creating Gmail draft...'}, {status:'created'}, {status:'created',confirmation:{draft_id:'fictional-draft',message_id:'fictional-message'}}];
const panels=cases.map(data=>{a.renderGmailApiResult(data);return element('#gmail-api-result').innerHTML;});console.log(JSON.stringify({panels,calls:calls.length}));
""")
        for panel in result['panels'][:4]:
            self.assertNotIn('Created as a Gmail draft only',panel)
        self.assertIn('invalid_grant',result['panels'][0])
        self.assertIn('No Gmail draft creation was confirmed',result['panels'][0])
        self.assertIn('if the request may have reached it',result['panels'][1])
        self.assertIn('Created as a Gmail draft only',result['panels'][4])
        self.assertIn('fictional-draft',result['panels'][4])
        self.assertEqual(result['calls'],0)

    def test_record_clicks_report_prior_http_failure_without_blocking_new_target(self):
        for control,route in [('#record-draft','/api/drafts/status'),('#record-parsed-prepared-draft','/api/drafts/record')]:
            with self.subTest(control=control):
                result=self.run_js("""
a.renderPrepared(prepare());element('#record_draft_id').value='alpha-draft';element('#record_message_id').value='alpha-message';element('#gmail_handoff_reviewed').checked=true;element('#gmail-response-raw').value=JSON.stringify({draft_id:'alpha-draft',message_id:'alpha-message'});
let release;deferred=new Promise(resolve=>release=resolve);const pending=element(CONTROL).listeners.click();a.selectPreparedEmailTarget(1);element('#status-pill').textContent='new-target';responseFailure='Earlier Alpha record was rejected';release();await pending;
console.log(JSON.stringify({status:element('#status-pill').textContent,alert:element('#alert').textContent,payload:element('#record_payload').value,recorded:a.state.locallyRecordedPayload,call:calls[0]}));
""".replace('CONTROL',json.dumps(control)))
                self.assertEqual(result['status'],'new-target')
                self.assertIn('earlier selected draft recording request failed',result['alert'])
                self.assertEqual(result['payload'],'/fictional/beta.json')
                self.assertEqual(result['recorded'],'')
                self.assertEqual(result['call']['url'],route)
                self.assertEqual(result['call']['body']['payload'],'/fictional/alpha.json')

    def test_record_click_current_target_http_failure_still_blocks(self):
        result=self.run_js("""
a.renderPrepared(prepare());element('#record_draft_id').value='alpha-draft';responseFailure='Selected record was rejected';await element('#record-draft').listeners.click();
console.log(JSON.stringify({status:element('#status-pill').textContent,alert:element('#alert').textContent}));
""")
        self.assertEqual(result,{'status':'blocked','alert':'Selected record was rejected'})

    def test_parsed_record_click_acknowledges_late_success_without_applying_old_ids(self):
        result=self.run_js("""
a.renderPrepared(prepare());element('#gmail_handoff_reviewed').checked=true;element('#gmail-response-raw').value=JSON.stringify({draft_id:'alpha-draft',message_id:'alpha-message'});
let release;deferred=new Promise(resolve=>release=resolve);const pending=element('#record-parsed-prepared-draft').listeners.click();a.selectPreparedEmailTarget(1);element('#status-pill').textContent='new-target';release();await pending;
console.log(JSON.stringify({status:element('#status-pill').textContent,alert:element('#alert').textContent,payload:element('#record_payload').value,ids:element('#record_draft_id').value,recorded:a.state.locallyRecordedPayload,referenceLoads:context.referenceLoads}));
""")
        self.assertEqual(result['status'],'new-target')
        self.assertIn('earlier draft was recorded locally',result['alert'])
        self.assertEqual(result['payload'],'/fictional/beta.json')
        self.assertEqual(result['ids'],'')
        self.assertEqual(result['recorded'],'')
        self.assertEqual(result['referenceLoads'],1)

    def test_packet_is_one_target_new_preparation_resets_selection_and_source_change_clears_it(self):
        result=self.run_js("""
a.renderPrepared(prepare());a.selectPreparedEmailTarget(1);const packet={...prepare(),packet:{packet_mode:true,case_number:'Packet',recipient:'packet@example.test',pdf:'/fictional/packet.pdf',draft_payload:'/fictional/packet.json',gmail_create_draft_args:{to:'packet@example.test',attachment_files:['/fictional/packet.pdf']}}};
a.renderPrepared(packet);const packetTarget=a.preparedRecordTarget().draft_payload;const disabled=element('#prepared-email-target').disabled;const rejected=!a.selectPreparedEmailTarget(1);a.renderPrepared(prepare());const reset=a.preparedRecordTarget().draft_payload;a.clearPreparedArtifacts('fictional source change');
console.log(JSON.stringify({packetTarget,disabled,rejected,reset,cleared:a.preparedRecordTarget()===null,args:element('#prepared-email-target-args').textContent}));
""")
        self.assertEqual(result,{'packetTarget':'/fictional/packet.json','disabled':True,'rejected':True,'reset':'/fictional/alpha.json','cleared':True,'args':''})


if __name__=='__main__':
    unittest.main()
