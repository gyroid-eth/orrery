"""Explicit body-path links: literal probes, guarded reads and activation."""
import asyncio
import base64
import io
import json
import os
import tempfile
import time
from pathlib import Path

import pytest
from aiohttp import ClientSession, web
from PIL import Image

from test_preview_markdown_document import run, html
from test_conversation_review_regressions import cockpit, stable_roster
from test_conversation_history import start
from test_conversation_inline_images import message, prepare, shown
import conversation_preview as preview
import orrery_backend as backend


def candidates(text, document=False):
    result = run('const h=new Element("div");md.'+('renderDocument' if document else 'renderText')+'('+json.dumps(text)+',h);const values=[];function walk(n){if(n.dataset?.pathCandidate)values.push(n.dataset.pathCandidate);for(const c of n.children||[])walk(c);}walk(h);console.log(JSON.stringify({values,text:h.textContent}));')
    return json.loads(result)


@pytest.mark.parametrize('document', [False, True])
@pytest.mark.parametrize('suffix', list('。、，．！？「」『』（）【】〈〉《》') + ['.', ',', ';', ':', '!', '?', ')', ']'])
def test_path_boundaries_and_japanese_prose(suffix, document):
    value = '/fixture/plot.png'
    result = candidates('画像は'+value+suffix, document)
    assert result['values'] == [value]
    assert result['text'] == '画像は'+value+suffix


def test_candidates_keep_spaces_balanced_brackets_and_tilde_without_url_parts():
    text = '(/fixture/a(b).png). \n`~/A B/画像.png` \n/fixture/no-such.png \nhttps://example.com/path ftp://example.com/a file:///fixture/a abc/fixture/a //example.com/x'
    result = candidates(text)
    assert result['values'] == ['/fixture/a(b).png', '~/A B/画像.png', '/fixture/no-such.png']
    assert result['text'] == text
    assert '<a ' not in html('[path](/fixture/plot.png)')
    assert html('[path](/fixture/plot.png)').count('data-pathCandidate=') == 1
    assert candidates('[https://example.com/a](https://example.com/b)')['values'] == []


@pytest.mark.parametrize('document', [False, True])
@pytest.mark.parametrize('path', ['/fixture/A B/report(1).md', '~/資料/画像.png'])
@pytest.mark.parametrize('template', ['<{path}>', '[file](<{path}>)', '[file](<{path}> "title")'])
def test_angle_wrapped_paths_keep_only_destination_as_candidate(document, path, template):
    text = template.format(path=path)
    result = candidates(text, document)
    assert result['values'] == [path]
    assert result['text'] == ('file' if document and text.startswith('[') else text)


def test_angle_markdown_targets_keep_urls_and_unsafe_targets_inert():
    out = html('[web](<https://example.com/a>) [mail](<mailto:a@example.com>) '
               '[unsafe](<javascript:alert(1)>) [![image](<https://example.com/i.png>)](<https://example.com/b>)')
    assert out.count('<a ') == 3
    assert 'href="https://example.com/a"' in out and 'href="mailto:a@example.com"' in out
    assert 'href="https://example.com/b"' in out
    assert 'href="javascript:' not in out and '<img' not in out


def test_probe_literal_longest_prefix_spaces_unicode_home_and_missing(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    image = tmp_path/'A B'/'画像.png'; image.parent.mkdir(); image.touch()
    for text, shown in [(str(image)+'です', str(image)), (str(image)+' after words', str(image)), ('~/A B/画像.png', '~/A B/画像.png')]:
        result = backend.probe_reader_path(text)
        assert result == {'shown':shown, 'path':str(image)}
    assert backend.probe_reader_path(str(tmp_path/'missing.png')) is None
    for value in ['relative.png', 'https://example.com/a', str(image)+'\x00', str(image)+'\n']:
        assert backend.probe_reader_path(value) is None


def test_clicked_images_outside_workspace_aliases_metadata_and_limits(tmp_path, monkeypatch):
    # The OS temporary directory exercises the broad-root restriction that
    # recorded preview grants must continue rejecting.
    with tempfile.TemporaryDirectory() as folder:
        folder=Path(folder).resolve(); image=folder/'plot.png'
        Image.new('RGB',(24,16),'teal').save(image)
        if folder.parent == Path('/private/tmp'):assert preview.root_path(str(folder.parent)) is None
        result=preview.clicked_path(str(image))
        assert result['mime']=='image/png' and (result['width'],result['height'])==(24,16)
        assert Image.open(io.BytesIO(base64.b64decode(result['data']))).size==(24,16)
        link=folder/'alias.png';link.symlink_to(image)
        assert preview.clicked_path(str(link))['width']==24
        nested=folder/'nested';nested.mkdir()
        assert preview.clicked_path(str(nested/'..'/'plot.png'))['height']==16
    monkeypatch.setenv('HOME',str(tmp_path))
    Image.new('RGB',(2,3)).save(tmp_path/'home.png')
    assert preview.clicked_path('~/home.png')['height']==3
    bad=tmp_path/'fake.png';bad.write_text('<svg onload="evil()"/>')
    for value, code in [(str(bad),'preview_type_denied'), (str(tmp_path/'missing.png'),'preview_unavailable'),
                        ('relative.png','preview_path_denied'),
                        (str(bad)+'\n','preview_path_denied')]:
        with pytest.raises(preview.PreviewUnavailable,match=code):preview.clicked_path(value)
    large=tmp_path/'large.png'
    with large.open('wb') as stream:stream.truncate(preview.MAX_IMAGE+1)
    with pytest.raises(preview.PreviewUnavailable,match='preview_too_large'):preview.clicked_path(str(large))
    Image.new('RGB',(8193,1)).save(large)
    with pytest.raises(preview.PreviewUnavailable,match='preview_too_large'):preview.clicked_path(str(large))
    Image.new('1',(4001,4000)).save(large)
    with pytest.raises(preview.PreviewUnavailable,match='preview_too_large'):preview.clicked_path(str(large))


@pytest.mark.parametrize('extension', ['png', 'txt'])
def test_clicked_path_unreadable_special_files_and_alias_swap(tmp_path, monkeypatch, extension):
    target=tmp_path/f'original.{extension}'
    other=tmp_path/f'other.{extension}'
    if extension=='png':
        Image.new('RGB',(2,2)).save(target)
        Image.new('RGB',(3,3)).save(other)
    else:
        target.write_text('original',encoding='utf-8')
        other.write_text('other',encoding='utf-8')
    fifo=tmp_path/f'pipe.{extension}';os.mkfifo(fifo)
    with pytest.raises(preview.PreviewUnavailable,match='preview_type_denied'):preview.clicked_path(str(fifo))
    original=preview.os.open
    def deny(path,*args,**kwargs):
        if path==target.name:raise PermissionError('fixture denied')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(preview.os,'open',deny)
    with pytest.raises(preview.PreviewUnavailable,match='preview_unavailable'):preview.clicked_path(str(target))
    monkeypatch.setattr(preview.os,'open',original)
    link=tmp_path/f'alias.{extension}';link.symlink_to(target)
    assert preview.clicked_path(str(link))==preview.clicked_path(str(target))
    read=preview.ReferenceStore.read_file
    def swap(self,path):
        result=read(self,path);link.unlink();link.symlink_to(other);return result
    monkeypatch.setattr(preview.ReferenceStore,'read_file',swap)
    with pytest.raises(preview.PreviewUnavailable,match='preview_changed'):preview.clicked_path(str(link))


@pytest.mark.parametrize('name', ['draft.md', 'notes.txt', 'build.log', 'LICENSE'])
def test_clicked_path_reads_utf8_text_without_a_reference(tmp_path, name):
    path=tmp_path/name
    text='# Draft\n\n日本語の例。\n'
    path.write_text(text,encoding='utf-8')
    assert preview.clicked_path(str(path))==dict(kind='text',mime='text/plain',text=text,label=name)


@pytest.mark.parametrize('character', ['a', '漢', '🎵'])
def test_clicked_path_text_limit_counts_characters(tmp_path, character):
    path=tmp_path/'notes.txt'
    text=character*preview.MAX_TEXT
    path.write_text(text,encoding='utf-8')
    assert preview.clicked_path(str(path))['text']==text
    path.write_text(text+character,encoding='utf-8')
    with pytest.raises(preview.PreviewUnavailable,match='preview_text_too_large'):
        preview.clicked_path(str(path))


@pytest.mark.parametrize('data', [b'\xffinvalid UTF-8', b'valid UTF-8 with a binary\x00 byte'])
def test_clicked_path_rejects_nontext_files(tmp_path, data):
    path=tmp_path/'fixture.bin'
    path.write_bytes(data)
    with pytest.raises(preview.PreviewUnavailable,match='preview_not_text'):
        preview.clicked_path(str(path))


def test_clicked_text_changed_during_read_is_refused(tmp_path, monkeypatch):
    path=tmp_path/'note.txt';path.write_text('before',encoding='utf-8')
    original=preview.os.read
    def replace_after_read(fd,size):
        data=original(fd,size)
        path.write_text('different contents',encoding='utf-8')
        return data
    monkeypatch.setattr(preview.os,'read',replace_after_read)
    with pytest.raises(preview.PreviewUnavailable,match='preview_changed'):
        preview.clicked_path(str(path))


def test_path_api_same_origin_json_only_read_after_click_and_reveal_stub(tmp_path, monkeypatch):
    image=tmp_path/'plot.png';Image.new('RGB',(4,3)).save(image)
    note=tmp_path/'note.txt';note.write_text('fixture')
    revealed=[];reads=[]
    monkeypatch.setattr(backend,'reveal_in_finder',lambda path:revealed.append(str(path)) or 'file')
    original=backend.clicked_path
    def read(value):reads.append(value);return original(value)
    monkeypatch.setattr(backend,'clicked_path',read)
    async def main():
        app=web.Application(middlewares=[backend.own_page_only,backend.json_writes_only])
        app.router.add_post('/telemetry/conversation/path-probe',backend.probe_conversation_paths)
        app.router.add_post('/telemetry/conversation/path-image',backend.preview_clicked_path)
        app.router.add_post('/telemetry/reveal-path',backend.reveal_path)
        runner,url=await start(app)
        try:
            async with ClientSession() as client:
                async with client.post(url+'/telemetry/conversation/path-probe',json={'texts':[str(image),str(note),str(tmp_path/'missing.png')]}) as response:
                    data=await response.json();assert response.status==200
                    assert data['paths'][0]['path']==str(image) and data['paths'][2] is None
                assert reads==[] and revealed==[]
                async with client.post(url+'/telemetry/conversation/path-image',json={'path':str(image)}) as response:
                    data=await response.json();assert response.status==200 and data['width']==4
                    assert response.headers['Cache-Control']=='no-store' and response.headers['X-Content-Type-Options']=='nosniff'
                async with client.post(url+'/telemetry/conversation/path-image',json={'path':str(note)}) as response:
                    data=await response.json();assert response.status==200 and data['text']=='fixture'
                    assert response.headers['Cache-Control']=='no-store'
                    assert response.headers['Content-Security-Policy']=="default-src 'none'; frame-ancestors 'none'"
                assert reads==[str(image),str(note)]
                async with client.post(url+'/telemetry/reveal-path',json={'path':str(note),'literal':True}) as response:assert response.status==200
                assert revealed==[str(note)]
                for body,error in [({'path':str(image),'ref':'x'},'invalid_query'),
                                   ({'path':str(tmp_path/'missing.txt')},'preview_unavailable')]:
                    async with client.post(url+'/telemetry/conversation/path-image',json=body) as response:
                        assert response.status==400 and (await response.json())['error']==error
                async with client.post(url+'/telemetry/conversation/path-image',json={'path':str(image)},headers={'Origin':'https://example.test'}) as response:assert response.status==403
                async with client.post(url+'/telemetry/conversation/path-image',data=json.dumps({'path':str(image)})) as response:assert response.status==415
                async with client.get(url+'/telemetry/conversation/path-image') as response:assert response.status==405
                for body in [{'texts':['/a']*33},{'texts':['x'*2001]},{'texts':['x'*2000]*17},{'texts':['/a'],'path':'/a'}]:
                    async with client.post(url+'/telemetry/conversation/path-probe',json=body) as response:assert response.status==400
        finally:await runner.cleanup()
    asyncio.run(main())


def prepare_paths(cockpit, tmp_path):
    js, wait, client, requests, enable=cockpit
    stable_roster(js);enable(count=1)
    text='/private/tmp/reader-path-fixture/plot.png'
    home='~/reader-path-fixture/note.txt'
    # Only API stubs are used by browser tests; no Finder or real dashboard.
    events=[dict(id='path-assistant',kind='text',role='assistant',text='Image: '+text+'。\nHome: '+home+'。\nMissing: /fixture/absent.png'),
            dict(id='path-user',kind='text',role='user',text='（'+text+'）。'),
            dict(id='path-table',kind='text',role='assistant',text='| File |\n|---|\n| '+text+' |'),
            dict(id='path-mail',kind='mail',role='assistant',text='Recorded Mail',mail=[dict(direction='received',subject='Image',body=text,coverage='complete')])]
    stream=io.BytesIO();Image.new('RGB',(320,160),'teal').save(stream,format='PNG')
    payload=dict(ok=True,kind='image',mime='image/png',data=base64.b64encode(stream.getvalue()).decode(),width=320,height=160)
    js('conversationView.close();window.pathProbes=[];window.pathReads=[];window.pathReveals=[];window.pathJumps=[];window.pathEvents='+json.dumps(events)+';window.pathPayload='+json.dumps(payload)+';'+
       'OrreryConversationSource.Source.prototype.read=async()=>({events:pathEvents,after:"paths:1"});'+
       'OrreryConversationSource.Source.prototype.probePaths=async texts=>{pathProbes.push(texts);return texts.map(text=>text.includes("absent")?null:({shown:text,path:text.startsWith("~/")?"/fixture/home/note.txt":text}));};'+
       'OrreryConversationSource.Source.prototype.pathPreview=async path=>{pathReads.push(path);return path.endsWith(".txt")?{kind:"text",text:"Fixture note"}:pathPayload};'+
       'OrreryConversationSource.Source.prototype.revealPath=async path=>{pathReveals.push(path);return {ok:true}};'+
       'window.pathReader=OrreryConversation.mount({getContext:()=>({...currentAgents[0],terminalPaneId:"%901"}),bindToggle:false,jumpToEvent:event=>pathJumps.push(event)});pathReader.open()')
    wait('document.querySelectorAll("[data-local-path]").length===5')
    return js,wait,client,text,home


def test_browser_paths_all_surfaces_enter_middle_focus_and_missing(cockpit,tmp_path):
    js,wait,client,text,home=prepare_paths(cockpit,tmp_path)
    assert js('pathReads.length')==0 and js('pathReveals.length')==0
    assert js('document.querySelector("[data-event-id=path-assistant]").textContent.includes("/fixture/absent.png")')
    assert js('document.querySelectorAll("a[data-local-path*=absent]").length')==0
    assert js('pathProbes.length')<=2
    js('document.querySelector("[data-event-id=path-assistant] a").click()')
    wait('document.querySelector(".conversation-preview-image")?.naturalWidth===320')
    assert js('document.querySelector(".conversation-preview-notice").textContent')=='320 × 160'
    assert js('pathReads')==[text] and js('pathJumps')==[]
    assert js('!!document.activeElement.closest(".conversation-panel")')
    js('document.querySelector(".conversation-preview-close").click();document.querySelectorAll("[data-event-id=path-assistant] a")[1].focus()')
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',windowsVirtualKeyCode=13)
    wait('document.querySelector(".conversation-preview-text")?.textContent==="Fixture note"')
    assert js('pathReads')==[text,'/fixture/home/note.txt']
    assert js('pathReveals')==[]
    js('document.querySelector(".conversation-reveal").click();document.querySelector(".conversation-preview-close").click()')
    assert js('pathReveals')==['/fixture/home/note.txt']
    js('document.querySelector("[data-event-id=path-user] a").dispatchEvent(new MouseEvent("auxclick",{bubbles:true,cancelable:true,button:1}))')
    wait('pathReads.length===3')
    assert js('pathJumps')==[]
    js('document.querySelector(".conversation-preview-close").click();OrreryConversationSource.Source.prototype.pathPreview=async()=>{throw new Error("This file exceeds the preview size or pixel limit.")};document.querySelector("[data-event-id=path-user] a").click()')
    wait('document.querySelector(".conversation-preview-notice").textContent.includes("pixel limit")')
    assert js('document.querySelector(".conversation-preview-content").textContent')==text
    assert js('!!document.querySelector(".conversation-reveal")')
    assert js('pathReveals.length')==1


@pytest.mark.parametrize('filename', ['plot.png', 'measurements.txt'])
def test_body_path_reply_cites_the_clicked_message(cockpit, filename):
    path = '/fixture/' + filename
    text = f'[Results](<{path}>)'
    first = message('first-path', text)
    clicked = message('clicked-path', text)
    clicked['ts'] = '2026-11-01T04:15:00Z'
    js, wait, _ = prepare(cockpit, [message('intro', 'Results')])
    js('conversationView.close();inlineEvents='+json.dumps([first, clicked])+''';
      OrreryConversationSource.Source.prototype.probePaths=async texts=>texts.map(path=>({shown:path,path}));
      OrreryConversationSource.Source.prototype.pathPreview=async path=>path.endsWith('.txt')?{kind:'text',text:'Fixture measurements'}:inlineData;
      window.revealedPaths=[];
      OrreryConversationSource.Source.prototype.revealPath=async path=>revealedPaths.push(path);
      conversationView.open();''')
    wait('document.querySelectorAll("a[data-local-path]").length===2')
    js('document.querySelector("[data-event-id=clicked-path] a").click()')
    if filename.endswith('.png'):
        wait('document.querySelector(".conversation-preview-image")?.naturalWidth===640')
    else:
        wait('document.querySelector(".conversation-preview-text")?.textContent==="Fixture measurements"')
        assert js('revealedPaths') == []
        js('document.querySelector(".conversation-reveal").click()')
        assert js('revealedPaths') == [path]
    assert js('document.querySelector(".conversation-preview-reply").getAttribute("aria-label")') == 'Reply with reference'
    js('promptInput.value="Please check these results.";document.querySelector(".conversation-preview-reply").click()')
    assert js('document.querySelector(".conversation-preview").hidden')
    assert js('document.querySelector(".conversation-reply-quote").textContent') == path
    assert 'ReviewFixture · File reference' in js('document.querySelector(".conversation-reply-label").textContent')
    assert js('packets.filter(p=>p.type==="input")') == []
    js('sendPrompt()')
    wait('packets.filter(p=>p.type==="input").length===2')
    assert js('packets.find(p=>p.type==="input").data') == (
        '\x1b[200~Reference: ReviewFixture · assistant · 2026-11-01T04:15:00Z\n'
        f'Recorded message: clicked-path\n> {path}\n\nPlease check these results.\x1b[201~'
    )


def test_path_in_preview_without_origin_has_no_reply_button(cockpit):
    js, wait, _ = prepare(cockpit, [shown()])
    payload = json.dumps(dict(kind='text', text='See /fixture/plot.png'))
    js('OrreryConversationSource.Source.prototype.reference=async()=>('+payload+');'+
       'OrreryConversationSource.Source.prototype.probePaths=async texts=>texts.map(path=>({shown:path,path}));'+
       'OrreryConversationSource.Source.prototype.pathPreview=async()=>inlineData;'+
       'document.querySelector(".conversation-tool-group").click();'+
       'document.querySelector(".conversation-files button[data-ref-id^=z]").click();')
    wait('document.querySelector(".conversation-preview a[data-local-path]")!==null')
    assert js('!!document.querySelector(".conversation-preview-reply")')
    js('document.querySelector(".conversation-preview a[data-local-path]").click()')
    wait('document.querySelector(".conversation-preview-image")?.naturalWidth===640')
    assert not js('!!document.querySelector(".conversation-preview-reply")')


def test_browser_preview_prose_paths_and_screenshots(cockpit,tmp_path):
    js,wait,client,text,home=prepare_paths(cockpit,tmp_path)
    output=Path(os.environ.get('ORRERY_PATH_SCREENSHOTS',tmp_path));output.mkdir(parents=True,exist_ok=True)
    js('document.querySelector(".conversation-expand[aria-controls="+pathReader.panel.id+"]").click()')
    for theme in ['dark','light']:
        js('OrreryColorTheme.setPreference('+json.dumps(theme)+');document.querySelector(".conversation-scroll").scrollTop=0')
        time.sleep(.2)
        (output/(theme+'-links.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
        js('document.querySelector("[data-event-id=path-assistant] a").click()')
        wait('document.querySelector(".conversation-preview-image")?.naturalWidth===320')
        time.sleep(.2)
        (output/(theme+'-preview.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
        js('document.querySelector(".conversation-preview-close").click()')
    js('OrreryConversationSource.Source.prototype.reference=async()=>({kind:"text",text:"Image: '+text+'。\\n[home]('+home+')"});pathReader.panel.querySelector(".conversation-events").replaceChildren();pathEvents=[{id:"recorded",kind:"tool",role:"assistant",text:"read",references:[{id:"A".repeat(32),label:"preview.md",kind:"file"}]}];pathReader.refresh()')
    wait('document.querySelector(".conversation-file")!==null')
    js('document.querySelector(".conversation-file").click()')
    wait('document.querySelectorAll(".conversation-preview-markdown a[data-local-path]").length===2')
    assert js('document.querySelector(".conversation-preview-notice").textContent')=='Current file · may differ from the recorded edit'
    assert js('document.querySelector(".conversation-preview-markdown a[data-local-path]").textContent')==text
    print('Path link screenshots:',output)


@pytest.fixture
def path_backend():
    """Private real preview/probe routes, no live services or OS opener."""
    import queue
    import threading
    ready=queue.Queue()
    reads=[]
    async def main():
        stop=asyncio.Event()
        app=web.Application(middlewares=[backend.own_page_only,backend.json_writes_only])
        async def clicked(request):
            reads.append(True)
            return await backend.preview_clicked_path(request)
        async def empty(request):return web.json_response({'agents':[],'prefs':{}})
        app.router.add_post('/telemetry/conversation/path-probe',backend.probe_conversation_paths)
        app.router.add_post('/telemetry/conversation/path-image',clicked)
        app.router.add_post('/telemetry/path-probe',backend.path_probe)
        for path in backend.PUBLIC_FILES:app.router.add_get(path,backend.serve_public_file)
        app.router.add_route('*','/{tail:.*}',empty)
        runner,url=await start(app)
        ready.put((url,asyncio.get_running_loop(),stop))
        try:await stop.wait()
        finally:await runner.cleanup()
    thread=threading.Thread(target=lambda:asyncio.run(main()),daemon=True);thread.start()
    url,loop,stop=ready.get(timeout=10)
    try:yield url,reads
    finally:loop.call_soon_threadsafe(stop.set);thread.join(timeout=10)


def test_real_body_path_text_roundtrip(cockpit, path_backend, tmp_path):
    js,wait,client,_,enable=cockpit
    origin,reads=path_backend
    draft=tmp_path/'release-draft.md'
    note=tmp_path/'verification.txt'
    large=tmp_path/'oversized.log'
    binary=tmp_path/'archive.bin'
    missing=tmp_path/'removed.txt'
    markdown=(
        '# Release draft\n\n'
        'The desktop build is ready for review.\n\n'
        '## Verification\n\n'
        '| Check | Status |\n| --- | --- |\n| Desktop | **Passed** |\n| Packaging | Ready |\n\n'
        '## Before publishing\n\n'
        '- Confirm the release notes.\n- Attach the signed build.\n'
    )
    draft.write_text(markdown,encoding='utf-8')
    note.write_text('# This is literal text\n日本語の記録',encoding='utf-8')
    large.write_text('a'*(preview.MAX_TEXT+1),encoding='utf-8')
    binary.write_bytes(b'binary with \x00 content')
    missing.touch()
    files=[draft,note,large,binary,missing]
    events=[message(f'file-{i}',f'Preview <{path}>') for i,path in enumerate(files)]

    client.call('Page.navigate',url=origin+'/cockpit.html')
    wait("typeof conversationView!=='undefined'&&typeof createPane==='function'")
    js('clearTimeout(reconnectTimer);scheduleReconnect=()=>{}')
    stable_roster(js);enable(count=1)
    js('conversationView.close();window.textEvents='+json.dumps(events)+';'
       'OrreryConversationSource.Source.prototype.read=async()=>({events:textEvents,after:"text:1"});'
       'conversationView.open()')
    wait('document.querySelectorAll("[data-event-id^=file-] a[data-local-path]").length===5')
    assert reads==[]
    missing.unlink()

    body='document.querySelector(".conversation-preview-content")'
    notice='document.querySelector(".conversation-preview-notice")'
    source='document.querySelector(".conversation-preview-source")'
    def open_file(index):
        js('document.querySelector(".conversation-preview-close")?.click();'
           f'document.querySelector("[data-event-id=file-{index}] a[data-local-path]").click()')

    open_file(0)
    wait(body+'?.querySelector("h1")?.textContent==="Release draft"')
    assert js(body+'.querySelector("td strong").textContent')=='Passed'
    assert js(source+'.getAttribute("aria-pressed")')=='false'
    output=os.environ.get('ORRERY_PATH_SCREENSHOTS')
    if output:
        (Path(output)/'reader-path-markdown.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
    js(source+'.click()')
    assert js(body+'.querySelector("pre").textContent')==markdown
    assert js(source+'.getAttribute("aria-pressed")')=='true'
    if output:
        (Path(output)/'reader-path-source.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
    assert len(reads)==1

    open_file(1)
    wait(body+'?.querySelector("pre")!==null')
    assert js(body+'.querySelector("pre").textContent')=='# This is literal text\n日本語の記録'
    assert js(source) is None
    for index,reason in [(2,'131,072-character preview limit'),(3,'binary or is not UTF-8'),(4,'could not be opened')]:
        open_file(index)
        wait(notice+'.textContent.includes('+json.dumps(reason)+')')
        assert js(body+'.textContent')==str(files[index])
        assert js('!!document.querySelector(".conversation-reveal")')
    assert len(reads)==len(files)


@pytest.mark.parametrize('document', [False, True])
def test_real_angle_paths_reader_and_pane_activation(cockpit, path_backend, tmp_path, document):
    js, wait, client, requests, enable = cockpit
    origin, reads = path_backend
    target = tmp_path/'A B'/'report(1).png'
    target.parent.mkdir(); Image.new('RGB', (48, 24), 'teal').save(target)
    path = str(target)
    text = f'[image](<{path}>)\n<{path}>\n[source](https://example.com/source)'
    client.call('Page.navigate', url=origin+'/cockpit.html')
    wait("typeof conversationView!=='undefined'&&typeof createPane==='function'")
    js('clearTimeout(reconnectTimer);scheduleReconnect=()=>{}')
    stable_roster(js); enable(count=1)
    event = dict(id='angle-path', kind='text', role='assistant', text=text)
    js('conversationView.close();window.angleEvent='+json.dumps(event)+';window.angleOpened=[];'
       'OrreryConversationSource.Source.prototype.read=async()=>({events:[angleEvent],after:"angle:1"});'
       'window.angleReader=OrreryConversation.mount({getContext:()=>({...currentAgents[0],terminalPaneId:"%901"}),bindToggle:false,openExternalUrl:url=>angleOpened.push(url)});angleReader.open()')
    wait('angleReader.panel.querySelector(".conversation-text")!==null')
    js('window.angleHost=angleReader.panel.querySelector(".conversation-text")')
    if document:
        js('angleHost.replaceChildren();OrreryConversationMarkdown.renderDocument(angleEvent.text,angleHost)')
    wait('angleHost.querySelectorAll("a[data-local-path]").length===2')
    assert js('[...angleHost.querySelectorAll("a[data-local-path]")].map(a=>a.dataset.localPath)') == [path, path]
    assert js('angleHost.querySelector("a[data-local-path]").textContent') == 'image'
    assert reads == []
    js('angleHost.querySelector("a[data-local-path]").click()')
    wait('document.querySelector(".conversation-preview-image")?.naturalWidth===48')
    assert len(reads) == 1
    js('angleReader.panel.querySelector(".conversation-preview-close").click();angleHost.querySelector("a[href^=https]").click()')
    assert js('angleOpened') == ['https://example.com/source']
    # The same unrendered source in xterm already supports angle boundaries.
    js('window.anglePane=panes.get("%901");anglePane.term.resize(240,20);anglePane.term.reset();'
       'revealLocalPath=path=>angleOpened.push(path);'
       'anglePane.term.write('+json.dumps(text.replace('\n','\r\n'))+')')
    wait('anglePane.term.buffer.active.getLine(1).translateToString(true).startsWith("<")')
    links = js('(async()=>{const provider=anglePane.term._core._linkProviderService.linkProviders.at(-1),out=[];'
               'for(const y of [1,2]){const links=await new Promise(r=>provider.provideLinks(y,r));'
               'for(const link of links||[]){out.push({text:link.text,range:link.range});link.activate({preventDefault(){}});}}return out;})()')
    assert [link['text'] for link in links] == [path, path]
    assert js('angleOpened') == ['https://example.com/source', path, path]
    for link, prefix in zip(links, ['[image](<', '<']):
        assert link['range']['start']['x'] == len(prefix)+1
        assert link['range']['end']['x'] == len(prefix)+len(path)


def test_real_body_path_image_roundtrip_dark_light(cockpit,path_backend,tmp_path,monkeypatch):
    from PIL import ImageDraw
    js,wait,client,requests,enable=cockpit
    origin,reads=path_backend
    fixture_home=tmp_path/'home';fixture_home.mkdir()
    home_note=fixture_home/'note.txt';home_note.write_text('Generated reader path fixture.\n')
    monkeypatch.setenv('HOME',str(fixture_home))
    client.call('Page.navigate',url=origin+'/cockpit.html')
    wait("typeof conversationView!=='undefined'&&typeof createPane==='function'")
    js('clearTimeout(reconnectTimer);scheduleReconnect=()=>{}')
    stable_roster(js);enable(count=1)
    # A real broad temporary path, unrelated to the agent workspace.
    base=Path('/private/tmp') if Path('/private/tmp').is_dir() else Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix='reader-pathlinks-',dir=base) as folder:
        target=Path(folder)/'local image.png'
        raster=Image.new('RGB',(480,240),'#14333d');draw=ImageDraw.Draw(raster)
        draw.text((24,24),'LOCAL IMAGE PREVIEW',fill='#f0d790')
        for index,height in enumerate([40,70,100,130,95,165]):
            x=35+index*68;draw.rectangle((x,215-height,x+42,215),fill='#51b9b1')
        raster.save(target)
        home='~/note.txt'
        text='Image: '+str(target)+'。\nHome: '+home+'。\nMissing: '+str(Path(folder)/'absent.png')
        event=dict(id='real-path',kind='text',role='assistant',text=text)
        js('conversationView.close();window.realPathEvent='+json.dumps(event)+';OrreryConversationSource.Source.prototype.read=async()=>({events:[realPathEvent],after:"real:1"});window.pathReader=OrreryConversation.mount({getContext:()=>({...currentAgents[0],terminalPaneId:"%901"}),bindToggle:false});pathReader.open()')
        wait('document.querySelectorAll("a[data-local-path]").length===2')
        assert reads==[]
        assert js('document.querySelectorAll("a[data-local-path]")[0].textContent')==str(target)
        assert js('document.querySelectorAll("a[data-local-path]")[1].dataset.localPath')==str(home_note)
        output=Path(os.environ.get('ORRERY_PATH_SCREENSHOTS',tmp_path));output.mkdir(parents=True,exist_ok=True)
        for theme in ['dark','light']:
            js('OrreryColorTheme.setPreference('+json.dumps(theme)+');{const button=document.querySelector(".conversation-expand[aria-controls="+pathReader.panel.id+"]");if(button.getAttribute("aria-pressed")!=="true")button.click();}')
            time.sleep(.2)
            (output/(theme+'-real-links.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
            js('document.querySelector("a[data-local-path]").click()')
            wait('document.querySelector(".conversation-preview-image")?.naturalWidth===480')
            assert js('document.querySelector(".conversation-preview-notice").textContent')=='480 × 240'
            time.sleep(.2)
            (output/(theme+'-real-preview.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
            assert js('!!document.activeElement.closest(".conversation-panel")')
            js('document.querySelector(".conversation-preview-close").click()')
        assert len(reads)==2
        print('Real path HTTP screenshots:',output)


@pytest.mark.parametrize('extension,format', [('png','PNG'),('jpg','JPEG'),('jpeg','JPEG'),('gif','GIF'),('webp','WEBP')])
def test_clicked_supported_raster_formats(extension,format,tmp_path):
    target=tmp_path/('plot.'+extension)
    Image.new('RGB',(7,5),'teal').save(target,format=format)
    result=preview.clicked_path(str(target))
    assert result['kind']=='image' and result['mime']=='image/png' and result['width']==7


@pytest.mark.parametrize('expression', ["'/fixture/'.repeat(30000)", "'/fixture/'+ 'x'.repeat(200000)", "'/fixture/a.png '.repeat(10000)"])
def test_path_scan_long_lines_remain_bounded(expression):
    result=json.loads(run('const text='+expression+';const h=new Element("div");const t=performance.now();md.renderText(text,h);show(text);console.log(JSON.stringify({ms:performance.now()-t}));'))
    assert result['ms']<1500


@pytest.mark.parametrize('document', [False,True])
@pytest.mark.parametrize('suffix', [' (https://example.com/source)', ' [source](https://example.com/source)'])
def test_path_candidate_never_consumes_following_url_or_markdown_link(document,suffix):
    text='/fixture/mixed.png'+suffix
    renderer='renderDocument' if document else 'renderText'
    result=json.loads(run('const h=new Element("div");md.'+renderer+'('+json.dumps(text)+',h);const paths=[],urls=[];function walk(n){if(n.dataset?.pathCandidate)paths.push(n.dataset.pathCandidate);if(n.tag==="a")urls.push(n.href);for(const c of n.children||[])walk(c);}walk(h);console.log(JSON.stringify({paths,urls}));'))
    assert result['paths']==['/fixture/mixed.png']
    assert result['urls']==['https://example.com/source']


@pytest.mark.parametrize('name', ['plain.png','画像.png','日本語のファイル.png'])
@pytest.mark.parametrize('home', [False,True])
def test_probe_path_before_long_japanese_prose_keeps_unicode_filenames(tmp_path,monkeypatch,name,home):
    monkeypatch.setenv('HOME',str(tmp_path))
    target=tmp_path/name;target.touch()
    shown='~/'+name if home else str(target)
    text=shown+'です'+'日本語の説明'*12
    assert backend.probe_reader_path(text)=={'shown':shown,'path':str(target)}


@pytest.mark.parametrize('document', [False,True])
@pytest.mark.parametrize('exists', [False,True])
def test_real_mixed_path_urls_and_long_japanese_suffix(cockpit,path_backend,tmp_path,document,exists):
    js,wait,client,requests,enable=cockpit
    origin,reads=path_backend
    client.call('Page.navigate',url=origin+'/cockpit.html')
    wait("typeof conversationView!=='undefined'&&typeof createPane==='function'")
    js('clearTimeout(reconnectTimer);scheduleReconnect=()=>{}');stable_roster(js);enable(count=1)
    target=tmp_path/'mixed.png'
    if exists:Image.new('RGB',(8,6),'teal').save(target)
    unicode_image=tmp_path/'画像.png';Image.new('RGB',(8,6),'teal').save(unicode_image)
    unicode_note=tmp_path/'日本語資料'
    if exists:unicode_note.write_text('Generated fixture.\n')
    suffix='です'+'日本語の説明'*12
    text=str(target)+' (https://example.com/source)\n'+str(target)+' [source](https://example.com/source)\n'+str(unicode_image)+suffix+'\n'+str(unicode_note)+suffix
    event=dict(id='mixed-links',kind='text',role='assistant',text=text)
    js('conversationView.close();window.mixedEvent='+json.dumps(event)+';window.mixedOpened=[];OrreryConversationSource.Source.prototype.read=async()=>({events:[mixedEvent],after:"mixed:1"});window.mixedReader=OrreryConversation.mount({getContext:()=>({...currentAgents[0],terminalPaneId:"%901"}),bindToggle:false,openExternalUrl:url=>mixedOpened.push(url)});mixedReader.open()')
    wait('mixedReader.panel.querySelector("[data-event-id=mixed-links]")!==null')
    if document:
        js('window.mixedHost=mixedReader.panel.querySelector(".conversation-text");mixedHost.replaceChildren();mixedHost.classList.add("conversation-preview-markdown");OrreryConversationMarkdown.renderDocument(mixedEvent.text,mixedHost)')
    else:js('window.mixedHost=mixedReader.panel.querySelector(".conversation-text")')
    wait('!mixedHost.querySelector("[data-path-candidate]")')
    assert js('mixedHost.querySelectorAll("a[href^=https]").length')==2
    assert js('mixedHost.querySelectorAll("a[data-local-path]").length')==(3 if exists else 1)
    assert not js('Array.from(mixedHost.querySelectorAll("a[data-local-path]")).some(a=>a.dataset.localPath==='+json.dumps(str(tmp_path))+')')
    assert js('Array.from(mixedHost.querySelectorAll("a[data-local-path]")).some(a=>a.dataset.localPath==='+json.dumps(str(unicode_image))+')')
    assert reads==[]
    js('mixedHost.querySelectorAll("a[href^=https]").forEach(a=>a.click())')
    assert js('mixedOpened')==['https://example.com/source']*2


def test_probe_unicode_name_keeps_longest_match_and_stat_budget(tmp_path,monkeypatch):
    target=tmp_path/'日本語の資料';target.touch()
    assert backend.probe_reader_path(str(target)+'です')=={'shown':str(target),'path':str(target)}
    original=Path.exists;checks=[]
    def exists(path):
        checks.append(path)
        return original(path)
    monkeypatch.setattr(Path,'exists',exists)
    assert backend.probe_reader_path(str(tmp_path/'missing.png')+'です'+'日本語の説明'*200) is None
    assert len(checks)<=64


@pytest.mark.parametrize('exists', [False,True])
@pytest.mark.parametrize('home', [False,True])
def test_probe_long_unicode_name_never_falls_back_to_parent_directory(tmp_path,monkeypatch,exists,home):
    monkeypatch.setenv('HOME',str(tmp_path))
    target=tmp_path/'日本語資料'
    if exists:target.write_text('Generated fixture.\n')
    shown='~/日本語資料' if home else str(target)
    assert backend.probe_reader_path(shown+'です'+'日本語の説明'*12) is None


@pytest.mark.parametrize('suffix', ['', ' after generated words'])
def test_probe_explicit_directory_with_trailing_slash_still_works(tmp_path,suffix):
    shown=str(tmp_path)+'/'
    assert backend.probe_reader_path(shown+suffix)=={'shown':shown,'path':str(tmp_path)}
