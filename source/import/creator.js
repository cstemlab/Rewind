/* Source → reviewed Cantonese → a prepared tape. AI requests share the Rewind connection. */
(()=>{
 const el=id=>document.getElementById(id),connection=RewindConnection,local=connection.local;
 let mode='faithful',view='source',service=null,job=null,ticket=0,abort=null,pendingSession=null,busy=false,returnView='source';
 let importTicket=0,importAbort=null,returnAfterConnect=false;
 const fileHint='TXT · Word · PDF · Markdown';
 const modes={faithful:'保留原意、細節與語氣，轉成自然粵語口語。',beginner:'保留原意和重要細節，用常用詞和較短句子表達。'};
 const stages={queued:'等候處理…',translating:'轉成粵語口語…',planning:'整理粵拼與短句…',synthesizing:'製作粵語錄音…',assembling:'整理練習…'};
 function error(message=''){el('creator-error').textContent=message;el('creator-error').hidden=!message;}
 function warning(message=''){el('creator-warning').textContent=message;el('creator-warning').hidden=!message;}
 function paint(next){view=next;el('creator-panel').dataset.view=next;for(const name of ['source','draft','progress','ready'])el('creator-'+name+'-view').hidden=name!==next;el('creator-step').textContent=({source:'01 · Script',draft:'02 · Cantonese',progress:'Making your tape',ready:'03 · Ready'})[next];el('creator-reset').hidden=next==='progress';if(next!=='source')el('creator-service-note').hidden=true;}
 function count(){el('creator-count').textContent=Array.from(el('creator-source').value).length.toLocaleString('en')+' / 12,000';}
 const request=connection.post;
 function connectionNote(){
   const link=connection.getInfo(),available=service?.configured&&service?.creator?.available;
   const provider=({openai:'OpenAI',gemini:'Google Gemini',azure:'Azure'})[service?.provider]||'AI 服務';
   el('creator-provider-note').textContent=`文字會交給 ${provider} 轉換；下一步可先修改。`;
   el('creator-service-note').hidden=!!available||view!=='source';
   el('creator-service-message').textContent=link.message||(!link.available?'AI 製作服務尚未啟用。你貼上的稿件會保留。':service?.configured?'這個語音服務暫未提供新練習製作。':local?'連接 OpenAI 後，即可製作新練習。':'沿用錄音時的存取碼即可。若尚未連接，在 Speech 輸入一次，就同時開啟錄音回饋和新講稿轉換。');
   el('creator-connect').hidden=!link.available;el('creator-local-guide').hidden=link.available;return !!available;
 }
 async function refresh(){try{service=await connection.status();}catch{service=null;}connectionNote();}
 async function cancel(show=true){const old=job;ticket++;job=null;abort?.abort();abort=null;const was=busy;busy=false;if(old&&connection.getInfo().available)request('/api/creator/cancel',{job_id:old}).catch(()=>{});if(was){paint(returnView);if(show)warning('已取消；原稿和目前練習均保留。');}}
 async function run(route,body,back){
   if(busy)return;
   const mine=++ticket;busy=true;returnView=back;error();warning();pendingSession=null;
   abort=new AbortController();paint('progress');el('creator-progress-message').textContent='準備中…';el('creator-progress').removeAttribute('value');
   try{
     await refresh();if(mine!==ticket)return;
     if(!connectionNote()){busy=false;abort=null;paint(back);connectionNote();error(connection.getInfo().message||(local?'請先連接可製作練習的服務，再按一次製作。':'請先在 Speech 連接 AI 練習，再按一次製作。'));return;}
     // Keep the short start request alive so cancellation can dispose its eventual job ID.
     const started=await request(route,{...body,consent:true});
     if(mine!==ticket){if(started.job_id)request('/api/creator/cancel',{job_id:started.job_id}).catch(()=>{});return;}
     if(!started.job_id)throw Error('服務未建立製作工作。');job=started.job_id;
     while(mine===ticket){
       const status=await request('/api/creator/status',{job_id:job},abort.signal);if(mine!==ticket)return;
       el('creator-progress-message').textContent=status.message||stages[status.stage]||'處理中…';
       if(status.total>0){el('creator-progress').max=status.total;el('creator-progress').value=Math.max(0,status.completed||0);}
       if(status.state==='completed'){
         const result=status.result||status;busy=false;job=null;abort=null;
         if(result.draft){const draft=result.draft;el('creator-draft-title').value=draft.title||el('creator-title').value;el('creator-draft').value=draft.text||'';paint('draft');}
         else if(result.session){
           pendingSession=rewindLibrary.add(result.session);
           const wanted=el('creator-voice')?.value,used=pendingSession.source?.voice;
           el('creator-ready-title').textContent=pendingSession.title;el('creator-ready-meta').textContent=`${pendingSession.sentences.length} 句 · ${pendingSession.phrases.length} 小段 · ${stamp(pendingSession.duration||0)}`;paint('ready');
           if(wanted&&used&&used!==wanted)warning('這份示範仍使用服務預設的聲音。所選聲音要等雲端服務更新後，再生一次才會換成那一個聲音。');
         }
         else throw Error('製作結果不完整，尚未更換目前練習。');return;
       }
       if(status.state==='failed')throw Error(typeof status.error==='string'?status.error:status.error?.message||'製作未完成，原稿仍保留。');
       if(status.state==='cancelled')throw Error('製作已取消，原稿仍保留。');
       await new Promise(resolve=>setTimeout(resolve,700));
     }
   }catch(e){if(mine!==ticket||e.name==='AbortError')return;busy=false;job=null;abort=null;paint(back);error(e.message);}
 }
 function stopImport(){importTicket++;importAbort?.abort();importAbort=null;fileStatus(fileHint,false);}
 function blankCreator(){stopImport();pendingSession=null;error();warning();el('creator-source').value='';el('creator-title').value='';el('creator-draft').value='';el('creator-draft-title').value='';count();paint('source');connectionNote();}
 el('create-button').onclick=()=>{if(view==='ready'||pendingSession)blankCreator();rewindPanels.open('creator');};
 el('creator-source').addEventListener('input',count);
 for(const button of el('creator-panel').querySelectorAll('[data-mode]'))button.onclick=()=>{mode=button.dataset.mode;for(const item of el('creator-panel').querySelectorAll('[data-mode]'))item.setAttribute('aria-pressed',String(item===button));el('creator-mode-note').textContent=modes[mode];};
 function fileStatus(text,loading){const name=el('creator-file-name');name.textContent=text;name.classList.toggle('is-busy',!!loading);el('creator-file-button').classList.toggle('is-busy',!!loading);el('creator-file-button').disabled=!!loading;el('creator-translate').disabled=!!loading;el('creator-source').readOnly=!!loading;el('creator-title').readOnly=!!loading;el('creator-source-view').setAttribute('aria-busy',String(!!loading));}
 async function importFile(file){
   if(!file)return;
   if(busy)await cancel(false);stopImport();paint('source');rewindPanels.open('creator');pendingSession=null;
   error();warning();const mine=++importTicket;importAbort=new AbortController();fileStatus('正在讀取 '+file.name+'…',true);
   try{
     const result=await RewindFileImport.read(file,{signal:importAbort.signal});
     if(mine!==importTicket)return;
     el('creator-source').value=result.text;el('creator-title').value=result.title.slice(0,120);
     fileStatus(file.name+' · '+Array.from(result.text).length.toLocaleString('en')+' 字',false);count();warning((result.warnings||[]).join(' '));
     el('creator-source').focus({preventScroll:true});el('creator-source').scrollTop=0;
   }catch(err){if(mine===importTicket&&err.name!=='AbortError'){fileStatus(file.name+' · 未能讀入',false);error(err.message+' 目前內容已保留。');el('creator-error').scrollIntoView({block:'nearest'});}}
   finally{if(mine===importTicket){importAbort=null;fileStatus(el('creator-file-name').textContent,false);}}
 }
 el('creator-file-button').onclick=()=>el('creator-file').click();
 el('creator-file').addEventListener('change',e=>{const file=e.target.files?.[0];e.target.value='';if(file)importFile(file);});
 for(const id of ['creator-source-view','library-panel']){const area=el(id);area.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';area.classList.add('file-dragging');}});area.addEventListener('dragleave',e=>{if(!area.contains(e.relatedTarget))area.classList.remove('file-dragging');});area.addEventListener('drop',e=>{area.classList.remove('file-dragging');if(!e.dataTransfer.files.length)return;e.preventDefault();if(e.dataTransfer.files.length!==1){error('請一次選擇一份講稿。');rewindPanels.open('creator');return;}const file=e.dataTransfer.files[0];if(/\.(json|rewind)$/i.test(file.name)){window.rewindOpenFile(file);return;}importFile(file);});}
 el('creator-translate').onclick=()=>{const text=el('creator-source').value.trim();if(!text){error('請先貼上或匯入講稿。');el('creator-source').focus();return;}run('/api/creator/translate',{text,title:el('creator-title').value.trim(),mode},'source');};
 el('creator-render').onclick=()=>{const text=el('creator-draft').value.trim();if(!text){error('請先填寫粵語講稿。');return;}run('/api/creator/render',{draft:{title:el('creator-draft-title').value.trim(),text,mode,voice:el('creator-voice').value}},'draft');};
 el('creator-edit-source').onclick=()=>{error();warning();paint('source');connectionNote();};
 el('creator-revise').onclick=()=>{pendingSession=null;paint('draft');};
 el('creator-cancel').onclick=()=>cancel();
 el('creator-reset').onclick=async()=>{await cancel(false);blankCreator();};
 el('creator-connect').onclick=()=>{returnAfterConnect=true;rewindSpeech.openSettings();};
 el('creator-use').onclick=async()=>{if(!pendingSession)return;error();const candidate=pendingSession;el('creator-use').disabled=true;try{const loaded=await loadSession(candidate,{add:true});if(loaded){pendingSession=null;setFocus(true);}else error('這份練習未能載入，原練習保持不變。');}finally{el('creator-use').disabled=false;}};
 window.addEventListener('rewind:panel',e=>{if(e.detail==='creator'){refresh();}else{if(busy)cancel(false);if(importAbort)stopImport();}});
 new MutationObserver(()=>{if(el('drawer').hidden){if(busy)cancel(false);if(importAbort)stopImport();}}).observe(el('drawer'),{attributes:true,attributeFilter:['hidden']});
 window.addEventListener('pagehide',()=>cancel(false));
 connection.subscribe(link=>{service=link.status;connectionNote();if(returnAfterConnect&&service?.configured&&service?.creator?.available){returnAfterConnect=false;rewindPanels.open('creator');}});
 window.rewindCreator=Object.freeze({getState:()=>({mode,view,busy,hasDraft:!!el('creator-draft').value,hasSession:!!pendingSession,local,job}),open:()=>rewindPanels.open('creator'),importFile});
 paint('source');count();connectionNote();
})();

