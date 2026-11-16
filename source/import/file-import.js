/* Rewind local file import. No file contents leave the browser. */
(()=>{
 'use strict';
 const assets=REWIND_IMPORT_ASSETS,MAX_BYTES=5_000_000,MAX_CHARS=12000;
 let pdfLibrary,workerUrl,mammothUrl;
 const bytes64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
 const blobUrl=(data,type='text/javascript')=>URL.createObjectURL(new Blob([data],{type}));
 const abortError=()=>new DOMException('Import cancelled','AbortError');
 function check(signal){if(signal?.aborted)throw abortError();}
 function clean(text){return text.replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n').replace(/\u0000/g,'').replace(/[\t ]+\n/g,'\n').replace(/\n{4,}/g,'\n\n\n').trim();}
 function bounded(text){text=clean(text);if(!text)throw Error('這個檔案沒有可讀文字。');if(Array.from(text).length>MAX_CHARS)throw Error('講稿超過 12,000 字。請分成較短的檔案；目前內容未被替換。');return text;}
 function checkZip(data){
   const v=new DataView(data);let end=-1;
   for(let p=data.byteLength-22;p>=Math.max(0,data.byteLength-65557);p--)if(v.getUint32(p,true)===0x06054b50){end=p;break;}
   if(end<0)throw Error('這份 Word 檔無法讀取，請另存為 DOCX 再試。');
   const count=v.getUint16(end+10,true);let p=v.getUint32(end+16,true),expanded=0;
   if(count>1000||count===65535)throw Error('Word 檔內容過大，請只保留需要的講稿。');
   for(let i=0;i<count;i++){
     if(p+46>data.byteLength||v.getUint32(p,true)!==0x02014b50)throw Error('Word 檔格式不完整。');
     if(v.getUint16(p+8,true)&1)throw Error('請先移除 Word 檔密碼，再匯入。');
     expanded+=v.getUint32(p+24,true);if(expanded>20_000_000)throw Error('Word 檔解壓後內容過大，請只保留需要的講稿。');
     p+=46+v.getUint16(p+28,true)+v.getUint16(p+30,true)+v.getUint16(p+32,true);
   }
 }
 async function docx(data,signal){
   checkZip(data);mammothUrl ||= blobUrl(bytes64(assets.mammoth));
   const bootstrap=blobUrl(`importScripts(${JSON.stringify(mammothUrl)});onmessage=async e=>{try{const r=await mammoth.extractRawText({arrayBuffer:e.data});postMessage({text:r.value});}catch(e){postMessage({error:true});}}`);
   let worker;
   try{return await new Promise((resolve,reject)=>{
     worker=new Worker(bootstrap);const stop=()=>{worker.terminate();reject(abortError());};
     signal?.addEventListener('abort',stop,{once:true});
     const done=(fn,value)=>{signal?.removeEventListener('abort',stop);worker.terminate();fn(value);};
     worker.onmessage=e=>e.data.error?done(reject,Error('未能讀取這份 Word 檔，請重新另存為 DOCX。')):done(resolve,e.data.text);
     worker.onerror=()=>done(reject,Error('Word 讀取器未能啟動，請重新開啟 Rewind 再試。'));
     worker.postMessage(data,[data]);
   });}finally{worker?.terminate();URL.revokeObjectURL(bootstrap);}
 }
 async function pdfLib(){
   if(!pdfLibrary){const url=blobUrl(bytes64(assets.pdf));pdfLibrary=import(url).finally(()=>URL.revokeObjectURL(url)).catch(e=>{pdfLibrary=null;throw e;});}
   return pdfLibrary;
 }
 class EmbeddedDataFactory{
   async fetch({kind,filename}){const map=kind==='cMapUrl'?assets.cmaps:kind==='standardFontDataUrl'?assets.fonts:null;if(map&&Object.hasOwn(map,filename))return bytes64(map[filename]);throw Error('This document requires unsupported embedded font data.');}
 }
 const cjk=/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u;
 function pageText(items){
   const lines=[];let line='',last=null;
   const flush=()=>{if(line.trim())lines.push(line.trim());line='';last=null;};
   for(const item of items){if(typeof item.str!=='string')continue;const s=item.str;
     if(last&&Math.abs(item.transform[5]-last.transform[5])>Math.max(Math.abs(item.height),Math.abs(last.height),1)*.55)flush();
     if(s){
       const previous=Array.from(line).at(-1)||'',first=Array.from(s)[0]||'';
       const gap=last?item.transform[4]-(last.transform[4]+last.width):0;
       if(line&&!/\s$/.test(line)&&!/^\s/.test(s)&&!cjk.test(previous)&&!cjk.test(first)&&gap>Math.max(1,Math.abs(item.height)*.12))line+=' ';
       line+=s;last=item;
     }
     if(item.hasEOL)flush();
   }
   flush();return lines.join('\n').replace(/([\p{Script=Han}]) +(?=[\p{Script=Han}])/gu,'$1');
 }
 async function pdf(data,signal){
   if(new TextDecoder('ascii').decode(data.slice(0,5))!=='%PDF-')throw Error('這個檔案不是有效的 PDF。');
   const lib=await pdfLib();check(signal);workerUrl ||= blobUrl(bytes64(assets.pdfWorker));lib.GlobalWorkerOptions.workerSrc=workerUrl;
   const task=lib.getDocument({data:new Uint8Array(data),useWorkerFetch:false,BinaryDataFactory:EmbeddedDataFactory,cMapPacked:true,disableFontFace:true,useSystemFonts:true,useWasm:false,isEvalSupported:false,disableWorkerRendering:true,isOffscreenCanvasSupported:false,verbosity:0});
   const stop=()=>{task.destroy().catch(()=>{});};signal?.addEventListener('abort',stop,{once:true});
   try{
     const doc=await task.promise;check(signal);if(doc.numPages>100)throw Error('PDF 超過 100 頁，請先另存需要的頁面。');
     const pages=[];let blank=0,total=0;
     for(let i=1;i<=doc.numPages;i++){check(signal);const page=await doc.getPage(i);const text=pageText((await page.getTextContent()).items);page.cleanup();if(!text.trim())blank++;total+=Array.from(text).length;if(total>MAX_CHARS)throw Error('講稿超過 12,000 字。請分成較短的檔案；目前內容未被替換。');pages.push(text);}
     if(blank===doc.numPages)throw Error('這份 PDF 沒有可選取的文字，可能是掃描圖片。請先用 OCR 轉成文字，或貼上講稿。');
     return {text:pages.join('\n\n'),warnings:[blank?`已讀取文字；有 ${blank} 頁沒有可讀文字，可能需要 OCR。`:'已讀取 PDF 文字，請檢查段落及欄位順序。']};
   }catch(e){check(signal);if(e.name==='PasswordException')throw Error('PDF 已加密，請移除密碼後再匯入。');if(e.name==='InvalidPDFException')throw Error('這份 PDF 已損壞或格式不完整，請另存後再試。');throw e;}
   finally{signal?.removeEventListener('abort',stop);await task.destroy().catch(()=>{});}
 }
 async function read(file,{signal:outer}={}){
   if(!file||typeof file.arrayBuffer!=='function')throw Error('請選擇講稿檔案。');
   if(!file.size)throw Error('這個檔案是空的。');if(file.size>MAX_BYTES)throw Error('請使用小於 5 MB 的講稿檔。');
   const ext=(file.name.split('.').pop()||'').toLowerCase();
   if(ext==='doc')throw Error('請先在 Word 將舊版 DOC 另存為 DOCX，再匯入。');
   if(!['txt','text','md','markdown','docx','pdf'].includes(ext))throw Error('請選擇 TXT、Markdown、DOCX 或 PDF 講稿。');
   const controller=new AbortController();let timedOut=false;
   const abort=()=>controller.abort();if(outer?.aborted)throw abortError();outer?.addEventListener('abort',abort,{once:true});
   const timer=setTimeout(()=>{timedOut=true;controller.abort();},30000);const signal=controller.signal;
   try{
     const data=await file.arrayBuffer();check(signal);let result;
     if(ext==='pdf')result=await pdf(data,signal);
     else if(ext==='docx')result={text:await docx(data,signal),warnings:['已讀取正文及表格；圖片、頁首頁尾和批註不包括在內。']};
     else{
       const b=new Uint8Array(data);let encoding='utf-8';if(b[0]===255&&b[1]===254)encoding='utf-16le';else if(b[0]===254&&b[1]===255)encoding='utf-16be';
       try{result={text:new TextDecoder(encoding,{fatal:true}).decode(data),warnings:[]};}catch{throw Error('文字檔編碼無法辨識，請另存為 UTF-8 或 UTF-16，或直接貼上文字。');}
     }
     check(signal);return {...result,text:bounded(result.text),title:file.name.replace(/\.[^.]+$/,'').slice(0,120)};
   }catch(e){if(timedOut)throw Error('這份檔案處理時間較長。請縮小檔案或貼上需要的文字。');throw e;}
   finally{clearTimeout(timer);outer?.removeEventListener('abort',abort);}
 }
 window.RewindFileImport=Object.freeze({read});
})();
