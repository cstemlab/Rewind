const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../creator.js'),'utf8');
function harness(read,post=async()=>({})){
 const elements=new Map(),events={},observers=[],opened=[],loaded=[];
 const element=id=>{if(!elements.has(id))elements.set(id,{id,value:'',textContent:'',hidden:false,disabled:false,readOnly:false,dataset:{},classList:{add(){},remove(){},toggle(){}},handlers:{},addEventListener(name,cb){this.handlers[name]=cb;},append(){},replaceChildren(){},setAttribute(){},removeAttribute(){},querySelectorAll(){return [];},focus(){this.focused=true;},scrollIntoView(){},contains(){return false;}});return elements.get(id);};
 const window={addEventListener(name,cb){(events[name]??=[]).push(cb);}};
 const emit=(name,detail)=>{for(const cb of events[name]||[])cb({detail});};
 let status={configured:false};
 const connection={local:false,post,status:async()=>status,getInfo:()=>({available:true,status}),subscribe(cb){this.notify=s=>{status=s;cb({status:s});};}};
 const ctx={document:{getElementById:element,createElement:()=>({})},window,RewindConnection:connection,RewindFileImport:{read},AbortController,MutationObserver:class{constructor(cb){observers.push(cb);}observe(){}},rewindPanels:{open(name){opened.push(name);emit('rewind:panel',name);}},rewindSpeech:{openSettings(){emit('rewind:panel','speech');}},setTimeout,clearTimeout,stamp:()=>'',rewindLibrary:{add:s=>s},loadSession:async s=>{loaded.push(s);return true;},setFocus(){}};
 vm.runInNewContext(source,ctx);
 return {element,emit,observers,opened,loaded,api:window.rewindCreator,connection};
}
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const result=(text,title='Imported')=>({text,title,warnings:[]});
test('import succeeds without a connected AI service and focuses review text',async()=>{
 const h=harness(async()=>result('大家好。','Morning'));
 await h.api.importFile({name:'Morning.docx'});
 assert.equal(h.element('creator-source').value,'大家好。');assert.equal(h.element('creator-title').value,'Morning');assert.equal(h.element('creator-source').focused,true);assert.equal(h.element('creator-translate').disabled,false);
});
test('failure preserves current draft and unlocks controls for retry',async()=>{
 const h=harness(async()=>{throw Error('This PDF is scanned.');});h.element('creator-source').value='Keep this';h.element('creator-title').value='Original';
 await h.api.importFile({name:'Scan.pdf'});
 assert.equal(h.element('creator-source').value,'Keep this');assert.equal(h.element('creator-title').value,'Original');assert.match(h.element('creator-error').textContent,/scanned/);assert.equal(h.element('creator-file-button').disabled,false);assert.equal(h.element('creator-source').readOnly,false);
});
test('a newer import wins when the previous reader finishes late',async()=>{
 const first=deferred(),second=deferred();let n=0;const h=harness(()=>++n===1?first.promise:second.promise);
 const a=h.api.importFile({name:'first.pdf'}),b=h.api.importFile({name:'second.txt'});
 second.resolve(result('Latest'));await b;first.resolve(result('Stale'));await a;
 assert.equal(h.element('creator-source').value,'Latest');assert.equal(h.element('creator-file-button').disabled,false);
});
test('New draft invalidates a slow file read',async()=>{
 const pending=deferred();const h=harness(()=>pending.promise);const load=h.api.importFile({name:'slow.pdf'});
 await h.element('creator-reset').onclick();pending.resolve(result('Must not return'));await load;
 assert.equal(h.element('creator-source').value,'');assert.equal(h.element('creator-title').value,'');assert.equal(h.element('creator-file-button').disabled,false);
});
test('closing options invalidates import and preserves previous text',async()=>{
 const pending=deferred();const h=harness(()=>pending.promise);h.element('creator-source').value='Keep';const load=h.api.importFile({name:'slow.pdf'});
 h.element('drawer').hidden=true;h.observers[0]();pending.resolve(result('Stale'));await load;
 assert.equal(h.element('creator-source').value,'Keep');assert.equal(h.element('creator-source').readOnly,false);
});
test('choosing the same file again works because the native input resets immediately',async()=>{
 let count=0;const h=harness(async()=>{count++;return result('Again');});const input=h.element('creator-file');input.files=[{name:'again.txt'}];input.value='fake-path';input.handlers.change({target:input});await Promise.resolve();assert.equal(input.value,'');
 input.value='fake-path';input.handlers.change({target:input});await Promise.resolve();assert.equal(count,2);assert.equal(input.value,'');
});

test('connecting AI from the draft returns to the preserved script',()=>{
 const h=harness(async()=>result('大家好。'));h.element('creator-source').value='Keep draft';h.element('creator-connect').onclick();h.connection.notify({configured:true,creator:{available:true}});assert.equal(h.opened.at(-1),'creator');assert.equal(h.element('creator-source').value,'Keep draft');
});
test('import, review, mocked translation and narration hand off the new tape title',async()=>{
 let phase='',sent=[];const h=harness(async()=>result('Hello everyone.','Welcome'),async(route,body)=>{sent.push({route,body});if(route.endsWith('/translate')){phase='translate';return {job_id:'t'};}if(route.endsWith('/render')){phase='render';return {job_id:'r'};}if(route.endsWith('/status'))return {state:'completed',result:phase==='translate'?{draft:{title:'Welcome',text:'大家好。'}}:{session:{title:'Welcome',sentences:[{}],phrases:[{}],duration:2}}};return {};});
 h.connection.notify({configured:true,provider:'gemini',creator:{available:true}});await h.api.importFile({name:'Welcome.docx'});h.element('creator-translate').onclick();await new Promise(setImmediate);assert.equal(h.api.getState().view,'draft');assert.equal(h.element('creator-draft').value,'大家好。');h.element('creator-render').onclick();await new Promise(setImmediate);assert.equal(h.api.getState().view,'ready');await h.element('creator-use').onclick();assert.equal(h.loaded[0].title,'Welcome');assert.equal(sent.find(x=>x.route.endsWith('/translate')).body.text,'Hello everyone.');
});
