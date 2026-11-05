/* Settings → Phone.
 *
 * Two switches: "Phone access" (the phone reads everything the reader offers:
 * agents, Graph, Mail, conversation, file and image previews) and "Send from
 * phone" (one confirmed line to a pane; on by default). The reader belongs to
 * Telemetry: GET/PUT /telemetry/mobile run its `agentstack-mobile` command,
 * which writes ~/.agentstack/mobile.json and the launchd job.
 *
 * Tailscale Serve and the access policy stay the person's own steps. This panel
 * only reads Serve/Funnel, offers the command to copy, and records the
 * person's own "I reviewed the policy" with its date; it cannot verify it.
 * The setup steps are shown only while one is missing.
 *
 * A reader started by hand (not by Settings) may hold the port: the panel says
 * so (MANUAL) and its switches change nothing until that reader is stopped.
 * In demo mode the owner login, the phone address and the Serve URL are not
 * put on the page at all (demo mode masks only the user and host names).
 *
 * Every value is put in with textContent; nothing here builds HTML from data.
 */
(function(){
  'use strict';
  var ENDPOINT='/telemetry/mobile';
  var root=document.getElementById('phoneSettings');
  var badge=document.getElementById('phoneBadge');
  var popover=document.getElementById('settingsPopover');
  if(!root)return;
  var state=null,busy=false,message='',editing=false,setupOpen=false,hint='';
  var MESSAGES={
    telemetry_missing:'Phone access needs ORRERY Telemetry: agentstack-mobile was not found.',
    identity_invalid:'Check the login and address: the address must be https://<name>.ts.net:9443.',
    port_in_use:'A reader not started from Settings is running on its port. Stop it where it was started, then use this switch. Nothing was changed.',
    launchd_unavailable:'launchd did not answer. Phone access is unchanged.',
    launchd_failed:'launchd could not start the reader, so Phone access is off again. Try once more; ~/.agentstack/logs/mobile-relay.log may say why.',
    job_stuck:'The old reader did not stop. Nothing was changed; try again in a moment.',
    python_too_old:'The Python that runs agentstack-mobile is older than 3.11. Run it with a newer python3.',
    settings_unsafe:'~/.agentstack/mobile.json must be your own file with mode 0600.',
    settings_invalid:'~/.agentstack/mobile.json could not be read. Fix or remove it.',
    change_invalid:'That change was not accepted.',
    config_invalid:'~/.orrery/config.json could not be read, so Send was changed for this run only.',
    mobile_slow:'Telemetry took too long to answer. Check again.',
    request_denied:'This page may not change phone access.',
  };
  var HIDDEN='hidden in demo mode';
  function demo(){return !!(window.OrreryDemo&&window.OrreryDemo.on);}
  function text(code){return MESSAGES[code]||'Phone access is unavailable right now.';}
  function el(tag,cls,content){var e=document.createElement(tag);if(cls)e.className=cls;if(content!=null)e.textContent=content;return e;}
  function button(label,onClick,primary){var b=el('button','cockpit-control',label);b.type='button';b.disabled=busy;b.addEventListener('click',onClick);if(primary)b.dataset.primary='1';return b;}
  function toggle(id,name,help,checked,disabled,onChange){
    var label=el('label','settings-toggle-row');label.htmlFor=id;
    var copy=el('span','settings-toggle-copy');copy.append(el('span','settings-row-name',name),el('span','settings-help',help));
    var sw=el('span','settings-switch');var input=document.createElement('input');input.type='checkbox';input.id=id;
    input.checked=!!checked;input.disabled=!!disabled||busy;input.addEventListener('change',function(){onChange(input.checked);});
    sw.append(input);label.append(copy,sw);return label;
  }
  function line(kind,words,extra){var row=el('div','phone-line '+kind);row.append(el('span','dot',kind==='ok'?'●':kind==='warn'?'●':'○'),el('span','',words));row.append(extra||el('span'));return row;}
  function date(at){var d=at?new Date(at):null;if(!d||isNaN(d))return '';var two=function(n){return String(n).padStart(2,'0');};return d.getFullYear()+'-'+two(d.getMonth()+1)+'-'+two(d.getDate());}

  async function call(method,body){
    var init={method:method,headers:{'Accept':'application/json'},cache:'no-store'};
    if(body){init.headers['Content-Type']='application/json';init.body=JSON.stringify(body);}
    try{
      var response=await fetch(ENDPOINT,init);
      var value=await response.json();
      return value&&typeof value==='object'?value:{ok:false,error:'mobile_unavailable'};
    }catch(_){return {ok:false,error:'mobile_unavailable'};}
  }
  async function refresh(){
    var value=await call('GET');
    if(value.ok){state=value;}else{state=state||null;message=text(value.error);if(value.error==='telemetry_missing')state=null;}
    render();
  }
  async function change(body){
    busy=true;message='';render();
    var value=await call('PUT',body);
    busy=false;
    if(value.ok){state=value;editing=false;setupOpen=false;hint='';if(value.warning)message=text(value.warning);}
    else message=text(value.error);
    render();
  }

  function identityFields(s){
    var box=el('div','phone-fields');
    var login=document.createElement('input');login.className='settings-select';login.id='phoneOwner';login.spellcheck=false;login.autocomplete='off';
    login.value=s.settings.owner_login||s.suggest.owner_login||'';login.placeholder='you@example.com';
    var origin=document.createElement('input');origin.className='settings-select';origin.id='phoneAddress';origin.spellcheck=false;origin.autocomplete='off';
    origin.value=s.settings.public_origin||s.suggest.public_origin||'';origin.placeholder='https://computer.example.ts.net:9443';
    var a=el('label','phone-field');a.htmlFor='phoneOwner';a.append(el('span','','Owner (Tailscale login)'),login);
    var b=el('label','phone-field');b.htmlFor='phoneAddress';b.append(el('span','','Address on the phone'),origin);
    box.append(a,b);
    return {box:box,value:function(){return {owner_login:login.value.trim(),public_origin:origin.value.trim()};}};
  }

  function steps(s){
    var ts=s.tailscale,set=s.settings;
    var list=el('div','phone-steps');
    function step(done,now,n,name,who,body){
      var row=el('div','phone-step'+(done?' done':now?' now':''));
      var head=el('div');var nm=el('span','settings-row-name',name);head.append(nm,el('span','phone-who',who));
      var main=el('div');main.append(head);(body||[]).forEach(function(x){main.append(x);});
      row.append(el('span','phone-num',done?'✓':String(n)),main);return row;
    }
    var signed=ts.found&&ts.signed_in;
    list.append(step(signed,!signed,1,'Tailscale signed in','checked',[el('div','settings-help',signed?(demo()?'Signed in (account '+HIDDEN+')':ts.dns_name+' · '+ts.login):ts.found?'Tailscale is installed but not signed in.':'Tailscale was not found on this computer.')]));
    var named=!!(set.owner_login&&set.public_origin);
    var fields=null,body=[];
    if((!named||editing)&&demo())body.push(el('div','settings-help','Owner and address are '+HIDDEN+'. Open the cockpit without demo mode to set them.'));
    else if(!named||editing){fields=identityFields(s);body.push(el('div','settings-help','Filled in from Tailscale. Only this login is let in.'+(set.policy_reviewed_at?' Changing them asks you to confirm step 4 again.':'')),fields.box);
      var act=el('div','phone-actions');act.append(button(set.access||!named?'Confirm and turn on':'Confirm',function(){var v=fields.value();v.access=true;change(v);},true));body.push(act);}
    else body.push(el('div','settings-help',demo()?'Set ('+HIDDEN+')':set.owner_login+' · '+set.public_origin));
    var two=step(named&&!editing,signed&&(!named||editing),2,'Owner and address','you · once',body);two.id='phoneStepOwner';
    list.append(two);
    var served=ts.serve==='ok';
    var serveBody=[el('div','settings-help',served?(demo()?'9443 → this computer (address '+HIDDEN+')':'https://'+ts.dns_name+':9443 → this computer'):'Run this once in a terminal; ORRERY only reads the result.')];
    if(!served){serveBody.push(el('div','phone-code','tailscale serve --https=9443 http://127.0.0.1:'+s.relay.port));
      var a2=el('div','phone-actions');a2.append(button('Copy',function(){try{navigator.clipboard.writeText('tailscale serve --https=9443 http://127.0.0.1:'+s.relay.port);}catch(_){}}),button('Check again',refresh));serveBody.push(a2);}
    list.append(step(served,named&&!served,3,'Serve 9443 → reader','you · terminal',serveBody));
    var reviewed=!!set.policy_reviewed_at;
    var policyBody=[el('div','settings-help',reviewed?'You reviewed it on '+date(set.policy_reviewed_at)+'. ORRERY cannot check the policy.':'Limit tcp:9443 to your own phones and tablets in the Tailscale admin console, then confirm here. ORRERY cannot check it. Conversation and Send stay off until you do.')];
    if(!reviewed){var a3=el('div','phone-actions');a3.append(button('I reviewed the policy',function(){change({policy_reviewed:true});},true));policyBody.push(a3);}
    list.append(step(reviewed,named&&served&&!reviewed,4,'Who can reach it','you · admin console',policyBody));
    return list;
  }

  /* One line right under the Phone access switch, for the three places where
     the switch alone said nothing: demo mode before the first setup, the first
     press (the switch stays off until step 2 is confirmed), and ON before the
     policy review (badge SETUP). */
  function switchNote(s,named,reviewed,manual){
    var words='';
    if(!named&&hint==='demo')words='Turn off demo mode to set up phone access (once). After that you can switch it on and off in demo mode.';
    else if(!named&&hint==='signin')words='Not on yet: sign in to Tailscale on this computer first (step 1 below), then press Phone access again.';
    else if(!named&&hint==='first')words='Not on yet: check the owner and address in step 2 below, then press Confirm and turn on.';
    else if(s.settings.access&&named&&!reviewed&&!manual)words='On, but Conversation and Send from phone stay off until step 4 below (I reviewed the policy).';
    if(!words)return null;
    var box=el('div','phone-note');box.id='phoneSwitchNote';box.setAttribute('role','status');box.append(el('span','',words));
    if(!named&&hint==='demo'&&window.OrreryDemo&&typeof window.OrreryDemo.reloadFor==='function'){
      var a=el('div','phone-actions');a.append(button('Turn off demo mode',function(){window.OrreryDemo.reloadFor(false);}));box.append(a);
    }
    return box;
  }
  function showStepTwo(){
    var two=document.getElementById('phoneStepOwner');
    if(two&&typeof two.scrollIntoView==='function')two.scrollIntoView({block:'center',behavior:'smooth'});
    var owner=document.getElementById('phoneOwner');
    if(owner&&typeof owner.focus==='function')owner.focus({preventScroll:true});
  }

  function render(){
    root.replaceChildren();
    if(!state){
      badge.hidden=true;
      root.append(el('div','settings-help',message||'Checking phone access…'));
      if(message){var a=el('div','phone-actions');a.append(button('Check again',refresh));root.append(a);}
      return;
    }
    var s=state,set=s.settings,ts=s.tailscale;
    var named=!!(set.owner_login&&set.public_origin),reviewed=!!set.policy_reviewed_at;
    var running=set.access&&s.relay.listening;
    var manual=s.relay.manual===true;
    var missing=!(ts.found&&ts.signed_in)||!named||ts.serve!=='ok'||!reviewed;
    badge.hidden=false;
    badge.className='phone-badge'+(running?(missing||ts.funnel?' warn':' on'):'');
    badge.textContent=!set.access?'OFF':running?(missing?'SETUP':'ON'):'STARTING';
    if(set.access&&!s.relay.listening&&s.relay.job!=='loaded')badge.textContent='STOPPED';
    if(manual){badge.className='phone-badge warn';badge.textContent='MANUAL';}

    var main=el('div','settings-row');
    main.append(toggle('phoneAccess','Phone access','Read the cockpit from your phone over Tailscale: agents, Graph, Mail, conversation, files and images. Images cannot be redacted.',
      set.access,manual,function(on){
        if(on&&!named){
          var box=document.getElementById('phoneAccess');if(box)box.checked=false;
          /* pressed again while step 2 is open: keep what was typed there */
          if(hint==='first'&&!demo()){showStepTwo();return;}
          setupOpen=true;
          hint=demo()?'demo':!(ts.found&&ts.signed_in)?'signin':'first';
          if(hint==='signin'){refresh();return;}  /* re-reads Tailscale, so the next press sees a new sign-in */
          render();if(hint==='first')showStepTwo();return;
        }
        change({access:on});
      }));
    var note=switchNote(s,named,reviewed,manual);
    if(note)main.append(note);
    var sub=el('div','phone-sub');
    sub.append(toggle('phoneSend','Send from phone','Send one confirmed line to a pane.'+(reviewed||manual?'':set.access?' Starts after step 4 below.':' Starts once Phone access is on and you have reviewed who can reach it.'),
      set.send,!set.access||!reviewed||manual,function(on){change({send:on});}));
    main.append(sub);
    root.append(main);

    if(missing&&(set.access||setupOpen)){
      var setup=el('div','settings-row');setup.append(el('span','settings-row-name','Setup'),steps(s));root.append(setup);
    }
    if(set.access||named||manual){
      var status=el('div','settings-row');status.append(el('span','settings-row-name','Status'));
      var lines=el('div','phone-lines');
      if(manual)lines.append(line('warn','A reader not started from Settings is running on 127.0.0.1:'+s.relay.port+'. The phone can still reach it. Stop it where it was started; these switches change nothing until then.'));
      else lines.append(set.access?(s.relay.listening?line('ok','Reader running on 127.0.0.1:'+s.relay.port):line('warn','Reader not answering on 127.0.0.1:'+s.relay.port+(s.relay.job==='loaded'?' (starting)':''))):line('off','Reader off'));
      var stepsShown=missing&&(set.access||setupOpen);
      if(!stepsShown)lines.append(ts.serve==='ok'?line('ok','Serve 9443 → reader'):ts.serve==='other'?line('warn','Serve 9443 points elsewhere'):ts.serve==='missing'?line('warn','Serve 9443 not set up'):line('off','Serve state unknown'));
      if(s.relay.python_missing)lines.append(line('warn','The Python this reader was set up with is gone. Turn Phone access off and on to use the current one.'));
      if(ts.funnel===true)lines.append(line('warn','Funnel is on: the port is open to the internet. Turn it off.'));
      else if(ts.funnel===false)lines.append(line('ok','Funnel off'));
      if(!stepsShown)lines.append(reviewed?line('ok','Policy reviewed by you on '+date(set.policy_reviewed_at)):line('warn','Policy not reviewed yet'));
      status.append(lines);
      if(named&&!editing&&!missing){
        status.append(el('div','settings-help',demo()?'Owner and address set ('+HIDDEN+')':set.owner_login+' · '+set.public_origin));
        var act=el('div','phone-actions');if(!demo())act.append(button('Change owner or address',function(){editing=true;setupOpen=true;render();}));act.append(button('Check again',refresh));status.append(act);
      }
      root.append(status);
    }
    if(editing&&!missing&&!demo()){var ed=el('div','settings-row');ed.append(el('span','settings-row-name','Owner and address'));var f=identityFields(s);ed.append(f.box);
      if(reviewed)ed.append(el('div','settings-help','Changing them asks you to confirm step 4 again.'));
      var a4=el('div','phone-actions');a4.append(button('Save',function(){change(f.value());},true),button('Cancel',function(){editing=false;render();}));ed.append(a4);root.append(ed);}
    if(message)root.append(el('div','phone-message',message));
    if(busy)root.append(el('div','settings-help','Applying…'));
  }

  if(popover)popover.addEventListener('toggle',function(event){if(event.newState==='open'){message='';hint='';setupOpen=false;refresh();}});
  window.OrreryPhoneSettings=Object.freeze({refresh:refresh});
})();
