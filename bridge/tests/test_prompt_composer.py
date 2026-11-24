"""Composer behavior on the real cockpit with synthetic panes and CDP."""

import pytest

from test_conversation_review_regressions import cockpit, stable_roster


def terminal(cockpit):
    js, wait, client, *_ = cockpit
    stable_roster(js)
    js("""window.packets=[];window.send=packet=>{packets.push(packet);return true};
        currentAgents=[{name:'ReviewFixture',running:true,program:'codex'}];
        createPane('ReviewFixture',{paneId:'%901',windowId:'@901',width:80,height:20});
        setActive('%901');packets.length=0;""")
    return js, wait, client


def test_card_fills_stage_and_resizes_the_textarea(cockpit):
    js, wait, _ = terminal(cockpit)
    assert js('promptInput.placeholder') == 'Message ReviewFixture'
    assert js("""(()=>{const card=promptInput.closest('.prompt-card').getBoundingClientRect();
        const stage=document.querySelector('.termstage').getBoundingClientRect();
        return [card.left-stage.left,stage.right-card.right]})()""") == [18, 18]
    js(r"promptInput.value='Several lines\n'.repeat(20);promptInput.dispatchEvent(new Event('input'))")
    wait('promptInput.clientHeight===88 && promptInput.scrollHeight>88')
    assert js("packets.filter(packet=>packet.type==='resize')") == []
    js("promptInput.value='';promptInput.dispatchEvent(new Event('input'))")
    wait('promptInput.clientHeight===32')


@pytest.mark.parametrize('reduced', [False, True])
def test_action_switches_to_stop_only_for_an_empty_working_draft(cockpit, reduced):
    js, wait, client = terminal(cockpit)
    if reduced:
        client.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    assert js('promptSendBtn.disabled')
    js("currentAgents[0].act_state='work';document.dispatchEvent(new Event('oc:agents'));promptSendBtn.click()")
    assert js('promptSendBtn.title') == 'Stop agent (Esc)'
    assert js("packets.find(packet=>packet.type==='input').data") == '\x1b'
    square = "document.querySelector('.prompt-square').style.transform==='scale(1)'"
    if reduced:
        assert js(square)
    else:
        wait(square)
    js(r"promptInput.value='First line\nSecond line';promptInput.dispatchEvent(new Event('input'))")
    assert js('promptSendBtn.title') == 'Send message'
    if reduced:
        assert js('promptInput.clientHeight') == 56
    js("packets.length=0;promptSendBtn.click()")
    wait("packets.filter(packet=>packet.type==='input').length===2")
    assert js("packets.filter(packet=>packet.type==='input').map(packet=>packet.data)") == [
        '\x1b[200~First line\nSecond line\x1b[201~', '\r',
    ]
