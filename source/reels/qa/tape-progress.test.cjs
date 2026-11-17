const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const dir=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(dir,'tape-progress.js'),'utf8');
const ctx={};vm.createContext(ctx);vm.runInContext(source+'\nthis.tape=RewindTapeProgress;',ctx);
const measure=ctx.tape.measure;
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-9,`${a} != ${b}`);
test('all tape starts on the right and ends on the left, with fixed standard capacity',()=>{
 for(const duration of [2,8,300,3600]){
  const first=measure(0,0,duration),last=measure(duration,0,duration);
  near(first.left,.58);near(first.right,1);near(last.left,1);near(last.right,.58);
  near(first.windowLeft,0);near(first.windowRight,1);
  near(last.windowLeft,1);near(last.windowRight,0);
 }
});
test('equal fractions of different recordings look identical; short recordings transfer faster',()=>{
 for(const progress of [.1,.25,.5,.9]){
  const short=measure(progress*6,0,6),long=measure(progress*600,0,600);
  near(short.left,long.left);near(short.right,long.right);near(short.windowLeft,long.windowLeft);
 }
 assert.ok(measure(3,0,6).left>measure(3,0,600).left);
});
test('window circles use actual gear centres and tape wraps outside a fixed smaller core',()=>{
 for(const width of [72,156,350]){
  const distance=width*.74;
  for(const cx of [-distance,width+distance]){
   const shape=ctx.tape.windowGeometry(cx,width*.35,width);
   near(shape.cx,cx);near(shape.cy,width*.35);
   near(shape.coreRadius-distance,width*.06);
   near(shape.fullRadius-distance,width*.26);
   for(let p=0;p<=100;p++){
    const value=measure(p,0,100),mirror=measure(100-p,0,100);
    near(value.windowLeft,mirror.windowRight);
    for(const amount of [value.windowLeft,value.windowRight]){
     const radius=shape.coreRadius+(shape.fullRadius-shape.coreRadius)*amount;
     assert.ok(radius>=shape.coreRadius-1e-9);
     assert.ok(radius-distance<width/2);
     near(Math.hypot(radius*Math.cos(.4),radius*Math.sin(.4)),radius);
    }
   }
  }
 }
});
test('wound tape area is conserved; halfway gives two equal packs',()=>{
 for(let p=0;p<=100;p++){
  const s=measure(p,0,100);near(s.left*s.left+s.right*s.right,1+.58*.58);
 }
 const halfway=measure(50,0,100);near(halfway.left,halfway.right);
});
test('global position handles selection, section jumps, loop returns and end padding',()=>{
 const start=.25,end=297;
 assert.ok(measure(180,start,end).progress>.6);
 assert.ok(measure(120,start,end).left<measure(180,start,end).left);
 near(measure(start,start,end).progress,0);near(measure(300,start,end).progress,1);
 near(measure(-1,start,end).progress,0);
 for(const args of [[0,0,0],[NaN,0,10],[1,0,Infinity]])assert.equal(measure(...args).progress,0);
});
test('rendering follows the cursor and does no repeated work while paused',()=>{
 let writes=0;const properties={},element={style:{setProperty(k,v){properties[k]=v;writes++;}},dataset:{}};
 const render=ctx.tape.create(element);
 render(0,0,10);assert.equal(element.dataset.tapeProgress,'0.000000');assert.equal(writes,4);
 render(0,0,10);assert.equal(writes,4);
 render(5,0,10);assert.equal(element.dataset.tapeProgress,'0.500000');assert.equal(properties['--left-pack'],properties['--right-pack']);
 render(0,0,100);assert.equal(element.dataset.tapeProgress,'0.000000');
});
test('production embeds the reviewed source and uses full-session bounds',()=>{
 const html=fs.readFileSync(path.resolve(dir,'../../index.html'),'utf8');
 assert.ok(html.includes(source.trim()));assert.ok(html.includes(fs.readFileSync(path.join(dir,'tape-progress.css'),'utf8').trim()));
 assert.ok(html.includes('<span class="window-reel window-reel-left"></span><span class="window-reel window-reel-right"></span>'));
 assert.match(html,/updateTapeProgress\(global,session\.phrases\[0\]\.start,session\.phrases\[session\.phrases\.length-1\]\.end\)/);
});
