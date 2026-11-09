"""Explicit body-path links: literal probes, isolated image reads and activation."""
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
        result=preview.clicked_image(str(image))
        assert result['mime']=='image/png' and (result['width'],result['height'])==(24,16)
        assert Image.open(io.BytesIO(base64.b64decode(result['data']))).size==(24,16)
        link=folder/'alias.png';link.symlink_to(image)
        assert preview.clicked_image(str(link))['width']==24
        nested=folder/'nested';nested.mkdir()
        assert preview.clicked_image(str(nested/'..'/'plot.png'))['height']==16
    monkeypatch.setenv('HOME',str(tmp_path))
    Image.new('RGB',(2,3)).save(tmp_path/'home.png')
    assert preview.clicked_image('~/home.png')['height']==3
    bad=tmp_path/'fake.png';bad.write_text('<svg onload="evil()"/>')
    for value, code in [(str(bad),'preview_type_denied'), (str(tmp_path/'missing.png'),'preview_unavailable'),
                        (str(tmp_path/'home.txt'),'preview_type_denied'), ('relative.png','preview_path_denied'),
                        (str(bad)+'\n','preview_path_denied')]:
        with pytest.raises(preview.PreviewUnavailable,match=code):preview.clicked_image(value)
    large=tmp_path/'large.png'
    with large.open('wb') as stream:stream.truncate(preview.MAX_IMAGE+1)
    with pytest.raises(preview.PreviewUnavailable,match='preview_too_large'):preview.clicked_image(str(large))
    Image.new('RGB',(8193,1)).save(large)
    with pytest.raises(preview.PreviewUnavailable,match='preview_too_large'):preview.clicked_image(str(large))
    Image.new('1',(4001,4000)).save(large)
    with pytest.raises(preview.PreviewUnavailable,match='preview_too_large'):preview.clicked_image(str(large))


def test_clicked_image_unreadable_special_files_and_alias_swap(tmp_path, monkeypatch):
    image=tmp_path/'plot.png';Image.new('RGB',(2,2)).save(image)
    fifo=tmp_path/'pipe.png';os.mkfifo(fifo)
    with pytest.raises(preview.PreviewUnavailable,match='preview_type_denied'):preview.clicked_image(str(fifo))
    original=preview.os.open
    def deny(path,*args,**kwargs):
        if path=='plot.png':raise PermissionError('fixture denied')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(preview.os,'open',deny)
    with pytest.raises(preview.PreviewUnavailable,match='preview_unavailable'):preview.clicked_image(str(image))
    monkeypatch.setattr(preview.os,'open',original)
    other=tmp_path/'other.png';Image.new('RGB',(3,3)).save(other)
    link=tmp_path/'alias.png';link.symlink_to(image)
    read=preview.ReferenceStore.read_file
    def swap(self,path):
        result=read(self,path);link.unlink();link.symlink_to(other);return result
    monkeypatch.setattr(preview.ReferenceStore,'read_file',swap)
    with pytest.raises(preview.PreviewUnavailable,match='preview_changed'):preview.clicked_image(str(link))


def test_path_api_same_origin_json_only_read_after_click_and_reveal_stub(tmp_path, monkeypatch):
    image=tmp_path/'plot.png';Image.new('RGB',(4,3)).save(image)
    note=tmp_path/'note.txt';note.write_text('fixture')
    revealed=[];reads=[]
    monkeypatch.setattr(backend,'reveal_in_finder',lambda path:revealed.append(str(path)) or 'file')
    original=backend.clicked_image
    def read(value):reads.append(value);return original(value)
    monkeypatch.setattr(backend,'clicked_image',read)
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
                async with client.post(url+'/telemetry/reveal-path',json={'path':str(note),'literal':True}) as response:assert response.status==200
                assert revealed==[str(note)]
                for body in [{'path':str(note)},{'path':str(image),'ref':'x'},{'path':str(tmp_path/'missing.png')}]:
                    async with client.post(url+'/telemetry/conversation/path-image',json=body) as response:assert response.status==400
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
       'OrreryConversationSource.Source.prototype.pathImage=async path=>{pathReads.push(path);return pathPayload};'+
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
    wait('pathReveals.length===1')
    assert js('pathReveals')==['/fixture/home/note.txt']
    js('document.querySelector("[data-event-id=path-user] a").dispatchEvent(new MouseEvent("auxclick",{bubbles:true,cancelable:true,button:1}))')
    wait('pathReads.length===2')
    assert js('pathJumps')==[]
    js('document.querySelector(".conversation-preview-close").click();OrreryConversationSource.Source.prototype.pathImage=async()=>{throw new Error("This file exceeds the preview size or pixel limit.")};document.querySelector("[data-event-id=path-user] a").click()')
    wait('document.querySelector(".conversation-preview-content").textContent.includes("pixel limit")')
    assert js('pathReveals.length')==1


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
    """Private real image/probe HTTP routes, no live services or OS opener."""
    import queue
    import threading
    ready=queue.Queue()
    reads=[]
    async def main():
        stop=asyncio.Event()
        app=web.Application(middlewares=[backend.own_page_only,backend.json_writes_only])
        async def image(request):
            reads.append(True)
            return await backend.preview_clicked_path(request)
        async def empty(request):return web.json_response({'agents':[],'prefs':{}})
        app.router.add_post('/telemetry/conversation/path-probe',backend.probe_conversation_paths)
        app.router.add_post('/telemetry/conversation/path-image',image)
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
    result=preview.clicked_image(str(target))
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
