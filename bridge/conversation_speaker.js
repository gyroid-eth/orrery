(function(root){
  'use strict';
  function displayModel(value){
    if(typeof value!=='string')return '';
    const raw=value.trim();
    const claude=/^(?:anthropic[\/:])?claude-([a-z]+)-(\d+)(?:[.-](\d{1,2}))?(?:-\d{8})?$/i.exec(raw);
    if(claude)return claude[1][0].toUpperCase()+claude[1].slice(1)+' '+claude[2]+(claude[3]?'.'+claude[3]:'');
    if(/^gpt-/i.test(raw))return 'GPT-'+raw.slice(4).split('-').map(s=>s?s[0].toUpperCase()+s.slice(1):s).join('-');
    if(/^deepseek[- ]v/i.test(raw))return 'DeepSeek '+raw.replace(/^deepseek[- ]/i,'').replace(/^v/i,'V');
    return raw;
  }
  function paint(element,{name='',model='',harness='',context={},renderAvatar=null}={}){
    const recorded=typeof model==='string'?model:'';
    const label=recorded?displayModel(recorded):(typeof context.model==='string'?context.model.trim():'');
    element.classList.toggle('conversation-speaker',Boolean(name||label));element.dataset.harness=harness;
    if(!name&&!label){
      element.removeAttribute('role');element.title=element.ariaLabel=harness;
      if(element.childElementCount||element.textContent!==harness)element.textContent=harness;
      return;
    }
    element.setAttribute('role','group');
    element.title=element.ariaLabel=[name,label].filter(Boolean).join(' · ')+(harness?' ('+harness+')':'');
    let avatar=element.querySelector('.conversation-avatar');
    const next=renderAvatar?renderAvatar(name,recorded,avatar):null;
    if(next!==avatar){avatar?.remove();if(next)element.prepend(next);}
    let primary=element.querySelector('.conversation-speaker-name');
    if(!primary){primary=document.createElement('span');primary.className='conversation-speaker-name';element.appendChild(primary);}
    const text=name||label||harness;if(primary.textContent!==text)primary.textContent=text;
    let secondary=element.querySelector('.conversation-speaker-model');
    if(name&&label){
      if(!secondary){secondary=document.createElement('span');secondary.className='conversation-speaker-model';element.appendChild(secondary);}
      if(secondary.textContent!==label)secondary.textContent=label;
      secondary.title=[label,recorded].filter(Boolean).join(' · ');
    }else secondary?.remove();
    // The previous harness text is a bare text node on the initial render.
    for(const child of [...element.childNodes])if(child.nodeType===Node.TEXT_NODE)child.remove();
  }
  root.OrreryConversationSpeaker=Object.freeze({displayModel,paint});
})(window);
