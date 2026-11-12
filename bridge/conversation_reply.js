/* A reference stays browser-local beside the original composer until Send. */
(function(root){
  'use strict';
  function mount({host,input,getTarget,onError=()=>{}}){
    let reference=null,target=null;
    const screen=host.closest('.screen');
    const card=document.createElement('section');card.className='conversation-reply-reference';card.hidden=true;
    card.setAttribute('aria-label','Reply reference');
    const label=document.createElement('div');label.className='conversation-reply-label';
    const quote=document.createElement('blockquote');quote.className='conversation-reply-quote';
    const remove=document.createElement('button');remove.type='button';remove.className='conversation-reply-remove';
    remove.textContent='×';remove.title='Remove reference';remove.setAttribute('aria-label',remove.title);
    card.append(label,quote,remove);host.prepend(card);
    for(const type of ['pointerdown','mousedown','keydown','keyup'])card.addEventListener(type,event=>event.stopPropagation());
    function size(){
      const space=reference?Math.ceil(card.getBoundingClientRect().height)+8:0;
      screen.style.setProperty('--conversation-reply-space',space+'px');
    }
    const observer=new ResizeObserver(size);observer.observe(card);
    function clear(){
      reference=target=null;card.hidden=true;label.textContent=quote.textContent='';
      host.classList.remove('has-conversation-reference');size();
    }
    remove.onclick=()=>{clear();input.focus({preventScroll:true});};
    function add(value){
      const selected=getTarget();
      if(!selected||selected.session!==value.agent||!value.isCurrent()){
        onError('Reference unavailable — select its agent and try again.');return false;
      }
      if(typeof value.text!=='string'||!value.text.trim()||value.text.length>8192){
        onError('Select up to 8,192 characters to reference.');return false;
      }
      reference=value;target=selected;
      const at=new Date(value.ts),time=Number.isFinite(at.getTime())?at.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';
      label.textContent=[value.agent,value.kind==='file'?'File reference':'Message reference',time].filter(Boolean).join(' · ');
      quote.textContent=value.text;quote.title=value.text;card.hidden=false;
      host.classList.add('has-conversation-reference');size();input.focus({preventScroll:true});
      return true;
    }
    function check(value,pinned,selected){
      if(!value)return true;
      const same=selected&&pinned.pane===selected.pane&&pinned.paneId===selected.paneId&&
        pinned.session===selected.session&&pinned.socket===selected.socket&&value.isCurrent();
      if(!same)onError('Reference belongs to '+value.agent+' — select its original conversation or remove the reference.');
      return Boolean(same);
    }
    function guard(){const value=reference,pinned=target;return selected=>check(value,pinned,selected);}
    function compose(text){
      if(!reference)return text;
      const title='Reference: '+reference.agent+' · '+reference.role+(reference.ts?' · '+reference.ts:'');
      const provenance='Recorded message: '+reference.eventId;
      const quoted=reference.text.replace(/\r\n?/g,'\n').split('\n').map(line=>'> '+line).join('\n');
      return title+'\n'+provenance+'\n'+quoted+'\n\n'+text;
    }
    return Object.freeze({add,guard,compose,clear,get hasReference(){return Boolean(reference);},
      dispose(){observer.disconnect();clear();card.remove();}});
  }
  root.OrreryConversationReply=Object.freeze({mount});
})(window);
