/* Files stay in the browser draft until the operator submits it. */
(function(root){
  'use strict';
  const imageTypes=new Set(['jpg','jpeg','png','webp']);
  const fileTypes=new Set(['pdf','txt','md','csv','json']);
  const maxFiles=5,mebibyte=1024*1024;
  function kindFor(file){
    const extension=file.name.split('.').pop().toLowerCase();
    if(imageTypes.has(extension))return {kind:'image',extension,maxBytes:10*mebibyte};
    if(fileTypes.has(extension))return {kind:'file',extension,maxBytes:5*mebibyte};
    return null;
  }
  function dataFor(file){
    return new Promise((resolve,reject)=>{
      const reader=new FileReader();
      reader.onload=()=>resolve(String(reader.result).split(',',2)[1]);
      reader.onerror=()=>reject(new Error('Could not read the selected file.'));
      reader.readAsDataURL(file);
    });
  }
  function mount({host,clip,picker,list,onChange,onError,mayEdit}){
    let entries=[],dragDepth=0;
    const node=(tag,cls)=>{
      const el=document.createElement(tag);el.className=cls;return el;
    };
    function clear(){
      for(const entry of entries)if(entry.preview)URL.revokeObjectURL(entry.preview);
      entries=[];paint();
    }
    function paint(){
      list.hidden=!entries.length;
      list.replaceChildren(...entries.map(entry=>{
        const item=node('li','prompt-attachment'),label=node('span','prompt-file-name');
        const remove=node('button','prompt-file-remove');
        let icon;
        if(entry.preview){
          icon=node('img','prompt-file-preview');icon.src=entry.preview;icon.alt='';
        }else{
          const svg='http://www.w3.org/2000/svg';
          icon=document.createElementNS(svg,'svg');icon.classList.add('prompt-file-icon');
          icon.setAttribute('viewBox','0 0 16 18');icon.setAttribute('aria-hidden','true');
          const line=document.createElementNS(svg,'path');
          line.setAttribute('d',entry.extension==='pdf'?'M3 1h6l4 4v12H3z M9 1v5h4 M5 13l2-3 1 3 3-1':
            'M3 1h6l4 4v12H3z M9 1v5h4 M5 10h6 M5 13h5');
          line.setAttribute('stroke','currentColor');line.setAttribute('fill','none');icon.append(line);
        }
        label.textContent=entry.file.name;item.title=entry.file.name;
        remove.type='button';remove.textContent='×';remove.title='Remove '+entry.file.name;
        remove.setAttribute('aria-label',remove.title);
        remove.onclick=()=>{
          if(!mayEdit())return;
          entries=entries.filter(value=>value!==entry);
          if(entry.preview)URL.revokeObjectURL(entry.preview);
          paint();clip.focus({preventScroll:true});
        };
        item.append(icon,label,remove);
        return item;
      }));
      onChange();
    }
    function add(files){
      if(!mayEdit())return;
      const unsupported=[],oversized=[];
      for(const file of files){
        const format=kindFor(file);
        if(!format){unsupported.push(file.name);continue;}
        if(!file.size||file.size>format.maxBytes){oversized.push(file.name);continue;}
        if(entries.some(entry=>entry.file.name===file.name&&entry.file.size===file.size&&entry.file.lastModified===file.lastModified))continue;
        if(entries.length===maxFiles){onError('Attach up to '+maxFiles+' files.');break;}
        const mime=format.extension==='jpg'||format.extension==='jpeg'?'image/jpeg':'image/'+format.extension;
        const preview=format.kind==='image'?URL.createObjectURL(file.slice(0,file.size,mime)):null;
        entries.push({file,...format,preview});
      }
      if(unsupported.length)onError('Unsupported file type: '+unsupported.join(', '));
      else if(oversized.length)onError('Empty or too large: '+oversized.join(', '));
      paint();
    }
    clip.onclick=()=>{if(mayEdit())picker.click();};
    picker.onchange=()=>{add(picker.files);picker.value='';};
    const dropping=event=>Array.from(event.dataTransfer?.types||[]).includes('Files');
    host.addEventListener('dragenter',event=>{
      if(!dropping(event))return;
      event.preventDefault();dragDepth++;
      host.toggleAttribute('data-dragging',mayEdit());
    });
    host.addEventListener('dragover',event=>{
      if(!dropping(event))return;
      event.preventDefault();event.dataTransfer.dropEffect=mayEdit()?'copy':'none';
    });
    host.addEventListener('dragleave',event=>{
      if(!dropping(event))return;
      dragDepth=Math.max(0,dragDepth-1);
      if(!dragDepth)host.removeAttribute('data-dragging');
    });
    host.addEventListener('drop',event=>{
      if(!dropping(event))return;
      event.preventDefault();dragDepth=0;host.removeAttribute('data-dragging');
      add(event.dataTransfer.files);
    });
    return {clear,get entries(){return entries.slice();}};
  }
  async function upload(target,entries){
    const paths=[];
    for(const entry of entries){
      const data=await dataFor(entry.file);
      const body={...target,kind:entry.kind,data,label:entry.file.name.slice(0,256)};
      if(entry.kind==='file')body.format=entry.extension;
      const response=await fetch('/telemetry/prompt-attachment',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),
      });
      const payload=await response.json();
      if(!response.ok||typeof payload.path!=='string'||!/^\.\/\.orrery-input-(images|files)\/[a-f0-9]{32}\.[a-z0-9]+$/.test(payload.path))
        throw new Error('Could not save '+entry.file.name+' in the agent workspace.');
      paths.push(payload.path);
    }
    return paths;
  }
  root.OrreryPromptAttachments=Object.freeze({mount,upload});
})(window);
