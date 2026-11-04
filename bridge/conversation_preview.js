/* Inert record renderer and replaceable preview outlet. No paths or external
   URLs are accepted here. Only server reference IDs cross the data boundary. */
(function(root){
  'use strict';
  function mount({host,source,onActivate=()=>{}}){
    let request=null,generation=0,objectUrl=null,selected=null;
    const create=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el;};
    const button=(cls,text,action)=>{const el=create('button','cockpit-control conversation-action '+cls,text);el.type='button';el.addEventListener('click',action);return el;};
    function cancel(){generation++;if(request)request.abort();request=null;if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=null;}
    function markSelected(){host.closest('.conversation-panel').querySelectorAll('.conversation-file').forEach(chip=>chip.setAttribute('aria-pressed',String(chip.dataset.refId===selected?.id)));}
    function close(){cancel();selected=null;markSelected();host.hidden=true;host.replaceChildren();host.parentElement.classList.remove('conversation-has-preview');}
    async function open(ref){
      cancel();selected=ref;markSelected();const token=generation;request=new AbortController();
      host.hidden=false;host.parentElement.classList.add('conversation-has-preview');onActivate(ref);
      const head=create('div','conversation-preview-head'),title=create('h3','conversation-preview-title',ref.label);
      const closeButton=button('conversation-preview-close','× Preview',()=>{close();document.querySelector('.conversation-scroll')?.focus();});
      head.append(title,closeButton);
      const notice=create('div','conversation-preview-notice','Current file · may differ from the recorded edit');
      const body=create('div','conversation-preview-content','Loading preview…');body.tabIndex=0;
      host.replaceChildren(head,notice,body);closeButton.focus();
      try{
        const data=await source.reference(ref.id,{signal:request.signal});
        if(token!==generation)return;
        body.replaceChildren();
        if(data.kind==='text'&&typeof data.text==='string'&&data.text.length<=131072){
          body.appendChild(create('pre','conversation-preview-text',data.text));
        }else if(data.kind==='image'&&data.mime==='image/png'&&typeof data.data==='string'&&data.data.length<12*1024*1024){
          const bytes=Uint8Array.from(atob(data.data),char=>char.charCodeAt(0));
          objectUrl=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
          const image=create('img','conversation-preview-image');image.alt=ref.label;image.src=objectUrl;image.draggable=false;
          body.appendChild(image);notice.textContent+=' · '+data.width+' × '+data.height;
        }else throw new Error('Unsupported preview response.');
        const reveal=button('conversation-reveal','Reveal in file manager',async()=>{
          reveal.disabled=true;
          try{await source.reference(ref.id,{reveal:true});if(token===generation)notice.textContent='Selected in file manager';}
          catch(error){if(token===generation)notice.textContent=error.message;}
          finally{reveal.disabled=false;}
        });
        head.insertBefore(reveal,closeButton);
      }catch(error){if(token===generation&&error.name!=='AbortError')body.textContent=error.message;}
      finally{if(token===generation)request=null;}
    }
    function render(event,article){
      if(Array.isArray(event.references)){
        const chips=create('div','conversation-files');
        for(const ref of event.references.slice(0,24)){
          if(!ref||!/^[A-Za-z0-9_-]{32}$/.test(ref.id)||typeof ref.label!=='string')continue;
          const chip=button('conversation-file',(ref.kind==='image'?'▧ ':'▤ ')+ref.label,()=>open(ref));
          chip.title='Preview current '+(ref.kind==='image'?'image':'file');chip.dataset.refId=ref.id;chips.appendChild(chip);
          chip.setAttribute('aria-pressed',String(selected?.id===ref.id));
        }
        article.appendChild(chips);
      }
      if(typeof event.diff==='string'&&event.diff){
        const details=create('details','conversation-diff');
        details.appendChild(create('summary','conversation-diff-summary',event.diff_status||'Recorded edit request · outcome unconfirmed'));
        const code=create('pre','conversation-diff-code');code.tabIndex=0;
        for(const line of event.diff.slice(0,49152).split('\n')){
          const kind=line.startsWith('+++')||line.startsWith('---')?'file':line.startsWith('+')?'add':line.startsWith('-')?'remove':line.startsWith('@@')?'hunk':'context';
          code.appendChild(create('span','conversation-diff-line conversation-diff-'+kind,line+'\n'));
        }
        details.appendChild(code);article.appendChild(details);
      }
      return article;
    }
    return Object.freeze({render,open,close,get selected(){return selected;}});
  }
  root.OrreryConversationPreview=Object.freeze({mount});
})(window);
