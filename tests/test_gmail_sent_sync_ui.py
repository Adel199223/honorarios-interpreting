"""Recent Work sent-status sync uses synthetic local responses only."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
import fs from 'node:fs';import vm from 'node:vm';
const elements=new Map(),calls=[],opened=[],events=[];
const classes=()=>({values:new Set(),toggle(name,on){if(on??!this.values.has(name))this.values.add(name);else this.values.delete(name)},contains(name){return this.values.has(name)},add(name){this.values.add(name)},remove(name){this.values.delete(name)}});
const element=selector=>{
 if(!elements.has(selector))elements.set(selector,{id:selector.slice(1),listeners:{},children:[],dataset:{},attributes:{},value:'',disabled:false,textContent:'',innerHTML:'',className:'',classList:classes(),parentElement:{classList:classes()},
  addEventListener(name,listener){this.listeners[name]=listener},click(){return this.listeners.click?.()},replaceChildren(...nodes){this.children=[...nodes]},append(node){this.children.push(node)},
  setAttribute(name,value){this.attributes[name]=String(value)},getAttribute(name){return this.attributes[name]||''},removeAttribute(name){delete this.attributes[name]}});
 return elements.get(selector);
};
let now=100000;
class Clock extends Date {static now(){return now}}
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const flush=async()=>{for(let i=0;i<10;i+=1)await Promise.resolve()};
const safe={workspace_id:'synthetic-workspace',send_allowed:false,gmail_write_allowed:false};
let readiness={...safe,status:'ready',configured:true,connected:true,read_ready:true};
let result={...safe,status:'complete',checked_count:2,sent_count:0,unchanged_count:2,still_drafted_count:2,needs_review_count:0,error_count:0,warnings:[],checked_at:'2026-10-02T19:00:00Z'};
let reference={workspace_id:safe.workspace_id,duplicates:[],draft_log:[],service_profiles:{fictional:{description:'Fictional profile'}}};
let requestOverride=null;
const context={...guidance,console,JSON,Date:Clock,Promise,URL,
 document:{querySelector:element,getElementById:id=>element('#'+id),querySelectorAll:()=>[],createElement:tag=>({tag,textContent:''}),body:{dataset:{}}},
 window:{location:{hash:'',pathname:'/',search:''},history:{replaceState(){}},open:(...args)=>opened.push(args)},
 mockRequest:async(url,options={})=>{const body=options.body?JSON.parse(options.body):{};calls.push({url,body});if(requestOverride)return requestOverride(url,body);
  if(url==='/api/gmail/sent-sync/status')return readiness;if(url==='/api/gmail/sent-sync')return result;
  if(url==='/api/reference')return reference;if(url==='/api/gmail/oauth/start')return {status:'authorization_required',authorization_url:'https://accounts.google.com/fictional-consent'};
  throw new Error('Unexpected route '+url)},
};
let source=fs.readFileSync('honorarios_app/static/app.js','utf8').replace(/^import \{[\s\S]*?\} from "\.\/review_guidance\.js";/,'');
const full=source;source=source.slice(0,source.lastIndexOf('\nbindNavigation();'));
for(const id of ['#gmail-sent-sync-now','#gmail-sent-sync-enable']){
 const start=full.indexOf(`$("${id}").addEventListener(`);if(start<0)throw new Error('Missing production sync action');source+='\n'+full.slice(start).split('\n')[0];
}
source+='\nrequestJson=this.mockRequest;renderReference=()=>events.push("full-reference-render");renderAiStatus=()=>{};renderGmailStatus=()=>events.push("gmail-status-render");renderBackupStatus=()=>{};initializeWorkspaceDraft=id=>{state.workspaceDraft.workspaceId=id};';
source+='\nthis.api={state,showPanel,loadReference,syncGmailSentStatus,enableGmailSentSync,renderGmailSentSync,refreshSentSyncHistory,renderHistoryRecords,startGmailOAuth,syncServerConnectionGates};';
context.events=events;vm.runInNewContext(source,context);const a=context.api;
a.state.reference={...reference};a.state.workspaceDraft.workspaceId=safe.workspace_id;
a.state.gmailStatus={connected:true,configured:true,manual_handoff_ready:true};
"""


class GmailSentSyncUiTests(unittest.TestCase):
    def run_js(self, body):
        script = 'import * as guidance from ' + json.dumps((ROOT / 'honorarios_app/static/review_guidance.js').as_uri()) + ';\n'
        process = subprocess.run(['node', '--input-type=module', '-'], input=script + HARNESS + body,
                                 text=True, encoding='utf-8', capture_output=True, cwd=ROOT, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_history_entry_throttles_automatic_checks_and_other_routes_do_not_sync(self):
        result = self.run_js("""
a.showPanel('new-job');a.showPanel('references');const before=calls.length;
a.showPanel('history');await a.state.gmailSentSync.pending;a.showPanel('history');
a.showPanel('new-job');a.showPanel('history');await flush();const withinMinute=calls.length;
now+=60001;a.showPanel('new-job');a.showPanel('history');await a.state.gmailSentSync.pending;
console.log(JSON.stringify({before,withinMinute,calls,summary:element('#gmail-sent-sync-summary').textContent}));
""")
        self.assertEqual(result['before'], 0)
        self.assertEqual(result['withinMinute'], 2)
        self.assertEqual([row['url'] for row in result['calls']], ['/api/gmail/sent-sync/status', '/api/gmail/sent-sync'] * 2)
        self.assertEqual(result['calls'][1]['body'], {'workspace_id': 'synthetic-workspace', 'force': False})

    def test_manual_force_bypasses_throttle_but_shares_active_request(self):
        result = self.run_js("""
a.showPanel('history');await a.state.gmailSentSync.pending;
const gate=deferred();requestOverride=(url)=>url.endsWith('/status')?gate.promise:result;
const first=element('#gmail-sent-sync-now').click(),second=element('#gmail-sent-sync-now').click();
const same=first===second,disabled=element('#gmail-sent-sync-now').disabled;gate.resolve(readiness);await first;
console.log(JSON.stringify({same,disabled,calls,afterDisabled:element('#gmail-sent-sync-now').disabled}));
""")
        self.assertTrue(result['same'])
        self.assertTrue(result['disabled'])
        self.assertFalse(result['afterDisabled'])
        self.assertEqual(len(result['calls']), 4)
        self.assertEqual(result['calls'][-1]['body']['force'], True)

    def test_initial_history_route_waits_for_reference_workspace_then_checks_once(self):
        result = self.run_js("""
a.state.workspaceDraft.workspaceId='';a.state.reference=null;a.showPanel('#history');const before=calls.length;
await a.loadReference();await a.state.gmailSentSync.pending;
console.log(JSON.stringify({before,calls,workspace:a.state.workspaceDraft.workspaceId}));
""")
        self.assertEqual(result['before'], 0)
        self.assertEqual([row['url'] for row in result['calls']], ['/api/reference', '/api/gmail/sent-sync/status', '/api/gmail/sent-sync'])
        self.assertEqual(result['workspace'], 'synthetic-workspace')

    def test_missing_permission_opens_purpose_oauth_without_resetting_compose_connection(self):
        result = self.run_js("""
readiness={...readiness,status:'authorization_required',read_ready:false};a.showPanel('history');await a.state.gmailSentSync.pending;
const permissionShown=!element('#gmail-sent-sync-enable').classList.contains('hidden'),before={...a.state.gmailStatus};
await element('#gmail-sent-sync-enable').click();const notice=element('#gmail-sent-sync-summary').textContent,fallback=element('#gmail-sent-sync-authorization').attributes.href;
readiness={...readiness,status:'ready',read_ready:true};await element('#gmail-sent-sync-now').click();
console.log(JSON.stringify({permissionShown,calls,opened,notice,fallback,clearedFallback:!a.state.gmailSentSync.authorizationUrl,connectionUnchanged:JSON.stringify(before)===JSON.stringify(a.state.gmailStatus),events}));
""")
        self.assertTrue(result['permissionShown'])
        self.assertEqual(result['calls'][1], {'url': '/api/gmail/oauth/start', 'body': {'purpose': 'sent_sync'}})
        self.assertEqual(len(result['opened']), 1)
        self.assertIn('Then click Sync now', result['notice'])
        self.assertEqual(result['fallback'], 'https://accounts.google.com/fictional-consent')
        self.assertTrue(result['clearedFallback'])
        self.assertTrue(result['connectionUnchanged'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['calls'][-1]['body']['force'], True)

    def test_history_refresh_preserves_active_source_prepared_queue_profiles_and_recovery_inputs(self):
        result = self.run_js("""
a.state.currentIntake={case_number:'701/26.0TSTXX',personal_profile_id:'chosen'};a.state.lastPrepared={payload:'prepared'};a.state.lastReview={status:'ready'};a.state.batchIntakes=[{case_number:'702/26.0TSTXX'}];a.state.sourceCaseCandidates=[{source:'original'}];a.state.currentPersonalProfile={id:'chosen'};
element('#profile').value='chosen-service';element('#personal_profile_id').value='chosen-personal';element('#source-file').files=[{name:'retained.jpg'}];element('#pending-recovery-input').value='entered-id';
const preserve=()=>JSON.stringify({intake:a.state.currentIntake,prepared:a.state.lastPrepared,review:a.state.lastReview,queue:a.state.batchIntakes,cases:a.state.sourceCaseCandidates,personal:a.state.currentPersonalProfile,profile:element('#profile').value,personalChoice:element('#personal_profile_id').value,source:element('#source-file').files,recovery:element('#pending-recovery-input').value,revision:a.state.workflowRevision});
const before=preserve();result={...result,sent_count:1,unchanged_count:1};reference={...reference,duplicates:[{case_number:'700/26.0TSTXX',service_date:'2026-10-01',status:'sent'}],draft_log:[{case_number:'700/26.0TSTXX',service_date:'2026-10-01',status:'sent'}],service_profiles:{different:{description:'Do not apply'}}};
a.showPanel('history');await a.state.gmailSentSync.pending;
console.log(JSON.stringify({preserved:before===preserve(),duplicates:a.state.reference.duplicates,profileKeys:Object.keys(a.state.reference.service_profiles),list:element('#duplicate-list').innerHTML,events,calls}));
""")
        self.assertTrue(result['preserved'])
        self.assertEqual(result['duplicates'][0]['status'], 'sent')
        self.assertEqual(result['profileKeys'], ['fictional'])
        self.assertIn('700/26.0TSTXX', result['list'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['calls'][-1]['url'], '/api/reference')

    def test_late_runtime_results_and_oauth_popup_are_discarded(self):
        result = self.run_js("""
const gate=deferred();requestOverride=url=>url.endsWith('/status')?readiness:gate.promise;
a.showPanel('history');await flush();a.state.workspaceDraft.workspaceId='different-runtime';gate.resolve({...result,sent_count:1});await a.state.gmailSentSync.pending;
const ignored=a.state.gmailSentSync.result===null,noReference=calls.every(row=>row.url!=='/api/reference');
a.state.workspaceDraft.workspaceId=safe.workspace_id;const authGate=deferred();requestOverride=()=>authGate.promise;const auth=a.enableGmailSentSync();a.state.workspaceDraft.runtimeChanged=true;
authGate.resolve({authorization_url:'https://accounts.google.com/fictional-consent'});await auth;
console.log(JSON.stringify({ignored,noReference,opened,disabled:element('#gmail-sent-sync-now').disabled}));
""")
        self.assertTrue(result['ignored'])
        self.assertTrue(result['noReference'])
        self.assertEqual(result['opened'], [])
        self.assertTrue(result['disabled'])

    def test_mismatched_or_unsafe_responses_never_post_or_update_history(self):
        for changed in [{'workspace_id': 'other'}, {'gmail_write_allowed': True}, {'send_allowed': True}]:
            with self.subTest(changed=changed):
                result = self.run_js('readiness={...readiness,...' + json.dumps(changed) + """};
a.showPanel('history');await a.state.gmailSentSync.pending;
console.log(JSON.stringify({calls,result:a.state.gmailSentSync.result,summary:element('#gmail-sent-sync-summary').textContent}));
""")
                self.assertEqual(len(result['calls']), 1)
                self.assertIsNone(result['result'])
                self.assertIn('could not be verified', result['summary'])

    def test_partial_counts_and_warnings_are_safe_and_unknown_is_not_zero(self):
        result = self.run_js("""
result={...result,status:'partial',checked_count:3,sent_count:0,unchanged_count:3,still_drafted_count:1,needs_review_count:1,error_count:1,warnings:['<script>fictional warning</script>']};
a.showPanel('history');await a.state.gmailSentSync.pending;
const counts=['checked','sent','unchanged','drafted','review','errors'].map(name=>element('#gmail-sent-sync-'+name).textContent),summary=element('#gmail-sent-sync-summary').textContent,warningText=element('#gmail-sent-sync-warnings').children[0].textContent;
a.state.gmailSentSync.result={status:'partial',sent_count:-1,checked_count:true};a.renderGmailSentSync();
console.log(JSON.stringify({counts,summary,warningText,unknown:['checked','sent','unchanged'].map(name=>element('#gmail-sent-sync-'+name).textContent),checked:element('#gmail-sent-sync-checked-at').textContent,calls}));
""")
        self.assertEqual(result['counts'], ['3', '0', '3', '1', '1', '1'])
        self.assertIn('Unverified requests keep their existing status', result['summary'])
        self.assertEqual(result['warningText'], '<script>fictional warning</script>')
        self.assertEqual(result['unknown'], ['Unknown'] * 3)
        self.assertIn('Not checked yet', result['checked'])
        self.assertFalse(any(row['url'] == '/api/reference' for row in result['calls']))

    def test_automatic_failure_stays_in_panel_and_disconnected_runtime_cannot_start(self):
        result = self.run_js("""
requestOverride=()=>{throw new Error('provider failure with private detail')};a.showPanel('history');await a.state.gmailSentSync.pending;
const summary=element('#gmail-sent-sync-summary').textContent;
a.state.serverConnection.connected=false;await element('#gmail-sent-sync-now').click();await element('#gmail-sent-sync-enable').click();
console.log(JSON.stringify({summary,calls,events,disabled:element('#gmail-sent-sync-now').disabled}));
""")
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['events'], [])
        self.assertEqual(result['summary'], 'Sent-status sync could not finish. Try Sync now.')
        self.assertTrue(result['disabled'])

    def test_partial_local_commit_refreshes_history_even_without_completed_sent_count(self):
        result = self.run_js("""
a.state.lastPrepared={payload:'retained'};a.state.currentIntake={source_sha256:'retained-source'};
result={...result,status:'partial',sent_count:0,managed_data_changed:true,needs_review_count:1,error_count:1,warnings:['Local recording needs another check.']};
reference={...reference,duplicates:[{case_number:'700/26.0TSTXX',service_date:'2026-10-01',status:'sent'}],draft_log:[{case_number:'700/26.0TSTXX',service_date:'2026-10-01',status:'drafted'}]};
a.showPanel('history');await a.state.gmailSentSync.pending;
console.log(JSON.stringify({calls,duplicate:a.state.reference.duplicates[0].status,draft:a.state.reference.draft_log[0].status,summary:element('#gmail-sent-sync-summary').textContent,prepared:a.state.lastPrepared,intake:a.state.currentIntake}));
""")
        self.assertEqual(result['calls'][-1]['url'], '/api/reference')
        self.assertEqual(result['duplicate'], 'sent')
        self.assertEqual(result['draft'], 'drafted')
        self.assertIn('need review', result['summary'])
        self.assertEqual(result['prepared'], {'payload': 'retained'})
        self.assertEqual(result['intake'], {'source_sha256': 'retained-source'})

    def test_history_refresh_discards_old_runtime_and_newer_reference_results(self):
        result = self.run_js("""
const gate=deferred();requestOverride=()=>gate.promise;
const pending=a.refreshSentSyncHistory(safe.workspace_id);a.state.reference={...a.state.reference,duplicates:[{marker:'newer-local-history'}]};
gate.resolve({...reference,duplicates:[{marker:'stale-response'}]});const first=await pending;
requestOverride=async()=>({...reference,workspace_id:'other-runtime',duplicates:[{marker:'wrong-runtime'}]});const second=await a.refreshSentSyncHistory(safe.workspace_id);
console.log(JSON.stringify({first,second,duplicates:a.state.reference.duplicates,events}));
""")
        self.assertFalse(result['first'])
        self.assertFalse(result['second'])
        self.assertEqual(result['duplicates'], [{'marker': 'newer-local-history'}])
        self.assertEqual(result['events'], [])

    def test_blocked_popup_has_safe_fallback_and_unexpected_authorization_url_is_rejected(self):
        result = self.run_js("""
context.window.open=()=>null;a.state.gmailSentSync.status={...readiness,status:'authorization_required',read_ready:false};
await a.enableGmailSentSync();const link=element('#gmail-sent-sync-authorization').attributes.href,visible=!element('#gmail-sent-sync-authorization').classList.contains('hidden');
requestOverride=async()=>({authorization_url:'javascript:alert(1)'});await a.enableGmailSentSync();
console.log(JSON.stringify({link,visible,noUnsafeLink:!element('#gmail-sent-sync-authorization').attributes.href,summary:element('#gmail-sent-sync-summary').textContent,opened}));
""")
        self.assertEqual(result['link'], 'https://accounts.google.com/fictional-consent')
        self.assertTrue(result['visible'])
        self.assertTrue(result['noUnsafeLink'])
        self.assertIn('could not be opened', result['summary'])
        self.assertEqual(result['opened'], [])


if __name__ == '__main__':
    unittest.main()
