/* Optional effort stays separate from the slider's neutral display position. */
window.EffortSlider={
  mount(host,{levels,value,onChange}){
    host.replaceChildren();
    const choices=[...new Set((levels||[]).filter(v=>typeof v==='string'&&v))];
    const element=(tag,className,text)=>{const e=document.createElement(tag);e.className=className;if(text)e.textContent=text;return e;};
    if(!choices.length){host.append(element('span','effort-not-supported','Not supported'));return;}
    const title=v=>v==='xhigh'?'X-high':v[0].toUpperCase()+v.slice(1);
    let selected=choices.includes(value)?value:null;
    const control=element('div','effort-orbit'),output=element('output','effort-value');
    const input=element('input','effort-range');input.type='range';input.name='spawnEffort';
    input.min=0;input.max=choices.length-1;input.step=1;input.setAttribute('aria-label','Effort');
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 300 36');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');
    const shape=(tag,attrs)=>{const e=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));svg.append(e);return e;};
    const path='M14 24 Q150 10 286 24';
    shape('path',{d:path,class:'effort-track',fill:'none'});
    shape('path',{d:'M14 29 Q150 15 286 29',class:'effort-guide',fill:'none'});
    const progress=shape('path',{d:path,class:'effort-progress',fill:'none',pathLength:100});
    const position=i=>14+(choices.length>1?i/(choices.length-1):.5)*272;
    const y=x=>17+7*((x-150)/136)**2;
    choices.forEach((choice,i)=>shape('circle',{cx:position(i),cy:y(position(i)),r:1.8,class:'effort-stop'}));
    const halo=shape('circle',{r:8,class:'effort-halo'}),ring=shape('circle',{r:4.5,class:'effort-ring'}),dot=shape('circle',{r:1.7,class:'effort-dot'});
    const ends=element('div','effort-ends');ends.append(element('span','',title(choices[0])),element('span','',title(choices.at(-1))));
    const foot=element('div','effort-foot'),caption=element('span','effort-caption'),reset=element('button','effort-reset','Use default');reset.type='button';
    foot.append(caption,reset);control.append(output,svg,ends,input);host.append(control,foot);
    function paint(){
      const neutral=selected===null,index=neutral?(choices.length-1)/2:choices.indexOf(selected),x=position(index);
      control.classList.toggle('is-default',neutral);
      input.value=neutral?Math.floor(choices.length/2):index;
      input.setAttribute('aria-valuetext',neutral?'Default':title(selected));
      output.textContent=neutral?'Default':title(selected);
      output.style.left=`clamp(36px, ${x/3}%, calc(100% - 36px))`;
      [halo,ring,dot].forEach(e=>{e.setAttribute('cx',x);e.setAttribute('cy',y(x));});
      progress.setAttribute('stroke-dasharray',(neutral||choices.length===1?0:index/(choices.length-1)*100)+' 100');
      caption.textContent=neutral?'Uses your settings':'Custom setting';reset.hidden=neutral;
    }
    function choose(){selected=choices[Number(input.value)];paint();onChange(selected);}
    input.addEventListener('input',choose);
    // A click on the neutral stop also explicitly chooses that effort.
    input.addEventListener('pointerup',()=>{if(selected===null)choose();});
    reset.addEventListener('click',()=>{selected=null;paint();onChange(null);input.focus({preventScroll:true});});
    paint();
  },
};
