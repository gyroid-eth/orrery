"""Reader geometry must resize only terminals owned by this cockpit."""
import asyncio
import os
import pty
import runpy
import subprocess
import time

import pytest

from test_conversation_review_regressions import cockpit, stable_roster
from test_split_pane_headers import setup
from test_runtime_target import endpoint, deploy


def prepare(cockpit, split, claimed=True):
    js, wait, client, _, enable = cockpit
    if split:
        setup(cockpit, 2)
        js("focusSplitSession('ReviewFixture')")
    else:
        stable_roster(js)
        enable(claimed=claimed, count=1)
        js('conversationView.close()')
    if claimed:
        js("for(const p of panes.values()){claimedSessions.add(p.session);p.host.classList.remove('follow')}queueStageFit()")
    time.sleep(.2)
    js("""window.fitTarget=panes.get(paneIdForSession('ReviewFixture'));
      window.fitOwner=fitTarget.host.closest('.split-cell')||document.querySelector('.screen');
      window.fitMetrics=()=>{
        const host=fitTarget.host.getBoundingClientRect(),screen=fitTarget.host.querySelector('.xterm-screen').getBoundingClientRect();
        const reader=fitOwner.querySelector('.conversation-panel:not([hidden])')?.getBoundingClientRect();
        return {width:host.width,right:host.right,screenRight:screen.right,readerLeft:reader?.left,
          cols:fitTarget.term.cols,rows:fitTarget.term.rows,
          others:[...panes.values()].filter(p=>p!==fitTarget).map(p=>p.term.cols)};
      };packets.length=0;""")
    return js, wait, client


def open_reader(js, split):
    js("fitOwner.querySelector('.split-history-toggle').click()" if split else 'conversationView.open()')
    time.sleep(.2)


def assert_half(js, closed, *, same_neighbors=True):
    opened = js('fitMetrics()')
    assert opened['right'] <= opened['readerLeft'] + 1, opened
    assert opened['screenRight'] <= opened['readerLeft'] + 1, opened
    assert 10 < opened['cols'] < closed['cols'], (closed, opened)
    if same_neighbors:
        assert opened['others'] == closed['others']
    assert js('packets.some(p=>p.type==="resize"&&p.paneId===fitTarget.meta.paneId&&p.cols===fitTarget.term.cols)')
    return opened


@pytest.mark.parametrize('split', [False, True])
def test_half_reader_fits_claimed_terminal_and_restores_without_resize_loop(cockpit, split):
    js, wait, client = prepare(cockpit, split)
    closed = js('fitMetrics()')
    # Short history lines avoid reflow, so a changed viewport means lost scroll.
    js("new Promise(resolve=>fitTarget.term.write(('history line\\r\\n').repeat(100),resolve))")
    js("fitTarget.term.scrollLines(-12);window.fitScroll=fitTarget.term.buffer.active.viewportY;promptInput.value='unsent draft';promptInput.focus()")
    for _ in range(3):
        open_reader(js, split)
        assert_half(js, closed)
        assert js('fitTarget.term.buffer.active.viewportY===fitScroll')
        js("fitOwner.querySelector('.conversation-scroll').focus();packets.length=0")
        time.sleep(.25)
        assert js("document.activeElement.classList.contains('conversation-scroll')")
        assert js("packets.filter(p=>p.type==='resize')") == []
        js('conversationView.close()')
        wait('fitTarget.term.cols===' + str(closed['cols']))
        assert js('fitMetrics().others') == closed['others']
    assert js('promptInput.value') == 'unsent draft'
    assert js("packets.filter(p=>['input','claim','release'].includes(p.type))") == []
    js('fitTarget.term.focus()')
    client.call('Input.insertText', text='typed')
    wait("packets.some(p=>p.type==='input'&&p.data==='typed')")


@pytest.mark.parametrize('split', [False, True])
def test_full_reader_and_viewport_resize_keep_valid_terminal_grid(cockpit, split):
    js, wait, client = prepare(cockpit, split)
    closed = js('fitMetrics()')
    open_reader(js, split)
    half = assert_half(js, closed)
    js("fitOwner.querySelector('.conversation-expand').click()")
    wait('fitOwner.classList.contains("conversation-full")')
    time.sleep(.2)
    assert js('fitTarget.term.cols') == closed['cols']
    js("fitOwner.querySelector('.conversation-expand').click()")
    wait('fitTarget.term.cols===' + str(half['cols']))
    client.call('Emulation.setDeviceMetricsOverride', width=1500, height=900, deviceScaleFactor=1, mobile=False)
    time.sleep(.3)
    resized = assert_half(js, closed, same_neighbors=False)
    assert resized['cols'] < half['cols']
    js('conversationView.close()')
    wait('fitTarget.term.cols>' + str(resized['cols']))


@pytest.mark.parametrize('split,width', [(False, 900), (True, 390)])
def test_overlay_reader_does_not_fit_hidden_terminal_to_zero(cockpit, split, width):
    js, wait, client = prepare(cockpit, split)
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    time.sleep(.3)
    cols = js('fitTarget.term.cols')
    open_reader(js, split)
    assert js('fitTarget.term.cols') == cols
    assert cols > 10


@pytest.mark.parametrize('split', [False, True])
def test_follow_reader_never_resizes_external_terminal_grid(cockpit, split):
    js, wait, client = prepare(cockpit, split, claimed=False)
    closed = js('fitMetrics()')
    open_reader(js, split)
    js('conversationView.close()')
    time.sleep(.2)
    assert js('fitTarget.term.cols') == closed['cols']
    assert js("packets.filter(p=>['resize','claim','release'].includes(p.type))") == []


@pytest.mark.parametrize('split', [False, True])
def test_claim_and_release_while_reader_is_open(cockpit, split):
    js, wait, client = prepare(cockpit, split, claimed=False)
    followed = js('fitMetrics()')
    open_reader(js, split)
    js('toggleActivePaneClaim()')
    wait('!fitTarget.host.classList.contains("follow")')
    time.sleep(.2)
    assert_half(js, followed)
    js('toggleActivePaneClaim()')
    wait('fitTarget.host.classList.contains("follow")')
    time.sleep(.2)
    assert js('fitTarget.term.cols') == followed['cols']
    assert js('fitMetrics().width') == followed['width']
    assert js("packets.some(p=>p.type==='release'&&p.paneId===fitTarget.meta.paneId)")


@pytest.mark.parametrize('split', [False, True])
def test_rapid_reader_toggles_send_only_the_settled_grid(cockpit, split):
    js, wait, client = prepare(cockpit, split)
    closed = js('fitMetrics()')
    js("""new Promise(async resolve=>{
      packets.length=0;
      for(let n=0;n<11;n++){
        if(n%2)conversationView.close();
        else if(fitOwner.classList.contains('split-cell'))fitOwner.querySelector('.split-history-toggle').click();
        else conversationView.open();
        await new Promise(r=>setTimeout(r,25));
      }
      setTimeout(resolve,200);
    })""")
    assert_half(js, closed)
    assert js("packets.filter(p=>p.type==='resize'&&p.paneId===fitTarget.meta.paneId).length") == 1


@pytest.mark.parametrize('split', [False, True])
def test_reader_resize_reaches_tmux_despite_other_control_client(cockpit, endpoint, split):
    """Replay real browser sizes through the production claim path on a private socket."""
    from control_server import ControlConfig
    from orrery_backend import SessionBridgeManager, SessionState, SessionTmuxBridge
    from runtime_target import LegacyTargetBoundary

    js, wait, client = prepare(cockpit, split)
    sizes = [js('fitMetrics()')]
    open_reader(js, split)
    sizes.append(assert_half(js, sizes[0]))
    js('conversationView.close()')
    wait('fitTarget.term.cols===' + str(sizes[0]['cols']))
    sizes.append(js('fitMetrics()'))
    deploy(endpoint['home'])
    boundary = LegacyTargetBoundary(endpoint['binary'], home=endpoint['home'], environ=endpoint['env'])
    # OS process-start proof is covered outside the sandbox in the shared suite.
    # Keep socket, membership, admission and all tmux resize operations real here.
    admission = boundary.shared['legacy_admission']
    api = runpy.run_path(str(endpoint['home'] / 'bin/lib/runtime_client.py'))
    api['process_start'] = lambda *args, **kwargs: 'fixture-start'
    boundary.shared['legacy_admission'] = lambda *args, **kwargs: admission(*args, **{**kwargs, 'api': api})
    master, slave = pty.openpty()
    foreign = subprocess.Popen([*endpoint['prefix'], '-C', 'attach-session', '-t', '=orrery-normal'],
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                               env={**endpoint['env'], 'TERM': 'xterm'})
    os.close(slave)

    def tmux(*args):
        return subprocess.check_output([*endpoint['prefix'], *args], text=True, env=endpoint['env']).strip()

    async def exercise():
        bridge = SessionTmuxBridge(ControlConfig('127.0.0.1', 0, 'orrery-normal', boundary,
                                                history_dir=endpoint['home'] / 'history'))
        await bridge.start()
        try:
            window = tmux('display-message', '-p', '-t', endpoint['pane'], '#{window_id}')
            state = SessionState(bridge=bridge)
            for size in sizes:
                payload = {'type': 'resize', 'paneId': endpoint['pane'], 'cols': size['cols'], 'rows': size['rows']}
                assert await SessionBridgeManager._claim_window(state, payload, window, size['cols'], size['rows'])
                # An external client requests a conflicting size after each claim.
                os.write(master, b'refresh-client -C 40,15\n')
                await asyncio.sleep(.1)
                assert '40' in tmux('list-clients', '-F', '#{client_width}').splitlines()
                assert tmux('display-message', '-p', '-t', endpoint['pane'], '#{pane_width}x#{pane_height}') == f"{size['cols']}x{size['rows']}"
                assert len(tmux('list-clients', '-F', '#{client_pid}').splitlines()) == 2
            await SessionBridgeManager._restore_claimed_windows(state)
        finally:
            await bridge.stop()

    try:
        asyncio.run(exercise())
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)
        os.close(master)
