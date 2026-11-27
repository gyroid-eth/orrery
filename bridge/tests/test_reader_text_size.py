"""Exercise the Settings font preferences against the rendered cockpit."""
import json

import pytest

from test_conversation_review_regressions import cockpit, open_agents_fixture, stable_roster


KEY = 'oc-term-reader-text-size'
EVENTS = [
    dict(id='source', kind='text', role='assistant', text='## Review summary\n\n'
         'The generated report includes `capture.png` and a short status check.\n\n'
         '```text\ncapture.png · ready\n```'),
    dict(id='wash', kind='text', role='user', text='Please check the layout in both themes.'),
    dict(id='reply', kind='text', role='user', text='Reference: ReviewFixture · assistant\n'
         'Recorded message: source\n> The generated report includes capture.png.\n\n'
         'Keep the original capture with the report.'),
]
SAMPLES = {
    '[data-event-id=source] .conversation-text': 13,
    '[data-event-id=source] p': 13,
    '[data-event-id=source] .markdown-heading': 13,
    '[data-event-id=source] p code': 13,
    '[data-event-id=source] pre code': 12,
    '[data-event-id=source] .conversation-speaker-name': 12,
    '[data-event-id=wash] .conversation-text': 13,
    '[data-event-id=reply] .conversation-reference-quote': 11,
    '[data-event-id=reply] .conversation-text': 13,
    '.conversation-activity[data-state=work]:not([hidden]) .conversation-activity-label': 12,
    '.conversation-working-speaker .conversation-speaker-name': 12,
}


def prepare(cockpit, events=EVENTS):
    js, wait, _, _, enable = cockpit
    stable_roster(js)
    enable(count=1)
    js("""conversationView.close();
      Object.assign(currentAgents[0],{running:true,act_state:'work',work_disp:'12s'});
      OrreryConversationSource.Source.prototype.read=async()=>({
        mode:'cursor',after:'fixture:end',events:""" + json.dumps(events) + """});
      conversationView.open();""")
    wait("""Boolean(document.querySelector('[data-event-id=reply] .conversation-reference-quote')&&
      document.querySelector('.conversation-activity[data-state=work]:not([hidden])'))""")
    return js


def select_size(js, size):
    js("readerTextSize.value=" + json.dumps(str(size)) +
       ";readerTextSize.dispatchEvent(new Event('change',{bubbles:true}));")


def sizes(js, selectors=SAMPLES):
    return js('(' + json.dumps(list(selectors)) + """).map(selector=>
      parseFloat(getComputedStyle(document.querySelector(selector)).fontSize))""")


@pytest.mark.parametrize('size', [10, 13, 18])
def test_reader_size_applies_live_and_restores_after_reload(cockpit, size):
    js = prepare(cockpit)
    _, wait, client, _, _ = cockpit
    assert js(f"OrreryPrefs.synced('{KEY}')")
    js("window.keptText=document.querySelector('[data-event-id=source] .conversation-text')")
    select_size(js, size)
    assert js(f"localStorage.getItem('{KEY}')") == str(size)
    assert js("keptText===document.querySelector('[data-event-id=source] .conversation-text')")
    assert sizes(js) == pytest.approx([size * baseline / 13 for baseline in SAMPLES.values()], abs=.001)
    client.call('Page.removeScriptToEvaluateOnNewDocument', identifier=js.storage_bootstrap)
    client.call('Page.reload', ignoreCache=True)
    wait(f"!window.keptText&&document.getElementById('readerTextSize')?.value==='{size}'")
    assert js("document.documentElement.style.getPropertyValue('--reader-text-size')") == f'{size}px'


def test_default_and_synced_reader_sizes(cockpit):
    js = prepare(cockpit)
    assert js(f"localStorage.getItem('{KEY}')") is None
    assert js('readerTextSize.value') == '13'
    assert sizes(js) == list(SAMPLES.values())
    js(f"""localStorage.setItem('{KEY}','15');
      document.dispatchEvent(new CustomEvent('oc:prefs-changed',{{detail:{{keys:['{KEY}']}}}}));""")
    assert js('readerTextSize.value') == '15'
    assert sizes(js, ['[data-event-id=source] .conversation-text']) == [15]
    js(f"""localStorage.setItem('{KEY}','invalid');
      window.dispatchEvent(new StorageEvent('storage',{{key:'{KEY}'}}));""")
    assert js('readerTextSize.value') == '13'
    assert sizes(js) == list(SAMPLES.values())


def test_narrow_viewport_reduces_the_whole_reader_scale(cockpit):
    js = prepare(cockpit)
    _, _, client, _, _ = cockpit
    client.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=False)
    assert sizes(js) == pytest.approx([12.5 * baseline / 13 for baseline in SAMPLES.values()], abs=.001)
    select_size(js, 15)
    assert sizes(js) == pytest.approx([14.5 * baseline / 13 for baseline in SAMPLES.values()], abs=.001)


def test_split_reader_reduces_scale_in_a_narrow_cell(cockpit):
    js, wait = open_agents_fixture(cockpit, {'FirstFixture': 'codex', 'SecondFixture': 'claude-code'})
    js("""agentDefaultView.value='reader';agentDefaultView.dispatchEvent(new Event('change'));
      openFixtureAgent('FirstFixture',true);openFixtureAgent('SecondFixture',true);
      finishAgentAttach('SecondFixture',902);finishAgentAttach('FirstFixture',901);""")
    selector = '.split-cell .conversation-panel:not([hidden]) .conversation-text'
    wait(f"document.querySelectorAll('{selector}').length===2")
    assert sizes(js, [selector]) == [12.5]
    select_size(js, 12)
    assert sizes(js, [selector]) == [11.5]


def test_reader_scales_tools_mail_status_question_and_preview(cockpit):
    events = EVENTS + [
        dict(id='file', kind='tool', role='assistant', text='Inspect the notes',
             references=[dict(id='A'*32, label='layout.txt', kind='file')]),
        dict(id='mail', kind='mail', role='assistant', text='Review request',
             mail=[dict(direction='received', sender='ParentFixture', subject='Check the layout',
                        body='Readability at the smallest setting matters.', coverage='complete')]),
    ]
    js = prepare(cockpit, events)
    _, wait, _, _, _ = cockpit
    wait("Boolean(document.querySelector('.conversation-file')&&document.querySelector('.conversation-mail'))")
    js("""document.querySelector('.conversation-mail').open=true;
      const toggle=document.querySelector('.conversation-steps-toggle,.conversation-tool-group');
      if(toggle?.getAttribute('aria-expanded')==='false')toggle.click();
      OrreryConversationSource.Source.prototype.reference=async()=>({ok:true,kind:'text',text:'A fixture document'});
      document.querySelector('.conversation-file').click();
      currentAgents[0].act_state='question';document.dispatchEvent(new Event('oc:agents'));
      writePaneOutput(panes.get('%901'),{snapshot:true,data:'ReviewFixture needs your input'});""")
    wait("Boolean(document.querySelector('.conversation-preview-text')&&packets.some(p=>p.type==='approval-inspect'))")
    js("""const inspect=packets.findLast(p=>p.type==='approval-inspect');
      readerApproval.receive({type:'approval',paneId:inspect.paneId,session:inspect.session,requestId:inspect.requestId,
        state:'ready',kind:'question',harness:'codex',mode:'choice',token:'fixture-question',
        body:'Review the layout?',default:1,choices:[{id:1,label:'Read the draft'}]});""")
    wait("!document.querySelector('.reader-approval').hidden")
    samples = {
        '.conversation-step-tool,.conversation-tool-name': 11,
        '.conversation-activity-label': 11,
        '.conversation-mail-subject': 12,
        '.conversation-mail-text': 12,
        '.conversation-preview-title': 12,
        '.conversation-preview-text': 12,
        '.reader-approval-title': 21,
        '.reader-approval-choice-copy': 11,
    }
    for size in (10, 13, 18):
        select_size(js, size)
        assert sizes(js, samples) == pytest.approx([size * baseline / 13 for baseline in samples.values()], abs=.001)
        assert js("""[...document.querySelectorAll('.conversation-scroll,.conversation-preview,.reader-approval')]
          .filter(el=>!el.hidden).every(el=>el.scrollWidth<=el.clientWidth+1)""")
        assert js("""document.querySelector('.reader-approval').getBoundingClientRect().bottom<=
          document.querySelector('.promptbar').getBoundingClientRect().top""")
        assert js("""(()=>{const k=document.querySelector('.reader-approval-choice kbd').getBoundingClientRect(),
          t=document.querySelector('.reader-approval-choice-copy').getBoundingClientRect();
          return k.right <= t.left && Math.abs((k.top+k.bottom-t.top-t.bottom)/2) < 1;})()""")


def test_terminal_drag_applies_font_fit_and_sync_only_once(cockpit):
    js, wait, client, _, enable = cockpit
    stable_roster(js)
    enable(claimed=True, count=1)
    js("""conversationView.close();settingsPopover.showPopover();
      terminalFontRange.scrollIntoView({block:'center'});terminalFontRange.focus();""")
    js("new Promise(resolve=>setTimeout(resolve,350))")
    js("""window.fontCalls={apply:0,queue:0,fit:0,save:0,sync:0};
      const apply=applyTerminalSettings,queue=queueStageFit,save=persistTerminalSettings,
        fit=panes.get('%901').fit.fit.bind(panes.get('%901').fit),open=XMLHttpRequest.prototype.open;
      applyTerminalSettings=(...args)=>{fontCalls.apply++;return apply(...args)};
      queueStageFit=(...args)=>{fontCalls.queue++;return queue(...args)};
      persistTerminalSettings=(...args)=>{fontCalls.save++;return save(...args)};
      panes.get('%901').fit.fit=(...args)=>{fontCalls.fit++;return fit(...args)};
      XMLHttpRequest.prototype.open=function(method,url,...args){
        if(method==='PUT'&&url==='/telemetry/prefs')fontCalls.sync++;
        return open.call(this,method,url,...args);
      };
      packets.length=0;
      for(const value of ['10','13.5','16','18']){
        terminalFontRange.value=value;
        terminalFontRange.dispatchEvent(new Event('input',{bubbles:true}));
      }""")
    assert js('terminalFontValue.textContent') == '18.0 px'
    assert js('terminalFontRange.getAttribute("aria-valuetext")') == '18.0 pixels'
    assert js('terminalFontEffective.textContent') == 'effective 12.5 px'
    assert js("getComputedStyle(panes.get('%901').host.querySelector('.xterm-rows')).fontSize") == '12.5px'
    assert js('fontCalls') == dict(apply=0, queue=0, fit=0, save=0, sync=0)
    assert js("localStorage.getItem('oc-term-font')") is None
    js("""terminalFontRange.dispatchEvent(new Event('change',{bubbles:true}));
      terminalFontRange.dispatchEvent(new Event('change',{bubbles:true}));""")
    wait("fontCalls.fit===1&&fontCalls.sync===1")
    assert js('fontCalls') == dict(apply=1, queue=1, fit=1, save=1, sync=1)
    assert js("packets.filter(p=>p.type==='resize'&&p.paneId==='%901').length") == 1
    assert js("getComputedStyle(panes.get('%901').host.querySelector('.xterm-rows')).fontSize") == '18px'
    assert js("document.activeElement===terminalFontRange && localStorage.getItem('oc-term-font')==='18'")
    assert js('effectiveTerminalFontSize(10,true,5)') == 10
    client.call('Page.removeScriptToEvaluateOnNewDocument', identifier=js.storage_bootstrap)
    client.call('Page.reload', ignoreCache=True)
    wait("!window.fontCalls&&document.getElementById('terminalFontSize')?.value==='18'")
    enable(count=1)
    assert js("getComputedStyle(panes.get('%901').host.querySelector('.xterm-rows')).fontSize") == '18px'
