import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_mobile_image import picture
from test_mobile_input import bridge_fixture
from control_server import PaneInfo


@pytest.mark.parametrize('case',['original_closed','indices_reordered'])
def test_another_pane_must_not_inherit_bound_workspace(tmp_path,monkeypatch,case):
    import orrery_backend as backend
    import mobile_access
    from mobile_input import CONTRACT,InputRefused
    class Boundary:
        shared=None;transport=None;home=tmp_path
    monkeypatch.setattr(backend,'LegacyTargetBoundary',Boundary)
    original_workspace=tmp_path/'original-agent';original_workspace.mkdir()
    second_workspace=tmp_path/'second-pane';second_workspace.mkdir()
    path=tmp_path/'fixture.jsonl'
    path.write_text(json.dumps(dict(type='session_meta',payload=dict(cwd=str(original_workspace))))+'\n')
    row=dict(name='FixtureCurie',program='codex',history_binding='bound',transcript_path=str(path))
    async def bound(request,name,not_before=None):return row
    monkeypatch.setattr(backend,'conversation_bound_row',bound)
    async def scenario():
        bridge=bridge_fixture(tmp_path)
        async def command(args,**kwargs):
            assert args==['display-message','-p','-t','%4','#{pane_current_path}']
            return SimpleNamespace(ok=True,overflow=False,lines=[str(second_workspace)])
        bridge.send_command=command
        app=backend.create_app(Boundary(),mobile_input_enabled=True)
        app[backend.BRIDGE_MANAGER_KEY]=SimpleNamespace(states={'FixtureCurie':SimpleNamespace(bridge=bridge)})
        coordinator=app[mobile_access.INPUT_KEY]
        class Resolver:
            def read(self,b,p,deadline):return dict(incarnation=b._incarnation,pane_id=p,height=24)
        coordinator.resolver=Resolver()
        async def capture(*args,**kwargs):return SimpleNamespace(lines=['different pane workspace'])
        bridge.capture_mobile_preview=capture
        bridge.panes['%4']=PaneInfo('%4','@1','$2','0','0',80,24,True,'Second',str(second_workspace))
        if case=='original_closed':del bridge.panes['%3']
        else:
            from dataclasses import replace
            bridge.panes['%3']=replace(bridge.panes['%3'],pane_index='1')
        scope=dict(contract=CONTRACT,owner='fixture@example.invalid',reader_epoch='a'*32,epoch=coordinator.epoch)
        target=next(t for t in (await coordinator.request('targets',dict(scope,name='FixtureCurie')))['targets'] if 'pane 0' in t['pane_label'])
        preview=await coordinator.request('preview',dict(scope,choice=target['choice']))
        try:
            result=await coordinator.request('image',dict(scope,choice=target['choice'],revision=preview['target']['revision'],image=picture()))
            print('WRITTEN',result.get('path'),'SELECTED',coordinator.choices[target['choice']]['pane_id'])
            assert not result.get('enabled'), 'a secondary pane inherited the original agent transcript workspace'
        except InputRefused:
            pass
        finally:coordinator.close()
        assert not list(original_workspace.rglob('*.png'))
    asyncio.run(scenario())
