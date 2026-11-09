"""Pane names remain readable while ordinary status is only a labeled dot."""
import json

import pytest
from test_split_pane_headers import cockpit,setup


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('width',[1600,600,390,280])
def test_split_names_match_the_single_header_and_fit_narrow_cells(cockpit,theme,width):
    js,wait,client=setup(cockpit,2)
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=844,deviceScaleFactor=1,mobile=False)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+');document.querySelector(".split-cell .split-history-toggle").click()')
    wait("document.querySelector('.split-cell .conversation-text')!==null")
    data=js("""(()=>{const body=getComputedStyle(document.querySelector('.conversation-text')),single=getComputedStyle(scrName);return [...document.querySelectorAll('.split-cell')].map(cell=>{
      const name=cell.querySelector('.scl-name'),style=getComputedStyle(name),state=cell.querySelector('.split-cell-status'),head=cell.querySelector('.split-cell-head').getBoundingClientRect();
      name.textContent='GeneratedVeryLongSessionFixture';const r=name.getBoundingClientRect();
      return {size:parseFloat(style.fontSize),body:parseFloat(body.fontSize),family:style.fontFamily,single:single.fontFamily,spacing:style.letterSpacing,
        text:state.textContent,label:state.getAttribute('aria-label'),title:state.title,dot:getComputedStyle(state,'::before').width,statusWidth:state.getBoundingClientRect().width,
        nameWidth:r.width,ellipsis:style.textOverflow,nowrap:style.whiteSpace,inside:r.left>=head.left&&r.right<=head.right,
        actions:[...cell.querySelectorAll('.scl-close,.split-history-toggle,.conversation-expand,.split-pane-window')].filter(e=>!e.hidden).every(e=>{const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.left>=head.left&&r.right<=head.right&&r.bottom<=head.bottom&&(hit===e||e.contains(hit))})};})})()""")
    for item in data:
        assert item['size']>=item['body'] and item['size']>=14,item
        assert item['family']==item['single'] and item['spacing']=='normal',item
        assert item['text']=='' and item['label'] in ['active','live'] and item['title']==item['label'],item
        assert item['dot']=='5px' and item['statusWidth']>=5,item
        assert item['nameWidth']>0 and item['ellipsis']=='ellipsis' and item['nowrap']=='nowrap',item
        assert item['inside'] and item['actions'],item


@pytest.mark.parametrize('theme',['dark','light'])
def test_single_normal_status_is_a_dot_and_abnormal_status_stays_named(cockpit,theme):
    js,wait,client=setup(cockpit,2)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+');setActive("%901","single")')
    for active,label in [(True,'active'),(False,'live')]:
        js('paintHead({...panes.get("%901").meta,active:'+json.dumps(active)+'})')
        assert js('scrBadge.textContent')==''
        assert js('scrBadge.getAttribute("aria-label")')==label
        assert js('scrBadge.title')==label
        assert js('scrBadge.getBoundingClientRect().width')>=5
    for action,label in [('paintPendingSession("GeneratedFixture")','connecting'),('resetHead()','offline')]:
        js(action)
        assert js('scrBadge.textContent')==label
        assert js('scrBadge.getAttribute("aria-label")')==label
        assert js('scrBadge.title')==label
    js("currentAgents.push({name:'HeadlessFixture',cmd:'codex-app'});jumpToSessionTarget('HeadlessFixture')")
    assert js('scrBadge.textContent')=='no terminal'
    assert js('scrBadge.getAttribute("aria-label")')=='no terminal'


@pytest.mark.parametrize('theme',['dark','light'])
def test_connecting_split_state_keeps_visible_text_and_accessible_name(cockpit,theme):
    js,wait,client=setup(cockpit,2)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+');panes.delete("%902");renderStage()')
    state="document.querySelector('.split-cell[data-session=OtherFixture] .split-cell-status')"
    assert js(state+'.textContent')=='connecting'
    assert js(state+'.getAttribute("aria-label")')=='connecting'
    assert js(state+'.title')=='connecting'
    assert not js(state+'.classList.contains("live")')
