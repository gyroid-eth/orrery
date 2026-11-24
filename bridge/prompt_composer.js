/* The card owns its presentation. Delivery, drafts and terminal focus remain
   with the cockpit because they bind to a particular live pane. */
(function(root){
  'use strict';
  function mount({input,button,getDestination,submit,interrupt,onHeightSettled}){
    const host=input.closest('.promptbar'),screen=host.closest('.screen');
    const card=input.closest('.prompt-card');
    const arrow=button.querySelector('.prompt-arrow');
    const square=button.querySelector('.prompt-square');
    const reduced=root.matchMedia('(prefers-reduced-motion: reduce)');
    const field={value:32,target:32,velocity:0,stiffness:420,damping:34};
    const glyph={value:0,target:0,velocity:0,stiffness:520,damping:30};
    const springs=[field,glyph];
    let frame=0,last=0,stopping=false,width=0,resizing=false;
    const moving=()=>!document.hidden&&!reduced.matches;
    const unsettled=state=>Math.abs(state.value-state.target)>.04||Math.abs(state.velocity)>.06;
    function paint(){
      input.style.height=Math.min(88,Math.max(32,field.value))+'px';
      input.style.overflowY=field.target===88?'auto':'hidden';
      const progress=Math.max(0,Math.min(1.15,glyph.value));
      arrow.style.transform=`rotate(${progress*90}deg) scale(${Math.max(0,1-progress)})`;
      square.style.transform=`scale(${progress})`;
    }
    function trackHeight(){
      const active=moving()&&unsettled(field);
      if(active===resizing)return;
      resizing=active;
      screen.toggleAttribute('data-prompt-resizing',active);
      if(!active)onHeightSettled();
    }
    function snap(){
      for(const state of springs){state.value=state.target;state.velocity=0;}
      paint();trackHeight();
    }
    function tick(now){
      const elapsed=last?(now-last)/1000:1/60;
      last=now;
      const step=root.OrreryConversationMotion?.stepSpring||root.OrreryPromptSpring.step;
      for(const state of springs)step(state,state.target,state.stiffness,state.damping,elapsed);
      if(springs.some(unsettled)){paint();trackHeight();frame=requestAnimationFrame(tick);}
      else{frame=0;snap();}
    }
    function animate(){
      if(!moving()){
        cancelAnimationFrame(frame);frame=0;snap();
      }else{
        trackHeight();
        if(!frame&&springs.some(unsettled)){last=0;frame=requestAnimationFrame(tick);}
      }
    }
    function refresh(){
      const {label,working,hasFiles=false,explicit=false,pending=false,count=0}=getDestination();
      const drafted=Boolean(input.value.trim())||hasFiles;
      stopping=Boolean(working&&!drafted&&!explicit&&!pending);
      const placeholder=label?`Message ${label}`:'Write a message';
      if(input.placeholder!==placeholder)input.placeholder=placeholder;
      const title=stopping?'Stop agent (Esc)':count>1?`Send to ${count} agents`:'Send message';
      if(button.title!==title){button.title=title;button.setAttribute('aria-label',title);}
      button.disabled=pending||!stopping&&!drafted;
      button.toggleAttribute('data-ready',!button.disabled);
      glyph.target=stopping?1:0;
      const scroll=input.scrollTop;
      input.style.height='0px';
      field.target=Math.min(88,Math.max(32,input.scrollHeight));
      paint();
      input.scrollTop=scroll;
      animate();
    }
    button.addEventListener('click',()=>stopping?interrupt():submit());
    reduced.addEventListener('change',animate);
    document.addEventListener('visibilitychange',animate);
    new ResizeObserver(()=>{
      const height=Math.ceil(host.getBoundingClientRect().height);
      if(height)screen.style.setProperty('--prompt-height',height+'px');
      const next=card.clientWidth;
      if(next!==width){width=next;refresh();}
    }).observe(host,{box:"border-box"});
    refresh();snap();
    return {refresh};
  }
  root.OrreryPromptComposer=Object.freeze({mount});
})(window);
