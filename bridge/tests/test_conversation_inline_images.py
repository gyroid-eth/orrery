"""私有 HTTP fixture と共有 CDP で、会話内の画像と既存 preview を確認する。"""
import base64
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from test_conversation_review_regressions import cockpit, stable_roster
from test_conversation_shown_images import native_delivery


def image_data():
    output = io.BytesIO()
    Image.new('RGB', (640, 400), '#548eae').save(output, 'PNG')
    return dict(ok=True, kind='image', mime='image/png', width=640, height=400,
                data=base64.b64encode(output.getvalue()).decode())


def message(id, text, **fields):
    return dict(id=id, kind='text', role='assistant', text=text,
                ts='2026-11-01T04:00:00Z', **fields)


def shown(id='shown', name='mcp__orrery_mail__show_files', ref='a'*32):
    event = message(id, name)
    event.update(kind='tool', references=[dict(id=ref, kind='image', label='figure.png'),
                                         dict(id='z'*32, kind='file', label='report.md')])
    return event


def prepare(cockpit, events, *, delayed=False, preview=None):
    js, wait, client, _, enable = cockpit
    stable_roster(js); enable(count=1); js('conversationView.close()')
    js('window.inlineEvents=' + json.dumps(events) + ';window.inlineData=' + json.dumps(preview or image_data()) + ';' + """
      window.inlineCalls=[];window.inlinePending=[];window.inlineUrls=[];window.inlineRevoked=[];
      const makeUrl=URL.createObjectURL.bind(URL),revokeUrl=URL.revokeObjectURL.bind(URL);
      URL.createObjectURL=blob=>{const url=makeUrl(blob);inlineUrls.push(url);return url;};
      URL.revokeObjectURL=url=>{inlineRevoked.push(url);revokeUrl(url);};
      OrreryConversationSource.Source.prototype.read=async()=>({events:inlineEvents,before:'start',after:'end'});
      OrreryConversationSource.Source.prototype.reference=(id,options={})=>{
        inlineCalls.push({id,thumbnail:options.thumbnail===true,signal:options.signal});
        return """ + ('new Promise(resolve=>inlinePending.push(resolve))' if delayed else 'Promise.resolve(inlineData)') + """;
      };conversationView.open();
    """)
    wait("document.querySelectorAll('.conversation-event').length===" + str(len(events)))
    wait("document.querySelector('.conversation-panel').dataset.conversationLayout==='settled'")
    return js, wait, client


@pytest.mark.parametrize('cockpit', [True, False], indirect=True, ids=['phone', 'desktop'])
def test_agentstack_completed_delivery_reaches_inline_and_expanded_preview(cockpit, tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'alias-image.png'
    Image.new('RGB', (640, 400), '#548eae').save(image)
    store, bound, event = native_delivery(work, [str(image)], 'codex_legacy', 'agentstack')
    preview = store.read(event['references'][0]['id'], bound)
    js, wait, client = prepare(cockpit, [message('intro', '画像を表示します。'), event], preview=preview)
    wait("document.querySelector('.conversation-inline-thumbnail')?.naturalWidth===640")
    assert js("document.querySelector('.conversation-inline-label').textContent") == 'alias-image.png'
    assert js("document.querySelector('.conversation-inline-images').previousElementSibling.hidden")
    capture = os.environ.get('ORRERY_ALIAS_SCREENSHOTS')
    layout = 'phone' if js('innerWidth') == 390 else 'desktop'
    if capture:
        folder = Path(capture)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (layout + '-inline.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot', format='png')['data']))
    js("document.querySelector('.conversation-inline-image').click()")
    wait("document.querySelector('.conversation-preview-image')?.naturalWidth===640")
    assert js("inlineCalls.map(c=>c.thumbnail)") == [True, False]
    if capture:
        (folder / (layout + '-expanded.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot', format='png')['data']))


def test_shown_image_is_outside_tools_and_opens_existing_preview(cockpit):
    events = [message('intro', '確認用の画像を見せます。'), shown(),
              shown('other', 'read_file', 'b'*32), message('after', '画像の後の説明です。')]
    js, wait, client = prepare(cockpit, events)
    wait("document.querySelector('.conversation-inline-thumbnail')?.naturalWidth>0")
    assert js("document.querySelector('.conversation-inline-image').getBoundingClientRect().height") > 200
    assert js("document.querySelectorAll('.conversation-inline-images').length") == 1
    assert js("document.querySelector('[data-event-id=shown]').hidden")
    assert js("document.querySelector('.conversation-inline-images').previousElementSibling.dataset.eventId") == 'shown'
    assert js("document.querySelectorAll('[data-event-id=shown] .conversation-file').length") == 2
    assert js("inlineCalls.map(c=>({id:c.id,thumbnail:c.thumbnail}))") == [dict(id='a'*32, thumbnail=True)]
    js("document.querySelector('.conversation-tool-group').click();document.querySelector('.conversation-tool-group').focus();conversationView.refresh()")
    wait("!document.querySelector('[data-event-id=shown]').hidden")
    assert js("document.activeElement.classList.contains('conversation-tool-group')")
    js("document.querySelector('.conversation-inline-image').click()")
    wait("document.querySelector('.conversation-preview-image')?.naturalWidth>0")
    assert js("inlineCalls.map(c=>c.thumbnail)") == [True, False]
    assert js("document.querySelectorAll('.conversation-file[aria-pressed=true]').length") == 2
    assert js("packets.filter(p=>p.type==='input')") == []
    capture = os.environ.get('ORRERY_INLINE_SCREENSHOTS')
    if capture:
        folder = Path(capture); folder.mkdir(parents=True, exist_ok=True)
        (folder/'expanded.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot', format='png')['data']))
        js("document.querySelector('.conversation-preview-close').click();document.querySelector('.conversation-tool-group').click()")
        wait("document.querySelector('.conversation-preview').hidden")
        (folder/'inline.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot', format='png')['data']))


def test_only_nearby_thumbnails_load_and_requests_and_blobs_are_bounded(cockpit):
    events = []
    for i in range(20):
        events += [shown(str(i), ref=f'{i:032d}'), message('gap'+str(i), '説明。\n'*45)]
    js, wait, _ = prepare(cockpit, events, delayed=True)
    assert js('inlineCalls.length') == 0
    js("document.querySelector('.conversation-scroll').dispatchEvent(new Event('pointerdown'));document.querySelector('[data-inline-for=\"19\"]').scrollIntoView()")
    wait('inlineCalls.length>0')
    assert js('inlineCalls.length') <= 2
    assert js("inlineCalls.some(c=>c.id==='00000000000000000000000000000000')") is False
    js("inlinePending.splice(0).forEach(resolve=>resolve(inlineData))")
    wait("document.querySelectorAll('.conversation-inline-thumbnail[src]').length>0")
    wait("document.querySelector('.conversation-panel').dataset.conversationLayout!=='pending'")
    js("document.querySelector('.conversation-scroll').dispatchEvent(new Event('pointerdown'));document.querySelector('.conversation-scroll').scrollTop=0")
    wait("inlineCalls.some(c=>c.id==='00000000000000000000000000000000')")
    assert js("inlineCalls.filter(c=>!c.signal.aborted).length") <= 4
    assert js("document.querySelectorAll('.conversation-inline-thumbnail[src]').length") <= 8
    js('conversationView.close();inlinePending.splice(0).forEach(resolve=>resolve(inlineData))')
    wait("document.querySelectorAll('.conversation-inline-images').length===0")
    assert js('inlineUrls.every(url=>inlineRevoked.includes(url))')


def test_background_retries_aborted_thumbnail_and_late_close_cannot_paint(cockpit):
    js, wait, _ = prepare(cockpit, [shown()], delayed=True)
    wait('inlineCalls.length===1')
    js("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
    assert js('inlineCalls[0].signal.aborted')
    js("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));inlinePending.shift()(inlineData)")
    wait('inlineCalls.length===2')
    assert js("document.querySelectorAll('.conversation-inline-thumbnail[src]').length") == 0
    js('conversationView.close();inlinePending.shift()(inlineData)')
    wait("document.querySelectorAll('.conversation-inline-images').length===0")
    assert js('inlineUrls.length') == 0


def test_recorded_user_image_shares_inline_and_expanded_preview(cockpit):
    event=message('input','この画像を確認してください。')
    event.update(role='user',input_images=True,references=[dict(id='c'*32,label='入力画像.png',kind='image',input_image=True)])
    js,wait,_=prepare(cockpit,[event,message('reply','画像を確認します。')])
    wait("document.querySelector('.conversation-inline-thumbnail')?.naturalWidth>0")
    assert js("document.querySelector('.conversation-inline-images').previousElementSibling.dataset.role")=='user'
    assert js("document.querySelectorAll('.conversation-tool-group').length")==0
    js("document.querySelector('.conversation-inline-image').click()")
    wait("document.querySelector('.conversation-preview-image')?.naturalWidth>0")
    assert js("document.querySelector('.conversation-preview-notice').textContent.startsWith('Recorded input image')")
    assert not js("document.querySelector('.conversation-reveal')!==null")
    assert js("inlineCalls.map(c=>c.thumbnail)")==[True,False]
