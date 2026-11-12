"""A received native terminal status remains visible while reading older rows."""
import base64
import json
import os
from pathlib import Path

import pytest

from test_conversation_review_regressions import cockpit
from test_conversation_inline_images import prepare,message
from test_conversation_reply import PASSAGE,stage


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
