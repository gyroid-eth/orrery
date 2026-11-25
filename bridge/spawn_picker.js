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
    return ({claude:'claude-code',claudecode:'claude-code','codex-cli':'codex','dsh-tui':'dsh'})[key]||key;
  }
  function harnessInfo(id){return HARNESS[harnessKey(id)]||{label:id,asset:null};}
  function unavailableReason(harness){
    if(harness&&harness.available)return '';
    const messages={
      runtime_not_prepared:'Install or repair this harness',
      credential_reader_unavailable:'Prepare the OS key store',
      disabled_by_opt_in:'Enable this harness in setup',
      unsupported_credential_store:'Use the supported OS key store',
      unsupported_mode:'Unavailable in this Mail mode',
      unsupported_platform:'Unavailable on this OS',
      harness_not_enabled:'Enable the connection settings',
      model_mismatch:'Check the configured model',
    };
    const reason=harness&&harness.reason;
    return Object.hasOwn(messages,reason)?messages[reason]:'Check setup and compatibility';
  }
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
    .filter(model=>model&&model.id).map(model=>({provider,model,key:JSON.stringify([provider.id,model.id,
      ...(Number.isInteger(model.url_index)?[model.url_index]:[]),...(model.url_key?[model.url_key]:[])]),family:family(provider,model)})));}
  function geminiFamily(provider,id){
    if(provider?.id!=='gemini'||!id||!Array.isArray(provider.efforts))return '';
    const split=id.lastIndexOf('-');
    return split>0&&provider.efforts.includes(id.slice(split+1))?id.slice(0,split):'';
  }
  function displayModels(provider,models,selectedId){
    if(provider.id!=='gemini')return models;
    const grouped=new Map(),ids=new Set(models.map(model=>model.id));
    for(const model of models){
      const family=geminiFamily(provider,model.id);
      if(!family){grouped.set('id:'+model.id,model);continue;}
      const key='family:'+family,previous=grouped.get(key);
      const keepPrevious=previous&&model.id!==selectedId&&(previous.id===selectedId||!model.default);
      const representative=keepPrevious?previous:model;
      // Keep a catalog ID for drafts and launch, even though the row represents
      // every available effort variant in this family.
      const pickerLabel=ids.has(family)?family+' (effort variants)':family;
      grouped.set(key,{...representative,pickerLabel,variantIds:[...(previous?.variantIds||[]),model.id]});
    }
    return [...grouped.values()];
  }
  function value(provider,model,key){return model&&Object.hasOwn(model,key)?model[key]:provider[key];}
  function harnesses(provider,model){
    const supplied=value(provider,model,'harnesses');
    const fallback=provider.program||({claude:'claude-code',codex:'codex-cli'})[provider.id]||provider.id;
    const offered=Array.isArray(supplied)?supplied:[{id:fallback,available:true,default:true}];
    const result=offered.filter(h=>h&&h.id).map(h=>({...h,label:h.label||harnessInfo(h.id).label,available:h.available===true}));
    return result;
  }
  function helperModels(provider,model,harness){
    const selected=harnesses(provider,model).find(h=>h.id===harness);
    const list=selected&&Object.hasOwn(selected,'helper_models')?selected.helper_models:value(provider,model,'helper_models');
    return Array.isArray(list)?list.filter(m=>typeof m==='string'||m&&m.id).map(m=>typeof m==='string'?{id:m,label:m}:m):[];
  }
  function metadata(provider,model){
    if(provider.dynamic_models){
      const source=model.context_source||'unreported';
      return [provider.label||provider.id,Number.isInteger(model.url_index)?'URL '+(model.url_index+1):'',
        model.context?Math.round(model.context/1000)+'K context ('+source+')':'Context unreported'].filter(Boolean).join(' · ');
    }
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
  return {harnessKey,harnessInfo,unavailableReason,locality,family,entries,geminiFamily,displayModels,value,harnesses,helperModels,metadata,recent,remember,rosterHarness};
});
