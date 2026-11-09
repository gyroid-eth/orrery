/* Small inert Markdown projection. Never parse HTML, load images or run inline
   JS: every piece of text reaches the page as a text node. */
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
  // GFM: a delimiter cell is one or more hyphens, with optional colons for alignment.
  const isDelimiter=(header,delimiter)=>Boolean(header?.length&&header.length<=64&&delimiter&&header.length===delimiter.length&&delimiter.every(cell=>/^:?-+:?$/.test(cell)));
  const alignOf=cell=>cell.startsWith(':')&&cell.endsWith(':')?'center':cell.endsWith(':')?'right':'left';
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
      if(blockStart(line)||!isDelimiter(header,delimiter)){plain+=lines[i++];continue;}
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
      blocks.push({kind:'table',header,rows,align:delimiter.map(alignOf),raw:lines.slice(i,end).join('')});i=end;
    }
    if(plain)blocks.push({kind:'text',text:plain});return blocks;
  }
  // `fill(cell,value)` writes one cell; the conversation keeps cells as text.
  function tableNode(block,fill=(cell,value)=>renderText(value,cell)){
    const container=document.createElement('div');container.className='conversation-table';
    const copy=document.createElement('button');copy.type='button';copy.className='cockpit-control conversation-table-copy';copy.textContent='Copy Markdown';
    copy.addEventListener('click',async event=>{event.stopPropagation();try{await navigator.clipboard.writeText(block.raw);copy.textContent='Copied';}catch(_){copy.textContent='Copy unavailable';}});
    copy.addEventListener('keydown',event=>event.stopPropagation());
    const scroll=document.createElement('div');scroll.className='conversation-table-scroll';scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label','Markdown table; scroll horizontally for more columns');
    const table=document.createElement('table'),head=document.createElement('thead'),body=document.createElement('tbody');
    function row(values,header){const tr=document.createElement('tr');values.forEach((value,i)=>{const cell=document.createElement(header?'th':'td');fill(cell,value);cell.style.textAlign=block.align[i];if(header)cell.scope='col';tr.appendChild(cell);});return tr;}
    head.appendChild(row(block.header,true));for(const values of block.rows)body.appendChild(row(values,false));
    table.append(head,body);scroll.appendChild(table);container.append(copy,scroll);return container;
  }
  function render(text,host){
    const blocks=parse(text);
    if(!blocks.some(block=>block.kind==='table')){host.textContent='';return renderText(text,host);}
    for(const block of blocks){
      if(block.kind==='text'){const prose=document.createElement('span');renderText(block.text,prose);host.appendChild(prose);continue;}
      host.appendChild(tableNode(block));
    }
    return host;
  }

  /* A document view for a file preview: headings, paragraphs, lists, tables,
     code, quotes, rules and inline marks. Raw HTML stays visible text. An
     image is a text label and is never fetched. Only http(s) and mailto links
     are links (a new tab, no referrer); any other target is plain text.
     Every pattern runs in time linear in its line: a file of 128 KiB in one
     line must not hold the page (review r1 measured 35 s for a backtracking
     heading pattern). Lines longer than LONG_LINE are paragraphs. */
  const MAX_DEPTH=8,SPAN=2000,LONG_LINE=4096;
  const el=(tag,cls)=>{const node=document.createElement(tag);if(cls)node.className=cls;return node;};
  function safeUrl(value){
    try{const url=new URL(value);return ['http:','https:','mailto:'].includes(url.protocol)?url.href:null;}catch(_){return null;}
  }
  function anchor(href){
    const node=el('a');node.href=href;node.target='_blank';node.rel='noopener noreferrer';node.referrerPolicy='no-referrer';node.title=href;return node;
  }
  // Match the terminal addon's boundaries, allowing balanced () and [] in
  // paths. Japanese punctuation also ends a URL. Scan each candidate once;
  // overlong candidates stay text rather than becoming truncated links.
  const URL_END=/[\s"'!*{}|\\^<>`\u3001\u3002\uff0c\uff0e\uff01\uff1f\u300c-\u300f\uff08\uff09\u3010\u3011\u3008-\u300b]/;
  const URL_START=/https?:\/\//iy;
  function bareUrl(text,begin){
    if(/[a-z0-9]/i.test(text[begin-1]||'')||!at(URL_START,text,begin))return null;
    let end=URL_START.lastIndex,round=0,square=0;
    while(end<text.length&&!URL_END.test(text[end])){
      const ch=text[end];
      if(ch===')'&&!round||ch===']'&&!square)break;
      if(ch==='(')round++;else if(ch===')')round--;
      else if(ch==='[')square++;else if(ch===']')square--;
      end++;
    }
    let last=end;
    while(last>begin&&/[.,;:!?]/.test(text[last-1]))last--;
    return {end,last,href:last-begin<=SPAN?safeUrl(text.slice(begin,last)):null};
  }
  function renderText(text,host){
    const start=/https?:\/\//gi;let match,from=0;
    while((match=start.exec(text))){
      const begin=match.index,url=bareUrl(text,begin);if(!url)continue;
      const {end,last,href}=url;start.lastIndex=end;
      if(!href)continue;
      if(begin>from)host.appendChild(document.createTextNode(text.slice(from,begin)));
      const node=anchor(href);node.textContent=text.slice(begin,last);host.appendChild(node);from=last;
    }
    if(from<text.length)host.appendChild(document.createTextNode(text.slice(from)));
    return host;
  }
  const ESCAPE=/[\\`*_{}[\]()#+\-.!|~<>]/;
  // The part after a link's or an image's label: ](target "title")
  const TARGET=/\]\(([^()\s]{0,2000})(?:[ \t]+"[^"\n]{0,500}")?\)/y;
  const AUTOLINK=/<((?:https?:\/\/|mailto:)[^\s<>]{1,2000})>/iy;
  const STRONG=/(\*\*|__)(?=\S)([\s\S]{0,2000}?\S)\1/y;
  const STRIKE=/~~(?=\S)([\s\S]{0,2000}?\S)~~/y;
  const EMPHASIS=/([*_])(?=\S)([\s\S]{0,2000}?\S)\1/y;
  function at(pattern,text,i){pattern.lastIndex=i;return pattern.exec(text);}
  function inline(text,host,depth=0,inLink=false){
    let plain='';
    // Next `]`, next newline, the `]` whose target already failed, and the
    // next closing run per backtick count: each found once per position.
    let close=-2,newline=-2,failed=-1;const runs=new Map();
    const next=(cached,ch,from)=>cached>=from||cached===-1?cached:text.indexOf(ch,from);
    // A bracketed label from `from`: [label start, `]` index, target match].
    function bracket(from,max,empty){
      close=next(close,']',from);if(close===-1)return null;
      newline=next(newline,'\n',from);
      if(close-from>max||(!empty&&close===from)||(newline!==-1&&newline<close)||close===failed)return null;
      const target=at(TARGET,text,close);
      if(!target){failed=close;return null;}
      return {label:text.slice(from,close),target:target[1],end:close+target[0].length};
    }
    const flush=()=>{if(plain){host.appendChild(document.createTextNode(plain));plain='';}};
    const wrap=(tag,inner,cls)=>{flush();const node=el(tag,cls);if(depth<MAX_DEPTH)inline(inner,node,depth+1,inLink||tag==='a');else node.textContent=inner;host.appendChild(node);return node;};
    const image=(alt,target)=>{const label=el('span','markdown-image');label.textContent='[image'+(alt?': '+alt:'')+']';label.title=target;return label;};
    function link(target,fill){
      flush();const href=safeUrl(target),node=el(href?'a':'span',href?'':'markdown-link-text');
      if(href){node.href=href;node.target='_blank';node.rel='noopener noreferrer';node.referrerPolicy='no-referrer';node.title=href;}
      else if(target)node.title=target;
      fill(node);host.appendChild(node);
    }
    const label=text=>node=>{if(depth<MAX_DEPTH)inline(text,node,depth+1,true);else node.textContent=text;};
    for(let i=0;i<text.length;){
      const ch=text[i];let m;
      // A URL is one token before Markdown can consume its underscores or
      // tildes. Link labels keep the same token as text, never a nested link.
      if((ch==='h'||ch==='H')&&(m=bareUrl(text,i))){
        if(inLink||!m.href)plain+=text.slice(i,m.end);
        else{flush();const node=anchor(m.href);node.textContent=text.slice(i,m.last);host.appendChild(node);plain=text.slice(m.last,m.end);}
        i=m.end;continue;
      }
      if(ch==='\\'&&ESCAPE.test(text[i+1]||'')){plain+=text[i+1];i+=2;continue;}
      if(ch==='`'){
        let run=1;while(text[i+run]==='`')run++;
        let end=runs.get(run);
        if(end===undefined||(end!==-1&&end<i+run)){end=text.indexOf('`'.repeat(run),i+run);runs.set(run,end);}
        if(end>0&&end-i<=SPAN&&text[end+run]!=='`'){
          flush();const code=el('code'),value=text.slice(i+run,end).replace(/^ ([\s\S]*\S[\s\S]*) $/,'$1');if(inLink)code.textContent=value;else renderText(value,code);host.appendChild(code);i=end+run;continue;
        }
        plain+='`'.repeat(run);i+=run;continue;
      }
      if(ch==='!'&&text[i+1]==='['&&(m=bracket(i+2,500,true))){flush();host.appendChild(image(m.label,m.target));i=m.end;continue;}
      if(ch==='['&&!inLink){
        // A badge: [![alt](image)](link) is a link whose label is the image's.
        if(text[i+1]==='!'&&text[i+2]==='['){
          const inner=bracket(i+3,500,true),outer=inner&&text[inner.end]===']'?at(TARGET,text,inner.end):null;
          if(outer){link(outer[1],node=>node.appendChild(image(inner.label,inner.target)));i=inner.end+outer[0].length;continue;}
        }
        if((m=bracket(i+1,1000,false))){link(m.target,label(m.label));i=m.end;continue;}
      }
      if(ch==='<'&&!inLink&&(m=at(AUTOLINK,text,i))){link(m[1],label(m[1]));i+=m[0].length;continue;}
      if((ch==='*'||ch==='_')&&(m=at(STRONG,text,i))&&!(ch==='_'&&/\w/.test(text[i-1]||''))){wrap('strong',m[2]);i+=m[0].length;continue;}
      if(ch==='~'&&(m=at(STRIKE,text,i))){wrap('del',m[1]);i+=m[0].length;continue;}
      if((ch==='*'||ch==='_')&&(m=at(EMPHASIS,text,i))&&!(ch==='_'&&(/\w/.test(text[i-1]||'')||/\w/.test(text[i+m[0].length]||'')))){wrap('em',m[2]);i+=m[0].length;continue;}
      plain+=ch;i++;
    }
    flush();return host;
  }
  // Block patterns match a prefix; the rest of the line is cut with string
  // operations, never by a pattern that can backtrack over it.
  const FENCE=/^ {0,3}(`{3,}|~{3,})(.*)$/,HEADING=/^ {0,3}(#{1,6})(?=[ \t]|$)/;
  const RULE=/^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/,QUOTE=/^ {0,3}> ?/,ITEM=/^( {0,3})([-+*]|\d{1,9}[.)])([ \t]+|$)/;
  function fenceOf(line){
    const m=FENCE.exec(line);if(!m)return null;
    const info=m[2].trim();
    if(m[1][0]==='`'&&info.includes('`'))return null;
    return {mark:m[1],info,language:info.split(/[ \t]/)[0]};
  }
  function headingOf(line){
    const m=HEADING.exec(line);if(!m)return null;
    let text=line.slice(m[0].length).trim(),end=text.length;
    while(end&&text[end-1]==='#')end--;
    if(end===0)text='';else if(end<text.length&&(text[end-1]===' '||text[end-1]==='\t'))text=text.slice(0,end).trim();
    return {level:m[1].length,text};
  }
  const indentOf=line=>line.match(/^[ \t]*/)[0].replace(/\t/g,'    ').length;
  function dedent(line,width){let n=0,i=0;while(i<line.length&&n<width&&(line[i]===' '||line[i]==='\t')){n+=line[i]==='\t'?4:1;i++;}return line.slice(i);}
  function interrupts(line,next){
    if(line.length>LONG_LINE)return false;
    if(fenceOf(line)||HEADING.test(line)||RULE.test(line)||QUOTE.test(line))return true;
    const item=ITEM.exec(line);if(item&&line.slice(item[0].length).trim()&&(/^[-+*]$/.test(item[2])||/^1[.)]$/.test(item[2])))return true;
    return isDelimiter(cells(line),next===undefined||next.length>LONG_LINE?null:cells(next));
  }
  function codeBlock(text,cls='markdown-code'){const pre=el('pre',cls),code=el('code');renderText(text,code);pre.appendChild(code);return pre;}
  // `tight`: a list item without blank lines; its text needs no paragraph.
  function blocks(lines,host,depth,tight=false){
    for(let i=0;i<lines.length;){
      const line=lines[i];let m;
      if(!line.trim()){i++;continue;}
      if(depth>=MAX_DEPTH){host.appendChild(codeBlock(lines.slice(i).join('\n')));return;}
      const long=line.length>LONG_LINE;
      if(!long&&(m=fenceOf(line))){
        const body=[];i++;
        while(i<lines.length){
          const close=lines[i].length<=LONG_LINE?FENCE.exec(lines[i]):null;
          if(close&&close[1][0]===m.mark[0]&&close[1].length>=m.mark.length&&!close[2].trim()){i++;break;}
          body.push(lines[i++]);
        }
        const pre=codeBlock(body.join('\n'));if(m.language)pre.dataset.language=m.language.slice(0,40);host.appendChild(pre);continue;
      }
      if(!long&&(m=headingOf(line))){const heading=el('h'+m.level,'markdown-heading');inline(m.text,heading,depth);host.appendChild(heading);i++;continue;}
      if(!long&&RULE.test(line)){host.appendChild(el('hr'));i++;continue;}
      if(!long&&QUOTE.test(line)){
        const inner=[];
        while(i<lines.length&&lines[i].trim()&&(QUOTE.test(lines[i])||inner.length&&!interrupts(lines[i],lines[i+1])))inner.push(lines[i++].replace(QUOTE,''));
        const quote=el('blockquote');blocks(inner,quote,depth+1);host.appendChild(quote);continue;
      }
      if(!long&&(m=ITEM.exec(line))){
        const ordered=/\d/.test(m[2]),list=el(ordered?'ol':'ul'),base=m[1].length,kind=ordered?m[2].slice(-1):m[2];
        if(ordered&&Number(m[2].slice(0,-1))!==1)list.start=Number(m[2].slice(0,-1));
        while(i<lines.length){
          const head=ITEM.exec(lines[i]);
          if(!head||head[1].length>base+1||(ordered?head[2].slice(-1):head[2])!==kind)break;
          const width=lines[i].slice(head[0].length).trim()?head[0].length:head[1].length+head[2].length+1;
          const item=[lines[i].slice(head[0].length)];i++;
          while(i<lines.length){
            const next=lines[i];
            if(!next.trim()){
              let k=i;while(k<lines.length&&!lines[k].trim())k++;
              if(k<lines.length&&indentOf(lines[k])>=width){while(i<k){item.push('');i++;}continue;}
              break;
            }
            if(indentOf(next)>=width){item.push(dedent(next,width));i++;continue;}
            if(ITEM.test(next)||interrupts(next,lines[i+1]))break;
            item.push(next.trim());i++;   // a lazy continuation of the item's paragraph
          }
          const li=el('li'),task=/^\[([ xX])\][ \t]+/.exec(item[0]);
          if(task){
            item[0]=item[0].slice(task[0].length);li.className='markdown-task';li.dataset.checked=String(task[1]!==' ');
            const box=el('span','markdown-task-box');box.textContent=task[1]===' '?'☐ ':'☑ ';li.appendChild(box);
          }
          const loose=item.some((text,n)=>!text.trim()&&n<item.length-1);
          if(!loose&&!item.slice(1).some(text=>interrupts(text)||ITEM.test(text)||/^( {4}|\t)/.test(text)))inline(item.join('\n'),li,depth);
          else blocks(item,li,depth+1,!loose);
          list.appendChild(li);
          // Blank lines between items keep one list.
          let k=i;while(k<lines.length&&!lines[k].trim())k++;
          const again=k<lines.length?ITEM.exec(lines[k]):null;
          if(k>i&&again&&again[1].length<=base+1)i=k;else if(k>i)break;
        }
        host.appendChild(list);continue;
      }
      if(!long&&isDelimiter(cells(line),i+1<lines.length&&lines[i+1].length<=LONG_LINE?cells(lines[i+1]):null)){
        const header=cells(line),align=cells(lines[i+1]).map(alignOf),rows=[],start=i;i+=2;
        while(i<lines.length&&lines[i].trim()&&!interrupts(lines[i])&&rows.length<500){
          const row=cells(lines[i]);if(!row)break;
          rows.push(header.map((_,n)=>row[n]??''));i++;
        }
        host.appendChild(tableNode({header,rows,align,raw:lines.slice(start,i).join('\n')+'\n'},(cell,value)=>inline(value,cell,depth)));continue;
      }
      if(!long&&/^( {4}|\t)/.test(line)){
        const body=[];
        while(i<lines.length&&(/^( {4}|\t)/.test(lines[i])||!lines[i].trim()))body.push(dedent(lines[i++],4));
        while(body.length&&!body[body.length-1].trim())body.pop();
        host.appendChild(codeBlock(body.join('\n')));continue;
      }
      const paragraph=[line.trim()];i++;
      while(i<lines.length&&lines[i].trim()&&!interrupts(lines[i],lines[i+1]))paragraph.push(lines[i++].trim());
      if(tight)inline(paragraph.join('\n'),host,depth);
      else{const p=el('p');inline(paragraph.join('\n'),p,depth);host.appendChild(p);}
    }
  }
  function renderDocument(text,host){
    const lines=String(text).replace(/\r\n?/g,'\n').split('\n');let start=0;
    // YAML front matter (Obsidian notes) stays as text at the top.
    if(lines[0]==='---'){
      const close=lines.indexOf('---',1);
      if(close>0&&close<=200){host.appendChild(codeBlock(lines.slice(0,close+1).join('\n'),'markdown-code markdown-front-matter'));start=close+1;}
    }
    blocks(lines.slice(start),host,0);
    return host;
  }
  root.OrreryConversationMarkdown=Object.freeze({parse,render,renderDocument,renderText});
})(typeof window==='undefined'?globalThis:window);
