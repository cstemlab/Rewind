const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../import/creator.js'),'utf8');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const catalog=(provider='gemini')=>({configured:true,provider,creator:{available:true,voice_selection:true,voice_preview:true,default_voice:provider==='gemini'?'google-a':'alloy',voices:provider==='gemini'?[{id:'google-a',label:'Aoede · 女聲'},{id:'google-b',label:'Charon · 男聲'}]:[{id:'alloy',label:'Alloy'},{id:'nova',label:'Nova'}]}});
const clip=voice=>({voice,text:'你好，歡迎練習粵語。',audio:{mime:'audio/wav',base64:'UklGRg=='},duration:2});
function harness({post=async()=>({}),local=false,authenticated=true,storage=new Map()}={}){
 const elements=new Map(),events={},observers=[],samples=[],sent=[],revoked=[];
 let status={configured:false},pauseCount=0,playSignals=0;
 const node=()=>({value:'',textContent:'',hidden:false,disabled:false,readOnly:false,dataset:{},attributes:{},children:[],handlers:{},classList:{add(){},remove(){},toggle(){}},addEventListener(name,cb){this.handlers[name]=cb;},setAttribute(name,value){this.attributes[name]=value;},removeAttribute(name){delete this.attributes[name];},replaceChildren(){this.children=[];},append(child){this.children.push(child);},querySelectorAll(){return [];},focus(){},scrollIntoView(){},contains(){return false;}});
 const element=id=>{if(!elements.has(id))elements.set(id,{...node(),id});return elements.get(id);};
 const window={addEventListener(name,cb){(events[name]??=[]).push(cb);},dispatchEvent(e){for(const cb of events[e.type]||[])cb(e);}};
 const emit=(type,detail)=>window.dispatchEvent({type,detail});
 window.addEventListener('rewind:playrequest',()=>playSignals++);
 const connection={local,post:async(route,body,signal)=>{sent.push({route,body,signal});return post(route,body,signal);},status:async()=>status,getInfo:()=>({available:true,authenticated,status}),subscribe(cb){this.notify=s=>{status=s;cb({status:s});};}};
 class Audio{constructor(src){this.src=src;this.events={};this.paused=true;samples.push(this);}addEventListener(name,cb){this.events[name]=cb;}async play(){this.paused=false;}pause(){this.paused=true;}removeAttribute(){this.src='';}load(){}emit(name){this.events[name]?.();}}
 const ctx={document:{getElementById:element,createElement:node},window,RewindConnection:connection,RewindFileImport:{read:async()=>({text:'',title:'',warnings:[]})},AbortController,MutationObserver:class{constructor(cb){observers.push(cb);}observe(){}},rewindPanels:{open(name){emit('rewind:panel',name);}},rewindSpeech:{openSettings(){emit('rewind:panel','speech');}},setTimeout,clearTimeout,stamp:()=>'',rewindLibrary:{add:s=>s},loadSession:async()=>true,setFocus(){},pauseForOptions(){pauseCount++;},stopAction(){},Event:class{constructor(type){this.type=type;}},Audio,Blob,Uint8Array,atob,URL:{createObjectURL:()=>`blob:${samples.length}`,revokeObjectURL:url=>revoked.push(url)},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}};
 vm.runInNewContext(source,ctx);
 return {element,emit,observers,samples,sent,revoked,storage,api:window.rewindCreator,connection,get pauseCount(){return pauseCount;},get playSignals(){return playSignals;},select(value){element('creator-voice').value=value;element('creator-voice').handlers.change();},preview:()=>element('creator-voice-preview').onclick()};
}
test('catalog is provider-specific; voice preference persists across providers and a fresh page',()=>{
 const h=harness();h.connection.notify(catalog());assert.deepEqual(h.element('creator-voice').children.map(x=>x.value),['google-a','google-b']);assert.equal(h.api.getState().voice,'google-a');
 h.select('google-b');h.connection.notify(catalog('openai'));assert.equal(h.api.getState().voice,'alloy');h.select('nova');h.connection.notify(catalog());assert.equal(h.api.getState().voice,'google-b');h.connection.notify(catalog('openai'));assert.equal(h.api.getState().voice,'nova');
 const fresh=harness({storage:h.storage});fresh.connection.notify(catalog());assert.equal(fresh.api.getState().voice,'google-b');
});
test('catalog labels show declared gender and quality with one default marker',()=>{
 const h=harness(),status=catalog();status.creator.voices=[{id:'google-a',label:'Aoede',gender:'female',quality:'Chirp 3 HD'},{id:'google-b',label:'Standard B',gender:'male',quality:'Standard'}];h.connection.notify(status);
 assert.deepEqual(h.element('creator-voice').children.map(x=>x.textContent),['Aoede · 女聲 (HD) · 預設','Standard B · 男聲 (Standard)']);
});
test('generation sends the selected supported voice and ready names the actual response voice',async()=>{
 const h=harness({post:async route=>route.endsWith('/render')?{job_id:'r'}:{state:'completed',result:{session:{title:'Tape',sentences:[{}],phrases:[{}],duration:2,source:{voice:'google-b'}}}}});
 h.connection.notify(catalog());h.select('google-b');h.element('creator-draft').value='大家好。';await h.element('creator-render').onclick();
 assert.equal(h.sent.find(x=>x.route.endsWith('/render')).body.draft.voice,'google-b');assert.equal(h.api.getState().view,'ready');assert.match(h.element('creator-ready-voice').textContent,/Charon/);assert.equal(h.element('creator-warning').hidden,true);
});
test('a stale selected voice is blocked if refreshed capabilities change',async()=>{
 const h=harness();h.connection.notify(catalog());h.select('google-b');h.element('creator-draft').value='大家好。';
 h.connection.status=async()=>catalog('openai');await h.element('creator-render').onclick();assert.equal(h.sent.length,0);assert.equal(h.api.getState().view,'draft');assert.match(h.element('creator-error').textContent,/重新選擇/);
});
test('legacy local service exposes only its fixed default and sends no unsupported voice field',async()=>{
 const h=harness({local:true,post:async route=>route.endsWith('/render')?{job_id:'r'}:{state:'completed',result:{session:{title:'Tape',sentences:[],phrases:[],duration:2,source:{voice:'nova'}}}}});
 h.connection.notify({configured:true,provider:'openai',creator:{available:true,voice:'nova'}});
 assert.equal(h.element('creator-voice').disabled,true);assert.equal(h.element('creator-voice-preview').disabled,true);assert.match(h.element('creator-voice').children[0].textContent,/nova/);assert.match(h.element('creator-voice-note').textContent,/固定聲音/);await h.preview();assert.equal(h.sent.length,0);
 h.element('creator-draft').value='大家好。';await h.element('creator-render').onclick();assert.equal('voice' in h.sent.find(x=>x.route.endsWith('/render')).body.draft,false);assert.equal(h.element('creator-ready-voice').textContent,'聲音：nova');
});
test('preview sends only fixed-sample consent and selected voice, and stops existing playback',async()=>{
 const h=harness({post:async(_route,body)=>clip(body.voice)});h.connection.notify(catalog());h.select('google-b');h.element('creator-draft').value='PRIVATE DRAFT';await h.preview();
 assert.equal(h.sent[0].route,'/api/creator/preview');assert.equal(JSON.stringify(h.sent[0].body),JSON.stringify({voice:'google-b',consent:true}));assert.equal(h.pauseCount,1);assert.equal(h.playSignals,1);assert.equal(h.api.getState().preview,'playing');assert.equal(h.element('creator-voice-preview-label').textContent,'停止');
 await h.preview();assert.equal(h.samples[0].paused,true);assert.equal(h.api.getState().preview,'idle');assert.equal(h.revoked.length,1);
});
test('stop cancels a pending request and a late response cannot start audio',async()=>{
 const pending=deferred(),h=harness({post:()=>pending.promise});h.connection.notify(catalog());const play=h.preview();assert.equal(h.api.getState().preview,'loading');assert.equal(h.element('creator-voice-preview-label').textContent,'取消');await h.preview();assert.equal(h.sent[0].signal.aborted,true);pending.resolve(clip('google-a'));await play;assert.equal(h.samples.length,0);assert.equal(h.api.getState().preview,'idle');
});
test('changing voice cancels pending preview and never plays the previous choice',async()=>{
 const pending=deferred(),h=harness({post:()=>pending.promise});h.connection.notify(catalog());const play=h.preview();h.select('google-b');assert.equal(h.sent[0].signal.aborted,true);pending.resolve(clip('google-a'));await play;assert.equal(h.samples.length,0);assert.equal(h.api.getState().voice,'google-b');
});
test('panel switch, drawer close, tape playback and ended events release preview audio',async()=>{
 for(const stop of [h=>h.emit('rewind:panel','speech'),h=>{h.element('drawer').hidden=true;h.observers[0]();},h=>h.emit('rewind:playrequest'),h=>h.samples[0].emit('ended')]){
   const h=harness({post:async()=>clip('google-a')});h.connection.notify(catalog());await h.preview();stop(h);assert.equal(h.api.getState().preview,'idle');assert.equal(h.samples[0].paused,true);assert.equal(h.revoked.length,1);
 }
});
test('generation aborts a pending sample before starting the render',async()=>{
 const pending=deferred(),h=harness({post:async route=>route.endsWith('/preview')?pending.promise:route.endsWith('/render')?{job_id:'r'}:{state:'completed',result:{session:{title:'Tape',sentences:[],phrases:[],source:{voice:'google-a'}}}}});
 h.connection.notify(catalog());const play=h.preview();h.element('creator-draft').value='大家好。';await h.element('creator-render').onclick();assert.equal(h.sent[0].signal.aborted,true);pending.resolve(clip('google-a'));await play;assert.equal(h.samples.length,0);assert.equal(h.api.getState().view,'ready');
});
test('no authentication means no preview request; auth expiry cancels a running sample',async()=>{
 const h=harness({authenticated:false});h.connection.notify(catalog());await h.preview();assert.equal(h.sent.length,0);assert.equal(h.element('creator-voice-preview').disabled,true);assert.match(h.element('creator-voice-note').textContent,/連接 AI/);
 const live=harness({post:async()=>clip('google-a')});live.connection.notify(catalog());await live.preview();live.connection.notify({configured:false});assert.equal(live.api.getState().preview,'idle');assert.equal(live.samples[0].paused,true);
});
test('mismatched preview voice is rejected before playback; failed request clears busy state',async()=>{
 for(const post of [async()=>clip('other'),async()=>{throw Error('Please connect again.');}]){
   const h=harness({post});h.connection.notify(catalog());await h.preview();assert.equal(h.samples.length,0);assert.equal(h.api.getState().preview,'idle');assert.equal(h.element('creator-voice-preview').disabled,false);assert.notEqual(h.element('creator-voice-note').textContent,'試聽固定短句。');
 }
});
test('ready reports a service voice mismatch explicitly, never relabels it as the selected voice',async()=>{
 const h=harness({post:async route=>route.endsWith('/render')?{job_id:'r'}:{state:'completed',result:{session:{title:'Tape',sentences:[],phrases:[],source:{voice:'different-actual-voice'}}}}});h.connection.notify(catalog());h.select('google-b');h.element('creator-draft').value='大家好。';await h.element('creator-render').onclick();assert.equal(h.element('creator-ready-voice').textContent,'聲音：different-actual-voice');assert.match(h.element('creator-warning').textContent,/different-actual-voice/);
});
test('public HTML embeds the same creator source and allows only the explicit preview route',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../../../index.html'),'utf8');
 const start=html.indexOf('/* Source → reviewed Cantonese → a prepared tape.'),end=html.indexOf('/* Independent cassette shell',start);assert.equal(html.slice(start,end).replace(/\r\n/g,'\n').trim(),source.replace(/\r\n/g,'\n').trim());
 const baseline=require('node:child_process').execFileSync('git',['show','HEAD:index.html'],{cwd:path.join(__dirname,'../../..'),maxBuffer:20000000}).toString();
 assert.equal(html.slice(end),baseline.slice(baseline.indexOf('/* Independent cassette shell')),'All existing skin, phone layout and fullscreen behavior after the creator must be preserved byte-for-byte.');
 assert.match(html,/creator\\\/\(\?:extract\|translate\|render\|preview\|status\|cancel\)/);
});
