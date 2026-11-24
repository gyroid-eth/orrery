/* View-only native status from the already delivered terminal screen. No I/O. */
(function(root){
  'use strict';
  const codexPrompt=/^\s*›(?:\s|$)/u;
  const codexFooter=/^(?:gpt-\S+\s+(?:default|low|medium|high|xhigh|max|ultra)\b|\? for shortcuts\b|(?:Context\s+)?\d{1,3}%?\s+context left\b|Context\s+\d{1,3}%\s+(?:left|used)\b)/i;
  function compaction(text,program){
    if(program!=='codex'||typeof text!=='string'||text.length>65536)return null;
    const rows=text.split('\n').slice(-40).map(row=>row.trimEnd());
    let prompt=-1;
    for(let i=rows.length-1;i>=0;i--)if(codexPrompt.test(rows[i])){prompt=i;break;}
    if(prompt<0)return null;
    const footer=rows.slice(prompt+1).map(row=>row.trim()).filter(Boolean);
    if(!footer.some(row=>codexFooter.test(row)))return null;
    const block=rows.slice(Math.max(0,prompt-5),prompt).map(row=>row.trim()).filter(Boolean);
    if(block.at(-1)==='Making room to continue.')block.pop();
    // Codex 0.163.0 COMPACTION_HEADER and its timed native status widget.
    // Only the adjacent current control block counts; a later reply clears it.
    for(let width=1;width<=Math.min(3,block.length);width++){
      const match=/^[•▌●]\s+Compacting context\s*\(((?:\d{1,4}h\s*)?(?:\d{1,3}m\s*)?\d{1,2}s)\s*[•·]\s*esc to interrupt\)$/u.exec(block.slice(-width).join(' '));
      if(match)return {reader_phase:'compacting',reader_phase_elapsed:match[1].replace(/\s+/g,' ')};
    }
    return null;
  }
  const claudeMarker=/^[●⏺](?: |$)/u;
  const markers={claude:claudeMarker,'claude-code':claudeMarker,codex:/^•(?: |$)/u,dsh:/^ {0,3}[●⏺](?: |$)/u};
  const divider=/^\s*[─━═]{8,}\s*$/u;
  const dshPromptTop=/^\s*╭─{8,}.*╮$/u,dshPromptBottom=/^\s*╰─{8,}╯$/u;
  const codexStatus=/^[•▌●]\s+.*\(.*\besc to interrupt\)$/u;
  const codexTool=/^(?:Ran|Running|Called|Calling|Explored|Exploring|Searched|Searching|Applied|Edited|Updated Plan|Waiting for)\b/u;
  const claudeStatus=/^(?:[✢✳✶✻✽·] [^…]+…(?: \(.*)?|\s+● \S+ · \/effort)$/u;
  const claudeTool=/^(?:Thinking for \d|Thought for \d|Reading \S|Read \d+ files?\b|(?:Bash|Read|Write|Edit|Grep|Glob|WebFetch|WebSearch)\()/u;
  const dshStatus=/^\s*(?:[·•●]\s+[^()]+…\s+\(\d+[hms].*\)|\S\s+.+· ↓ [\d.,]+[kKmM]? tokens(?: · .*)?)$/u;
  const unsafeBody=/^(?:\s*[│┃┆┊╭╰┌└├┏┗⎿]|\s*`{3,}|\s*~{3,}|\s*<(?:think|thinking|analysis|reasoning)\b|\s*(?:Thinking|Reasoning|Analysis)(?:\s*[:·…]|\s*\(|\s*$))/iu;
  const minText=12,maxText=4096;
  function publicBody(row,start,{plainStart=false}={}){
    const cell=row.line.getCell(start);
    if(!cell||!cell.getChars().trim()||cell.isDim()||cell.isItalic()||cell.isInverse()||cell.isInvisible())return false;
    if(plainStart&&cell.isBold())return false;
    for(let i=start;i<row.line.length;i++){
      const char=row.line.getCell(i);
      if(char?.getChars().trim()&&(char.isDim()||char.isInvisible()||char.isInverse()))return false;
    }
    return true;
  }
  function bulletTail(rows,program){
    const codex=program==='codex',dsh=program==='dsh';
    const promptMarker=dsh?dshPromptTop:codex?codexPrompt:/^\s*[❯›>](?:\s|$)/u;
    const prompt=rows.findLastIndex(({text})=>promptMarker.test(text));
    if(prompt<0||rows.length-prompt>9)return null;
    if(codex&&!rows.slice(prompt+1).some(row=>codexFooter.test(row.text.trim())))return null;
    if(dsh&&(!/^\s*(?:⌸\s+)?❯(?:\s|$)/u.test(rows[prompt+1]?.text||'')||
      !rows.slice(prompt+2).some(row=>dshPromptBottom.test(row.text))))return null;
    if(!dsh&&!codex&&!rows.slice(Math.max(0,prompt-2),prompt+3).some(row=>divider.test(row.text)))return null;
    let end=prompt-1;
    const status=codex?codexStatus:dsh?dshStatus:claudeStatus;
    while(end>=0&&(!rows[end].text.trim()||divider.test(rows[end].text)||status.test(rows[end].text)))end--;
    // These TUIs insert hard line breaks for layout. With no record, the
    // second row can be wrapped prose, a new block, or a tool's first line.
    const head=rows[end];
    const prefix=head&&markers[program].exec(head.text)?.[0];
    if(!prefix)return null;
    const text=head.text.slice(prefix.length).trimEnd();
    if(text&&!publicBody(head,prefix.length,{plainStart:true}))return null;
    const glyph=head.line.getCell(prefix.search(/\S/u));
    if(head.line.isWrapped||unsafeBody.test(text)||codex&&(!glyph.isDim()||codexTool.test(text)))return null;
    if(!codex&&text){
      const body=head.line.getCell(prefix.length);
      // Claude colors its public bullet white (dark palette) or black
      // (light palette). Tool and thinking bullets use other colors.
      if(dsh&&!body.isFgDefault()&&glyph.getFgColor()!==body.getFgColor())return null;
      if(!dsh&&(![0x000000,0xffffff].includes(glyph.getFgColor())||!glyph.isFgRGB()||!body.isFgDefault()||claudeTool.test(text)))return null;
    }
    return {row:head.index,text,first:text};
  }
  function hermesInkTail(rows){
    const prompt=rows.findLastIndex(({text})=>/^\s*☤\s+❯(?:\s|$)/u.test(text));
    if(prompt<2||!divider.test(rows[prompt-1].text)||!divider.test(rows[prompt+1]?.text||''))return null;
    const status=rows[prompt-2].text;
    if(!/^\s*☤\s+\S.*│/u.test(status))return null;
    let end=prompt-3;
    while(end>=0&&!rows[end].text.trim())end--;
    const head=rows[end],prefix=head&&/^\s*┊ {2}/u.exec(head.text)?.[0];
    if(!prefix||head.line.isWrapped)return null;
    const text=head.text.slice(prefix.length);
    if(unsafeBody.test(text)||!publicBody(head,prefix.length,{plainStart:true}))return null;
    return {row:head.index,text,first:text};
  }
  function hermesTail(rows){
    const start=rows.findLastIndex(({text})=>/^╭─ ?☤ Hermes ?(?:\d{1,2}:\d{2}(?::\d{2})?(?: [AP]M)? *)?─*╮$/u.test(text));
    if(start<0)return null;
    const body=[];let color=null,blank=0;
    for(const row of rows.slice(start+1)){
      const text=row.text;
      if(/^╰─+╯$/u.test(text))break;
      if(!text){blank++;continue;}
      const cell=row.line.getCell(0),foreground=cell?.getFgColor();
      if(blank&&(!cell?.isFgRGB()||foreground!==color))break;
      if(row.line.isWrapped||unsafeBody.test(text)||!cell?.isFgRGB()||!publicBody(row,0)||color!==null&&foreground!==color)return null;
      body.push(...Array(blank).fill(''),text);color=foreground;blank=0;
    }
    return {row:rows[start].index,text:body.join('\n'),first:body[0]};
  }
  function liveText(rows,program){
    const tail=rows.findLastIndex(row=>row.text.trim());
    rows=rows.slice(0,tail+1);
    const candidate=program==='hermes'?(hermesInkTail(rows)||hermesTail(rows)):
      Object.hasOwn(markers,program)?bulletTail(rows,program):null;
    if(!candidate||candidate.text.length>maxText)return null;
    if(candidate.text.length<minText)return candidate;
    const repeats=rows.filter(row=>row.text.includes(candidate.first)).length;
    return repeats>1?null:candidate;
  }
  function advanceLiveText(previous,candidate){
    if(!candidate)return previous?.text.length>=minText?{...previous,missing:true,confirmed:false}:null;
    if(previous?.missing){
      const repeated=candidate.text.length>=minText&&
        (candidate.text.startsWith(previous.text)||previous.text.startsWith(candidate.text));
      return {...candidate,confirmed:false,blocked:repeated};
    }
    if(!previous||previous.row!==candidate.row)return {...candidate,confirmed:false,blocked:previous?.text===candidate.text};
    if(previous.blocked||candidate.text===previous.text)return previous;
    if(!candidate.text.startsWith(previous.text))return {...candidate,blocked:true,confirmed:false};
    return {...candidate,confirmed:true,id:previous.id,at:previous.at};
  }
  function mount({getPanes,getProgram,getBinding=()=>''}){
    const rows=new Map(),pending=new Set();let frame=0;
    let liveSerial=0;
    function changed(){root.document.dispatchEvent(new CustomEvent('oc:reader-activity'));}
    function sample(pane){
      if(!pane.host.isConnected||pane.host.dataset.snapshot==='pending')return;
      const {term,host}=pane,buffer=term.buffer.active,lines=[];
      const end=Math.min(buffer.length,buffer.baseY+term.rows);
      for(let index=Math.max(0,end-40);index<end;index++){
        const line=buffer.getLine(index);if(line)lines.push({index,line,text:line.translateToString(true)});
      }
      const text=lines.map(row=>row.text).join('\n'),program=getProgram(pane),old=rows.get(pane);
      const phase=old?.text===text&&old.program===program?old.phase:compaction(text,program);
      const binding=getBinding(pane),epoch=host.dataset.snapshotEpoch;
      const key=JSON.stringify([program,binding,epoch,term.cols,term.rows,buffer.type]);
      const candidate=liveText(lines,program);
      const track=advanceLiveText(old?.key===key?old.track:null,candidate);
      if(track&&!track.id){track.id=++liveSerial;track.at=new Date().toISOString();}
      const live=track?.confirmed&&!track.blocked&&track.text.length>=minText?{text:track.text,id:track.id,at:track.at}:null;
      rows.set(pane,{text,program,key,phase,track,live,binding,epoch});
      return JSON.stringify(old?.phase||null)!==JSON.stringify(phase)||old?.live?.id!==live?.id||old?.live?.text!==live?.text;
    }
    function flush(){
      frame=0;let dirty=false;
      for(const pane of pending)dirty=sample(pane)||dirty;
      pending.clear();for(const pane of rows.keys())if(!pane.host.isConnected)rows.delete(pane);
      if(dirty)changed();
    }
    function observe(pane){if(!pane)return;pending.add(pane);if(!frame)frame=root.setTimeout(flush,16);}
    function disconnected(){root.clearTimeout(frame);frame=0;pending.clear();rows.clear();changed();}
    for(const pane of getPanes())observe(pane);
    return Object.freeze({observe,current:pane=>{const row=rows.get(pane);
      return row&&row.program===getProgram(pane)&&row.binding===getBinding(pane)&&
        row.epoch===pane.host.dataset.snapshotEpoch&&pane.host.dataset.snapshot!=='pending'?
        {...row.phase,...row.live&&{reader_live_text:row.live}}:{};},disconnected});
  }
  root.OrreryReaderActivity=Object.freeze({compaction,mount});
  if(typeof module!=='undefined')module.exports={compaction,liveText,advanceLiveText};
})(typeof window==='undefined'?globalThis:window);
