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


def test_compaction_is_one_expandable_system_row_beside_a_human_prompt(cockpit, tmp_path):
    path = tmp_path / 'fixture.jsonl'
    path.write_bytes(line(claude('user', 'Generated compacted summary.', isCompactSummary=True)) +
                     line(claude('user', 'Generated human request.')))
    events = page(row(path, 'claude-code'))['events']
    js, wait, client = prepare(cockpit)
    js('OrreryConversationSource.Source.prototype.read=async()=>({events:' + json.dumps(events) +
       ",provider:'claude',after:'end'});conversationView.open()")
    wait("document.querySelectorAll('.conversation-event').length===2")
    assert js("document.querySelector('.conversation-system-toggle').textContent") == '▸Context compacted'
    assert js("[...document.querySelectorAll('.conversation-role')].map(e=>e.textContent)") == ['You']
    assert js("document.querySelector('.conversation-system-detail').hidden")
    js("document.querySelector('.conversation-system-toggle').focus()")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    wait("!document.querySelector('.conversation-system-detail').hidden")
    assert js("document.querySelector('.conversation-system-detail').textContent") == 'Generated compacted summary.'
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
