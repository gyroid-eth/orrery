/* Small inert table projection. Never parse HTML, URLs, images or inline JS. */
(function(root){
  'use strict';
  function cells(line){
    if(/^ {4}|^\t/.test(line))return null;
    line=line.trim();let parts=[''],pipes=0;
    for(let i=0;i<line.length;i++){
      const ch=line[i];
      if(ch==='\\'&&['|','\\'].includes(line[i+1])){parts[parts.length-1]+=line[++i];continue;}
      if(ch==='|'){parts.push('');pipes++;}else parts[parts.length-1]+=ch;
    }
    if(!pipes)return null;
    if(line[0]==='|')parts.shift();
    if(parts[parts.length-1]==='')parts.pop();
    return parts.map(value=>value.trim());
  }
  const blockStart=line=>/^ {0,3}(?:`{3,}|~{3,}|#{1,6}(?:\s|$)|>|[-+*]\s+|\d{1,9}[.)]\s+)/.test(line);
  function parse(text){
    const lines=text.match(/[^\n]*\n|[^\n]+$/g)||[],blocks=[];let plain='',fence=null;
    const bare=line=>line.replace(/\r?\n$/,'');
    for(let i=0;i<lines.length;){
      const line=bare(lines[i]),mark=/^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
      if(fence){
        plain+=lines[i++];
        if(mark&&mark[1][0]===fence.char&&mark[1].length>=fence.length&&!mark[2].trim())fence=null;
        continue;
      }
      if(mark){fence={char:mark[1][0],length:mark[1].length};plain+=lines[i++];continue;}
      const header=cells(line),delimiter=i+1<lines.length?cells(bare(lines[i+1])):null;
      if(blockStart(line)||!header?.length||header.length>64||!delimiter||header.length!==delimiter.length||!delimiter.every(cell=>/^:?-{3,}:?$/.test(cell))){plain+=lines[i++];continue;}
      const rows=[];let end=i+2,valid=true;
      while(end<lines.length){
        if(blockStart(bare(lines[end])))break;
        const row=cells(bare(lines[end]));
        if(!row)break;
        if(row.length!==header.length||rows.length>=500)valid=false;
        rows.push(row);end++;
      }
      if(!valid){plain+=lines.slice(i,end).join('');i=end;continue;}
      if(plain){blocks.push({kind:'text',text:plain});plain='';}
      blocks.push({kind:'table',header,rows,align:delimiter.map(cell=>cell.startsWith(':')&&cell.endsWith(':')?'center':cell.endsWith(':')?'right':'left'),raw:lines.slice(i,end).join('')});i=end;
    }
    if(plain)blocks.push({kind:'text',text:plain});return blocks;
  }
  function render(text,host){
    const blocks=parse(text);
    if(!blocks.some(block=>block.kind==='table')){host.textContent=text;return host;}
    for(const block of blocks){
      if(block.kind==='text'){const prose=document.createElement('span');prose.textContent=block.text;host.appendChild(prose);continue;}
      const container=document.createElement('div');container.className='conversation-table';
      const copy=document.createElement('button');copy.type='button';copy.className='cockpit-control conversation-table-copy';copy.textContent='Copy Markdown';
      copy.addEventListener('click',async event=>{event.stopPropagation();try{await navigator.clipboard.writeText(block.raw);copy.textContent='Copied';}catch(_){copy.textContent='Copy unavailable';}});
      copy.addEventListener('keydown',event=>event.stopPropagation());
      const scroll=document.createElement('div');scroll.className='conversation-table-scroll';scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label','Markdown table; scroll horizontally for more columns');
      const table=document.createElement('table'),head=document.createElement('thead'),body=document.createElement('tbody');
      function row(values,header){const tr=document.createElement('tr');values.forEach((value,i)=>{const cell=document.createElement(header?'th':'td');cell.textContent=value;cell.style.textAlign=block.align[i];if(header)cell.scope='col';tr.appendChild(cell);});return tr;}
      head.appendChild(row(block.header,true));for(const values of block.rows)body.appendChild(row(values,false));
      table.append(head,body);scroll.appendChild(table);container.append(copy,scroll);host.appendChild(container);
    }
    return host;
  }
  root.OrreryConversationMarkdown=Object.freeze({parse,render});
})(typeof window==='undefined'?globalThis:window);
