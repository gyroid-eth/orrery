/* Recorded Mail presentation only. No fetching, acknowledgement or active HTML. */
(function(root){
  'use strict';
  const create=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(typeof text==='string')el.textContent=text;return el;};
  function layoutThread(details){
    const line=details.querySelector('.conversation-mail-thread'),avatar=details.querySelector('.conversation-mail-sender .conversation-avatar');
    line.hidden=true;details.classList.remove('is-threaded');
    if(!details.open||!avatar)return;
    const card=details.getBoundingClientRect(),face=avatar.getBoundingClientRect();
    if(!face.width)return;
    const x=face.left+face.width/2-card.left;
    details.style.setProperty('--mail-thread-inset',(x+16)+'px');
    line.style.left=(x-.5)+'px';line.style.top=(face.bottom-card.top+3)+'px';
    details.classList.add('is-threaded');line.hidden=false;
  }
  function layout(container,force=false){
    const panel=container.matches('.conversation-panel')?container:container.closest('.conversation-panel');
    if(!panel||!panel.getClientRects().length)return;
    const narrow=panel.getBoundingClientRect().width<300;
    for(const route of container.querySelectorAll('.conversation-mail-route')){
      const group=route.querySelector('.conversation-mail-recipients'),peers=[...group.querySelectorAll('.conversation-mail-peer')];
      const compact=narrow&&peers.length>1,width=route.getBoundingClientRect().width;
      if(!force&&route._mailWidth===width&&route.classList.contains('is-compact')===compact)continue;
      route._mailWidth=width;route.classList.toggle('is-compact',compact);group.classList.remove('is-wrap');
      const more=group.querySelector('.conversation-mail-more');
      for(const peer of peers){peer.hidden=false;peer.querySelector('.conversation-mail-peer-name').hidden=compact;}
      more.hidden=true;more.textContent='';more.style.marginLeft='';
      if(!compact)continue;
      const known=peers.filter(peer=>peer.querySelector('.conversation-avatar'));
      const widths=new Map();
      const counterWidth=count=>{
        if(!count)return 0;
        const digits=String(count).length;
        if(!widths.has(digits)){more.hidden=false;more.textContent='+'+count;widths.set(digits,more.getBoundingClientRect().width);}
        return widths.get(digits);
      };
      const sender=route.querySelector('.conversation-mail-sender'),arrow=route.querySelector('.conversation-mail-arrow');
      const gap=parseFloat(getComputedStyle(route).columnGap)||0;
      const remaining=width-sender.getBoundingClientRect().width-gap;
      const prefix=arrow.getBoundingClientRect().width+6;
      const minimum=prefix+(known.length?21+(peers.length>1?6+counterWidth(peers.length-1):0):3+counterWidth(peers.length));
      const wrap=remaining<minimum;group.classList.toggle('is-wrap',wrap);
      const available=wrap?width:remaining;
      let shown=known.length;
      while(shown>0){
        const hidden=peers.length-shown,needed=prefix+21+(shown-1)*14+(hidden?6+counterWidth(hidden):0);
        if(needed<=available)break;
        shown--;
      }
      const visible=new Set(known.slice(0,shown));
      for(const peer of peers)peer.hidden=!visible.has(peer);
      const hidden=peers.length-shown;
      more.textContent=hidden?'+'+hidden:'';more.hidden=!hidden;more.style.marginLeft=shown&&hidden?'6px':'';
      more.title=peers.filter(peer=>!visible.has(peer)).map(peer=>peer.dataset.peerName).join(', ');
    }
    for(const details of container.querySelectorAll('.conversation-mail'))layoutThread(details);
  }
  function refreshPeers(container,renderPeerAvatar){
    if(typeof renderPeerAvatar!=='function')return;
    let changed=false;
    for(const peer of container.querySelectorAll('.conversation-mail-peer')){
      const previous=peer.querySelector('.conversation-avatar'),avatar=renderPeerAvatar(peer.dataset.peerName,previous);
      if(avatar===previous)continue;
      changed=true;previous?.remove();if(avatar)peer.prepend(avatar);
    }
    layout(container,changed);
  }
  function render(event,article,{name='',renderPeerAvatar=null}={}){
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
      const senderPeer=peer(from,sent);senderPeer.classList.add('conversation-mail-sender');
      const group=create('span','conversation-mail-recipients');group.appendChild(arrow);group.setAttribute('aria-label',fullTo);group.title=fullTo;
      for(const recipient of sent&&recipients.length?recipients:[to])group.appendChild(peer(recipient,!sent));
      const more=create('span','conversation-mail-more');more.hidden=true;group.appendChild(more);
      route.append(senderPeer,group);
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
      const line=create('span','conversation-mail-thread');line.hidden=true;line.setAttribute('aria-hidden','true');
      details.append(body,line);details.addEventListener('toggle',()=>layoutThread(details));article.appendChild(details);
    }
    refreshPeers(article,renderPeerAvatar);return article;
  }
  root.OrreryConversationMail=Object.freeze({render,refreshPeers,layout});
})(window);
