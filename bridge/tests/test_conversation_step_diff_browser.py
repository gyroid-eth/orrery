"""Exercise the shipped Inline disclosure in an isolated cockpit fixture."""
import json

import pytest

from test_conversation_review_regressions import cockpit
from test_conversation_steps_browser import prepare
from test_conversation_step_diff import bound, claude_records, codex_record, PATH
from conversation_history import open_reader
from conversation_preview import ReferenceStore


INERT = '<img id="fixture-inert" onerror="never()">'


def projected(tmp_path, provider, records):
    row = bound(tmp_path, provider, records)
    with open_reader(row) as stream:
        events = stream.read_page()['events']
        store = ReferenceStore()
        store.decorate_all(row, stream, events)
    return events, {ref: store.read_step_diff(ref, row)
                    for event in events if (ref := event.get('step', {}).get('diff_ref'))}


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_diff_only_fetches_on_click_and_renders_text(cockpit, tmp_path, provider):
    content = '\n'.join([INERT] + [f'fixture line {i}' for i in range(1, 12)])
    records = (claude_records('Write', dict(content=content), metadata=dict(type='create', originalFile=None))
               if provider == 'claude' else [codex_record({PATH: dict(type='add', content=content)})])
    rows, payloads = projected(tmp_path, provider, records)
    js, wait, _ = prepare(cockpit, provider, rows=rows, working=False)
    js('window.diffPayloads='+json.dumps(payloads)+''';
        window.diffReads=[];
        OrreryConversationSource.Source.prototype.stepDiff=async ref=>{diffReads.push(ref);return diffPayloads[ref]};
        document.querySelector('.conversation-steps-toggle').click();
        window.diffToggle=document.querySelector('.conversation-step-diff-toggle:not([hidden])');
    ''')
    assert js('diffToggle.querySelector(".conversation-step-diff-plus").textContent') == '+12'
    assert js('diffToggle.querySelector(".conversation-step-diff-minus").hidden')
    assert js('diffReads.length') == 0
    assert js("!document.querySelector('.conversation-step-diff-code')")
    js('diffToggle.click()')
    wait("document.querySelectorAll('.conversation-step-diff-line').length===8")
    assert js('diffReads') == list(payloads)
    assert js("document.querySelector('.conversation-step-diff-head').textContent") == 'New file'
    assert js("document.querySelector('.conversation-step-diff-text').textContent") == INERT
    assert js("document.getElementById('fixture-inert')===null")
    assert js("document.querySelector('.conversation-step-diff-fold').textContent") == 'Show 4 more lines'
    js("document.querySelector('.conversation-step-diff-fold').click()")
    assert js("document.querySelectorAll('.conversation-step-diff-line').length") == 12
    js("document.querySelector('.conversation-step-diff-fold').focus();diffToggle.click()")
    assert js("document.activeElement===diffToggle&&diffToggle.getAttribute('aria-expanded')==='false'")
    assert js('diffReads.length') == 1


def test_switching_diffs_aborts_the_previous_request_and_shows_the_limit(cockpit, tmp_path):
    first = codex_record({PATH: dict(type='update', unified_diff='@@ -1 +1,2 @@\n keep\n+first\n')})
    second = codex_record({'/fixture/long.txt': dict(type='add', content='preview\n' * 401)})
    second['payload']['item']['id'] = 'separate-operation'
    rows, payloads = projected(tmp_path, 'codex', [first, second])
    js, wait, _ = prepare(cockpit, 'codex', rows=rows, working=False)
    js('window.diffPayloads='+json.dumps(payloads)+''';
        window.diffReads=[];
        OrreryConversationSource.Source.prototype.stepDiff=(ref,{signal})=>{
          diffReads.push({ref,signal});
          if(diffReads.length>1)return Promise.resolve(diffPayloads[ref]);
          return new Promise(resolve=>window.releaseDiff=()=>resolve(diffPayloads[ref]));
        };
        document.querySelector('.conversation-steps-toggle').click();
        window.diffButtons=[...document.querySelectorAll('.conversation-step-diff-toggle:not([hidden])')];
        diffButtons[0].click();diffButtons[1].click();releaseDiff();
    ''')
    wait("document.querySelector('.conversation-step-diff-note')?.textContent==='Too long to show here'")
    assert js("diffButtons[0].querySelector('.conversation-step-diff-minus').textContent") == '−0'
    assert js('diffReads.map(call=>call.signal.aborted)') == [True, False]
    assert js("document.querySelectorAll('.conversation-step-diff:not([hidden])').length") == 1
    assert js("document.querySelector('.conversation-step-diff-text').textContent") == 'preview'
    assert js("!document.querySelector('.conversation-step-diff-fold')")
