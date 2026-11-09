"""Reader prose, inert command records, exact copies and send reconciliation."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_conversation_markdown import prepare
from test_conversation_submissions import prepare as prepare_submission
from test_conversation_review_regressions import cockpit, wait_reading_layout

CODE = '  printf "日本語 <ok>"\n\t# keep the tab and trailing spaces  \n\n'
SAMPLE = '# Result\n\n**Ready** with `inline` code.\n\n- first\n- second\n\n```sh\n' + CODE + '```\n\n```\nplain\n```'


@pytest.mark.parametrize('provider', ['claude', 'codex', 'dsh'])
def test_assistant_document_marks_and_code_copy(cockpit, provider):
    js, wait, client = prepare(cockpit, SAMPLE, provider)
    assert js("document.querySelector('.conversation-text h1').textContent") == 'Result'
    assert js("document.querySelector('.conversation-text strong').textContent") == 'Ready'
    assert js("document.querySelector('.conversation-text p code').textContent") == 'inline'
    assert js("document.querySelectorAll('.conversation-text li').length") == 2
    assert js("document.querySelectorAll('.conversation-code').length") == 2
    assert js("document.querySelector('.conversation-code-language').textContent") == 'sh'
    wait_reading_layout(js)
    js("window.copied=null;Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>copied=text},configurable:true});document.querySelector('.conversation-code-copy').focus()")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    wait('copied!==null')
    assert js('copied') == CODE
    assert js("document.querySelector('.conversation-code pre code').textContent") == CODE
    assert js("document.querySelector('.conversation-code-copy').textContent") == 'Copied'
    assert js("packets.filter(p=>p.type==='input')") == []
    js("document.querySelectorAll('.conversation-code-copy')[1].click()")
    wait("copied==='plain\\n'")


def user_message(cockpit, text):
    js, wait, client = prepare(cockpit, text)
    js("conversationView.close();OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:'command',kind:'text',role:'user',text:originalMessage}],after:'end'});conversationView.open()")
    wait("document.querySelector('[data-event-id=command]')!==null")
    return js, wait, client


@pytest.mark.parametrize('text,expected', [
    ('<bash-input>printf &quot;日本語&quot; &gt; result.txt &amp;&amp; echo &#39;ok&#39;</bash-input>', 'printf "日本語" > result.txt && echo \'ok\''),
    ('<command-name>/inspect</command-name>\n<command-message>inspect</command-message>\n<command-args>--label &lt;sample&gt;</command-args>', '/inspect --label <sample>'),
])
def test_command_records_are_blocks_with_exact_copy(cockpit, text, expected):
    js, wait, client = user_message(cockpit, text)
    assert js("document.querySelector('.conversation-command pre code').textContent") == '$ ' + expected
    js("window.copied=null;Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>copied=text},configurable:true});document.querySelector('.conversation-code-copy').click()")
    wait('copied!==null')
    assert js('copied') == expected


@pytest.mark.parametrize('text,labels,values', [
    ('<bash-stdout>a -&gt; b\n&lt;script&gt;alert(1)&lt;/script&gt; &amp;lt;</bash-stdout><bash-stderr>bad &quot;arg&quot;</bash-stderr>', ['stdout', 'stderr'], ['a -> b\n<script>alert(1)</script> &lt;', 'bad "arg"']),
    ('<local-command-stdout>status &gt; ready</local-command-stdout>', ['output'], ['status > ready']),
])
def test_output_entities_are_decoded_once_as_inert_text(cockpit, text, labels, values):
    js, wait, client = user_message(cockpit, text)
    assert js("[...document.querySelectorAll('.conversation-code-language')].map(e=>e.textContent)") == labels
    assert js("[...document.querySelectorAll('.conversation-text pre code')].map(e=>e.textContent)") == values
    assert js("document.querySelectorAll('.conversation-text script,.conversation-text img').length") == 0


def test_ordinary_user_text_and_entities_stay_literal(cockpit):
    source = '**literal** &gt; <script>alert(1)</script> <bash-input>not a whole record</bash-input>'
    js, wait, client = user_message(cockpit, source)
    assert js("document.querySelector('[data-event-id=command] .conversation-text').textContent") == source
    assert js("document.querySelectorAll('.conversation-text script,.conversation-text strong,.conversation-code').length") == 0


def test_assistant_html_images_and_long_line_stay_inert_and_responsive(cockpit):
    source = '<script>window.pwned=1</script>\n\n![image](https://example.test/never.png)\n\n# a' + ' ' * 131000 + 'z'
    js, wait, client = prepare(cockpit, source)
    assert js("document.querySelector('.conversation-text').textContent.includes('<script>window.pwned=1</script>')")
    assert js("document.querySelectorAll('.conversation-text img,.conversation-text script').length") == 0
    assert js('window.pwned===undefined')
    assert js("performance.getEntriesByType('resource').every(e=>!e.name.includes('never.png'))")
    assert js("(()=>{const start=performance.now(),host=document.createElement('div');OrreryConversationMarkdown.renderDocument(originalMessage,host,{codeControls:true});return performance.now()-start})()") < 1000


def test_bash_record_reconciles_sent_command(cockpit):
    js, wait, client = prepare_submission(cockpit, 'claude')
    js("sentText='! printf \"日本語\" > result.txt';newRecord.text='<bash-input>printf &quot;日本語&quot; &gt; result.txt</bash-input>';promptInput.value=sentText;sendPrompt()")
    wait('receipts.length===1')
    assert js("reader.querySelectorAll('.conversation-submission').length") == 1
    js('turnDone=true;conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=new]')!==null")
    assert js("reader.querySelectorAll('.conversation-submission').length") == 0


def test_unmatched_receipt_can_be_dismissed_without_dropping_record(cockpit):
    js, wait, client = prepare_submission(cockpit)
    js("newRecord.text='Different recorded prompt';promptInput.value=sentText;sendPrompt()")
    wait('receipts.length===1')
    js('turnDone=true;conversationView.refresh()')
    wait("reader.querySelector('.conversation-submission').textContent.includes('Record not matched')")
    js("reader.querySelector('.conversation-submission-dismiss').click()")
    assert js("reader.querySelectorAll('.conversation-submission').length") == 0
    assert js("reader.querySelector('[data-event-id=new]').textContent.includes('Different recorded prompt')")


@pytest.mark.parametrize('width', [1600, 390])
def test_long_code_scrolls_inside_reader(cockpit, width):
    js, wait, client = prepare(cockpit, '```sh\n' + 'a' * 1000 + '\n```')
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    wait("document.querySelector('.conversation-code')!==null")
    assert js("(()=>{const e=document.querySelector('.conversation-code pre');return e.scrollWidth>e.clientWidth&&e.getBoundingClientRect().right<=document.querySelector('.conversation-scroll').getBoundingClientRect().right})()")
    js("document.querySelector('.conversation-code pre').scrollLeft=100")
    assert js("document.querySelector('.conversation-code pre').scrollLeft") > 0


def test_system_notification_is_compact_and_keyboard_expandable(cockpit):
    js, wait, client = prepare(cockpit, 'placeholder')
    js("conversationView.close();OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:'notice',kind:'system',role:'system',text:'Background task completed',system_detail:'Generated check completed\\nStatus: completed\\nOutput: /fixture/output.txt'}],after:'end'});conversationView.open()")
    wait("document.querySelector('[data-event-id=notice]')!==null")
    assert js("document.querySelector('[data-event-id=notice] .conversation-role')") is None
    assert js("document.querySelector('.conversation-system-toggle').textContent") == '▸Background task completed'
    assert js("document.querySelector('.conversation-system-detail').hidden")
    wait_reading_layout(js)
    js("document.querySelector('.conversation-system-toggle').focus()")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    wait("document.querySelector('.conversation-system-toggle').getAttribute('aria-expanded')==='true'")
    assert js("document.querySelector('.conversation-system-detail').textContent.includes('/fixture/output.txt')")
    client.call('Input.dispatchKeyEvent', type='keyDown', key=' ', code='Space', windowsVirtualKeyCode=32, text=' ')
    client.call('Input.dispatchKeyEvent', type='keyUp', key=' ', code='Space', windowsVirtualKeyCode=32)
    wait("document.querySelector('.conversation-system-toggle').getAttribute('aria-expanded')==='false'")
    assert js("document.querySelector('.conversation-system-toggle').getAttribute('aria-expanded')") == 'false'
    js("document.querySelector('.conversation-system-toggle').click()")
    assert js("document.querySelector('.conversation-system-toggle').getAttribute('aria-expanded')") == 'true'


def test_copy_feedback_and_resize_preserve_the_same_code_character(cockpit):
    body = '\n'.join('line ' + str(n).zfill(3) + ': generated code' for n in range(80)) + '\n'
    js, wait, client = prepare(cockpit, '```text\n' + body + '```')
    wait_reading_layout(js)
    js("""window.readCode=document.querySelector('.conversation-code pre code').firstChild;
      window.codeRange=document.createRange(),codeScroll=document.querySelector('.conversation-scroll');
      const offset=readCode.textContent.indexOf('line 030');codeRange.setStart(readCode,offset);codeRange.setEnd(readCode,offset+1);
      codeScroll.dispatchEvent(new WheelEvent('wheel'));codeScroll.scrollTop+=codeRange.getBoundingClientRect().top-codeScroll.getBoundingClientRect().top-30;
      codeScroll.dispatchEvent(new Event('scroll'));
      window.codeTop=()=>codeRange.getBoundingClientRect().top-codeScroll.getBoundingClientRect().top;
    """)
    before = js('codeTop()')
    js("Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{}},configurable:true});document.querySelector('.conversation-code-copy').click()")
    wait("document.querySelector('.conversation-code-copy').textContent==='Copied'")
    client.call('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=False)
    wait_reading_layout(js)
    assert abs(js('codeTop()') - before) <= 1


def test_adjacent_bash_records_form_one_shell_entry_and_keep_human_prose(cockpit):
    js, wait, client = prepare(cockpit, 'placeholder')
    records = [dict(id='shell-in', role='user', kind='text', text='<bash-input>printf &quot;ready&quot;</bash-input>'),
               dict(id='shell-out', role='user', kind='text', text='<bash-stdout>result -&gt; ready</bash-stdout><bash-stderr></bash-stderr>'),
               dict(id='human', role='user', kind='text', text='**Keep this literal**')]
    js('conversationView.close();window.shellRows='+json.dumps(records[:1])+';OrreryConversationSource.Source.prototype.read=async()=>({events:shellRows,after:"shell"+shellRows.length});conversationView.open()')
    wait("document.querySelector('[data-event-id=shell-in]')!==null")
    js('window.keptCommand=document.querySelector(".conversation-command");shellRows.push(...'+json.dumps(records[1:])+');conversationView.refresh()')
    wait("document.querySelector('[data-event-id=human]')!==null")
    assert js("[...document.querySelectorAll('.conversation-event .conversation-byline')].filter(e=>getComputedStyle(e).display!=='none').map(e=>e.textContent)") == ['Shell', 'You']
    assert js("document.querySelector('[data-event-id=shell-out]').classList.contains('conversation-shell-continuation')")
    assert js("[...document.querySelectorAll('.conversation-command pre code')].map(e=>e.textContent)") == ['$ printf "ready"']
    assert js("document.querySelector('[data-event-id=shell-out] pre code').textContent") == 'result -> ready'
    assert js("document.querySelectorAll('[data-event-id=shell-out] .conversation-code').length") == 1
    assert js("document.querySelector('[data-event-id=human] .conversation-text').textContent") == '**Keep this literal**'
    # A late output joins the existing command without replacing its code DOM.
    assert js('keptCommand.isConnected')


def test_long_shell_output_can_be_expanded_and_copied_in_full(cockpit):
    output = '\n'.join('Generated output ' + str(n) for n in range(30))
    js, wait, client = user_message(cockpit, '<bash-stdout>'+output+'</bash-stdout>')
    assert js("document.querySelector('.conversation-role').textContent") == 'Shell'
    assert js("document.querySelector('.conversation-output-toggle').getAttribute('aria-expanded')") == 'false'
    assert js("document.querySelector('.conversation-code pre').clientHeight<=170")
    js("document.querySelector('.conversation-output-toggle').click()")
    assert js("document.querySelector('.conversation-output-toggle').getAttribute('aria-expanded')") == 'true'
    assert js("document.querySelector('.conversation-code pre').clientHeight>170")
    js("window.copied=null;Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>copied=text},configurable:true});document.querySelector('.conversation-code-copy').click()")
    wait('copied!==null')
    assert js('copied') == output
