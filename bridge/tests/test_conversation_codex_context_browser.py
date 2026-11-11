"""Codex context uses the existing system row and does not alter human input."""
import json

import pytest

from test_conversation_codex_context import ENVIRONMENT, INSTRUCTIONS, message
from test_conversation_providers import line, page, row
from test_conversation_review_regressions import cockpit, stable_roster


@pytest.mark.parametrize('cockpit', [False, True], indirect=True, ids=['desktop', 'phone-width'])
def test_codex_injected_context_folds_but_literal_human_input_stays_visible(cockpit, tmp_path):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([INSTRUCTIONS, ENVIRONMENT],
                                 ['agents_md.instructions', 'environments.environment_context'])) +
                     line(message([ENVIRONMENT], ['user.text'])))
    events = page(row(path, 'codex'))['events']
    js, wait, client, _, enable = cockpit
    stable_roster(js)
    enable(count=1)
    js('conversationView.close();OrreryConversationSource.Source.prototype.read=async()=>({events:' +
       json.dumps(events) + ',provider:"codex",after:"end"});conversationView.open()')
    wait("document.querySelectorAll('.conversation-event').length===2")
    assert js("[...document.querySelectorAll('.conversation-role')].map(e=>e.textContent)") == ['You']
    assert js("document.querySelector('.conversation-system-toggle').textContent") == '▸System notice'
    assert js("document.querySelector('.conversation-system-detail').hidden")
    assert js("document.querySelector('.conversation-text').textContent") == ENVIRONMENT
    js("document.querySelector('.conversation-system-toggle').focus()")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', windowsVirtualKeyCode=13, text='\r')
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    wait("!document.querySelector('.conversation-system-detail').hidden")
    assert js("document.querySelector('.conversation-system-detail').textContent") == INSTRUCTIONS + '\n' + ENVIRONMENT
    assert js("document.querySelector('.conversation-system-toggle').getAttribute('aria-expanded')") == 'true'
    assert js("packets.filter(p=>p.type==='input')") == []


def test_demo_copy_keeps_original_paths_when_only_some_candidates_exist(cockpit):
    js, wait, client, _, enable = cockpit
    stable_roster(js)
    enable(count=1)
    # Start demo mode with a synthetic identity, without any account lookup.
    js("""conversationView.close();
      history.replaceState({},'',location.pathname+'?demo=1');
      window.fetchBeforeDemo=window.fetch;window.fetch=(url,...args)=>String(url)==='/telemetry/identity'
        ?Promise.resolve(new Response(JSON.stringify({users:['mira'],hosts:[]})))
        :fetchBeforeDemo(url,...args);
      document.head.appendChild(Object.assign(document.createElement('script'),{src:'demo_mode.js'}));
    """)
    wait('OrreryDemo.on&&OrreryDemo.known')
    text = '/Users/mira/existing.txt\n/Users/mira/missing.txt'
    js('window.copySource=' + json.dumps(text) + ';' + """
      window.releasePathProbe=null;
      OrreryConversationSource.Source.prototype.probePaths=texts=>new Promise(resolve=>{
        releasePathProbe=()=>resolve(texts.map(text=>text.includes('existing')?{shown:text,path:text}:null));
      });
      OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:'demo-paths',kind:'text',role:'user',text:copySource}],after:'end'});
      conversationView.open();
    """)
    wait('releasePathProbe!==null')
    wait("document.querySelector('.conversation-text').textContent.includes('/Users/****/missing.txt')")
    js('releasePathProbe()')
    wait("document.querySelectorAll('.conversation-text [data-path-candidate]').length===0")
    assert js("document.querySelector('.conversation-text').textContent") == text.replace('mira', '****')
    copied = js("""(()=>{
      const body=document.querySelector('.conversation-text'),range=document.createRange();range.selectNodeContents(body);
      const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
      const clipboard=new DataTransfer(),event=new ClipboardEvent('copy',{clipboardData:clipboard,bubbles:true,cancelable:true});
      body.dispatchEvent(event);return clipboard.getData('text/plain')||String(selection);
    })()""")
    assert copied == text
