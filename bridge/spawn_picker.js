/* Catalog-only model choices. No local server inventory is invented here. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.SpawnPicker=api;
})(typeof globalThis!=='undefined'?globalThis:this,()=>{
  const HARNESS={
    'claude-code':{label:'Claude Code',asset:'anthropic.svg'},
    codex:{label:'Codex',asset:'openai.svg'},
    hermes:{label:'Hermes',asset:'hermes.png'},
    dsh:{label:'dsh',asset:'dsh.svg'},
  };
  function harnessKey(id){
    const key=String(id||'').trim().toLowerCase().split('/').pop();
    return ({claude:'claude-code','codex-cli':'codex','dsh-tui':'dsh'})[key]||key;
  }
  function harnessInfo(id){return HARNESS[harnessKey(id)]||{label:id,asset:null};}
  function locality(provider,model){return (model&&model.locality||provider.locality)==='local'?'local':'cloud';}
  function family(provider,model){
    if(locality(provider,model)==='local')return 'local';
    const key=String(model&&model.provider||provider.id||'').toLowerCase();
    if(['claude','anthropic','claude-code'].includes(key))return 'claude';
    if(['codex','openai','codex-cli'].includes(key))return 'codex';
    if(key.includes('deepseek'))return 'deepseek';
    return key;
  }
  function entries(catalog){return (catalog.providers||[]).flatMap(provider=>(provider.models||[])
    .filter(model=>model&&model.id).map(model=>({provider,model,key:JSON.stringify([provider.id,model.id]),family:family(provider,model)})));}
  function value(provider,model,key){return model&&Object.hasOwn(model,key)?model[key]:provider[key];}
  function harnesses(provider,model){
    const supplied=value(provider,model,'harnesses');
    const fallback=provider.program||({claude:'claude-code',codex:'codex-cli'})[provider.id]||provider.id;
    const offered=Array.isArray(supplied)?supplied:[{id:fallback,available:true,default:true}];
    const result=offered.filter(h=>h&&h.id).map(h=>({...h,label:h.label||harnessInfo(h.id).label,available:h.available===true}));
    for(const id of ['hermes','dsh'])if(!result.some(h=>harnessKey(h.id)===id))result.push({id,label:HARNESS[id].label,available:false,default:false});
    return result;
  }
  // Stage1 contract: the managed dispatch owns registration and the private worktree.
  function isManaged(provider,model,harness){
    return value(provider,model,'managed')===true||['deepseek','strata'].includes(provider.id)||['dsh','hermes'].includes(harnessKey(harness));
  }
  function managedPayload(base,attemptId,allowedPaths,expected){
    const {name,headless,worktree_base,...rest}=base;
    return {...rest,attempt_id:attemptId,standalone:false,worktree:true,helper_model:'same',
      allowed_paths:allowedPaths,expected,async:true};
  }
  function managedError(payload){
    if(!payload.parent)return 'Choose a parent for this managed launch.';
    if(!payload.allowed_paths.length)return 'List the files this child may edit.';
    if(payload.allowed_paths.some(path=>path.startsWith('/')||path.includes('\\')||/[?*\[\]]/.test(path)||path.split('/').some(part=>!part||['.','..','.git'].includes(part))))
      return 'Use relative file names without globs, parent directories or .git.';
    const check=payload.expected[0];
    if(!check||!payload.allowed_paths.includes(check.path))return 'The expected file must be in the allowed files list.';
    if(Object.hasOwn(check,'sha256')&&!/^[a-f0-9]{64}$/i.test(check.sha256))return 'Enter the expected SHA256 (64 hexadecimal characters).';
    if(Object.hasOwn(check,'contains')&&!check.contains)return 'Enter text that the expected file must contain.';
    return '';
  }
  function helperModels(provider,model){
    const list=value(provider,model,'helper_models');
    return Array.isArray(list)?list.filter(m=>typeof m==='string'||m&&m.id).map(m=>typeof m==='string'?{id:m,label:m}:m):[];
  }
  function metadata(provider,model){
    return ['server','quantization','context'].map(key=>value(provider,model,key)).filter(v=>v!==undefined&&v!==null&&v!=='').join(' / ');
  }
  function recent(storage,key){
    try{const list=JSON.parse(storage.getItem(key)||'[]');return Array.isArray(list)?list.filter(v=>typeof v==='string').slice(0,8):[];}catch(_){return [];}
  }
  function remember(storage,key,entryKey){
    try{storage.setItem(key,JSON.stringify([entryKey,...recent(storage,key).filter(k=>k!==entryKey)].slice(0,8)));}catch(_){}
  }
  function rosterHarness(agent){
    const id=agent.harness||agent.program||agent.cmd||'';
    const key=harnessKey(id),model=String(agent.model_raw||agent.model||'').toLowerCase();
    const local=String(agent.locality||agent.provider||'').toLowerCase()==='local';
    const maker=String(agent.provider||'').toLowerCase();
    if(!local&&((key==='claude-code'&&(['anthropic','claude'].includes(maker)||/claude|opus|sonnet|haiku|fable|mythos/.test(model)))||
       (key==='codex'&&(['openai','codex'].includes(maker)||/gpt|codex/.test(model)))))return null;
    if(!id||agent.category&&agent.category!=='agent')return null;
    return {id:key,...harnessInfo(id)};
  }
  return {isManaged,managedPayload,managedError,harnessKey,harnessInfo,locality,family,entries,value,harnesses,helperModels,metadata,recent,remember,rosterHarness};
});
