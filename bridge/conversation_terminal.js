/* Search the currently retained xterm buffer, never tmux/provider input.
   The caller owns pane identity, visibility and follow/claim presentation. */
(function(root){
  'use strict';
  const MAX_ROWS=6500,MAX_CHARS=2*1024*1024,MAX_MATCHES=20;
  const normalize=text=>text.replace(/\s+/g,' ').trim();
  function find(buffer,text,{alternate=false}={}){
    if(!buffer||typeof text!=='string'||!text.trim())return {state:'not_retained',count:0};
    if(alternate&&buffer.type!=='alternate')return {state:'alternate',count:0};
    if(text.length>65536)return {state:'limited',count:0};
    const query=normalize(text);
    if(!query)return {state:'not_retained',count:0};
    const rows=[];let size=0,complete=buffer.length<=MAX_ROWS;
    for(let i=buffer.length-1;i>=Math.max(0,buffer.length-MAX_ROWS);i--){
      const line=buffer.getLine(i);if(!line){complete=false;continue;}
      const wrapped=Boolean(buffer.getLine(i+1)?.isWrapped);
      const value=line.translateToString(!wrapped).replace(/\s+/g,' ');
      if(size+value.length+1>MAX_CHARS){complete=false;break;}
      rows.push({row:i,value,wrapped});size+=value.length+1;
    }
    // A partial search cannot establish uniqueness in the retained buffer.
    if(!complete)return {state:'limited',count:0};
    rows.reverse();let content='';const offsets=[];
    for(const line of rows){
      let value=line.value;
      if(content.endsWith(' ')&&value.startsWith(' '))value=value.slice(1);
      offsets.push({offset:content.length,row:line.row});content+=value;
      if(!line.wrapped&&!content.endsWith(' '))content+=' ';
    }
    const matches=[];let from=0;
    const word=char=>Boolean(char&&/[\p{L}\p{N}_-]/u.test(char));
    while(matches.length<MAX_MATCHES){
      const offset=content.indexOf(query,from);if(offset<0)break;
      from=offset+1;
      // Short words must not match inside a longer identifier or sentence token.
      if(query.length<12&&(word(query[0])&&word(content[offset-1])||word(query.at(-1))&&word(content[offset+query.length])))continue;
      matches.push(offset);
    }
    if(!matches.length)return {state:alternate||buffer.type==='alternate'?'alternate':'not_retained',count:0};
    if(matches.length>1)return {state:'multiple',count:matches.length,limited:matches.length===MAX_MATCHES};
    const rowAt=offset=>{let lo=0,hi=offsets.length;while(lo<hi){const mid=(lo+hi)>>1;if(offsets[mid].offset<=offset)lo=mid+1;else hi=mid;}return offsets[Math.max(0,lo-1)].row;};
    return {state:'unique',count:1,line:rowAt(matches[0]),endLine:rowAt(matches[0]+query.length-1)};
  }
  root.OrreryConversationTerminal=Object.freeze({find});
  if(typeof module!=='undefined')module.exports={find};
})(typeof window==='undefined'?globalThis:window);
