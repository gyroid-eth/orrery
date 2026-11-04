"""Inert GFM tables in the real reader, including copy and terminal search."""
import sys,json,time
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_conversation_review_regressions import cockpit,stable_roster
TABLE='前の段落\n\n| | 公式ベンチ | 補助の測定 |\n|---|:---:|---:|\n| 日本語 | 123 | 456 |\n| literal | <img src=x onerror=alert(1)> | [link](https://example.invalid) |\n\n後の段落'


def prepare(cockpit,text=TABLE,provider='codex'):
    js,wait,client,requests,enable=cockpit
    stable_roster(js);enable(count=1);js('conversationView.close()')
    js('window.originalMessage='+json.dumps(text)+';OrreryConversationSource.Source.prototype.read=async()=>({provider:'+json.dumps(provider)+",events:[{id:'table',kind:'text',role:'assistant',text:originalMessage}],after:'one'});conversationView.open()")
    wait("document.querySelector('[data-event-id=table]')!==null")
    return js,wait,client


@pytest.mark.parametrize('provider',['codex','claude','dsh','hermes'])
def test_table_is_text_only_and_surrounding_paragraphs_stay(cockpit,provider):
    js,wait,client=prepare(cockpit,provider=provider)
    assert js("document.querySelectorAll('.conversation-text table').length")==1
    assert js("[...document.querySelectorAll('th')].map(e=>e.textContent)")==['','公式ベンチ','補助の測定']
    assert js("document.querySelectorAll('.conversation-text img,.conversation-text a,.conversation-text script').length")==0
    assert js("document.querySelector('.conversation-text').textContent.startsWith('前の段落\\n\\n')")
    assert js("document.querySelector('.conversation-text').textContent.endsWith('\\n後の段落')")
    assert js("document.querySelector('thead th:last-child').style.textAlign")=='right'


def test_strict_parser_rejects_malformed_fenced_indented_and_plain_pipe_text(cockpit):
    js,wait,client=prepare(cockpit)
    cases=['a | b\nnot a delimiter\nx | y','| a | b |\n|---|---|\n| mismatch |','```md\n|a|b|\n|---|---|\n|x|y|\n```','~~~~\n|a|b|\n|---|---|\n~~~~','    |a|b|\n    |---|---|','|a|b|\n|--|---|']
    for text in cases:assert js('OrreryConversationMarkdown.parse('+json.dumps(text)+").every(b=>b.kind==='text')"),text
    assert js("OrreryConversationMarkdown.parse('|a|b|\\n|---|---|\\n|left\\\\|right|tail|')[0].rows[0][0]")=='left|right'
    assert js("OrreryConversationMarkdown.parse('|a|\\n|---|\\n|b|')[0].header")==['a']


def test_copy_button_uses_original_markdown_without_terminal_jump(cockpit):
    js,wait,client=prepare(cockpit)
    js("window.copied=null;Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>copied=text},configurable:true});document.querySelector('.conversation-table-copy').click()")
    wait('copied!==null')
    assert js('copied')==TABLE[TABLE.index('|'):TABLE.index('\n\n後')+1]
    time.sleep(.65)
    assert not js("document.querySelector('.conversation-toolbar').textContent.includes('見つかりません')")
    assert js("packets.filter(p=>p.type==='input')")==[]


def test_table_cell_jump_searches_original_message(cockpit):
    js,wait,client=prepare(cockpit)
    js("window.searched=null;OrreryConversationTerminal.find=(...args)=>{searched=args;return {state:'absent'}}")
    # Use the real terminal adapter and its original text rather than DOM text.
    js("{const p=panes.get('%901');p.meta.alternateOn=false;p._wheelAlternate=false;writePaneOutput(p,{snapshot:true,data:('earlier\\r\\n'.repeat(20))+originalMessage.replace(/\\n/g,'\\r\\n')+('\\r\\nlater'.repeat(80))})}")
    wait("!hostSnapshotPending(panes.get('%901').host)")
    js("document.querySelector('td').click()")
    wait("panes.get('%901').term.getSelection().includes('公式ベンチ')")
    assert js("panes.get('%901').term.getSelection().includes('|---|:---:|---:|')")
    assert js("packets.filter(p=>p.type==='input')")==[]


@pytest.mark.parametrize('width',[900,390])
def test_wide_table_scrolls_inside_reader(cockpit,width):
    text='|'+ '|'.join('日本語の長い列名'+str(i) for i in range(12))+'|\n|'+'|'.join(['---']*12)+'|\n|'+'|'.join(['長い測定結果の文字列']*12)+'|'
    js,wait,client=prepare(cockpit,text)
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=844,deviceScaleFactor=1,mobile=False);time.sleep(.2)
    assert js("(()=>{const e=document.querySelector('.conversation-table-scroll');return e.scrollWidth>e.clientWidth&&e.getBoundingClientRect().right<=document.querySelector('.conversation-scroll').getBoundingClientRect().right})()")
    js("document.querySelector('.conversation-table-scroll').scrollLeft=100")
    assert js("document.querySelector('.conversation-table-scroll').scrollLeft")>0
