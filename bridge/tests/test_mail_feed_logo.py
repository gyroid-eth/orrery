"""The Mail rail uses current roster marks without changing message actions."""
import json

import pytest
from test_conversation_review_regressions import cockpit, stable_roster


def prepare(cockpit,theme='dark',rail_width=320):
    js,wait,client,requests,_=cockpit
    stable_roster(js)
    wait("document.querySelector('#mail .mailcards')!==null")
    # Discard bootstrap roster responses started before this fixture was installed.
    js("""rosterAnnotationEpoch++;currentAgents=[{name:'SenderFixture',provider:'anthropic',program:'claude-code'},
      {name:'RecipientFixture',provider:'openai',program:'codex'},
      {name:'LocalFixture',provider:'local',program:'hermes',model:'GLM 4.7',model_raw:'glm-4.7'}];
      window.feedMessages=[{id:101,sender:'SenderFixture',recipients:['RecipientFixture'],subject:'Generated high importance update',importance:'high',ts:Date.now()/1000},
        {id:102,sender:'LocalFixture',recipients:['SenderFixture','RecipientFixture','MissingFixture'],subject:'Generated normal update',importance:'normal',ts:Date.now()/1000-10},
        {id:103,sender:'MissingFixture',recipients:['SenderFixture'],subject:'Literal <img src=x> subject',importance:'normal',ts:Date.now()/1000-20}];
      document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:feedMessages}}));
      OrreryColorTheme.setPreference("""+json.dumps(theme)+""");
      document.querySelector('.grid').style.gridTemplateColumns="""+json.dumps(f'250px minmax(0,1fr) {rail_width}px')+""";
      document.querySelectorAll('#mail .msg').forEach(c=>{c.style.animation='none';c.style.opacity='1';c.style.transform='none'});
      """)
    wait("document.querySelectorAll('#mail .msg').length===3")
    assert abs(js("document.querySelector('.col.mail').getBoundingClientRect().width")-rail_width)<=1
    return js,wait,client,requests


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('rail_width',[320,220])
def test_sender_and_each_recipient_share_header_marks_and_keep_badges(cockpit,theme,rail_width):
    js,wait,_,_=prepare(cockpit,theme,rail_width)
    assert js("document.querySelectorAll('#mail .mail-peer .pane-provider').length")==6
    wait("[...document.querySelectorAll('#mail .mail-peer img')].every(i=>i.naturalWidth>0)")
    assert js("[...document.querySelectorAll('#mail .msg[data-mid=\"101\"] .provider-logo')].map(i=>i.getAttribute('src'))")==['cockpit-assets/anthropic.svg','cockpit-assets/openai.svg']
    assert js("document.querySelector('#mail .msg[data-mid=\"102\"] .from img').getAttribute('src')")=='cockpit-assets/glm.svg'
    assert not js("[...document.querySelectorAll('#mail .mail-peer')].filter(p=>p.dataset.peerName==='MissingFixture').some(p=>p.querySelector('.pane-provider'))")
    assert js("[...document.querySelectorAll('#mail .imp')].map(p=>[p.textContent,p.className])")==[['high','imp hi'],['normal','imp '],['normal','imp ']]
    assert js("[...document.querySelectorAll('#mail .msg .mtop')].every(h=>{const r=h.getBoundingClientRect(),b=h.querySelector('.imp').getBoundingClientRect();return h.scrollWidth<=h.clientWidth+1&&b.right<=r.right+1&&b.left>=r.left})")
    assert js("[...document.querySelectorAll('#mail .pane-provider')].every(p=>p.getBoundingClientRect().width===16&&!p.classList.contains('is-working'))")
    assert js("document.querySelector('#mail .msg[data-mid=\"102\"] .to').textContent")=='SenderFixture, RecipientFixture, MissingFixture'
    assert not js("document.querySelector('#mail .body img')")


def test_roster_refresh_updates_marks_without_rebuilding_focused_cards(cockpit):
    js,wait,_,_=prepare(cockpit)
    js("window.keptCard=document.querySelector('#mail .msg');keptCard.focus();currentAgents[0].provider='google';document.dispatchEvent(new Event('oc:agents'))")
    wait("keptCard.querySelector('.from img')?.getAttribute('src')==='cockpit-assets/google.svg'")
    assert js("document.activeElement===keptCard&&keptCard===document.querySelector('#mail .msg')")
    assert 'Gemini' in js("keptCard.querySelector('.from .pane-provider').getAttribute('aria-label')")
    js("currentAgents=currentAgents.filter(a=>a.name!=='SenderFixture');document.dispatchEvent(new Event('oc:agents'))")
    assert not js("keptCard.querySelector('.from .pane-provider')")
    assert js("keptCard.querySelector('.from').textContent")=='SenderFixture'


def test_logo_click_and_keyboard_still_open_the_message(cockpit):
    js,wait,client,requests=prepare(cockpit)
    js("window.feedFetch=window.fetch;window.fetch=(url,...args)=>String(url).startsWith('/telemetry/mail/message')?Promise.resolve(new Response(JSON.stringify({message:{...feedMessages[0],body_md:'Generated detail body'}}))):feedFetch(url,...args)")
    wait("document.querySelector('#mail .msg .pane-provider img')?.naturalWidth>0")
    js("document.querySelector('#mail .msg .pane-provider').click()")
    wait("document.querySelector('#mail .maildrawer').classList.contains('open')&&document.querySelector('#mail .mail-md')?.textContent.includes('Generated detail body')")
    js("document.querySelector('#mail [data-action=close]').click();document.querySelector('#mail .msg').focus()")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',code='Enter',windowsVirtualKeyCode=13,text='\r')
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',code='Enter',windowsVirtualKeyCode=13)
    wait("document.querySelector('#mail .maildrawer').classList.contains('open')")
    assert not js("document.querySelector('#mail .maildrawer .pane-provider')")
