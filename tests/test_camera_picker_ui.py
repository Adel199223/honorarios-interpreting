"""Camera chooser behavior with fictional file names and injected offline requests."""
from pathlib import Path
import json
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const calls=[],events=[],chosen=[],views=[];
let revision=7,available=true;
let status={configured:true,label:'Phone Camera'};
const first={id:'fictional-token-one',fingerprint:'fictional-fingerprint-one',name:'20261002_120001.jpg',filename:'20261002_120001.jpg',size:101};
const second={id:'fictional-token-two',fingerprint:'fictional-fingerprint-two',name:'20261002_120002.jpg',filename:'20261002_120002.jpg',size:202};
let listing={configured:true,label:'Phone Camera',items:[first,second],offset:0,next_offset:null,total:2,truncated:false};
let requestOverride=null,fileOverride=null;
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const picker=createCameraPicker({
 requestJson:async url=>{calls.push(url);if(requestOverride)return requestOverride(url);return url.endsWith('/status')?status:listing;},
 fetchFile:async item=>{events.push('download:'+item.id);if(fileOverride)return fileOverride(item);return {name:item.name,type:'image/jpeg',size:item.size};},
 onState:value=>views.push(JSON.parse(JSON.stringify(value))),
 onSelectionStart:()=>{events.push('invalidate');revision+=1;},
 onChoose:async file=>{events.push('choose:'+file.name);chosen.push(file);},
 getRevision:()=>revision,
 isAvailable:()=>available,
});
"""
APP_HARNESS = r"""
import fs from 'node:fs';import vm from 'node:vm';
const elements=new Map(),requests=[],uiEvents=[],recovered=[],renderedEvidence=[];
const makeElement=id=>{
 const classes=new Set();
 const value={id,listeners:{},children:[],files:[],open:false,disabled:false,textContent:'',_value:'',
  addEventListener(name,listener){this.listeners[name]=listener;},
  setAttribute(name,value){this.attributes??={};this.attributes[name]=String(value)},removeAttribute(name){if(this.attributes)delete this.attributes[name];},
  classList:{toggle(name,force){if(force===undefined? !classes.has(name):force)classes.add(name);else classes.delete(name)},contains:name=>classes.has(name),add(...names){names.forEach(name=>classes.add(name))},remove(...names){names.forEach(name=>classes.delete(name))}},
  showModal(){this.open=true},close(){this.open=false},focus(){uiEvents.push('focus:'+id)},
  replaceChildren(...children){this.children=[...children]},append(...children){this.children.push(...children)},
  click(){uiEvents.push('click:'+id);return this.listeners.click?.({preventDefault(){}})},
 };
 Object.defineProperty(value,'innerHTML',{get(){return ''},set(){throw new Error('Chooser dynamic values must use text rendering')}});
 Object.defineProperty(value,'value',{get(){return this._value},set(v){this._value=String(v);if(id==='#source-file'&&!v)this.files=[]}});
 return value;
};
const element=id=>{if(!elements.has(id))elements.set(id,makeElement(id));return elements.get(id)};
const one={name:'20261002_120001.jpg',fingerprint:'fictional-fingerprint',size:101,modified_ns:1790942401000000000};
let appConfigured=true,appListing={items:[one],offset:0,next_offset:null,total:1,truncated:false};
class SyntheticTransfer {constructor(){this.files=[];this.items={add:file=>this.files.push(file)}}}
const context={...guidance,createCameraPicker,JSON,File,DataTransfer:SyntheticTransfer,
 state:{sourceRecoveryKeys:new Set(),workflowRevision:7,lastPrepared:{payload:'prepared-sentinel'},lastReview:{status:'ready'},sourceFileNeedsReview:false,sourceCaseCandidates:[],batchIntakes:[],cameraPicker:null,serverConnection:{connected:true},workspaceDraft:{runtimeChanged:false}},
 $:element,document:{createElement:tag=>makeElement(tag),querySelector:element},
 requestJson:async url=>{requests.push({url});return url.endsWith('/status')?{configured:appConfigured,label:'Phone Camera'}:appListing},
 fetch:async(url,options)=>{requests.push(options.body?{url,body:JSON.parse(options.body)}:{url});return {ok:true,blob:async()=>new Blob([options.body?'fictional-original-bytes':'fictional-thumbnail-bytes'],{type:'image/jpeg'})}},
 clearPreparedArtifacts:reason=>{uiEvents.push('clear:'+reason);context.state.workflowRevision+=1;context.state.lastPrepared=null},
 renderSourceCaseList(){},sourceTravelBlockedReason:()=>'',claimMode:()=> 'both',
 renderWorkspaceDraft(){},selectedSourceCase:()=>null,fillFormFromIntake(){},renderBatchQueue(){},renderSupportingAttachmentList(){},closeReviewDrawer(){},renderNextSafeAction(){},scheduleWorkspaceDraftSave(){},
 resetReview:()=>{uiEvents.push('reset-review');context.state.sourceFileNeedsReview=false},
 buildIntakeFromProfile:async()=>{uiEvents.push('build-manual')},manualEntryBlocker:()=>'',focusHomeReviewCard(){},
 persistCurrentSourceCase(){},renderSourceEvidence:value=>renderedEvidence.push(value),renderGuidedStep(){},renderDraftLifecycle(){},openReviewDrawer(){},
 requestWorkflowJson:async(url)=>{requests.push({url});throw new Error('Unexpected source preparation before review')},
 setDropStatus:(text,status)=>uiEvents.push('status:'+text),
 inferDroppedSourceKind:file=>file.name.endsWith('.pdf')?'notification_pdf':'photo',
 uploadSource:async(kind,options)=>{recovered.push({kind,file:options.file.name});return {status:'uploaded'}},
 setStatus(){},showAlert(){},updateHomeReviewCard(){},
};
const fullApp=fs.readFileSync('honorarios_app/static/app.js','utf8');
const start=fullApp.indexOf('async function recoverLocalSourceFile(');
const end=fullApp.indexOf('\nfunction requestWorkflowUpload(',start);
if(start<0||end<0)throw new Error('Missing production source chooser wiring');
let source=fullApp.slice(start,end);
const extractFunction=name=>{
 const expression=new RegExp('(?:async )?function '+name+'\\(');const match=expression.exec(fullApp);
 if(!match)throw new Error('Missing production '+name);
 const next=/\n(?:async )?function \w+\(/.exec(fullApp.slice(match.index+match[0].length));
 return fullApp.slice(match.index,next?match.index+match[0].length+next.index:undefined);
};
for(const name of ['clearSourceCaseReview','hideHomeReviewPanel','canPrepareSourceEmailReplacement','prepareIntake','reviewIntake','addCurrentIntakeToBatch','adoptUploadedSource','sourceEmailTextForIntake','applyReview','sentDuplicateForReview','duplicateSubmissionWording','showSentDuplicateDecision','normalizeAttachmentList','ensureSupportingAttachmentEmailBody','mergeSupportingAttachmentsIntoIntake','resumeWorkspaceDraft'])source+='\n'+extractFunction(name);
const handlerStart=fullApp.indexOf('  $("#source-upload-form").addEventListener("submit",');
if(handlerStart<0)throw new Error('Missing production source submit handler');
source+='\n'+fullApp.slice(handlerStart,fullApp.indexOf('\n  });',handlerStart)+6);
const manualStart=fullApp.indexOf('  $("#build-profile").addEventListener("click",');
if(manualStart<0)throw new Error('Missing production manual entry handler');
source+='\n'+fullApp.slice(manualStart,fullApp.indexOf('\n  });',manualStart)+6);
source+='\nthis.api={renderCameraPicker,initializeCameraPicker,invalidateSelectedSource,canPrepareSourceEmailReplacement,prepareIntake,reviewIntake,addCurrentIntakeToBatch,adoptUploadedSource,applyReview,resumeWorkspaceDraft}';
vm.runInNewContext(source,context);const a=context.api;
"""
GRID_HARNESS = r"""
const requests=[],chosen=[],created=[],revoked=[],observers=[];
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const flush=async()=>{for(let step=0;step<8;step+=1)await Promise.resolve()};
const makeElement=tag=>{
 const classes=new Set(),attributes={};
 return {tag,children:[],listeners:{},attributes,disabled:false,textContent:'',
  append(...children){this.children.push(...children)},replaceChildren(...children){this.children=[...children]},
  setAttribute(name,value){attributes[name]=String(value)},removeAttribute(name){delete attributes[name];if(name==='src')delete this.src},
  addEventListener(name,callback){this.listeners[name]=callback},
  classList:{add:name=>classes.add(name),remove:name=>classes.delete(name),contains:name=>classes.has(name)},
  click(){return this.listeners.click?.()},emit(name){return this.listeners[name]?.()},
  set innerHTML(value){throw new Error('Dynamic thumbnail content must use text rendering')},
 };
};
const container=makeElement('div'),root=makeElement('dialog');
const observe=(callback,options)=>{
 const instance={callback,options,targets:[],disconnected:false,
  observe(target){this.targets.push(target)},disconnect(){this.disconnected=true},
  intersect(...indices){callback(indices.map(index=>({target:this.targets[index],isIntersecting:true})))},
  hide(...indices){callback(indices.map(index=>({target:this.targets[index],isIntersecting:false})))},
 };
 observers.push(instance);return instance;
};
const items=Array.from({length:6},(_,index)=>({name:`camera-${index}.jpg`,fingerprint:`fingerprint-${index}`,size:1024*1024*(index+1)}));
const view={open:true,busy:false,query:'',offset:0,items};
const grid=createCameraThumbnailGrid({document:{createElement:makeElement},container,root,observe,
 onChoose:item=>chosen.push(item),
 fetchThumbnail:(item,signal)=>{const gate=deferred();requests.push({item,signal,...gate});return gate.promise},
 createObjectURL:blob=>{const url=`blob:synthetic-${created.length}`;created.push({url,blob});return url},
 revokeObjectURL:url=>revoked.push(url),
});
const imageAt=index=>container.children[index].children[0].children[0];
const placeholderAt=index=>container.children[index].children[0].children[1];
"""


class CameraPickerUiTests(unittest.TestCase):
    def run_js(self, body, app=False, grid=False):
        module_url = (ROOT / 'honorarios_app/static/camera_picker.js').as_uri()
        guidance_url = (ROOT / 'honorarios_app/static/review_guidance.js').as_uri()
        script = 'import {createCameraPicker,createCameraThumbnailGrid} from ' + json.dumps(module_url) + ';\n'
        if app:
            script += 'import * as guidance from ' + json.dumps(guidance_url) + ';\n'
        script += (APP_HARNESS if app else GRID_HARNESS if grid else HARNESS) + body
        result = subprocess.run(['node', '--input-type=module', '-'], input=script,
                                text=True, encoding='utf-8', capture_output=True, timeout=20, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_thumbnail_grid_requests_only_visible_tiles_with_three_in_flight(self):
        result = self.run_js("""
grid.update(view);const beforeVisible=requests.length;
observers[0].intersect(0,1,2,3,4);const firstWave=requests.map(row=>row.item.name);
observers[0].hide(3);requests[0].resolve('first-thumbnail');await flush();
const afterOne=requests.map(row=>row.item.name);imageAt(0).emit('load');
console.log(JSON.stringify({beforeVisible,firstWave,afterOne,rootMatches:observers[0].options.root===root,
 loaded:container.children[0].children[0].classList.contains('has-preview'),src:imageAt(0).src,
 label:container.children[0].attributes['aria-label'],caption:container.children[0].children[1].children.map(node=>node.textContent),chosen}));
""", grid=True)
        self.assertEqual(result['beforeVisible'], 0)
        self.assertEqual(result['firstWave'], ['camera-0.jpg', 'camera-1.jpg', 'camera-2.jpg'])
        self.assertEqual(result['afterOne'], ['camera-0.jpg', 'camera-1.jpg', 'camera-2.jpg', 'camera-4.jpg'])
        self.assertTrue(result['rootMatches'])
        self.assertTrue(result['loaded'])
        self.assertEqual(result['src'], 'blob:synthetic-0')
        self.assertEqual(result['caption'], ['camera-0.jpg', '1.0 MB'])
        self.assertEqual(result['label'], 'camera-0.jpg · 1.0 MB')
        self.assertEqual(result['chosen'], [])

    def test_same_listing_rerender_keeps_previews_and_failure_still_selects_original(self):
        result = self.run_js("""
view.items[1]={...items[1],name:'<script>fictional</script>.jpg'};
grid.update(view);const originalButtons=[...container.children];observers[0].intersect(0,1,2);
requests[0].resolve('ok');requests[1].reject(new Error('offline'));requests[2].resolve('bad-image');await flush();
imageAt(0).emit('load');imageAt(2).emit('error');grid.update({...view,error:'harmless status refresh'});
container.children[1].click();container.children[2].click();
console.log(JSON.stringify({sameButtons:container.children.every((button,index)=>button===originalButtons[index]),
 count:requests.length,src:imageAt(0).src,failures:[placeholderAt(1).textContent,placeholderAt(2).textContent],
 text:container.children[1].children[1].children[0].textContent,chosen,revoked}));
""", grid=True)
        self.assertTrue(result['sameButtons'])
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['src'], 'blob:synthetic-0')
        self.assertEqual(result['failures'], ['Preview unavailable. Refresh photos to try again.'] * 2)
        self.assertEqual(result['text'], '<script>fictional</script>.jpg')
        self.assertEqual([item['fingerprint'] for item in result['chosen']], ['fingerprint-1', 'fingerprint-2'])
        self.assertEqual(result['revoked'], ['blob:synthetic-1'])

    def test_search_page_close_abort_old_work_revoke_urls_and_ignore_late_callbacks(self):
        result = self.run_js("""
grid.update(view);const firstObserver=observers[0],oldButton=container.children[0];firstObserver.intersect(0,1,2);
requests[0].resolve('first');await flush();
grid.update({...view,query:'new-search',items:[items[4]]});const afterSearch={revoked:[...revoked],aborted:requests.slice(1).every(row=>row.signal.aborted),disconnected:firstObserver.disconnected};
firstObserver.intersect(0);oldButton.click();observers.at(-1).intersect(0);
grid.update({...view,query:'new-search',offset:50,items:[items[5]]});observers.at(-1).intersect(0);
const countWhileOldPending=requests.length;
requests[1].resolve('stale-search-result');requests[2].reject(new Error('stale-search-error'));await flush();
const currentRequest=requests.at(-1);currentRequest.resolve('current-page');await flush();
const beforeClose={count:requests.length,created:created.map(row=>row.blob),src:imageAt(0).src};
grid.clear();requests[3].resolve('late-previous-page');await flush();
console.log(JSON.stringify({afterSearch,countWhileOldPending,beforeClose,created:created.map(row=>row.blob),revoked,children:container.children.length,chosen,allAborted:requests[3].signal.aborted}));
""", grid=True)
        self.assertEqual(result['afterSearch'], {'revoked': ['blob:synthetic-0'], 'aborted': True, 'disconnected': True})
        self.assertEqual(result['countWhileOldPending'], 4)
        self.assertEqual(result['beforeClose'], {'count': 5, 'created': ['first', 'current-page'], 'src': 'blob:synthetic-1'})
        self.assertEqual(result['created'], ['first', 'current-page'])
        self.assertEqual(result['revoked'], ['blob:synthetic-0', 'blob:synthetic-1'])
        self.assertEqual(result['children'], 0)
        self.assertEqual(result['chosen'], [])
        self.assertTrue(result['allAborted'])

    def test_pause_resume_limits_unsettled_aborts_and_preserves_finished_preview(self):
        result = self.run_js("""
grid.update(view);observers[0].intersect(0,1,2,3);requests[0].resolve('finished');await flush();
grid.update({...view,busy:true});const paused={disabled:container.children.every(button=>button.disabled),aborted:requests.slice(1).every(row=>row.signal.aborted)};
container.children[0].click();grid.update(view,true);grid.update(view);
const beforeSettled=requests.length;requests[1].resolve('stale');await flush();const afterOne=requests.length;
requests[2].reject(new Error('aborted'));requests[3].resolve('stale');await flush();
const afterAll=requests.length,finishedSrc=imageAt(0).src;
grid.clear();requests.slice(4).forEach(request=>request.resolve('late'));await flush();
console.log(JSON.stringify({paused,beforeSettled,afterOne,afterAll,finishedSrc,chosen,created:created.map(row=>row.blob),revoked}));
""", grid=True)
        self.assertEqual(result['paused'], {'disabled': True, 'aborted': True})
        self.assertEqual(result['beforeSettled'], 4)
        self.assertEqual(result['afterOne'], 5)
        self.assertEqual(result['afterAll'], 7)
        self.assertEqual(result['finishedSrc'], 'blob:synthetic-0')
        self.assertEqual(result['created'], ['finished'])
        self.assertEqual(result['revoked'], ['blob:synthetic-0'])
        self.assertEqual(result['chosen'], [])

    def test_real_renderer_preview_get_and_original_selection_keep_review_explicit(self):
        result = self.run_js("""
const intersections=[];
globalThis.IntersectionObserver=class {constructor(callback){this.callback=callback;this.targets=[];intersections.push(this)}observe(target){this.targets.push(target)}disconnect(){}};
one.name='synthetic & 02.jpg';
await a.initializeCameraPicker();await element('#choose-camera-source').click();
const observer=intersections.at(-1);observer.callback(observer.targets.map(target=>({target,isIntersecting:true})));
for(let step=0;step<8;step+=1)await Promise.resolve();
const previewOnly={requests:[...requests],prepared:context.state.lastPrepared,revision:context.state.workflowRevision,recovered:recovered.length};
await element('#camera-picker-files').children[0].click();
const original=element('#source-file').files[0];
console.log(JSON.stringify({previewOnly,requests,selected:original.name,bytes:await original.text(),needsReview:context.state.sourceFileNeedsReview,recovered,closed:!element('#camera-picker').open}));
""", app=True)
        self.assertEqual(result['previewOnly']['requests'][-1]['url'], '/api/camera/thumbnail?name=synthetic%20%26%2002.jpg&fingerprint=fictional-fingerprint')
        self.assertEqual(result['previewOnly']['prepared'], {'payload': 'prepared-sentinel'})
        self.assertEqual(result['previewOnly']['revision'], 7)
        self.assertEqual(result['previewOnly']['recovered'], 0)
        self.assertEqual(result['requests'][-1], {'url': '/api/camera/file', 'body': {'name': 'synthetic & 02.jpg', 'fingerprint': 'fictional-fingerprint'}})
        self.assertEqual(result['selected'], 'synthetic & 02.jpg')
        self.assertEqual(result['bytes'], 'fictional-original-bytes')
        self.assertTrue(result['needsReview'])
        self.assertTrue(result['closed'])
        self.assertEqual(result['recovered'], [])

    def test_preview_error_guidance_maps_only_known_changed_detail_and_stays_selectable(self):
        result = self.run_js("""
const intersections=[];
globalThis.IntersectionObserver=class {constructor(callback){this.callback=callback;this.targets=[];intersections.push(this)}observe(target){this.targets.push(target)}disconnect(){}};
const replies=[{detail:'The photo changed since Camera was loaded. Open Camera again and select it again.'},
 {detail:'C:\\private\\phone\\secret.jpg could not be opened',code:'camera_photo_changed'},null];
appListing={...appListing,items:replies.map((_,index)=>({...one,name:`failure-${index}.jpg`}))};
context.fetch=async(url)=>{requests.push({url});const index=Number(/failure-(\\d)/.exec(url)[1]);return {ok:false,json:async()=>{if(index===2)throw new Error('invalid body');return replies[index]}}};
await a.initializeCameraPicker();await element('#choose-camera-source').click();
const observer=intersections.at(-1);observer.callback(observer.targets.map(target=>({target,isIntersecting:true})));
for(let step=0;step<12;step+=1)await Promise.resolve();
const tiles=element('#camera-picker-files').children;
console.log(JSON.stringify({messages:tiles.map(tile=>tile.children[0].children[1].textContent),labels:tiles.map(tile=>tile.attributes['aria-label']),disabled:tiles.map(tile=>tile.disabled),revision:context.state.workflowRevision,prepared:context.state.lastPrepared,recovered}));
""", app=True)
        messages = ['Photo changed. Refresh photos to load its latest version.',
                    'Preview unavailable. Refresh photos to try again.',
                    'Preview unavailable. Refresh photos to try again.']
        self.assertEqual(result['messages'], messages)
        for index, message in enumerate(messages):
            self.assertEqual(result['labels'][index], f'failure-{index}.jpg · 0.0 MB · {message}')
        self.assertEqual(result['disabled'], [False] * 3)
        self.assertEqual(result['revision'], 7)
        self.assertEqual(result['prepared'], {'payload': 'prepared-sentinel'})
        self.assertEqual(result['recovered'], [])

    def test_refresh_reloads_current_query_page_and_retries_failed_preview_without_touching_source(self):
        result = self.run_js("""
const intersections=[];
globalThis.IntersectionObserver=class {constructor(callback){this.callback=callback;this.targets=[];intersections.push(this)}observe(target){this.targets.push(target)}disconnect(){this.disconnected=true}};
let fail=true;
context.fetch=async(url)=>{requests.push({url});return fail?{ok:false,json:async()=>({detail:'unrecognized preview error'})}:{ok:true,blob:async()=>new Blob(['thumbnail'],{type:'image/jpeg'})}};
await a.initializeCameraPicker();await element('#choose-camera-source').click();
appListing={...appListing,offset:50,total:51};await context.state.cameraPicker.load('2026-10',50);
element('#source-file').files=[new File(['previous source'],'previous-source.jpg',{type:'image/jpeg'})];element('#camera-selected-source').textContent='previous-source.jpg';
const before={revision:context.state.workflowRevision,prepared:context.state.lastPrepared,review:context.state.lastReview};
const oldObserver=intersections.at(-1),oldTile=oldObserver.targets[0];oldObserver.callback([{target:oldTile,isIntersecting:true}]);
for(let step=0;step<10;step+=1)await Promise.resolve();const failed=oldTile.children[0].children[1].textContent;
element('#camera-search').value='not submitted';fail=false;await element('#camera-picker-refresh').click();
oldObserver.callback([{target:oldTile,isIntersecting:true}]);await oldTile.click();
const currentObserver=intersections.at(-1);currentObserver.callback(currentObserver.targets.map(target=>({target,isIntersecting:true})));
for(let step=0;step<10;step+=1)await Promise.resolve();
console.log(JSON.stringify({failed,lastListing:requests.filter(row=>row.url.includes('/camera/files')).at(-1).url,
 thumbnails:requests.filter(row=>row.url.includes('/camera/thumbnail')).length,hasNewPreview:element('#camera-picker-files').children[0].children[0].children[0].src?.startsWith('blob:'),
 oldDisconnected:oldObserver.disconnected,changedTile:oldTile!==element('#camera-picker-files').children[0],source:element('#source-file').files[0].name,selected:element('#camera-selected-source').textContent,
 unchanged:JSON.stringify(before)===JSON.stringify({revision:context.state.workflowRevision,prepared:context.state.lastPrepared,review:context.state.lastReview}),originalReads:requests.filter(row=>row.url==='/api/camera/file').length,recovered}));
""", app=True)
        self.assertEqual(result['failed'], 'Preview unavailable. Refresh photos to try again.')
        self.assertEqual(result['lastListing'], '/api/camera/files?query=2026-10&offset=50&limit=50')
        self.assertEqual(result['thumbnails'], 2)
        self.assertTrue(result['hasNewPreview'])
        self.assertTrue(result['oldDisconnected'])
        self.assertTrue(result['changedTile'])
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['source'], 'previous-source.jpg')
        self.assertEqual(result['selected'], 'previous-source.jpg')
        self.assertEqual(result['originalReads'], 0)
        self.assertEqual(result['recovered'], [])

    def test_refresh_is_blocked_during_original_selection_and_unavailable_runtime(self):
        result = self.run_js("""
await a.initializeCameraPicker();await element('#choose-camera-source').click();
let resolveOriginal;const originalResponse=new Promise(resolve=>resolveOriginal=resolve);
context.fetch=async(url)=>{requests.push({url});return originalResponse};
const selecting=element('#camera-picker-files').children[0].click();
const duringSelection={disabled:element('#camera-picker-refresh').disabled,count:requests.length};await element('#camera-picker-refresh').click();
const noReadDuringSelection=requests.length===duringSelection.count;
resolveOriginal({ok:true,blob:async()=>new Blob(['original'],{type:'image/jpeg'})});await selecting;
await element('#choose-camera-source').click();const count= requests.length;
context.state.workspaceDraft.runtimeChanged=true;a.renderCameraPicker(context.state.cameraPicker.snapshot());
const runtimeDisabled=element('#camera-picker-refresh').disabled;await element('#camera-picker-refresh').click();
context.state.workspaceDraft.runtimeChanged=false;context.state.serverConnection.connected=false;a.renderCameraPicker(context.state.cameraPicker.snapshot());
const disconnectedDisabled=element('#camera-picker-refresh').disabled;await element('#camera-picker-refresh').click();
console.log(JSON.stringify({duringSelection,noReadDuringSelection,runtimeDisabled,disconnectedDisabled,noReadWhileUnavailable:requests.length===count,selected:element('#source-file').files[0].name,recovered}));
""", app=True)
        self.assertTrue(result['duringSelection']['disabled'])
        self.assertTrue(result['noReadDuringSelection'])
        self.assertTrue(result['runtimeDisabled'])
        self.assertTrue(result['disconnectedDisabled'])
        self.assertTrue(result['noReadWhileUnavailable'])
        self.assertEqual(result['selected'], '20261002_120001.jpg')
        self.assertEqual(result['recovered'], [])

    def test_startup_checks_configuration_without_listing_or_reading_photos(self):
        result = self.run_js("""
await picker.initialize();
console.log(JSON.stringify({calls,events,state:picker.snapshot()}));
""")
        self.assertEqual(result['calls'], ['/api/camera/status'])
        self.assertEqual(result['events'], [])
        self.assertTrue(result['state']['configured'])
        self.assertFalse(result['state']['open'])
        self.assertFalse(result['state']['busy'])
        self.assertEqual(result['state']['label'], 'Phone Camera')

    def test_open_lists_default_camera_and_cancel_leaves_workflow_untouched(self):
        result = self.run_js("""
await picker.initialize();const before=revision;await picker.open();
const opened=picker.snapshot();picker.close();
console.log(JSON.stringify({calls,events,opened,closed:picker.snapshot(),unchanged:revision===before}));
""")
        self.assertTrue(result['opened']['open'])
        self.assertEqual([item['id'] for item in result['opened']['items']], ['fictional-token-one', 'fictional-token-two'])
        self.assertEqual(result['calls'][1], '/api/camera/files?query=&offset=0&limit=50')
        self.assertEqual(result['events'], [])
        self.assertTrue(result['unchanged'])
        self.assertFalse(result['closed']['open'])
        self.assertFalse(result['closed']['busy'])

    def test_selected_photo_invalidates_before_download_and_accepts_new_revision(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const selected=await picker.select(first);
console.log(JSON.stringify({selected,events,chosen,state:picker.snapshot(),revision}));
""")
        self.assertTrue(result['selected'])
        self.assertEqual(result['events'], ['invalidate', 'download:fictional-token-one', 'choose:20261002_120001.jpg'])
        self.assertEqual(result['chosen'][0]['name'], '20261002_120001.jpg')
        self.assertEqual(result['revision'], 8)
        self.assertFalse(result['state']['open'])
        self.assertFalse(result['state']['busy'])

    def test_cancel_during_original_download_never_adopts_late_file(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const gate=deferred();fileOverride=()=>gate.promise;
const pending=picker.select(first);picker.close();gate.resolve({name:first.name});const accepted=await pending;
console.log(JSON.stringify({accepted,chosen,state:picker.snapshot()}));
""")
        self.assertFalse(result['accepted'])
        self.assertEqual(result['chosen'], [])
        self.assertFalse(result['state']['open'])
        self.assertFalse(result['state']['busy'])

    def test_reset_or_other_source_change_discards_pending_original(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const gate=deferred();fileOverride=()=>gate.promise;
const pending=picker.select(first);revision+=1;gate.resolve({name:first.name});const accepted=await pending;
console.log(JSON.stringify({accepted,chosen,state:picker.snapshot()}));
""")
        self.assertFalse(result['accepted'])
        self.assertEqual(result['chosen'], [])
        self.assertFalse(result['state']['busy'])
        self.assertIn('changed', result['state']['error'].lower())

    def test_runtime_change_while_reading_cannot_adopt_original(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const gate=deferred();fileOverride=()=>gate.promise;
const pending=picker.select(first);available=false;gate.resolve({name:first.name});const accepted=await pending;
console.log(JSON.stringify({accepted,chosen,state:picker.snapshot()}));
""")
        self.assertFalse(result['accepted'])
        self.assertEqual(result['chosen'], [])
        self.assertFalse(result['state']['busy'])

    def test_old_download_failure_does_not_describe_the_new_request(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const gate=deferred();fileOverride=()=>gate.promise;
const pending=picker.select(first);revision+=1;gate.reject(new Error('obsolete original download failure'));const accepted=await pending;
console.log(JSON.stringify({accepted,chosen,state:picker.snapshot()}));
""")
        self.assertFalse(result['accepted'])
        self.assertEqual(result['chosen'], [])
        self.assertFalse(result['state']['busy'])
        self.assertNotIn('obsolete original download failure', result['state']['error'])

    def test_repeated_click_does_not_download_or_invalidate_twice(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const gate=deferred();fileOverride=()=>gate.promise;
const pending=picker.select(first);const repeated=await picker.select(first);
gate.resolve({name:first.name});const accepted=await pending;
console.log(JSON.stringify({repeated,accepted,events,chosen}));
""")
        self.assertFalse(result['repeated'])
        self.assertTrue(result['accepted'])
        self.assertEqual(result['events'].count('invalidate'), 1)
        self.assertEqual(result['events'].count('download:fictional-token-one'), 1)
        self.assertEqual(len(result['chosen']), 1)

    def test_unlisted_or_changed_file_cannot_be_selected_from_an_old_listing(self):
        result = self.run_js("""
await picker.initialize();await picker.open();
const changed=await picker.select({...first,fingerprint:'changed-after-list'});
const unlisted=await picker.select({...first,name:'not-listed.jpg'});
console.log(JSON.stringify({changed,unlisted,events,chosen}));
""")
        self.assertFalse(result['changed'])
        self.assertFalse(result['unlisted'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['chosen'], [])

    def test_unavailable_workspace_cannot_open_or_start_a_file_read(self):
        result = self.run_js("""
await picker.initialize();available=false;const opened=await picker.open();
available=true;await picker.open();available=false;const selected=await picker.select(first);
console.log(JSON.stringify({opened,selected,events,chosen,calls}));
""")
        self.assertFalse(result['opened'])
        self.assertFalse(result['selected'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['chosen'], [])
        self.assertEqual(len(result['calls']), 2)

    def test_cancelled_download_error_does_not_pollute_reopened_chooser(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const gate=deferred();fileOverride=()=>gate.promise;
const pending=picker.select(first);picker.close();await picker.open();
gate.reject(new Error('obsolete download failure'));const accepted=await pending;
console.log(JSON.stringify({accepted,chosen,state:picker.snapshot()}));
""")
        self.assertFalse(result['accepted'])
        self.assertEqual(result['chosen'], [])
        self.assertTrue(result['state']['open'])
        self.assertFalse(result['state']['busy'])
        self.assertEqual(result['state']['error'], '')

    def test_cancelled_listing_result_never_reopens_chooser_or_changes_workflow(self):
        result = self.run_js("""
await picker.initialize();const gate=deferred();requestOverride=()=>gate.promise;
const pending=picker.open();picker.close();gate.resolve(listing);await pending;
console.log(JSON.stringify({state:picker.snapshot(),events,revision}));
""")
        self.assertFalse(result['state']['open'])
        self.assertFalse(result['state']['busy'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['revision'], 7)

    def test_new_search_wins_over_older_listing_even_when_old_request_fails(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const gate=deferred();
requestOverride=url=>url.includes('query=older')?gate.promise:Promise.resolve({...listing,items:[second],total:1});
const older=picker.load('older');await picker.load('latest');gate.reject(new Error('obsolete listing failure'));await older;
console.log(JSON.stringify({state:picker.snapshot(),events}));
""")
        self.assertEqual(result['state']['query'], 'latest')
        self.assertEqual([item['id'] for item in result['state']['items']], ['fictional-token-two'])
        self.assertEqual(result['state']['error'], '')
        self.assertFalse(result['state']['busy'])
        self.assertEqual(result['events'], [])

    def test_filter_and_pagination_are_encoded_without_reading_image_bytes(self):
        result = self.run_js("""
await picker.initialize();await picker.open();
listing={...listing,items:[second],offset:50,next_offset:100,total:151,truncated:true};
await picker.load('case & 02/10',50);
console.log(JSON.stringify({url:calls.at(-1),state:picker.snapshot(),events}));
""")
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(result['url']).query)
        self.assertEqual(query, {'query': ['case & 02/10'], 'offset': ['50'], 'limit': ['50']})
        self.assertEqual(result['state']['offset'], 50)
        self.assertEqual(result['state']['nextOffset'], 100)
        self.assertEqual(result['state']['total'], 151)
        self.assertTrue(result['state']['truncated'])
        self.assertEqual(result['events'], [])

    def test_absent_configuration_stays_unconfigured_without_listing(self):
        result = self.run_js("""
status={configured:false,label:'Camera'};await picker.initialize();
console.log(JSON.stringify({calls,state:picker.snapshot(),events}));
""")
        self.assertFalse(result['state']['configured'])
        self.assertEqual(result['calls'], ['/api/camera/status'])
        self.assertFalse(result['state']['open'])
        self.assertEqual(result['events'], [])

    def test_empty_and_offline_camera_do_not_change_workflow(self):
        result = self.run_js("""
await picker.initialize();listing={...listing,items:[],total:0};await picker.open();const empty=picker.snapshot();
requestOverride=async()=>{throw new Error('Phone is offline. Browse another folder or reconnect.');};
await picker.load();
console.log(JSON.stringify({empty,offline:picker.snapshot(),events,revision}));
""")
        self.assertEqual(result['empty']['items'], [])
        self.assertFalse(result['empty']['busy'])
        self.assertTrue(result['offline']['open'])
        self.assertFalse(result['offline']['busy'])
        self.assertIn('offline', result['offline']['error'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['revision'], 7)

    def test_current_download_failure_is_visible_and_retry_uses_explicit_selection(self):
        result = self.run_js("""
await picker.initialize();await picker.open();
fileOverride=async()=>{throw new Error('Original is not available.');};
const failed=await picker.select(first);const blocked=picker.snapshot();
fileOverride=null;const retried=await picker.select(first);
console.log(JSON.stringify({failed,blocked,retried,chosen,events}));
""")
        self.assertFalse(result['failed'])
        self.assertTrue(result['blocked']['open'])
        self.assertFalse(result['blocked']['busy'])
        self.assertIn('not available', result['blocked']['error'])
        self.assertTrue(result['retried'])
        self.assertEqual(len(result['chosen']), 1)
        self.assertEqual(result['events'].count('download:fictional-token-one'), 2)

    def test_render_subscribers_cannot_mutate_chooser_items_through_snapshot(self):
        result = self.run_js("""
await picker.initialize();await picker.open();const exposed=picker.snapshot();
exposed.items[0].name='changed-outside.jpg';exposed.items.push({id:'forged'});
console.log(JSON.stringify({state:picker.snapshot(),events}));
""")
        self.assertEqual(len(result['state']['items']), 2)
        self.assertEqual(result['state']['items'][0]['name'], '20261002_120001.jpg')
        self.assertEqual(result['events'], [])

    def test_invalidate_is_cancel_without_workflow_or_file_operations(self):
        result = self.run_js("""
await picker.initialize();await picker.open();picker.invalidate();
console.log(JSON.stringify({state:picker.snapshot(),events,revision}));
""")
        self.assertFalse(result['state']['open'])
        self.assertFalse(result['state']['busy'])
        self.assertEqual(result['events'], [])
        self.assertEqual(result['revision'], 7)

    def test_configured_add_source_opens_camera_and_cancel_preserves_prepared_work(self):
        result = self.run_js("""
await a.initializeCameraPicker();const controls={cameraHidden:element('#camera-source-controls').classList.contains('hidden'),nativeHidden:element('#native-source-controls').classList.contains('hidden')};
await element('#choose-camera-source').click();const opened=element('#camera-picker').open;
element('#camera-picker-close').click();
console.log(JSON.stringify({controls,opened,closed:!element('#camera-picker').open,requests,prepared:context.state.lastPrepared,revision:context.state.workflowRevision,recovered}));
""", app=True)
        self.assertEqual(result['controls'], {'cameraHidden': False, 'nativeHidden': True})
        self.assertTrue(result['opened'])
        self.assertTrue(result['closed'])
        self.assertEqual(result['prepared'], {'payload': 'prepared-sentinel'})
        self.assertEqual(result['revision'], 7)
        self.assertEqual([row['url'] for row in result['requests']], ['/api/camera/status', '/api/camera/files?query=&offset=0&limit=50'])
        self.assertEqual(result['recovered'], [])

    def test_camera_selection_reads_only_chosen_original_and_waits_for_review_source(self):
        result = self.run_js("""
await a.initializeCameraPicker();await element('#choose-camera-source').click();
await element('#camera-picker-files').children[0].click();
const beforeReview={selected:element('#source-file').files[0].name,label:element('#camera-selected-source').textContent,prepared:context.state.lastPrepared,recovered:recovered.length};
await element('#source-upload-form').listeners.submit({preventDefault(){}});
console.log(JSON.stringify({beforeReview,recovered,requests,open:element('#camera-picker').open}));
""", app=True)
        self.assertEqual(result['beforeReview'], {'selected': '20261002_120001.jpg', 'label': '20261002_120001.jpg', 'prepared': None, 'recovered': 0})
        self.assertEqual(result['requests'][-1], {'url': '/api/camera/file', 'body': {'name': '20261002_120001.jpg', 'fingerprint': 'fictional-fingerprint'}})
        self.assertEqual(result['recovered'], [{'kind': 'photo', 'file': '20261002_120001.jpg'}])
        self.assertFalse(result['open'])

    def test_native_fallback_remains_available_for_configured_and_absent_camera(self):
        result = self.run_js("""
appConfigured=false;await a.initializeCameraPicker();
const absent={cameraHidden:element('#camera-source-controls').classList.contains('hidden'),nativeHidden:element('#native-source-controls').classList.contains('hidden')};
appConfigured=true;await a.initializeCameraPicker();await element('#choose-camera-source').click();
element('#camera-picker-other').click();const cancelled={prepared:context.state.lastPrepared,closed:!element('#camera-picker').open};
element('#source-file').files=[new File(['fictional-pdf'],'notice.pdf',{type:'application/pdf'})];
element('#source-file').listeners.change();
await element('#source-upload-form').listeners.submit({preventDefault(){}});
console.log(JSON.stringify({absent,cancelled,nativeClicked:uiEvents.includes('click:#source-file'),prepared:context.state.lastPrepared,label:element('#camera-selected-source').textContent,recovered}));
""", app=True)
        self.assertEqual(result['absent'], {'cameraHidden': True, 'nativeHidden': False})
        self.assertTrue(result['nativeClicked'])
        self.assertEqual(result['cancelled'], {'prepared': {'payload': 'prepared-sentinel'}, 'closed': True})
        self.assertIsNone(result['prepared'])
        self.assertEqual(result['label'], 'notice.pdf')
        self.assertEqual(result['recovered'], [{'kind': 'notification_pdf', 'file': 'notice.pdf'}])

    def test_filename_and_error_are_rendered_as_plain_text_and_runtime_blocks_selection(self):
        result = self.run_js("""
await a.initializeCameraPicker();
const name='<img src=x onerror=alert(1)>.jpg',error='<script>bad()</script>';
context.state.workspaceDraft.runtimeChanged=true;
a.renderCameraPicker({configured:true,open:true,busy:false,items:[{...one,name}],total:1,offset:0,nextOffset:null,truncated:false,error});
console.log(JSON.stringify({name:element('#camera-picker-files').children[0].attributes['aria-label'],error:element('#camera-picker-status').textContent,disabled:element('#camera-picker-files').children[0].disabled,requests}));
""", app=True)
        self.assertIn('<img src=x onerror=alert(1)>.jpg', result['name'])
        self.assertEqual(result['error'], '<script>bad()</script>')
        self.assertTrue(result['disabled'])
        self.assertEqual(result['requests'], [{'url': '/api/camera/status'}])

    def test_staged_camera_photo_blocks_prior_multicase_preparation_and_preserves_queue(self):
        result = self.run_js("""
await a.initializeCameraPicker();
context.state.sourceCaseCandidates=[710,711].map(number=>({candidate_intake:{case_number:`${number}/26.0TSTXX`,service_date:'2026-10-01'},review:{status:'ready',questions:[]}}));
context.state.sourceCaseSelectedIndex=1;context.state.sourceTravelChoice={mode:'shared',ownerIndex:0};
context.state.batchIntakes=[{case_number:'900/26.0TSTXX',service_date:'2026-09-01',source_sha256:'independent-source'}];
context.state.batchPreflight={status:'ready',snapshot:'independent-reviewed-queue'};
const batchBefore=JSON.stringify({queue:context.state.batchIntakes,preflight:context.state.batchPreflight});
const previouslyReady=a.canPrepareSourceEmailReplacement();
await element('#choose-camera-source').click();await element('#camera-picker-files').children[0].click();
const replacementReady=a.canPrepareSourceEmailReplacement(),errors=[];
for(const options of [{},{correctionMode:true,sourceReplacement:true,correctionReason:'Replace old source'}]){
 try{await a.prepareIntake(options)}catch(error){errors.push(error.message)}
}
console.log(JSON.stringify({previouslyReady,replacementReady,errors,needsReview:context.state.sourceFileNeedsReview,cases:context.state.sourceCaseCandidates,lastReview:context.state.lastReview,prepared:context.state.lastPrepared,reviewHidden:element('#interpretation-seed-panel').classList.contains('hidden'),batchUnchanged:batchBefore===JSON.stringify({queue:context.state.batchIntakes,preflight:context.state.batchPreflight}),requests}));
""", app=True)
        self.assertTrue(result['previouslyReady'])
        self.assertFalse(result['replacementReady'])
        self.assertTrue(result['needsReview'])
        self.assertEqual(result['cases'], [])
        self.assertIsNone(result['lastReview'])
        self.assertIsNone(result['prepared'])
        self.assertTrue(result['reviewHidden'])
        self.assertTrue(result['batchUnchanged'])
        self.assertEqual(result['errors'], ['Review the selected source before preparing its PDF.'] * 2)
        self.assertFalse(any('/prepare' in row['url'] for row in result['requests']))

    def test_staged_native_photo_uses_same_review_guard_and_cancel_has_no_effect(self):
        result = self.run_js("""
await a.initializeCameraPicker();
const before=JSON.stringify({prepared:context.state.lastPrepared,review:context.state.lastReview,revision:context.state.workflowRevision});
element('#source-file').listeners.change();
const cancelledUnchanged=before===JSON.stringify({prepared:context.state.lastPrepared,review:context.state.lastReview,revision:context.state.workflowRevision});
context.state.sourceCaseCandidates=[710,711].map(number=>({candidate_intake:{case_number:`${number}/26.0TSTXX`,service_date:'2026-10-01'},review:{status:'ready',questions:[]}}));
element('#source-file').files=[new File(['fictional-pdf'],'notice.pdf',{type:'application/pdf'})];element('#source-file').listeners.change();
let error='';try{await a.prepareIntake()}catch(e){error=e.message}
console.log(JSON.stringify({cancelledUnchanged,needsReview:context.state.sourceFileNeedsReview,cases:context.state.sourceCaseCandidates,replacementReady:a.canPrepareSourceEmailReplacement(),error,requests}));
""", app=True)
        self.assertTrue(result['cancelledUnchanged'])
        self.assertTrue(result['needsReview'])
        self.assertEqual(result['cases'], [])
        self.assertFalse(result['replacementReady'])
        self.assertEqual(result['error'], 'Review the selected source before preparing its PDF.')
        self.assertEqual(result['requests'], [{'url': '/api/camera/status'}])

    def test_staged_source_cannot_review_or_queue_the_previous_intake(self):
        result = self.run_js("""
context.state.currentIntake={case_number:'710/26.0TSTXX',service_date:'2026-10-01'};
context.state.batchIntakes=[{case_number:'900/26.0TSTXX',service_date:'2026-09-01'}];
a.invalidateSelectedSource();const queue=JSON.stringify(context.state.batchIntakes),errors=[];
for(const action of [()=>a.reviewIntake(),()=>a.addCurrentIntakeToBatch()]){
 try{await action()}catch(error){errors.push(error.message)}
}
console.log(JSON.stringify({errors,requests,queueUnchanged:queue===JSON.stringify(context.state.batchIntakes),needsReview:context.state.sourceFileNeedsReview}));
""", app=True)
        self.assertEqual(result['errors'], [
            'Click Review source to read the selected file before reviewing its details.',
            'Review the selected source before adding its request to the batch.',
        ])
        self.assertEqual(result['requests'], [])
        self.assertTrue(result['queueUnchanged'])
        self.assertTrue(result['needsReview'])

    def test_adopting_recovered_new_source_clears_staging_guard_for_its_own_intake(self):
        result = self.run_js("""
context.state.currentIntake={case_number:'710/26.0TSTXX',service_date:'2026-10-01'};a.invalidateSelectedSource();
const fresh={case_number:'712/26.0TSTXX',service_date:'2026-10-02',source_sha256:'new-original-sha256'};
a.adoptUploadedSource({candidate_intake:fresh,review:{status:'needs_info',intake:fresh},source:{filename:'new-original.jpg',sha256:fresh.source_sha256,source_kind:'photo'}});
console.log(JSON.stringify({needsReview:context.state.sourceFileNeedsReview,current:context.state.currentIntake.case_number,cases:context.state.sourceCaseCandidates.map(row=>row.candidate_intake.case_number),requests}));
""", app=True)
        self.assertFalse(result['needsReview'])
        self.assertEqual(result['current'], '712/26.0TSTXX')
        self.assertEqual(result['cases'], [])
        self.assertEqual(result['requests'], [])

    def test_successful_resume_replaces_staged_file_and_requires_fresh_saved_input_review(self):
        result = self.run_js("""
await a.initializeCameraPicker();await element('#choose-camera-source').click();await element('#camera-picker-files').children[0].click();await element('#choose-camera-source').click();
const snapshot={current_intake:{case_number:'900/26.0TSTXX',service_date:'2026-09-01'},source_cases:[],selected_case:null,travel_choice:null,batch_intakes:[],current_evidence:{},email_grouping:'source',packet_mode:false,answers:''};
context.state.workspaceDraft={pending:{snapshot},busy:false,runtimeChanged:false,editVersion:1,workspaceId:'fictional-workspace'};
context.requestJson=async(url,options)=>{requests.push({url});return {snapshot,missing_attachments:[],unavailable_profiles:[]}};
const result=await a.resumeWorkspaceDraft();
console.log(JSON.stringify({resumed:!!result,needsReview:context.state.sourceFileNeedsReview,pickerOpen:context.state.cameraPicker.snapshot().open,inputFiles:element('#source-file').files.length,label:element('#camera-selected-source').textContent,current:context.state.currentIntake.case_number,lastReview:context.state.lastReview.status,prepared:context.state.lastPrepared,requests}));
""", app=True)
        self.assertTrue(result['resumed'])
        self.assertFalse(result['needsReview'])
        self.assertFalse(result['pickerOpen'])
        self.assertEqual(result['inputFiles'], 0)
        self.assertEqual(result['label'], 'No photo selected')
        self.assertEqual(result['current'], '900/26.0TSTXX')
        self.assertEqual(result['lastReview'], 'blocked')
        self.assertIsNone(result['prepared'])
        self.assertEqual(result['requests'][-1]['url'], '/api/workspace/resume')
        self.assertFalse(any('/prepare' in row['url'] for row in result['requests']))

    def test_explicit_manual_entry_resets_staged_photo_before_building_manual_intake(self):
        result = self.run_js("""
context.state.sourceFileNeedsReview=true;await element('#build-profile').click();
const stagedEvents=uiEvents.filter(value=>['reset-review','build-manual'].includes(value));
uiEvents.length=0;await element('#build-profile').click();
console.log(JSON.stringify({stagedEvents,ordinaryEvents:uiEvents.filter(value=>['reset-review','build-manual'].includes(value)),needsReview:context.state.sourceFileNeedsReview,requests}));
""", app=True)
        self.assertEqual(result['stagedEvents'], ['reset-review', 'build-manual'])
        self.assertEqual(result['ordinaryEvents'], ['build-manual'])
        self.assertFalse(result['needsReview'])
        self.assertEqual(result['requests'], [])

    def test_single_original_retains_source_gps_preview_and_date_origin_after_normal_review(self):
        result = self.run_js("""
const intake={case_number:'712/26.0TSTXX',service_date:'2026-10-02',photo_metadata_date:'2026-10-02',source_sha256:'fictional-original-hash'};
const originalDate={field:'photo_metadata_date',value:'2026-10-02',source:'image_metadata',confidence:'high'};
const metadata={exif_date:'2026-10-02',exif_date_source:'DateTimeOriginal',gps_coordinates:{latitude:45,longitude:10},exif_capture_time:'12:00:01'};
const photoSource={filename:'20261002_120001.jpg',sha256:intake.source_sha256,source_kind:'photo',metadata};
const evidence={filename:photoSource.filename,kind:'photo',sha256:photoSource.sha256,metadata,rendered_page_urls:['/fictional/original-preview.jpg'],rendered_page_count:1,field_evidence:[originalDate]};
a.adoptUploadedSource({candidate_intake:intake,source:photoSource,source_evidence:evidence,review:{status:'needs_info',intake,review_evidence:{field_evidence:[originalDate]}}});
const seeded=JSON.parse(JSON.stringify(context.state.lastReview));
a.applyReview({status:'needs_info',intake:{...intake},review_evidence:{filename:'Manual review',metadata:{},rendered_page_urls:[],rendered_page_count:0,field_evidence:[{field:'photo_metadata_date',value:'2026-10-02',source:'manual',confidence:'medium'}],attention:{status:'blocked',flags:[{code:'current-question'}]}}},{openDrawer:false});
console.log(JSON.stringify({seeded,reviewed:context.state.lastReview,rendered:renderedEvidence.at(-1),cases:context.state.sourceCaseCandidates,requests}));
""", app=True)
        self.assertEqual(result['cases'], [])
        for record in [result['seeded'], result['reviewed'], result['rendered']]:
            self.assertEqual(record['source']['filename'], '20261002_120001.jpg')
            self.assertEqual(record['source']['sha256'], 'fictional-original-hash')
            self.assertEqual(record['source_evidence']['filename'], '20261002_120001.jpg')
            self.assertEqual(record['source_evidence']['metadata']['gps_coordinates'], {'latitude': 45, 'longitude': 10})
            self.assertEqual(record['source_evidence']['metadata']['exif_date_source'], 'DateTimeOriginal')
            self.assertEqual(record['source_evidence']['rendered_page_urls'], ['/fictional/original-preview.jpg'])
            self.assertEqual(record['source_evidence']['field_evidence'][0]['source'], 'image_metadata')
        self.assertEqual(result['reviewed']['source_evidence']['attention']['flags'], [{'code': 'current-question'}])
        self.assertEqual(result['requests'], [])


if __name__ == '__main__':
    unittest.main()
