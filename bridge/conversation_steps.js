/**
 * @author: @kokonutui
 * @description: AI Loading State
 * @version: 2.0.0
 * @date: 2026-10-14
 * @license: MIT
 * @website: https://kokonutui.com
 * @github: https://github.com/kokonut-labs/kokonutui
 *
 * ORRERY: bounded recorded operations, vanilla DOM, no tool execution.
 */
/*
MIT License

Copyright (c) 2025 kokonutUI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
(function(root){
  'use strict';
  const time=value=>typeof value==='number'&&Number.isFinite(value)?value:
    typeof value==='string'&&value?Date.parse(value):NaN;
  const key=value=>typeof value==='string'&&/^[a-f0-9]{32}$/.test(value);
  const text=value=>typeof value==='string'?value:'';
  function duration(seconds){
    seconds=Math.max(0,Math.floor(seconds));
    const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;
    return (h?h+'h ':'')+(m||h?m+'m ':'')+(m||h?String(s).padStart(2,'0'):s)+'s';
  }
  function elapsed(value){
    if(typeof value!=='string')return null;
    const match=/^\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?\s*$/.exec(value);
    return match&&match.slice(1).some(Boolean)?Number(match[1]||0)*3600+Number(match[2]||0)*60+Number(match[3]||0):null;
  }
  function collect(events,provider,{working=false,native=true,activeCalls=new Set()}={}){
    const enabled=native&&['Claude','Codex'].includes(provider)&&events.some(e=>e.step||e.step_turn||e.step_boundary);
    const pending=new Set();
    if(!enabled&&!working)return {groups:[],consumed:new Set(),pending};
    const groups=[],consumed=new Set(),calls=new Map(),results=new Map(),completions=new Map();
    const codexCalls=new Map(),recordOrder=new Map();
    let current=null,segment='partial',turn=null,tail=[];
    function cut(event){
      if(current)current.closed=true;
      current=null;segment='after:'+event.id;
    }
    function startTurn(event,id,started){
      cut(event);turn={id,started,groups:[]};
    }
    function active(){
      if(!current){
        current={id:segment,steps:new Map(),started:NaN,ended:NaN,duration:null,
          closed:false,anchor:null,orphans:0};
        groups.push(current);turn?.groups.push(current);
      }
      return current;
    }
    for(const [index,event] of events.entries()){
      recordOrder.set(event.id,index);
      if(working){
        if(['tool','tool_result'].includes(event.kind))tail.push(event);
        else tail=[];
      }
      if(!enabled){
        if(!['tool','tool_result'].includes(event.kind))cut(event);
        continue;
      }
      const boundary=event.step_turn;
      if(provider==='Codex'&&boundary&&key(boundary.id)){
        consumed.add(event.id);
        if(boundary.phase==='start'){
          startTurn(event,boundary.id,boundary.started??event.ts);
        }else if(!turn||turn.id===boundary.id){
          // The native elapsed time describes the whole turn. It applies to
          // a card only when the turn has a single run of operations.
          if(turn?.groups.length===1){
            const [only]=turn.groups;
            only.started=time(boundary.started??turn.started);
            only.ended=time(boundary.ended??event.ts);
            if(typeof boundary.duration==='number')only.duration=boundary.duration/1000;
          }
          cut(event);turn=null;
        }
        continue;
      }
      if(provider==='Codex'&&event.step_wrapper===true)consumed.add(event.id);
      const step=event.step;
      if(provider==='Codex'&&event.kind==='tool'&&key(event.tool_call_id)&&!step&&!event.step_wrapper)
        codexCalls.set(event.tool_call_id,event);
      if(step&&key(step.id)){
        if(step.phase==='call'&&provider==='Claude'){
          const owner=active();owner.anchor??=event.id;
          calls.set(step.id,{step,event,owner});
        }else if(step.phase==='result'&&provider==='Claude'){
          consumed.add(event.id);
          results.set(step.id,{step,event,owner:calls.has(step.id)?null:active()});
        }else if(step.phase==='complete'&&provider==='Codex'){
          consumed.add(event.id);
          const request=codexCalls.get(event.tool_call_id||step.id);
          if(request)consumed.add(request.id);
          const id=key(step.turn)?step.turn:turn?.id;
          const completionKey=(id||'')+':'+step.id;
          let completion=completions.get(completionKey);
          if(!completion){
            if(id&&turn?.id!==id)startTurn(event,id);
            const owner=active();owner.anchor??=request?.id||event.id;
            completion={owner,eventId:request?.id||event.id};completions.set(completionKey,completion);
          }
          const stepId=request?'record:'+request.id:step.id;
          completion.owner.steps.set(stepId,{...step,id:stepId,eventId:completion.eventId});
        }
      }
      // A tool request can also emit a visible Mail card. Record its step
      // before the separator so subsequent requests start below the card.
      if(event.step_boundary)cut(event);
    }
    for(const [id,call] of calls){
      const result=results.get(id);
      if(result){
        consumed.add(call.event.id);
        call.owner.steps.set(id,{...call.step,...result.step,phase:'complete',
          eventId:call.event.id,resultId:result.event.id});
      }else if(working&&call.owner===current||activeCalls.has(id)){
        // An idle observation can arrive before the transcript's result.
        // Keep a displayed request in its original run until it resolves.
        pending.add(id);
        consumed.add(call.event.id);
        call.owner.steps.set(id,{...call.step,status:working?'running':'observed',eventId:call.event.id});
      }
    }
    for(const [id,result] of results)if(!calls.has(id)){
      result.owner.orphans++;result.owner.anchor??=result.event.id;
    }
    if(working){
      const unprojected=tail.filter(event=>!consumed.has(event.id));
      const requests=unprojected.filter(event=>event.kind==='tool');
      if(requests.length){
        const owner=active();
        for(const event of requests){
          consumed.add(event.id);
          owner.anchor??=event.id;
          owner.steps.set('record:'+event.id,{id:'record:'+event.id,tool:event.text,
            status:'observed',started:event.ts,eventId:event.id});
        }
        for(const event of unprojected)if(event.kind==='tool_result')consumed.add(event.id);
      }
    }
    if(enabled&&!current&&(provider==='Claude'||turn))active();
    for(const g of groups){
      g.steps=[...g.steps.values()].sort((a,b)=>recordOrder.get(a.eventId)-recordOrder.get(b.eventId));
      const starts=g.steps.map(s=>time(s.started)).filter(Number.isFinite);
      const ends=g.steps.map(s=>time(s.ended)).filter(Number.isFinite);
      if(!Number.isFinite(g.started)&&starts.length)g.started=Math.min(...starts);
      if(!Number.isFinite(g.ended)&&ends.length)g.ended=Math.max(...ends);
      if(g.duration===null&&Number.isFinite(g.started)&&Number.isFinite(g.ended)&&g.ended>=g.started)
        g.duration=(g.ended-g.started)/1000;
    }
    return {groups,consumed,pending};
  }

  function mount({host,mutate=fn=>fn(),onFocusLost=()=>{}}){
    const cards=new Map();let model={groups:[],consumed:new Set()},current={},visible=false,timer=0,serial=0,workingModel=false;
    function activityState(context){
      // A missed terminal sample does not end the recorded run.
      return context?.running===true?(context.act_state||current.act_state):null;
    }
    const doingWork=context=>['work','ask','question'].includes(activityState(context));
    function setActivity(context,isVisible){
      current={...context,act_state:activityState(context)};visible=isVisible;
    }
    const heightSpring=root.OrreryConversationMotion?.spring(260,24);
    const reduced=root.matchMedia?.('(prefers-reduced-motion: reduce)');
    const make=(tag,cls,value)=>{const node=root.document.createElement(tag);node.className=cls;if(value!==undefined)node.textContent=value;return node;};
    function changed(node,value){if(node.textContent!==value)node.textContent=value;}
    function icon(status){
      const node=make('span','conversation-step-icon '+status);node.setAttribute('aria-hidden','true');
      node.innerHTML=['observed','running'].includes(status)?'<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="4.5"/></svg>':
        status==='failed'?'<svg viewBox="0 0 16 16"><path d="M4.5 4.5 11.5 11.5M11.5 4.5 4.5 11.5"/></svg>':
        '<svg viewBox="0 0 16 16"><path class="conversation-step-check" pathLength="1" d="M3.5 8.5 6.5 11.5 12.5 4.5"/></svg>';
      return node;
    }
    function setOpen(card,open,animate=false){
      const {body}=card;
      const from=animate&&visible&&heightSpring&&!reduced?.matches?body.getBoundingClientRect().height:null;
      card.animation?.cancel();card.animation=null;
      if(!open&&card.body.contains(root.document.activeElement))card.button.focus({preventScroll:true});
      card.open=open;card.node.classList.toggle('is-open',open);card.button.setAttribute('aria-expanded',String(open));
      body.inert=!open;
      if(from===null)return;
      const to=body.getBoundingClientRect().height;
      if(Math.abs(to-from)<.5)return;
      const animation=body.animate(heightSpring.map(value=>({height:Math.max(0,from+(to-from)*value)+'px'})),
        {duration:(heightSpring.length-1)*1000/60,fill:'backwards'});
      card.animation=animation;
      const forget=()=>{if(card.animation===animation)card.animation=null;};
      animation.finished.then(forget,forget);
    }
    function create(id){
      const node=make('section','conversation-steps');node.dataset.stepsGroup=id;node.setAttribute('aria-label','Agent steps');
      const button=make('button','conversation-steps-toggle');button.type='button';
      const symbol=make('span','conversation-steps-symbol');symbol.setAttribute('aria-hidden','true');
      symbol.innerHTML='<svg viewBox="0 0 16 16"><path d="M5 4h8M5 8h8M5 12h8M2.5 4h.01m-.01 4h.01m-.01 4h.01"/></svg>';
      const heading=make('span','conversation-steps-heading');
      const summary=make('span','conversation-steps-summary'),count=make('span','conversation-steps-count'),clock=make('span','conversation-steps-time');
      summary.append(count,clock);
      const chevron=make('span','conversation-steps-chevron');chevron.setAttribute('aria-hidden','true');
      chevron.innerHTML='<svg viewBox="0 0 16 16"><path d="m4 6 4 4 4-4"/></svg>';
      button.append(symbol,heading,summary,chevron);
      const body=make('div','conversation-steps-expansion'),inner=make('div','conversation-steps-inner');
      body.id='conversation-steps-'+(++serial)+'-'+Math.random().toString(36).slice(2);button.setAttribute('aria-controls',body.id);
      const list=make('ol','conversation-steps-list');
      const notice=make('p','conversation-steps-notice','Load earlier to see the matching tool requests.');notice.hidden=true;
      inner.append(list,notice);body.append(inner);node.append(button,body);
      const card={node,button,heading,clock,count,body,list,notice,rows:new Map(),open:false,working:false,waiting:false,
        clockValue:null,clockAt:0,lastWork:null,lastInput:null};
      button.addEventListener('click',()=>mutate(()=>setOpen(card,!card.open,true)));
      setOpen(card,false);return card;
    }
    function createRow(animate){
      const node=make('li','conversation-step'+(animate?' is-new':''));
      const copy=make('div','conversation-step-copy'),top=make('div','conversation-step-top');
      const tool=make('span','conversation-step-tool'),outcome=make('span','conversation-step-outcome');
      const clock=make('span','conversation-step-duration'),detail=make('div','conversation-step-target');
      top.append(tool,outcome,clock);copy.append(top,detail);node.append(copy);
      return {node,tool,outcome,clock,detail,icon:null,status:'',fingerprint:''};
    }
    function updateRow(record,step){
      const status=['done','failed','running'].includes(step.status)?step.status:'observed';
      if(record.status!==status){
        const symbol=icon(status);
        if(record.icon)record.icon.replaceWith(symbol);else record.node.prepend(symbol);
        record.icon=symbol;record.status=status;
      }
      changed(record.tool,text(step.tool).split('__').at(-1));
      changed(record.outcome,status==='failed'?'Failed':status==='running'?'Running…':status==='observed'?'Observed':'');
      const start=time(step.started),end=time(step.ended);
      changed(record.clock,Number.isFinite(start)&&Number.isFinite(end)&&end>=start?duration((end-start)/1000):'');
      changed(record.detail,text(step.detail));record.detail.hidden=!step.detail;
    }
    function paint(){
      const last=model.groups.at(-1);let ticking=false;
      for(const g of model.groups){
        const card=cards.get(g.id);if(!card)continue;
        const working=g===last&&!g.closed&&current.running===true&&current.act_state==='work';
        const waiting=g===last&&!g.closed&&current.running===true&&['ask','question'].includes(current.act_state);
        const seconds=elapsed(current.work_disp);
        if(working){
          if(card.lastInput!==current.work_disp||!card.working){
            card.clockValue=seconds;card.clockAt=Date.now();card.lastInput=current.work_disp;
          }
          card.lastWork=card.clockValue===null?null:card.clockValue+(Date.now()-card.clockAt)/1000;
        }
        const was=card.working||card.waiting,now=working||waiting;
        if(was&&!now&&card.open)setOpen(card,false);
        card.working=working;card.waiting=waiting;
        const compacting=working&&current.reader_phase==='compacting';
        const finished=g.closed?(g.duration??card.lastWork):(card.lastWork??g.duration);
        const status=working?(compacting?'Compacting context…':'Working…'):waiting?'Waiting for you':'';
        const unit=now?'step':'tool call';
        const count=g.steps.length+' '+unit+(g.steps.length===1?'':'s');
        const secondsShown=working?card.lastWork:finished;
        const clock=secondsShown===null?'':', '+duration(secondsShown);
        changed(card.heading,status);card.heading.hidden=!status;
        changed(card.count,count);changed(card.clock,clock);
        const label=(status?status+' ':'')+count+clock;
        if(card.button.title!==label){card.button.title=label;card.button.setAttribute('aria-label',label);}
        card.heading.classList.toggle('is-working',working&&!compacting);
        card.node.classList.toggle('is-paused',!visible);
        card.node.hidden=!g.steps.length&&!g.orphans&&!now;
        if(!visible)card.animation?.cancel();
        ticking=ticking||working&&visible;
      }
      if(ticking&&!timer)timer=root.setInterval(paint,500);
      if(!ticking&&timer){root.clearInterval(timer);timer=0;}
    }
    function sync({events,provider,mode,rows,context,isVisible}){
      setActivity(context,isVisible);
      workingModel=doingWork(current);
      model=collect(events,provider,{working:workingModel,native:!['snapshot','fresh_tail'].includes(mode),
        activeCalls:model.pending});
      const wanted=new Set(model.groups.map(g=>g.id)),byId=new Map(rows.map(r=>[r.dataset.eventId,r]));
      for(const [id,card] of cards)if(!wanted.has(id)){
        if(card.node.contains(root.document.activeElement))onFocusLost();card.animation?.cancel();card.node.remove();cards.delete(id);
      }
      for(const g of model.groups){
        const existed=cards.has(g.id),card=cards.get(g.id)||create(g.id);cards.set(g.id,card);
        const ids=new Set(g.steps.map(s=>s.id));
        for(const [id,record] of card.rows)if(!ids.has(id)){record.node.remove();card.rows.delete(id);}
        for(const [index,step] of g.steps.entries()){
          const fingerprint=JSON.stringify(step),record=card.rows.get(step.id)||createRow(existed);
          if(record.fingerprint!==fingerprint){updateRow(record,step);record.fingerprint=fingerprint;}
          card.rows.set(step.id,record);
          const node=record.node;
          if(card.list.children[index]!==node)card.list.insertBefore(node,card.list.children[index]||null);
        }
        card.notice.hidden=!g.orphans;
        const anchor=byId.get(g.anchor);
        if(anchor){if(card.node.nextSibling!==anchor)anchor.before(card.node);}
        else if(card.node.parentElement!==host)host.append(card.node);
      }
      paint();return model.consumed;
    }
    return Object.freeze({sync,needsSync:context=>workingModel!==doingWork(context),
      activity(context,isVisible){setActivity(context,isVisible);paint();return [...cards.values()].some(c=>!c.node.hidden&&(c.working||c.waiting));},
      reset(){if(timer)root.clearInterval(timer);timer=0;for(const card of cards.values()){card.animation?.cancel();card.node.remove();}cards.clear();model={groups:[],consumed:new Set()};current={};workingModel=false;},
    });
  }
  const api={collect,duration,elapsed,mount};
  root.OrreryConversationSteps=Object.freeze(api);
  if(typeof module!=='undefined')module.exports=api;
})(typeof window==='undefined'?globalThis:window);
