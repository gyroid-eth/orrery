/* Keep the catalog default separate from an explicit detent, even when they
   share a position. That distinction is required by some launch routes. */
window.EffortSlider={
  mount(host,{levels,value,fallback,onChange}){
    host.replaceChildren();
    const choices=[...new Set((levels||[]).filter(v=>typeof v==='string'&&v))];
    if(!choices.length)return;
    const element=(tag,className)=>{
      const node=document.createElement(tag);
      node.className=className;
      return node;
    };
    const position=index=>choices.length===1?50:index/(choices.length-1)*100;
    let selected=choices.includes(value)?value:null;
    const defaultIndex=choices.indexOf(fallback);
    const control=element('div','effort-control'),track=element('div','effort-orbit');
    const input=element('input','effort-range'),output=element('span','effort-value');
    input.type='range';input.name='spawnEffort';input.min=0;input.max=choices.length-1;input.step=1;
    input.setAttribute('aria-label','Effort');
    output.setAttribute('aria-hidden','true');
    const reset=element('button','spawn-icon-button effort-reset');reset.type='button';
    reset.title='Use default effort';reset.setAttribute('aria-label',reset.title);
    reset.innerHTML='<svg class="spawn-icon" aria-hidden="true"><use href="#spawn-icon-reset"/></svg>';
    const ticks=choices.map((_,index)=>{
      const tick=element('span','effort-stop');
      tick.style.setProperty('--effort-pos',position(index)+'%');
      return tick;
    });
    const thumb=element('span','effort-thumb');
    track.append(element('span','effort-track'),element('span','effort-progress'),...ticks,thumb,output,input);
    control.append(track,reset);host.append(control);
    function paint(){
      const index=selected===null?defaultIndex:choices.indexOf(selected);
      input.value=index<0?Math.floor(choices.length/2):index;
      input.setAttribute('aria-valuetext',selected===null?(fallback?'Default ('+fallback+')':'Default'):selected);
      output.textContent=input.getAttribute('aria-valuetext');
      track.style.setProperty('--effort-pos',(index<0?50:position(index))+'%');
      track.style.setProperty('--effort-fill',(index<0?0:position(index))+'%');
      ticks.forEach((tick,i)=>tick.classList.toggle('on',i<=index));
      reset.disabled=selected===null;
    }
    function choose(){
      const next=choices[Number(input.value)];
      if(selected===next)return;
      selected=next;paint();onChange(selected);
      if(!matchMedia('(prefers-reduced-motion: reduce)').matches){
        const spring=getComputedStyle(host).getPropertyValue('--spawn-spring').trim();
        thumb.getAnimations().forEach(animation=>animation.cancel());
        thumb.animate([{scale:'1.25'},{scale:'1'}],{duration:380,easing:spring||'ease-out'});
      }
    }
    input.addEventListener('input',choose);
    input.addEventListener('pointerup',()=>{if(selected===null)choose();});
    // With a single detent the native range has no value change to report.
    input.addEventListener('keydown',event=>{
      if(selected===null&&['Enter',' '].includes(event.key)&&!event.metaKey&&!event.ctrlKey){
        event.preventDefault();choose();
      }
    });
    reset.addEventListener('click',()=>{selected=null;paint();onChange(null);input.focus({preventScroll:true});});
    paint();
  },
};
