"""Provider identity replaces the status dot without crowding pane actions."""
import json

import pytest
from test_split_pane_headers import cockpit, setup
from test_conversation_review_regressions import wait_reading_layout


def prepare(cockpit, layout):
    js, wait, client = setup(cockpit, 2)
    if layout == 'single':
        js("setActive('%901','single')")
    head = '.scr-head' if layout == 'single' else '.split-cell[data-session=ReviewFixture] .split-cell-head'
    js('window.modelHead=document.querySelector('+json.dumps(head)+')')
    return js, wait, client


def paint(js, agent, active=True):
    js('Object.assign(currentAgents.find(a=>a.name==="ReviewFixture"),'+json.dumps(agent)+');panes.get("%901").meta.active='+json.dumps(active)+';renderStage();paintHead(panes.get("%901").meta)')


@pytest.mark.parametrize('layout', ['single', 'split'])
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_provider_marks_use_the_existing_maker_resolution(cockpit, layout, theme):
    js, wait, _ = prepare(cockpit, layout)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    cases = [
        ('anthropic', 'Opus 5.5', 'claude-opus-5-5', 'anthropic'),
        ('openai', 'GPT 6.1', 'gpt-6.1-sol', 'openai'),
        ('deepseek', 'DeepSeek V3.2', 'deepseek-v3.2', 'deepseek'),
        ('local', 'Qwen3 32B', 'qwen3-32b', 'qwen'),
        ('local', 'GLM 4.7', 'glm-4.7', 'glm'),
        ('local', 'Custom model', 'custom-model', None),
        ('unknown', 'Custom model', 'custom-model', None),
    ]
    for provider, model, raw, asset in cases:
        paint(js, dict(provider=provider, program='custom-cli', model=model, model_raw=raw, running=True, act_state='wait'))
        assert js("!!modelHead.querySelector('.pane-provider')")
        if asset:
            wait("modelHead.querySelector('.pane-provider img')?.naturalWidth>0")
            assert js("modelHead.querySelector('.pane-provider img').getAttribute('src')") == 'cockpit-assets/'+asset+'.svg'
            assert js("(()=>{const s=getComputedStyle(modelHead.querySelector('.pane-provider img'));return s.backgroundColor==='rgba(0, 0, 0, 0)'&&s.borderTopWidth==='0px'&&s.borderRadius==='0px'})()")
        else:
            assert js("!modelHead.querySelector('.pane-provider img')&&!!modelHead.querySelector('.pane-provider svg')")
        assert 'active' in js("modelHead.querySelector('.pane-provider').getAttribute('aria-label')")
        assert js("modelHead.querySelector('.pane-provider').title").endswith('active')
        assert js("modelHead.querySelector('.pane-provider').getAttribute('role')") == 'img'
        assert js("modelHead.querySelector('.pane-model').textContent") == ('Sol' if asset=='openai' else model)


@pytest.mark.parametrize('layout', ['single', 'split'])
def test_gpt_kind_display_preserves_the_full_id_in_title(cockpit, layout):
    js, _, _ = prepare(cockpit, layout)
    for kind in ['Sol', 'Terra', 'Luna', 'Astra']:
        raw = 'gpt-6.1-'+kind.lower()
        paint(js, dict(provider='openai', model='GPT 6.1', model_raw=raw))
        assert js("modelHead.querySelector('.pane-model').textContent") == kind
        assert raw in js("modelHead.querySelector('.pane-model').title")
    paint(js, dict(model='GPT 6.1', model_raw='GPT-6.1'))
    assert js("modelHead.querySelector('.pane-model').textContent") == 'GPT 6.1'
    paint(js, dict(model='', model_raw='gpt-6.1-sol'))
    assert js("modelHead.querySelector('.pane-model').hidden")
    paint(js, dict(model='<b>Literal model</b>', model_raw='custom'))
    assert js("modelHead.querySelector('.pane-model').textContent") == '<b>Literal model</b>'
    assert not js("!!modelHead.querySelector('.pane-model b')")


@pytest.mark.parametrize('layout', ['single', 'split'])
def test_only_active_work_pulses_and_reduced_motion_stops_it(cockpit, layout):
    js, _, client = prepare(cockpit, layout)
    for active, running, state, animated in [(True,True,'work',True),(True,True,'wait',False),(True,True,'question',False),(True,True,'ask',False),(False,True,'work',False),(True,False,'work',False),(True,True,None,False)]:
        paint(js, dict(provider='anthropic', model='Opus 5.5', model_raw='claude-opus-5-5', running=running, act_state=state), active)
        assert js("getComputedStyle(modelHead.querySelector('.pane-provider')).animationName!=='none'") == animated
        assert ('active' if active else 'live') in js("modelHead.querySelector('.pane-provider').getAttribute('aria-label')")
        status = js("(()=>{const s=modelHead.querySelector('.split-cell-status,.badge');return {text:s.textContent,dot:getComputedStyle(s,'::before').content,width:s.getBoundingClientRect().width}})()")
        assert status['text']=='' and status['dot'] in ['none','normal'] and status['width']==0
    paint(js, dict(running=True, act_state='work'))
    client.call('Emulation.setEmulatedMedia', features=[dict(name='prefers-reduced-motion',value='reduce')])
    assert js("getComputedStyle(modelHead.querySelector('.pane-provider')).animationName") == 'none'
    assert js("Number(getComputedStyle(modelHead.querySelector('.pane-provider')).opacity)>=0.8")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [1600,780,390,280])
def test_split_model_yields_to_the_name_and_actions_stay_hittable(cockpit, theme, width):
    js, wait, client = prepare(cockpit, 'split')
    client.call('Emulation.setDeviceMetricsOverride', width=width,height=844,deviceScaleFactor=1,mobile=False)
    paint(js, dict(provider='anthropic', model='A deliberately long display model name', model_raw='custom', running=True, act_state='wait'))
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    for reader in [False, True]:
        if reader:
            js("modelHead.querySelector('.split-history-toggle').click()")
            wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-text')!==null")
            js("modelHead.querySelector('.conversation-expand').click()")
            wait_reading_layout(js)
        state = js("""(()=>{const h=modelHead.getBoundingClientRect(),name=modelHead.querySelector('.scl-name'),model=modelHead.querySelector('.pane-model'),logo=modelHead.querySelector('.pane-provider'),n=name.getBoundingClientRect(),m=model.getBoundingClientRect(),l=logo.getBoundingClientRect();return {font:parseFloat(getComputedStyle(model).fontSize),nameFont:parseFloat(getComputedStyle(name).fontSize),nameWidth:n.width,nameFull:name.scrollWidth,modelWidth:m.width,modelFull:model.scrollWidth,logoWidth:l.width,logoLeft:l.left,nameLeft:n.left,inside:n.right<=h.right&&l.left>=h.left,actions:[...modelHead.querySelectorAll('button')].filter(b=>!b.hidden&&b.getBoundingClientRect().width).every(b=>{const r=b.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.left>=h.left&&r.right<=h.right&&(hit===b||b.contains(hit))})}})()""")
        assert 11<=state['font']<state['nameFont']
        assert state['logoWidth']>=14 and state['logoLeft']<state['nameLeft']
        assert state['nameWidth']>=16 and state['inside'] and state['actions'], state
        if state['nameWidth']<state['nameFull']-1:
            assert state['modelWidth']<=1, state


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [390,280])
def test_single_and_pane_window_headers_keep_controls(cockpit, theme, width):
    js, _, client = prepare(cockpit, 'single')
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=844,deviceScaleFactor=1,mobile=False)
    paint(js, dict(provider='openai', model='GPT 6.1', model_raw='gpt-6.1-terra', running=True, act_state='work'))
    assert js("!!modelHead.querySelector('.pane-provider')&&modelHead.querySelector('.pane-model').textContent==='Terra'")
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    for window in [False, True]:
        js('document.documentElement.classList.toggle("pane-window",'+json.dumps(window)+')')
        assert js("(()=>{const r=modelHead.getBoundingClientRect();return [...modelHead.querySelectorAll('.pane-provider,button')].filter(b=>!b.hidden&&b.getBoundingClientRect().width).every(b=>{const a=b.getBoundingClientRect(),hit=document.elementFromPoint(a.x+a.width/2,a.y+a.height/2);return a.left>=r.left&&a.right<=r.right&&(hit===b||b.contains(hit))})})()")


@pytest.mark.parametrize('layout', ['single', 'split'])
def test_roster_poll_refreshes_identity_without_rebuilding_focused_actions(cockpit, layout):
    js, _, _ = prepare(cockpit, layout)
    paint(js, dict(provider='openai', model='GPT 6.1', model_raw='gpt-6.1-sol', running=True, act_state='work'))
    js("window.focusedHeaderAction=[...modelHead.querySelectorAll('button')].find(b=>b.getBoundingClientRect().width>0);focusedHeaderAction.focus();Object.assign(currentAgents.find(a=>a.name==='ReviewFixture'),{model_raw:'gpt-6.1-terra',act_state:'wait'});pollAgents()")
    assert js("modelHead.querySelector('.pane-model').textContent") == 'Terra'
    assert js("getComputedStyle(modelHead.querySelector('.pane-provider')).animationName") == 'none'
    assert js('document.activeElement===focusedHeaderAction')
