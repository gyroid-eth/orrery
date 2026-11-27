/* Presentation and candidate detection only; the bridge owns approval parsing. */
(function(root){
  'use strict';
  // These cues come from the terminal. The bridge checks the actual question.
  const LOCALIZED_QUESTION_HINTS=[' が入力を求めています','📋 提问 · 第 '];
  const CLOSED_DISMISS_MS=1800;
  function mount({screen,getPane,getPanes,send,openTerminal,focusPrompt,closeDelayMs=CLOSED_DISMISS_MS}){
    const rows=new Map();let sequence=0,painted=null;
    const bar=document.createElement('section');bar.className='reader-approval';bar.hidden=true;bar.tabIndex=-1;
    bar.setAttribute('aria-label','Approval');
    const toggle=document.createElement('button');toggle.type='button';toggle.className='reader-approval-toggle';
    toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-live','polite');
    const details=document.createElement('div');details.className='reader-approval-details';details.hidden=true;
    details.id='reader-approval-details';toggle.setAttribute('aria-controls',details.id);
    const mainCopy=document.createElement('span');mainCopy.className='reader-approval-main-copy';
    const mainTitle=document.createElement('strong');mainTitle.className='reader-approval-main-title';
    const summary=document.createElement('span');summary.className='reader-approval-summary';
    const fold=document.createElement('span');fold.className='reader-approval-fold';
    mainCopy.append(mainTitle,summary);toggle.append(mainCopy,fold);
    const eyebrow=document.createElement('div');eyebrow.className='reader-approval-eyebrow';
    const dot=document.createElement('span');dot.className='reader-approval-dot';dot.setAttribute('aria-hidden','true');
    const eyebrowLabel=document.createElement('span'),kindLabel=document.createElement('span');kindLabel.className='reader-approval-kind';
    eyebrow.append(dot,eyebrowLabel,kindLabel);
    const title=document.createElement('h2');title.className='reader-approval-title';
    const lead=document.createElement('p');lead.className='reader-approval-lead';
    const label=document.createElement('div');label.className='reader-approval-label';
    const reason=document.createElement('p');reason.className='reader-approval-reason';
    const full=document.createElement('pre');full.className='reader-approval-full';
    const after=document.createElement('p');after.className='reader-approval-question';
    const foot=document.createElement('p');foot.className='reader-approval-foot';
    const setText=(node,value)=>{value=value||'';if(node.textContent!==value)node.textContent=value;node.hidden=!value;};
    // These are presentation fields of an already validated bridge response.
    // No text here authorizes a choice or supplies keys.
    function requestCopy(data){
      const lines=(data.body||'').split('\n');
      if(data.kind==='question')return {kind:({hermes:'Hermes',codex:'Codex',dsh:'dsh',agy:'Antigravity',claude:'Claude'}[data.harness]||'')+' · Question',title:data.body,
        summary:data.body,after:data.mode==='other'?'Write your answer in the message field.':''};
      if(data.kind==='read')return {kind:'Claude · Read',title:lines[0],target:lines[1],after:lines[2],
        summary:'Read · '+(lines[1]||'').slice(5,-1).split(/[\\/]/).pop()};
      if(data.kind==='mcp')return {kind:'Codex · MCP tool',title:lines[0]?.startsWith('Allow the orrery-mail ')?'Allow a Mail tool?':'Allow a tool?',
        lead:lines[0],label:'Arguments',target:lines.slice(1).join('\n'),summary:'MCP tool · '+(data.summary||'').split('(')[0]};
      if(data.kind==='command')return {kind:'Codex · Local environment',title:'Run outside the sandbox?',lead:lines[0],
        label:'Reason',reason:lines[2]?.slice(8),target:lines[3],summary:'Command · '+(lines[3]||'').split(/[\\/]/).pop()};
      return {kind:'Request incomplete',title:'Review this request in Terminal',summary:'Complete request unavailable',
        lead:'The complete request and its choices are not available here.'};
    }
    const choices=document.createElement('div');choices.className='reader-approval-choices';
    const status=document.createElement('div');status.className='reader-approval-status';status.setAttribute('role','status');
    const terminal=document.createElement('button');terminal.type='button';terminal.className='reader-approval-terminal';terminal.textContent='Open terminal to review';
    terminal.onclick=()=>openTerminal();
    details.append(eyebrow,title,lead,label,reason,full,after,choices,foot);bar.append(details,toggle,status,terminal);screen.append(bar);
    // These controls own their keys and must never focus the terminal beneath.
    for(const kind of ['pointerdown','mousedown','keydown','keyup'])bar.addEventListener(kind,event=>event.stopPropagation());
    function active(){return getPane();}
    function record(p){
      let row=rows.get(p);
      if(!row){row={pane:p,state:'none',open:false,seen:'',pending:null,dirty:false,data:{},timer:null,closeTimer:null};rows.set(p,row);}
      return row;
    }
    function clearCloseTimer(row){
      if(row.closeTimer){clearTimeout(row.closeTimer);row.closeTimer=null;}
    }
    function dismissClosed(row){
      clearCloseTimer(row);
      if(row.state!=='closed')return;
      row.state='none';row.open=false;row.data={};row.selection=new Set();
      paint();
    }
    function visible(p){
      if(!p)return false;
      const cell=p.host.closest('.split-cell');
      return (cell||screen).classList.contains('conversation-open');
    }
    function focusBar(){bar.focus({preventScroll:true});}
    const selection=row=>[...(row.selection||[])].sort((a,b)=>a-b);
    function paint(){
      const p=active(),row=p&&rows.get(p);
      const hadFocus=bar.contains(document.activeElement);
      bar.hidden=!row||row.state==='none'||!visible(p);
      if(bar.hidden){
        painted=null;
        if(hadFocus&&visible(p)){
          const scope=p.host.closest('.split-cell')||screen;
          scope.querySelector('.conversation-panel:not([hidden]) .conversation-scroll')?.focus({preventScroll:true});
        }
        return;
      }
      const data=row.data,signature=[row,row.state,row.open,data.token,data.message,data.logWarning,row.pending?.id,selection(row).join(',')];
      if(painted&&signature.every((v,i)=>v===painted[i]))return;
      painted=signature;
      const focusedChoice=document.activeElement?.dataset?.choice;
      if(focusedChoice)row.focusChoice=focusedChoice;
      const copy=requestCopy(data);
      const waiting=data.kind==='question'?'Waiting for your answer':'Approval needed';
      setText(mainTitle,row.state==='ready'?waiting:row.state==='sending'?'Sending response…':data.message||'Approval needs terminal review');
      setText(summary,copy.summary);
      setText(fold,row.open?'Hide details ▴':'Show details ▾');
      toggle.title=mainTitle.textContent+' · '+(data.summary||copy.summary);toggle.setAttribute('aria-expanded',String(row.open));
      details.hidden=!row.open;
      setText(eyebrowLabel,row.state==='ready'?waiting:row.state==='sending'?'Response pending':row.state==='sent'||row.state==='closed'?'Response sent':'Terminal review');
      setText(kindLabel,copy.kind);setText(title,copy.title);setText(lead,copy.lead);
      setText(label,copy.label);setText(reason,copy.reason);setText(full,copy.target);setText(after,copy.after);
      setText(foot,data.kind&&row.state!=='ready'?data.message:'');
      choices.replaceChildren();
      if(row.open&&row.state==='ready'&&data.mode!=='other')for(const choice of data.choices||[]){
        const button=document.createElement('button');button.type='button';
        const key=document.createElement('kbd');key.setAttribute('aria-hidden','true');
        key.textContent=data.kind==='command'?['Y','P','Esc'][choice.id-1]:String(choice.id);
        const choiceCopy=document.createElement('span');choiceCopy.className='reader-approval-choice-copy';
        choiceCopy.textContent=data.kind==='command'?choice.label.replace(/ \(y\)$| \(p\)$| \(esc\)$/,''):choice.label;
        if(choice.description)choiceCopy.title=choice.description;
        button.append(key,choiceCopy);button.title=choice.description||choice.label;
        button.className='reader-approval-choice';button.dataset.choice=String(choice.id);
        if(choice.id===data.default){button.classList.add('is-once');if(data.kind!=='question')button.setAttribute('aria-label',choice.label+' · Allow once');}
        button.disabled=Boolean(row.pending);
        if(data.multiple){
          const on=row.selection.has(choice.id);
          button.setAttribute('aria-pressed',String(on));key.textContent=on?'✓':'○';
          button.onclick=()=>{
            if(on)row.selection.delete(choice.id);else row.selection.add(choice.id);
            paint();if(choice.other&&!on)focusPrompt?.();
          };
        }else button.onclick=()=>choice.other?focusPrompt?.():answer(row,choice.id);
        choices.append(button);
      }
      if(row.open&&row.state==='ready'&&data.multiple&&data.mode==='choice'){
        const submit=document.createElement('button');submit.type='button';submit.className='reader-approval-choice';
        const other=data.choices.find(choice=>choice.other);
        submit.textContent='Submit choices';submit.disabled=!row.selection.size||row.selection.has(other?.id);
        submit.onclick=()=>answer(row,selection(row));choices.append(submit);
      }
      status.textContent=data.logWarning?'Response log could not be saved.':'';
      terminal.hidden=row.state==='ready'||row.state==='sending'||row.state==='closed';
      if(hadFocus){
        const target=row.open&&row.state==='ready'&&!row.pending?choices.querySelector(row.wantDefaultFocus?'.is-once':'[data-choice="'+row.focusChoice+'"]'):null;
        if(target){target.focus({preventScroll:true});row.wantDefaultFocus=false;}else focusBar();
      }
    }
    toggle.onclick=()=>{
      const row=active()&&rows.get(active());if(!row)return;
      row.open=!row.open;row.wantDefaultFocus=row.open;paint();
      if(row.open&&row.state==='refused'&&row.data.retryable)transmit(row,{type:'approval-inspect'});
      if(row.open&&row.state==='ready')choices.querySelector('.is-once')?.focus({preventScroll:true});
      else toggle.focus({preventScroll:true});
    };
    function transmit(row,payload,resolve){
      const id='approval-'+(++sequence);row.pending={id,type:payload.type,resolve};paint();
      if(!send({...payload,paneId:row.pane.meta.paneId,session:row.pane.session,requestId:id})){
        clearCloseTimer(row);
        row.pending=null;row.state=payload.type==='approval-answer'?'unknown':'unavailable';
        row.data={...row.data,message:payload.type==='approval-answer'?'Outcome unknown — check terminal':'Pane unavailable'};
        resolve?.('unknown');paint();return;
      }
      clearTimeout(row.timer);
      row.timer=setTimeout(()=>{
        if(row.pending?.id!==id)return;
        clearCloseTimer(row);
        row.pending=null;row.state=payload.type==='approval-answer'?'unknown':'unavailable';
        row.data={...row.data,message:payload.type==='approval-answer'?'Outcome unknown — check terminal':'Pane unavailable'};resolve?.('unknown');paint();
      },6000);
    }
    function answer(row,choice,text,resolve){
      if(row.state!=='ready'||row.pending||active()!==row.pane){resolve?.('refused');return;}
      clearCloseTimer(row);
      row.state='sending';paint();focusBar();
      transmit(row,{type:'approval-answer',token:row.data.token,choice,operation:root.crypto.randomUUID(),
        ...(text===undefined?{}:{text})},resolve);
    }
    function question(target){
      const p=active(),row=p&&rows.get(p);
      return row?.data.kind==='question'&&p.meta.paneId===target.paneId&&p.session===target.session
        &&!['none','closed'].includes(row.state)?row:null;
    }
    function answerDraft(target,text){
      const row=question(target);
      if(!row)return null;
      const other=row.data.choices?.find(option=>option.other)?.id;
      const choice=row.data.mode==='other'?0:other;
      if(choice===undefined||row.data.draft_empty===false)return Promise.resolve('refused');
      const selected=row.data.multiple&&choice!==0?[...new Set([...selection(row),choice])].sort((a,b)=>a-b):choice;
      return new Promise(resolve=>answer(row,selected,text,resolve));
    }
    function observe(p,force=false){
      if(!p||!p.term||!p.host?.isConnected)return;
      const row=record(p);
      if(p.host.dataset.snapshot==='pending')return;
      if(row.pending){row.dirty=true;return;}
      const buffer=p.term.buffer.active,lines=[];
      for(let i=buffer.baseY;i<Math.min(buffer.length,buffer.baseY+p.term.rows);i++)lines.push(buffer.getLine(i)?.translateToString(true)||'');
      const text=lines.join('\n');
      if(row.seen===text&&!force)return;
      row.seen=text;
      const candidate=/Allow the |Would you like to run|Read outside|Allow this read outside|Do you want to proceed\?|Allow for this session|Yes, proceed|Yes, but ask again|keep allowing any reads| needs your input|to submit answer|tab to add notes \| enter to|tab or esc to clear notes \| enter to|📋 Question |Navigate · enter Select · esc Skip|space Toggle · enter Submit · esc Skip|enter Submit · esc Back/.test(text)||
        LOCALIZED_QUESTION_HINTS.some(hint=>text.includes(hint));
      if(!candidate){
        if(!['none','closed','unavailable'].includes(row.state))transmit(row,{type:'approval-inspect'});
        paint();return;
      }
      transmit(row,{type:'approval-inspect'});
    }
    function receive(message){
      if(message.type!=='approval')return;
      const p=[...getPanes()].find(p=>p.meta.paneId===message.paneId&&p.session===message.session);
      const row=p&&rows.get(p);
      if(!row||row.pending?.id!==message.requestId)return;
      clearTimeout(row.timer);const resolve=row.pending.resolve;row.pending=null;
      const previous=row.state;
      if(message.state==='ready'&&message.token!==row.data.token){
        row.open=message.kind==='question';row.wantDefaultFocus=false;row.data={};
        row.selection=new Set((message.choices||[]).filter(choice=>choice.checked).map(choice=>choice.id));
      }
      row.state=message.state==='none'&&['sent','closed'].includes(previous)?'closed':message.state==='none'&&previous==='unknown'?'unknown':message.state;
      if(row.state!=='closed')clearCloseTimer(row);
      if(['none','terminal','unavailable','changed'].includes(row.state))row.data={};
      row.data={...row.data,...message};
      resolve?.(message.state==='sent'?'accepted':message.state==='unknown'?'unknown':'refused');
      if(row.state==='unknown'&&message.state==='none')row.data.message='Outcome unknown — check terminal';
      if(row.state==='none'){row.open=false;row.selection=new Set();}
      if((row.state==='sent'||row.state==='closed')&&previous!==row.state)row.open=false;
      if(message.state==='changed'){row.open=false;row.seen='';}
      if(message.state==='refused'&&message.retryable)row.open=false;
      paint();
      if(row.state==='sent'){
        row.timer=setTimeout(()=>{
          if(row.state!=='sent')return;
          row.data={...row.data,message:'Response sent — check terminal'};paint();
        },5000);
      }else if(row.state==='closed'&&!row.closeTimer){
        row.closeTimer=setTimeout(()=>dismissClosed(row),closeDelayMs);
      }
      // Output may have arrived before the answer's ACK/response frame.
      if(row.dirty||message.state==='changed'){row.dirty=false;row.seen='';observe(p);}
    }
    function refresh(){
      for(const [p,row] of rows)if(!p.host.isConnected){clearTimeout(row.timer);clearCloseTimer(row);row.pending?.resolve?.('unknown');rows.delete(p);}
      paint();observe(active());
    }
    function disconnected(){
      for(const row of rows.values()){
        clearTimeout(row.timer);clearCloseTimer(row);row.pending?.resolve?.('unknown');row.pending=null;
        if(row.state==='none'||row.state==='closed'){row.state='none';row.open=false;row.data={};row.selection=new Set();continue;}
        row.state=row.state==='sending'?'unknown':'unavailable';
        row.data={...row.data,message:row.state==='unknown'?'Outcome unknown — check terminal':'Pane unavailable'};
      }
      paint();
    }
    document.addEventListener('oc:focus-agent',refresh);
    document.addEventListener('oc:agents',refresh);
    const observer=new MutationObserver(records=>{
      if(records.some(r=>r.target.matches?.('.screen,.split-cell,.conversation-panel')))refresh();
    });
    observer.observe(screen,{attributes:true,subtree:true,attributeFilter:['class','hidden']});
    for(const p of getPanes())observe(p);
    return Object.freeze({observe,receive,refresh,disconnected,question,answerDraft});
  }
  root.OrreryReaderApproval=Object.freeze({mount});
})(window);
