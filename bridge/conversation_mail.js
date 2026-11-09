/* Recorded Mail presentation only. No fetching, acknowledgement or active HTML. */
(function(root){
  'use strict';
  const create=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(typeof text==='string')el.textContent=text;return el;};
  function refreshPeers(container,renderPeerLogo){
    if(typeof renderPeerLogo!=='function')return;
    for(const peer of container.querySelectorAll('.conversation-mail-peer')){
      const previous=peer.querySelector('.pane-provider'),logo=renderPeerLogo(peer.dataset.peerName,previous);
      if(logo===previous)continue;
      if(previous)previous.remove();
      if(logo)peer.prepend(logo);
    }
  }
  function render(event,article,{name='',renderPeerLogo=null}={}){
    article.classList.add('conversation-mail-event');
    for(const item of event.mail.slice(0,8)){
      if(!item||!['received','sent'].includes(item.direction)||typeof item.subject!=='string')continue;
      const details=create('details','conversation-mail');details.dataset.direction=item.direction;
      const sent=item.direction==='sent',direction=sent?'Sent':'Received';
      const summary=create('summary','conversation-mail-summary'),head=create('span','conversation-mail-head');
      const label=create('span','conversation-mail-label','Mail · '+direction);label.title='ORRERY Mail · '+direction;
      summary.appendChild(label);
      const importance=['low','normal','high','urgent'].includes(item.importance)?item.importance:'normal';
      const badge=create('span','conversation-mail-importance');badge.dataset.importance=importance;badge.title=importance+' importance';badge.setAttribute('aria-hidden','true');
      const date=new Date(event.ts),time=create('time','conversation-time');
      if(Number.isFinite(date.getTime())){time.dateTime=event.ts;time.textContent=date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});time.title=date.toLocaleString();}
      const recipients=Array.isArray(item.recipients)?item.recipients.filter(x=>typeof x==='string'&&x).slice(0,24):[];
      const sender=typeof item.sender==='string'&&item.sender?item.sender:'recorded sender unavailable';
      const from=sent?(name||'recorded sender unavailable'):sender,to=sent?(recipients[0]||'recorded recipient unavailable'):(name||'recorded recipient unavailable');
      const fullTo=sent?(recipients.join(', ')||to):to,route=create('span','conversation-mail-route');
      route.title=from+' → '+fullTo;
      const peer=(value,self)=>{
        const span=create('span','conversation-mail-peer'+(self?' is-self':' is-counterpart'));span.dataset.peerName=value;span.title=value;
        span.appendChild(create('span','conversation-mail-peer-name',value));return span;
      };
      const arrow=create('span','conversation-mail-arrow','→');arrow.setAttribute('aria-hidden','true');
      const chevron=create('span','conversation-mail-chevron','▸');chevron.setAttribute('aria-hidden','true');
      route.append(peer(from,sent),arrow,peer(to,!sent));
      if(sent&&recipients.length>1){const more=create('span','conversation-mail-more','+'+(recipients.length-1));more.title=recipients.slice(1).join(', ');route.appendChild(more);}
      head.append(chevron,route,time);summary.appendChild(head);
      const subject=create('span','conversation-mail-subject-row');subject.append(badge,create('span','conversation-mail-subject',item.subject.slice(0,512)));
      summary.appendChild(subject);
      summary.setAttribute('aria-label',direction+' from '+from+' to '+fullTo+' · '+importance+' importance · '+item.subject.slice(0,512)+(time.textContent?' · '+time.textContent:''));
      details.appendChild(summary);
      const body=create('div','conversation-mail-content');
      const notice=item.coverage==='complete'?'Recorded notification · full message':
        item.coverage==='preview'?'Preview only · read the rest in Mail.':
        item.coverage==='request'?'Recorded send request · delivery is not confirmed here.':
        'No body in this notification · read it in Mail.';
      body.appendChild(create('p','conversation-mail-notice',notice+(item.truncated?' Recorded text shortened.':'')));
      const text=create('p','conversation-mail-text'),value=typeof item.body==='string'?item.body.slice(0,65536):'';
      if(root.OrreryConversationMarkdown)root.OrreryConversationMarkdown.renderText(value,text);else text.textContent=value;
      body.appendChild(text);
      details.appendChild(body);article.appendChild(details);
    }
    refreshPeers(article,renderPeerLogo);return article;
  }
  root.OrreryConversationMail=Object.freeze({render,refreshPeers});
})(window);
