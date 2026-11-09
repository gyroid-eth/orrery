"""Tool runs collapse without moving messages, hiding Mail, or losing focus."""
import json
import time

import pytest
from test_conversation_review_regressions import cockpit, wait_reading_layout
from test_reader_header_notices import show


def event(id, kind='text', text=None, **extra):
    return dict(id=id, kind=kind, role='assistant', text=text or ('Read' if kind == 'tool' else 'Generated message '+id), ts='2026-01-01T12:00:00Z', **extra)


def tools(prefix='t', count=5):
    return [row for i in range(count) for row in [event(prefix+str(i), 'tool', 'Read' if i == 0 else 'Bash'), event(prefix+str(i)+'r', 'tool_result', 'Tool result · completed')]]


def sample():
    return [event('intro', text='I will check these generated files.')] + tools() + [event('mail', 'mail', mail=[dict(direction='received', sender='ParentFixture', subject='Generated review note', body='Keep this readable Mail card.', coverage='complete')])] + tools('next', 2) + [event('answer', text='The checks are complete.')]


def prepare(cockpit, theme='dark', layout='desktop', rows=None, mode='cursor'):
    js, wait, client = show(cockpit, theme, layout)
    rows = sample() if rows is None else rows
    js('conversationView.close();window.foldPage='+json.dumps(dict(events=rows, mode=mode, before='first', after='tail', has_older=True))+';window.foldOlder=null;window.foldReads=0;')
    js("OrreryConversationSource.Source.prototype.read=async(name,options)=>{foldReads++;return options.before&&foldOlder?foldOlder:foldPage};conversationView.open()")
    wait('readerHost.querySelectorAll(".conversation-event").length==='+str(len(rows)))
    wait_reading_layout(js)
    js("window.foldGroups=()=>[...reader.querySelectorAll('.conversation-tool-group')];readerScroll.scrollTop=0;packets.length=0")
    return js, wait, client


def key(client, value, code):
    for kind in ['keyDown', 'keyUp']:
        client.call('Input.dispatchKeyEvent', type=kind, key=value, code='Space' if value == ' ' else value, windowsVirtualKeyCode=code, **({'text':' ' if value == ' ' else '\r'} if kind == 'keyDown' else {}))


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('layout', ['desktop', 'phone', 'split', 'split-phone'])
def test_tool_runs_default_closed_and_native_keyboard_does_not_jump(cockpit, theme, layout):
    js, wait, client = prepare(cockpit, theme, layout)
    assert js('foldGroups().length') == 2
    assert js("foldGroups().every(b=>b.getAttribute('aria-expanded')==='false')")
    assert js("foldGroups()[0].title.includes('5 tool calls · Bash ×4, Read ×1')")
    assert js("foldGroups()[0].querySelector('.conversation-tool-times').textContent")
    assert js("[...reader.querySelectorAll('[data-kind=tool],[data-kind=tool_result]')].every(e=>e.hidden)")
    assert js("reader.querySelector('.conversation-mail').getBoundingClientRect().height>0")
    assert js("foldGroups().every(b=>b.scrollWidth<=b.clientWidth+1)")
    js('foldGroups()[0].click();foldGroups()[0].focus()')
    assert js("reader.querySelector('[data-event-id=t0]').hidden") is False
    key(client, 'Enter', 13)
    assert js("foldGroups()[0].getAttribute('aria-expanded')") == 'false'
    key(client, ' ', 32)
    assert js("foldGroups()[0].getAttribute('aria-expanded')") == 'true'
    time.sleep(.65)
    assert js("readerHost.querySelector('.conversation-toolbar').hidden")
    js('queueStageFit(activeId)')
    time.sleep(.12)
    assert js('document.activeElement===foldGroups()[0]')
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('layout', ['desktop', 'phone', 'split', 'split-phone'])
def test_tail_count_growth_keeps_the_same_character_and_follows_bottom(cockpit, theme, layout):
    rows = [event('text'+str(i), text='Generated readable message '+str(i)+'.\nSecond line to read.') for i in range(40)] + tools(count=1)
    js, wait, client = prepare(cockpit, theme, layout, rows)
    assert js('foldGroups().length') == 1
    js("""window.keptGroup=foldGroups()[0];window.keptText=reader.querySelector('[data-event-id=text20] .conversation-text').firstChild;
      window.keptRange=document.createRange();keptRange.setStart(keptText,4);keptRange.setEnd(keptText,5);
      window.keptTop=()=>keptRange.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top;
      readerScroll.dispatchEvent(new WheelEvent('wheel'));readerScroll.scrollTop+=keptRange.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top-32;
      readerScroll.dispatchEvent(new Event('scroll'));getSelection().removeAllRanges();getSelection().addRange(keptRange.cloneRange());""")
    time.sleep(.08)
    before = js('keptTop()')
    for n in range(2, 5):
        js('foldPage.events.push(...'+json.dumps(tools('more'+str(n), 1))+');foldPage.after='+json.dumps('tail'+str(n))+';conversationView.refresh()')
        wait("foldGroups()[0].querySelector('.conversation-tool-count').textContent==="+json.dumps(str(n)+' tool calls'))
        assert abs(js('keptTop()')-before) <= 1
        assert js('keptText.isConnected&&foldGroups()[0]===keptGroup')
        assert js('getSelection().toString()') == 'r'
    js('getSelection().removeAllRanges();readerScroll.scrollTop=1e9;foldPage.events.push(...'+json.dumps(tools('last', 1))+');foldPage.after="last";conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=last0]')!==null")
    assert js('readerScroll.scrollHeight-readerScroll.clientHeight-readerScroll.scrollTop') <= 1


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_expanded_tail_follows_visible_new_tool_rows(cockpit, theme):
    js, wait, client = prepare(cockpit, theme, 'phone', tools(count=30))
    assert js('foldGroups().length') == 1
    js('foldGroups()[0].click();readerScroll.scrollTop=1e9;window.oldHeight=readerScroll.scrollHeight;foldPage.events.push(...'+json.dumps(tools('tail', 2))+');foldPage.after="expanded-tail";conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=tail1r]')!==null")
    assert js("reader.querySelector('[data-event-id=tail1r]').hidden") is False
    assert js('readerScroll.scrollHeight>oldHeight')
    assert js('readerScroll.scrollHeight-readerScroll.clientHeight-readerScroll.scrollTop') <= 1


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('layout', ['desktop', 'phone', 'split', 'split-phone'])
def test_older_page_merges_the_boundary_and_preserves_expansion(cockpit, theme, layout):
    js, wait, client = prepare(cockpit, theme, layout, tools(count=2)+[event('after')]+[event('later'+str(i)) for i in range(30)])
    assert js('foldGroups().length') == 1
    js("window.keptGroup=foldGroups()[0];keptGroup.click();keptGroup.focus();window.keptRow=reader.querySelector('[data-event-id=t0]')")
    older = dict(mode='cursor', events=[event('older-text')]+tools('older', 3), before='oldest', has_older=False)
    js('foldOlder='+json.dumps(older)+';OrreryConversationSource.Source.prototype.read=async()=>new Promise(resolve=>window.finishFoldOlder=resolve);reader.querySelector(".conversation-older").click()')
    wait("typeof finishFoldOlder==='function'")
    js('keptGroup.focus();finishFoldOlder(foldOlder)')
    wait("reader.querySelector('[data-event-id=older0]')!==null")
    assert js('foldGroups().length') == 1
    assert js("foldGroups()[0]===keptGroup&&keptGroup.getAttribute('aria-expanded')==='true'")
    assert js("keptGroup.querySelector('.conversation-tool-count').textContent") == '5 tool calls'
    assert js("reader.querySelector('[data-event-id=t0]')===keptRow&&!keptRow.hidden")
    assert js("!reader.querySelector('[data-event-id=older0]').hidden")
    assert js('document.activeElement===keptGroup')


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('mode', ['cursor', 'fresh_tail'])
def test_open_group_and_focus_survive_poll_and_refresh(cockpit, theme, mode):
    js, wait, client = prepare(cockpit, theme, rows=tools(count=1), mode=mode)
    assert js('foldGroups().length') == 1
    js('window.keptGroup=foldGroups()[0];keptGroup.click();keptGroup.focus();foldPage.events.push(...'+json.dumps(tools('new', 1))+');foldPage.after="new";conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=new0]')!==null")
    assert js("foldGroups()[0]===keptGroup&&keptGroup.getAttribute('aria-expanded')==='true'")
    assert js("!reader.querySelector('[data-event-id=new0]').hidden")
    assert js('document.activeElement===keptGroup')


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('open', [False, True], ids=['closed', 'open'])
def test_boundary_merge_keeps_the_reading_character(cockpit, theme, open):
    rows = tools(count=2)+[event('text'+str(i), text='Generated line to keep reading '+str(i)) for i in range(40)]
    js, wait, client = prepare(cockpit, theme, 'split-phone', rows)
    assert js('foldGroups().length') == 1
    if open:
        js('foldGroups()[0].click()')
    js("""window.readNode=reader.querySelector('[data-event-id=text20] .conversation-text').firstChild;
      window.readRange=document.createRange();readRange.setStart(readNode,4);readRange.setEnd(readNode,5);
      window.readTop=()=>readRange.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top;
      readerScroll.dispatchEvent(new WheelEvent('wheel'));readerScroll.scrollTop+=readRange.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top-32;readerScroll.dispatchEvent(new Event('scroll'));""")
    time.sleep(.08)
    before = js('readTop()')
    js('foldOlder='+json.dumps(dict(mode='cursor', events=[event('prefix')]+tools('older', 3), before='oldest', has_older=False))+';reader.querySelector(".conversation-older").click()')
    wait("reader.querySelector('[data-event-id=older0]')!==null")
    assert js('foldGroups().length') == 1
    assert abs(js('readTop()')-before) <= 1
    assert js("foldGroups()[0].getAttribute('aria-expanded')") == str(open).lower()


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_single_results_and_tool_mail_are_separate_readable_runs(cockpit, theme):
    rows = [event('call', 'tool', 'Read'), event('mail', 'tool', 'Mail', mail=[dict(direction='sent', recipients=['ParentFixture'], subject='Visible Mail boundary', body='Generated body', coverage='request')]), event('result', 'tool_result')]
    js, wait, client = prepare(cockpit, theme, rows=rows)
    assert js('foldGroups().length') == 2
    assert js("foldGroups().map(b=>b.querySelector('.conversation-tool-count').textContent)") == ['1 tool call', '1 tool result']
    assert js("reader.querySelector('[data-event-id=mail]').hidden") is False
    js("reader.querySelector('.conversation-mail-summary').click()")
    assert js("reader.querySelector('.conversation-mail').open")


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_closed_boundary_merges_and_internal_jump_reveals_the_tool(cockpit, theme):
    js, wait, client = prepare(cockpit, theme, rows=tools(count=1)+[event('answer')])
    assert js('foldGroups().length') == 1
    js('window.keptGroup=foldGroups()[0];foldOlder='+json.dumps(dict(mode='cursor', events=tools('older', 1), before='oldest', has_older=False))+';reader.querySelector(".conversation-older").click()')
    wait("reader.querySelector('[data-event-id=older0]')!==null")
    assert js("foldGroups().length===1&&foldGroups()[0]===keptGroup&&keptGroup.getAttribute('aria-expanded')==='false'")
    js("reader.querySelector('[data-event-id=t0] .conversation-byline').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))")
    assert js("keptGroup.getAttribute('aria-expanded')") == 'true'
    assert js("reader.querySelector('[data-event-id=t0]').hidden") is False
    assert js("!readerHost.querySelector('.conversation-toolbar').hidden")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('direction', ['newer', 'older'])
def test_retention_removes_events_without_orphaning_groups(cockpit, theme, direction):
    js, wait, client = prepare(cockpit, theme, rows=tools(count=200))
    assert js('foldGroups().length') == 1
    for n in range(2):
        page = dict(mode='cursor', events=tools('page'+str(n), 150), before='older'+str(n), after='newer'+str(n), has_older=False)
        if direction == 'older':
            js('foldOlder='+json.dumps(page)+';reader.querySelector(".conversation-older").hidden=false;reader.querySelector(".conversation-older").click()')
        else:
            js('readerScroll.scrollTop=1e9;foldPage='+json.dumps(page)+';conversationView.refresh()')
        wait("reader.querySelector('[data-event-id=page"+str(n)+"0]')!==null")
    assert js("reader.querySelectorAll('.conversation-event').length") == 800
    assert js('foldGroups().length') == 1
    assert js("foldGroups()[0].querySelector('.conversation-tool-count').textContent") == '400 tool calls'
    assert js("[...reader.querySelectorAll('.conversation-event')].every(e=>e.hidden)")
