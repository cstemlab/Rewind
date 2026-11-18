const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const vm=require('node:vm');
const root=path.resolve(__dirname,'../../..');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const session=JSON.parse(html.match(/<script id="session-data" type="application\/json">(.*?)<\/script>/s)[1]);
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../manifest.json'),'utf8'));
test('the revised IN-SMART tape is the single embedded default',()=>{
 assert.equal(session.id,'insmart-qef-20261201-logan-r-c-20261119');
 assert.equal(session.source.scriptSha256,'c47d3c1e983c510769670589e4c8fcc587593816ce2bc70099c1747ed02196b2');
 assert.match(html,/const library=\[defaultSession\];/);
 assert.deepEqual(session.sections.map(s=>s.label),['1','2a','2b','2c','3','4']);
 assert.equal(session.source.voice,'zh-HK-WanLungNeural');assert.equal(session.source.rate,'-12%');
 assert.notEqual(session.audio.sha256,manifest.previous_audio_sha256);
 assert.equal(crypto.createHash('sha256').update(Buffer.from(session.audio.base64,'base64')).digest('hex'),session.audio.sha256);
});
test('every spoken unit has ordered timing and every Chinese character has Jyutping',()=>{
 let previous=-1;
 for(const u of session.units){
  if(/[\u3400-\u9fff]/u.test(u.text))assert.match(u.jyutping,/^[a-z]+[1-6]$/);
  if(u.spoken){assert.ok(u.start>=previous-.00001);assert.ok(u.end>u.start&&u.end<=session.duration);previous=u.end;}
 }
});
test('Short and Long cover every unit exactly once, with matching section and sentence boundaries',()=>{
 for(const type of ['phrases','sentences']){
  let end=0;
  for(const cue of session[type]){assert.equal(cue.from,end);assert.ok(cue.to>cue.from);assert.ok(cue.start<cue.end);assert.ok(cue.end<=session.duration);assert.equal(cue.section,session.units[cue.from].slide-1);end=cue.to;}
  assert.equal(end,session.units.length);
 }
 for(const phrase of session.phrases){const sentence=session.sentences[phrase.sentence];assert.ok(phrase.from>=sentence.from&&phrase.to<=sentence.to);assert.equal(phrase.section,sentence.section);assert.ok(phrase.spokenCount<=12);assert.ok(sentence.phrases.includes(phrase.id));}
 assert.equal(session.phrases.length,154);assert.equal(session.sentences.length,34);
});
test('new project details and closing handover replace the previous narrative',()=>{
 const text=session.units.map(u=>u.text).join('');
 for(const term of ['二十幾個','超過十個','三十間學校','learningdesign','learningdesignpatterns','learninganalytics','assessmentdesign','socioscientificissues','教師AI素養專業發展架構','課程舉措'])assert.ok(text.includes(term),term);
 for(const term of ['二十多個','學習設計模板','學習設計','二零二六至二七'])assert.ok(!text.includes(term),term);
 assert.equal((text.match(/learningdesignpatterns/g)||[]).length,3);
 assert.ok(!text.includes('接住，我嘅同事會用科學故事同工程設計嘅例子'));
});
test('the actual app validator accepts the new default and current import/voice UI remains embedded',()=>{
 const code=html.match(/function validateSession\(s\)\{[\s\S]*?\n\}/)[0];
 const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);assert.equal(ctx.validateSession(session),session);
 for(const id of ['creator-voice','creator-file','session-data','creator-use'])assert.ok(html.includes('id="'+id+'"'),id);
 assert.ok(html.includes('RewindFileImport'));assert.ok(html.includes('rewindSpeech'));
});
