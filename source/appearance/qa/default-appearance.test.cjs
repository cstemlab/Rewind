const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.resolve(__dirname,'../../../index.html'),'utf8');
const skins=JSON.parse(html.match(/const REWIND_SKINS\s*=\s*(\[.*?\]);/s)[1]);
const functions=html.match(/function validate\(input\)\{[\s\S]*?  let savedAppearance/)[0].replace(/  let savedAppearance$/,'');
const ctx={REWIND_SKINS:skins,REWIND_DEFAULT_SKIN:'rewind-yellow',materials:['matte','smoke','clear'],patterns:['plain','regions'],legacyPatterns:{preset:'plain',ruled:'regions',stripes:'regions',blocks:'regions'},hex:x=>typeof x==='string'&&/^#[0-9a-f]{6}$/i.test(x)};
vm.createContext(ctx);vm.runInContext(functions,ctx);
const state=id=>JSON.parse(JSON.stringify(ctx.fromPreset(id)));
test('a fresh or invalid preset gives the exact captured yellow smoked appearance',()=>{
 for(const id of ['rewind-yellow','missing']){
  const chosen=ctx.initialAppearance(null,id,true);
  assert.equal(chosen.material,'smoke');assert.equal(chosen.caseColor,'#424847');assert.equal(chosen.stickerColor,'#ffdd80');assert.equal(chosen.pattern,'plain');
  assert.equal(JSON.stringify(chosen.bands),JSON.stringify(['#98a573','#ffffff','#73a1de']));
 }
});
test('the old auto-saved default upgrades once; an intentional later choice survives',()=>{
 const old=state('archive-orange');
 assert.equal(ctx.initialAppearance(old,old.presetId,true).presetId,'rewind-yellow');
 assert.equal(ctx.initialAppearance(old,old.presetId,false).presetId,'archive-orange');
});
test('saved custom colours and other presets are preserved',()=>{
 const custom={...state('school-blue'),material:'smoke',caseColor:'#424847',stickerColor:'#ffdd80',bands:['#98a573','#ffffff','#73a1de']};
 const chosen=ctx.initialAppearance(custom,'school-blue',true);
 for(const key of ['material','caseColor','stickerColor','presetId'])assert.equal(chosen[key],custom[key]);
 assert.equal(ctx.initialAppearance(null,'school-blue',true).presetId,'school-blue');
 const changedArchive={...state('archive-orange'),caseColor:'#123456'};
 assert.equal(ctx.initialAppearance(changedArchive,'archive-orange',true).caseColor,'#123456');
});
