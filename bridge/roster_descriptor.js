(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.RosterDescriptor=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const SPECIFIC_SIGNAL_THRESHOLD=4;
  const MIN_AGENT_NAME_STRIP_CHARS=4;
  const RELAY_ENGLISH=[
    'read and execute','task execution','parent-agent','mcp agent mail',
    'canonical','inbox','awaiting','execute','execution','read','task',
    'delivered','received','delegated','assigned','parent','agent','mail',
    'under','from','via','for','by','the','in','of','and','it',
  ];
  const RELAY_JAPANESE=[
    '親エージェント','正本タスク','委任された','実行する','対応する','受け渡し',
    'からの','親側','正本','タスク','依頼','受信','届いた','届く','経由','委任',
    '実行','対応','待機','本人','から','への','親','へ','の','を','で',
  ];
  const SESSION_PATH_RE=/(?:^|\s)(?:codex|claude(?: code)?)\s+session\s+in\s+(?:\/|~)\S*/giu;
  const ABSOLUTE_PATH_RE=/(?:\/users|\/home|\/tmp|\/private)\/\S*/giu;
  const COORDINATION_TICKET_RE=/(^|[^\p{L}\p{N}_])(?:pr|ticket|issue)-[a-z0-9_-]+(?=$|[^\p{L}\p{N}_])/giu;
  const GLYPH_STRIP=/^[\s⠀-⣿✀-➿·•∗*●○◇◆⏎>~–—-]+/u;
  const ELAPSED_COUNTER_RE=/(?:^|\s)\d+(?:\.\d+)?(?:ms|s|m|h|d)(?=$|\s)/giu;
  const BARE_LOCATION_RE=/^(?:[a-z0-9._~-]+\/)*[a-z0-9._~-]+$/iu;

  function escapeRegExp(value){
    return String(value).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  }

  function knownAgentNames(agents){
    return [...new Set((Array.isArray(agents)?agents:[])
      .map(agent=>String(agent&&agent.name||'').trim().toLocaleLowerCase())
      .filter(name=>name.length>=MIN_AGENT_NAME_STRIP_CHARS))]
      .sort((a,b)=>b.length-a.length);
  }

  function stripEnglishWord(text,word){
    const escaped=escapeRegExp(word);
    const pattern=new RegExp(`(^|[^\\p{L}\\p{N}_])${escaped}(?=$|[^\\p{L}\\p{N}_])`,'giu');
    return text.replace(pattern,'$1 ');
  }

  function classify(text,names=[]){
    const source=String(text||'').normalize('NFKC').trim();
    if(!source)return {quality:'missing',residue:'',signal_chars:0};

    let residue=source.toLocaleLowerCase();
    residue=residue.replace(SESSION_PATH_RE,' ');
    residue=residue.replace(ABSOLUTE_PATH_RE,' ');
    for(const name of names){
      residue=residue.replace(new RegExp(escapeRegExp(name),'giu'),' ');
    }
    residue=residue.replace(COORDINATION_TICKET_RE,'$1 ');
    for(const word of RELAY_ENGLISH)residue=stripEnglishWord(residue,word);
    for(const word of RELAY_JAPANESE)residue=residue.split(word).join(' ');
    residue=residue.replace(/[\s\p{P}\p{S}]/gu,'');
    const signalChars=[...residue].length;
    return {
      quality:signalChars>=SPECIFIC_SIGNAL_THRESHOLD?'specific':'generic',
      residue,
      signal_chars:signalChars,
    };
  }

  function compact(value){return String(value||'').replace(/\s+/gu,' ').trim();}

  function taskFingerprint(value){
    const text=compact(value).normalize('NFKC');
    let hash=0x811c9dc5;
    for(const character of text){
      const codePoint=character.codePointAt(0);
      hash^=codePoint;
      hash=Math.imul(hash,0x01000193)>>>0;
    }
    return hash.toString(16).padStart(8,'0');
  }

  function stableLiveText(agent){
    let live=compact(agent&&agent.live).replace(GLYPH_STRIP,'').trim();
    live=compact(live.replace(ELAPSED_COUNTER_RE,' '));
    return live;
  }

  function agentCwd(agent){
    return compact(agent&&(agent.cwd||agent.dir||agent.workdir||agent.working_directory));
  }

  function cwdParts(value){
    return String(value||'').replace(/\\/gu,'/').split('/').filter(Boolean);
  }

  function sharedCwdPrefix(agents){
    const paths=(Array.isArray(agents)?agents:[]).map(agent=>cwdParts(agentCwd(agent)))
      .filter(parts=>parts.length);
    if(paths.length<2)return [];
    const prefix=[];
    for(let index=0;;index+=1){
      const segment=paths[0][index];
      if(segment===undefined||paths.some(parts=>parts[index]!==segment))break;
      prefix.push(segment);
    }
    return prefix;
  }

  function cwdDifference(agent,agents){
    const parts=cwdParts(agentCwd(agent));
    if(!parts.length)return '';
    const prefix=sharedCwdPrefix(agents);
    const remainder=parts.slice(prefix.length);
    if(!remainder.length)return '';
    const candidate=remainder.join('/');
    const peers=(Array.isArray(agents)?agents:[]).filter(other=>other!==agent)
      .map(other=>cwdParts(agentCwd(other)).slice(prefix.length).join('/'));
    if(peers.includes(candidate))return '';
    for(let width=1;width<=remainder.length;width+=1){
      const suffix=remainder.slice(-width).join('/');
      if(!peers.some(peer=>peer===suffix||peer.endsWith('/'+suffix)))return suffix;
    }
    return candidate;
  }

  function liveIsSpecific(agent,live,names){
    if(!live)return false;
    const normalized=live.toLocaleLowerCase();
    if(normalized===String(agent&&agent.name||'').trim().toLocaleLowerCase())return false;
    if(normalized==='claude code')return false;
    if(BARE_LOCATION_RE.test(live))return false;
    const cwd=agentCwd(agent);
    if(cwd&&normalized===cwdParts(cwd).slice(-1)[0].toLocaleLowerCase())return false;
    return classify(live,names).quality==='specific';
  }

  function deriveRosterDescriptor(agent,agents=[]){
    const names=knownAgentNames(agents);
    const task=compact(agent&&agent.task);
    const taskResult=classify(task,names);
    const live=stableLiveText(agent);
    const role=compact(agent&&agent.annot&&agent.annot.role);
    const cwdDiff=role?'':cwdDifference(agent,agents);
    let primary='Needs description',provenance='fallback',quality=taskResult.quality;
    if(taskResult.quality==='specific'){
      primary=task;provenance='task';quality='specific';
    }else if(liveIsSpecific(agent,live,names)){
      primary=live;provenance='live';quality='specific';
    }else if(taskResult.quality==='missing'){
      quality='missing';
    }
    const secondary=role||cwdDiff;
    const tokens=[String(agent&&agent.name||''),primary,secondary].filter(Boolean);
    return {primary,secondary,tokens,provenance,quality};
  }

  function assignmentSignature(agent){
    return JSON.stringify([
      compact(agent&&agent.task),
      compact(agent&&agent.annot&&agent.annot.role),
      agentCwd(agent),
    ]);
  }

  function createStableDescriptorStore(){
    const cache=new Map();
    return {
      get(agent,agents=[]){
        const name=String(agent&&agent.name||'');
        const signature=assignmentSignature(agent);
        const prior=cache.get(name);
        if(prior&&prior.signature===signature)return prior.descriptor;
        const descriptor=deriveRosterDescriptor(agent,agents);
        cache.set(name,{signature,descriptor});
        return descriptor;
      },
      retain(names){
        const keep=new Set(names||[]);
        for(const name of cache.keys())if(!keep.has(name))cache.delete(name);
      },
      clear(){cache.clear();},
    };
  }

  return Object.freeze({
    SPECIFIC_SIGNAL_THRESHOLD,MIN_AGENT_NAME_STRIP_CHARS,
    RELAY_ENGLISH,RELAY_JAPANESE,GLYPH_STRIP,
    knownAgentNames,classify,stableLiveText,cwdDifference,
    deriveRosterDescriptor,assignmentSignature,createStableDescriptorStore,taskFingerprint,
  });
});
