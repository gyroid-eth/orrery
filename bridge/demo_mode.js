/* Demo mode for recordings, live demos and screen sharing: the page shows the
   user name and the machine name masked (see demo_mask.js), while every click,
   copy, edit and send uses the real value.

   On:  ?demo=1 in the URL, or the Settings switch (kept in this browser).
        ?demo=0 turns it off for one page even when the switch is on.
  More words to hide (a person's name in Mail, say): the Settings field (kept
  in this browser), plus ?mask=word,word in the URL for one page. The words
  are hidden like the user name; see demo_mask.js for how a word matches.

   Fail closed. The page stays hidden until the backend has said which names
   to hide; if it cannot (no answer, an error, a timeout), the page stays
   hidden and says so, with Retry and a way to open it without demo mode. The
   terminal socket waits for the same moment (cockpit.html connects after
   OrreryDemo.ready), so no output is drawn before the mask exists.

   Masked here, keeping each original:
   - every text node and the tooltip-like attributes of this page and of
     same-origin frames (the telemetry dashboard). A frame is hidden from the
     moment it starts loading a new page until its document is masked;
   - text fields: the field keeps its real value (typing, sending and copying
     use it) and a masked copy is drawn over it while it holds a name.
   - terminals, where xterm draws them: the DOM renderer's rows are masked
     like other text, one wrapped line (all its rows) at a time, so a name
     split by a colour change or by the edge of the terminal is still found.
     The terminal's buffer stays real: the cursor, wrapping, selection, copy
     and links work on the real text, whatever the program did to build it.
     Masking runs in the MutationObserver callback, after xterm has changed
     the rows and before the browser paints them. */
(function(){
  'use strict';
  const STORAGE_KEY='orrery.demo-mode.v1';
  const WORDS_KEY='orrery.demo-mask-words.v1';
  const SHARED_KEY='orrery.demo.shared.v1';
  const bootstrap=window.OrreryDemoBootstrap||null;
  const ATTRIBUTES=['title','aria-label','alt','placeholder','data-tip','data-tooltip'];
  const SKIP=new Set(['SCRIPT','STYLE','NOSCRIPT','TEXTAREA']);
  const IDENTITY_TIMEOUT_MS=5000;

  function stored(){try{return localStorage.getItem(STORAGE_KEY)==='1';}catch(_){return false;}}
  function parseWords(text){
    return String(text||'').split(/[,\n]/).map(word=>word.trim()).filter(word=>word.length>=2);
  }
  function storedWords(){
    try{return parseWords((JSON.parse(localStorage.getItem(WORDS_KEY)||'[]')||[]).join(','));}catch(_){return [];}
  }
  function words(search){
    if(bootstrap)return bootstrap.words;
    const extra=parseWords(new URLSearchParams(search).get('mask')||'');
    return [...new Set([...storedWords(),...extra])];
  }
  function requested(search){
    if(bootstrap)return bootstrap.on;
    const value=new URLSearchParams(search).get('demo');
    if(value==='1'||value==='true')return true;
    if(value==='0'||value==='false')return false;
    return stored();
  }
  function publish(value){
    if(bootstrap||!window.OrreryPrefs?.flush)return Promise.resolve(true);
    const encoded=JSON.stringify({version:1,on:value,words:value?words(location.search):[]});
    try{localStorage.setItem(SHARED_KEY,encoded);}catch(_){return Promise.resolve(false);}
    return window.OrreryPrefs.flush().then(data=>data?.prefs?.[SHARED_KEY]===encoded);
  }
  function syncedReload(reload){
    return publish(api.on).then(ok=>{
      if(ok){reload();return true;}
      window.showToast?.('Could not sync Demo mode. Try again.',true);return false;
    });
  }
  let resolveReady=null;
  const api={
    on:requested(location.search),
    known:false,
    ready:Promise.resolve(),
    mask:text=>text,
    /* The real text of a DOM selection or a masked string that came from a
       text node on this page (see realSelectionText). */
    stored,
    setStored(value){
      try{
        if(value)localStorage.setItem(STORAGE_KEY,'1');
        else localStorage.removeItem(STORAGE_KEY);
      }catch(_){/* not kept: private window or blocked storage */}
    },
    /* The switch reloads: terminals then redraw from the backend with (or
       without) the mask, instead of keeping what they already painted. */
    reloadFor(value){
      api.setStored(value);
      const url=new URL(location.href);url.searchParams.delete('demo');
      return publish(value).then(ok=>{
        if(ok){location.replace(url.toString());return true;}
        api.setStored(api.on);window.showToast?.('Could not sync Demo mode. Try again.',true);
        const toggle=document.getElementById('demoModeToggle');if(toggle)toggle.checked=api.on;
        return false;
      });
    },
    attachFrame(){},
    requested,
    parseWords,
    storedWords,
    /* Saved words; demo mode reloads to redraw the terminals with them. */
    setWords(list,{reload=true}={}){
      try{localStorage.setItem(WORDS_KEY,JSON.stringify(parseWords((list||[]).join(','))));}catch(_){/* not kept */}
      if(reload&&api.on)return syncedReload(()=>location.reload());
    },
  };
  window.OrreryDemo=api;
  if(!api.on)return;
  api.ready=new Promise(resolve=>{resolveReady=resolve;});

  const html=document.documentElement;
  html.setAttribute('data-demo','pending');
  const style=document.createElement('style');
  style.textContent=
    'html[data-demo="pending"] body,html[data-demo="failed"] body{visibility:hidden}'+
    '.demo-status{visibility:visible;position:fixed;inset:0;display:flex;align-items:center;justify-content:center;'+
    'z-index:2147483600;background:var(--bg,#0a0a0c);color:var(--fg,#d8d4c6);font:13px/1.6 "IBM Plex Mono",Menlo,monospace}'+
    '.demo-status div{max-width:520px;padding:24px;border:1px solid currentColor;border-radius:4px}'+
    '.demo-status button,.demo-status a{font:inherit;color:inherit;margin-right:12px}'+
    '.demo-badge{position:fixed;left:8px;bottom:8px;z-index:2147483000;pointer-events:none;'+
    'font:600 10px/1 "IBM Plex Mono",Menlo,monospace;letter-spacing:.12em;padding:4px 6px;'+
    'border:1px solid currentColor;border-radius:3px;opacity:.55;color:var(--muted,#9a968a);'+
    'background:var(--bg,#0a0a0c)}'+
    '.demo-field-mask{position:absolute;pointer-events:none;overflow:hidden;box-sizing:border-box;'+
    'border-color:transparent!important;background:transparent!important;z-index:1}'+
    '.demo-field-mask>span{display:block;white-space:pre-wrap;word-wrap:break-word}';
  document.head.appendChild(style);

  // ---------------------------------------------------------------- terminal rows
  const rowOriginals=new WeakMap(); // text node in a terminal row -> {original, masked}
  const pendingRows=new Set();
  function rowOf(node){
    const element=node.nodeType===3?node.parentElement:node;
    const rows=element&&element.closest&&element.closest('.xterm-rows');
    if(!rows||element===rows)return null;
    let row=element;
    while(row&&row.parentElement!==rows)row=row.parentElement;
    return row;
  }
  function realRowText(node){
    const kept=rowOriginals.get(node);
    return kept&&kept.masked===node.nodeValue?kept.original:node.nodeValue;
  }
  /* Mask the rows xterm has just drawn. A row is matched together with the
     other rows of its wrapped line (cockpit.html's rowGroup, padded with the
     spaces xterm trims at the end of a row), on their real text, and each
     text node gets back its own part: same length, same cells. */
  function maskRows(){
    const done=new Set();
    for(const row of pendingRows){
      if(done.has(row)||!row.isConnected)continue;
      const group=(api.rowGroup&&api.rowGroup(row))||{rows:[row],pads:[0]};
      const parts=[];let text=group.before||'';
      group.rows.forEach((member,i)=>{
        done.add(member);
        const walker=member.ownerDocument.createTreeWalker(member,4 /* text */);
        let node;
        while((node=walker.nextNode())){const real=realRowText(node);parts.push({node,at:text.length,real});text+=real;}
        text+=' '.repeat(group.pads[i]||0);
      });
      text+=group.after||'';
      const masked=api.mask(text);
      for(const {node,at,real} of parts){
        const shown=masked.slice(at,at+real.length);
        if(shown!==real)rowOriginals.set(node,{original:real,masked:shown});else rowOriginals.delete(node);
        if(node.nodeValue!==shown)node.nodeValue=shown;
      }
    }
    pendingRows.clear();
  }

  // ---------------------------------------------------------------- DOM text
  const originals=new WeakMap(); // text node -> {original, masked}
  const attributeOriginals=new WeakMap();
  let remasking=false;
  function maskText(node){
    const row=rowOf(node);
    if(row){pendingRows.add(row);return;}
    const shown=node.nodeValue;
    if(!shown)return;
    const kept=originals.get(node);
    // Our own write comes back through the observer: nothing to do.
    if(!remasking&&kept&&kept.masked===shown)return;
    const value=kept&&kept.masked===shown?kept.original:shown;
    const masked=api.mask(value);
    if(masked!==value){originals.set(node,{original:value,masked});node.nodeValue=masked;}
    else{originals.delete(node);if(node.nodeValue!==value)node.nodeValue=value;}
  }
  function maskAttributes(element){
    let kept=attributeOriginals.get(element);
    if(!kept){kept=new Map();attributeOriginals.set(element,kept);}
    for(const name of ATTRIBUTES){
      const value=element.getAttribute&&element.getAttribute(name);
      if(!value){kept.delete(name);continue;}
      const original=kept.get(name),real=original&&original.masked===value?original.original:value;
      const masked=api.mask(real);
      if(masked!==real)kept.set(name,{original:real,masked});else kept.delete(name);
      if(masked!==value)element.setAttribute(name,masked);
    }
  }
  function walk(rootNode){
    if(!rootNode)return;
    if(rootNode.nodeType===3){
      if(!rootNode.parentNode||!SKIP.has(rootNode.parentNode.nodeName))maskText(rootNode);
      return;
    }
    if(rootNode.nodeType!==1&&rootNode.nodeType!==9&&rootNode.nodeType!==11)return;
    if(rootNode.nodeType===1){
      if(SKIP.has(rootNode.nodeName))return;
      maskAttributes(rootNode);
    }
    const doc=rootNode.ownerDocument||rootNode;
    const walker=doc.createTreeWalker(rootNode,5 /* elements and text */,{
      acceptNode:node=>node.nodeType===1&&SKIP.has(node.nodeName)?2 /* reject */:1,
    });
    let node;
    while((node=walker.nextNode())){
      if(node.nodeType===3)maskText(node);else maskAttributes(node);
    }
    maskRows();
  }

  /* The real text of a selection: the browser's own text for it (which has
     the line breaks of the layout), with each masked run swapped back for the
     original of the text node it came from. Every text node of the selection
     is followed in document order, masked or not, so a run is restored at its
     own place: a "****" the user typed earlier in the selection stays.
     (A terminal's selection is xterm's own and copies from its real buffer.) */
  function realSelectionText(selection){
    const shown=String(selection);
    if(!shown||!selection.rangeCount)return shown;
    const pieces=[];
    for(let r=0;r<selection.rangeCount;r++){
      const range=selection.getRangeAt(r);
      const doc=range.startContainer.ownerDocument||document;
      const root=range.commonAncestorContainer.nodeType===3?range.commonAncestorContainer.parentNode:range.commonAncestorContainer;
      const walker=doc.createTreeWalker(root,4 /* text */);
      let node=walker.currentNode.nodeType===3?walker.currentNode:walker.nextNode();
      for(;node;node=walker.nextNode()){
        if(!range.intersectsNode(node))continue;
        const kept=originals.get(node);
        const from=node===range.startContainer?range.startOffset:0;
        const to=node===range.endContainer?range.endOffset:node.nodeValue.length;
        if(to<=from)continue;
        const shownPart=node.nodeValue.slice(from,to);
        const realPart=kept&&kept.masked===node.nodeValue?kept.original.slice(from,to):shownPart;
        pieces.push({masked:shownPart,original:realPart});
      }
    }
    let out='',cursor=0;
    for(const piece of pieces){
      const at=shown.indexOf(piece.masked,cursor);
      if(at<0)continue; // not in the text (hidden, or white space the layout collapsed)
      out+=shown.slice(cursor,at)+piece.original;cursor=at+piece.masked.length;
    }
    return out+shown.slice(cursor);
  }

  // ---------------------------------------------------------------- fields
  /* A field keeps its real value. While the value holds a name, its own text
     is made transparent (the caret and the selection stay) and a masked copy
     is drawn exactly over it. Values set by code (a restored draft, history)
     are caught by the value setter below as well as by input events. */
  const fields=new Set();
  const FIELD_STYLE=['font','fontFamily','fontSize','fontWeight','fontStyle','letterSpacing','lineHeight',
    'textAlign','textIndent','textTransform','wordSpacing','tabSize','direction',
    'paddingTop','paddingRight','paddingBottom','paddingLeft',
    'borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth','borderStyle','color'];
  function isTextField(el){
    if(!el||el.nodeType!==1)return false;
    if(el.nodeName==='TEXTAREA')return true;
    return el.nodeName==='INPUT'&&/^(text|search|url|email|tel|)$/i.test(el.getAttribute('type')||'');
  }
  function syncField(field){
    const real=field.value||'';
    const masked=real?api.mask(real):real;
    let overlay=field.__demoOverlay;
    if(masked===real||!field.isConnected){
      if(overlay){overlay.remove();field.__demoOverlay=null;}
      if(field.__demoColor!==undefined){
        field.style.removeProperty('color');field.style.removeProperty('-webkit-text-fill-color');
        field.style.caretColor=field.__demoCaret||'';field.__demoColor=undefined;
      }
      if(!field.isConnected)fields.delete(field);
      return;
    }
    const doc=field.ownerDocument,view=doc.defaultView;
    const computed=view.getComputedStyle(field);
    if(field.__demoColor===undefined){
      field.__demoColor=computed.color;field.__demoCaret=field.style.caretColor;
      field.style.caretColor=computed.caretColor==='auto'?computed.color:computed.caretColor;
      field.style.setProperty('color','transparent','important');
      field.style.setProperty('-webkit-text-fill-color','transparent','important');
    }
    const host=field.offsetParent||doc.body;
    if(!overlay){
      overlay=doc.createElement('div');overlay.className='demo-field-mask';overlay.setAttribute('aria-hidden','true');
      overlay.appendChild(doc.createElement('span'));field.__demoOverlay=overlay;
    }
    if(overlay.parentNode!==host)host.appendChild(overlay);
    for(const name of FIELD_STYLE)overlay.style[name]=name==='color'?field.__demoColor:computed[name];
    const span=overlay.firstChild;
    span.style.whiteSpace=field.nodeName==='TEXTAREA'?'pre-wrap':'pre';
    // Place it over the field inside the same positioned ancestor.
    const box=field.getBoundingClientRect(),base=host===doc.body?{left:-view.scrollX,top:-view.scrollY}:host.getBoundingClientRect();
    const hostLeft=host===doc.body?0:host.clientLeft,hostTop=host===doc.body?0:host.clientTop;
    overlay.style.left=`${box.left-base.left-hostLeft+(host===doc.body?0:host.scrollLeft)}px`;
    overlay.style.top=`${box.top-base.top-hostTop+(host===doc.body?0:host.scrollTop)}px`;
    overlay.style.width=`${box.width}px`;overlay.style.height=`${box.height}px`;
    if(field.nodeName==='INPUT'){span.style.lineHeight=`${field.clientHeight-parseFloat(computed.paddingTop)-parseFloat(computed.paddingBottom)}px`;}
    span.style.transform=`translate(${-field.scrollLeft}px,${-field.scrollTop}px)`;
    if(span.textContent!==masked+(field.nodeName==='TEXTAREA'?'\n':''))span.textContent=masked+(field.nodeName==='TEXTAREA'?'\n':'');
  }
  function trackField(field){
    if(!isTextField(field)||fields.has(field))return;
    fields.add(field);
    for(const kind of ['input','change','scroll','focus','blur','select'])
      field.addEventListener(kind,()=>syncField(field),{passive:true});
    syncField(field);
  }
  function trackFields(rootNode){
    if(!rootNode||rootNode.nodeType!==1&&rootNode.nodeType!==9)return;
    if(isTextField(rootNode))trackField(rootNode);
    if(rootNode.querySelectorAll)for(const el of rootNode.querySelectorAll('textarea,input'))trackField(el);
  }
  function patchValueSetters(view){
    for(const proto of [view.HTMLInputElement&&view.HTMLInputElement.prototype,view.HTMLTextAreaElement&&view.HTMLTextAreaElement.prototype]){
      if(!proto||proto.__demoPatched)continue;
      const property=Object.getOwnPropertyDescriptor(proto,'value');
      if(!property||!property.set)continue;
      Object.defineProperty(proto,'value',{configurable:true,enumerable:property.enumerable,get:property.get,
        set(value){property.set.call(this,value);if(fields.has(this))syncField(this);else trackField(this);}});
      proto.__demoPatched=true;
    }
  }
  function followFields(){
    for(const field of fields)syncField(field);
    requestAnimationFrame(followFields);
  }

  // ---------------------------------------------------------------- documents
  function observe(doc){
    if(!doc||!doc.documentElement||doc.__orreryDemoObserved)return;
    doc.__orreryDemoObserved=true;
    if(doc.defaultView)patchValueSetters(doc.defaultView);
    walk(doc.documentElement);trackFields(doc.documentElement);
    new MutationObserver(records=>{
      for(const record of records){
        if(record.type==='characterData')maskText(record.target);
        else if(record.type==='attributes')maskAttributes(record.target);
        else for(const added of record.addedNodes){walk(added);trackFields(added);}
      }
      maskRows();
    }).observe(doc.documentElement,{subtree:true,childList:true,characterData:true,
      attributes:true,attributeFilter:ATTRIBUTES});
    const view=doc.defaultView;
    if(view&&view!==window)view.addEventListener('copy',realCopy);
  }

  /* A frame is hidden whenever it may be showing a document that is not yet
     masked: from the moment its src changes or its page unloads, until the
     next document has been observed (which masks it as it is parsed). */
  api.attachFrame=function(frame){
    if(!frame||frame.__orreryDemoFrame)return;
    frame.__orreryDemoFrame=true;
    let waitingFor=null; // the document that must be replaced before showing
    const hide=()=>{frame.style.setProperty('visibility','hidden','important');};
    const show=()=>{frame.style.removeProperty('visibility');};
    const current=()=>{try{return frame.contentDocument;}catch(_){return null;}};
    hide();waitingFor=null;
    new MutationObserver(()=>{hide();waitingFor=current();}).observe(frame,{attributes:true,attributeFilter:['src','srcdoc']});
    const watch=()=>{
      const doc=current();
      if(doc&&doc.documentElement&&doc!==waitingFor){
        if(!doc.__orreryDemoObserved){
          observe(doc);
          const view=doc.defaultView;
          if(view)view.addEventListener('pagehide',()=>{hide();waitingFor=doc;},{once:true});
        }
        waitingFor=null;show();
      }else if(!doc){hide();} // another origin: never shown in demo mode
      requestAnimationFrame(watch);
    };
    watch();
  };

  // ---------------------------------------------------------------- copy
  /* A copy gives the real text: a DOM selection is rebuilt from the
     originals. A field copies its real value by itself, and so does a
     terminal (xterm's selection comes from its real buffer, through its own
     textarea). */
  function realCopy(event){
    const data=event.clipboardData;
    if(!data)return;
    const target=event.target;
    if(isTextField(target))return;
    const view=target&&target.ownerDocument&&target.ownerDocument.defaultView||window;
    const selection=view.getSelection&&view.getSelection();
    if(!selection||!String(selection))return;
    const real=realSelectionText(selection);
    if(real===String(selection)&&!data.getData('text/plain'))return;
    data.setData('text/plain',real);
    event.preventDefault();
  }

  // ---------------------------------------------------------------- start
  function fail(reason){
    html.setAttribute('data-demo','failed');
    let panel=document.querySelector('.demo-status');
    if(!panel){
      panel=document.createElement('div');panel.className='demo-status';panel.setAttribute('role','alert');
      (document.body||html).appendChild(panel);
    }
    const plain=new URL(location.href);plain.searchParams.set('demo','0');
    panel.innerHTML='<div><b>Demo mode</b><p class="demo-reason"></p>'+
      '<p>The page stays hidden: it cannot show your screen without knowing which names to mask.</p>'+
      '<p><button type="button" class="demo-retry">Retry</button><a class="demo-plain">Open without demo mode</a></p></div>';
    panel.querySelector('.demo-reason').textContent=`Could not learn the names to hide (${reason}).`;
    panel.querySelector('.demo-plain').href=plain.toString();
    panel.querySelector('.demo-retry').addEventListener('click',()=>{panel.remove();html.setAttribute('data-demo','pending');load();});
  }
  function load(){
    const abort=typeof AbortController==='function'?new AbortController():null;
    const timer=setTimeout(()=>abort&&abort.abort(),IDENTITY_TIMEOUT_MS);
    (bootstrap?Promise.resolve(bootstrap.identity):publish(true).then(ok=>{
      if(!ok)throw new Error('Demo mode could not be synced');
      return fetch('/telemetry/identity',{cache:'no-store',signal:abort?abort.signal:undefined}).then(response=>{
        if(!response.ok)throw new Error(`the backend answered ${response.status}`);
        return response.json();
      });
    }))
      .then(identity=>{
        clearTimeout(timer);
        const masker=window.OrreryDemoMask.create({...(identity||{}),words:words(location.search)});
        if(!masker.active)throw new Error('the backend returned no names');
        api.known=true;api.mask=masker.mask;
        const start=()=>{
          observe(document);
          const badge=document.createElement('div');
          badge.className='demo-badge';badge.setAttribute('aria-label','Demo mode');badge.textContent='DEMO';
          document.body.appendChild(badge);
          window.addEventListener('copy',realCopy);
          requestAnimationFrame(followFields);
          html.setAttribute('data-demo','on');
          resolveReady();
        };
        if(document.body)start();else document.addEventListener('DOMContentLoaded',start,{once:true});
      })
      .catch(error=>{
        clearTimeout(timer);
        const reason=error&&error.name==='AbortError'?'no answer in 5 seconds':String(error&&error.message||error);
        if(document.body)fail(reason);else document.addEventListener('DOMContentLoaded',()=>fail(reason),{once:true});
      });
  }
  api.refresh=function({on,identity,words:extra}){
    const masker=on?window.OrreryDemoMask.create({...identity,words:extra}):null;
    if(on&&!masker.active)throw new Error('No names to mask');
    api.on=on;api.mask=on?masker.mask:text=>text;remasking=true;
    try{
      const visit=doc=>{walk(doc.documentElement);for(const frame of doc.querySelectorAll('iframe')){try{if(frame.contentDocument)visit(frame.contentDocument);}catch(_){}}};
      visit(document);for(const field of fields)syncField(field);
    }finally{remasking=false;}
    const badge=document.querySelector('.demo-badge');if(badge)badge.hidden=!on;
    html.setAttribute('data-demo',on?'on':'off');
  };
  load();
})();
