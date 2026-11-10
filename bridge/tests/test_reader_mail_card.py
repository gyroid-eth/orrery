"""Mail routes keep roster identity visible and native details accessible."""
import json

import pytest

from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout


def prepare(cockpit, *, direction='received', sender='KnownPeer', recipients=None, importance='high', width=1600, theme='dark'):
    js, wait, client, requests, enable = cockpit
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=1000, deviceScaleFactor=1, mobile=False)
    stable_roster(js);enable(count=1)
    item = dict(direction=direction, sender=sender, recipients=recipients or ['KnownPeer'], importance=importance,
                subject='Generated Mail subject', body='Literal <script> text and https://example.com/source', coverage='request' if direction=='sent' else 'complete')
    js("""conversationView.close();
      Object.assign(currentAgents[0],{provider:'anthropic',program:'claude-code'});
      currentAgents.push({name:'KnownPeer',provider:'openai',program:'codex'},
        {name:'LocalPeer',provider:'local',model:'GLM 4.7',model_raw:'glm-4.7',program:'custom'},
        {name:'UnknownPeer',provider:'unknown',program:'custom',model:'custom'});
      window.mailCard="""+json.dumps(item)+""";
      OrreryConversationSource.Source.prototype.read=async()=>({provider:'claude',mode:'cursor',after:'tail',
        events:[{id:'mail-card',kind:'mail',role:'user',ts:'2026-11-09T13:20:00Z',text:'',mail:[mailCard]}]});
      OrreryColorTheme.setPreference("""+json.dumps(theme)+""");conversationView.open();
      """)
    wait("document.querySelector('.conversation-panel:not([hidden]) .conversation-mail')!==null")
    js("window.mailReader=document.querySelector('.conversation-panel:not([hidden])')")
    wait_reading_layout(js)
    return js, wait, client, requests


@pytest.mark.parametrize('direction', ['received', 'sent'])
@pytest.mark.parametrize('peer,asset', [('KnownPeer', 'openai'), ('LocalPeer', 'glm')])
def test_received_and_sent_routes_use_roster_provider_marks(cockpit, direction, peer, asset):
    js, wait, client, _ = prepare(cockpit, direction=direction, sender=peer, recipients=[peer])
    names = [peer, 'ReviewFixture'] if direction=='received' else ['ReviewFixture', peer]
    assert js("[...mailReader.querySelectorAll('.conversation-mail-peer-name')].map(e=>e.textContent)") == names
    assert js("mailReader.querySelectorAll('.conversation-avatar').length")==2
    assert js("[...mailReader.querySelectorAll('.conversation-avatar')].every(e=>e.getBoundingClientRect().width===18)")
    expected = [asset, 'anthropic'] if direction=='received' else ['anthropic', asset]
    wait("[...mailReader.querySelectorAll('.conversation-mail-peer .provider-badge img')].filter(e=>e.naturalWidth>0).length===2")
    assert js("[...mailReader.querySelectorAll('.conversation-mail-peer .provider-badge img')].map(e=>e.getAttribute('src'))") == ['cockpit-assets/'+a+'.svg' for a in expected]


def test_multiple_recipients_show_every_name_and_full_accessible_route(cockpit):
    js, wait, client, _ = prepare(cockpit, direction='sent', recipients=['KnownPeer', 'LocalPeer', 'UnknownPeer'])
    assert js("mailReader.querySelector('.conversation-mail-more').hidden")
    assert js("[...mailReader.querySelectorAll('.conversation-mail-peer-name')].map(e=>e.textContent)") == ['ReviewFixture', 'KnownPeer', 'LocalPeer', 'UnknownPeer']
    label = js("mailReader.querySelector('summary').getAttribute('aria-label')")
    assert all(name in label for name in ['KnownPeer', 'LocalPeer', 'UnknownPeer'])


@pytest.mark.parametrize('peer', ['UnregisteredOpenAIPeer','knownpeer','KnownPeer ','UnknownPeer'])
def test_unknown_peer_does_not_guess_a_provider(cockpit, peer):
    js, wait, client, _ = prepare(cockpit, sender=peer)
    selector = '.conversation-mail-peer[data-peer-name='+json.dumps(peer)+']'
    assert not js('!!mailReader.querySelector('+json.dumps(selector)+').querySelector(".provider-badge img[src]")')
    assert js('!!mailReader.querySelector('+json.dumps(selector)+').querySelector(".conversation-avatar")') == (peer=='UnknownPeer')
    assert js('mailReader.querySelector('+json.dumps(selector)+').querySelector(".conversation-mail-peer-name").textContent') == peer


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_phone_elides_names_but_keeps_marks_route_and_time(cockpit, theme):
    js, wait, client, _ = prepare(cockpit, width=390, theme=theme)
    js("""window.longPeer='KnownPeerWithAnExceptionallyLongAgentName';
      currentAgents.push({name:longPeer,provider:'openai'});mailCard.sender=longPeer;
      conversationView.close();conversationView.open();""")
    wait("document.querySelector('.conversation-panel:not([hidden]) .conversation-mail-peer-name')?.textContent===longPeer")
    js("mailReader=document.querySelector('.conversation-panel:not([hidden])')")
    wait_reading_layout(js)
    assert js("(()=>{const n=mailReader.querySelector('.conversation-mail-peer-name');return n.scrollWidth>n.clientWidth&&getComputedStyle(n).textOverflow==='ellipsis'})()")
    assert js("[...mailReader.querySelectorAll('.conversation-mail-peer .conversation-avatar')].every(e=>e.getBoundingClientRect().width>=16)")
    assert js("(()=>{const h=mailReader.querySelector('.conversation-mail-head'),r=h.getBoundingClientRect(),t=h.querySelector('time').getBoundingClientRect();return h.scrollWidth<=h.clientWidth+1&&t.right<=r.right+1&&t.top>=r.top&&t.bottom<=r.bottom+1})()")


@pytest.mark.parametrize('importance', ['low', 'normal', 'high', 'urgent'])
def test_importance_is_a_small_subject_mark(cockpit, importance):
    js, wait, client, _ = prepare(cockpit, importance=importance)
    assert js("mailReader.querySelector('.conversation-mail-subject-row .conversation-mail-importance')!==null")
    if importance in ['high', 'urgent']:
        assert js("(()=>{const r=mailReader.querySelector('.conversation-mail-importance').getBoundingClientRect();return r.width>0&&r.width<=6&&r.height<=6})()")
    assert importance in js("mailReader.querySelector('summary').getAttribute('aria-label')").lower()


def test_roster_refresh_preserves_open_body_and_focus(cockpit):
    js, wait, client, requests = prepare(cockpit)
    js("mailReader.querySelector('summary').focus()")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    wait("mailReader.querySelector('details').open")
    js("window.keptMailBody=mailReader.querySelector('.conversation-mail-content');Object.assign(currentAgents.find(a=>a.name==='KnownPeer'),{provider:'google'});document.dispatchEvent(new Event('oc:agents'))")
    wait("mailReader.querySelector('.conversation-mail-peer .provider-badge img')?.getAttribute('src')==='cockpit-assets/google.svg'")
    assert js("mailReader.querySelector('details').open&&keptMailBody===mailReader.querySelector('.conversation-mail-content')")
    assert js("document.activeElement===mailReader.querySelector('summary')")
    assert js("keptMailBody.querySelector('script')") is None
    assert js("keptMailBody.querySelector('a').getAttribute('href')") == 'https://example.com/source'
    assert 'delivery' not in js("keptMailBody.querySelector('.conversation-mail-notice').textContent")
    assert js("packets.filter(p=>p.type==='input')") == []
    assert not [p for p in requests if p.startswith('/telemetry/mail/message')]
    js("currentAgents=currentAgents.filter(a=>a.name!=='KnownPeer');document.dispatchEvent(new Event('oc:agents'))")
    assert not js("mailReader.querySelector('.conversation-mail-peer').querySelector('.conversation-avatar')")
    assert js("mailReader.querySelector('details').open&&keptMailBody===mailReader.querySelector('.conversation-mail-content')")


@pytest.mark.parametrize('theme',['dark','light'])
def test_phone_split_preserves_full_recipient_count_and_readable_names(cockpit,theme):
    recipients=['KnownPeerWithALongName']+['GeneratedPeer'+str(i) for i in range(23)]
    js,wait,client,_=prepare(cockpit,direction='sent',recipients=recipients,width=390,theme=theme)
    js("currentAgents.push({name:'KnownPeerWithALongName',provider:'openai'},{name:'OtherFixture',program:'codex',history_binding:'bound'});createPane('OtherFixture',{paneId:'%902',windowId:'@902',width:80,height:20});replaceSplitSessions(['ReviewFixture','OtherFixture']);splitVisible=true;focusSplitSession('ReviewFixture')")
    wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-mail')!==null")
    wait_reading_layout(js)
    state=js("""(()=>{const head=document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-mail-head'),route=head.querySelector('.conversation-mail-route'),r=route.getBoundingClientRect(),c=route.querySelector('.conversation-mail-more'),t=head.querySelector('time').getBoundingClientRect(),h=head.getBoundingClientRect();return {count:c.textContent,inside:c.getBoundingClientRect().right<=r.right+.5,sender:route.querySelector('.conversation-mail-sender .conversation-mail-peer-name').getBoundingClientRect().width,shown:route.querySelectorAll('.conversation-mail-recipients .conversation-mail-peer:not([hidden])').length,marks:[...route.querySelectorAll('.conversation-avatar,.conversation-mail-arrow')].every(e=>{const q=e.getBoundingClientRect();return q.left>=r.left-.5&&q.right<=r.right+.5}),time:t.right<=h.right+.5&&t.bottom<=h.bottom+.5}})()""")
    assert state['count']=='+23' and state['inside'] and state['marks'] and state['time'],state
    assert state['sender']>=8 and state['shown']==1,state


def split_mail(js,wait):
    js("currentAgents.push({name:'OtherFixture',program:'codex',history_binding:'bound'});createPane('OtherFixture',{paneId:'%902',windowId:'@902',width:80,height:20});replaceSplitSessions(['ReviewFixture','OtherFixture']);splitVisible=true;focusSplitSession('ReviewFixture')")
    wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-mail')!==null")
    js("mailReader=document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-panel')")
    wait_reading_layout(js)


@pytest.mark.parametrize('theme',['dark','light'])
def test_mail_route_selection_excludes_avatar_initials(cockpit,theme):
    js,wait,_,_=prepare(cockpit,theme=theme)
    selected=js("""(()=>{const r=document.createRange();r.selectNodeContents(mailReader.querySelector('.conversation-mail-route'));getSelection().removeAllRanges();getSelection().addRange(r);return getSelection().toString()})()""")
    assert 'KnownPeer' in selected and 'ReviewFixture' in selected
    assert not any(line.strip() in ['K','R'] for line in selected.splitlines()),selected


@pytest.mark.parametrize('theme',['dark','light'])
def test_normal_reader_wraps_all_eight_names_without_a_count(cockpit,theme):
    names=['GeneratedPeer'+str(i) for i in range(8)]
    js,wait,_,_=prepare(cockpit,direction='sent',recipients=names,theme=theme)
    assert js("[...mailReader.querySelectorAll('.conversation-mail-recipients .conversation-mail-peer-name')].map(e=>e.textContent)")==names
    assert js("mailReader.querySelector('.conversation-mail-more').hidden")
    assert js("new Set([...mailReader.querySelectorAll('.conversation-mail-recipients .conversation-mail-peer')].map(e=>e.getBoundingClientRect().top)).size>1")
    assert not js("mailReader.querySelector('.conversation-mail-route').classList.contains('is-compact')")


@pytest.mark.parametrize('width',[1800,1100,390])
@pytest.mark.parametrize('count',[1,3,8])
def test_recipient_layout_preserves_sender_at_wide_medium_and_narrow_widths(cockpit,count,width):
    names=(['KnownPeer','LocalPeer','UnlistedPeer']+['GeneratedPeer'+str(i) for i in range(5)])[:count]
    js,wait,client,_=prepare(cockpit,direction='sent',recipients=names,width=width)
    js("for(let i=0;i<5;i++)currentAgents.push({name:'GeneratedPeer'+i,provider:'openai'})")
    if width!=1800:split_mail(js,wait)
    value=js("""(()=>{const r=mailReader.querySelector('.conversation-mail-route'),peers=[...r.querySelectorAll('.conversation-mail-recipients .conversation-mail-peer')],shown=peers.filter(e=>!e.hidden),more=r.querySelector('.conversation-mail-more'),sender=r.querySelector('.conversation-mail-sender .conversation-mail-peer-name');return {panel:mailReader.getBoundingClientRect().width,inside:shown.every(e=>{const b=e.getBoundingClientRect(),a=r.getBoundingClientRect();return b.left>=a.left-.5&&b.right<=a.right+.5})&&(more.hidden||more.getBoundingClientRect().right<=r.getBoundingClientRect().right+.5),compact:r.classList.contains('is-compact'),shown:shown.map(e=>e.dataset.peerName),hidden:more.hidden,count:more.textContent,sender:sender.getBoundingClientRect().width,full:sender.scrollWidth,names:shown.map(e=>e.querySelector('.conversation-mail-peer-name').getBoundingClientRect().width),unknownFace:!!r.querySelector('[data-peer-name=UnlistedPeer] .conversation-avatar'),title:r.title}})()""")
    assert value['compact']==(count>1 and value['panel']<300)
    assert value['inside'],value
    assert value['sender']>=value['full']-1,value
    assert not value['unknownFace']
    if not value['compact']:
        assert all(width>=8 for width in value['names']) and value['hidden']
        assert value['shown']==names
    else:
        known=[name for name in names if name!='UnlistedPeer']
        assert value['shown']==known[:len(value['shown'])] and value['shown']
        assert value['names']==[0]*len(value['shown'])
        assert value['count']=='+'+str(count-len(value['shown']))
    assert all(name in value['title'] for name in names)


def test_width_and_roster_changes_keep_mail_body_and_restore_all_names(cockpit):
    names=['KnownPeer','LocalPeer','UnlistedPeer']
    js,wait,client,_=prepare(cockpit,direction='sent',recipients=names,width=390)
    split_mail(js,wait)
    js("mailReader.querySelector('summary').click();window.keptMailDetails=mailReader.querySelector('details');window.keptMailText=mailReader.querySelector('.conversation-mail-text');keptMailDetails.querySelector('summary').focus();currentAgents.push({name:'UnlistedPeer',provider:'google'});document.dispatchEvent(new Event('oc:agents'))")
    wait("!mailReader.querySelector('.conversation-mail-more').textContent")
    assert js("mailReader.querySelectorAll('.conversation-mail-recipients .conversation-mail-peer:not([hidden])').length")==3
    client.call('Emulation.setDeviceMetricsOverride',width=1800,height=1000,deviceScaleFactor=1,mobile=False)
    js("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-expand').click()")
    wait("mailReader.getBoundingClientRect().width>=300")
    wait_reading_layout(js)
    assert not js("mailReader.querySelector('.conversation-mail-route').classList.contains('is-compact')")
    assert js("[...mailReader.querySelectorAll('.conversation-mail-recipients .conversation-mail-peer-name')].every(e=>e.getBoundingClientRect().width>0)")
    assert js("keptMailDetails===mailReader.querySelector('details')&&keptMailDetails.open&&keptMailText===mailReader.querySelector('.conversation-mail-text')")


def test_narrow_unregistered_recipients_are_counted_without_fabricated_faces(cockpit):
    js,wait,_,_=prepare(cockpit,direction='sent',recipients=['UnlistedOne','UnlistedTwo'],width=390)
    split_mail(js,wait)
    assert js("mailReader.querySelectorAll('.conversation-mail-recipients .conversation-avatar').length")==0
    assert js("mailReader.querySelector('.conversation-mail-more').textContent")=='+2'
    assert js("[...mailReader.querySelectorAll('.conversation-mail-recipients .conversation-mail-peer')].every(e=>e.hidden)")
    assert all(name in js("mailReader.querySelector('summary').ariaLabel") for name in ['UnlistedOne','UnlistedTwo'])


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('width',[1600,390])
def test_open_mail_thread_tracks_sender_and_body_end(cockpit,theme,width):
    js,wait,client,_=prepare(cockpit,direction='sent',recipients=['KnownPeer','LocalPeer','UnlistedPeer'],theme=theme,width=width)
    if width==390:split_mail(js,wait)
    js("window.threadCard=mailReader.querySelector('.conversation-mail')")
    assert js("threadCard.querySelector('.conversation-mail-thread')!==null")
    assert js("threadCard.querySelector('.conversation-mail-thread').getClientRects().length===0")
    js("threadCard.querySelector('summary').click()")
    wait("threadCard.querySelector('.conversation-mail-thread').getBoundingClientRect().height>0")
    wait_reading_layout(js)
    def geometry():
        return js("""(()=>{const t=threadCard.querySelector('.conversation-mail-thread'),l=t.getBoundingClientRect(),a=threadCard.querySelector('.conversation-mail-sender .conversation-avatar').getBoundingClientRect(),b=threadCard.querySelector('.conversation-mail-text').getBoundingClientRect();return {x:Math.abs((l.left+l.width/2)-(a.left+a.width/2)),top:l.top-a.bottom,end:Math.abs(l.bottom-b.bottom),width:l.width,decorative:t.getAttribute('aria-hidden')==='true'&&getComputedStyle(t).userSelect==='none'&&getComputedStyle(t).pointerEvents==='none',empty:t.textContent==='',right:b.left>l.right}})()""")
    value=geometry()
    assert value['x']<=1 and value['end']<=1 and value['width']==1 and 0<=value['top']<=4,value
    assert value['decorative'] and value['empty'] and value['right'],value
    wait("threadCard.querySelector('.conversation-mail-sender .face img').style.display==='none'")
    assert js("threadCard.querySelector('.conversation-mail-sender .ini').textContent==='R'")
    # Reflow an already open card; the sender and body must remain its anchors.
    client.call('Emulation.setDeviceMetricsOverride',width=1800 if width==390 else 1100,height=1000,deviceScaleFactor=1,mobile=False)
    wait_reading_layout(js)
    value=geometry()
    assert value['x']<=1 and value['end']<=1,value
    js("threadCard.querySelector('summary').click()")
    wait("threadCard.querySelector('.conversation-mail-thread').getClientRects().length===0")


def test_wrapped_mail_recipients_leave_the_sender_thread_column_clear(cockpit):
    names=['KnownPeer','LocalPeer']+['GeneratedPeer'+str(i) for i in range(6)]
    js,wait,_,_=prepare(cockpit,direction='sent',recipients=names,width=1200)
    js("for(let i=0;i<6;i++)currentAgents.push({name:'GeneratedPeer'+i,provider:'openai'});document.dispatchEvent(new Event('oc:agents'));mailReader.querySelector('summary').click()")
    wait("mailReader.querySelector('.conversation-mail-thread')?.getBoundingClientRect().height>0")
    value=js("""(()=>{const d=mailReader.querySelector('.conversation-mail'),a=d.querySelector('.conversation-mail-sender .conversation-avatar').getBoundingClientRect(),line=d.querySelector('.conversation-mail-thread').getBoundingClientRect(),wrapped=[...d.querySelectorAll('.conversation-mail-recipients .conversation-avatar')].map(e=>e.getBoundingClientRect()).filter(r=>r.top>a.bottom);return {wrapped:wrapped.length,clear:wrapped.every(r=>r.left>line.right)}})()""")
    assert value['wrapped']>0 and value['clear'],value
