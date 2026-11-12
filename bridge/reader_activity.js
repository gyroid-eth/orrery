/* View-only native status from the already delivered terminal screen. No I/O. */
(function(root){
  'use strict';
  function compaction(text,program){
    if(program!=='codex'||typeof text!=='string'||text.length>65536)return null;
    const rows=text.split('\n').slice(-40).map(row=>row.trimEnd());
    let prompt=-1;
    for(let i=rows.length-1;i>=0;i--)if(/^\s*›(?:\s|$)/u.test(rows[i])){prompt=i;break;}
    if(prompt<0)return null;
    const footer=rows.slice(prompt+1).map(row=>row.trim()).filter(Boolean);
    if(!footer.some(row=>/^(?:gpt-\S+\s+(?:default|low|medium|high|xhigh|max|ultra)\b|\? for shortcuts\b|(?:Context\s+)?\d{1,3}%?\s+context left\b|Context\s+\d{1,3}%\s+(?:left|used)\b)/i.test(row)))return null;
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
  function mount({getPanes,getProgram}){
    const rows=new Map(),pending=new Set();let frame=0;
    function changed(){root.document.dispatchEvent(new CustomEvent('oc:reader-activity'));}
    function sample(pane){
      if(!pane.host.isConnected||pane.host.dataset.snapshot==='pending')return;
      const buffer=pane.term.buffer.active,lines=[];
      for(let i=Math.max(buffer.baseY,buffer.length-40);i<Math.min(buffer.length,buffer.baseY+pane.term.rows);i++)lines.push(buffer.getLine(i)?.translateToString(true)||'');
      const text=lines.join('\n'),program=getProgram(pane),old=rows.get(pane);
      if(old?.text===text&&old.program===program)return;
      const value=compaction(text,program);
      rows.set(pane,{text,program,value});
      return JSON.stringify(old?.value||null)!==JSON.stringify(value);
    }
    function flush(){
      frame=0;let dirty=false;
      for(const pane of pending)dirty=sample(pane)||dirty;
      pending.clear();for(const pane of rows.keys())if(!pane.host.isConnected)rows.delete(pane);
      if(dirty)changed();
    }
    function observe(pane){if(!pane)return;pending.add(pane);if(!frame)frame=root.requestAnimationFrame(flush);}
    function disconnected(){root.cancelAnimationFrame(frame);frame=0;pending.clear();rows.clear();changed();}
    for(const pane of getPanes())observe(pane);
    return Object.freeze({observe,current:pane=>{const row=rows.get(pane);
      return row&&row.program===getProgram(pane)&&pane.host.dataset.snapshot!=='pending'?row.value||{}:{};},disconnected});
  }
  root.OrreryReaderActivity=Object.freeze({compaction,mount});
  if(typeof module!=='undefined')module.exports={compaction};
})(typeof window==='undefined'?globalThis:window);
