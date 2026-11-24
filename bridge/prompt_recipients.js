/* Explicit destinations are separate from the text delivered to an agent. */
(function(root){
  'use strict';
  const rowHeight=40,padding=4,limit=6;
  function queryAt(text,start,end){
    if(start!==end)return null;
    const match=/(?:^|\s)@([\p{L}\p{N}_-]*)$/u.exec(text.slice(0,start));
    if(!match)return null;
    const tail=/^[^\s@]*/u.exec(text.slice(start))[0];
    const complete=match[1]+tail;
    if(!/^[\p{L}\p{N}_-]*$/u.test(complete))return null;
    return {start:start-match[1].length-1,end:start+tail.length,word:match[1].toLowerCase()};
  }
  function matches(name,role,word){
    const words=value=>value.replace(/([a-z0-9])([A-Z])/g,'$1 $2').split(/[\s_-]+/);
    return [name,role,...words(name),...words(role)].some(part=>part.toLowerCase().startsWith(word));
  }
  const element=(tag,cls)=>{
    const node=document.createElement(tag);node.className=cls;return node;
  };
  function mount({input,meta,portrait,getAgents,getRole,getRefusal,getProvider,onChange,onText}){
    const picker=element('div','prompt-mentions'),band=element('div','prompt-mention-band');
    picker.id='promptMentions';picker.setAttribute('role','listbox');picker.setAttribute('aria-label','Choose a recipient');
    band.setAttribute('aria-hidden','true');picker.append(band);document.body.append(picker);
    input.setAttribute('aria-controls',picker.id);
    input.setAttribute('aria-autocomplete','list');
    input.setAttribute('aria-expanded','false');
    const chosen=element('span','prompt-chosen'),faces=element('span','prompt-faces');
    const count=element('span','prompt-target'),remove=element('button','prompt-remove-recipient');
    remove.type='button';remove.textContent='×';remove.title='Clear recipients';remove.setAttribute('aria-label',remove.title);
    chosen.append(faces,count,remove);meta.after(chosen);chosen.hidden=true;
    const media=root.matchMedia('(prefers-reduced-motion: reduce)');
    const allowed=()=>!media.matches&&!document.hidden;
    const state=(value,stiffness,damping)=>({value,target:value,velocity:0,stiffness,damping});
    const height=state(0,260,24),opacity=state(0,420,32),x=state(0,900,50),y=state(0,900,50);
    const lead=state(0,620,36),trail=state(0,190,19),chip=state(1,520,16);
    const rows=new Map();
    let entries=[],names=[],current=null,index=-1,frame=0,last=0,serial=0,removing=false;
    const clamp=value=>Math.max(0,Math.min(1,value));
    const more=part=>Math.abs(part.value-part.target)>.04||Math.abs(part.velocity)>.08;
    const step=(part,elapsed)=>{
      if(!allowed()||!more(part)){part.value=part.target;part.velocity=0;return;}
      const integrate=root.OrreryConversationMotion?.stepSpring||root.OrreryPromptSpring.step;
      integrate(part,part.target,part.stiffness,part.damping,elapsed);
    };
    function paint(){
      picker.hidden=!current&&height.value<=.04;
      picker.style.height=Math.max(0,height.value)+'px';
      picker.style.opacity=clamp(opacity.value);
      picker.style.transform=`translate(${x.value}px,${y.value}px)`;
      band.hidden=index<0;
      const top=Math.min(lead.value,trail.value);
      band.style.transform=`translateY(${top}px)`;
      band.style.height=(rowHeight+Math.abs(lead.value-trail.value))+'px';
      for(const [name,row] of rows){
        if(!row.opacity.target&&row.opacity.value<.02){row.node.remove();rows.delete(name);continue;}
        row.node.style.opacity=clamp(row.opacity.value);
        row.node.style.transform=`translateY(${row.top.value}px)`;
      }
      chosen.style.transform=`scale(${Math.max(0,chip.value)})`;
      if(removing&&chip.value<=.04){chosen.hidden=true;removing=false;}
    }
    function tick(now){
      frame=0;
      const elapsed=last?(now-last)/1000:1/60;last=now;
      const states=[height,opacity,x,y,lead,trail,chip,...[...rows.values()].flatMap(row=>[row.top,row.opacity])];
      states.forEach(part=>step(part,elapsed));
      paint();
      if(allowed()&&states.some(more))frame=requestAnimationFrame(tick);
    }
    function draw(){
      if(!allowed()){cancelAnimationFrame(frame);last=0;tick(0);}
      else if(!frame){last=0;frame=requestAnimationFrame(tick);}
    }
    function place(fresh=false){
      if(!current)return;
      const box=input.getBoundingClientRect(),style=getComputedStyle(input);
      const mirror=element('div','prompt-caret-measure');
      Object.assign(mirror.style,{left:box.x+'px',top:box.y+'px',width:input.clientWidth+'px',font:style.font,padding:style.padding});
      const mark=document.createElement('span');mark.textContent='@';
      mirror.append(input.value.slice(0,current.start),mark);document.body.append(mirror);
      const at=mark.getBoundingClientRect();mirror.remove();
      const view=root.visualViewport;
      const left=view?.offsetLeft||0,top=view?.offsetTop||0;
      const width=Math.min(320,(view?.width||innerWidth)-16);
      const bottom=top+(view?.height||innerHeight);
      const below=at.bottom-input.scrollTop+6;
      picker.style.width=width+'px';
      x.target=Math.max(left+8,Math.min(at.x-input.scrollLeft,left+(view?.width||innerWidth)-width-8));
      y.target=below+height.target<=bottom-8?below:Math.max(top+8,at.top-input.scrollTop-height.target-6);
      if(fresh){x.value=x.target;y.value=y.target;}
    }
    function makeRow(agent){
      const node=element('div','prompt-mention-row'),face=portrait(agent.name);
      const name=element('span','prompt-mention-name'),role=element('span','prompt-mention-role');
      const logo=element('img','prompt-mention-logo');
      logo.alt='';
      node.id='promptMention-'+(++serial);node.setAttribute('role','option');
      node.append(face,name,role,logo);
      node.addEventListener('pointerdown',event=>event.preventDefault());
      node.addEventListener('click',()=>choose(entries.findIndex(item=>item.name===agent.name)));
      picker.append(node);
      return {node,name,role,logo,top:state(0,260,24),opacity:state(0,420,32)};
    }
    function select(next){
      const prev=lead.target;
      index=next;
      const position=next<0?0:padding+next*rowHeight;
      lead.target=trail.target=position;
      if(position<prev){lead.stiffness=190;lead.damping=19;trail.stiffness=620;trail.damping=36;}
      else{lead.stiffness=620;lead.damping=36;trail.stiffness=190;trail.damping=19;}
      entries.forEach((entry,i)=>rows.get(entry.name).node.setAttribute('aria-selected',String(i===index)));
      const active=entries[index];
      if(active)input.setAttribute('aria-activedescendant',rows.get(active.name).node.id);
      else input.removeAttribute('aria-activedescendant');
      draw();
    }
    function close(){
      if(!current)return;
      current=null;entries=[];height.target=opacity.target=0;
      for(const row of rows.values()){row.opacity.target=0;row.node.setAttribute('aria-hidden','true');row.node.setAttribute('aria-selected','false');}
      picker.inert=true;input.setAttribute('aria-expanded','false');select(-1);
    }
    function update(){
      const query=document.activeElement===input&&queryAt(input.value,input.selectionStart,input.selectionEnd);
      if(!query){close();return false;}
      const options=getAgents().filter(agent=>agent.name&&matches(agent.name,getRole(agent),query.word))
        .sort((a,b)=>Number(Boolean(getRefusal(a)))-Number(Boolean(getRefusal(b))))
        .slice(0,limit);
      if(!options.length){close();return false;}
      const fresh=!current,prior=entries[index]?.name;
      current=query;entries=options;
      const visible=new Set(entries.map(agent=>agent.name));
      for(const [name,row] of rows){
        if(visible.has(name))continue;
        row.opacity.target=0;row.top.target=Math.max(0,row.top.target-rowHeight/2);row.node.setAttribute('aria-hidden','true');row.node.setAttribute('aria-selected','false');
      }
      entries.forEach((agent,i)=>{
        let row=rows.get(agent.name);
        if(!row){row=makeRow(agent);rows.set(agent.name,row);row.top.value=padding+rowHeight*i;}
        const reason=getRefusal(agent),provider=getProvider(agent);
        row.name.textContent=agent.name;row.role.textContent=getRole(agent);
        row.logo.hidden=!provider;
        if(provider&&row.logo.getAttribute('src')!==provider.src)row.logo.src=provider.src;
        row.logo.title=provider?.label||'';
        row.node.title=reason||[agent.name,getRole(agent)].filter(Boolean).join(' · ');
        row.node.setAttribute('aria-disabled',String(Boolean(reason)));
        row.node.removeAttribute('aria-hidden');
        row.top.target=padding+rowHeight*i;row.opacity.target=1;
      });
      height.target=entries.length*rowHeight+padding*2;opacity.target=1;
      picker.hidden=false;picker.inert=false;input.setAttribute('aria-expanded','true');place(fresh);
      const selected=entries.findIndex(entry=>entry.name===prior&&!getRefusal(entry));
      select(selected<0?entries.findIndex(entry=>!getRefusal(entry)):selected);
      return true;
    }
    function set(next){
      const unique=[...new Set(next)];
      if(unique.length===names.length&&unique.every((name,i)=>name===names[i]))return;
      names=unique;
      const label=names.length>1?`${names.length} agents`:names[0]||'';
      if(names.length){
        faces.replaceChildren(...names.slice(0,3).map(portrait));
        count.textContent=label;chosen.title=names.join(', ');
        chosen.hidden=false;removing=false;
        chip.value=.6;chip.velocity=0;chip.target=1;
      }else{removing=true;chip.target=0;}
      meta.hidden=names.length>0;
      onChange();draw();
    }
    function choose(i){
      const agent=entries[i];
      if(!current||!agent||getRefusal(agent))return false;
      input.setRangeText('',current.start,current.end,'end');
      set([...names,agent.name]);close();onText();return true;
    }
    function handleKey(event){
      if(current){
        if(event.key==='Escape'){event.preventDefault();close();return true;}
        if(event.key==='ArrowUp'||event.key==='ArrowDown'){
          event.preventDefault();
          const eligible=entries.map((agent,i)=>getRefusal(agent)?-1:i).filter(i=>i>=0);
          if(eligible.length){
            const direction=event.key==='ArrowDown'?1:-1;
            select(eligible[(eligible.indexOf(index)+direction+eligible.length)%eligible.length]);
          }
          return true;
        }
        if((event.key==='Enter'&&!event.shiftKey)||event.key==='Tab'){
          if(event.key==='Tab'&&index<0){close();return false;}
          event.preventDefault();choose(index);return true;
        }
      }
      if(event.key==='Backspace'&&names.length&&input.selectionStart===0&&input.selectionEnd===0){
        event.preventDefault();set(names.slice(0,-1));return true;
      }
      return false;
    }
    remove.addEventListener('click',()=>{set([]);input.focus({preventScroll:true});});
    input.addEventListener('blur',close);
    input.addEventListener('click',update);
    input.addEventListener('scroll',()=>{if(current){place();draw();}});
    root.addEventListener('resize',()=>{if(current){place();draw();}});
    const reposition=()=>{if(current){place();draw();}};
    root.visualViewport?.addEventListener('resize',reposition);
    root.visualViewport?.addEventListener('scroll',reposition);
    new ResizeObserver(reposition).observe(input.closest('.promptbar'),{box:'border-box'});
    media.addEventListener('change',draw);
    document.addEventListener('visibilitychange',draw);
    document.addEventListener('pointerdown',event=>{if(event.target!==input&&!picker.contains(event.target))close();});
    picker.hidden=true;picker.inert=true;
    return {update,close,handleKey,set,get names(){return names.slice();}};
  }
  root.OrreryPromptRecipients=Object.freeze({mount,queryAt,matches});
})(window);
