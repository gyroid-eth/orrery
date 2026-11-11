"""Recorded references only; no provider files, browser path grants or OS reveal."""
import base64
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conversation_artifacts import extract_artifacts
from conversation_preview import ReferenceStore, PreviewUnavailable


def call(name, arguments=None, input=None):
    return dict(type='response_item', payload=dict(type='custom_tool_call' if input is not None else 'function_call',
        name=name, arguments=json.dumps(arguments), input=input))


def setup(tmp_path, item, **options):
    transcript=tmp_path/'bound.jsonl'
    header=dict(type='session_meta',payload=dict(cwd=str(tmp_path)))
    first=(json.dumps(header)+'\n').encode()
    transcript.write_bytes(first+(json.dumps(item)+'\n').encode())
    row=dict(name='FixtureAgent',program='codex',history_binding='bound',transcript_path=str(transcript),native_session_id='fixture')
    store=ReferenceStore(**options)
    with transcript.open('rb') as stream:
        event={'id':str(len(first))}
        store.decorate(row,stream,event)
    return store,row,event


def preview(store,row,event,index=0):
    return store.read(event['references'][index]['id'],row)


def test_os_tmp_image_alias_gets_a_reference(tmp_path):
    """OS の /tmp 別名だけを許可し、固定した記録から画像を読める。"""
    with tempfile.TemporaryDirectory(dir='/tmp') as folder:
        image=Path(folder)/'shown.png'
        Image.new('RGB',(12,9)).save(image)
        item=dict(type='event_msg',payload=dict(type='item_completed',item=dict(
            type='McpToolCall',server='orrery-mail',tool='show_files',status='completed',
            arguments={'paths':[str(image)]})))
        store,row,event=setup(tmp_path,item)
        assert event['references'][0]['kind']=='image'
        assert preview(store,row,event)['kind']=='image'


def test_user_symlink_under_tmp_is_still_denied(tmp_path):
    """OS の別名の先にある利用者の symlink は許可しない。"""
    with tempfile.TemporaryDirectory(dir='/tmp') as folder:
        root=Path(folder);image=root/'image.png';Image.new('RGB',(12,9)).save(image)
        link=root/'user-link.png';link.symlink_to(image.resolve())
        item=dict(type='event_msg',payload=dict(type='item_completed',item=dict(
            type='McpToolCall',server='orrery-mail',tool='show_files',status='completed',
            arguments={'paths':[str(link)]})))
        store,row,event=setup(tmp_path,item)
        assert not event.get('references')
        with pytest.raises(PreviewUnavailable):store.policy(str(link),tmp_path,shown=True)


def test_structured_paths_and_recorded_diff_never_parse_shell_or_free_text():
    patch='*** Begin Patch\n*** Update File: src/main.py\n@@\n-old\n+new\n*** End Patch'
    result=extract_artifacts(call('apply_patch',input=patch))
    assert result['paths']==['src/main.py']
    assert '-old\n+new' in result['diff']
    assert result['diff_status']=='Recorded edit request · outcome unconfirmed'
    assert extract_artifacts(call('exec_command',{'cmd':'cat /tmp/not-a-reference'}))['paths']==[]
    assert extract_artifacts(dict(type='response_item',payload=dict(type='message',role='assistant',content='open /tmp/a')))['paths']==[]


def test_static_exec_wrapper_supports_literals_without_evaluating_javascript():
    patch='*** Begin Patch\n*** Add File: a.txt\n+hello\n*** End Patch'
    js='await tools.apply_patch('+json.dumps(patch)+'); await tools.view_image({path:"images/plot.png"});'
    result=extract_artifacts(call('functions.exec',input=js))
    assert result['paths']==['a.txt','images/plot.png']
    assert extract_artifacts(call('functions.exec',input='"tools.view_image({path:\"fake\"})"; tools.view_image({path:computed});'))['paths']==[]
    assert extract_artifacts(call('functions.exec',input='tools.view_image({path:`${evil()}`})'))['paths']==[]
    assert extract_artifacts(call('functions.exec',input='other.tools.view_image({path:"fake"});'))['paths']==[]
    assert extract_artifacts(call('functions.exec',input='nottools.view_image({path:"fake"});'))['paths']==[]
    assert extract_artifacts(call('functions.exec',input='const regex=/tools.view_image({path:"fake"})/;'))['paths']==[]


def test_reference_is_opaque_bound_and_rechecks_original_record(tmp_path):
    (tmp_path/'a.txt').write_text('current text')
    store,row,event=setup(tmp_path,call('read_file',{'path':'a.txt'}))
    assert 'a.txt' not in event['references'][0]['id']
    assert event['references'][0]['label']=='a.txt'
    assert preview(store,row,event)['text']=='current text'
    with pytest.raises(PreviewUnavailable): store.read('a.txt',row)
    with pytest.raises(PreviewUnavailable): store.read(event['references'][0]['id'],dict(row,native_session_id='other'))
    transcript=Path(row['transcript_path'])
    transcript.write_bytes(transcript.read_bytes().replace(b'a.txt',b'b.txt'))
    with pytest.raises(PreviewUnavailable): preview(store,row,event)


@pytest.mark.parametrize('name',['auth.json','token.txt','api_key.md','secrets/config.txt','credentials.yaml','private/notes.txt'])
def test_secret_like_names_are_previewed(tmp_path,name):
    # The owner decides; names alone never hide a recorded workspace file.
    path=tmp_path/name;path.parent.mkdir(exist_ok=True);path.write_text('fixture body')
    store,row,event=setup(tmp_path,call('read_file',{'path':name}))
    assert event['references'][0]['label']==Path(name).name
    assert preview(store,row,event)['text']=='fixture body'


def test_containment_symlinks_hardlinks_fifo_and_late_swaps(tmp_path):
    root=tmp_path/'workspace';root.mkdir()
    outside=tmp_path/'outside.txt';outside.write_text('OUTSIDE')
    for name in ['../outside.txt',str(outside),'https://example.test/a.png']:
        store,row,event=setup(root,call('read_file',{'path':name}))
        assert not event.get('references')
    (root/'a.txt').write_text('safe')
    store,row,event=setup(root,call('read_file',{'path':'a.txt'}))
    (root/'a.txt').unlink();(root/'a.txt').symlink_to(outside)
    with pytest.raises(PreviewUnavailable): preview(store,row,event)
    (root/'a.txt').unlink();os.link(outside,root/'a.txt')
    with pytest.raises(PreviewUnavailable): preview(store,row,event)
    (root/'a.txt').unlink();os.mkfifo(root/'a.txt')
    with pytest.raises(PreviewUnavailable): preview(store,row,event)


def test_text_limit_mime_verbatim_text_and_recorded_diff_not_disk(tmp_path):
    (tmp_path/'a.txt').write_text('sk-proj-'+'x'*40+'\ncurrent disk')
    patch='*** Begin Patch\n*** Update File: a.txt\n@@\n-old recorded\n+new recorded\n*** End Patch'
    store,row,event=setup(tmp_path,call('apply_patch',input=patch))
    assert 'new recorded' in event['diff'] and 'current disk' not in event['diff']
    result=preview(store,row,event)
    assert result['text']=='sk-proj-'+'x'*40+'\ncurrent disk'
    (tmp_path/'a.txt').write_text('x'*(128*1024+1))
    with pytest.raises(PreviewUnavailable): preview(store,row,event)
    (tmp_path/'a.txt').write_bytes(b'\x89PNG\x00not text')
    with pytest.raises(PreviewUnavailable): preview(store,row,event)


def test_raster_reencoded_and_explicit_image_root_is_not_text_grant(tmp_path):
    workspace=tmp_path/'work';workspace.mkdir()
    images=tmp_path/'images';images.mkdir()
    target=images/'plot.png';Image.new('RGB',(12,9),'teal').save(target)
    store,row,event=setup(workspace,call('view_image',{'path':str(target)}),image_roots=[str(images)])
    result=preview(store,row,event)
    assert result['mime']=='image/png' and result['width']==12 and result['height']==9
    assert Image.open(io.BytesIO(base64.b64decode(result['data']))).size==(12,9)
    target.write_text('<svg onload="evil()"/>')
    with pytest.raises(PreviewUnavailable): preview(store,row,event)
    (images/'file.txt').write_text('not granted')
    store,row,event=setup(workspace,call('read_file',{'path':str(images/'file.txt')}),image_roots=[str(images)])
    assert not event.get('references')


def test_oversized_pixels_and_expiring_bounded_reference_store(tmp_path):
    Image.new('RGB',(100,100)).save(tmp_path/'plot.png')
    store,row,event=setup(tmp_path,call('view_image',{'path':'plot.png'}),max_pixels=99)
    with pytest.raises(PreviewUnavailable): preview(store,row,event)
    now=[1.0]
    store,row,event=setup(tmp_path,call('view_image',{'path':'plot.png'}),clock=lambda:now[0],ttl=5,max_refs=1)
    now[0]=7
    with pytest.raises(PreviewUnavailable): preview(store,row,event)


def test_remote_html_stays_inert_and_secret_named_diff_is_shown_verbatim(tmp_path):
    patch='*** Begin Patch\n*** Add File: .env\n+NOTE=visible\n+api_key=hidden\n*** End Patch'
    result=extract_artifacts(call('apply_patch',input=patch))
    assert result['paths']==['.env'] and '+NOTE=visible' in result['diff'] and '+api_key=hidden' in result['diff']
    store,row,event=setup(tmp_path,call('view_image',{'path':'https://example.test/image.png'}))
    assert not event.get('references')


def test_diff_budget_and_absolute_display_labels_are_bounded():
    patch='*** Begin Patch\n*** Update File: /Users/example/project/a.py\n@@\n-old\n+new\n'+' context\n'*10000+'*** End Patch'
    result=extract_artifacts(call('apply_patch',input=patch))
    assert result['paths']==['/Users/example/project/a.py']
    assert '/Users/' not in result['diff']
    assert len(result['diff'])<=48*1024
    deletion=extract_artifacts(call('apply_patch',input='*** Begin Patch\n*** Delete File: a.txt\n*** End Patch'))
    assert '+++ /dev/null' in deletion['diff'] and 'original content unavailable' in deletion['diff']


def test_directory_symlink_swap_and_changed_file_during_read_fail_closed(tmp_path,monkeypatch):
    folder=tmp_path/'folder';folder.mkdir();(folder/'a.txt').write_text('safe')
    store,row,event=setup(tmp_path,call('read_file',{'path':'folder/a.txt'}))
    outside=tmp_path/'outside';outside.mkdir();(outside/'a.txt').write_text('other')
    folder.rename(tmp_path/'old');folder.symlink_to(outside,target_is_directory=True)
    with pytest.raises(PreviewUnavailable):preview(store,row,event)
    folder.unlink();(tmp_path/'old').rename(folder)
    original=os.read
    def read_then_swap(fd,size):
        data=original(fd,size)
        (folder/'a.txt').unlink();(folder/'a.txt').write_text('swapped')
        return data
    monkeypatch.setattr(os,'read',read_then_swap)
    with pytest.raises(PreviewUnavailable):preview(store,row,event)


def test_reference_cap_and_record_inode_replacement(tmp_path):
    (tmp_path/'a.txt').write_text('a');(tmp_path/'b.txt').write_text('b')
    js='tools.read_file({path:"a.txt"});tools.read_file({path:"b.txt"});'
    store,row,event=setup(tmp_path,call('functions.exec',input=js),max_refs=1)
    assert len(store.refs)==1
    with pytest.raises(PreviewUnavailable):preview(store,row,event,0)
    assert preview(store,row,event,1)['text']=='b'
    transcript=Path(row['transcript_path']);data=transcript.read_bytes()
    transcript.rename(tmp_path/'old.jsonl');transcript.write_bytes(data)
    with pytest.raises(PreviewUnavailable):preview(store,row,event,1)


def test_relative_reference_cannot_move_when_workspace_header_changes(tmp_path):
    one=tmp_path/'one';two=tmp_path/'two';one.mkdir();two.mkdir()
    (one/'a.txt').write_text('first');(two/'a.txt').write_text('other')
    store,row,event=setup(one,call('read_file',{'path':'a.txt'}))
    transcript=Path(row['transcript_path'])
    original=transcript.read_bytes()
    transcript.write_bytes(original.replace(str(one).encode(),str(two).encode()))
    with pytest.raises(PreviewUnavailable):preview(store,row,event)


def test_api_accepts_only_server_ids_and_rechecks_live_binding(tmp_path,monkeypatch):
    import asyncio
    from aiohttp import ClientSession,web
    import orrery_backend as backend
    from test_conversation_history import start
    async def main():
        (tmp_path/'a.txt').write_text('safe fixture')
        store,row,event=setup(tmp_path,call('read_file',{'path':'a.txt'}))
        async def agents(request):return web.json_response({'agents':[row]})
        upstream=web.Application();upstream.router.add_get('/api/agents',agents)
        runner,origin=await start(upstream);monkeypatch.setattr(backend,'DASHBOARD_URL',origin)
        app=web.Application(middlewares=[backend.own_page_only,backend.json_writes_only])
        app[backend.HTTP_SESSION_KEY]=ClientSession();app[backend.TMUX_BIN_KEY]=object()
        app[backend.CONVERSATION_REFERENCES_KEY]=store
        app.router.add_get('/telemetry/conversation',backend.serve_conversation)
        app.router.add_get('/telemetry/conversation/preview',backend.serve_conversation_preview)
        app.router.add_post('/telemetry/conversation/reveal',backend.reveal_conversation_reference)
        server,url=await start(app)
        revealed=[];monkeypatch.setattr(backend,'reveal_in_finder',lambda path:revealed.append(str(path)) or 'file')
        try:
            async with ClientSession() as client:
                async with client.get(url+'/telemetry/conversation?agent=FixtureAgent') as response:
                    page=await response.json();assert response.status==200
                ref=page['events'][0]['references'][0]['id']
                for query in ['path=a.txt','ref='+ref+'&path=a.txt','ref='+ref+'&ref='+ref]:
                    async with client.get(url+'/telemetry/conversation/preview?'+query) as response:assert response.status==400
                async with client.get(url+'/telemetry/conversation/preview?ref='+ref) as response:
                    data=await response.json();assert response.status==200 and data['text']=='safe fixture'
                    assert response.headers['Cache-Control']=='no-store'
                assert not revealed
                async with client.post(url+'/telemetry/conversation/reveal',json={'ref':ref}) as response:assert response.status==200
                assert revealed==[str(tmp_path/'a.txt')]
                async with client.post(url+'/telemetry/conversation/reveal',json={'ref':ref,'path':'a.txt'}) as response:assert response.status==400
                row['native_session_id']='replaced'
                async with client.get(url+'/telemetry/conversation/preview?ref='+ref) as response:
                    data=await response.json();assert response.status==400 and 'safe fixture' not in str(data)
                row['native_session_id']='fixture'
                original=store.read
                def rebind_during_read(*args,**kwargs):
                    result=original(*args,**kwargs);row['native_session_id']='changed-mid-read';return result
                monkeypatch.setattr(store,'read',rebind_during_read)
                async with client.get(url+'/telemetry/conversation/preview?ref='+ref) as response:
                    data=await response.json();assert response.status==400 and 'safe fixture' not in str(data)
                async with client.get(url+'/telemetry/conversation/preview?ref='+ref,headers={'Origin':'https://example.test'}) as response:assert response.status==403
        finally:
            await server.cleanup();await app[backend.HTTP_SESSION_KEY].close();await runner.cleanup()
    asyncio.run(main())
