"""Selected direction C against the real cockpit and generated pane state."""
import sys,time,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_conversation_review_regressions import cockpit,stable_roster


def setup(cockpit,count=4):
    js,wait,client,requests,enable=cockpit
    stable_roster(js);enable(count=1);js('conversationView.close()')
    names=['ReviewFixture','OtherFixture','ThirdFixture','FourthFixture'][:count]
    for n,name in enumerate(names[1:],902):
        js('currentAgents.push({name:'+json.dumps(name)+',program:"codex",history_binding:"bound"});createPane('+json.dumps(name)+',{paneId:'+json.dumps('%'+str(n))+',windowId:'+json.dumps('@'+str(n))+',width:80,height:20,active:true});')
    js('replaceSplitSessions('+json.dumps(names)+');splitVisible=true;focusSplitSession('+json.dumps(names[-1])+');window.headerWindows=[];popSessionToWindow=(name)=>{headerWindows.push(name);return true};')
    wait('document.querySelectorAll(".split-history-toggle").length==='+str(count))
    return js,wait,client


def visible(js,selector):return js('(()=>{const e=document.querySelector('+json.dumps(selector)+');return !!e&&e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0})()')


@pytest.mark.parametrize('count',[2,4])
def test_headers_have_only_owner_actions_and_keep_other_focus(cockpit,count):
    js,wait,client=setup(cockpit,count)
    assert not visible(js,'.scr-head')
    assert js("document.querySelectorAll('.split-cell-head .split-history-toggle').length")==count
    assert js("document.querySelectorAll('.split-cell-head .split-pane-window').length")==count
    js("document.querySelector('.split-cell[data-session=ReviewFixture] .split-pane-window').click()")
    assert js('headerWindows')==['ReviewFixture']
    assert js('activeSession()')!= 'ReviewFixture'
    js("document.querySelector('.split-cell[data-session=ReviewFixture] .split-history-toggle').click()")
    wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-event')!==null")
    assert js('activeSession()')=='ReviewFixture'
    assert js("document.querySelector('.split-cell.focused').dataset.session")=='ReviewFixture'
    assert js("document.querySelectorAll('.split-cell:not([data-session=ReviewFixture]) .conversation-panel:not([hidden])').length")==0


def test_header_keyboard_enter_space_and_focus_survive_fit(cockpit):
    js,wait,client=setup(cockpit,2)
    js("document.querySelector('.split-cell[data-session=ReviewFixture] .split-pane-window').focus();packets.length=0;queueStageFit(activeId)")
    time.sleep(.2)
    assert js("document.activeElement.classList.contains('split-pane-window')")
    for key,code in [('Enter',13),(' ',32)]:
        client.call('Input.dispatchKeyEvent',type='keyDown',key=key,code='Space' if key==' ' else 'Enter',windowsVirtualKeyCode=code,text=' ' if key==' ' else '\r')
        client.call('Input.dispatchKeyEvent',type='keyUp',key=key,code='Space' if key==' ' else 'Enter',windowsVirtualKeyCode=code)
    assert js('headerWindows')==['ReviewFixture','ReviewFixture']
    js("document.querySelector('.split-cell[data-session=ReviewFixture] .split-history-toggle').focus()")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',code='Enter',text='\r',windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',windowsVirtualKeyCode=13)
    wait("!document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-panel').hidden")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Escape',windowsVirtualKeyCode=27)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Escape',windowsVirtualKeyCode=27)
    assert js("document.activeElement.classList.contains('split-history-toggle')")
    client.call('Input.dispatchKeyEvent',type='keyDown',key=' ',code='Space',text=' ',windowsVirtualKeyCode=32)
    client.call('Input.dispatchKeyEvent',type='keyUp',key=' ',code='Space',windowsVirtualKeyCode=32)
    wait("!document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-panel').hidden")
    assert js("packets.filter(p=>['input','codex-page','claim','release'].includes(p.type))")==[]


def test_header_rebuild_reorder_close_off_and_return_to_single(cockpit):
    js,wait,client=setup(cockpit,4)
    js("replaceSplitSessions(['FourthFixture','OtherFixture','ReviewFixture','ThirdFixture']);renderStage();renderStage()")
    assert js("document.querySelectorAll('.split-cell-head').length")==4
    assert js("document.querySelectorAll('.split-pane-window').length")==4
    js("document.querySelector('.split-cell[data-session=ThirdFixture] .scl-close').click()")
    wait("document.querySelectorAll('.split-cell').length===3")
    assert js("document.querySelectorAll('.split-cell-head').length")==3
    js("conversationEnabled.checked=false;conversationEnabled.dispatchEvent(new Event('change'))")
    assert js("document.querySelectorAll('.split-history-toggle').length")==0
    assert js("document.querySelectorAll('.split-pane-window').length")==3
    js("setActive(paneIdForSession('ReviewFixture'),'single');renderStage()")
    assert visible(js,'.scr-head') and visible(js,'#panePopout')
    assert not visible(js,'#conversationToggle')
    js("conversationEnabled.checked=true;conversationEnabled.dispatchEvent(new Event('change'))")
    wait("!document.getElementById('conversationToggle').hidden")
    assert visible(js,'#conversationToggle')


@pytest.mark.parametrize('width',[900,390,280])
def test_narrow_headers_stay_one_line_without_covering_terminal_or_losing_actions(cockpit,width):
    js,wait,client=setup(cockpit,2)
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=844,deviceScaleFactor=1,mobile=False)
    time.sleep(.3)
    wait("document.querySelectorAll('.split-cell-head .split-history-toggle').length===2")
    state=js("""[...document.querySelectorAll('.split-cell')].map(cell=>{const head=cell.querySelector('.split-cell-head'),h=head.getBoundingClientRect(),t=cell.querySelector('.termhost').getBoundingClientRect(),actions=[...head.querySelectorAll('.split-history-toggle,.split-pane-window')].map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,text:e.innerText,label:e.getAttribute('aria-label'),svg:!!e.querySelector('svg')}}),r=cell.getBoundingClientRect();return {left:r.left,right:r.right,bottom:h.bottom,top:h.top,height:h.height,termTop:t.top,actions}})""")
    for cell in state:
        assert cell['height']==40,cell
        assert cell['termTop']>=cell['bottom']-1,cell
        for action in cell['actions']:
            assert action['label'],action
            content_width=cell['right']-cell['left']-2
            assert action['svg'] and action['text']=='',action
            assert action['left']>=cell['left'] and action['right']<=cell['right'],cell
            assert action['bottom']<=cell['bottom'],cell
            assert abs((action['top']+action['bottom'])/2-(cell['top']+cell['bottom'])/2)<=1,cell
    js("document.querySelector('.split-cell .split-history-toggle').click()")
    wait("!document.querySelector('.split-cell .conversation-panel').hidden")
    bounds=js("(()=>{const cell=document.querySelector('.split-cell').getBoundingClientRect(),p=document.querySelector('.split-cell .conversation-panel').getBoundingClientRect();const head=document.querySelector('.split-cell-head').getBoundingClientRect();return {ok:p.left>=cell.left&&p.right<=cell.right&&p.bottom<=cell.bottom&&p.top>=head.bottom}})()")
    assert bounds['ok']


def test_last_split_uses_single_header_and_returns_keyboard_focus(cockpit):
    js,wait,client=setup(cockpit,2)
    js("document.querySelector('.split-cell[data-session=OtherFixture] .scl-close').click()")
    wait("document.querySelectorAll('.split-cell').length===0")
    assert visible(js,'.scr-head')
    js("document.getElementById('conversationToggle').click()")
    wait("!document.querySelector('.screen>.conversation-panel').hidden")
    js("document.querySelector('#conversationToggle').click()")
    assert js("document.activeElement.id")=='conversationToggle'
    # A restored one-member split also keeps the single shared header.
    js("replaceSplitSessions(['ReviewFixture']);splitVisible=true;focusSplitSession('ReviewFixture')")
    wait("document.querySelectorAll('.split-cell').length===1")
    assert visible(js,'.scr-head') and not visible(js,'.split-cell-head')
    js("document.getElementById('conversationToggle').click()")
    wait("!document.querySelector('.split-cell .conversation-panel').hidden")
    assert js("document.querySelector('.split-cell .conversation-panel').getAttribute('aria-label').includes('ReviewFixture')")
    assert js("(()=>{const c=document.querySelector('.split-cell').getBoundingClientRect(),p=document.querySelector('.split-cell .conversation-panel').getBoundingClientRect();return Math.abs(c.top-p.top)<2})()")
    js("document.querySelector('#conversationToggle').click()")
    assert js("document.activeElement.id")=='conversationToggle'


def test_name_keyboard_focus_keeps_status_inert(cockpit):
    js,wait,client=setup(cockpit,2)
    js("document.querySelector('.split-cell[data-session=ReviewFixture] .scl-name').focus();packets.length=0")
    client.call('Input.dispatchKeyEvent',type='keyDown',key=' ',code='Space',text=' ',windowsVirtualKeyCode=32)
    client.call('Input.dispatchKeyEvent',type='keyUp',key=' ',code='Space',windowsVirtualKeyCode=32)
    assert js('activeSession()')=='ReviewFixture'
    assert js("document.querySelector('.split-cell[data-session=ReviewFixture] .split-cell-status').getAttribute('role')")=='status'
    assert js("document.querySelectorAll('.split-cell-status.cockpit-control,.split-cell-status[tabindex]').length")==0
    assert js("packets.filter(p=>['input','codex-page','claim','release'].includes(p.type))")==[]


@pytest.mark.parametrize('count',[2,4])
def test_split_history_preserves_usable_mobile_composer(cockpit,count):
    # LimeEdison C review: a local reader must receive the mobile composer
    # geometry without turning the whole screen into a global reader.
    js,wait,client=setup(cockpit,count)
    client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    js("promptInput.value='Generated local draft';document.querySelector('.split-cell[data-session=OtherFixture] .split-history-toggle').click()")
    wait("document.querySelectorAll('.split-cell.conversation-open').length===1")
    time.sleep(.2)
    observed=js("""(()=>{const p=promptInput.getBoundingClientRect(),bar=promptInput.closest('.promptbar').getBoundingClientRect(),screen=document.querySelector('.screen'),stage=document.getElementById('termstage').getBoundingClientRect();return {inputWidth:p.width,inputHeight:p.height,barHeight:bar.height,barTop:bar.top,stageBottom:stage.bottom,globalOpen:screen.classList.contains('conversation-open'),localOpen:document.querySelectorAll('.split-cell.conversation-open').length}})()""")
    print(observed)
    assert observed['inputWidth']>=160,observed
    assert observed['barHeight']==132 and observed['inputHeight']>50,observed
    assert not observed['globalOpen'] and observed['localOpen']==1
    assert observed['stageBottom']<=observed['barTop']+1,observed
    assert js('promptInput.value')=='Generated local draft'
    js("document.querySelector('.split-cell.conversation-open .split-history-toggle').click()")
    assert js("document.querySelector('.promptbar').getBoundingClientRect().height")==84
