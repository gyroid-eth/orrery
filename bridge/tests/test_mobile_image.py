"""Phone images stay local; fixtures never touch live agent workspaces."""
import base64
import asyncio
import io
import os
from pathlib import Path
import sys
import time

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def picture(fmt='PNG', exif=None):
    out = io.BytesIO()
    options = {'exif': exif} if exif else {}
    Image.new('RGB', (30, 10), 'red').save(out, fmt, **options)
    return base64.b64encode(out.getvalue()).decode()


def test_save_returns_local_random_path_and_removes_exif(tmp_path):
    from mobile_image import save_image
    exif = Image.Exif()
    exif[274] = 6
    exif[34853] = {1: 'N', 2: (35.0, 1.0, 1.0)}
    path = Path(save_image(tmp_path, picture('JPEG', exif)))
    assert path.parent == tmp_path / '.orrery-input-images'
    assert len(path.stem) == 32 and path.suffix == '.jpg'
    assert (path.parent / '.gitignore').read_text() == '*\n'
    with Image.open(path) as image:
        assert image.size == (10, 30)
        assert not image.getexif() and 'exif' not in image.info


@pytest.mark.parametrize('value', ['not base64', base64.b64encode(b'<svg/>').decode(),
    base64.b64encode(b'x' * (10 * 1024 * 1024 + 1)).decode()])
def test_invalid_or_oversized_image_never_creates_file(tmp_path, value):
    from mobile_image import save_image
    with pytest.raises(ValueError):
        save_image(tmp_path, value)
    assert not list(tmp_path.glob('.orrery-input-images/*.*'))


def test_cleanup_only_expired_random_images_and_cap_at_fifty(tmp_path):
    from mobile_image import save_image
    directory = tmp_path / '.orrery-input-images'
    path = Path(save_image(tmp_path, picture()))
    os.utime(path, (time.time() - 8 * 86400,) * 2)
    unrelated = directory / 'notes.txt'
    unrelated.write_text('keep')
    for n in range(50):
        save_image(tmp_path, picture())
    assert not path.exists() and unrelated.read_text() == 'keep'
    with pytest.raises(ValueError, match='image_folder_full'):
        save_image(tmp_path, picture())


def test_symlink_folder_is_never_used(tmp_path):
    from mobile_image import save_image
    other = tmp_path / 'other'
    other.mkdir()
    (tmp_path / '.orrery-input-images').symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        save_image(tmp_path, picture())
    assert not list(other.iterdir())


@pytest.mark.parametrize('case',['upload','probe','wrong_owner','wrong_revision','changed_pane','disabled','no_workspace','no_pillow'])
def test_real_bridge_route_validates_pane_before_image_and_keeps_text_send(tmp_path,monkeypatch,case):
    import contextlib
    import json
    from types import SimpleNamespace
    from aiohttp import ClientSession, web
    from test_mobile_input import bridge_fixture
    import mobile_input as mobile
    import mobile_image

    async def scenario():
        bridge=bridge_fixture(tmp_path)
        version=[1]
        class Resolver:
            def read(self,b,p,deadline):
                return dict(session='FixtureCurie',pane_id=p,incarnation=b._incarnation,height=24,version=version[0])
            @contextlib.contextmanager
            def admission(self,row,deadline):
                yield self.read(row['bridge'],row['pane_id'],deadline)
        async def get_bridge(name):return bridge
        async def root(row):return None if case=='no_workspace' else tmp_path
        async def capture(*args,**kwargs):return SimpleNamespace(lines=['fixture'])
        bridge.capture_mobile_preview=capture
        sent=[]
        async def send(pane,text,**kwargs):
            assert kwargs['valid']() and kwargs['claim']()
            sent.append(text)
            return 'accepted'
        bridge.send_confirmed_input=send
        coordinator=mobile.InputCoordinator(Resolver(),get_bridge,enabled=True,image_workspace=root)
        app=web.Application()
        mobile.install_routes(app,coordinator)
        runner=web.AppRunner(app,access_log=None)
        await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0)
        await site.start()
        port=site._server.sockets[0].getsockname()[1]
        try:
            async with ClientSession() as client:
                scope=dict(contract=mobile.CONTRACT,owner='fixture@example.invalid',reader_epoch='a'*32)
                headers={'Origin':f'http://127.0.0.1:{port}','Content-Type':'application/json','X-ORRERY-Mobile-Contract':mobile.CONTRACT}
                async def post(op,payload):
                    async with client.post(f'http://127.0.0.1:{port}/_mobile/terminal/{op}',data=json.dumps(dict(scope,**payload)),headers=headers) as response:
                        return response.status,await response.json()
                _,cap=await post('capability',{})
                scope['epoch']=cap['epoch']
                _,listed=await post('targets',dict(name='FixtureCurie'))
                choice=listed['targets'][0]['choice']
                _,preview=await post('preview',dict(choice=choice))
                rev=preview['target']['revision']
                if case=='wrong_owner':scope['owner']='other@example.invalid'
                if case=='wrong_revision':rev='0'*64
                if case=='changed_pane':version[0]+=1
                if case=='disabled':coordinator.set_enabled(False)
                if case=='no_pillow':monkeypatch.setattr(mobile_image,'Image',None)
                status,result=await post('image',dict(choice=choice,revision=rev,image=None if case in {'probe','no_workspace','no_pillow'} else picture()))
                assert sent==[]
                if case in {'wrong_owner','wrong_revision','changed_pane','disabled'}:
                    assert status==403 and not (tmp_path/'.orrery-input-images').exists()
                    return
                assert status==200 and result['enabled'] is (case not in {'no_workspace','no_pillow'})
                if case=='upload':assert Path(result['path']).is_file()
                else:assert 'path' not in result and not (tmp_path/'.orrery-input-images').exists()
                _,pending=await post('prepare',dict(choice=choice,revision=rev,text='unchanged text'))
                payload=dict(intent=pending['intent'],confirmation=pending['confirmation'])
                assert (await post('commit',payload))[1]['state']=='accepted'
                assert (await post('commit',payload))[1]['state']=='accepted'
                assert sent==['unchanged text']
        finally:await runner.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('case',['bound','missing_workspace','binding_changed','secondary_pane'])
def test_app_uses_bound_transcript_workspace_not_phone_path(tmp_path,monkeypatch,case):
    import json
    from types import SimpleNamespace
    import orrery_backend as backend
    import mobile_access
    from test_mobile_input import bridge_fixture
    from mobile_input import CONTRACT
    class Boundary:
        shared=None;transport=None;home=tmp_path
    monkeypatch.setattr(backend,'LegacyTargetBoundary',Boundary)
    path=tmp_path/'fixture.jsonl'
    path.write_text(json.dumps(dict(type='session_meta',payload=dict(cwd=str(tmp_path/'missing') if case=='missing_workspace' else str(tmp_path))))+'\n')
    row=dict(name='FixtureCurie',program='codex',history_binding='bound',transcript_path=str(path))
    calls=[]
    async def bound(request,name,not_before=None):
        calls.append(name)
        return dict(row,transcript_path=str(tmp_path/'other.jsonl')) if case=='binding_changed' and len(calls)>1 else row
    monkeypatch.setattr(backend,'conversation_bound_row',bound)
    async def scenario():
        bridge=bridge_fixture(tmp_path)
        app=backend.create_app(Boundary(),mobile_input_enabled=True)
        app[backend.BRIDGE_MANAGER_KEY]=SimpleNamespace(states={'FixtureCurie':SimpleNamespace(bridge=bridge)})
        coordinator=app[mobile_access.INPUT_KEY]
        class Resolver:
            def read(self,b,p,deadline):return dict(incarnation=b._incarnation,pane_id=p,height=24)
        coordinator.resolver=Resolver()
        async def capture(*args,**kwargs):return SimpleNamespace(lines=['fixture'])
        bridge.capture_mobile_preview=capture
        scope=dict(contract=CONTRACT,owner='fixture@example.invalid',reader_epoch='a'*32,epoch=coordinator.epoch)
        target=(await coordinator.request('targets',dict(scope,name='FixtureCurie')))['targets'][0]
        preview=await coordinator.request('preview',dict(scope,choice=target['choice']))
        if case=='secondary_pane':
            import mobile_input
            selected=coordinator.choices[target['choice']]
            selected['pane_id']='%4';bridge.panes['%4']=bridge.panes['%3']
            selected['proof']=coordinator.resolver.read(bridge,'%4',time.monotonic()+1)
            preview['target']['revision']=mobile_input.revision(selected['proof'])
        value=await coordinator.request('image',dict(scope,choice=target['choice'],revision=preview['target']['revision'],image=None))
        assert value['enabled'] is (case=='bound')
        assert not (tmp_path/'.orrery-input-images').exists()
        coordinator.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('case',['no_contract','other_origin','public_host','serve_header','no_choice'])
def test_direct_bridge_image_request_cannot_bypass_internal_admission(tmp_path,case):
    from aiohttp import ClientSession,web
    import mobile_input as mobile
    called=[]
    class Coordinator(mobile.InputCoordinator):
        async def request(self,operation,payload):
            called.append(operation)
            return await super().request(operation,payload)
    async def scenario():
        async def get_bridge(*args):raise AssertionError('an unissued choice must not resolve a pane')
        coordinator=Coordinator(None,get_bridge,enabled=True)
        app=web.Application();mobile.install_routes(app,coordinator)
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        try:
            headers={'Origin':f'http://127.0.0.1:{port}','X-ORRERY-Mobile-Contract':mobile.CONTRACT}
            if case=='no_contract':del headers['X-ORRERY-Mobile-Contract']
            if case=='other_origin':headers['Origin']='https://outsider.example.test'
            if case=='public_host':headers['Host']='viewer.example.ts.net'
            if case=='serve_header':headers['Tailscale-User-Login']='owner@example.test'
            async with ClientSession() as client:
                body=dict(contract=mobile.CONTRACT,owner='owner@example.test',reader_epoch='a'*32,epoch=coordinator.epoch,
                          choice='b'*64,revision='c'*64,image=picture())
                async with client.post(f'http://127.0.0.1:{port}/_mobile/terminal/image',headers=headers,json=body) as response:
                    assert response.status==403
            assert called==(['image'] if case=='no_choice' else [])
            assert not (tmp_path/'.orrery-input-images').exists()
        finally:await runner.cleanup()
    asyncio.run(scenario())


def test_backend_cannot_bind_to_a_public_interface():
    import orrery_backend as backend
    with pytest.raises(SystemExit,match='restricted to 127.0.0.1'):
        backend.main(['--host','0.0.0.0'])
