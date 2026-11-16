"""Preview image Lightbox, driven with real CDP input (mouse wheel, press, key).

Needs ORRERY_CDP_URL (see test_conversation_review_regressions). It loads the
real cockpit.html and conversation_preview.js; only the history read and the
reference fetch are replaced, so the preview's own open() path is the one that
draws every image, including the ones reached with the arrow keys.
"""
import base64
import io
import json
import os
import time
from pathlib import Path

import pytest
from PIL import Image

from test_conversation_review_regressions import cockpit, stable_roster  # noqa: F401

IDS = ['a' * 32, 'b' * 32, 'c' * 32]
SIZES = {IDS[0]: (1600, 800), IDS[1]: (900, 1200), IDS[2]: (320, 200)}
COLORS = {IDS[0]: '#548eae', IDS[1]: '#ae8e54', IDS[2]: '#8eae54'}


def png(id):
    output = io.BytesIO()
    Image.new('RGB', SIZES[id], COLORS[id]).save(output, 'PNG')
    return dict(ok=True, kind='image', mime='image/png', width=SIZES[id][0], height=SIZES[id][1],
                data=base64.b64encode(output.getvalue()).decode())


def events():
    rows = []
    for index, id in enumerate(IDS):
        rows.append(dict(id='e%d' % index, kind='text', role='assistant', text='Image %d' % index,
                         ts='2026-11-01T04:0%d:00Z' % index,
                         references=[dict(id=id, kind='image', label='fig%d.png' % index)]))
    rows.append(dict(id='doc', kind='text', role='assistant', text='Notes', ts='2026-11-01T04:09:00Z',
                     references=[dict(id='d' * 32, kind='file', label='notes.txt')]))
    return rows


def prepare(cockpit):
    js, wait, client, _, enable = cockpit
    stable_roster(js)
    enable(count=1)
    js('conversationView.close()')
    js('window.lbEvents=' + json.dumps(events()) + ';window.lbData=' + json.dumps({id: png(id) for id in IDS})
       + ';lbData["' + 'd' * 32 + '"]={ok:true,kind:"text",text:"plain notes"};' + """
      window.lbRevoked=[];const revoke=URL.revokeObjectURL.bind(URL);
      URL.revokeObjectURL=url=>{lbRevoked.push(url);revoke(url);};
      window.lbKeys=0;document.addEventListener('keydown',()=>lbKeys++);
      OrreryConversationSource.Source.prototype.read=async()=>({events:lbEvents,before:'start',after:'end'});
      OrreryConversationSource.Source.prototype.reference=(id)=>Promise.resolve(lbData[id]);
      conversationView.open();""")
    wait("document.querySelectorAll('.conversation-event').length===4")
    wait("document.querySelector('.conversation-panel').dataset.conversationLayout==='settled'")
    return js, wait, client


def open_preview(js, wait, index=0):
    js("document.querySelectorAll('.conversation-file')[%d].click()" % index)
    wait("document.querySelector('.conversation-preview-image')?.naturalWidth>0")


def center(js, selector):
    return js("(()=>{const r=document.querySelector(%s).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()" % json.dumps(selector))


def mouse(client, type, x, y, **extra):
    client.call('Input.dispatchMouseEvent', type=type, x=x, y=y, **extra)


def click(client, x, y):
    mouse(client, 'mouseMoved', x, y)
    mouse(client, 'mousePressed', x, y, button='left', clickCount=1)
    mouse(client, 'mouseReleased', x, y, button='left', clickCount=1)


KEYS = {'Escape': (27, 'Escape'), 'ArrowLeft': (37, 'ArrowLeft'), 'ArrowRight': (39, 'ArrowRight'),
        '+': (187, 'Equal'), '-': (189, 'Minus'), '0': (48, 'Digit0'), '1': (49, 'Digit1')}


def wheel(js, wait, client, x, y, delta, times=1, **extra):
    """Real wheel input. Chrome hands wheel events to the page on the next frame, so wait for them."""
    start = js("window.lbWheels||0")
    for _ in range(times):
        mouse(client, 'mouseWheel', x, y, deltaX=0, deltaY=delta, **extra)
    wait("(window.lbWheels||0)===%d" % (start + times))


def key(client, name):
    code, physical = KEYS[name]
    text = name if len(name) == 1 else None
    client.call('Input.dispatchKeyEvent', type='keyDown', key=name, code=physical, windowsVirtualKeyCode=code, **({'text': text} if text else {}))
    client.call('Input.dispatchKeyEvent', type='keyUp', key=name, code=physical, windowsVirtualKeyCode=code)
    time.sleep(.1)  # the page sees it on its next frame


def view(js):
    """Scale and top-left of the lightbox image, plus its stage box."""
    return js("""(()=>{const img=document.querySelector('.conversation-lightbox-image'),m=new DOMMatrix(getComputedStyle(img).transform),
      s=document.querySelector('.conversation-lightbox-stage').getBoundingClientRect();
      return {s:m.a,x:m.e,y:m.f,w:img.offsetWidth,h:img.offsetHeight,left:s.left,top:s.top,width:s.width,height:s.height,
        zoom:document.querySelector('.conversation-lightbox-zoom')?.textContent}})()""")


def fit_scale(v):
    return min(1, v['width'] / v['w'], v['height'] / v['h'])


def open_lightbox(js, wait, client, id_index=0):
    open_preview(js, wait, id_index)
    x, y = center(js, '.conversation-preview-fullscreen')
    click(client, x, y)
    wait("document.querySelector('.conversation-lightbox')!==null&&document.querySelector('.conversation-lightbox-image').getAttribute('src')")
    js("window.lbWheels=0;document.querySelector('.conversation-lightbox-stage').addEventListener('wheel',()=>setTimeout(()=>lbWheels++),true)")
    return view(js)


def test_full_screen_button_opens_a_modal_layer_fitted_to_the_window(cockpit):
    js, wait, client = prepare(cockpit)
    v = open_lightbox(js, wait, client)
    assert js("document.querySelector('.conversation-lightbox').getAttribute('aria-modal')") == 'true'
    assert js("document.querySelector('.conversation-lightbox-name').textContent") == 'fig0.png'
    assert js("document.querySelector('.conversation-lightbox-count').textContent") == '1 / 3'
    assert v['s'] == pytest.approx(fit_scale(v), abs=1e-3)
    assert js("document.activeElement===document.querySelector('.conversation-lightbox')")
    assert js("[...document.body.children].filter(n=>!n.classList.contains('conversation-lightbox')&&n.tagName!=='SCRIPT').every(n=>n.inert)")
    assert js("getComputedStyle(document.querySelector('.conversation-lightbox')).position") == 'fixed'


def test_bar_buttons_are_icons_only_with_names_in_aria_label_and_title(cockpit):
    js, wait, client = prepare(cockpit)
    open_lightbox(js, wait, client)
    bar = js("""[...document.querySelectorAll('.conversation-lightbox-bar button')].map(b=>({text:b.textContent.trim(),label:b.getAttribute('aria-label'),
      title:b.title,svg:b.querySelectorAll('svg').length,w:Math.round(b.getBoundingClientRect().width),h:Math.round(b.getBoundingClientRect().height)}))""")
    assert [b['label'] for b in bar] == ['Fit to window (0)', 'Actual size (1)', 'Close (Esc)']
    assert all(b['text'] == '' and b['svg'] == 1 and b['title'] == b['label'] and (b['w'], b['h']) == (30, 30) for b in bar)
    assert js("document.querySelector('.conversation-lightbox-help')") is None
    assert 'Wheel zoom' in js("document.querySelector('.conversation-lightbox-stage').title")
    # the information stays as text: the name, the position and the magnification
    assert js("document.querySelector('.conversation-lightbox-name').textContent") == 'fig0.png'
    assert js("document.querySelector('.conversation-lightbox-count').textContent") == '1 / 3'
    assert js("document.querySelector('.conversation-lightbox-zoom').textContent").endswith('%')
    js("document.querySelector('[aria-label=\"Actual size (1)\"]').click()")
    assert js("document.querySelector('[aria-label=\"Actual size (1)\"]').getAttribute('aria-pressed')") == 'true'


def test_wheel_zooms_around_the_cursor_and_is_bounded(cockpit):
    js, wait, client = prepare(cockpit)
    v = open_lightbox(js, wait, client)
    px, py = v['left'] + v['width'] * 0.7, v['top'] + v['height'] * 0.4
    wheel(js, wait, client, px, py, -120)
    assert view(js)['s'] > v['s'] * 1.1
    # Once the picture covers the window, zooming keeps the point under the cursor fixed
    # (while it is still smaller than the window it stays centred, so that is not tested here).
    wheel(js, wait, client, px, py, -120, times=3)
    start = view(js)
    before = ((px - start['left'] - start['x']) / start['s'], (py - start['top'] - start['y']) / start['s'])
    wheel(js, wait, client, px, py, -120)
    after = view(js)
    assert after['s'] > start['s'] * 1.1
    point = ((px - after['left'] - after['x']) / after['s'], (py - after['top'] - after['y']) / after['s'])
    assert point[0] == pytest.approx(before[0], abs=1) and point[1] == pytest.approx(before[1], abs=1)
    wheel(js, wait, client, px, py, -240, times=60)
    assert view(js)['s'] == pytest.approx(8, abs=1e-3)
    wheel(js, wait, client, px, py, 240, times=120)
    low = view(js)
    assert low['s'] == pytest.approx(fit_scale(low) * 0.8, abs=1e-3)
    # pinch on a trackpad arrives as a wheel with ctrlKey
    wheel(js, wait, client, px, py, -30, modifiers=2)
    assert view(js)['s'] > low['s']


def test_drag_pans_and_a_still_click_toggles_actual_size(cockpit):
    js, wait, client = prepare(cockpit)
    v = open_lightbox(js, wait, client, 1)  # 900 x 1200: taller than the window
    cx, cy = v['left'] + v['width'] / 2, v['top'] + v['height'] / 2
    click(client, cx, cy)  # still click -> 100% about the clicked point
    time.sleep(.1)
    full = view(js)
    assert full['s'] == pytest.approx(1, abs=1e-3)
    assert js("document.querySelector('.conversation-lightbox-zoom').textContent") == '100%'
    mouse(client, 'mouseMoved', cx, cy)
    mouse(client, 'mousePressed', cx, cy, button='left', clickCount=1)
    for step in range(1, 7):
        mouse(client, 'mouseMoved', cx - 20 * step, cy + 20 * step, button='left')
    mouse(client, 'mouseReleased', cx - 120, cy + 120, button='left', clickCount=1)
    time.sleep(.1)
    moved = view(js)
    assert moved['s'] == pytest.approx(1, abs=1e-3)  # a drag is not a click
    assert moved['y'] - full['y'] == pytest.approx(120, abs=1)  # 900 px wide: the window is wider, so only y moves
    click(client, cx, cy)  # click again -> Fit
    time.sleep(.1)
    assert view(js)['s'] == pytest.approx(fit_scale(full), abs=1e-3)


def test_arrow_keys_walk_the_conversation_images_and_keys_stay_in_the_layer(cockpit):
    js, wait, client = prepare(cockpit)
    open_lightbox(js, wait, client)
    first_url = js("document.querySelector('.conversation-lightbox-image').src")
    js('lbKeys=0')
    key(client, 'ArrowRight')
    wait("document.querySelector('.conversation-lightbox-name').textContent==='fig1.png'&&document.querySelector('.conversation-lightbox-image').getAttribute('src')")
    assert js("document.querySelector('.conversation-lightbox-count').textContent") == '2 / 3'
    v = view(js)
    assert (v['w'], v['h']) == (900, 1200)
    assert v['s'] == pytest.approx(fit_scale(v), abs=1e-3)
    assert first_url in js('lbRevoked')  # the previous image's object URL was released
    assert js("document.querySelector('.conversation-preview-title').textContent") == 'fig1.png'  # preview follows
    key(client, 'ArrowRight')
    wait("document.querySelector('.conversation-lightbox-name').textContent==='fig2.png'&&document.querySelector('.conversation-lightbox-image').getAttribute('src')")
    assert js("document.querySelector('.conversation-lightbox-nav.next').disabled")
    key(client, 'ArrowLeft')
    wait("document.querySelector('.conversation-lightbox-name').textContent==='fig1.png'")
    key(client, 'ArrowRight')
    key(client, 'ArrowRight')  # past the end: stays
    wait("document.querySelector('.conversation-lightbox-name').textContent==='fig2.png'")
    assert js('lbKeys') == 0  # nothing reached the page behind the layer


def test_plus_minus_zero_one_and_escape_restore_focus_to_the_button(cockpit):
    js, wait, client = prepare(cockpit)
    v = open_lightbox(js, wait, client)
    key(client, '+')
    assert view(js)['s'] > v['s'] * 1.2
    key(client, '-')
    key(client, '-')
    assert view(js)['s'] < v['s']
    key(client, '1')
    assert view(js)['s'] == pytest.approx(1, abs=1e-3)
    key(client, '0')
    assert view(js)['s'] == pytest.approx(fit_scale(v), abs=1e-3)
    key(client, 'Escape')
    wait("document.querySelector('.conversation-lightbox')===null")
    assert js("document.activeElement===document.querySelector('.conversation-preview-fullscreen')")
    assert js("[...document.body.children].every(n=>!n.inert)")


def test_clicking_the_preview_image_opens_it_and_escape_returns_to_the_image(cockpit):
    js, wait, client = prepare(cockpit)
    open_preview(js, wait, 1)
    x, y = center(js, '.conversation-preview-image')
    click(client, x, y)
    wait("document.querySelector('.conversation-lightbox')!==null")
    assert js("document.querySelector('.conversation-lightbox-name').textContent") == 'fig1.png'
    key(client, 'Escape')
    wait("document.querySelector('.conversation-lightbox')===null")
    assert js("document.activeElement===document.querySelector('.conversation-preview-image')")


def test_text_preview_has_no_full_screen_door(cockpit):
    js, wait, client = prepare(cockpit)
    js("document.querySelectorAll('.conversation-file')[3].click()")
    wait("document.querySelector('.conversation-preview-text')!==null")
    assert js("document.querySelector('.conversation-preview-fullscreen')") is None


def test_closing_the_preview_while_the_layer_is_open_removes_the_layer(cockpit):
    js, wait, client = prepare(cockpit)
    open_lightbox(js, wait, client)
    js("conversationView.close()")
    wait("document.querySelector('.conversation-lightbox')===null")
    assert js("[...document.body.children].every(n=>!n.inert)")


@pytest.mark.skipif(not os.environ.get('ORRERY_LIGHTBOX_SHOTS'), reason='set ORRERY_LIGHTBOX_SHOTS=<dir> to write screenshots')
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_screenshots(cockpit, theme):
    """Fit / wheel-zoomed / 100% / narrow window, for looking at (not asserted)."""
    folder = Path(os.environ['ORRERY_LIGHTBOX_SHOTS'])
    folder.mkdir(parents=True, exist_ok=True)
    sample = os.environ.get('ORRERY_LIGHTBOX_SAMPLE')
    js, wait, client = prepare(cockpit)
    if sample:
        data = base64.b64encode(Path(sample).read_bytes()).decode()
        width, height = Image.open(sample).size
        js('lbData[%s]=Object.assign({},lbData[%s],{width:%d,height:%d,data:%s})' % (json.dumps(IDS[0]), json.dumps(IDS[0]), width, height, json.dumps(data)))
    if theme == 'light':
        js("OrreryColorTheme.setPreference('light')")
    def shot(name):
        time.sleep(.3)
        (folder / ('%s-%s.png' % (theme, name))).write_bytes(base64.b64decode(client.call('Page.captureScreenshot', format='png')['data']))
    v = open_lightbox(js, wait, client)
    shot('1-fit')
    px, py = v['left'] + v['width'] * 0.35, v['top'] + v['height'] * 0.3
    wheel(js, wait, client, px, py, -240, times=5)
    shot('2-wheel')
    key(client, '1')
    shot('3-actual')
    key(client, '0')
    client.call('Emulation.setDeviceMetricsOverride', width=700, height=800, deviceScaleFactor=1, mobile=False)
    time.sleep(.3)
    shot('4-narrow')
