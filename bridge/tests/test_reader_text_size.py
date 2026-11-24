"""Exercise the Settings preference against the rendered Reader in Chromium."""
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


def prepare(cockpit):
    js, wait, _, _, enable = cockpit
    stable_roster(js)
    enable(count=1)
    js("""conversationView.close();
      Object.assign(currentAgents[0],{running:true,act_state:'work',work_disp:'12s'});
      OrreryConversationSource.Source.prototype.read=async()=>({
        mode:'cursor',after:'fixture:end',events:""" + json.dumps(EVENTS) + """});
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


@pytest.mark.parametrize('size', [12, 13, 14, 15])
def test_all_reader_sizes_apply_live_and_restore_after_reload(cockpit, size):
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
