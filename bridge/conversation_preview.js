/* Inert record renderer and preview outlet. Recorded references retain their
   grants; an explicit body-path click has a separate image-only boundary. */
(function(root){
  'use strict';
  function mount({host,source,onActivate=()=>{},onBeforeOpen=()=>{},onClose=()=>{}}){
    // sourceView: this reader's last Markdown/Source choice for .md previews.
    let request=null,generation=0,objectUrl=null,selected=null,sourceView=false;
    const create=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el;};
    const button=(cls,text,action)=>{const el=create('button','cockpit-control conversation-action '+cls,text);el.type='button';el.addEventListener('click',action);return el;};
    const scroll=host.closest('.conversation-panel').querySelector('.conversation-scroll');
    const inlineRows=new Map(),near=new Set();let visible=false,loading=0,frame=0;
    const observer=new IntersectionObserver(changes=>{
      for(const change of changes){const entry=change.target.inlineEntry;if(entry.alive&&change.isIntersecting)near.add(entry);else near.delete(entry);}
      schedule();
    },{root:scroll,rootMargin:'200px'});
    function schedule(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;pump();});}
    function release(entry){
      entry.request?.abort();entry.request=null;
      if(entry.url)URL.revokeObjectURL(entry.url);entry.url=null;
      entry.image.removeAttribute('src');entry.image.hidden=true;entry.status.hidden=false;
    }
    function forget(row){for(const entry of row.entries){entry.alive=false;observer.unobserve(entry.button);near.delete(entry);release(entry);}row.node.remove();}
    function resetInline(){observer.disconnect();near.clear();for(const row of inlineRows.values())forget(row);inlineRows.clear();cancelAnimationFrame(frame);frame=0;}
    function setVisible(value){
      if(visible===value)return;visible=value;observer.disconnect();near.clear();
      for(const row of inlineRows.values())for(const entry of row.entries){
        if(value)observer.observe(entry.button);else{entry.request?.abort();entry.request=null;}
      }
      schedule();
    }
    async function loadInline(entry){
      const request=new AbortController();entry.request=request;loading++;
      try{
        const data=await source.reference(entry.ref.id,{signal:request.signal,thumbnail:true});
        if(entry.request!==request||!visible||!entry.button.isConnected)return;
        if(data.kind!=='image'||data.mime!=='image/png'||typeof data.data!=='string'||data.data.length>=12*1024*1024)throw new Error('Preview unavailable');
        const bytes=Uint8Array.from(atob(data.data),char=>char.charCodeAt(0));
        entry.url=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
        entry.image.src=entry.url;entry.image.hidden=false;entry.status.hidden=true;
      }catch(error){if(entry.request===request&&error.name!=='AbortError'){entry.failed=true;entry.status.textContent='Preview unavailable · click to retry';}}
      finally{loading--;if(entry.request===request)entry.request=null;schedule();}
    }
    function pump(){
      if(!visible)return;
      // 近い画像を優先する。同時取得と Blob の保持を各 Reader で制限する。
      const top=scroll.getBoundingClientRect().top;
      const wanted=new Set([...near].filter(entry=>entry.button.isConnected).sort((a,b)=>
        Math.abs(a.button.getBoundingClientRect().top-top)-Math.abs(b.button.getBoundingClientRect().top-top)).slice(0,8));
      for(const row of inlineRows.values())for(const entry of row.entries)if(!wanted.has(entry))release(entry);
      for(const entry of wanted)if(loading<2&&!entry.url&&!entry.request&&!entry.failed)loadInline(entry);
    }
    scroll.addEventListener('scroll',schedule,{passive:true});
    function syncInline(rows,events){
      const keep=new Set();
      for(const row of rows){
        const event=events.get(row.dataset.eventId);
        const input=event?.kind==='text'&&event.role==='user'&&event.input_images===true;
        if(!input&&(event?.kind!=='tool'||!/^mcp__orrery[-_]mail__show_files$/.test(event.text)))continue;
        const refs=(Array.isArray(event.references)?event.references:[]).slice(0,24).filter(ref=>
          ref?.kind==='image'&&/^[A-Za-z0-9_-]{32}$/.test(ref.id)&&typeof ref.label==='string');
        if(!refs.length)continue;
        const id=event.id,signature=JSON.stringify(refs);keep.add(id);
        let record=inlineRows.get(id);
        if(record?.signature!==signature){if(record)forget(record);record=null;}
        if(!record){
          const node=create('div','conversation-inline-images');node.dataset.inlineFor=id;
          record={node,signature,entries:[]};inlineRows.set(id,record);
          for(const ref of refs){
            const control=button('conversation-inline-image conversation-file','',()=>open(ref));
            control.dataset.refId=ref.id;control.setAttribute('aria-label','Preview '+ref.label);
            const image=create('img','conversation-inline-thumbnail');image.alt='';image.hidden=true;image.draggable=false;
            const status=create('span','conversation-inline-status','Preview image');
            control.append(image,status,create('span','conversation-inline-label',ref.label));
            const entry={ref,button:control,image,status,url:null,request:null,failed:false,alive:true};control.inlineEntry=entry;
            record.entries.push(entry);node.appendChild(control);if(visible)observer.observe(control);
          }
        }
        if(row.nextElementSibling!==record.node)row.after(record.node);
      }
      for(const [id,row] of inlineRows)if(!keep.has(id)){forget(row);inlineRows.delete(id);}
      markSelected();schedule();
    }
    function cancel(){generation++;if(request)request.abort();request=null;if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=null;}
    function markSelected(){host.closest('.conversation-panel').querySelectorAll('.conversation-file').forEach(chip=>chip.setAttribute('aria-pressed',String(chip.dataset.refId===selected?.id)));}
    function close(){cancel();selected=null;markSelected();host.hidden=true;host.replaceChildren();host.parentElement.classList.remove('conversation-has-preview');onClose();}
    async function open(ref){
      onBeforeOpen();cancel();selected=ref;markSelected();const token=generation;request=new AbortController();
      host.hidden=false;host.parentElement.classList.add('conversation-has-preview');onActivate(ref);
      const head=create('div','conversation-preview-head'),title=create('h3','conversation-preview-title',ref.label);
      const closeButton=button('conversation-preview-close','× Preview',()=>{close();host.closest('.conversation-panel').querySelector('.conversation-scroll')?.focus();});
      head.append(title,closeButton);
      const notice=create('div','conversation-preview-notice',ref.path?'':ref.input_image?'Recorded input image':'Current file · may differ from the recorded edit');
      const body=create('div','conversation-preview-content','Loading preview…');body.tabIndex=0;
      host.replaceChildren(head,notice,body);closeButton.focus();
      try{
        const data=await (ref.path?source.pathImage(ref.path,{signal:request.signal}):source.reference(ref.id,{signal:request.signal}));
        if(token!==generation)return;
        body.replaceChildren();
        if(data.kind==='text'&&typeof data.text==='string'&&data.text.length<=131072){
          const raw=create('pre','conversation-preview-text',data.text),markdown=root.OrreryConversationMarkdown;
          if(markdown){raw.textContent='';markdown.renderText(data.text,raw);}
          if(/\.(?:md|markdown)$/i.test(ref.label)&&typeof markdown?.renderDocument==='function'){
            // Drawn as a document by default; Source shows the file's own text.
            // Both views are inert (text nodes only); see conversation_markdown.js.
            let doc=null;
            const toggle=button('conversation-preview-source','Source',()=>{sourceView=!sourceView;show();});
            const show=()=>{
              if(!sourceView&&!doc){
                // A drawing failure shows the file's own text, never an error in its place.
                try{doc=markdown.renderDocument(data.text,create('div','conversation-preview-markdown'));}
                catch(_){doc=raw;toggle.disabled=true;toggle.title='Markdown view unavailable for this file';}
              }
              body.replaceChildren(sourceView?raw:doc);body.scrollTop=0;
              if(toggle.disabled)return;
              toggle.setAttribute('aria-pressed',String(sourceView));
              toggle.title=sourceView?'Show as Markdown':'Show the original text';
            };
            show();head.insertBefore(toggle,closeButton);
          }else body.appendChild(raw);
        }else if(data.kind==='image'&&data.mime==='image/png'&&typeof data.data==='string'&&data.data.length<12*1024*1024){
          const bytes=Uint8Array.from(atob(data.data),char=>char.charCodeAt(0));
          objectUrl=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
          const image=create('img','conversation-preview-image');image.alt=ref.label;image.src=objectUrl;image.draggable=false;
          body.appendChild(image);notice.textContent+=(ref.path?'':' · ')+data.width+' × '+data.height;
        }else throw new Error('Unsupported preview response.');
        const reveal=button('conversation-reveal','Reveal in file manager',async()=>{
          reveal.disabled=true;
          try{if(ref.path)await source.revealPath(ref.path);else await source.reference(ref.id,{reveal:true});if(token===generation)notice.textContent='Selected in file manager';}
          catch(error){if(token===generation)notice.textContent=error.message;}
          finally{reveal.disabled=false;}
        });
        if(!ref.input_image)head.insertBefore(reveal,closeButton);
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
          const text=create('span','conversation-diff-line conversation-diff-'+kind);
          if(root.OrreryConversationMarkdown)root.OrreryConversationMarkdown.renderText(line+'\n',text);else text.textContent=line+'\n';
          code.appendChild(text);
        }
        details.appendChild(code);article.appendChild(details);
      }
      return article;
    }
    return Object.freeze({render,open,close,syncInline,setVisible,resetInline,
      dispose(){resetInline();scroll.removeEventListener('scroll',schedule);close();},get selected(){return selected;}});
  }
  root.OrreryConversationPreview=Object.freeze({mount});
})(window);
