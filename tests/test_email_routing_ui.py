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
      classList:{add(){},remove(){},toggle(name,value){this.values??={};this.values[name]=value??!this.values[name];},contains(){return false}},setAttribute(){},getAttribute(){return ''},removeAttribute(){},
      focus(){context.document.activeElement=this;},showModal(){this.open=true;this.openCount=(this.openCount||0)+1;},close(){this.open=false;},scrollIntoView(){},reset(){},querySelector(s){return element(s)},querySelectorAll(){return []}});
    Object.defineProperty(elements.get(selector),'value',{get(){return this._value||''},set(v){this._value=String(v??'')}});
  }return elements.get(selector);
};
const calls=[],copied=[];let deferred=null;let responseOverride=null;let responseFailure=null;let routeOverrides={};let deferredRoute='';
const context={...g,console,FormData,JSON,Map,Set,Date,window:{},referenceLoads:0,navigator:{clipboard:{writeText:async text=>copied.push(text)}},
  document:{querySelector:element,querySelectorAll(){return []},getElementById:id=>element('#'+id),body:{dataset:{}}},
  fetch:async(url,options)=>{
    const body=options?.body?JSON.parse(options.body):{};calls.push({url,body});if(deferred&&(!deferredRoute||deferredRoute===url))await deferred;
    if(responseFailure)return {ok:false,status:409,json:async()=>({detail:responseFailure})};
    let result={};
    if(url==='/api/review')result={status:'needs_info',intake:body.intake,effective_intake:body.intake,questions:[{field:'recipient_email'}],next_safe_action:{state:'answer_questions',blocked:true}};
    else if(url==='/api/gmail/manual-handoff')result={status:'ready',payload_path:body.payload,to:body.payload.includes('beta')?'beta@example.test':'alpha@example.test',copyable_prompt:'prompt:'+body.payload};
    else if(url==='/api/drafts/active-check')result=body.underlying_requests?{status:'clear',message:'All photo email requests checked',member_checks:body.underlying_requests.map(row=>({...row,status:'clear',message:'No active draft'}))}:{status:'clear',message:body.intake.case_number};
    else if(url==='/api/prepare/preflight')result={status:'ready',preflight_review:{token:'fictional-preflight'},email_grouping:body.email_grouping,next_safe_action:{state:'prepare_pdf'}};
    else if(url==='/api/prepare')result=groupedPrepare();
    else if(url==='/api/gmail/drafts/create')result={status:'created',draft_id:'draft:'+body.payload,message_id:'message:'+body.payload,confirmation:{draft_id:'draft:'+body.payload,to:'selected@example.test'}};
    else if(url==='/api/gmail/drafts/verify')result={status:'verified',draft_id:body.draft_id};
    else if(url==='/api/drafts/record'||url==='/api/drafts/status')result={status:'recorded',draft_id:body.draft_id};
    else throw new Error('Unexpected synthetic route '+url);
    return {ok:true,json:async()=>routeOverrides[url]?(typeof routeOverrides[url]==='function'?routeOverrides[url](body):routeOverrides[url]):responseOverride||result};
  }};
const fullApp=fs.readFileSync('honorarios_app/static/app.js','utf8').replace(/^import \{[\s\S]*?\} from "\.\/review_guidance\.js";/,'');
let app=fullApp.slice(0,fullApp.lastIndexOf('\nbindNavigation();'));
const listenerSource=(id,event='click')=>{
  const start=fullApp.indexOf(`$("${id}").addEventListener("${event}",`);
  if(start<0)throw new Error('Missing production event handler '+id);
  const firstLine=fullApp.slice(start).split('\n')[0];if(firstLine.trim().endsWith(';'))return firstLine;
  return fullApp.slice(start,fullApp.indexOf('\n  });',start)+6);
};
['#check-active-drafts','#create-gmail-api-draft','#record-draft','#record-parsed-prepared-draft','#prepare-source-email-replacement'].forEach(id=>{app+='\n'+listenerSource(id);});
app+='\n'+listenerSource('#saved-court-email','change');
app+='\n'+listenerSource('#sent-duplicate-stop')+'\n'+listenerSource('#sent-duplicate-review')+'\n'+listenerSource('#sent-duplicate-dialog','cancel');
app+='\n'+listenerSource('#build-profile');
app+='\n'+listenerSource('#pp_add_distance')+'\n'+listenerSource('#personal-profile-form','submit');
app+='\n'+listenerSource('#preflight-batch-intakes');
app+='\n'+listenerSource('#batch-email-grouping','change')+'\n'+listenerSource('#prepared-email-member','change');
const intakeStart=fullApp.indexOf('  const intakeChanged =');
app+='\n'+fullApp.slice(intakeStart,fullApp.indexOf('  $("#source-case-list").addEventListener',intakeStart));
app+='\nloadReference=async()=>{referenceLoads+=1};this.api={uploadSource,uploadSupportingAttachments,buildIntakeFromProfile,updateHomeReviewCard,state,fillFormFromIntake,mergeFormIntoCurrentIntake,renderSavedCourtEmailOptions,chooseSavedCourtEmail,renderReference,renderPrepared,selectPreparedEmailTarget,selectPreparedEmailMember,preparedRecordTarget,preparedTargetIntake,preparedTargetIntakes,copyPreparedDraftArgs,buildManualHandoffPacket,autofillRecordFormFromPrepared,currentPreparedReviewFields,recordPreparedDraftFromForm,recordDraft,activeCheck,createGmailApiDraft,renderGmailApiResult,verifyGmailDraft,verifyCreatedGmailDraft,clearPreparedArtifacts,refreshHomeWorkflow,batchPreflightSignature,currentBatchEmailGrouping,preflightBatchIntakes,prepareBatchIntakes,prepareIntake,prepareSourceEmailReplacement,canPrepareSourceEmailReplacement};';
app+='\nthis.api.recoverGmailAttempt=recoverGmailAttempt;this.api.renderGmailStatus=renderGmailStatus;this.api.renderHistoryDraftActionResult=renderHistoryDraftActionResult;';
app+='\nObject.assign(this.api,{applyReview,reviewIntake,resolveSentDuplicateDecision,renderSourceCaseList,syncActionGates,syncManualEntryGate,setServerConnected,setServerDisconnected});';
app+='\nObject.assign(this.api,{importGooglePhotosPickerSelection,recoverLocalSourceFile,openPersonalProfileDrawer,closePersonalProfileDrawer,saveCurrentPersonalProfile,renderDraftLifecycle,renderHistoryRecords});';
vm.runInNewContext(app,context);const a=context.api;
const intake=(n,city)=>({case_number:`${n}/26.0TSTXX`,service_date:'2026-10-01',service_place:'Police '+city,payment_entity:'Court '+city,recipient_email:city.toLowerCase()+'@example.test',source_sha256:city+'-source',personal_profile_id:'main'});
const alpha=intake(710,'Alpha'),beta=intake(711,'Beta');
const sentReview=(row=alpha,status='sent')=>({status:'duplicate',intake:row,questions:[],message:'Previously sent request',
 duplicate:{case_number:row.case_number,service_date:row.service_date,service_period_label:row.service_period_label||'',...(status===null?{}:{status}),sent_date:'2026-10-02',recipient:'<court@example.test>'},
 next_safe_action:{state:'stop_duplicate_sent',blocked:true},send_allowed:false});
const prepare=()=>({status:'prepared',items:[alpha,beta].map((row,i)=>({...row,recipient:row.recipient_email,pdf:`/fictional/${i?'beta':'alpha'}.pdf`,draft_payload:`/fictional/${i?'beta':'alpha'}.json`,attachment_count:1,png_preview_urls:[`/fictional/${i?'beta':'alpha'}.png`],gmail_create_draft_args:{to:row.recipient_email,subject:row.case_number,attachment_files:[`/fictional/${i?'beta':'alpha'}.pdf`]}})),prepared_review_material:{effective_intakes:[alpha,beta]},prepared_review:{manifest:'/fictional/prepared.json',prepared_review_token:'fictional-token',review_fingerprint:'fictional-fingerprint',payload_paths:['/fictional/alpha.json','/fictional/beta.json']},next_safe_action:{state:'review_gmail_draft_args',blocked:false}});
const photoRows=()=>[alpha,...Array.from({length:5},(_,index)=>({...beta,case_number:`${711+index}/26.0TSTXX`,claim_interpreting:true,claim_transport:index===0,travel_group_id:'photo-trip-beta'}))];
const groupedPrepare=()=>{
 const rows=photoRows(),items=rows.map((row,index)=>({...row,recipient:row.recipient_email,pdf:`/fictional/request-${index}.pdf`,draft_payload:`/fictional/request-${index}.json`,png_preview_urls:[`/fictional/request-${index}.png`],attachment_count:1}));
 const email_groups=[[0],[1,2,3,4,5]].map((member_indices,index)=>({group_id:index?'photo-beta':'photo-alpha',source_sha256:rows[member_indices[0]].source_sha256,recipient:rows[member_indices[0]].recipient_email,member_indices,underlying_requests:member_indices.map(itemIndex=>items[itemIndex]),child_payload_paths:member_indices.map(itemIndex=>items[itemIndex].draft_payload),attachment_files:member_indices.map(itemIndex=>items[itemIndex].pdf),draft_payload:`/fictional/group-${index}.json`,payload_path:`/fictional/group-${index}.json`,attachment_count:member_indices.length,gmail_create_draft_args:{to:rows[member_indices[0]].recipient_email,subject:`${member_indices.length} requests`,body:'Individual PDFs attached',attachment_files:member_indices.map(itemIndex=>items[itemIndex].pdf)}}));
 return {status:'prepared',email_grouping:'source',items,email_groups,prepared_review_material:{effective_intakes:rows},prepared_review:{manifest:'/fictional/grouped-prepared.json',prepared_review_token:'fictional-group-token',review_fingerprint:'fictional-group-fingerprint',payload_paths:email_groups.map(group=>group.draft_payload)},next_safe_action:{state:'review_gmail_draft_args',blocked:false}};
};
"""


class EmailRoutingUiTests(unittest.TestCase):
    def run_js(self, body):
        script='import * as g from '+json.dumps((ROOT/'honorarios_app/static/review_guidance.js').as_uri())+';\n'+HARNESS+body
        result=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=20,cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_source_recovery_guard_and_busy_controls_cover_post_upload_review(self):
        result=self.run_js("""
a.state.reference={service_profiles:{example_interpreting:{}}};a.setServerConnected();
element('#source-upload-form button[type=submit]').textContent='Review source';
let releaseReview,reviewStarted;const started=new Promise(resolve=>reviewStarted=resolve);const gate=new Promise(resolve=>releaseReview=resolve);let uploads=0,reviews=0;
context.fetch=async(url,options)=>{
 if(url==='/api/sources/upload'){uploads++;return {ok:true,json:async()=>({candidate_intake:{...alpha},source:{sha256:alpha.source_sha256,source_kind:'photo',filename:'fictional.png'}})};}
 if(url==='/api/review'){reviews++;reviewStarted();await gate;return {ok:true,json:async()=>({status:'ready',intake:JSON.parse(options.body).intake,questions:[],next_safe_action:{state:'prepare_pdf'}})};}
 throw new Error('Unexpected route '+url);
};
const file={name:'fictional.png',size:10,lastModified:1,type:'image/png'};
const first=a.uploadSource('photo',{file});await started;
a.syncActionGates();const selectors=['#source-upload-form button[type=submit]','#source-file','#choose-camera-source','#choose-other-source','#build-profile'];
const busy=selectors.every(s=>element(s).disabled),label=element(selectors[0]).textContent;
const repeated=await a.uploadSource('photo',{file});let manualError='';try{await a.buildIntakeFromProfile()}catch(error){manualError=error.message;}
const beforeRelease=uploads;releaseReview();await first;
console.log(JSON.stringify({busy,label,repeated,manualError,beforeRelease,uploads,reviews,cleared:a.state.sourceRecoveryKeys.size===0,reenabled:selectors.every(s=>!element(s).disabled),restoredLabel:element(selectors[0]).textContent}));
""")
        self.assertTrue(result['busy'])
        self.assertIn('Reviewing',result['label'])
        self.assertIsNone(result['repeated'])
        self.assertIn('Wait for the source review',result['manualError'])
        self.assertEqual((result['beforeRelease'],result['uploads'],result['reviews']),(1,1,1))
        self.assertTrue(result['cleared'])
        self.assertTrue(result['reenabled'])
        self.assertEqual(result['restoredLabel'],'Review source')

    def test_drop_paste_and_new_file_identity_cannot_bypass_active_source_recovery(self):
        result=self.run_js("""
let release;const gate=new Promise(resolve=>release=resolve);let uploads=0;
context.fetch=async()=>{uploads++;await gate;return {ok:false,status:503,json:async()=>({message:'fictional failure'})}};
const file={name:'fictional.png',size:10,lastModified:1,type:'image/png'};
const first=a.recoverLocalSourceFile(file).catch(()=>null);const initialStatus=element('#source-drop-status').textContent;
const changedTimestamp=await a.uploadSource('photo',{file:{...file,lastModified:2}});
const differentDropped=await a.recoverLocalSourceFile({...file,name:'different.png',lastModified:3});
element('#google-photos-session-id').value='new-picker-session';const picker=await a.importGooglePhotosPickerSelection();
const beforeRelease=uploads,keys=a.state.sourceRecoveryKeys.size,statusUnchanged=element('#source-drop-status').textContent===initialStatus;
a.clearPreparedArtifacts('new source/reset');a.state.currentIntake={...beta};release();await first;
console.log(JSON.stringify({uploads,beforeRelease,keys,changedTimestamp,differentDropped,picker,statusUnchanged,current:a.state.currentIntake.case_number,cleared:a.state.sourceRecoveryKeys.size===0}));
""")
        self.assertEqual((result['uploads'],result['beforeRelease'],result['keys']),(1,1,1))
        for key in ['changedTimestamp','differentDropped','picker']:
            self.assertIsNone(result[key],key)
        self.assertTrue(result['statusUnchanged'])
        self.assertTrue(result['cleared'])
        self.assertEqual(result['current'],'711/26.0TSTXX')

    def test_source_guard_survives_form_edit_reset_and_failure_then_allows_retry(self):
        result=self.run_js("""
a.state.reference={service_profiles:{example_interpreting:{}}};a.setServerConnected();
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);
let release;const gate=new Promise(resolve=>release=resolve);let uploads=0;
context.fetch=async()=>{uploads++;await gate;return {ok:false,status:503,json:async()=>({message:'fictional source failure'})}};
const file={name:'fictional.png',size:10,lastModified:1,type:'image/png'};
const first=a.uploadSource('photo',{file});const repeated=await a.uploadSource('photo',{file});
element('#intake-form').listeners.input({target:{id:'service_place'}});
const afterEdit=await a.uploadSource('photo',{file});a.clearPreparedArtifacts('reset');a.state.currentIntake={...beta};
const afterReset=await a.uploadSource('photo',{file});const beforeRelease=uploads;release();const stale=await first;
let retryError='';try{await a.uploadSource('photo',{file})}catch(error){retryError=error.message;}
a.state.workspaceDraft.runtimeChanged=true;let setupError='';try{await a.uploadSource('photo',{file})}catch(error){setupError=error.message;}
const runtimeDisabled=element('#source-upload-form button[type=submit]').disabled;a.state.workspaceDraft.runtimeChanged=false;a.setServerConnected();
console.log(JSON.stringify({beforeRelease,uploads,repeated,afterEdit,afterReset,stale,retryError,setupError,runtimeDisabled,current:a.state.currentIntake.case_number,cleared:a.state.sourceRecoveryKeys.size===0,pending:a.state.sourceUploadPending,enabled:!element('#source-upload-form button[type=submit]').disabled}));
""")
        self.assertEqual(result['beforeRelease'],1)
        self.assertEqual(result['uploads'],2)
        for key in ['repeated','afterEdit','afterReset','stale','pending']:
            self.assertIsNone(result[key],key)
        self.assertEqual(result['retryError'],'fictional source failure')
        self.assertIn('workspace changed',result['setupError'])
        self.assertEqual(result['current'],'711/26.0TSTXX')
        for key in ['runtimeDisabled','cleared','enabled']:
            self.assertTrue(result[key],key)

    def test_google_picker_import_guard_covers_followup_review_without_second_import(self):
        result=self.run_js("""
element('#google-photos-session-id').value='fictional-session';let release,started;
const gate=new Promise(resolve=>release=resolve),reviewStarted=new Promise(resolve=>started=resolve);let imports=0;
context.fetch=async(url,options)=>{
 if(url==='/api/google-photos/picker/import'){imports++;return {ok:true,json:async()=>({candidate_intake:{...alpha},source:{sha256:alpha.source_sha256}})};}
 if(url==='/api/review'){started();await gate;return {ok:true,json:async()=>({status:'ready',intake:JSON.parse(options.body).intake,next_safe_action:{state:'prepare_pdf'}})};}
 throw new Error('Unexpected '+url);
};
const first=a.importGooglePhotosPickerSelection();await reviewStarted;const repeated=await a.importGooglePhotosPickerSelection();release();await first;
console.log(JSON.stringify({imports,repeated,cleared:a.state.sourceRecoveryKeys.size===0}));
""")
        self.assertEqual(result['imports'],1)
        self.assertIsNone(result['repeated'])
        self.assertTrue(result['cleared'])

    def test_profile_distance_errors_are_local_and_blank_cannot_be_saved_as_zero(self):
        result=self.run_js("""
a.openPersonalProfileDrawer({id:'fictional-profile',travel_distances_by_city:{'Original City':12}});
const failures=[];for(const value of ['-10','','   ','not-a-number']){
 element('#pp_distance_city').value='New City';element('#pp_distance_km').value=value;element('#pp_add_distance').listeners.click();
 failures.push({message:element('#personal-profile-drawer-alert').textContent,visible:!element('#personal-profile-drawer-alert').className.includes('hidden'),unchanged:JSON.stringify(a.state.currentPersonalProfile.travel_distances_by_city)==='{"Original City":12}'});
}
element('#pp_distance_km').value='0';element('#pp_add_distance').listeners.click();
const distances=a.state.currentPersonalProfile.travel_distances_by_city,success=element('#personal-profile-drawer-alert').textContent;
element('#pp_distance_city').value='unfinished';a.openPersonalProfileDrawer({id:'other-profile',travel_distances_by_city:{}});
console.log(JSON.stringify({failures,distances,success,calls,cleared:element('#personal-profile-drawer-alert').textContent===''&&element('#pp_distance_city').value===''}));
""")
        for row in result['failures']:
            self.assertIn('valid one-way distance',row['message'])
            self.assertTrue(row['visible'])
            self.assertTrue(row['unchanged'])
        self.assertEqual(result['distances'],{'Original City':12,'New City':0})
        self.assertIn('Save profile to keep this change',result['success'])
        self.assertTrue(result['cleared'])
        self.assertEqual(result['calls'],[])
        page=(ROOT/'honorarios_app/templates/index.html').read_text(encoding='utf-8')
        for label in ['personal-profile-alert','personal-profile-drawer-alert']:
            self.assertIn(f'id="{label}" class="result-card hidden" role="status" aria-live="polite"',page)

    def test_profile_save_error_and_success_remain_visible_on_profiles(self):
        result=self.run_js("""
a.state.reference={};a.openPersonalProfileDrawer({id:'fictional-profile',travel_distances_by_city:{}});
let callsToSave=0;context.fetch=async()=>{callsToSave++;return {ok:false,status:400,json:async()=>({detail:'Enter a valid applicant name'})}};
await element('#personal-profile-form').listeners.submit({preventDefault(){}});
const error=element('#personal-profile-drawer-alert').textContent;
context.fetch=async()=>{callsToSave++;return {ok:true,json:async()=>({message:'Fictional profile saved.',profiles:{profiles:[],primary_profile_id:''}})}};
await element('#personal-profile-form').listeners.submit({preventDefault(){}});
console.log(JSON.stringify({error,callsToSave,message:element('#personal-profile-alert').textContent,visible:!element('#personal-profile-alert').className.includes('hidden'),loads:context.referenceLoads}));
""")
        self.assertEqual(result['error'],'Enter a valid applicant name')
        self.assertEqual(result['message'],'Fictional profile saved.')
        self.assertTrue(result['visible'])
        self.assertEqual(result['callsToSave'],2)
        self.assertEqual(result['loads'],1)

    def test_invalid_advanced_distances_stop_before_save_and_valid_empty_object_clears(self):
        result=self.run_js("""
a.state.reference={};a.openPersonalProfileDrawer({id:'fictional-profile',travel_distances_by_city:{'Original City':12}});
let saveCalls=0,payload;context.fetch=async(_url,options)=>{saveCalls++;payload=JSON.parse(options.body);return {ok:true,json:async()=>({message:'Saved.',profiles:{profiles:[]}})}};
const failures=[];
for(const raw of ['', '{bad', '[]', 'null', '12', '{"City":-1}', '{"City":null}', '{"City":""}', '{"City":"Infinity"}', '{"":12}']){
 element('#pp_distances_json').value=raw;await element('#personal-profile-form').listeners.submit({preventDefault(){}});
 failures.push({message:element('#personal-profile-drawer-alert').textContent,unchanged:a.state.currentPersonalProfile.travel_distances_by_city['Original City']===12,inputKept:element('#pp_distances_json').value===raw});
}
const beforeValid=saveCalls;element('#pp_distances_json').value='{}';await element('#personal-profile-form').listeners.submit({preventDefault(){}});
console.log(JSON.stringify({failures,beforeValid,saveCalls,distances:payload.profile.travel_distances_by_city}));
""")
        for row in result['failures']:
            self.assertIn('Advanced distance data',row['message'])
            self.assertTrue(row['unchanged'])
            self.assertTrue(row['inputKept'])
        self.assertEqual(result['beforeValid'],0)
        self.assertEqual(result['saveCalls'],1)
        self.assertEqual(result['distances'],{})

    def test_paper_submission_duplicate_words_are_distinct_and_keep_creation_blocked(self):
        result=self.run_js("""
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);
const paper=sentReview();paper.duplicate={case_number:alpha.case_number,service_date:alpha.service_date,status:'sent',submission_channel:'paper',submission_evidence:'user_confirmed'};paper.message='Already submitted on paper.';
a.applyReview(paper);const title=element('#sent-duplicate-title').textContent,explanation=element('#sent-duplicate-explanation').textContent,details=element('#sent-duplicate-details').textContent;
element('#sent-duplicate-stop').listeners.click();const stopped=element('#alert').textContent,summary=element('#interpretation-review-home-result').innerHTML;
a.applyReview(paper);element('#sent-duplicate-review').listeners.click();const continued=element('#alert').textContent;
a.renderDraftLifecycle({status:'sent_duplicate',duplicate_records:[paper.duplicate],message:'Already submitted on paper.',replacement_allowed:false});
const lifecycle=element('#draft-lifecycle-body').innerHTML,lifecycleChip=element('#draft-lifecycle-chip').textContent;
a.state.reference={duplicates:[paper.duplicate],draft_log:[]};a.renderHistoryRecords();const history=element('#duplicate-list').innerHTML;
const blocked=element('#prepare-intake').disabled&&element('#create-gmail-api-draft').disabled;
a.applyReview(sentReview());const emailTitle=element('#sent-duplicate-title').textContent,emailDetails=element('#sent-duplicate-details').textContent;
console.log(JSON.stringify({title,explanation,details,stopped,summary,continued,lifecycle,lifecycleChip,history,blocked,emailTitle,emailDetails,calls}));
""")
        self.assertEqual(result['title'],'This fee request was already submitted on paper')
        self.assertIn('A paper submission',result['explanation'])
        self.assertNotIn('Sent on',result['details'])
        for key in ['stopped','summary','continued','lifecycle','lifecycleChip','history']:
            self.assertIn('submitted on paper',result[key],key)
        self.assertNotIn('Recorded sent details',result['summary'])
        self.assertTrue(result['blocked'])
        self.assertEqual(result['emailTitle'],'This fee request was already sent')
        self.assertIn('Sent on: 2026-10-02',result['emailDetails'])
        self.assertEqual(result['calls'],[])

    def test_source_cases_distinguish_paper_and_email_completed_requests(self):
        result=self.run_js("""
const paper=sentReview(alpha);paper.duplicate.submission_channel='paper';paper.duplicate.submission_evidence='user_confirmed';delete paper.duplicate.sent_date;
a.state.sourceCaseCandidates=[{candidate_intake:{...alpha},review:paper,needs_review:false},{candidate_intake:{...beta},review:sentReview(beta),needs_review:false}];
a.renderSourceCaseList();const mixed=element('#source-case-list').innerHTML,mixedSummary=element('#source-case-summary').textContent;
a.state.sourceCaseCandidates[1].review.duplicate.submission_channel='paper';a.state.sourceCaseCandidates[1].review.duplicate.submission_evidence='user_confirmed';a.renderSourceCaseList();
console.log(JSON.stringify({mixed,mixedSummary,allPaper:element('#source-case-summary').textContent,paperRows:element('#source-case-list').innerHTML,calls}));
""")
        self.assertIn('Already submitted on paper',result['mixed'])
        self.assertIn('Already sent',result['mixed'])
        self.assertIn('already submitted.',result['mixedSummary'])
        self.assertIn('already submitted on paper.',result['allPaper'])
        self.assertEqual(result['paperRows'].count('Already submitted on paper'),2)
        self.assertEqual(result['calls'],[])

    def test_paper_wording_requires_confirmed_completed_evidence_on_raw_history_too(self):
        result=self.run_js("""
const variants=[{submission_evidence:undefined},{submission_evidence:'unverified'},
 {status:'drafted'},{status:'trashed'},{submission_channel:'other'}];const results=[];
for(const changes of variants){
 const review=sentReview();review.duplicate={...review.duplicate,submission_channel:'paper',submission_evidence:'user_confirmed',...changes};
 a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);a.applyReview(review);
 a.renderDraftLifecycle({status:'blocked',duplicate_records:[review.duplicate],message:'Existing record',replacement_allowed:false});
 a.state.reference={duplicates:[review.duplicate],draft_log:[]};a.renderHistoryRecords();
 a.state.sourceCaseCandidates=[{candidate_intake:{...alpha},review,needs_review:false},{candidate_intake:{...beta},review:sentReview(beta),needs_review:false}];a.renderSourceCaseList();
 results.push([element('#interpretation-review-home-result').innerHTML,element('#draft-lifecycle-body').innerHTML,
   element('#draft-lifecycle-chip').textContent,element('#duplicate-list').innerHTML,element('#source-case-list').innerHTML,element('#source-case-summary').textContent]);
}
console.log(JSON.stringify({results,calls}));
""")
        for surfaces in result['results']:
            for rendered in surfaces:
                self.assertNotIn('submitted on paper',rendered)
        self.assertEqual(result['calls'],[])

    def test_sent_warning_no_is_default_and_preserves_siblings_queue_and_saved_work(self):
        result=self.run_js("""
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);a.state.batchIntakes=[{...beta}];
a.state.workspaceDraft.pending={snapshot:{saved:'keep me'}};
a.state.sourceCaseCandidates=[{candidate_intake:{...alpha},review:sentReview(),needs_review:false},{candidate_intake:{...beta},review:{status:'ready'},answers:'2. keep',needs_review:false}];
a.state.sourceCaseSelectedIndex=0;
a.applyReview(sentReview());const open=element('#sent-duplicate-dialog').open,focus=context.document.activeElement.id,details=element('#sent-duplicate-details').textContent;
const before=JSON.stringify({queue:a.state.batchIntakes,cases:a.state.sourceCaseCandidates,pending:a.state.workspaceDraft.pending,current:a.state.currentIntake});
element('#sent-duplicate-stop').listeners.click();
console.log(JSON.stringify({open,focus,details,html:element('#sent-duplicate-details').innerHTML,closed:!element('#sent-duplicate-dialog').open,
 same:before===JSON.stringify({queue:a.state.batchIntakes,cases:a.state.sourceCaseCandidates,pending:a.state.workspaceDraft.pending,current:a.state.currentIntake}),
 status:a.state.lastReview.status,drawer:context.document.body.dataset.interpretationReviewDrawer,alert:element('#alert').textContent,
 banner:element('#interpretation-review-home-result').innerHTML,calls}));
""")
        self.assertTrue(result['open'])
        self.assertEqual(result['focus'],'sent-duplicate-stop')
        self.assertIn('710/26.0TSTXX',result['details'])
        self.assertIn('Service date 2026-10-01',result['details'])
        self.assertIn('Sent on: 2026-10-02',result['details'])
        self.assertIn('<court@example.test>',result['details'])
        self.assertEqual(result['html'],'')
        self.assertTrue(result['closed'])
        self.assertTrue(result['same'])
        self.assertEqual(result['status'],'duplicate')
        self.assertEqual(result['drawer'],'closed')
        self.assertIn('Stopped: this fee request was already sent',result['alert'])
        self.assertIn('Stopped: this fee request was already sent',result['banner'])
        self.assertEqual(result['calls'],[])
        page=(ROOT/'honorarios_app/templates/index.html').read_text(encoding='utf-8')
        self.assertIn('aria-labelledby="sent-duplicate-title"',page)
        self.assertIn('id="sent-duplicate-stop" autofocus>No — stop',page)
        self.assertIn('Do you want to continue reviewing this request?',page)

    def test_manual_entry_waits_for_profiles_and_blank_form_uses_loaded_default(self):
        result=self.run_js("""
a.state.currentIntake={...alpha};a.state.sourceFileNeedsReview=true;const original=a.state.currentIntake;const originalRevision=a.state.workflowRevision;
a.syncManualEntryGate();const initialDisabled=element('#build-profile').disabled;let earlyError='';
try{await a.buildIntakeFromProfile();}catch(error){earlyError=error.message;}
await element('#build-profile').listeners.click();
const untouched=a.state.currentIntake===original&&a.state.workflowRevision===originalRevision&&a.state.sourceFileNeedsReview;
a.setServerConnected();const stillDisabled=element('#build-profile').disabled;
a.state.reference={service_profiles:{court_mp_generic:{}}};a.syncManualEntryGate();const ready=!element('#build-profile').disabled;
a.setServerDisconnected(new Error('offline'));const offlineDisabled=element('#build-profile').disabled;
await element('#build-profile').listeners.click();const offlineUntouched=a.state.currentIntake===original&&a.state.workflowRevision===originalRevision;
a.setServerConnected();const reconnected=!element('#build-profile').disabled;
a.state.workspaceDraft.runtimeChanged=true;a.syncManualEntryGate();const runtimeDisabled=element('#build-profile').disabled;
await element('#build-profile').listeners.click();let runtimeError='';try{await a.buildIntakeFromProfile();}catch(error){runtimeError=error.message;}
const runtimeUntouched=a.state.currentIntake===original&&a.state.workflowRevision===originalRevision&&a.state.sourceFileNeedsReview;
a.state.workspaceDraft.runtimeChanged=false;a.state.sourceFileNeedsReview=false;a.state.currentIntake=null;const sent=[];context.fetch=async(url,options)=>{const body=JSON.parse(options.body);sent.push({url,body});return {ok:true,json:async()=>url==='/api/intake/from-profile'?{intake:alpha}:{status:'needs_info',intake:alpha,questions:[{field:'service_date'}],next_safe_action:{state:'answer_questions',blocked:true}}}};
await a.buildIntakeFromProfile({openDrawer:false});
console.log(JSON.stringify({initialDisabled,earlyError,untouched,stillDisabled,ready,offlineDisabled,offlineUntouched,reconnected,runtimeDisabled,runtimeUntouched,runtimeError,sent}));
""")
        for key in ['initialDisabled','untouched','stillDisabled','ready','offlineDisabled','offlineUntouched','reconnected','runtimeDisabled','runtimeUntouched']:
            self.assertTrue(result[key],key)
        self.assertIn('Saved profiles are not ready',result['earlyError'])
        self.assertIn('workspace changed',result['runtimeError'])
        self.assertEqual([row['url'] for row in result['sent']],['/api/intake/from-profile','/api/review'])
        self.assertEqual(result['sent'][0]['body'],{'profile':'court_mp_generic'})
        page=(ROOT/'honorarios_app/templates/index.html').read_text(encoding='utf-8')
        self.assertIn('id="build-profile" disabled',page)

    def test_sent_summary_uses_history_not_current_form_and_survives_passive_refresh(self):
        result=self.run_js("""
const results=[];
for(const status of ['sent',null]){
 const current={...alpha,payment_entity:'Unreviewed payer',service_place:'Unreviewed station',recipient_email:'wrong@example.test',claim_interpreting:false,claim_transport:true};
 a.state.currentIntake=current;a.fillFormFromIntake(current);
 const review={...sentReview(current,status),recipient:'wrong-footer@example.test',auto_profile:{confidence:'low',profile_key:'generic'}};
 review.duplicate={...review.duplicate,service_period_label:'Morning',draft_id:'historical-id',recipient_email:'recorded@example.test'};
 a.applyReview(review);const before=JSON.stringify(a.state.currentIntake);element('#sent-duplicate-stop').listeners.click();
 const stopped=element('#interpretation-review-home-result').innerHTML;a.refreshHomeWorkflow();
 results.push({status,stopped,refreshed:element('#interpretation-review-home-result').innerHTML,
 unchanged:before===JSON.stringify(a.state.currentIntake),claimHidden:element('#request-claim-card').classList.values.hidden,open:element('#sent-duplicate-dialog').open});
}
console.log(JSON.stringify({results,calls}));
""")
        for row in result['results']:
            self.assertTrue(row['unchanged'])
            self.assertTrue(row['claimHidden'])
            self.assertFalse(row['open'])
            for html in [row['stopped'],row['refreshed']]:
                for expected in ['Already sent','No further answers are needed','Stopped: this fee request was already sent','710/26.0TSTXX','2026-10-01','2026-10-02','Morning','recorded@example.test']:
                    self.assertIn(expected,html)
                for absent in ['Needs answer','What I still need','data-review-correct-field','profile-fallback-notice','AI-read','Request includes','Unreviewed','wrong@example.test','wrong-footer@example.test','Existing draft:']:
                    self.assertNotIn(absent,html)
        self.assertEqual(result['calls'],[])

    def test_sent_summary_omits_unknown_history_fields_and_renders_explicit_ones_only(self):
        result=self.run_js("""
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);const record={case_number:alpha.case_number,service_date:alpha.service_date,status:'sent'};
const review={...sentReview(),duplicate:record};a.applyReview(review);const minimal=element('#interpretation-review-home-result').innerHTML;
a.updateHomeReviewCard({...review,duplicate:{...record,recipient:'<recorded@example.test>',payment_entity:'Recorded court',service_place:'Recorded venue'}});
console.log(JSON.stringify({minimal,explicit:element('#interpretation-review-home-result').innerHTML,calls}));
""")
        for absent in ['Recipient','Payment entity','Service place','Needs answer','Court Alpha','Police Alpha','alpha@example.test']:
            self.assertNotIn(absent,result['minimal'])
        for expected in ['&lt;recorded@example.test&gt;','Recorded court','Recorded venue']:
            self.assertIn(expected,result['explicit'])
        self.assertNotIn('<recorded@example.test>',result['explicit'])
        self.assertEqual(result['calls'],[])

    def test_sent_summary_does_not_suppress_normal_questions_draft_review_or_ready_actions(self):
        result=self.run_js("""
const current={...alpha,payment_entity:'',service_place:'',recipient_email:''};a.state.currentIntake=current;a.fillFormFromIntake(current);
a.applyReview(sentReview(current));const sentHidden=element('#request-claim-card').classList.values.hidden;
const rows=[{status:'needs_info',intake:current,questions:[{number:1,field:'payment_entity',question:'Which paying court?'}],next_safe_action:{state:'answer_questions',blocked:true}},
 {...sentReview(current,'drafted'),next_safe_action:{state:'correct_existing_draft',blocked:true}},
 {status:'ready',intake:alpha,questions:[],next_safe_action:{state:'prepare_pdf',blocked:false}}];
const results=[];for(const row of rows){a.applyReview(row);results.push({status:row.status,html:element('#interpretation-review-home-result').innerHTML,claimHidden:element('#request-claim-card').classList.values.hidden});}
console.log(JSON.stringify({sentHidden,results,calls}));
""")
        self.assertTrue(result['sentHidden'])
        for row in result['results']:
            self.assertFalse(row['claimHidden'])
            self.assertNotIn('data-sent-history-summary',row['html'])
            self.assertIn('data-review-correct-field',row['html'])
        self.assertIn('Which paying court?',result['results'][0]['html'])
        self.assertIn('Type your numbered answers',result['results'][0]['html'])
        self.assertIn('Needs answer',result['results'][1]['html'])
        self.assertIn('Review draft and PDF step',result['results'][2]['html'])
        self.assertEqual(result['calls'],[])

    def test_all_fresh_sent_source_hides_claim_prompts_but_mixed_or_stale_source_keeps_controls(self):
        result=self.run_js("""
const rows=[alpha,beta].map(row=>({candidate_intake:{...row},review:sentReview(row),needs_review:false,answers:'keep'}));
a.state.sourceCaseCandidates=rows;a.state.batchIntakes=[{...beta}];a.state.workspaceDraft.pending={saved:'keep'};const results=[];
for(const mode of ['sent','mixed','stale']){
 if(mode==='mixed')rows[1].review={status:'ready',intake:beta,questions:[]};
 if(mode==='stale'){rows[1].review=sentReview(beta);rows[1].needs_review=true;}
 const before=JSON.stringify({rows,queue:a.state.batchIntakes,pending:a.state.workspaceDraft.pending});a.renderSourceCaseList();
 results.push({mode,travelHidden:element('#source-travel-controls').classList.values.hidden,replacementHidden:element('#source-email-correction').classList.values.hidden,
 summary:element('#source-case-summary').textContent,next:element('#source-case-next-action').textContent,list:element('#source-case-list').innerHTML,
 unchanged:before===JSON.stringify({rows,queue:a.state.batchIntakes,pending:a.state.workspaceDraft.pending}),addDisabled:element('#add-source-cases-to-batch').disabled});
}
console.log(JSON.stringify({results,calls}));
""")
        sent=result['results'][0]
        self.assertTrue(sent['travelHidden'])
        self.assertTrue(sent['replacementHidden'])
        self.assertTrue(sent['addDisabled'])
        self.assertIn('All 2 requests in this source were already sent',sent['summary'])
        self.assertIn('No further answers or new requests are needed',sent['next'])
        self.assertEqual(sent['list'].count('Already sent'),2)
        self.assertNotIn('Police Alpha',sent['list'])
        self.assertNotIn('Interpreting',sent['list'])
        for row in result['results'][1:]:
            self.assertFalse(row['travelHidden'])
            self.assertFalse(row['replacementHidden'])
            self.assertNotIn('All 2 requests',row['summary'])
        self.assertTrue(all(row['unchanged'] for row in result['results']))
        self.assertEqual(result['calls'],[])

    def test_sent_warning_yes_only_opens_blocked_review_details(self):
        result=self.run_js("""
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);a.applyReview(sentReview());
element('#sent-duplicate-review').listeners.click();
console.log(JSON.stringify({open:element('#sent-duplicate-dialog').open,drawer:context.document.body.dataset.interpretationReviewDrawer,
status:a.state.lastReview.status,action:a.state.currentNextSafeAction.state,prepared:a.state.lastPrepared,
disabled:['#drawer-prepare-intake','#drawer-prepare-intake-inline','#create-gmail-api-draft','#prepare-replacement-draft','#prepare-source-email-replacement'].map(id=>element(id).disabled),calls}));
""")
        self.assertFalse(result['open'])
        self.assertEqual(result['drawer'],'open')
        self.assertEqual(result['status'],'duplicate')
        self.assertEqual(result['action'],'stop_duplicate_sent')
        self.assertIsNone(result['prepared'])
        self.assertTrue(all(result['disabled']))
        self.assertEqual(result['calls'],[])

    def test_sent_warning_escape_is_no_and_passive_render_never_reopens_it(self):
        result=self.run_js("""
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);a.applyReview(sentReview(alpha,null));let prevented=false;
element('#sent-duplicate-dialog').listeners.cancel({preventDefault(){prevented=true;}});
a.updateHomeReviewCard(a.state.lastReview);a.renderSourceCaseList();a.syncActionGates();
const afterPassive={open:element('#sent-duplicate-dialog').open,count:element('#sent-duplicate-dialog').openCount,alert:element('#alert').textContent};
a.applyReview(sentReview(alpha,null));console.log(JSON.stringify({prevented,afterPassive,afterFresh:{open:element('#sent-duplicate-dialog').open,count:element('#sent-duplicate-dialog').openCount},calls}));
""")
        self.assertTrue(result['prevented'])
        self.assertFalse(result['afterPassive']['open'])
        self.assertEqual(result['afterPassive']['count'],1)
        self.assertIn('Stopped:',result['afterPassive']['alert'])
        self.assertEqual(result['afterFresh'],{'open':True,'count':2})
        self.assertEqual(result['calls'],[])

    def test_sent_warning_ignores_drafts_unresolved_dates_and_mismatched_identity(self):
        result=self.run_js("""
const rows=[sentReview(alpha,'drafted'),{...sentReview(),status:'active_draft'},
{...sentReview(),status:'needs_info',questions:[{field:'service_date'}]},sentReview({...alpha,service_date:'2026-02-30'}),
sentReview({...alpha,service_date:''}),{...sentReview(),duplicate:{...sentReview().duplicate,case_number:beta.case_number}},
{...sentReview({...alpha,service_period_label:'afternoon'}),duplicate:{...sentReview().duplicate,service_period_label:'morning'}}];
const opened=[];for(const row of rows){a.state.currentIntake={...row.intake};a.fillFormFromIntake(a.state.currentIntake);a.applyReview(row);opened.push(Boolean(element('#sent-duplicate-dialog').open));}
console.log(JSON.stringify({opened,calls}));
""")
        self.assertFalse(any(result['opened']))
        self.assertEqual(result['calls'],[])

    def test_sent_decision_is_invalidated_by_edits_and_rejects_other_stale_contexts(self):
        result=self.run_js("""
const results=[];
for(const mutation of ['edit','identity','source','selection','review']){
 a.state.currentIntake={...alpha};a.state.sourceCaseSelectedIndex=null;a.fillFormFromIntake(alpha);a.applyReview(sentReview());
 if(mutation==='edit'){element('#service_place').value='Another venue';element('#intake-form').listeners.input({target:element('#service_place')});}
 if(mutation==='identity')a.state.currentIntake={...beta};
 if(mutation==='source')a.state.currentIntake={...alpha,source_sha256:'changed-source'};
 if(mutation==='selection')a.state.sourceCaseSelectedIndex=1;
 if(mutation==='review')a.state.lastReview={...a.state.lastReview};
 context.document.body.dataset.interpretationReviewDrawer='sentinel';element('#alert').textContent='keep current message';
 element('#sent-duplicate-review').listeners.click();
 results.push({mutation,open:Boolean(element('#sent-duplicate-dialog').open),drawer:context.document.body.dataset.interpretationReviewDrawer,alert:element('#alert').textContent,stopped:a.state.sentDuplicateStoppedReview});
}
console.log(JSON.stringify({results,calls}));
""")
        for row in result['results']:
            self.assertFalse(row['open'])
            self.assertEqual(row['drawer'],'sentinel')
            self.assertEqual(row['alert'],'keep current message')
            self.assertIsNone(row['stopped'])
        self.assertEqual(result['calls'],[])

    def test_late_sent_review_cannot_prompt_for_the_next_source(self):
        result=self.run_js("""
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);let release;deferred=new Promise(resolve=>release=resolve);deferredRoute='/api/review';responseOverride=sentReview();
const pending=a.reviewIntake();a.clearPreparedArtifacts('new photo selected');a.state.currentIntake={...beta};a.fillFormFromIntake(beta);release();await pending;
console.log(JSON.stringify({current:a.state.currentIntake.case_number,open:Boolean(element('#sent-duplicate-dialog').open),review:a.state.lastReview,calls}));
""")
        self.assertEqual(result['current'],'711/26.0TSTXX')
        self.assertFalse(result['open'])
        self.assertIsNone(result['review'])
        self.assertEqual([row['url'] for row in result['calls']],['/api/review'])

    def test_sent_or_unknown_child_keeps_source_replacement_disabled(self):
        result=self.run_js("""
const results=[];element('#source-correction-reason').value='Reviewed replacement reason';
for(const status of ['sent',null,'drafted']){
 a.state.sourceCaseCandidates=[alpha,beta].map(row=>({candidate_intake:row,review:sentReview(row,status),needs_review:false}));
 a.syncActionGates();results.push({status,allowed:a.canPrepareSourceEmailReplacement(),disabled:element('#prepare-source-email-replacement').disabled});
}
console.log(JSON.stringify({results,calls}));
""")
        self.assertEqual(result['results'],[
            {'status':'sent','allowed':False,'disabled':True},
            {'status':None,'allowed':False,'disabled':True},
            {'status':'drafted','allowed':True,'disabled':False}])
        self.assertEqual(result['calls'],[])

    def test_visible_venue_replacement_requests_dependent_reconciliation_without_changing_trip(self):
        result = self.run_js("""
const source={...alpha,service_place:'Posto da GNR de Alpha',service_entity:'GNR Alpha',service_entity_type:'gnr',
service_place_phrase:'no Posto da GNR de Alpha',transport:{destination:'Alpha',km_one_way:25}};
a.state.currentIntake=source;a.fillFormFromIntake(source);
a.state.lastPrepared={sentinel:true};
element('#service_place').value='Tribunal de Alpha';
element('#intake-form').listeners.input({target:element('#service_place')});
a.mergeFormIntoCurrentIntake();
console.log(JSON.stringify({intake:a.state.currentIntake,prepared:a.state.lastPrepared}));
""")
        self.assertIn('service_place', result['intake']['review_cleared_fields'])
        self.assertEqual(result['intake']['service_place'], 'Tribunal de Alpha')
        self.assertEqual(result['intake']['payment_entity'], 'Court Alpha')
        self.assertEqual(result['intake']['transport'], {'destination': 'Alpha', 'km_one_way': 25})
        self.assertIsNone(result['prepared'])

    def test_visible_payer_replacement_reconciles_salutation_for_photo_and_manual_inputs(self):
        result = self.run_js("""
const rows=[];
for(const photo of [false,true])for(const newRecipient of ['', 'new@example.test']){
 const source={...alpha,addressee:'Exmo. Senhor Procurador da República\\nOld MP',court_email:'old@example.test',court_email_key:'old',
  recipient_override_reason:'old exception',...(photo?{photo_defaults_applied:{routing_status:'applied'}}:{})};
 a.state.currentIntake=source;a.fillFormFromIntake(source);
 element('#payment_entity').value='Tribunal de New City';
 if(newRecipient)element('#recipient_email').value=newRecipient;
 a.mergeFormIntoCurrentIntake();rows.push({photo,newRecipient,intake:JSON.parse(JSON.stringify(a.state.currentIntake))});
}
console.log(JSON.stringify(rows));
""")
        for row in result:
            intake = row['intake']
            self.assertIn('payment_entity', intake['review_cleared_fields'])
            self.assertEqual(intake['addressee'], '')
            self.assertEqual(intake['recipient_email'], row['newRecipient'])
            if not row['newRecipient']:
                self.assertIn('recipient_email', intake['review_cleared_fields'])
            else:
                self.assertNotIn('recipient_email', intake['review_cleared_fields'])
            self.assertFalse(intake['court_email'])
            self.assertFalse(intake['court_email_key'])
            self.assertFalse(intake['recipient_override_reason'])
            self.assertEqual(intake['service_place'], 'Police Alpha')

    def test_unedited_visible_venue_and_payer_preserve_custom_details(self):
        result = self.run_js("""
const source={...alpha,addressee:'Custom reviewed addressee',service_place_phrase:'custom reviewed physical host phrase'};
a.state.currentIntake=source;a.fillFormFromIntake(source);a.mergeFormIntoCurrentIntake();
console.log(JSON.stringify(a.state.currentIntake));
""")
        self.assertEqual(result['addressee'], 'Custom reviewed addressee')
        self.assertEqual(result['service_place_phrase'], 'custom reviewed physical host phrase')
        self.assertNotIn('review_cleared_fields', result)

    def test_late_supporting_proof_never_attaches_to_a_new_request(self):
        result = self.run_js("""
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);
let release;const gate=new Promise(resolve=>release=resolve);
context.fetch=async()=>{await gate;return {ok:true,json:async()=>({attachment:{stored_path:'/fictional/alpha-proof.pdf'}})}};
const pending=a.uploadSupportingAttachments([{name:'alpha-proof.pdf'}]);
a.clearPreparedArtifacts('source changed');a.state.currentIntake={...beta};a.fillFormFromIntake(beta);
release();const result=await pending;
console.log(JSON.stringify({result,current:a.state.currentIntake.case_number,attachments:a.state.currentIntake.additional_attachment_files||[]}));
""")
        self.assertIsNone(result['result'])
        self.assertEqual(result['current'], '711/26.0TSTXX')
        self.assertEqual(result['attachments'], [])

    def test_new_pdf_upload_does_not_inherit_another_sources_proofs_or_body(self):
        result = self.run_js("""
const results=[];const originalFetch=context.fetch;
for(const previousHash of [alpha.source_sha256,beta.source_sha256,'']){
 a.state.currentIntake={...alpha,source_sha256:previousHash,additional_attachment_files:['/fictional/alpha-proof.pdf'],email_body:'Previous explanation'};a.fillFormFromIntake(a.state.currentIntake);
 context.fetch=async(url,options)=>url==='/api/sources/upload'?{ok:true,json:async()=>({candidate_intake:{...beta,source_kind:'notification_pdf'},review:{status:'ready',intake:beta,next_safe_action:{state:'prepare_pdf'}},source:{sha256:beta.source_sha256,source_kind:'notification_pdf'}})}:originalFetch(url,options);
 await a.uploadSource('notification_pdf',{file:{name:'beta.pdf',size:20,lastModified:2,type:'application/pdf'}});
 results.push({previousHash,case:a.state.currentIntake.case_number,attachments:a.state.currentIntake.additional_attachment_files||[],body:a.state.currentIntake.email_body||''});
}
console.log(JSON.stringify({results,reviewBodies:calls.filter(row=>row.url==='/api/review').map(row=>({attachments:row.body.intake.additional_attachment_files||[],body:row.body.intake.email_body||''}))}));
""")
        self.assertEqual(result['results'][0]['case'], '711/26.0TSTXX')
        self.assertEqual(result['results'][0]['attachments'], [])
        self.assertEqual(result['results'][0]['body'], '')
        self.assertEqual(result['reviewBodies'][0], {'attachments': [], 'body': ''})
        for row in result['results'][1:]:
            self.assertEqual(row['attachments'], ['/fictional/alpha-proof.pdf'])
            self.assertEqual(row['body'], 'Previous explanation')

    def test_pdf_multiple_cases_follow_existing_review_and_shared_trip_ui(self):
        result = self.run_js("""
const rows=photoRows().slice(1,3).map(row=>({...row,source_kind:'notification_pdf',service_date:'2026-09-28',transport:{origin:'Example home',destination:'Beta',km_one_way:12}}));
const originalFetch=context.fetch;
context.fetch=async(url,options)=>url==='/api/sources/upload'?{ok:true,json:async()=>({candidate_intake:rows[0],case_count:2,case_candidates:rows.map(intake=>({candidate_intake:intake,review:{status:'ready',intake,next_safe_action:{state:'prepare_pdf'}}})),source:{sha256:rows[0].source_sha256,source_kind:'notification_pdf',filename:'fictional-two-cases.pdf'}})}:originalFetch(url,options);
routeOverrides['/api/review']=body=>({status:'ready',intake:body.intake,next_safe_action:{state:'prepare_pdf'}});
await a.uploadSource('notification_pdf',{file:{name:'two-cases.pdf',size:20,lastModified:2,type:'application/pdf'}});
console.log(JSON.stringify({cases:a.state.sourceCaseCandidates.map(row=>({case:row.candidate_intake.case_number,kind:row.candidate_intake.source_kind,date:row.candidate_intake.service_date,travel:row.candidate_intake.claim_transport,status:row.review.status})),owner:a.state.sourceTravelChoice.ownerIndex,addDisabled:element('#add-source-cases-to-batch').disabled,reviewed:calls.filter(row=>row.url==='/api/review').map(row=>row.body.intake.case_number)}));
""")
        self.assertEqual([row['case'] for row in result['cases']], ['711/26.0TSTXX', '712/26.0TSTXX'])
        self.assertTrue(all(row['kind'] == 'notification_pdf' and row['date'] == '2026-09-28' and row['status'] == 'ready' for row in result['cases']))
        self.assertEqual([row['travel'] for row in result['cases']], [True, False])
        self.assertEqual(result['owner'], 0)
        self.assertFalse(result['addDisabled'])
        self.assertEqual(result['reviewed'], ['711/26.0TSTXX', '712/26.0TSTXX'])

    def test_late_pdf_upload_cannot_restore_old_supplemental_files_after_source_change(self):
        result = self.run_js("""
a.state.currentIntake={...alpha,additional_attachment_files:['/fictional/alpha-proof.pdf'],email_body:'Alpha explanation'};a.fillFormFromIntake(a.state.currentIntake);
let release;const gate=new Promise(resolve=>release=resolve);
context.fetch=async()=>{await gate;return {ok:true,json:async()=>({candidate_intake:alpha,source:{sha256:alpha.source_sha256,source_kind:'notification_pdf'}})}};
const pending=a.uploadSource('notification_pdf',{file:{name:'alpha.pdf',size:20,lastModified:2,type:'application/pdf'}});
a.clearPreparedArtifacts('changed source');a.state.currentIntake={...beta,additional_attachment_files:['/fictional/beta-proof.pdf'],email_body:'Beta explanation'};
release();const result=await pending;
console.log(JSON.stringify({result,current:a.state.currentIntake,cases:a.state.sourceCaseCandidates.length}));
""")
        self.assertIsNone(result['result'])
        self.assertEqual(result['current']['case_number'], '711/26.0TSTXX')
        self.assertEqual(result['current']['additional_attachment_files'], ['/fictional/beta-proof.pdf'])
        self.assertEqual(result['current']['email_body'], 'Beta explanation')
        self.assertEqual(result['cases'], 0)

    def test_current_multiple_proofs_attach_but_stale_upload_error_is_ignored(self):
        result = self.run_js("""
a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);let uploaded=0;
context.fetch=async()=>({ok:true,json:async()=>({attachment:{stored_path:`/fictional/proof-${++uploaded}.pdf`}})});
await a.uploadSupportingAttachments([{name:'one.pdf'},{name:'two.pdf'}]);
const attachments=a.state.currentIntake.additional_attachment_files;
let release;const gate=new Promise(resolve=>release=resolve);
context.fetch=async()=>{await gate;throw new Error('obsolete upload failure')};
const pending=a.uploadSupportingAttachments([{name:'old.pdf'}]);
a.clearPreparedArtifacts('reset');a.state.currentIntake=null;release();const stale=await pending;
console.log(JSON.stringify({attachments,stale,current:a.state.currentIntake}));
""")
        self.assertEqual(result['attachments'], ['/fictional/proof-1.pdf', '/fictional/proof-2.pdf'])
        self.assertIsNone(result['stale'])
        self.assertIsNone(result['current'])

    def test_late_manual_profile_result_cannot_replace_current_source(self):
        result = self.run_js("""
a.state.reference={service_profiles:{example_interpreting:{}}};a.state.currentIntake={...alpha};a.fillFormFromIntake(alpha);
let release;const gate=new Promise(resolve=>release=resolve);const requests=[];
context.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});await gate;return {ok:true,json:async()=>({intake:alpha})}};
const pending=a.buildIntakeFromProfile({openDrawer:false});
a.clearPreparedArtifacts('new source');a.state.currentIntake={...beta};a.fillFormFromIntake(beta);release();const stale=await pending;
console.log(JSON.stringify({stale,current:a.state.currentIntake.case_number,requests}));
""")
        self.assertIsNone(result['stale'])
        self.assertEqual(result['current'], '711/26.0TSTXX')
        self.assertEqual(len(result['requests']), 1)
        self.assertEqual(result['requests'][0]['body']['profile'], 'example_interpreting')

    def test_upload_double_click_is_one_request_and_old_errors_cannot_block_new_source(self):
        result = self.run_js("""
let release;const gate=new Promise(resolve=>release=resolve);let count=0;
context.fetch=async()=>{count++;await gate;return {ok:false,status:503,json:async()=>({message:'obsolete source failure'})}};
const file={name:'one.png',size:10,lastModified:1,type:'image/png'};
const first=a.uploadSource('photo',{file});const repeated=await a.uploadSource('photo',{file});
a.clearPreparedArtifacts('reset');a.state.currentIntake={...beta};release();const stale=await first;
let currentError='';try {await a.uploadSource('photo',{file})}catch(error){currentError=error.message}
console.log(JSON.stringify({count,repeated,stale,currentError,current:a.state.currentIntake.case_number,pending:a.state.sourceUploadPending}));
""")
        self.assertEqual(result['count'], 2, 'One original upload and one deliberate retry after reset')
        self.assertIsNone(result['repeated'])
        self.assertIsNone(result['stale'])
        self.assertEqual(result['currentError'], 'obsolete source failure')
        self.assertEqual(result['current'], '711/26.0TSTXX')
        self.assertIsNone(result['pending'])

    def test_cleared_single_case_fields_reach_review_as_explicit_removals(self):
        result = self.run_js("""
a.state.currentIntake={...alpha,transport:{km_one_way:42}};a.fillFormFromIntake(a.state.currentIntake);
for(const id of ['case_number','service_date','payment_entity','service_place','km_one_way'])element('#'+id).value='';
a.mergeFormIntoCurrentIntake();const cleared=JSON.parse(JSON.stringify(a.state.currentIntake));
element('#case_number').value='712/26.0TSTXX';a.mergeFormIntoCurrentIntake();
console.log(JSON.stringify({cleared,resolved:a.state.currentIntake.review_cleared_fields}));
""")
        for field in ['case_number', 'service_date', 'payment_entity', 'service_place']:
            self.assertEqual(result['cleared'][field], '')
            self.assertIn(field, result['cleared']['review_cleared_fields'])
        self.assertEqual(result['cleared']['transport']['km_one_way'], '')
        self.assertIn('transport.km_one_way', result['cleared']['review_cleared_fields'])
        self.assertIn('case_number', result['resolved'], 'Review resolves the intent marker after reconciling dependent fields')

    def test_error_review_never_advertises_readiness(self):
        result = self.run_js("""
a.state.currentIntake={...alpha};a.updateHomeReviewCard({status:'error',message:'Unknown service profile',questions:[]});
console.log(JSON.stringify({card:element('#interpretation-review-home-result').innerHTML}));
""")
        self.assertIn('Review needs attention', result['card'])
        self.assertNotIn('Ready for the next step', result['card'])

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

    def test_uncertain_creation_blocks_new_create_without_claiming_local_recording(self):
        result=self.run_js("""
a.renderPrepared(prepare());a.state.gmailStatus={connected:true};element('#gmail_handoff_reviewed').checked=true;
responseOverride={status:'creation_uncertain',attempt_id:'fictional-attempt',message:'Check Gmail before retrying.',gmail_create_draft_args:{to:'alpha@example.test'}};
await a.createGmailApiDraft();console.log(JSON.stringify({recorded:a.state.locallyRecordedPayload,disabled:element('#create-gmail-api-draft').disabled,panel:element('#gmail-api-result').innerHTML,ids:element('#record_draft_id').value,status:element('#status-pill').textContent}));
""")
        self.assertEqual(result['recorded'],'')
        self.assertEqual(result['ids'],'')
        self.assertTrue(result['disabled'])
        self.assertEqual(result['status'],'blocked')
        self.assertIn('I checked Gmail and no draft exists',result['panel'])
        self.assertNotIn('Created as a Gmail draft only',result['panel'])

    def test_known_creation_failure_retains_ids_and_recovers_only_original_attempt(self):
        result=self.run_js("""
a.renderPrepared(prepare());a.state.gmailStatus={connected:true};element('#gmail_handoff_reviewed').checked=true;
responseOverride={status:'created_unrecorded',attempt_id:'fictional-attempt',draft_id:'fictional-created',message_id:'fictional-message',draft_payload:'/fictional/alpha.json',message:'Finish local recording.'};
await a.createGmailApiDraft();const firstPanel=element('#gmail-api-result').innerHTML;const firstRecorded=a.state.locallyRecordedPayload;
responseOverride={status:'created',draft_id:'fictional-created',message_id:'fictional-message',draft_payload:'/fictional/alpha.json',recovered_existing_draft:true,message:'Existing draft recorded. No new Gmail draft was created.'};
await a.recoverGmailAttempt('record');console.log(JSON.stringify({firstPanel,firstRecorded,calls,recorded:a.state.locallyRecordedPayload,ids:element('#record_draft_id').value}));
""")
        self.assertIn('The Gmail draft exists',result['firstPanel'])
        self.assertIn('Finish local recording',result['firstPanel'])
        self.assertEqual(result['firstRecorded'],'')
        self.assertEqual(result['calls'][1]['body']['recover_attempt_id'],'fictional-attempt')
        self.assertNotIn('payload',result['calls'][1]['body'])
        self.assertEqual(result['recorded'],'/fictional/alpha.json')
        self.assertEqual(result['ids'],'fictional-created')

    def test_no_draft_resolution_requires_confirmation_and_reenables_create(self):
        result=self.run_js("""
a.renderPrepared(prepare());a.state.gmailStatus={connected:true};element('#gmail_handoff_reviewed').checked=true;
responseOverride={status:'creation_uncertain',attempt_id:'fictional-attempt',message:'Check Gmail first.'};await a.createGmailApiDraft();
context.window.confirm=()=>false;await a.recoverGmailAttempt('absent');const cancelledCount=calls.length;
context.window.confirm=()=>true;responseOverride={status:'not_created',create_retry_allowed:true,message:'No-draft check recorded.'};await a.recoverGmailAttempt('absent');
console.log(JSON.stringify({cancelledCount,calls,disabled:element('#create-gmail-api-draft').disabled,completed:a.state.gmailCreateCompletedPayload}));
""")
        self.assertEqual(result['cancelledCount'],1)
        self.assertEqual(result['calls'][1]['body']['confirmation_phrase'],'I CHECKED GMAIL: NO DRAFT')
        self.assertFalse(result['disabled'])
        self.assertEqual(result['completed'],'')

    def test_connected_gmail_hides_setup_and_keeps_one_checklist_before_primary_action(self):
        result=self.run_js("""
a.renderGmailStatus({connected:true,configured:true,recommended_mode:'gmail_api'});console.log(JSON.stringify({setup:element('#gmail-setup-details').open,manual:element('#manual-handoff-card').open,direct:element('#gmail-api-deferred-panel').open}));
""")
        self.assertEqual(result,{'setup':False,'manual':False,'direct':True})
        page=(ROOT/'honorarios_app/templates/index.html').read_text(encoding='utf-8')
        self.assertEqual(page.count('id="gmail_handoff_reviewed"'),1)
        self.assertLess(page.index('id="gmail_handoff_reviewed"'),page.index('id="create-gmail-api-draft"'))
        self.assertLess(page.index('id="create-gmail-api-draft"'),page.index('id="gmail-client-id"'))

    def test_recent_work_recovery_is_available_after_restart_without_prepared_workspace(self):
        result=self.run_js("""
const attempt={status:'created_unrecorded',attempt_id:'fictional-restart-attempt',draft_id:'fictional-existing',message_id:'fictional-message',message:'Finish local recording.',gmail_create_draft_args:{to:'court@example.test',body:'Original <email>'}};
a.state.reference={pending_gmail_attempts:[attempt]};a.renderReference();const panel=element('#pending-gmail-attempts').innerHTML;
responseOverride={status:'created',draft_id:'fictional-existing',message_id:'fictional-message',draft_payload:'/fictional/original.json',recovered_existing_draft:true,message:'Recovered existing draft locally.'};
await a.recoverGmailAttempt('record',{history:true,attempt});console.log(JSON.stringify({panel,calls,prepared:a.state.lastPrepared,recorded:a.state.locallyRecordedPayload,loads:context.referenceLoads}));
""")
        self.assertIn('Finish local recording',result['panel'])
        self.assertIn('Original &lt;email&gt;',result['panel'])
        self.assertIsNone(result['prepared'])
        self.assertEqual(result['recorded'],'')
        self.assertEqual(result['calls'][0]['body']['recover_attempt_id'],'fictional-restart-attempt')
        self.assertEqual(result['loads'],1)

    def test_history_recovery_and_no_draft_results_describe_local_writes_truthfully(self):
        result=self.run_js("""
const cases=[{status:'created',recovered_existing_draft:true,gmail_api_action:'local_record_recovery',recorded_duplicate_count:5},
{status:'not_created',create_retry_allowed:true,gmail_api_action:'local_attempt_resolution'},
{status:'verified',gmail_api_action:'users.drafts.get'}];
const panels=cases.map(data=>{a.renderHistoryDraftActionResult(data);return element('#history-draft-action-result').innerHTML;});console.log(JSON.stringify({panels}));
""")
        recovered,resolved,verified=result['panels']
        self.assertIn('recorded locally',recovered)
        self.assertIn('no new draft was created',recovered)
        self.assertIn('local_record_recovery',recovered)
        self.assertIn('Duplicate records updated: <strong>5',recovered)
        self.assertIn('Your Gmail check was saved locally',resolved)
        self.assertIn('separate action',resolved)
        self.assertIn('local_attempt_resolution',resolved)
        for panel in (recovered,resolved):
            self.assertNotIn('Read-only Gmail draft verification',panel)
            self.assertNotIn('No local records were changed',panel)
            self.assertNotIn('users.drafts.create',panel)
        self.assertIn('Read-only Gmail draft verification',verified)

    def test_history_recovery_never_borrows_another_workspaces_ids(self):
        result=self.run_js("""
element('#record_draft_id').value='fictional-unrelated-draft';element('#record_message_id').value='fictional-unrelated-message';element('#record_thread_id').value='fictional-unrelated-thread';context.window.confirm=()=>true;
let error='';try{await a.recoverGmailAttempt('existing',{history:true,attempt:{attempt_id:'fictional-old-attempt'},draft_id:'',message_id:''});}catch(exc){error=exc.message;}
responseOverride={status:'created',message:'Recorded existing draft.'};await a.recoverGmailAttempt('existing',{history:true,attempt:{attempt_id:'fictional-old-attempt'},draft_id:'fictional-intended-draft',message_id:'fictional-intended-message'});
console.log(JSON.stringify({error,calls}));
""")
        self.assertIn('both the existing draft ID and message ID',result['error'])
        self.assertEqual(len(result['calls']),1)
        self.assertEqual(result['calls'][0]['body']['draft_id'],'fictional-intended-draft')
        self.assertEqual(result['calls'][0]['body']['thread_id'],'')

    def test_late_pending_creation_does_not_overwrite_new_target_or_claim_success(self):
        result=self.run_js("""
a.renderPrepared(prepare());element('#gmail_handoff_reviewed').checked=true;let release;deferred=new Promise(resolve=>release=resolve);const pending=a.createGmailApiDraft();a.selectPreparedEmailTarget(1);
responseOverride={status:'created_unrecorded',attempt_id:'fictional-attempt',draft_id:'earlier-draft',message_id:'earlier-message',message:'Earlier draft needs local recording.'};release();await pending;
console.log(JSON.stringify({ids:element('#record_draft_id').value,payload:element('#record_payload').value,recorded:a.state.locallyRecordedPayload,alert:element('#alert').textContent}));
""")
        self.assertEqual(result['ids'],'')
        self.assertEqual(result['payload'],'/fictional/beta.json')
        self.assertEqual(result['recorded'],'')
        self.assertIn('needs local recording',result['alert'])
        self.assertNotIn('created as a draft and recorded',result['alert'])

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

    def test_batch_preflight_handler_keeps_ready_action_and_blockers_in_batch_workspace(self):
        for status in ('ready', 'blocked'):
            with self.subTest(status=status):
                result=self.run_js("const status="+json.dumps(status)+";"+"""
a.state.batchIntakes=photoRows();context.document.body.dataset.interpretationReviewDrawer='open';
let focused='',batchVisible=false,scrolled=false;
element('#prepare-batch-intakes').focus=()=>{focused='prepare'};
element('#batch-preflight-result').focus=()=>{focused='result'};
element('#batch-preflight-result').scrollIntoView=()=>{scrolled=true};
element('#batch-queue-panel').classList.remove=name=>{if(name==='hidden')batchVisible=true};
routeOverrides['/api/prepare/preflight']={status,message:status==='ready'?'All queued requests are ready.':'Fictional recipient needs review.',
 preflight_review:status==='ready'?{token:'fictional-preflight'}:null,next_safe_action:{state:status==='ready'?'prepare_batch':'fix_blocker'},
 blockers:status==='blocked'?[{message:'Fictional recipient needs review.'}]:[]};
await element('#preflight-batch-intakes').listeners.click();
console.log(JSON.stringify({focused,batchVisible,scrolled,drawer:context.document.body.dataset.interpretationReviewDrawer,
 disabled:element('#prepare-batch-intakes').disabled,result:element('#batch-preflight-result').innerHTML,calls}));
""")
                self.assertEqual(result['drawer'],'closed')
                self.assertTrue(result['batchVisible'])
                self.assertTrue(result['scrolled'])
                self.assertEqual(result['focused'],'prepare' if status=='ready' else 'result')
                self.assertEqual(result['disabled'],status!='ready')
                self.assertIn('All queued requests are ready.' if status=='ready' else 'Fictional recipient needs review.',result['result'])
                self.assertEqual([call['url'] for call in result['calls']],['/api/prepare/preflight'])

    def test_manual_visit_selection_is_bound_to_preflight_and_invalidates_on_mode_change(self):
        result=self.run_js("""
const rows=[{...alpha,source_kind:'manual',source_sha256:'',claim_transport:true},
 {...alpha,source_kind:'manual',source_sha256:'',case_number:'711/26.0TSTXX',claim_transport:false}];
a.state.batchIntakes=rows;const before=JSON.stringify(rows);
element('#batch-email-grouping').value='manual_visit';element('#batch-email-grouping').listeners.change();
const note=element('#batch-email-grouping-note').textContent;
await a.preflightBatchIntakes();const checked=a.batchPreflightSignature();
await a.prepareBatchIntakes();
element('#batch-email-grouping').value='individual';element('#batch-email-grouping').listeners.change();
console.log(JSON.stringify({calls,note,unchanged:JSON.stringify(rows)===before,checked,changed:a.batchPreflightSignature(),
 preflight:a.state.batchPreflight,prepared:a.state.lastPrepared,disabled:element('#prepare-batch-intakes').disabled}));
""")
        self.assertIn('confirms', result['note'])
        self.assertIn('travel claimed once', result['note'])
        self.assertTrue(result['unchanged'])
        self.assertNotEqual(result['checked'], result['changed'])
        self.assertIsNone(result['preflight'])
        self.assertIsNone(result['prepared'])
        self.assertTrue(result['disabled'])
        for call in result['calls']:
            self.assertEqual(call['body']['email_grouping'], 'manual_visit')
            self.assertEqual([row['claim_transport'] for row in call['body']['intakes']], [True, False])
        self.assertEqual(result['calls'][1]['body']['preflight_review'], {'token':'fictional-preflight'})

    def test_manual_visit_replacement_keeps_mode_and_both_members(self):
        result=self.run_js("""
const prepared=groupedPrepare();prepared.email_grouping='manual_visit';prepared.items=prepared.items.slice(0,2);
prepared.prepared_review_material.effective_intakes=prepared.prepared_review_material.effective_intakes.slice(0,2).map((row,index)=>({...row,source_kind:'manual',source_sha256:'',claim_transport:index===0}));
prepared.email_groups=[{...prepared.email_groups[0],source_sha256:'',member_indices:[0,1],underlying_requests:prepared.items}];
prepared.correction_mode=true;prepared.correction_reason='Correct both manual visit requests';
a.renderPrepared(prepared);const options=element('#prepared-email-target').innerHTML;
a.state.currentIntake=alpha;a.fillFormFromIntake(alpha);await a.prepareIntake({correctionMode:true});
console.log(JSON.stringify({calls,options}));
""")
        self.assertIn('2 requests from one manual visit', result['options'])
        for call in result['calls']:
            self.assertEqual(call['body']['email_grouping'], 'manual_visit')
            self.assertEqual(len(call['body']['intakes']), 2)
            self.assertTrue(call['body']['correction_mode'])

    def test_created_draft_next_action_points_to_existing_draft_and_resets_on_target_change(self):
        result=self.run_js("""
const prepared=prepare();prepared.next_safe_action={state:'review_gmail_draft_args',title:'Create Gmail Draft',button_id:'create-gmail-api-draft'};
a.renderPrepared(prepared);a.state.gmailStatus={connected:true};element('#gmail_handoff_reviewed').checked=true;
await a.createGmailApiDraft();const completed=element('#next-safe-action-body').innerHTML,disabled=element('#create-gmail-api-draft').disabled;
a.selectPreparedEmailTarget(1);
console.log(JSON.stringify({completed,disabled,next:element('#next-safe-action-body').innerHTML,calls}));
""")
        self.assertIn('Review the created draft in Gmail', result['completed'])
        self.assertNotIn('data-next-action-target="create-gmail-api-draft"', result['completed'])
        self.assertTrue(result['disabled'])
        self.assertIn('Create Gmail Draft', result['next'])
        self.assertEqual(len(result['calls']), 1)

    def test_source_grouping_is_signed_without_combining_individual_pdfs(self):
        result=self.run_js("""
a.state.batchIntakes=photoRows();const original=JSON.stringify(a.state.batchIntakes);
await a.preflightBatchIntakes();await a.prepareBatchIntakes();
console.log(JSON.stringify({calls,unchanged:JSON.stringify(a.state.batchIntakes)===original,items:a.state.lastPrepared.items.length,groups:a.state.lastPrepared.email_groups.length,options:element('#prepared-email-target').innerHTML}));
""")
        self.assertTrue(result['unchanged'])
        self.assertEqual((result['items'],result['groups']),(6,2))
        self.assertIn('5 requests from one source',result['options'])
        for call in result['calls']:
            self.assertEqual(call['body']['email_grouping'],'source')
            self.assertFalse(call['body']['packet_mode'])
            self.assertEqual(len(call['body']['intakes']),6)
        self.assertEqual(result['calls'][1]['body']['preflight_review'],{'token':'fictional-preflight'})

    def test_group_member_preview_changes_only_displayed_pdf_and_immutable_facts(self):
        result=self.run_js("""
const prepared=groupedPrepare(),original=JSON.stringify(prepared);a.state.currentIntake=alpha;a.renderPrepared(prepared);a.selectPreparedEmailTarget(1);
element('#gmail_handoff_reviewed').checked=true;element('#prepared-email-member').value='4';element('#prepared-email-member').listeners.change({target:element('#prepared-email-member')});
console.log(JSON.stringify({summary:element('#prepared-email-target-summary').textContent,members:element('#prepared-email-target-members').innerHTML,preview:element('#prepared-email-target-preview').innerHTML,args:JSON.parse(element('#prepared-email-target-args').textContent),selected:a.preparedTargetIntake(),target:a.preparedRecordTarget().draft_payload,unchanged:JSON.stringify(prepared)===original,current:a.state.currentIntake,ack:element('#gmail_handoff_reviewed').checked}));
""")
        self.assertIn('5 requests in one email',result['summary'])
        self.assertIn('beta@example.test',result['summary'])
        self.assertNotIn('alpha@example.test',result['summary'])
        for number in range(711,716):
            self.assertIn(f'{number}/26.0TSTXX',result['members'])
        self.assertIn('/fictional/request-5.png',result['preview'])
        self.assertEqual(result['selected']['case_number'],'715/26.0TSTXX')
        self.assertEqual(result['current']['case_number'],'710/26.0TSTXX')
        self.assertEqual(result['target'],'/fictional/group-1.json')
        self.assertEqual(len(result['args']['attachment_files']),5)
        self.assertTrue(result['unchanged'])
        self.assertTrue(result['ack'])

    def test_group_copy_handoff_create_and_record_use_composite_signed_payload(self):
        result=self.run_js("""
a.renderPrepared(groupedPrepare());a.selectPreparedEmailTarget(1);await a.copyPreparedDraftArgs();await a.buildManualHandoffPacket();await a.activeCheck();
element('#record_draft_id').value='five-member-draft';element('#gmail_handoff_reviewed').checked=true;await a.recordPreparedDraftFromForm();await a.createGmailApiDraft();
console.log(JSON.stringify({calls,copied,recorded:a.state.locallyRecordedPayload}));
""")
        args=json.loads(result['copied'][0])
        self.assertEqual(args['to'],'beta@example.test')
        self.assertEqual(len(args['attachment_files']),5)
        routes={call['url']:call['body'] for call in result['calls']}
        for route in ['/api/gmail/manual-handoff','/api/drafts/record','/api/gmail/drafts/create']:
            self.assertEqual(routes[route]['payload'],'/fictional/group-1.json')
            self.assertEqual(routes[route]['prepared_review_token'],'fictional-group-token')
        self.assertEqual(len(routes['/api/drafts/active-check']['underlying_requests']),5)
        self.assertNotIn('intake',routes['/api/drafts/active-check'])
        self.assertEqual(result['recorded'],'/fictional/group-1.json')

    def test_group_active_check_blocks_whole_email_when_last_member_is_active(self):
        result=self.run_js("""
a.renderPrepared(groupedPrepare());a.selectPreparedEmailTarget(1);
routeOverrides['/api/drafts/active-check']=body=>({status:'blocked',can_create_new_draft:false,message:'A sibling is active',member_checks:body.underlying_requests.map((row,index)=>({...row,status:index===4?'active_draft':'clear',message:index===4?'Sibling draft must be corrected':'Clear'}))});
await a.activeCheck();let handoffError='',createError='';try{await a.buildManualHandoffPacket();}catch(e){handoffError=e.message;}element('#gmail_handoff_reviewed').checked=true;try{await a.createGmailApiDraft();}catch(e){createError=e.message;}
console.log(JSON.stringify({calls,html:element('#draft-lifecycle-body').innerHTML,handoffError,createError}));
""")
        self.assertEqual(len(result['calls']),1)
        self.assertEqual(len(result['calls'][0]['body']['underlying_requests']),5)
        self.assertIn('715/26.0TSTXX',result['html'])
        self.assertIn('Sibling draft must be corrected',result['html'])
        self.assertIn('member request needs correction',result['handoffError'])
        self.assertIn('member request needs correction',result['createError'])

    def test_grouping_change_invalidates_preflight_and_discards_old_mode_response(self):
        result=self.run_js("""
a.state.batchIntakes=photoRows();a.renderPrepared(groupedPrepare());const signature=a.batchPreflightSignature();let release;deferredRoute='/api/prepare/preflight';deferred=new Promise(resolve=>release=resolve);const pending=a.preflightBatchIntakes();
element('#batch-email-grouping').value='individual';element('#batch-email-grouping').listeners.change();const changed=a.batchPreflightSignature();release();const answer=await pending;
console.log(JSON.stringify({discarded:answer===null,cleared:a.state.lastPrepared===null,preflight:a.state.batchPreflight,changed:signature!==changed,grouping:a.currentBatchEmailGrouping(),payload:element('#record_payload').value}));
""")
        self.assertEqual(result,{'discarded':True,'cleared':True,'preflight':None,'changed':True,'grouping':'individual','payload':''})

    def test_grouped_late_handoff_active_and_create_responses_stay_with_old_email(self):
        for operation in ['handoff','active','create_success','create_failure']:
            with self.subTest(operation=operation):
                result=self.run_js("""
a.renderPrepared(groupedPrepare());a.selectPreparedEmailTarget(1);element('#gmail_handoff_reviewed').checked=true;let release;deferred=new Promise(resolve=>release=resolve);
const operation=OPERATION;const pending=operation==='handoff'?a.buildManualHandoffPacket():operation==='active'?element('#check-active-drafts').listeners.click():element('#create-gmail-api-draft').listeners.click();
a.selectPreparedEmailTarget(0);element('#status-pill').textContent='fresh-alpha';element('#gmail-api-result').innerHTML='fresh-panel';if(operation==='create_failure')responseFailure='Old five-case email refused';release();await pending;
console.log(JSON.stringify({payload:element('#record_payload').value,ids:element('#record_draft_id').value,checked:element('#gmail_handoff_reviewed').checked,handoff:a.state.lastManualHandoff,lifecycle:a.state.draftLifecycle,status:element('#status-pill').textContent,panel:element('#gmail-api-result').innerHTML,oldPayload:calls[0].body.payload,oldMembers:calls[0].body.underlying_requests?.length,alert:element('#alert').textContent}));
""".replace('OPERATION',json.dumps(operation)))
                self.assertEqual(result['payload'],'/fictional/group-0.json')
                self.assertEqual(result['ids'],'')
                self.assertFalse(result['checked'])
                self.assertIsNone(result['handoff'])
                self.assertIsNone(result['lifecycle'])
                self.assertEqual(result['status'],'fresh-alpha')
                self.assertEqual(result['panel'],'fresh-panel')
                if operation=='active':
                    self.assertEqual(result['oldMembers'],5)
                else:
                    self.assertEqual(result['oldPayload'],'/fictional/group-1.json')

    def test_malformed_group_membership_never_falls_back_to_individual_payload(self):
        for indices in [[1,1],[1,99],[]]:
            with self.subTest(indices=indices):
                result=self.run_js("""
const prepared=groupedPrepare();prepared.email_groups[1].member_indices=INDICES;a.renderPrepared(prepared);a.selectPreparedEmailTarget(1);let error='';try{await a.copyPreparedDraftArgs();}catch(e){error=e.message;}
console.log(JSON.stringify({target:a.preparedRecordTarget(),summary:element('#prepared-email-target-summary').textContent,copied:copied.length,error,calls:calls.length}));
""".replace('INDICES',json.dumps(indices)))
                self.assertIsNone(result['target'])
                self.assertIn('membership is incomplete',result['summary'])
                self.assertEqual(result['copied'],0)
                self.assertEqual(result['calls'],0)

    def test_different_photo_targets_are_retained_even_with_same_recipient(self):
        result=self.run_js("""
const prepared=groupedPrepare();prepared.email_groups[1].recipient=prepared.email_groups[0].recipient;prepared.email_groups[1].gmail_create_draft_args.to=prepared.email_groups[0].recipient;a.renderPrepared(prepared);a.selectPreparedEmailTarget(1);
console.log(JSON.stringify({targets:g.preparedEmailTargets(prepared).length,payload:a.preparedRecordTarget().draft_payload,members:a.preparedTargetIntakes().length,options:element('#prepared-email-target').innerHTML}));
""")
        self.assertEqual(result['targets'],2)
        self.assertEqual(result['payload'],'/fictional/group-1.json')
        self.assertEqual(result['members'],5)

    def test_prepared_group_replacement_keeps_all_claims_and_superseding_ids(self):
        result=self.run_js("""
const prepared=groupedPrepare();prepared.correction_mode=true;prepared.correction_reason='Corrected contact for all photo cases';prepared.items.forEach((item,index)=>item.draft_lifecycle={active_gmail_drafts:[{draft_id:'previous-'+index}],duplicate_records:[]});
a.renderPrepared(prepared);a.selectPreparedEmailTarget(1);const oldIds=element('#record_supersedes').value;await a.buildManualHandoffPacket();
a.state.currentIntake=alpha;a.fillFormFromIntake(alpha);await a.prepareIntake({correctionMode:true});
console.log(JSON.stringify({oldIds,calls}));
""")
        self.assertEqual(set(result['oldIds'].split(', ')),{f'previous-{index}' for index in range(1,6)})
        handoff=result['calls'][0]['body']
        self.assertEqual(set(handoff['supersedes']),{f'previous-{index}' for index in range(1,6)})
        self.assertEqual(handoff['correction_reason'],'Corrected contact for all photo cases')
        for call in result['calls'][1:]:
            body=call['body']
            self.assertTrue(body['correction_mode'])
            self.assertEqual(body['email_grouping'],'source')
            self.assertEqual(len(body['intakes']),5)
            self.assertEqual([row['claim_transport'] for row in body['intakes']],[True,False,False,False,False])
            self.assertEqual(body['correction_reason'],'Corrected contact for all photo cases')

    def test_photo_replacement_button_refreshes_all_children_before_atomic_prepare(self):
        result=self.run_js("""
const rows=photoRows().slice(1);a.state.sourceCaseCandidates=rows.map(row=>({candidate_intake:row,review:{status:'duplicate',duplicate:{status:'drafted'},intake:row,effective_intake:row,questions:[]},needs_review:false}));a.state.sourceCaseSelectedIndex=0;a.state.currentIntake=rows[0];a.fillFormFromIntake(rows[0]);element('#source-correction-reason').value='Correct all five photo recipients';
routeOverrides['/api/review']=body=>({status:'duplicate',duplicate:{status:'drafted'},intake:body.intake,effective_intake:body.intake,questions:[]});
await element('#prepare-source-email-replacement').listeners.click();console.log(JSON.stringify({calls,queue:a.state.batchIntakes.length,status:element('#status-pill').textContent}));
""")
        reviews=[call for call in result['calls'] if call['url']=='/api/review']
        self.assertEqual(len(reviews),5)
        self.assertEqual(result['queue'],0)
        for call in result['calls'][5:]:
            self.assertEqual(len(call['body']['intakes']),5)
            self.assertTrue(call['body']['correction_mode'])
            self.assertEqual(call['body']['correction_reason'],'Correct all five photo recipients')
            self.assertEqual(call['body']['email_grouping'],'source')
        self.assertEqual(result['status'],'prepared')

    def test_photo_replacement_with_unresolved_child_creates_no_artifacts(self):
        result=self.run_js("""
const rows=photoRows().slice(1);a.state.sourceCaseCandidates=rows.map(row=>({candidate_intake:row,review:{status:'duplicate',duplicate:{status:'drafted'},intake:row,effective_intake:row,questions:[]},needs_review:false}));a.state.sourceCaseSelectedIndex=0;a.state.currentIntake=rows[0];a.fillFormFromIntake(rows[0]);element('#source-correction-reason').value='Correct all five photo recipients';
routeOverrides['/api/review']=body=>({status:body.intake.case_number.startsWith('715/')?'needs_info':'duplicate',intake:body.intake,effective_intake:body.intake,questions:body.intake.case_number.startsWith('715/')?[{field:'service_date'}]:[]});
await element('#prepare-source-email-replacement').listeners.click();console.log(JSON.stringify({routes:calls.map(call=>call.url),prepared:a.state.lastPrepared,status:element('#status-pill').textContent,alert:element('#alert').textContent}));
""")
        self.assertEqual(result['routes'],['/api/review']*5)
        self.assertIsNone(result['prepared'])
        self.assertEqual(result['status'],'blocked')
        self.assertIn('Resolve every case',result['alert'])


if __name__=='__main__':
    unittest.main()
