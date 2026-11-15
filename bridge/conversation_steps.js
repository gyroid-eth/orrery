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
  function collect(events,provider){
    if(!['Claude','Codex'].includes(provider))return {groups:[],consumed:new Set()};
    const enabled=events.some(e=>e.step||e.step_turn||e.step_boundary);
    if(!enabled)return {groups:[],consumed:new Set()};
    const groups=new Map(),consumed=new Set(),calls=new Map(),results=new Map();
    let current=null;
    function group(id){
      if(!groups.has(id))groups.set(id,{id,steps:new Map(),started:NaN,ended:NaN,last:NaN,
        duration:null,closed:false,anchor:null,orphans:0});
      return groups.get(id);
    }
    function active(){return current||(current=group('partial'));}
    for(const event of events){
      if(provider==='Claude'&&event.step_boundary){
        if(current)current.closed=true;
        current=group('prompt:'+event.id);current.started=time(event.ts);
      }
      const boundary=event.step_turn;
      if(provider==='Codex'&&boundary&&key(boundary.id)){
        current=group(boundary.id);consumed.add(event.id);
        if(Number.isFinite(time(boundary.started)))current.started=time(boundary.started);
        if(boundary.phase==='end'){
          current.closed=true;current.ended=time(boundary.ended)||time(event.ts);
          if(typeof boundary.duration==='number'){current.duration=boundary.duration/1000;current.explicitDuration=true;}
        }else if(!Number.isFinite(current.started))current.started=time(event.ts);
      }
      if(current&&event.kind==='text'&&event.role==='assistant')current.last=time(event.ts);
      if(provider==='Codex'&&event.step_wrapper===true)consumed.add(event.id);
      const step=event.step;
      if(!step||!key(step.id))continue;
      if(step.phase==='call'&&provider==='Claude'){
        const owner=active();owner.anchor??=event.id;
        calls.set(step.id,{step,event,owner});
      }else if(step.phase==='result'&&provider==='Claude'){
        consumed.add(event.id);
        results.set(step.id,{step,event,owner:active()});
      }else if(step.phase==='complete'&&provider==='Codex'){
        consumed.add(event.id);
        const owner=key(step.turn)?group(step.turn):active();
        current=owner;owner.anchor??=event.id;
        owner.steps.set(step.id,{...step,eventId:event.id});
      }
    }
    for(const [id,call] of calls){
      const result=results.get(id);
      if(result){
        consumed.add(call.event.id);
        call.owner.steps.set(id,{...call.step,...result.step,phase:'complete',
          eventId:call.event.id,resultId:result.event.id});
      }
    }
    for(const [id,result] of results)if(!calls.has(id)){
      result.owner.orphans++;result.owner.anchor??=result.event.id;
    }
    const values=[...groups.values()];
    values.forEach((g,i)=>{
      if(i<values.length-1)g.closed=true;
      g.steps=[...g.steps.values()];
      const starts=g.steps.map(s=>time(s.started)).filter(Number.isFinite);
      const ends=g.steps.map(s=>time(s.ended)).filter(Number.isFinite);
      if(!Number.isFinite(g.started)&&starts.length)g.started=Math.min(...starts);
      if(!Number.isFinite(g.ended)&&ends.length)g.ended=Math.max(...ends,Number.isFinite(g.last)?g.last:0);
      if(g.duration===null&&Number.isFinite(g.started)&&Number.isFinite(g.ended)&&g.ended>=g.started)
        g.duration=(g.ended-g.started)/1000;
    });
    return {groups:values,consumed};
  }

  function mount({host,mutate=fn=>fn(),onFocusLost=()=>{}}){
    const cards=new Map();let model={groups:[],consumed:new Set()},current={},visible=false,timer=0,serial=0;
    const make=(tag,cls,value)=>{const node=root.document.createElement(tag);node.className=cls;if(value!==undefined)node.textContent=value;return node;};
    function changed(node,value){if(node.textContent!==value)node.textContent=value;}
    function icon(status){
      const node=make('span','conversation-step-icon '+status);node.setAttribute('aria-hidden','true');
      node.innerHTML=status==='observed'?'<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="4.5"/></svg>':
        status==='failed'?'<svg viewBox="0 0 16 16"><path d="M4.5 4.5 11.5 11.5M11.5 4.5 4.5 11.5"/></svg>':
        '<svg viewBox="0 0 16 16"><path class="conversation-step-check" pathLength="1" d="M3.5 8.5 6.5 11.5 12.5 4.5"/></svg>';
      return node;
    }
    function setOpen(card,open){
      if(!open&&card.body.contains(root.document.activeElement))card.button.focus({preventScroll:true});
      card.open=open;card.node.classList.toggle('is-open',open);card.button.setAttribute('aria-expanded',String(open));
      card.body.inert=!open;
    }
    function create(id){
      const node=make('section','conversation-steps');node.dataset.stepsGroup=id;node.setAttribute('aria-label','Agent steps');
      const button=make('button','conversation-steps-toggle');button.type='button';
      const heading=make('span','conversation-steps-heading'),clock=make('span','conversation-steps-time');
      const count=make('span','conversation-steps-count'),chevron=make('span','conversation-steps-chevron','⌄');chevron.setAttribute('aria-hidden','true');
      button.append(heading,clock,count,chevron);
      const body=make('div','conversation-steps-expansion'),inner=make('div','conversation-steps-inner');
      body.id='conversation-steps-'+(++serial)+'-'+Math.random().toString(36).slice(2);button.setAttribute('aria-controls',body.id);
      const label=make('div','conversation-steps-label','Agent steps'),list=make('ol','conversation-steps-list');
      const notice=make('p','conversation-steps-notice','Load earlier to see the matching tool requests.');notice.hidden=true;
      inner.append(label,list,notice);body.append(inner);node.append(button,body);
      const card={node,button,heading,clock,count,body,list,notice,rows:new Map(),open:false,working:false,waiting:false,
        clockValue:null,clockAt:0,lastWork:null,lastInput:null};
      button.addEventListener('click',()=>mutate(()=>setOpen(card,!card.open)));
      setOpen(card,false);return card;
    }
    function row(step,animate){
      const node=make('li','conversation-step'+(animate?' is-new':''));
      const status=['done','failed'].includes(step.status)?step.status:'observed';
      const copy=make('div','conversation-step-copy'),top=make('div','conversation-step-top');
      const tool=make('span','conversation-step-tool',text(step.tool).split('__').at(-1));
      const outcome=make('span','conversation-step-outcome',status==='failed'?'Failed':status==='observed'?'Observed':'');
      const start=time(step.started),end=time(step.ended);
      top.append(tool,outcome,make('span','conversation-step-duration',
        Number.isFinite(start)&&Number.isFinite(end)&&end>=start?duration((end-start)/1000):''));
      copy.append(top);
      if(step.detail)copy.append(make('div','conversation-step-target',text(step.detail)));
      node.append(icon(status),copy);return node;
    }
    function title(card,value,working){
      if(card.title===value&&card.wave===working)return;
      card.title=value;card.wave=working;card.heading.replaceChildren();
      if(working){
        Array.from('Working…').forEach((char,index)=>{
          const span=make('span','conversation-steps-letter',char);span.style.animationDelay=(index*.05)+'s';card.heading.append(span);
        });
      }else card.heading.textContent=value;
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
        if(!card.initialized||was!==now){
          setOpen(card,now);card.initialized=true;
        }
        card.working=working;card.waiting=waiting;
        const compacting=working&&current.reader_phase==='compacting';
        const finished=g.explicitDuration?g.duration:card.lastWork??g.duration;
        title(card,working?(compacting?'Compacting context…':'Working…'):waiting?'Waiting for you':
          finished!==null?'Worked for '+duration(finished):'Recorded work',working&&!compacting);
        changed(card.clock,working&&card.lastWork!==null?duration(card.lastWork):'');
        changed(card.count,'· '+g.steps.length+(g.steps.length===1?' step':' steps'));
        card.node.classList.toggle('is-paused',!visible);
        card.node.hidden=!g.steps.length&&!g.orphans&&!now;
        ticking=ticking||working&&visible;
      }
      if(ticking&&!timer)timer=root.setInterval(paint,500);
      if(!ticking&&timer){root.clearInterval(timer);timer=0;}
    }
    function sync({events,provider,mode,rows,context,isVisible}){
      current=context||{};visible=isVisible;
      model=['snapshot','fresh_tail'].includes(mode)?{groups:[],consumed:new Set()}:collect(events,provider);
      const wanted=new Set(model.groups.map(g=>g.id)),byId=new Map(rows.map(r=>[r.dataset.eventId,r]));
      for(const [id,card] of cards)if(!wanted.has(id)){
        if(card.node.contains(root.document.activeElement))onFocusLost();card.node.remove();cards.delete(id);
      }
      for(const g of model.groups){
        const existed=cards.has(g.id),card=cards.get(g.id)||create(g.id);cards.set(g.id,card);
        const ids=new Set(g.steps.map(s=>s.id));
        for(const [id,record] of card.rows)if(!ids.has(id)){record.node.remove();card.rows.delete(id);}
        for(const [index,step] of g.steps.entries()){
          const fingerprint=JSON.stringify(step),record=card.rows.get(step.id);
          if(!record||record.fingerprint!==fingerprint){
            const node=row(step,existed);if(record)record.node.replaceWith(node);
            card.rows.set(step.id,{node,fingerprint});
          }
          const node=card.rows.get(step.id).node;
          if(card.list.children[index]!==node)card.list.insertBefore(node,card.list.children[index]||null);
        }
        const nodes=[...card.list.children];nodes.forEach((node,index)=>node.classList.toggle('has-next',index<nodes.length-1));
        card.notice.hidden=!g.orphans;
        const anchor=byId.get(g.anchor);
        if(anchor){if(card.node.nextSibling!==anchor)anchor.before(card.node);}
        else if(card.node.parentElement!==host)host.append(card.node);
      }
      paint();return model.consumed;
    }
    return Object.freeze({sync,
      activity(context,isVisible){current=context||{};visible=isVisible;paint();return [...cards.values()].some(c=>!c.node.hidden&&(c.working||c.waiting));},
      reset(){if(timer)root.clearInterval(timer);timer=0;for(const card of cards.values())card.node.remove();cards.clear();model={groups:[],consumed:new Set()};},
    });
  }
  const api={collect,duration,elapsed,mount};
  root.OrreryConversationSteps=Object.freeze(api);
  if(typeof module!=='undefined')module.exports=api;
})(typeof window==='undefined'?globalThis:window);
