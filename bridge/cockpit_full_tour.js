/* Selected Full tour steps. The checklist presentation belongs to OrreryTour. */
(function(root){
'use strict';
const STEPS=Object.freeze([
  {id:'full-start',title:'Start an agent',target:'#newAgentBtn',copy:'Start an agent in your workshop folder with a signed-in CLI. Give it a simple task and wait until it is ready.'},
  {id:'full-choose',title:'Choose your agent',target:'.col.roster',copy:'Choose your agent on the left. Its terminal opens in the center, and Agent Mail follows it.'},
  {id:'full-talk',title:'Send a prompt',target:'.promptbar',copy:'Say hello in the input below the terminal and press Enter or SEND. Use Shift+Enter for another line.'},
  {id:'full-shiritori',title:'Delegate a game of shiritori',target:'#promptInput',copy:'Use the workshop prompt below and send it to your parent agent to create one child with /delegate and play over ORRERY Mail. This step checks off after a fresh parent–child Mail round trip; let all three rounds finish.'},
  {id:'full-split',title:'Work side by side',target:'.col.roster',copy:'Modifier-click your parent and child in the agent list to show both terminals together. Use ⌘click on macOS or Ctrl+click on WSL.'},
  {id:'full-drag',title:'Move a pane',target:'.tabstrip',copy:'Drag a pane tab or split label to move it, or move a floating pane by its header. You can arrange the workspace around your task.'},
  {id:'full-planetarium',title:'Open Planetarium',target:'#planetariumBtn',copy:'Open PLANETARIUM to see who spawned whom. Find the parent and child from your game, then close the view.'},
  {id:'full-usage',title:'Read what is left',target:'#usageBtn',copy:'Open LEFT to see the remaining account allowance and when its windows reset, then close it. A stale or unavailable reading is labelled rather than shown as a current value.',manual:'I’ve seen it'},
  {id:'full-telemetry',title:'Open Telemetry',target:'#networkBtn',copy:'Open TELEMETRY for the crew’s status and history; fold or move this checklist when it covers a control. Cockpit is where you work with agents; Telemetry is where you observe and manage them.'},
  {id:'full-exit',title:'Exit from Deck',target:'#networkOverlay',copy:'On Deck, use EXIT on the shiritori child after the game has finished, then confirm. EXIT asks it to finish gracefully; your parent stays available.'},
  {id:'full-edge',title:'Read a Network edge',target:'#networkOverlay',copy:'Switch to Network and click the message count on the edge between your parent and child. Read the game’s Mail thread in the drawer.'},
  {id:'full-select',title:'Select several agents',target:'#networkOverlay',copy:'Turn on Select and click both agents, or drag a rectangle around them. The selection bar shows actions for the selected crew.'},
  {id:'full-replay',title:'Replay the collaboration',target:'#networkOverlay',copy:'Choose Replay to watch the selected agents’ history. Try play, pause or seeking; close Replay when you are done.'},
  {id:'full-resume',title:'Resume the child',target:'#networkOverlay',copy:'Open the exited child’s details and use RESUME when it is available, or select the child and use RESUME in the selection bar. If RESUME takes you to Cockpit, reopen TELEMETRY to continue; an already-running agent does not count as a resume.'},
  {id:'full-network-settings',title:'Adjust the Network',target:'#networkOverlay',copy:'In Network, close agent details if needed and fold this checklist to reach SETTINGS. Change a slider such as Node size or Link distance and watch the graph update.'},
  {id:'full-return',title:'Return to your agent',target:'#networkOverlay',copy:'Select a running agent in Telemetry and choose OPEN IN COCKPIT. Its terminal becomes your workspace again.'},
]);
const SHIRITORI_PROMPT="/delegate Start exactly one child agent, then play Japanese shiritori with it over ORRERY Mail (send_message), three turns each: exactly three round trips.\n\nRead and follow the installed ORRERY delegate skill. Use /delegate to create the child and ORRERY Mail (send_message) for every ready message and game move. Do not use Claude Code's built-in Agent or SendMessage tools. Include these same tool requirements in the child's embedded task. Use an available authenticated CLI: prefer a child from the other provider if available; otherwise use this provider. For a Claude child select Sonnet, never Haiku. Do not use --worktree for a Codex child. Keep the current working directory and existing ORRERY project identity. No native subagent tool, simulated dialogue, recursive delegation, game-output file edits, purchases, or external posting. Temporary task files required by the delegate skill are allowed.\n\nPut the complete rules in the child's embedded task. Its first action must send me ORRERY Mail with subject \"shiritori ready\" and body \"ready\", then wait through the documented Mail mechanism. Use the server-assigned names, not invented identities. If launch or Mail fails, report the exact failure and stop.\n\nRules: use common Japanese words in hiragana. Each word starts with the last hiragana character of the previous word. No repeated words; no word ending in ん. Match the exact ending character, including voicing; avoid small kana and long-vowel marks. Include romaji and a short English meaning so an English-speaking audience can follow.\n\nI am the parent player. My first word is りんご (ringo, apple). Send it to the child as \"shiritori round 1\". The child replies with a valid word; I validate it and send my next word for round 2; then repeat for round 3. This is six words total: parent/child, parent/child, parent/child. The ready message is not a word move. The child waits for actual messages and replies only once per numbered round. Permit one corrected reply if a move is invalid; report a failed game if it remains invalid.\n\nAt the end show a six-row table: round, sender, hiragana, romaji, meaning, and observed Mail ID when available. Check the chain and repetition explicitly. Distinguish actual messages from missing evidence; do not invent IDs. Tell the human which child was created and that cockpit EXIT is the cleanup action after accepting the result. Finish after three round trips, with no new game.";
const TELEMETRY_ACTIONS=Object.freeze({exit:'full-exit',edge:'full-edge',select:'full-select',
  replay:'full-replay',resume:'full-resume',settings:'full-network-settings',return:'full-return'});

function telemetryAction(event,origin,frame){
  const data=event&&event.data;
  if(!frame||!event||event.origin!==origin||event.source!==frame||!data||
     data.type!=='orrery-tour-action'||data.version!==1||typeof data.action!=='string')return null;
  return Object.prototype.hasOwnProperty.call(TELEMETRY_ACTIONS,data.action)
    ?TELEMETRY_ACTIONS[data.action]:null;
}

// A ready message is not a game move; old rounds and unrelated peers do not count.
function createShiritoriTracker(parent,since,afterId=0){
  const rounds=new Map(),seen=new Set();
  return {
    add(messages,agents){
      const children=new Set((Array.isArray(agents)?agents:[]).filter(a=>a&&a.parent===parent).map(a=>a.name));
      for(const m of Array.isArray(messages)?messages:[]){
        if(!m||m.id==null||seen.has(String(m.id)))continue;
        const id=Number(m.id);
        if(!Number.isSafeInteger(id)||id<=afterId)continue;
        const rawTime=m.ts_unix??m.ts??m.created_ts??m.timestamp;
        const ts=typeof rawTime==='number'?rawTime*1000:Date.parse(rawTime);
        if(!Number.isFinite(ts)||ts<since||/^ready\s*$/i.test(String(m.body??m.body_md??m.excerpt??'').trim()))continue;
        const sender=String(m.sender||'');
        const recipients=(Array.isArray(m.recipients)?m.recipients:[]).filter(Boolean).map(r=>typeof r==='string'?r:r.name??r.recipient);
        if(m.recipient)recipients.push(m.recipient);
        let child=null,direction=null;
        if(sender===parent){child=recipients.find(r=>children.has(r));direction='out';}
        else if(children.has(sender)&&recipients.includes(parent)){child=sender;direction='in';}
        if(!child)continue;
        seen.add(String(m.id));
        const pair=rounds.get(child)||{},prior=pair[direction];
        if(!prior||(direction==='out'?id<prior.id:id>prior.id))pair[direction]={id,ts};
        rounds.set(child,pair);
      }
      return !!this.child();
    },
    // The child that played a full round with the parent, once there is one.
    child(){
      for(const [name,pair] of rounds)if(pair.out&&pair.in&&pair.in.id>pair.out.id&&pair.in.ts>=pair.out.ts)return name;
      return null;
    },
  };
}

const API={STEPS,SHIRITORI_PROMPT,TELEMETRY_ACTIONS,telemetryAction,createShiritoriTracker};
if(typeof module!=='undefined'&&module.exports)module.exports=API;
root.OrreryFullTour=API;
if(!root.document)return;
function mount(){
  const doc=root.document,shared=root.OrreryTour;
  if(!shared||!shared.mountChecklist||doc.documentElement.classList.contains('pane-window'))return;
  const tour=shared.mountChecklist({id:'full-tour',title:'Full tour',steps:STEPS,
    storageKey:'oc-full-tour-v1',autoOpen:false,meta:'16 steps · about 10 minutes',
    footer:'Follow the steps in order. Reopen anytime in Settings.'});
  if(!tour)return;
  API.checklist=tour;
  const row=tour.el.querySelector('[data-step="full-shiritori"]');
  const copy=doc.createElement('button');copy.type='button';copy.className='flight-read';row.append(copy);
  let visibleStep=null;
  function revealCurrent(){
    const id=tour.state.current?.id;
    if(tour.el.hidden||(!tour.solo&&tour.state.folded)||id===visibleStep)return;
    visibleStep=id;
    if(id)root.requestAnimationFrame(()=>{
      if(!tour.el.hidden&&(tour.solo||!tour.state.folded))tour.el.querySelector('[data-step="'+id+'"]').scrollIntoView({block:'nearest'});
    });
  }
  tour.onChange(revealCurrent);revealCurrent();
  // A separate tour window only presents progress; it never operates agents.
  if(tour.solo){
    copy.textContent='Copy workshop prompt';
    copy.addEventListener('click',async()=>{
      try{await root.navigator.clipboard.writeText(SHIRITORI_PROMPT);copy.textContent='Copied · paste into your parent’s input';}
      catch(_){copy.textContent='Clipboard unavailable · reopen this step in Cockpit';}
    });
    tour.render();return;
  }
  const oc=root.OC;
  if(!oc)return;
  if(tour.state.open&&shared.firstFlight?.state.open)shared.firstFlight.close();
  let lastTalk=null,choosePending=null,returnArmed=false,returnPending=null;
  let context=null,tracker=null;
  const contextKey='oc-full-tour-shiritori-v1';
  try{context=JSON.parse(root.localStorage.getItem(contextKey));}catch(_){}
  if(context&&typeof context.parent==='string'&&Number.isFinite(context.since))
    tracker=createShiritoriTracker(context.parent,context.since,context.afterId||0);
  else context=null;
  function current(id){return tour.state.open&&tour.state.current?.id===id;}
  function mark(id){return current(id)&&tour.mark(id);}
  function saveContext(){try{if(context)root.localStorage.setItem(contextKey,JSON.stringify(context));else root.localStorage.removeItem(contextKey);}catch(_){}}
  copy.textContent='Use workshop prompt';
  copy.addEventListener('click',()=>{
    const input=doc.getElementById('promptInput');
    if(!context||oc.activeAgent()!==context.parent){root.showToast('Choose your parent agent first.',true);return;}
    if(input.value.trim()&&input.value!==SHIRITORI_PROMPT){root.showToast('Send or clear your draft first.',true);return;}
    input.value=SHIRITORI_PROMPT;input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();
  });
  function observeMail(){
    if(!current('full-shiritori')||!tracker)return;
    const agents=oc.agents().map(a=>({...a,parent:oc.lineageParent.get(a.name)}));
    if(tracker.add(oc.mailBacklog(),agents)){
      // Kept for the Network edge step, which may come after a reload.
      context.child=tracker.child();saveContext();
      mark('full-shiritori');
    }
  }
  function changed(){
    copy.hidden=!current('full-shiritori');
    if(!current('full-choose'))choosePending=null;
    if(current('full-start')){context=null;tracker=null;lastTalk=null;saveContext();}
    if(current('full-shiritori')&&!context){
      const parent=lastTalk||oc.activeAgent();
      if(parent){context={parent,since:Math.floor(Date.now()/1000)*1000,afterId:Math.max(0,...oc.mailBacklog().map(m=>Number(m.id)||0))};tracker=createShiritoriTracker(parent,context.since,context.afterId);saveContext();}
    }
    if(!current('full-return')){returnArmed=false;returnPending=null;}
    observeMail();
  }
  tour.onChange(changed);changed();
  shared.addSettingsEntry('Full tour',()=>{
    if(shared.firstFlight?.state.open)shared.firstFlight.close();
    tour.show();
  },'fullTourBtn');
  // Opening either guide presents a single checklist, keeping their progress independent.
  shared.firstFlight?.onChange(()=>{if(shared.firstFlight.state.open&&tour.state.open)tour.close();});
  doc.getElementById('helpMapBtn')?.addEventListener('click',()=>tour.close());
  doc.addEventListener('oc:full-tour-action',event=>mark(event.detail?.id));
  doc.addEventListener('oc:telemetry-return',event=>{
    if(returnArmed&&current('full-return')){
      returnPending=event.detail?.name;returnArmed=false;
    }
  });
  doc.addEventListener('oc:planetarium-closed',()=>mark('full-planetarium'));
  doc.addEventListener('oc:tour-action',event=>{
    const detail=event.detail||{};
    if(detail.tour==='full-tour'){mark(detail.id);return;}
    if(detail.tour!==undefined)return;
    if(detail.id==='choose'&&current('full-choose')){
      choosePending=detail.name;
      if(choosePending&&oc.activeAgent()===choosePending&&doc.querySelector('.termhost.on'))mark('full-choose');
      return;
    }
    if(detail.id==='talk'&&current('full-talk'))lastTalk=detail.name||oc.activeAgent();
    // Planetarium checks off when the view closes (oc:planetarium-closed), as its text says.
    const ids={start:'full-start',talk:'full-talk',telemetry:'full-telemetry'};
    if(ids[detail.id])mark(ids[detail.id]);
  });
  function focused(event){
    const name=event.detail?.name;
    if(name&&name===choosePending&&mark('full-choose'))choosePending=null;
    if(name&&name===returnPending&&!doc.getElementById('networkOverlay').classList.contains('on'))mark('full-return');
  }
  doc.addEventListener('oc:focus-agent',focused);
  doc.addEventListener('oc:tour-focus',focused);
  doc.addEventListener('oc:mail',observeMail);doc.addEventListener('oc:agents',observeMail);
  root.addEventListener('message',event=>{
    const frame=doc.getElementById('networkFrame')?.contentWindow;
    const id=telemetryAction(event,root.location.origin,frame);
    if(id==='full-return'){if(current(id))returnArmed=true;return;}
    if(id){mark(id);return;}
  });
  // The Telemetry steps happen inside the embedded page, which this page
  // cannot ring into: it is told the step instead and rings its own control
  // (orrery-telemetry dashboard/tour_cue.js). The checklist, folded or not,
  // lies over the page; the cue's tag keeps clear of it (avoid, in the
  // frame's coordinates). Sent only when something changed.
  const overlay=doc.getElementById('networkOverlay'),frameEl=doc.getElementById('networkFrame');
  if(!overlay||!frameEl)return;
  let lastCue='';
  function sendCue(force){
    const win=frameEl.contentWindow;if(!win)return;
    const id=tour.state.current?.id,step=STEPS.find(s=>s.id===id);
    const cue=tour.state.open&&step&&step.target==='#networkOverlay'&&overlay.classList.contains('on')?id:null;
    const avoid=[];
    if(cue&&!tour.el.hidden){
      const f=frameEl.getBoundingClientRect(),g=tour.el.getBoundingClientRect();
      if(g.width&&g.height)avoid.push({l:Math.round(g.left-f.left),t:Math.round(g.top-f.top),r:Math.round(g.right-f.left),b:Math.round(g.bottom-f.top)});
    }
    // The game's parent and child, so the page can ring their edge and not
    // another one; without them it rings no edge at all.
    const child=cue&&context?(typeof context.child==='string'&&context.child)||(tracker&&tracker.child()):null;
    const message={type:'orrery-tour-cue',version:1,step:cue,avoid,...(child?{pair:[context.parent,child]}:{})};
    const key=JSON.stringify(message);
    if(!force&&key===lastCue)return;
    lastCue=key;
    try{win.postMessage(message,root.location.origin);}catch(_){}
  }
  tour.onChange(()=>sendCue());
  new MutationObserver(()=>sendCue()).observe(overlay,{attributes:true,attributeFilter:['class']});
  // A reloaded page forgot the cue.
  frameEl.addEventListener('load',()=>sendCue(true));
  root.addEventListener('resize',()=>sendCue());
  // The checklist can be dragged over the page without a tour change.
  setInterval(()=>sendCue(),1000);
  API.sendCue=sendCue;
}
if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})(typeof window==='undefined'?globalThis:window);
