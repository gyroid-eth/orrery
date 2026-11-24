/* Demo mode: hide the user name and the machine name on screen only.

   What is hidden: the user name where it is part of a home path
   (/Users/<name>, /home/<name>, C:\Users\<name>), the user name right before
   an "@" (a shell prompt's user@host), and the host name as a whole word. The
   names come from the backend (GET /telemetry/identity), never from guessing.
   A name that only appears inside another word ("admiral" for a user called
   "mira") is left alone.

   The user can add words to hide (identity.words: a person's name written in
   Mail, a project name). A word of Latin letters and digits is hidden as a
   whole word, in any letter case ("Mira" in "Ask Mira", not in "Miranda").
   A word with any other character (Japanese has no spaces between words) is
   hidden wherever it appears.

   Names use one mask character of the same width ("*" for narrow characters,
   "＊" for wide ones). The optional location mask uses fixed labels. In a
   terminal, those labels occupy the original cells so links still line up.

   The masked text is never turned back into a name by its shape (two names
   of the same length look alike, and a user can type "****" too): callers
   keep the original where they mask it. A terminal is masked where xterm
   draws it, and its buffer stays real (see demo_mode.js).

   Escape sequences are skipped when matching (a colour change inside a name
   does not hide it); every sequence other than a colour change counts as a
   word break. Nothing here changes data: callers mask only what they display. */
(function(root){
  'use strict';

  const NARROW_MASK='*',WIDE_MASK='\uFF0A';
  const NAME_CHAR=/[A-Za-z0-9._-]/,HOST_CHAR=/[A-Za-z0-9-]/,WORD_CHAR=/[A-Za-z0-9_]/;
  const LATIN_WORD=/^[A-Za-z0-9_][A-Za-z0-9_ .'-]*$/;
  const LOCATION=/(^|[\s([{=,:;<>"'`|])([a-z][a-z0-9+.-]*:\/\/|(?:data|mailto|blob|tel|urn|magnet):|www\.|[a-z]:[\\/]|(?:~|\.\.?)\/|\\\\|\/+)/gi;
  const MARKER={url:'[URL]',path:'[path]'};
  const TERMINAL_MARKER={url:'<>',path:'[]'};

  // East Asian Wide / Fullwidth ranges, enough for names and host names.
  function isWide(cp){
    return (cp>=0x1100&&cp<=0x115F)||(cp>=0x2E80&&cp<=0x303E)||(cp>=0x3041&&cp<=0x33FF)||
      (cp>=0x3400&&cp<=0x4DBF)||(cp>=0x4E00&&cp<=0x9FFF)||(cp>=0xA000&&cp<=0xA4CF)||
      (cp>=0xAC00&&cp<=0xD7A3)||(cp>=0xF900&&cp<=0xFAFF)||(cp>=0xFE30&&cp<=0xFE4F)||
      (cp>=0xFF00&&cp<=0xFF60)||(cp>=0xFFE0&&cp<=0xFFE6)||(cp>=0x20000&&cp<=0x3FFFD);
  }
  // One mask character per UTF-16 unit keeps String.length (DOM offsets and
  // the terminal's character count) unchanged.
  function maskUnit(unit){return isWide(unit.charCodeAt(0))?WIDE_MASK:NARROW_MASK;}
  function maskName(text){let out='';for(let i=0;i<text.length;i++)out+=maskUnit(text[i]);return out;}
  // Columns a shown text takes; separators ('\n', from controls and cursor
  // moves) take none.
  function columns(text){let n=0;for(const ch of text)if(ch!=='\n')n+=isWide(ch.codePointAt(0))?2:1;return n;}
  function unique(list){
    const seen=new Set(),out=[];
    for(const item of list){
      const value=typeof item==='string'?item.trim():'';
      if(value.length<2||seen.has(value.toLowerCase()))continue;
      seen.add(value.toLowerCase());out.push(value);
    }
    // Longer names first, so "mira" does not hide half of "mira-studio".
    return out.sort((a,b)=>b.length-a.length);
  }

  /* Split terminal output into what is shown and what is not: the shown
     characters with the raw index of each, and, when the text ends in the
     middle of an escape sequence, where that sequence starts. Control
     characters count as separators (they end a word), and so does every
     escape sequence except a colour change (SGR, "ESC[...m"): a program that
     repaints its screen (tmux does) moves the cursor between rows instead of
     writing a line break, and the rows must not run together into one word.
     A separator is recorded as '\n' at the escape's own raw index; it is
     never part of a name, so it is never masked. */
  function scan(raw){
    const shown=[],at=[];let incomplete=-1,i=0;
    while(i<raw.length){
      const ch=raw.charCodeAt(i);
      if(ch===0x1b){
        const start=i,next=raw[i+1];
        if(next===undefined){incomplete=start;break;}
        if(next==='['){
          let j=i+2;
          while(j<raw.length&&!(raw.charCodeAt(j)>=0x40&&raw.charCodeAt(j)<=0x7e))j++;
          if(j>=raw.length){incomplete=start;break;}
          if(raw[j]!=='m'){shown.push('\n');at.push(start);}
          i=j+1;continue;
        }
        if(next===']'||next==='P'||next==='_'||next==='^'||next==='X'){
          let j=i+2,done=false;
          while(j<raw.length){
            if(raw[j]==='\x07'){j++;done=true;break;}
            if(raw[j]==='\x1b'&&raw[j+1]==='\\'){j+=2;done=true;break;}
            j++;
          }
          if(!done){incomplete=start;break;}
          shown.push('\n');at.push(start);
          i=j;continue;
        }
        if('()*+#%'.includes(next)){
          if(i+2>=raw.length){incomplete=start;break;}
          i+=3;continue;
        }
        shown.push('\n');at.push(start);
        i+=2;continue;
      }
      shown.push(ch<0x20||ch===0x7f?'\n':raw[i]);at.push(i);
      i++;
    }
    return {text:shown.join(''),at,incomplete};
  }

  function pathWithSpacesEnd(text,end){
    // A later directory separator or filename suffix can identify spaces in
    // a bare path. Stop before an independent location or shell delimiter.
    const word=/ +([^\s<>"'`|;&]+)/y;
    let last=end;
    for(let count=0;count<16;count++){
      word.lastIndex=end;
      const next=word.exec(text);
      if(!next||/^(?:[a-z][a-z0-9+.-]*:\/\/|[a-z]:[\\/]|[~\/\\]|www\.)/i.test(next[1]))break;
      if(/[\\/]|\.[a-z0-9]{1,12}(?:[.,!?]|$)/i.test(next[1]))last=word.lastIndex;
      end=word.lastIndex;
    }
    return last;
  }

  function locationSpans(text){
    const found=[];
    LOCATION.lastIndex=0;
    for(let match;(match=LOCATION.exec(text));){
      const start=match.index+match[1].length,prefix=match[2],before=match[1];
      const kind=/^[a-z][a-z0-9+.-]*:\/\/|^(?:data|mailto|blob|tel|urn|magnet):|^www\./i.test(prefix)
        &&!/^file:/i.test(prefix)?'url':'path';
      let end=LOCATION.lastIndex;
      const closing=({'<':'>','"':'"',"'":"'",'`':'`'})[before];
      if(closing){
        // Quoted file names and Markdown destinations can contain spaces.
        const quoted=text.indexOf(closing,end);
        const newline=text.indexOf('\n',end);
        if(quoted>=0&&(newline<0||quoted<newline))end=quoted;
      }
      if(end===LOCATION.lastIndex){
        const open={'(':0,'[':0,'{':0},pairs={')':'(',']':'[','}':'{'};
        while(end<text.length){
          const ch=text[end];
          if(kind==='path'&&ch==='\\'&&text[end+1]===' '){end+=2;continue;}
          if(/[\s<>"'`|]/.test(ch))break;
          if(ch in open)open[ch]++;
          if(ch in pairs&&--open[pairs[ch]]<0)break;
          end++;
        }
        if(kind==='path'&&prefix.length+start<end)end=pathWithSpacesEnd(text,end);
        while(end>LOCATION.lastIndex&&/[.,;!?]/.test(text[end-1]))end--;
      }
      if(end===LOCATION.lastIndex&&prefix==='/')continue;
      if(before==='<'&&/^\/[a-z][\w-]*$/i.test(text.slice(start,end))&&text[end]==='>')continue;
      found.push([start,end,kind]);
      LOCATION.lastIndex=end;
    }
    return found;
  }

  function create(identity){
    const users=unique((identity&&identity.users)||[]);
    const hosts=unique((identity&&identity.hosts)||[]);
    const words=unique((identity&&identity.words)||[]);
    const hideLocations=identity?.hideLocations===true;
    const lowerUsers=users.map(u=>u.toLowerCase()),lowerHosts=hosts.map(h=>h.toLowerCase());
    // [lowercase word, whole-word only]
    const lowerWords=words.map(w=>[w.toLowerCase(),LATIN_WORD.test(w)]);
    const LEADS=['/users/','/home/','\\users\\','\\home\\'];
    // Every string a match can start with, and which part of it is the name.
    const needles=[];
    for(const user of lowerUsers){
      for(const lead of LEADS)needles.push({text:lead+user,from:lead.length,to:lead.length+user.length});
      needles.push({text:user+'@',from:0,to:user.length,before:NAME_CHAR});
    }
    for(const host of lowerHosts)needles.push({text:host,from:0,to:host.length,before:HOST_CHAR});
    for(const [word,whole] of lowerWords)needles.push({text:word,from:0,to:word.length,before:whole?WORD_CHAR:null});

    /* Location ranges take precedence over names inside the same text. */
    function spans(text,{literalPath,wholePath,streaming}={}){
      const lower=text.toLowerCase(),found=hideLocations?locationSpans(text):[];
      if(hideLocations&&wholePath&&text)return [[0,text.length,'path']];
      if(hideLocations&&literalPath){
        const start=text.lastIndexOf(literalPath),end=start+literalPath.length;
        if(start>=0){
          for(let i=found.length-1;i>=0;i--)if(found[i][0]<end&&found[i][1]>start)found.splice(i,1);
          found.push([start,end,'path']);
        }
      }
      const take=(start,end)=>{
        if(found.some(([a,b])=>start<b&&end>a))return;
        found.push([start,end,null]);
      };
      const each=(needle,fn)=>{for(let at=lower.indexOf(needle);at>=0;at=lower.indexOf(needle,at+1))fn(at);};
      for(const user of lowerUsers){
        for(const lead of LEADS)each(lead+user,at=>{
          const after=text[at+lead.length+user.length];
          if(after===undefined||!NAME_CHAR.test(after))take(at+lead.length,at+lead.length+user.length);
        });
        each(user+'@',at=>{
          const before=text[at-1];
          if(before===undefined||!NAME_CHAR.test(before))take(at,at+user.length);
        });
      }
      for(const host of lowerHosts)each(host,at=>{
        const before=text[at-1],after=text[at+host.length];
        if((before===undefined||!HOST_CHAR.test(before))&&(after===undefined||!HOST_CHAR.test(after)))
          take(at,at+host.length);
      });
      for(const [word,whole] of lowerWords)each(word,at=>{
        if(whole){
          const before=text[at-1],after=text[at+word.length];
          if(before!==undefined&&WORD_CHAR.test(before))return;
          if(after!==undefined&&WORD_CHAR.test(after))return;
        }
        take(at,at+word.length);
      });
      // A streaming sample can stop in the middle of a known name. Mask its
      // possible continuation now and resolve it again with the next sample.
      if(streaming)for(const needle of needles){
        for(let length=Math.min(lower.length,needle.text.length-1);length>needle.from;length--){
          const start=lower.length-length,previous=text[start-1];
          if(needle.before&&previous!==undefined&&needle.before.test(previous))continue;
          if(!lower.endsWith(needle.text.slice(0,length)))continue;
          take(start+needle.from,lower.length);break;
        }
      }
      return found.sort((a,b)=>a[0]-b[0]);
    }

    /* DOM ranges shrink to a fixed label. Keep their position map for copy. */
    function project(text,options){
      if(typeof text!=='string'||!text||!needles.length&&!hideLocations)return {text,ranges:[]};
      const view=scan(text);
      const ranges=[];let out='',cursor=0;
      for(const [a,b,kind] of spans(view.text,options)){
        const from=view.at[a],to=view.at[b-1]+1;
        out+=text.slice(cursor,from);
        if(kind){
          const start=out.length;
          out+=MARKER[kind];ranges.push({from,to,start,end:out.length});
        }else{
          let at=from;
          for(let k=a;k<b;k++){
            const index=view.at[k];out+=text.slice(at,index)+maskUnit(text[index]);at=index+1;
          }
        }
        cursor=to;
      }
      return {text:out+text.slice(cursor),ranges};
    }

    /* The terminal keeps original columns for xterm links, selection and
       cursor positioning. Only the two marker cells are visibly filled. */
    function terminal(text){
      if(!hideLocations)return project(text).text;
      const view=scan(text),out=text.split('');
      for(const [a,b,kind] of spans(view.text)){
        for(let k=a;k<b;k++){
          const at=view.at[k],unit=text[at];
          out[at]=kind?TERMINAL_MARKER[kind][k-a]||(isWide(unit.charCodeAt(0))?'\u3000':' '):maskUnit(unit);
        }
      }
      return out.join('');
    }

    return {active:users.length+hosts.length>0,users,hosts,words,mask:text=>project(text).text,
      project,terminal,maskName,columns,scan};
  }

  function originalOffset(offset,ranges,end=false){
    let delta=0;
    for(const range of ranges){
      if(offset<range.start)break;
      if(offset===range.start)return range.from;
      if(offset<range.end)return end?range.to:range.from;
      delta=range.to-range.end;
    }
    return offset+delta;
  }

  const api={create,maskName,originalOffset};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.OrreryDemoMask=api;
})(typeof window!=='undefined'?window:globalThis);
