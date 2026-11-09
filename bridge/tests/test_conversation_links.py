"""Bare HTTP links in every reader surface and their activation boundary."""
import base64
import json
import re
import time

import pytest
from test_preview_markdown_document import html, run
from test_conversation_review_regressions import cockpit, stable_roster

EXAMPLE = ('今回の数字の元になったページの URL です。\n\n'
           '- 参考ページ（本文を確かめた）\n  https://example.com/article/\n'
           '- 為替（参考値）\n  https://example.com/rates\n\n'
           '検索ページそのものも載せておきます。\nhttps://example.com/search?q=RTX3090')


def test_document_bare_links_in_prose_lists_quotes_tables_and_code():
    source = (EXAMPLE + '\n\n> https://example.com/quote。\n\n'
              '| URL |\n|---|\n| https://example.com/table |\n\n'
              '`https://example.com/inline`\n\n```\nhttps://example.com/code\n```\n\n'
              '    https://example.com/indented')
    out = html(source)
    assert out.count('<a ') == 8
    assert '<code><a href="https://example.com/inline"' in out
    assert '<code><a href="https://example.com/code"' in out
    assert '<td><a href="https://example.com/table"' in out


@pytest.mark.parametrize('suffix', list('。、，．！？「」『』（）【】〈〉《》\u3000') + ['.', ',', ';', ':', '!', '?', ')', ']', '}'])
def test_url_boundaries(suffix):
    out = html('https://example.com/path' + suffix)
    assert 'href="https://example.com/path"' in out
    assert '>https://example.com/path</a>' in out


def test_balanced_parentheses_existing_links_and_invalid_schemes():
    out = html('https://example.com/wiki/Test_(topic)). '
               '[label](https://example.com/linked) <https://example.com/angle> '
               '[https://example.com/label](https://example.com/target) '
               'ftp://example.com file:///tmp/example javascript:void0 http:// https://:bad')
    assert out.count('<a ') == 4
    assert 'href="https://example.com/wiki/Test_(topic)"' in out
    assert '<a ' not in out.split('ftp:')[1]
    assert '<a href="https://example.com/target"' in out
    assert '<a ' not in out.split('href="https://example.com/target"')[1].split('</a>')[0]


def test_raw_reader_keeps_text_and_links_table_and_markdown_targets_once():
    source = (EXAMPLE + '\n\n[文字](https://example.com/linked)\n<https://example.com/angle>\n'
              '`https://example.com/code`\n```\nhttps://example.com/fenced\n```\n'
              '> https://example.com/quote。\n[百科](https://example.com/wiki/Test_(topic))\n\n'
              '| URL |\n|---|\n| http://example.com/table |\n')
    result = json.loads(run('const h=new Element("div");md.render('+json.dumps(source)+',h);console.log(JSON.stringify({text:h.textContent,html:h.html()}));'))
    assert result['html'].count('<a ') == 10
    assert result['html'].count('href="https://example.com/linked"') == 1
    assert '>https://example.com/linked</a>)' in result['html']
    assert '>https://example.com/wiki/Test_(topic)</a>)' in result['html']
    assert '<td><a href="http://example.com/table"' in result['html']
    assert result['text'].startswith(EXAMPLE)


@pytest.mark.parametrize('source,raw_hrefs,document_hrefs', [
    ('[https://example.com](https://example.org)',
     ['https://example.com/', 'https://example.org/'], ['https://example.org/']),
    ('[https://example.com/label](https://example.org/target)',
     ['https://example.com/label', 'https://example.org/target'], ['https://example.org/target']),
    ('[https://example.com/_x_](https://example.com/_x_)',
     ['https://example.com/_x_', 'https://example.com/_x_'], ['https://example.com/_x_']),
    ('(https://example.com/a)', ['https://example.com/a'], ['https://example.com/a']),
    ('https://en.wikipedia.org/wiki/Foo_(bar)',
     ['https://en.wikipedia.org/wiki/Foo_(bar)'], ['https://en.wikipedia.org/wiki/Foo_(bar)']),
    ('[label](https://example.org/x_(y))', ['https://example.org/x_(y)'], ['https://example.org/x_(y)']),
    ('https://example.com/path[part]', ['https://example.com/path[part]'], ['https://example.com/path[part]']),
    ('https://example.com/a)https://example.org/b',
     ['https://example.com/a', 'https://example.org/b'], ['https://example.com/a', 'https://example.org/b']),
])
@pytest.mark.parametrize('context', ['{}', '| URL |\n|---|\n| {} |'])
def test_unmatched_closing_brackets_end_a_url(source, raw_hrefs, document_hrefs, context):
    result = json.loads(run('const h=new Element("div");md.render('+json.dumps(context.format(source))+',h);console.log(JSON.stringify({text:h.textContent,html:h.html()}));'))
    assert source in result['text']
    assert re.findall(r'href="([^"]*)"', result['html']) == raw_hrefs
    assert re.findall(r'href="([^"]*)"', html(context.format(source))) == document_hrefs


@pytest.mark.parametrize('expression', ["'x'.repeat(200000)", "'https://example.com/a '.repeat(10000)", "'https://example.com/'+ 'x'.repeat(200000)", "'http://'.repeat(30000)"])
def test_long_lines_remain_fast_and_do_not_link_partial_overlong_urls(expression):
    result = json.loads(run('const text='+expression+';const h=new Element("div");const t=performance.now();md.render(text,h);show(text);console.log(JSON.stringify({ms:performance.now()-t,links:h.html().split("<a ").length-1}));'))
    assert result['ms'] < 1500, result
    assert result['links'] == (10000 if expression == "'https://example.com/a '.repeat(10000)" else 0)


def test_bare_url_length_limit_and_case():
    prefix = 'HTTPS://example.com/'
    valid = prefix + 'a' * (2000 - len(prefix))
    out = html(valid + ' ' + valid + 'b')
    assert out.count('<a ') == 1
    assert 'href="https://example.com/' in out


@pytest.mark.parametrize('url', [
    'https://example.com/_file_', 'https://example.com/?q=_word_',
    'https://example.com/a~~b~~', 'https://example.com/search?q=_foo_&x=1',
    'https://example.com/#_heading_', 'https://example.com/#~~bar~~',
])
@pytest.mark.parametrize('context', ['{}', '- {}', '| URL |\n|---|\n| {} |'])
def test_markdown_tokens_inside_bare_urls_stay_in_the_link(url, context):
    out = html(context.format(url))
    escaped = url.replace('&', '&amp;')
    assert out.count('<a ') == 1
    assert 'href="'+escaped+'"' in out
    assert '>'+escaped+'</a>' in out
    assert '<em>' not in out and '<del>' not in out


@pytest.mark.parametrize('source,href,wrapper', [
    ('*https://example.com/*', 'https://example.com/', 'em'),
    ('**https://example.com/a_b_c**', 'https://example.com/a_b_c', 'strong'),
    ('[https://example.com/_x_](https://example.com/_x_)', 'https://example.com/_x_', None),
])
def test_markdown_tokens_around_urls_and_explicit_labels(source, href, wrapper):
    out = html(source)
    assert out.count('<a ') == 1
    assert 'href="'+href+'"' in out
    assert '>'+href+'</a>' in out
    if wrapper:
        assert '<'+wrapper+'><a ' in out


def test_bare_urls_need_a_boundary_and_overlong_markdown_stays_text():
    assert '<a ' not in html('abchttps://example.com/_file_')
    result = json.loads(run("const text='https://example.com/'+'_http://'.repeat(30000);const t=performance.now();const out=show(text);console.log(JSON.stringify({ms:performance.now()-t,links:out.split('<a ').length-1}));"))
    assert result['links'] == 0
    assert result['ms'] < 1500


def prepare(cockpit):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    js('window.openedLinks=[];window.jumps=[]')
    enable(count=1)
    js('conversationView.close();window.readerLinkText='+json.dumps(EXAMPLE)+';OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:"assistant-links",kind:"text",role:"assistant",text:readerLinkText},{id:"user-links",kind:"text",role:"user",text:"（https://example.com/user）。"},{id:"mail-links",kind:"mail",role:"assistant",text:"Recorded Mail",mail:[{direction:"received",subject:"Links",body:"https://example.com/mail。",coverage:"complete"}]}],after:"one"});document.querySelectorAll(".conversation-panel").forEach(el=>el.remove());window.readerLinks=OrreryConversation.mount({getContext:()=>({...currentAgents[0],terminalPaneId:"%901"}),bindToggle:false,openExternalUrl:url=>openedLinks.push(url),jumpToEvent:event=>{jumps.push(event);return {state:"absent"}}});readerLinks.open()')
    wait('document.querySelector("[data-event-id=mail-links]")!==null')
    js("""document.querySelector('.conversation-expand[aria-controls="'+readerLinks.panel.id+'"]').click();openedLinks.length=0;jumps.length=0""")
    return js, wait, client


def test_user_mail_click_modifiers_enter_and_selection_never_jump(cockpit):
    js, wait, client = prepare(cockpit)
    assert js('document.querySelectorAll("[data-event-id=assistant-links] a").length') == 3
    assert js('document.querySelector("[data-event-id=user-links] a").href') == 'https://example.com/user'
    assert js('document.querySelector(".conversation-mail-text a").href') == 'https://example.com/mail'
    js('document.querySelector("[data-event-id=user-links] a").click()')
    time.sleep(.75)
    assert js('openedLinks') == ['https://example.com/user']
    assert js('jumps') == []
    js('document.querySelector("[data-event-id=user-links] a").focus()')
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    time.sleep(.75)
    assert js('openedLinks') == ['https://example.com/user'] * 2
    assert js('jumps') == []
    js('document.querySelector("[data-event-id=user-links] a").dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,ctrlKey:true,metaKey:true}))')
    assert js('openedLinks') == ['https://example.com/user'] * 3
    js('''{const a=document.querySelector('[data-event-id=user-links] a'),r=document.createRange();r.selectNodeContents(a);getSelection().removeAllRanges();getSelection().addRange(r);a.click();}''')
    time.sleep(.75)
    assert js('openedLinks') == ['https://example.com/user'] * 3
    assert js('jumps') == []
    js('getSelection().removeAllRanges();document.querySelector("[data-event-id=user-links] a").dispatchEvent(new PointerEvent("pointerdown",{bubbles:true,clientX:1,clientY:1}));document.querySelector("[data-event-id=user-links] a").dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,detail:1,clientX:30,clientY:1}))')
    time.sleep(.75)
    assert js('openedLinks') == ['https://example.com/user'] * 3
    assert js('jumps') == []


def test_preview_links_source_code_and_mailto_keep_activation_boundary(cockpit):
    js, wait, client = prepare(cockpit)
    js('OrreryConversationSource.Source.prototype.reference=async()=>({kind:"text",text:"`https://example.com/code` [mail](mailto:reader@example.com) https://example.com/search?q=_foo_&x=1。 https://example.com/#~~bar~~"});OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:"file",kind:"tool",role:"assistant",text:"read",references:[{id:"A".repeat(32),label:"example.md",kind:"file"}]}],after:"two"});readerLinks.refresh()')
    wait('document.querySelector(".conversation-file")!==null')
    js('document.querySelector(".conversation-file").click()')
    wait('document.querySelector(".conversation-preview-markdown a")!==null')
    assert js('document.querySelector(".conversation-preview-markdown code a").href') == 'https://example.com/code'
    js('document.querySelector(".conversation-preview-markdown code a").click()')
    assert js('openedLinks') == ['https://example.com/code']
    js('document.querySelector(".conversation-preview-markdown a[href*=search]").click()')
    assert js('openedLinks') == ['https://example.com/code', 'https://example.com/search?q=_foo_&x=1']
    assert js('document.querySelector(".conversation-preview-markdown a[href*=bar]").textContent') == 'https://example.com/#~~bar~~'
    js('readerLinks.panel.addEventListener("click",e=>{window.mailWasPrevented=e.defaultPrevented;e.preventDefault()},{once:true});document.querySelector("a[href^=mailto]").click()')
    assert js('mailWasPrevented') is False
    assert js('openedLinks') == ['https://example.com/code', 'https://example.com/search?q=_foo_&x=1']
    js('document.querySelector(".conversation-preview-source").click()')
    assert js('document.querySelectorAll(".conversation-preview-text a").length') == 3


def test_reader_link_screenshots(cockpit, tmp_path):
    js, wait, client = prepare(cockpit)
    js('document.querySelector(".conversation-scroll").scrollTop=0')
    output = tmp_path
    for theme in ['dark', 'light']:
        js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
        time.sleep(.15)
        (output / (theme+'.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot', format='png')['data']))
    print('History link screenshots:', output)


def test_cockpit_workspace_passes_its_external_opener(cockpit):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    js('window.appLinks=[];window.__TAURI__={core:{invoke:async(command,args)=>{appLinks.push({command,...args})}}}')
    enable(count=1)
    js('conversationView.close();OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:"app-link",kind:"text",role:"assistant",text:"https://example.com/app。"}],after:"one"});conversationView.open()')
    wait('document.querySelector("[data-event-id=app-link] a")!==null')
    js('document.querySelector("[data-event-id=app-link] a").click()')
    time.sleep(.75)
    assert js('appLinks') == [dict(command='open_external_url', url='https://example.com/app')]
    assert '/telemetry/open-url' not in requests
    assert 'Keep reading history here' not in js('document.querySelector(".conversation-toolbar").textContent')


def test_standalone_reader_falls_back_to_browser_open(cockpit):
    js, wait, client = prepare(cockpit)
    js('readerLinks.dispose();window.browserLinks=[];window.open=(...args)=>browserLinks.push(args);readerLinks=OrreryConversation.mount({getContext:()=>({...currentAgents[0],terminalPaneId:"%901"}),bindToggle:false});readerLinks.open()')
    wait('document.querySelector("[data-event-id=user-links] a")!==null')
    js('document.querySelector("[data-event-id=user-links] a").click()')
    assert js('browserLinks') == [['https://example.com/user', '_blank', 'noopener,noreferrer']]


def test_double_click_and_middle_click_use_the_opener_once(cockpit):
    js, wait, client = prepare(cockpit)
    point = js('(()=>{const a=document.querySelector("[data-event-id=assistant-links] a");a.scrollIntoView({block:"center"});const r=a.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
    for count in [1, 2]:
        client.call('Input.dispatchMouseEvent', type='mousePressed', button='left', clickCount=count, **point)
        client.call('Input.dispatchMouseEvent', type='mouseReleased', button='left', clickCount=count, **point)
    time.sleep(.75)
    assert js('openedLinks') == ['https://example.com/article/']
    selected = js('getSelection().toString()')
    js('document.querySelector("[data-event-id=assistant-links] a").dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,detail:2}))')
    assert js('getSelection().toString()') == selected
    assert js('openedLinks') == ['https://example.com/article/']
    js('getSelection().removeAllRanges()')
    js('readerLinks.panel.addEventListener("auxclick",e=>{if(e.button===1){window.middleWasPrevented=e.defaultPrevented;e.preventDefault()}})')
    client.call('Input.dispatchMouseEvent', type='mousePressed', button='middle', clickCount=1, **point)
    client.call('Input.dispatchMouseEvent', type='mouseReleased', button='middle', clickCount=1, **point)
    time.sleep(.75)
    assert js('openedLinks') == ['https://example.com/article/'] * 2
    assert js('middleWasPrevented') is True
    assert js('jumps') == []
    js('window.rightWasPrevented=null;readerLinks.panel.addEventListener("auxclick",e=>rightWasPrevented=e.defaultPrevented,{once:true});document.querySelector("[data-event-id=assistant-links] a").dispatchEvent(new MouseEvent("auxclick",{bubbles:true,cancelable:true,button:2}))')
    assert js('rightWasPrevented') is False
    assert js('openedLinks') == ['https://example.com/article/'] * 2


@pytest.mark.parametrize('source,expected', [
    ('[https://example.com](https://example.org)', ['https://example.com/', 'https://example.org/']),
    ('[https://example.com/label](https://example.org/target)', ['https://example.com/label', 'https://example.org/target']),
    ('[https://example.com/_x_](https://example.com/_x_)', ['https://example.com/_x_', 'https://example.com/_x_']),
])
@pytest.mark.parametrize('role', ['assistant', 'user'])
def test_raw_markdown_url_label_and_target_open_separately(cockpit, source, expected, role):
    js, wait, client = prepare(cockpit)
    event = dict(id='separate-links', kind='text', role=role, text=source)
    js('OrreryConversationSource.Source.prototype.read=async()=>({events:['+json.dumps(event)+'],after:"separate:1"});readerLinks.refresh()')
    wait('document.querySelector("[data-event-id=separate-links] a")!==null')
    js('document.querySelectorAll("[data-event-id=separate-links] a").forEach(a=>a.click())')
    time.sleep(.75)
    assert js('openedLinks') == expected
    assert js('jumps') == []
