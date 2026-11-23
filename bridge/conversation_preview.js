/* Inert record renderer and preview outlet. Recorded references retain their
   grants; an explicit body-path click uses the local preview route. */
(function(root){
  'use strict';
  const MAX_TEXT=131072;
  function mount({host,source,onActivate=()=>{},onBeforeOpen=()=>{},onClose=()=>{},onReference=null}){
    // sourceView: this reader's last Markdown/Source choice for .md previews.
    let request=null,generation=0,objectUrl=null,selected=null,sourceView=false;
    const create=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el;};
    const button=(cls,text,action)=>{const el=create('button','cockpit-control conversation-action '+cls,text);el.type='button';el.addEventListener('click',action);return el;};
    // Heading buttons are icons only; the name lives in aria-label and title.
    const ICONS={
      reply:'<path d="M6.5 3.5 2.5 7.5l4 4"/><path d="M2.5 7.5h6a5 5 0 0 1 5 5v0"/>',
      source:'<path d="m5.5 4.5-3.5 3.5 3.5 3.5"/><path d="m10.5 4.5 3.5 3.5-3.5 3.5"/>',
      fullscreen:'<path d="M2.5 6V2.5H6"/><path d="M10 2.5h3.5V6"/><path d="M13.5 10v3.5H10"/><path d="M6 13.5H2.5V10"/>',
      reveal:'<path d="M1.8 4.2c0-.7.5-1.2 1.2-1.2h3l1.4 1.6H13c.7 0 1.2.5 1.2 1.2v6.2c0 .7-.5 1.2-1.2 1.2H3c-.7 0-1.2-.5-1.2-1.2z"/>',
      close:'<path d="m3.5 3.5 9 9"/><path d="m12.5 3.5-9 9"/>',
      fit:'<path d="M6 2.5V6H2.5"/><path d="M10 2.5V6h3.5"/><path d="M13.5 10H10v3.5"/><path d="M2.5 10H6v3.5"/>',
      actual:'<path d="m2.5 6.8 1.7-1.3v5.5"/><path d="M8 7.2v.01"/><path d="M8 10.2v.01"/><path d="m11.3 6.8 1.7-1.3v5.5"/>',
    };
    const svgIcon=icon=>{
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
      svg.setAttribute('viewBox','0 0 16 16');svg.setAttribute('width','16');svg.setAttribute('height','16');svg.setAttribute('fill','none');
      svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.5');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');
      svg.setAttribute('aria-hidden','true');svg.innerHTML=ICONS[icon];return svg;
    };
    const iconButton=(cls,icon,name,action)=>{
      const el=button('conversation-preview-icon '+cls,'',action);
      el.appendChild(svgIcon(icon));el.setAttribute('aria-label',name);el.title=name;return el;
    };
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
            remember(ref);
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
    // ---- Lightbox: the open image on a dark layer over the whole window. It
    // draws the bytes the preview already holds; Left/Right ask open() for the
    // neighbouring image so every fetch keeps the preview's route and limits.
    const known=new Map();            // id -> image reference seen in this conversation
    let current=null,lightbox=null;   // current: {ref,url,width,height} of the open preview image
    const SVG_NS='http://www.w3.org/2000/svg';
    function remember(ref){if(ref&&ref.kind==='image'&&typeof ref.id==='string')known.set(ref.id,ref);}
    function imageRefs(){
      const list=[],seen=new Set();
      for(const node of host.closest('.conversation-panel').querySelectorAll('[data-ref-id]')){
        const ref=known.get(node.dataset.refId);
        if(ref&&!seen.has(ref.id)){seen.add(ref.id);list.push(ref);}
      }
      if(selected&&!seen.has(selected.id)&&!list.includes(selected))list.push(selected);
      return list;
    }
    function lbButton(text,title,action){
      const el=create('button','conversation-lightbox-btn',text);el.type='button';el.title=title;el.addEventListener('click',action);return el;
    }
    // Bar buttons are icons only, built like the heading's (#140); the name is aria-label and title.
    function lbIcon(icon,name,action){
      const el=lbButton('',name,action);el.classList.add('conversation-lightbox-icon');el.appendChild(svgIcon(icon));el.setAttribute('aria-label',name);return el;
    }
    function openLightbox(returnTo){
      if(lightbox||!current)return;
      const lb={returnTo,w:current.width||1,h:current.height||1,s:1,x:0,y:0,drag:null,inerted:[],ready:false};
      const rootEl=create('div','conversation-lightbox');
      rootEl.setAttribute('role','dialog');rootEl.setAttribute('aria-modal','true');rootEl.setAttribute('aria-label','Image viewer');rootEl.tabIndex=-1;
      const bar=create('div','conversation-lightbox-bar');
      lb.name=create('span','conversation-lightbox-name');lb.count=create('span','conversation-lightbox-meta conversation-lightbox-count');lb.zoom=create('span','conversation-lightbox-meta conversation-lightbox-zoom');
      lb.fitBtn=lbIcon('fit','Fit to window (0)',()=>setFit(true));lb.oneBtn=lbIcon('actual','Actual size (1)',()=>setActual(null,true));
      lb.closeBtn=lbIcon('close','Close (Esc)',()=>closeLightbox(true));
      bar.append(lb.name,lb.count,lb.zoom,lb.fitBtn,lb.oneBtn,lb.closeBtn);
      lb.stage=create('div','conversation-lightbox-stage');
      lb.img=create('img','conversation-lightbox-image');lb.img.alt='';lb.img.draggable=false;
      lb.status=create('div','conversation-lightbox-status');lb.status.hidden=true;lb.status.setAttribute('role','status');
      lb.stage.append(lb.img,lb.status);
      lb.prev=lbButton('‹','Previous image (←)',()=>nav(-1));lb.next=lbButton('›','Next image (→)',()=>nav(1));
      lb.prev.classList.add('conversation-lightbox-nav','prev');lb.next.classList.add('conversation-lightbox-nav','next');
      lb.stage.title='Wheel zoom · drag pan · click fit ↔ 100% · ← → images · + − 0 1 · Esc close';
      rootEl.append(bar,lb.stage,lb.prev,lb.next);lb.root=rootEl;
      // The layer is modal: everything else is inert and keys never reach the page behind it.
      for(const node of [...document.body.children])if(!node.inert){node.inert=true;lb.inerted.push(node);}
      document.body.appendChild(rootEl);lightbox=lb;
      lb.onKey=event=>{
        if(lightbox!==lb)return;
        event.stopPropagation();
        if(event.type!=='keydown'||event.ctrlKey||event.metaKey||event.altKey)return;
        const half=()=>{const r=lb.stage.getBoundingClientRect();return [r.width/2,r.height/2];};
        let handled=true;
        switch(event.key){
          case 'Escape':closeLightbox(true);break;
          case 'ArrowLeft':nav(-1);break;
          case 'ArrowRight':nav(1);break;
          case '+':case '=':zoomAt(1.25,...half(),true);break;
          case '-':case '_':zoomAt(1/1.25,...half(),true);break;
          case '0':setFit(true);break;
          case '1':setActual(null,true);break;
          case 'Tab':{
            const items=[lb.fitBtn,lb.oneBtn,lb.closeBtn,lb.prev,lb.next].filter(el=>!el.disabled);
            const at=items.indexOf(document.activeElement),next=event.shiftKey?(at<=0?items.length-1:at-1):(at+1)%items.length;
            items[next]?.focus();break;
          }
          default:handled=false;
        }
        if(handled)event.preventDefault();
      };
      for(const type of ['keydown','keyup','keypress'])window.addEventListener(type,lb.onKey,true);
      lb.stage.addEventListener('wheel',event=>{
        event.preventDefault();
        const unit=event.deltaMode===1?16:event.deltaMode===2?400:1,delta=Math.max(-240,Math.min(240,event.deltaY*unit));
        const rect=lb.stage.getBoundingClientRect();
        zoomAt(Math.exp(-delta*(event.ctrlKey?0.01:0.0015)),event.clientX-rect.left,event.clientY-rect.top,false);
      },{passive:false});
      lb.stage.addEventListener('pointerdown',event=>{
        if(event.button!==0||!lb.ready)return;
        lb.drag={id:event.pointerId,sx:event.clientX,sy:event.clientY,x:lb.x,y:lb.y,moved:false};
        try{lb.stage.setPointerCapture(event.pointerId);}catch(_){}
      });
      lb.stage.addEventListener('pointermove',event=>{
        const d=lb.drag;if(!d||d.id!==event.pointerId)return;
        const dx=event.clientX-d.sx,dy=event.clientY-d.sy;
        if(!d.moved&&Math.hypot(dx,dy)>4){d.moved=true;lb.stage.classList.add('dragging');}
        if(d.moved){lb.x=d.x+dx;lb.y=d.y+dy;paint(false);}
      });
      const endDrag=event=>{
        const d=lb.drag;if(!d||d.id!==event.pointerId)return;
        lb.drag=null;lb.stage.classList.remove('dragging');
        try{lb.stage.releasePointerCapture(event.pointerId);}catch(_){}
        if(d.moved||event.type==='pointercancel')return;
        // A click (no drag): fit <-> actual size, but only on the image itself.
        const rect=lb.stage.getBoundingClientRect(),px=event.clientX-rect.left,py=event.clientY-rect.top;
        if(px<lb.x||py<lb.y||px>lb.x+lb.w*lb.s||py>lb.y+lb.h*lb.s)return;
        if(isFit())setActual([px,py],true);else setFit(true);
      };
      lb.stage.addEventListener('pointerup',endDrag);lb.stage.addEventListener('pointercancel',endDrag);
      lb.ro=new ResizeObserver(()=>{if(!lb.ready)return;if(lb.fitMode)setFit(false);else paint(false);});lb.ro.observe(lb.stage);
      setImage(current);rootEl.focus({preventScroll:true});
    }
    function fitScale(){const r=lightbox.stage.getBoundingClientRect();return Math.min(1,r.width/lightbox.w,r.height/lightbox.h)||1;}
    function isFit(){return Math.abs(lightbox.s-fitScale())<1e-3;}
    function paint(animate){
      const lb=lightbox;if(!lb)return;
      const r=lb.stage.getBoundingClientRect(),iw=lb.w*lb.s,ih=lb.h*lb.s;
      lb.x=iw<=r.width?(r.width-iw)/2:Math.min(0,Math.max(r.width-iw,lb.x));
      lb.y=ih<=r.height?(r.height-ih)/2:Math.min(0,Math.max(r.height-ih,lb.y));
      lb.img.classList.toggle('animate',!!animate);
      lb.img.style.transform='translate('+lb.x+'px,'+lb.y+'px) scale('+lb.s+')';
      lb.img.classList.toggle('pixelated',lb.s>=2);
      lb.fitMode=Math.abs(lb.s-fitScale())<1e-3;
      lb.zoom.textContent=Math.round(lb.s*100)+'%';
      lb.fitBtn.setAttribute('aria-pressed',String(lb.fitMode));lb.oneBtn.setAttribute('aria-pressed',String(Math.abs(lb.s-1)<1e-3));
    }
    function zoomAt(factor,cx,cy,animate){
      const lb=lightbox;if(!lb||!lb.ready)return;
      const fit=fitScale(),next=Math.max(fit*0.8,Math.min(Math.max(8,fit),lb.s*factor)),k=next/lb.s;
      lb.x=cx-(cx-lb.x)*k;lb.y=cy-(cy-lb.y)*k;lb.s=next;paint(animate);
    }
    function setFit(animate){const lb=lightbox;if(!lb||!lb.ready)return;lb.s=fitScale();lb.x=lb.y=0;paint(animate);}
    function setActual(point,animate){
      const lb=lightbox;if(!lb||!lb.ready)return;
      const r=lb.stage.getBoundingClientRect();
      // Put the clicked image point at the centre of the window (centre of the image when no point).
      const ix=point?(point[0]-lb.x)/lb.s:lb.w/2,iy=point?(point[1]-lb.y)/lb.s:lb.h/2;
      lb.s=1;lb.x=r.width/2-ix;lb.y=r.height/2-iy;paint(animate);
    }
    function lbState(){
      const lb=lightbox;if(!lb)return;
      const list=imageRefs(),index=Math.max(0,list.findIndex(ref=>ref===selected||(ref.id&&ref.id===selected?.id)));
      lb.count.textContent=list.length>1?(index+1)+' / '+list.length:'';lb.count.hidden=list.length<2;
      lb.prev.disabled=index<=0;lb.next.disabled=index>=list.length-1;
      lb.name.textContent=selected?.label||'';
    }
    function setImage(info){
      const lb=lightbox;if(!lb)return;
      lb.w=info.width||info.image?.naturalWidth||1;lb.h=info.height||info.image?.naturalHeight||1;
      lb.status.hidden=true;lb.img.style.width=lb.w+'px';lb.img.style.height=lb.h+'px';
      lb.img.src=info.url;lb.img.hidden=false;lb.ready=true;lbState();setFit(false);
    }
    function lbMessage(text){
      const lb=lightbox;if(!lb)return;
      lb.ready=false;lb.img.hidden=true;lb.img.removeAttribute('src');lb.status.textContent=text;lb.status.hidden=false;lb.zoom.textContent='';lbState();
    }
    function nav(delta){
      const lb=lightbox;if(!lb)return;
      const list=imageRefs(),index=list.findIndex(ref=>ref===selected||(ref.id&&ref.id===selected?.id)),ref=list[index+delta];
      if(!ref)return;
      lbMessage('Loading…');open(ref);
    }
    function closeLightbox(restoreFocus){
      const lb=lightbox;if(!lb)return;
      lightbox=null;lb.ro.disconnect();
      for(const type of ['keydown','keyup','keypress'])window.removeEventListener(type,lb.onKey,true);
      lb.root.remove();for(const node of lb.inerted)node.inert=false;
      if(restoreFocus){
        const target=host.querySelector(lb.returnTo==='image'?'.conversation-preview-image':'.conversation-preview-fullscreen')||host.querySelector('.conversation-preview-close');
        target?.focus();
      }
    }
    function close(){closeLightbox(false);current=null;cancel();selected=null;markSelected();host.hidden=true;host.replaceChildren();host.parentElement.classList.remove('conversation-has-preview');onClose();}
    async function open(ref){
      onBeforeOpen();cancel();current=null;selected=ref;markSelected();const token=generation;
      host.hidden=false;host.parentElement.classList.add('conversation-has-preview');onActivate(ref);
      const head=create('div','conversation-preview-head'),title=create('h3','conversation-preview-title',ref.label);
      const closeButton=iconButton('conversation-preview-close','close','Close preview',()=>{close();host.closest('.conversation-panel').querySelector('.conversation-scroll')?.focus();});
      head.append(title,closeButton);
      if(onReference&&(ref.path?ref.origin:ref.id))head.insertBefore(iconButton('conversation-preview-reply','reply','Reply with reference',()=>onReference(ref)),closeButton);
      const notice=create('div','conversation-preview-notice',ref.path?'':ref.input_image?'Recorded input image':'Current file · may differ from the recorded edit');
      const body=create('div','conversation-preview-content','Loading preview…');body.tabIndex=0;
      host.replaceChildren(head,notice,body);closeButton.focus();
      function addReveal(){
        const reveal=iconButton('conversation-reveal','reveal','Reveal in file manager',async()=>{
          reveal.disabled=true;
          try{if(ref.path)await source.revealPath(ref.path);else await source.reference(ref.id,{reveal:true});if(token===generation)notice.textContent='Selected in file manager';}
          catch(error){if(token===generation)notice.textContent=error.message;}
          finally{reveal.disabled=false;}
        });
        head.insertBefore(reveal,closeButton);
      }
      if(ref.path)addReveal();
      request=new AbortController();
      try{
        const data=await (ref.path?source.pathPreview(ref.path,{signal:request.signal}):source.reference(ref.id,{signal:request.signal}));
        if(token!==generation)return;
        body.replaceChildren();
        if(data.kind==='text'&&typeof data.text==='string'&&data.text.length<=MAX_TEXT*2&&
           (data.text.length<=MAX_TEXT||[...data.text].length<=MAX_TEXT)){
          const raw=create('pre','conversation-preview-text',data.text),markdown=root.OrreryConversationMarkdown;
          if(markdown){raw.textContent='';markdown.renderText(data.text,raw);}
          if(/\.(?:md|markdown)$/i.test(ref.label)&&typeof markdown?.renderDocument==='function'){
            // Drawn as a document by default; Source shows the file's own text.
            // Both views are inert (text nodes only); see conversation_markdown.js.
            let doc=null;
            const toggle=iconButton('conversation-preview-source','source','Source',()=>{sourceView=!sourceView;show();});
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
          current={ref,url:objectUrl,width:data.width,height:data.height};
          // Same two doors as the Full screen button: the picture itself (also from the keyboard).
          image.tabIndex=0;image.setAttribute('role','button');image.setAttribute('aria-label','Full screen');image.title='Full screen';
          image.addEventListener('click',()=>openLightbox('image'));
          image.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openLightbox('image');}});
          head.insertBefore(iconButton('conversation-preview-fullscreen','fullscreen','Full screen',()=>openLightbox('button')),closeButton);
          if(lightbox)setImage(current);
        }else throw new Error('Unsupported preview response.');
        if(!ref.path&&!ref.input_image)addReveal();
      }catch(error){
        if(token!==generation||error.name==='AbortError')return;
        if(ref.path){
          notice.textContent=error.message;
          body.replaceChildren(create('div','conversation-preview-text',ref.path));
        }else body.textContent=error.message;
        if(lightbox)lbMessage(error.message);
      }
      finally{if(token===generation)request=null;}
    }
    function render(event,article){
      if(Array.isArray(event.references)){
        const chips=create('div','conversation-files');
        for(const ref of event.references.slice(0,24)){
          if(!ref||!/^[A-Za-z0-9_-]{32}$/.test(ref.id)||typeof ref.label!=='string')continue;
          remember(ref);
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
