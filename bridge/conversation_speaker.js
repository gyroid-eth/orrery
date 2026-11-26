(function(root){
  'use strict';
  function paint(element,{name='',model='',harness='',renderAvatar=null,configureAgentButton=null}={}){
    const recorded=typeof model==='string'?model:'';
    element.classList.toggle('conversation-speaker',Boolean(name));element.dataset.harness=harness;
    if(!name){
      element.removeAttribute('role');element.title=element.ariaLabel=harness;
      if(element.childElementCount||element.textContent!==harness)element.textContent=harness;
      return;
    }
    element.setAttribute('role','group');
    element.title=element.ariaLabel=name+(harness?' ('+harness+')':'');
    let content=element.querySelector('button');
    if(!content&&configureAgentButton){
      content=document.createElement('button');element.appendChild(content);
    }
    if(content)configureAgentButton?.(content,name);
    content||=element;
    let avatar=content.querySelector('.conversation-avatar');
    const next=renderAvatar?renderAvatar(name,recorded,avatar):null;
    if(next!==avatar){avatar?.remove();if(next)content.prepend(next);}
    let primary=content.querySelector('.conversation-speaker-name');
    if(!primary){primary=document.createElement('span');primary.className='conversation-speaker-name';content.appendChild(primary);}
    if(primary.textContent!==name)primary.textContent=name;
    // The previous harness text is a bare text node on the initial render.
    for(const child of [...element.childNodes])if(child.nodeType===Node.TEXT_NODE)child.remove();
  }
  root.OrreryConversationSpeaker=Object.freeze({paint});
})(window);
