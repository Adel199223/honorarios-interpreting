"""Fictional browser-session recovery, isolated from private data and providers."""
import copy
import json
from pathlib import Path
import re
import subprocess
import unittest

from fastapi.testclient import TestClient
from honorarios_app.services import AppPaths, preflight_intakes
from honorarios_app.runtime import runtime_path_overrides
from honorarios_app.web import create_app
from honorarios_app.workspace_draft import validate_workspace_resume, workspace_runtime_id
from tests import test_source_email_groups as source_groups
from tests.test_email_routing_ui import HARNESS

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceDraftDomainTests(unittest.TestCase):
    setUp = source_groups.SourceEmailGroupsTests.setUp
    rows = source_groups.SourceEmailGroupsTests.rows

    def request(self):
        rows = self.rows()[1:]
        return {"workspace_id": workspace_runtime_id(self.paths), "snapshot": {
            "schema_version": 1, "current_intake": rows[2], "source_cases": [
                {"candidate_intake": row, "evidence": {"source": {"filename": "Fictional source title", "sha256": row['source_sha256']}},
                 "answers": f"1. Fictional answer {index}", "queued_key": ""} for index, row in enumerate(rows)],
            "selected_case": 2, "travel_choice": {"mode": "shared", "ownerIndex": 0, "groupId": "fictional-five-cases-one-visit"},
            "batch_intakes": rows, "current_evidence": {}, "email_grouping": "source", "packet_mode": False}}

    def client(self):
        return TestClient(create_app(**runtime_path_overrides(self.root)), base_url="http://127.0.0.1")

    def test_manual_visit_grouping_restores_inputs_without_preflight_or_draft_permissions(self):
        request = self.request()
        request['snapshot'].update(email_grouping='manual_visit', preflight_review={'token': 'old'}, gmail_handoff_reviewed=True)
        result = self.client().post('/api/workspace/resume', json=request)
        self.assertEqual(result.status_code, 200)
        saved = result.json()['snapshot']
        self.assertEqual(saved['email_grouping'], 'manual_visit')
        self.assertNotIn('preflight_review', saved)
        self.assertNotIn('gmail_handoff_reviewed', saved)

    def test_namespace_is_stable_opaque_and_changes_with_each_runtime_root(self):
        original = workspace_runtime_id(self.paths)
        self.assertRegex(original, r"^[a-f0-9]{64}$")
        self.assertEqual(self.client().get('/api/reference').json()['workspace_id'], original)
        for field in ('personal_profiles', 'duplicate_index', 'draft_log', 'source_upload_dir'):
            changed = copy.copy(self.paths)
            object.__setattr__(changed, field, getattr(changed, field).with_name('fictional-other'))
            self.assertNotEqual(workspace_runtime_id(changed), original)
        wrong = self.request(); wrong['workspace_id'] = 'f' * 64
        self.assertEqual(self.client().post('/api/workspace/resume', json=wrong).status_code, 400)

    def test_all_five_inputs_answers_claim_bindings_survive_without_approvals(self):
        request = self.request()
        request['snapshot']['current_intake'].update(review_cleared_fields=['recipient_email'], prepared_review_token='fictional-old-approval', gmail_handoff_reviewed=True)
        request['snapshot']['current_evidence']['ai_recovery'] = {'fields': {'case_number': 'fictional'}, 'raw_response': 'must not restore', 'access_token': 'must not restore'}
        result = self.client().post('/api/workspace/resume', json=request)
        self.assertEqual(result.status_code, 200)
        saved = result.json()['snapshot']
        self.assertNotIn('fictional-old-approval', json.dumps(saved))
        self.assertNotIn('must not restore', json.dumps(saved))
        self.assertEqual(saved['current_intake']['review_cleared_fields'], ['recipient_email'])
        self.assertEqual([row['answers'] for row in saved['source_cases']], [f'1. Fictional answer {i}' for i in range(5)])
        self.assertEqual(sum(row['claim_transport'] for row in saved['batch_intakes']), 1)
        self.assertEqual({row['travel_group_id'] for row in saved['batch_intakes']}, {'fictional-five-cases-one-visit'})
        self.assertEqual(preflight_intakes(saved['batch_intakes'], self.paths, email_grouping='source')['status'], 'ready')

    def test_missing_files_are_reported_and_facts_salvaged_but_outside_paths_never_reused(self):
        request = self.request()
        self.paths.source_upload_dir.mkdir(parents=True, exist_ok=True)
        valid = self.paths.source_upload_dir / 'fictional-proof.pdf'; valid.write_bytes(b'fictional')
        outside = self.root / 'fictional-outside.pdf'; outside.write_bytes(b'fictional')
        row = request['snapshot']['current_intake']
        row['source_file'] = str(self.paths.source_upload_dir / 'missing-original.jpg')
        row['additional_attachment_files'] = [str(valid), str(outside), str(self.paths.source_upload_dir / 'missing-proof.pdf')]
        result = self.client().post('/api/workspace/resume', json=request).json()
        self.assertEqual(result['snapshot']['current_intake']['additional_attachment_files'], [str(valid.resolve())])
        self.assertEqual(result['missing_attachments'], ['fictional-outside.pdf', 'missing-proof.pdf'])
        self.assertEqual(result['missing_sources'], ['missing-original.jpg'])
        self.assertEqual(result['snapshot']['current_intake']['case_number'], row['case_number'])

    def test_missing_profile_requires_explicit_available_replacement(self):
        request = self.request()
        expected = request['snapshot']['current_intake']['personal_profile_id']
        request['snapshot']['current_intake']['personal_profile_id'] = 'fictional-removed-profile'
        first = self.client().post('/api/workspace/resume', json=request).json()
        self.assertEqual(first['unavailable_profiles'], ['fictional-removed-profile'])
        self.assertEqual(first['snapshot']['current_intake']['personal_profile_id'], 'fictional-removed-profile')
        request['replacement_profile_id'] = expected
        second = self.client().post('/api/workspace/resume', json=request).json()
        self.assertEqual(second['unavailable_profiles'], [])
        self.assertEqual(second['snapshot']['current_intake']['personal_profile_id'], expected)

    def test_served_dependency_urls_share_the_app_asset_version(self):
        html = self.client().get('/').text
        version = re.search(r'/static/app.js\?v=([^" ]+)', html).group(1)
        self.assertIn(f'"/static/workspace_draft.js":"/static/workspace_draft.js?v={version}"', html)
        self.assertEqual(self.client().get('/static/workspace_draft.js?v='+version).status_code, 200)

    def test_resume_offer_is_outside_the_reordered_source_panel(self):
        from html.parser import HTMLParser
        class Parents(HTMLParser):
            def __init__(self):
                super().__init__(); self.stack = []; self.ancestors = []
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if values.get('id') == 'workspace-draft-status': self.ancestors.append(list(self.stack))
                if tag not in {'input', 'img', 'br', 'meta', 'link', 'hr'}: self.stack.append((tag, values.get('id')))
            def handle_endtag(self, tag):
                for index in range(len(self.stack)-1, -1, -1):
                    if self.stack[index][0] == tag:
                        self.stack = self.stack[:index]; break
        parser = Parents(); parser.feed(self.client().get('/').text)
        self.assertEqual(len(parser.ancestors), 1)
        self.assertIn(('section', 'panel-new-job'), parser.ancestors[0])
        self.assertNotIn(('section', 'interpretation-intake-panel'), parser.ancestors[0])


class WorkspaceDraftUiTests(unittest.TestCase):
    def run_js(self, body):
        harness = HARNESS.replace("this.api={", "this.api={initializeWorkspaceDraft,currentWorkspaceDraft,saveWorkspaceDraft,discardWorkspaceDraft,resumeWorkspaceDraft,resetWorkspace,resetReview,requestJson,saveSourceCaseAnswers,applyNumberedAnswers,")
        harness = harness.replace("vm.runInNewContext(app,context)", "app+='\\n'+listenerSource('#workspace-draft-status');vm.runInNewContext(app,context)")
        harness = harness.replace("if(url==='/api/review')", "if(url==='/api/workspace/resume')result={snapshot:body.snapshot,missing_attachments:[],unavailable_profiles:[]};else if(url==='/api/review')")
        harness = harness.replace("else if(url==='/api/review')", "else if(url==='/api/review/apply-answers')result={status:'ready',intake:body.intake,applied_fields:['case_number'],next_safe_action:{state:'prepare_pdf'}};else if(url==='/api/review')")
        script = 'import * as g from '+json.dumps((ROOT/'honorarios_app/static/review_guidance.js').as_uri())+';\n'+harness+"""
const storage=new Map();context.window.localStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
context.window.location={hash:'#new-job'};
const workspace='a'.repeat(64);a.state.reference={personal_profiles:{profiles:[{id:'main',display_name:'Fictional profile'}]}};
const savedRecord=snapshot=>JSON.stringify({schema_version:1,workspace_id:workspace,snapshot});
const makeSnapshot=()=>g.workspaceDraftSnapshot({currentIntake:alpha,sourceCaseCandidates:[],batchIntakes:[alpha,beta]},{});
"""+body
        result = subprocess.run(['node','--input-type=module','-'], input=script, text=True, encoding='utf-8', capture_output=True, cwd=ROOT, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_resume_requires_explicit_choice_and_never_restores_preparation(self):
        result = self.run_js("""
const snapshot=makeSnapshot();snapshot.current_intake.source_title='Fictional custom title';snapshot.current_intake.review_cleared_fields=['service_date'];snapshot.answers='1. Unfinished answer';
storage.set(g.workspaceDraftStorageKey(workspace),savedRecord(snapshot));a.initializeWorkspaceDraft(workspace);
const before={current:a.state.currentIntake,queue:a.state.batchIntakes.length};
await a.resumeWorkspaceDraft();await Promise.resolve();
console.log(JSON.stringify({before,current:a.state.currentIntake,queue:a.state.batchIntakes.length,answers:element('#numbered-answers').value,
 prepared:a.state.lastPrepared,preflight:a.state.batchPreflight,ack:element('#gmail_handoff_reviewed').checked,disabled:element('#prepare-batch-intakes').disabled,calls}));
""")
        self.assertEqual(result['before'], {'current': None, 'queue': 0})
        self.assertEqual(result['current']['source_title'], 'Fictional custom title')
        self.assertEqual(result['current']['review_cleared_fields'], ['service_date'])
        self.assertEqual(result['queue'], 2)
        self.assertEqual(result['answers'], '1. Unfinished answer')
        self.assertIsNone(result['prepared']); self.assertIsNone(result['preflight'])
        self.assertFalse(result['ack']); self.assertTrue(result['disabled'])
        self.assertEqual([row['url'] for row in result['calls']], ['/api/workspace/resume'])

    def test_manual_visit_choice_survives_browser_snapshot_resume_with_fresh_preflight_required(self):
        result = self.run_js("""
const snapshot=g.workspaceDraftSnapshot({currentIntake:alpha,batchIntakes:[alpha,beta]}, {email_grouping:'manual_visit'});
storage.set(g.workspaceDraftStorageKey(workspace),savedRecord(snapshot));a.initializeWorkspaceDraft(workspace);
await a.resumeWorkspaceDraft();
console.log(JSON.stringify({saved:snapshot.email_grouping,selected:element('#batch-email-grouping').value,
 grouping:a.currentBatchEmailGrouping(),preflight:a.state.batchPreflight,prepared:a.state.lastPrepared,
 disabled:element('#prepare-batch-intakes').disabled,calls}));
""")
        self.assertEqual(result['saved'], 'manual_visit')
        self.assertEqual(result['selected'], 'manual_visit')
        self.assertEqual(result['grouping'], 'manual_visit')
        self.assertIsNone(result['preflight'])
        self.assertIsNone(result['prepared'])
        self.assertTrue(result['disabled'])
        self.assertEqual([row['url'] for row in result['calls']], ['/api/workspace/resume'])

    def test_manual_fields_save_without_building_and_restore_before_fresh_review(self):
        result = self.run_js("""
a.initializeWorkspaceDraft(workspace);element('#case_number').value='715/26.0TSTXX';element('#source_text').value='Fictional typed source';element('#personal_profile_id').value='main';
element('#intake-form').listeners.input({target:element('#case_number')});a.saveWorkspaceDraft();
const saved=JSON.parse(storage.get(g.workspaceDraftStorageKey(workspace)));
a.state.workspaceDraft={workspaceId:'',initialized:false};a.initializeWorkspaceDraft(workspace);element('#case_number').value='';
await a.resumeWorkspaceDraft();console.log(JSON.stringify({saved:saved.snapshot.manual_fields,current:a.state.currentIntake,case:element('#case_number').value,text:element('#source_text').value,panel:element('#workspace-draft-status').innerHTML}));
""")
        self.assertEqual(result['saved']['case_number'], '715/26.0TSTXX')
        self.assertIsNone(result['current'])
        self.assertEqual(result['case'], '715/26.0TSTXX')
        self.assertEqual(result['text'], 'Fictional typed source')
        self.assertIn('Review restored work', result['panel'])

    def test_manual_pending_answers_survive_resume_then_production_review_click(self):
        result = self.run_js("""
const answers='1. 850/26.0TSTXX\\n2. 2026-09-28';
const snapshot=makeSnapshot();snapshot.current_intake={...alpha,case_number:'',service_date:''};snapshot.batch_intakes=[];snapshot.answers=answers;
storage.set(g.workspaceDraftStorageKey(workspace),savedRecord(snapshot));a.initializeWorkspaceDraft(workspace);
// The real question textarea is replaced when its parent gets new innerHTML.
const card=element('#interpretation-review-home-result');Object.defineProperty(card,'innerHTML',{get(){return this._html||''},set(value){this._html=value;element('#home-numbered-answers').value='';element('#home-apply-numbered-answers').disabled=true}});
await a.resumeWorkspaceDraft();const resumed=element('#numbered-answers').value;
await element('#workspace-draft-status').listeners.click({target:{closest:selector=>selector==='#review-resumed-workspace'?{}:null}});
await Promise.resolve();
const reviewed={home:element('#home-numbered-answers').value,drawer:element('#numbered-answers').value,
 saved:JSON.parse(storage.get(g.workspaceDraftStorageKey(workspace))).snapshot.answers,disabled:element('#home-apply-numbered-answers').disabled};
const marker=fullApp.indexOf('const button = event.target.closest("#home-apply-numbered-answers")');
const start=fullApp.lastIndexOf('document.addEventListener("click", async',marker);
context.document.addEventListener=(event,handler)=>context.applyAnswerClick=handler;
vm.runInNewContext(fullApp.slice(start,fullApp.indexOf('\\n  });',marker)+6),context);
routeOverrides['/api/review/apply-answers']=body=>({status:'ready',intake:{...body.intake,case_number:'850/26.0TSTXX',service_date:'2026-09-28'},applied_fields:['case_number','service_date'],next_safe_action:{state:'prepare_pdf'}});
if(!reviewed.disabled)await context.applyAnswerClick({target:{closest:selector=>selector==='#home-apply-numbered-answers'?element(selector):null}});
console.log(JSON.stringify({resumed,...reviewed,cases:a.state.sourceCaseCandidates.length,calls:calls.map(row=>row.url),
 appliedAnswers:calls.find(row=>row.url==='/api/review/apply-answers')?.body.answers||'',next:a.state.currentNextSafeAction?.state,
 case:a.state.currentIntake.case_number,date:a.state.currentIntake.service_date,cleared:element('#home-numbered-answers').value,disabledAfterApply:element('#home-apply-numbered-answers').disabled}));
""")
        answers = '1. 850/26.0TSTXX\n2. 2026-09-28'
        self.assertEqual(result['resumed'], answers)
        self.assertEqual(result['home'], answers)
        self.assertEqual(result['drawer'], answers)
        self.assertEqual(result['saved'], answers)
        self.assertEqual(result['cases'], 0)
        self.assertFalse(result['disabled'])
        self.assertEqual(result['calls'], ['/api/workspace/resume', '/api/review', '/api/review/apply-answers'])
        self.assertEqual(result['appliedAnswers'], answers)
        self.assertEqual((result['case'], result['date'], result['next']), ('850/26.0TSTXX', '2026-09-28', 'prepare_pdf'))
        self.assertEqual(result['cleared'], '')
        self.assertTrue(result['disabledAfterApply'])

    def test_manual_answer_edits_sync_and_consumed_answers_do_not_reappear(self):
        result = self.run_js("""
a.state.currentIntake=alpha;a.fillFormFromIntake(alpha);const typed='1. 850/26.0TSTXX';
a.saveSourceCaseAnswers(typed);const mirrored=element('#numbered-answers').value;
await a.applyNumberedAnswers({sourceSelector:'#home-numbered-answers',openDrawer:false});
const applied={home:element('#home-numbered-answers').value,drawer:element('#numbered-answers').value};
a.saveSourceCaseAnswers(typed);a.saveSourceCaseAnswers('');a.state.currentNextSafeAction={state:'answer_questions'};a.updateHomeReviewCard({status:'needs_info',intake:alpha,questions:[{field:'service_date'}]});
console.log(JSON.stringify({mirrored,applied,cleared:element('#home-numbered-answers').value,disabled:element('#home-apply-numbered-answers').disabled,calls:calls.map(row=>row.url)}));
""")
        self.assertEqual(result['mirrored'], '1. 850/26.0TSTXX')
        self.assertEqual(result['applied'], {'home': '', 'drawer': ''})
        self.assertEqual(result['cleared'], '')
        self.assertTrue(result['disabled'])
        self.assertEqual(result['calls'], ['/api/review/apply-answers'])

    def test_five_case_resume_without_conditional_home_answer_control_finishes(self):
        result = self.run_js("""
const rows=photoRows().slice(1).map((row,index)=>({...row,claim_transport:index===3}));
const snapshot=g.workspaceDraftSnapshot({currentIntake:rows[3],sourceCaseCandidates:rows.map((row,index)=>({candidate_intake:row,answers:'1. Case '+index,
 review:{source:{filename:'Fictional original title'},source_evidence:{service_date_source:'photo_capture'}},queued_key:g.browserRequestIdentityKey(row)})),
 sourceCaseSelectedIndex:3,sourceTravelChoice:{mode:'shared',ownerIndex:3,groupId:'photo-trip-beta'},batchIntakes:rows},{});
storage.set(g.workspaceDraftStorageKey(workspace),savedRecord(snapshot));a.initializeWorkspaceDraft(workspace);
context.document.querySelector=selector=>selector==='#home-numbered-answers'?null:element(selector);
await a.resumeWorkspaceDraft();await Promise.resolve();
console.log(JSON.stringify({pending:!!a.state.workspaceDraft.pending,queue:a.state.batchIntakes.length,selected:a.state.sourceCaseSelectedIndex,
 owner:a.state.sourceTravelChoice.ownerIndex,needsReview:a.state.sourceCaseCandidates.every(row=>row.needs_review),answers:element('#numbered-answers').value,
 title:a.state.sourceCaseCandidates[3].review.source.filename,panel:element('#workspace-draft-status').innerHTML,disabled:element('#prepare-batch-intakes').disabled}));
""")
        self.assertFalse(result['pending']); self.assertEqual(result['queue'], 5)
        self.assertEqual((result['selected'], result['owner']), (3, 3))
        self.assertTrue(result['needsReview']); self.assertTrue(result['disabled'])
        self.assertEqual(result['answers'], '1. Case 3')
        self.assertEqual(result['title'], 'Fictional original title')
        self.assertIn('Review restored work', result['panel'])

    def test_missing_supporting_files_require_explicit_salvage_choice(self):
        result = self.run_js("""
const snapshot=makeSnapshot();storage.set(g.workspaceDraftStorageKey(workspace),savedRecord(snapshot));a.initializeWorkspaceDraft(workspace);
routeOverrides['/api/workspace/resume']={snapshot,missing_attachments:['fictional-proof.pdf'],unavailable_profiles:[]};
await a.resumeWorkspaceDraft();const first={current:a.state.currentIntake,pending:!!a.state.workspaceDraft.pending,panel:element('#workspace-draft-status').innerHTML};
await a.resumeWorkspaceDraft();console.log(JSON.stringify({first,current:a.state.currentIntake.case_number,pending:!!a.state.workspaceDraft.pending}));
""")
        self.assertIsNone(result['first']['current']); self.assertTrue(result['first']['pending'])
        self.assertIn('Resume without unavailable files', result['first']['panel'])
        self.assertIn('fictional-proof.pdf', result['first']['panel'])
        self.assertEqual(result['current'], '710/26.0TSTXX'); self.assertFalse(result['pending'])

    def test_corrupt_storage_can_be_explicitly_discarded_and_quota_keeps_previous(self):
        result = self.run_js("""
const key=g.workspaceDraftStorageKey(workspace);storage.set(key,'fictional broken json');a.initializeWorkspaceDraft(workspace);
const broken=element('#workspace-draft-status').innerHTML;const retained=storage.get(key);a.discardWorkspaceDraft({saveCurrent:false});
a.state.currentIntake=alpha;a.fillFormFromIntake(alpha);a.saveWorkspaceDraft();const previous=storage.get(key);
context.window.localStorage.setItem=()=>{throw new Error('Fictional quota exhausted')};element('#case_number').value='799/26.0TSTXX';a.saveWorkspaceDraft();
console.log(JSON.stringify({broken,retained,unchanged:previous===storage.get(key),current:a.state.currentIntake.case_number,error:element('#workspace-draft-status').innerHTML}));
""")
        self.assertIn('Discard saved work', result['broken'])
        self.assertEqual(result['retained'], 'fictional broken json')
        self.assertTrue(result['unchanged']); self.assertEqual(result['current'], '799/26.0TSTXX')
        self.assertIn('could not be saved', result['error'])

    def test_late_resume_does_not_replace_new_edits(self):
        result = self.run_js("""
storage.set(g.workspaceDraftStorageKey(workspace),savedRecord(makeSnapshot()));a.initializeWorkspaceDraft(workspace);
let release;deferred=new Promise(resolve=>release=resolve);const pending=a.resumeWorkspaceDraft();
a.state.workflowRevision++;a.state.currentIntake={...beta,case_number:'799/26.0TSTXX'};release();await pending;
console.log(JSON.stringify({current:a.state.currentIntake.case_number,pending:!!a.state.workspaceDraft.pending,stored:storage.size}));
""")
        self.assertEqual(result, {'current': '799/26.0TSTXX', 'pending': True, 'stored': 1})

    def test_runtime_switch_blocks_writes_and_other_namespace_is_not_loaded(self):
        result = self.run_js("""
storage.set(g.workspaceDraftStorageKey('b'.repeat(64)),savedRecord(makeSnapshot()));a.initializeWorkspaceDraft(workspace);
const empty=!a.state.workspaceDraft.pending;a.initializeWorkspaceDraft('b'.repeat(64));let error='';
try{await a.requestJson('/api/prepare',{method:'POST',body:'{}'})}catch(e){error=e.message}
console.log(JSON.stringify({empty,error,calls:calls.length}));
""")
        self.assertTrue(result['empty']); self.assertIn('workspace changed', result['error']); self.assertEqual(result['calls'], 0)

    def test_change_source_keeps_saved_queue_but_reset_discards_session(self):
        result = self.run_js("""
a.initializeWorkspaceDraft(workspace);a.state.currentIntake=alpha;a.fillFormFromIntake(alpha);a.state.batchIntakes=[alpha,beta];a.saveWorkspaceDraft();
a.resetReview();await Promise.resolve();const changed=JSON.parse(storage.get(g.workspaceDraftStorageKey(workspace))).snapshot;
a.resetWorkspace();await Promise.resolve();console.log(JSON.stringify({current:changed.current_intake,queue:changed.batch_intakes.length,remaining:storage.size}));
""")
        self.assertEqual(result, {'current': None, 'queue': 2, 'remaining': 0})


if __name__ == '__main__':
    unittest.main()
