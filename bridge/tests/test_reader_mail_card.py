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
    expected = [asset, 'anthropic'] if direction=='received' else ['anthropic', asset]
    wait("[...mailReader.querySelectorAll('.conversation-mail-peer img')].filter(e=>e.naturalWidth>0).length===2")
    assert js("[...mailReader.querySelectorAll('.conversation-mail-peer img')].map(e=>e.getAttribute('src'))") == ['cockpit-assets/'+a+'.svg' for a in expected]


def test_multiple_recipients_keep_the_first_and_full_accessible_route(cockpit):
    js, wait, client, _ = prepare(cockpit, direction='sent', recipients=['KnownPeer', 'LocalPeer', 'UnknownPeer'])
    assert js("mailReader.querySelector('.conversation-mail-more').textContent") == '+2'
    assert js("[...mailReader.querySelectorAll('.conversation-mail-peer-name')].map(e=>e.textContent)") == ['ReviewFixture', 'KnownPeer']
    label = js("mailReader.querySelector('summary').getAttribute('aria-label')")
    assert all(name in label for name in ['KnownPeer', 'LocalPeer', 'UnknownPeer'])


@pytest.mark.parametrize('peer', ['UnregisteredOpenAIPeer', 'UnknownPeer'])
def test_unknown_peer_does_not_guess_a_provider(cockpit, peer):
    js, wait, client, _ = prepare(cockpit, sender=peer)
    selector = '.conversation-mail-peer[data-peer-name='+peer+']'
    assert not js('mailReader.querySelector('+json.dumps(selector)+').querySelector("img")')
    assert js('mailReader.querySelector('+json.dumps(selector)+').textContent') == peer


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
    assert js("[...mailReader.querySelectorAll('.conversation-mail-peer .pane-provider')].every(e=>e.getBoundingClientRect().width>=16)")
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
    wait("mailReader.querySelector('.conversation-mail-peer img')?.getAttribute('src')==='cockpit-assets/google.svg'")
    assert js("mailReader.querySelector('details').open&&keptMailBody===mailReader.querySelector('.conversation-mail-content')")
    assert js("document.activeElement===mailReader.querySelector('summary')")
    assert js("keptMailBody.querySelector('script')") is None
    assert js("keptMailBody.querySelector('a').getAttribute('href')") == 'https://example.com/source'
    assert 'delivery' not in js("keptMailBody.querySelector('.conversation-mail-notice').textContent")
    assert js("packets.filter(p=>p.type==='input')") == []
    assert not [p for p in requests if p.startswith('/telemetry/mail/message')]
    js("currentAgents=currentAgents.filter(a=>a.name!=='KnownPeer');document.dispatchEvent(new Event('oc:agents'))")
    assert not js("mailReader.querySelector('.conversation-mail-peer').querySelector('.pane-provider')")
    assert js("mailReader.querySelector('details').open&&keptMailBody===mailReader.querySelector('.conversation-mail-content')")


@pytest.mark.parametrize('theme',['dark','light'])
def test_phone_split_preserves_full_recipient_count_and_readable_names(cockpit,theme):
    recipients=['KnownPeerWithALongName']+['GeneratedPeer'+str(i) for i in range(23)]
    js,wait,client,_=prepare(cockpit,direction='sent',recipients=recipients,width=390,theme=theme)
    js("currentAgents.push({name:'KnownPeerWithALongName',provider:'openai'},{name:'OtherFixture',program:'codex',history_binding:'bound'});createPane('OtherFixture',{paneId:'%902',windowId:'@902',width:80,height:20});replaceSplitSessions(['ReviewFixture','OtherFixture']);splitVisible=true;focusSplitSession('ReviewFixture')")
    wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-mail')!==null")
    wait_reading_layout(js)
    state=js("""(()=>{const head=document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-mail-head'),route=head.querySelector('.conversation-mail-route'),r=route.getBoundingClientRect(),c=route.querySelector('.conversation-mail-more'),t=head.querySelector('time').getBoundingClientRect(),h=head.getBoundingClientRect();return {count:c.textContent,inside:c.getBoundingClientRect().right<=r.right+.5,names:[...route.querySelectorAll('.conversation-mail-peer-name')].map(e=>e.getBoundingClientRect().width),marks:[...route.querySelectorAll('.pane-provider,.conversation-mail-arrow')].every(e=>{const q=e.getBoundingClientRect();return q.left>=r.left-.5&&q.right<=r.right+.5}),time:t.right<=h.right+.5&&t.bottom<=h.bottom+.5}})()""")
    assert state['count']=='+23' and state['inside'] and state['marks'] and state['time'],state
    assert all(width>=8 for width in state['names']),state
