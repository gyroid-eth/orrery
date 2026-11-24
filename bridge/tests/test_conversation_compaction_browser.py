"""Real Reader rendering and automatic session rollover on a private HTTP fixture."""
import json
import time

import pytest

from test_conversation_review_regressions import cockpit, stable_roster
from test_conversation_compaction import claude, line, page, row


def prepare(cockpit):
    js, wait, client, _, enable = cockpit
    stable_roster(js)
    enable(count=1)
    js('conversationView.close()')
    return js, wait, client


@pytest.mark.parametrize('delivery', ['initial', 'append', 'earlier'])
def test_compaction_is_one_expandable_system_row_beside_a_human_prompt(cockpit, tmp_path, delivery):
    path = tmp_path / 'fixture.jsonl'
    path.write_bytes(b''.join(line(record) for record in [
        claude('user', 'Generated compacted summary.', isCompactSummary=True),
        claude('user', '<local-command-caveat>Fixture native command</local-command-caveat>', isMeta=True),
        claude('user', '<command-name>/compact</command-name>\n<command-message>compact</command-message>'
                       '\n<command-args>Keep chart labels &lt;exact&gt;.</command-args>'),
        claude('user', '<local-command-stdout>\x1b[2mCompacted (ctrl+o to see full summary)\x1b[22m\n'
                       '\x1b[2mPreCompact [fixture hook] completed\x1b[22m</local-command-stdout>'),
        claude('user', 'Generated human request.'),
    ]))
    events = page(row(path, 'claude-code'))['events']
    first = {'initial': events, 'append': events[:1], 'earlier': events[1:]}[delivery]
    js, wait, client = prepare(cockpit)
    js('window.compactFirst=' + json.dumps(first) + ';window.compactAll=' + json.dumps(events) + ';' +
       """OrreryConversationSource.Source.prototype.read=async(name,options)=>({
         events:options.before?compactAll.slice(0,1):options.after?compactAll.slice(1):compactFirst,
         provider:'claude',before:'start',after:'end',has_older:!options.before
       });conversationView.open()""")
    wait(f"document.querySelectorAll('.conversation-event').length==={len(first)}")
    if delivery == 'append':
        js('conversationView.refresh()')
    elif delivery == 'earlier':
        js("document.querySelector('.conversation-older').click()")
    wait("document.querySelectorAll('.conversation-event').length===4")
    assert js("document.querySelectorAll('.conversation-event:not([hidden])').length") == 2
    assert js("document.querySelector('.conversation-system-toggle').textContent") == '▸Context compacted'
    assert js("[...document.querySelectorAll('.conversation-human')].map(e=>e.getAttribute('aria-label'))") == ['You']
    assert js("document.querySelector('.conversation-system-detail').hidden")
    assert js("document.querySelectorAll('.conversation-code').length") == 0
    js("document.querySelector('.conversation-system-toggle').focus()")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    wait("!document.querySelector('.conversation-system-detail').hidden")
    assert js("document.querySelector('.conversation-system-detail').textContent") == (
        'Instructions: Keep chart labels <exact>.\n\nGenerated compacted summary.')
    js("document.querySelector('.conversation-system-toggle').click()")
    assert js("document.querySelector('.conversation-system-detail').hidden")
    assert js("packets.filter(p=>p.type==='input')") == []


def changed_source(js, *, repeated=False):
    js("""window.sessionReads=[];OrreryConversationSource.Source.prototype.read=async(name,options)=>{
      sessionReads.push({before:options.before??null,after:options.after??null,at:performance.now()});
      if(""" + ('true' if repeated else 'sessionReads.length===1') + """)throw Object.assign(new Error('changed'),{code:'history_changed'});
      return {events:[{id:'new-session',kind:'text',role:'user',text:'Fresh session body'}],before:'new-start',after:'new-end'};
    };conversationView.refresh();""")


def test_changed_session_clears_old_content_and_reloads_without_retry(cockpit):
    js, wait, client, _, enable = cockpit
    stable_roster(js);enable(count=2)
    changed_source(js)
    wait("document.querySelectorAll('.conversation-event').length===0")
    assert js("document.querySelector('.conversation-retry').hidden")
    assert js("document.querySelector('.conversation-empty').textContent") == 'New session'
    wait("document.querySelector('[data-event-id=new-session]')!==null")
    assert js("document.querySelectorAll('.conversation-event').length") == 1
    assert js("document.querySelector('.conversation-retry').hidden")
    calls = js('sessionReads')
    assert len(calls) == 2 and calls[1]['before'] is None and calls[1]['after'] is None


def test_repeated_changed_errors_get_one_short_retry_then_normal_poll(cockpit):
    js, wait, client, _, enable = cockpit
    stable_roster(js);enable(count=1)
    changed_source(js, repeated=True)
    wait('sessionReads.length===2')
    time.sleep(.8)
    assert js('sessionReads.length') == 2
    assert js("document.querySelector('.conversation-retry').hidden")
    wait('sessionReads.length===3')
    calls = js('sessionReads')
    assert calls[2]['at'] - calls[1]['at'] >= 3500


def test_closing_reader_cancels_pending_session_reload(cockpit):
    js, wait, client, _, enable = cockpit
    stable_roster(js);enable(count=1)
    changed_source(js, repeated=True)
    wait('sessionReads.length===1')
    js('conversationView.close()')
    time.sleep(.6)
    assert js('sessionReads.length') == 1


@pytest.mark.parametrize('code', ['record_too_large', 'provider_unavailable', 'dashboard_upgrade_required'])
def test_permanent_reader_errors_still_require_retry(cockpit, code):
    js, wait, client, _, enable = cockpit
    stable_roster(js);enable(count=1)
    js("window.permanentReads=0;OrreryConversationSource.Source.prototype.read=async()=>{permanentReads++;throw Object.assign(new Error('fixture permanent error'),{code:" + json.dumps(code) + "})};conversationView.refresh()")
    wait("!document.querySelector('.conversation-retry').hidden")
    time.sleep(.6)
    assert js('permanentReads') == 1
