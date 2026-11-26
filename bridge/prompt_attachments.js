/* Files stay in the browser draft until the operator submits it. */
(function(root){
  'use strict';
  const imageTypes=new Set(['jpg','jpeg','png','webp']);
  const maxFiles=5,mebibyte=1024*1024,fileLimit=50;
  const clipboardImageExtensions={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'};
  function pathName(path){
    return typeof path==='string'&&/^\/(?:[^\x00-\x1f\x7f-\x9f]+)$/u.test(path)?path.split('/').pop():'';
  }
  function eventFiles(data){
    const files=Array.from(data?.files||[]);
    if(!files.length)for(const item of Array.from(data?.items||[])){
      const file=item.kind==='file'&&item.getAsFile();
      if(file)files.push(file);
    }
    return files.map(file=>{
      const extension=clipboardImageExtensions[file.type];
      if(pathName(file.path)||!extension||kindFor(file).kind==='image')return file;
      return new File([file],file.name?file.name+'.'+extension:'Clipboard image.'+extension,
        {type:file.type,lastModified:file.lastModified});
    });
  }
  function snapshotFiles(attachments){
    if(!Array.isArray(attachments))return [];
    return attachments.slice(0,maxFiles).flatMap(item=>{
      if(typeof item?.name!=='string'||item.name.length>256||/[\\/]/u.test(item.name)||
         typeof item.data!=='string'||!item.data)return [];
      const format=kindFor({name:item.name});
      if(item.data.length>4*Math.ceil(format.maxBytes/3))return [];
      try{
        const binary=atob(item.data),bytes=new Uint8Array(binary.length);
        for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
        return [new File([bytes],item.name,{type:item.type||'',lastModified:item.modified||0})];
      }catch(_){return [];}
    });
  }
  function kindFor(file){
    const dot=file.name.lastIndexOf('.');
    const suffix=dot>0?file.name.slice(dot+1).toLowerCase():'';
    const extension=/^[a-z0-9]{1,32}$/.test(suffix)?suffix:'';
    if(imageTypes.has(extension))return {kind:'image',extension,maxBytes:fileLimit*mebibyte};
    return {kind:'file',extension,maxBytes:fileLimit*mebibyte};
  }
  function dataFor(file){
    return new Promise((resolve,reject)=>{
      const reader=new FileReader();
      reader.onload=()=>resolve(String(reader.result).split(',',2)[1]);
      reader.onerror=()=>reject(new Error('Could not read the selected file.'));
      reader.readAsDataURL(file);
    });
  }
  function mount({host,clip,picker,list,onChange,onError,mayEdit,pickPaths}){
    let entries=[],dragDepth=0,pending=false;
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
        label.textContent=entry.name;item.title=entry.name;
        remove.type='button';remove.textContent='×';remove.title='Remove '+entry.name;
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
    function append(entry){
      if(entries.length===maxFiles){onError('Attach up to '+maxFiles+' files.');return false;}
      entries.push(entry);return true;
    }
    function appendPath(path){
      const name=pathName(path);
      if(!name||entries.some(entry=>entry.path===path))return true;
      return append({path,name,kind:'file',extension:kindFor({name}).extension});
    }
    function addPaths(paths){
      if(!mayEdit())return;
      for(const path of paths)if(!appendPath(path))break;
      paint();
    }
    function add(files,sourcePaths=[]){
      if(!mayEdit())return;
      const errors=[];
      for(const [index,file] of Array.from(files).entries()){
        const format=kindFor(file);
        const source=sourcePaths[index]||file.path;
        if(pathName(source)&&(!file.size||file.size>format.maxBytes)){
          if(!appendPath(source))break;
          continue;
        }
        if(!file.size){errors.push(file.name+' is empty.');continue;}
        if(file.size>format.maxBytes){
          errors.push(file.name+' exceeds '+format.maxBytes/mebibyte+' MiB.');continue;
        }
        if(entries.some(entry=>entry.file&&entry.name===file.name&&entry.file.size===file.size&&entry.file.lastModified===file.lastModified))continue;
        const mime=format.extension==='jpg'||format.extension==='jpeg'?'image/jpeg':'image/'+format.extension;
        const preview=format.kind==='image'?URL.createObjectURL(file.slice(0,file.size,mime)):null;
        if(!append({file,name:file.name,...format,preview})){
          if(preview)URL.revokeObjectURL(preview);
          break;
        }
      }
      if(errors.length)onError(errors.join(' '));
      paint();
    }
    clip.onclick=async()=>{
      if(!mayEdit()||pending)return;
      if(!pickPaths){picker.click();return;}
      try{addPaths(await pickPaths());}
      catch(_){if(mayEdit())picker.click();}
    };
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
    async function paste(read,fallback=[]){
      if(pending||!mayEdit())return;
      pending=true;onChange();
      try{
        const result=await read();
        if(!mayEdit())return;
        const paths=Array.isArray(result.paths)?result.paths.filter(pathName):[];
        const snapshot=Array.isArray(result.attachments)?result.attachments:[];
        const files=snapshotFiles(snapshot);
        if(fallback.length){
          const selected=files.map(file=>file.name).concat(paths.map(pathName)).sort();
          const matching=selected.length===fallback.length&&
            fallback.map(file=>file.name).sort().every((name,index)=>name===selected[index]);
          if(!matching||!files.length){
            const matchingPaths=paths.length===fallback.length&&paths.every((path,index)=>pathName(path)===fallback[index].name);
            add(fallback,matchingPaths?paths:[]);
            return;
          }
        }
        if(files.length)add(files);
        if(paths.length)addPaths(paths);
        const skipped=(result.skipped||0)+snapshot.length-files.length;
        if(result.oversized)onError('Clipboard selection exceeds the size limit (50 MiB, or 10 MiB for a clipboard-only image).');
        else if(result.error&&!files.length&&!paths.length)onError('Could not read clipboard attachments.');
        else if(skipped)onError(skipped===1?'1 clipboard item could not be attached.':skipped+' clipboard items could not be attached.');
        else if(!files.length&&!paths.length)onError('No files or images on the clipboard.');
      }catch(_){
        if(fallback.length)add(fallback);
        else if(mayEdit())onError('Could not read clipboard attachments.');
      }finally{
        pending=false;onChange();
      }
    }
    return {add,addPaths,clear,paste,get pending(){return pending;},get entries(){return entries.slice();}};
  }
  async function upload(target,entries){
    const paths=[];
    for(const entry of entries){
      const label=entry.name.slice(0,256);
      const body=entry.path?{...target,kind:'path',sourcePath:entry.path,label}:
        {...target,kind:entry.kind,data:await dataFor(entry.file),label};
      if(!entry.path&&entry.kind==='file')body.format=entry.extension;
      const response=await fetch('/telemetry/prompt-attachment',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),
      });
      const payload=await response.json();
      if(response.status===413||payload.error==='file_too_large'||payload.error==='image_too_large')
        throw new Error(entry.name+' exceeds 50 MiB.');
      if(payload.error==='attachment_source_unreadable')
        throw new Error('Could not read '+entry.name+' from its original location.');
      if(response.ok&&entry.path&&payload.original===true&&payload.path===entry.path){
        paths.push(payload.path);continue;
      }
      if(!response.ok||typeof payload.path!=='string'||!/^\.\/\.orrery-input-(?:images|files)\/[a-f0-9]{32}(?:\.[a-z0-9]{1,32})?$/.test(payload.path))
        throw new Error('Could not save '+entry.name+' in the agent workspace.');
      paths.push(payload.path);
    }
    return paths;
  }
  root.OrreryPromptAttachments=Object.freeze({mount,upload,eventFiles});
})(window);
