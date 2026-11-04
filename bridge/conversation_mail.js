/* Recorded Mail presentation only. No fetching, acknowledgement or active HTML. */
(function(root){
  'use strict';
  const create=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(typeof text==='string')el.textContent=text;return el;};
  function render(event,article){
    article.classList.add('conversation-mail-event');
    for(const item of event.mail.slice(0,8)){
      if(!item||!['received','sent'].includes(item.direction)||typeof item.subject!=='string')continue;
      const details=create('details','conversation-mail');details.dataset.direction=item.direction;
      const summary=create('summary','conversation-mail-summary'),head=create('span','conversation-mail-head');
      head.appendChild(create('span','conversation-mail-label','ORRERY MAIL'));
      const importance=['low','normal','high','urgent'].includes(item.importance)?item.importance:'normal';
      const badge=create('span','conversation-mail-importance',importance.toUpperCase());badge.dataset.importance=importance;head.appendChild(badge);
      const date=new Date(event.ts),time=create('time','conversation-time');
      if(Number.isFinite(date.getTime())){time.dateTime=event.ts;time.textContent=date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});time.title=date.toLocaleString();}
      head.appendChild(time);summary.appendChild(head);
      const peers=item.direction==='received'?item.sender:(Array.isArray(item.recipients)?item.recipients.filter(x=>typeof x==='string').slice(0,24).join(', '):'');
      summary.appendChild(create('span','conversation-mail-route',(item.direction==='received'?'Received ← ':'Sent → ')+(peers||'recorded recipient unavailable')));
      summary.appendChild(create('span','conversation-mail-subject',item.subject.slice(0,512)));
      details.appendChild(summary);
      const body=create('div','conversation-mail-content');
      const notice=item.coverage==='complete'?'Recorded notification · full message':
        item.coverage==='preview'?'Preview only · read the rest in Mail.':
        item.coverage==='request'?'Recorded send request · delivery is not confirmed here.':
        'No body in this notification · read it in Mail.';
      body.appendChild(create('p','conversation-mail-notice',notice+(item.truncated?' Recorded text shortened.':'')));
      body.appendChild(create('p','conversation-mail-text',typeof item.body==='string'?item.body.slice(0,65536):''));
      details.appendChild(body);article.appendChild(details);
    }
    return article;
  }
  root.OrreryConversationMail=Object.freeze({render});
})(window);
