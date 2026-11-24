"""A received native terminal status remains visible while reading older rows."""
import base64
import json
import os
from pathlib import Path

import pytest

from test_conversation_review_regressions import cockpit
from test_conversation_inline_images import prepare,message
from test_conversation_reply import PASSAGE,stage


RULE = '─' * 64
CLAUDE_COMPACT = [
    '❯ /compact Keep the labels.',
    '✶ Compacting conversation… (12s)',
    '  ⎿ \u00a0Tip: Use Plan Mode to prepare for a complex request before',
    '     making changes. Press shift+tab twice to enable.',
    '                                               ● high · /effort',
    RULE, '❯', RULE,
    '  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt',
]
DSH_COMPACT = [
    '● Summarizing earlier turns… · reading context… · 12s · Esc cancels',
    '╭'+RULE+'╮', '  ⌸ ❯                                                         ⛶',
    '╰'+RULE+'╯', 'ctx 19% (24k/128k)',
]
HERMES_COMPACT = ['─ ☤ compacting…      · 12s │ fixture-model │ 19%', ' ❯']


@pytest.mark.parametrize('cockpit', [False, True], indirect=True, ids=['desktop', 'phone'])
def test_idle_and_input_required_have_distinct_reader_labels(cockpit):
    js, wait, _ = prepare(cockpit, [message('answer', 'The release check is complete.')])
    for state, label in [('wait', 'Idle'), ('question', 'Waiting for you'), ('ask', 'Waiting for you')]:
        js("currentAgents[0].running=true;currentAgents[0].act_state="+json.dumps(state)+
           ";document.dispatchEvent(new Event('oc:agents'));")
        wait("document.querySelector('.conversation-activity:not([hidden]) .conversation-activity-label')"
             "?.textContent==="+json.dumps(label))


@pytest.mark.parametrize('program,provider,native,done', [
    ('claude', 'anthropic', CLAUDE_COMPACT, [RULE, '❯', RULE, '  ⏵⏵ auto mode on (shift+tab to cycle)']),
    ('claude-code', 'anthropic', CLAUDE_COMPACT, [RULE, '❯', RULE, '  ⏵⏵ auto mode on (shift+tab to cycle)']),
    ('dsh', 'deepseek', DSH_COMPACT, DSH_COMPACT[1:]),
    ('dsh', 'local', DSH_COMPACT, DSH_COMPACT[1:]),
    ('hermes', 'local', HERMES_COMPACT, ['─ ready │ fixture-model │ 19%', ' ❯']),
])
def test_native_compaction_uses_the_same_reader_status(cockpit, program, provider, native, done):
    js,wait,_ = prepare(cockpit,[message('answer','This stays visible during compaction.')])
    js(f"""currentAgents[0]={{...currentAgents[0],program:{json.dumps(program)},provider:{json.dumps(provider)},
      running:true,act_state:'wait'}};
      document.dispatchEvent(new Event('oc:agents'))""")
    wait("Boolean(document.querySelector('[data-event-id=answer]'))")

    def terminal(rows):
        frame = '\x1b[H\x1b[2J' + '\r\n'.join(rows)
        js("writePaneOutput(panes.get('%901'),{snapshot:true,data:"+json.dumps(frame)+"})")

    terminal(native)
    wait("!document.querySelector('.conversation-process').hidden")
    assert js("document.querySelector('.conversation-process-label').textContent") == 'Compacting context…'
    assert js("document.querySelector('.conversation-process-time').textContent") == '12s'
    assert js("document.querySelector('.conversation-activity').hidden")
    terminal(done)
    wait("document.querySelector('.conversation-process').hidden")
    assert js("packets.filter(p=>p.type==='input').length") == 0


@pytest.mark.parametrize('cockpit,layout',[(False,'desktop'),(True,'phone')],indirect=['cockpit'])
def test_compaction_is_visible_above_history_and_clears_on_completion(cockpit,layout):
    events=[message('quote',PASSAGE)]+[message(str(i),'Earlier conversation paragraph.\n\n'+('Keep reading while the agent makes room to continue. '*6)) for i in range(30)]
    js,wait,client=prepare(cockpit,events)
    js("currentAgents[0].running=true;currentAgents[0].act_state='work';document.dispatchEvent(new Event('oc:agents'));const list=document.querySelector('.conversation-scroll');list.dispatchEvent(new WheelEvent('wheel'));list.scrollTop=0;list.dispatchEvent(new Event('scroll'))")
    native='• Compacting context (12s • esc to interrupt)\r\n\r\n› Ask Codex to do anything\r\n\r\ngpt-6.1-sol high · 91% context left'
    js("writePaneOutput(panes.get('%901'),{snapshot:true,data:'\\x1b[H\\x1b[2J'+"+json.dumps(native)+"})")
    wait("!document.querySelector('.conversation-process').hidden")
    assert js("document.querySelector('.conversation-process-label').textContent")=='Compacting context…'
    assert js("document.querySelector('.conversation-process-time').textContent")=='12s'
    assert js("document.querySelector('.conversation-scroll').scrollTop")<100
    assert js("document.querySelector('.conversation-process').getBoundingClientRect().top>=document.querySelector('.conversation-panel').getBoundingClientRect().top")
    assert js("packets.filter(p=>p.type==='input').length")==0
    stage(js,wait,client)
    js("promptInput.value='Please keep this constraint.'")
    wait("document.querySelector('.conversation-reply-reference').getBoundingClientRect().bottom<=promptInput.getBoundingClientRect().top")
    js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    capture=os.environ.get('ORRERY_REPLY_SCREENSHOTS')
    if capture:
        path=Path(capture);path.mkdir(parents=True,exist_ok=True)
        (path/(layout+'-compact-reply.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
    done='• Context compacted · 12s\r\n\r\n› Ask Codex to do anything\r\n\r\ngpt-6.1-sol high · 78% context left'
    js("writePaneOutput(panes.get('%901'),{snapshot:true,data:'\\x1b[H\\x1b[2J'+"+json.dumps(done)+"})")
    wait("document.querySelector('.conversation-process').hidden")
    assert js('promptInput.value')=='Please keep this constraint.'
    js("writePaneOutput(panes.get('%901'),{snapshot:true,data:'\\x1b[H\\x1b[2J'+"+json.dumps(native)+"})")
    wait("!document.querySelector('.conversation-process').hidden")
    js('readerActivity.disconnected()')
    wait("document.querySelector('.conversation-process').hidden")
