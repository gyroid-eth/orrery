"""Desktop Reader navigation keeps person controls separate from message actions."""
import json

import pytest

from test_conversation_review_regressions import cockpit, open_agents_fixture


PROGRAMS = {'ReviewFixture': 'codex', 'BuildFixture': 'claude-code', 'AuditFixture': 'codex'}
SOURCE_ROWS = [
    dict(id='answer', kind='text', role='assistant', text='Generated Review answer'),
    dict(id='parent', kind='text', role='user',
         text='あなたは ReviewFixture（親: BuildFixture）。この起動は --embed-task mode です。'
              'ORRERY Mail への登録は親が完了済み・儀式不要です。 Generated parent request.'),
    dict(id='received', kind='mail', role='user', text='', mail=[
        dict(direction='received', sender='BuildFixture', subject='Generated received subject',
             body='Generated received body', coverage='complete')]),
    dict(id='sent', kind='mail', role='user', text='', mail=[
        dict(direction='sent', recipients=['AuditFixture', 'UnknownFixture'], subject='Generated sent subject',
             body='Generated sent body', coverage='request')]),
]


def prepare(cockpit):
    js, wait, client, _, _ = cockpit
    client.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    open_agents_fixture(cockpit, PROGRAMS)
    js("""openFixtureAgent('ReviewFixture');finishAgentAttach('ReviewFixture',901);
      currentAgents.find(a=>a.name==='ReviewFixture').parent_agent='BuildFixture';
      window.navigationRows=""" + json.dumps(SOURCE_ROWS) + """;
      OrreryConversationSource.Source.prototype.read=async name=>({mode:'cursor',after:'tail',
        has_older:false,events:name==='ReviewFixture'?navigationRows:[{id:'destination',kind:'text',
          role:'assistant',text:'Generated Reader for '+name}]});
      conversationView.open();
      document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[{id:501,sender:'BuildFixture',
        recipients:['ReviewFixture','AuditFixture','UnknownFixture'],subject:'Generated rail subject',
        ts:2000000000,body_md:'Generated rail body'}]}}));""")
    wait("document.querySelector('[data-event-id=sent] .conversation-mail-peer')!==null")
    wait("document.querySelector('.mail-request .mail-peer[data-agent-name=AuditFixture]')!==null")
    wait("""[...document.querySelectorAll('.mail-assignment')].every(row=>
      row.getAnimations({subtree:true}).every(animation=>animation.playState!=='running'))""")
    return js, wait, client


def activate(js, client, selector, action):
    target = 'document.querySelector(' + json.dumps(selector) + ')'
    if action == 'enter':
        js(target + '.focus()')
        assert js('document.activeElement===' + target)
        client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter',
                    windowsVirtualKeyCode=13, text='\r')
        client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter',
                    windowsVirtualKeyCode=13)
    else:
        point = js("""(()=>{const el=""" + target + """,r=el.getBoundingClientRect();
          return {x:r.x+r.width/2,y:r.y+r.height/2}})()""")
        client.call('Input.dispatchMouseEvent', type='mouseMoved', **point)
        for event in ('mousePressed', 'mouseReleased'):
            client.call('Input.dispatchMouseEvent', type=event, **point, button='left', clickCount=1)


def finish_navigation(js, wait, name, pane):
    name_js = json.dumps(name)
    wait(f"packets.some(p=>p.type==='attach'&&p.session==={name_js})")
    assert js("activeSession()") == 'ReviewFixture'
    js(f"finishAgentAttach({name_js},{pane})")
    wait(f"activeSession()==={name_js}&&[...document.querySelectorAll('.conversation-panel:not([hidden]) .conversation-text')]"
         f".some(e=>e.textContent==='Generated Reader for '+{name_js})")
    assert js("packets.filter(p=>['input','submit-prompt'].includes(p.type))") == []


@pytest.mark.parametrize(('selector', 'action', 'name'), [
    ('[data-event-id=received] .conversation-mail-sender .conversation-avatar', 'click', 'BuildFixture'),
    ('[data-event-id=sent] .conversation-mail-peer[data-peer-name=AuditFixture]', 'enter', 'AuditFixture'),
    ('[data-event-id=parent] .conversation-parent .reader-agent-link', 'enter', 'BuildFixture'),
])
def test_center_mail_people_and_parent_byline_open_their_reader(cockpit, selector, action, name):
    js, wait, client = prepare(cockpit)
    js("document.querySelector('.conversation-mail-subject').click()")
    assert js("document.querySelector('[data-event-id=received] details').open")
    assert js("document.querySelector('[data-event-id=sent] [data-peer-name=UnknownFixture]').disabled")
    activate(js, client, selector, action)
    assert js("document.querySelector('[data-event-id=received] details').open")
    assert not js("document.querySelector('[data-event-id=sent] details').open")
    finish_navigation(js, wait, name, 902)


@pytest.mark.parametrize(('selector', 'action', 'name'), [
    ('.mail-request .mail-peer[data-agent-name=BuildFixture] > :last-child', 'click', 'BuildFixture'),
    ('.mail-request .mail-peer[data-agent-name=AuditFixture]', 'enter', 'AuditFixture'),
])
def test_mail_rail_routes_open_reader_without_opening_the_thread(cockpit, selector, action, name):
    js, wait, client = prepare(cockpit)
    assert not js("document.querySelector('button .mail-peer')")
    activate(js, client, selector, action)
    assert js("document.querySelector('.maildrawer').hidden")
    finish_navigation(js, wait, name, 902)


def test_rail_subject_still_opens_thread_and_drawer_peers_open_reader(cockpit):
    js, wait, client = prepare(cockpit)
    activate(js, client, '.mail-request .mail-subject', 'click')
    wait("document.querySelector('.mail-md')?.textContent==='Generated rail body'")
    activate(js, client, '.drawer-body .mail-peer[data-agent-name=AuditFixture]', 'enter')
    assert not js("document.querySelector('.maildrawer').hidden")
    finish_navigation(js, wait, 'AuditFixture', 902)


def test_speaker_button_focuses_its_already_attached_reader_in_split(cockpit):
    js, wait, client = prepare(cockpit)
    js("""openFixtureAgent('BuildFixture');finishAgentAttach('BuildFixture',902);
      replaceSplitSessions(['ReviewFixture','BuildFixture']);
      splitVisible=true;focusSplitSession('BuildFixture');""")
    speaker = '.split-cell[data-session=ReviewFixture] .conversation-speaker .reader-agent-link'
    wait("activeSession()==='BuildFixture'&&document.querySelector(" + json.dumps(speaker) + ")!==null")
    assert js("document.querySelector(" + json.dumps(speaker) + ").getAttribute('aria-label')") == 'Open ReviewFixture Reader'
    activate(js, client, speaker, 'enter')
    wait("activeSession()==='ReviewFixture'")
    assert js("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-panel:not([hidden])')!==null")
