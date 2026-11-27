"""A slow catalog survives polling timeouts, and the open picker recovers itself."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.test_utils import TestClient, TestServer

from test_cockpit_tour import tour_browser

BRIDGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BRIDGE))
import orrery_backend as ob


def node(body):
    script=f"const Loader=require({json.dumps(str(BRIDGE/'spawn_catalog_loader.js'))});\n"
    script+='(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});'
    return json.loads(subprocess.run(['node','-e',script],check=True,capture_output=True,text=True).stdout)


def test_catalog_retries_with_spacing_then_polls_and_recovers_without_a_click():
    result=node('''
      const states=[],timers=[];let mode='fail',calls=0;
      const data={providers:[{id:'live',models:['from-telemetry']}]};
      const loader=Loader.create({isOpen:()=>true,onState:s=>states.push(s),
        fetchCatalog:async()=>{calls++;if(mode==='fail')throw Error('busy');return {catalog:data};},
        setTimer:(fn,delay)=>{const task={fn,delay};timers.push(task);return task;},clearTimer:()=>{}});
      await loader.refresh();const initial=states.at(-1).status;
      const delays=[];for(let i=0;i<4;i++){const t=timers.shift();delays.push(t.delay);await t.fn();}
      const unavailable=states.at(-1).status;mode='ready';const t=timers.shift();delays.push(t.delay);await t.fn();
      console.log(JSON.stringify({initial,unavailable,delays,calls,final:states.at(-1),timers:timers.length}));
    ''')
    assert result['initial']=='loading' and result['unavailable']=='unavailable'
    assert result['delays']==[1000,3000,8000,30000,30000]
    assert result['final']['status']=='ready' and result['final']['catalog']['providers'][0]['id']=='live'
    assert result['calls']==6 and result['timers']==0


def test_only_a_successful_catalog_is_reused_and_close_discards_late_results():
    result=node('''
      const states=[],timers=[];let mode='good',resolveOld;
      const good={providers:[{id:'last-good'}]},newer={providers:[{id:'newer'}]};
      const loader=Loader.create({isOpen:()=>true,onState:s=>states.push(s),
        fetchCatalog:()=>mode==='good'?Promise.resolve({catalog:good}):mode==='new'?Promise.resolve({catalog:newer}):mode==='slow'?new Promise(r=>resolveOld=r):Promise.reject(Error('offline')),
        setTimer:(fn,delay)=>{const t={fn,delay};timers.push(t);return t;},clearTimer:t=>timers.splice(timers.indexOf(t),1)});
      await loader.refresh();mode='fail';await loader.refresh();const stale=states.at(-1);
      loader.stop();const stopped=timers.length;mode='slow';const old=loader.refresh();
      await Promise.resolve();const same=loader.refresh()===old;loader.stop();mode='new';await loader.refresh();
      resolveOld({catalog:{providers:[{id:'obsolete'}]}});await old;
      console.log(JSON.stringify({stale,stopped,same,final:states.at(-1)}));
    ''')
    assert result['stale']==dict(status='stale',catalog=dict(providers=[dict(id='last-good')]))
    assert result['stopped']==0 and result['same']
    assert result['final']==dict(status='ready',catalog=dict(providers=[dict(id='newer')]))


def test_server_snapshot_is_shown_while_waiting_for_the_refresh():
    result=node('''
      const states=[],timers=[];let stale=true,calls=0;
      const loader=Loader.create({isOpen:()=>true,onState:s=>states.push(s),
        fetchCatalog:async()=>{calls++;return {catalog:{providers:[{id:stale?'old':'new'}]},stale}},
        setTimer:(fn,delay)=>{timers.push({fn,delay});return fn;},clearTimer:()=>{}});
      await loader.refresh();
      const initial=states.at(-1),timer=timers.shift();
      stale=false;await timer.fn();
      console.log(JSON.stringify({initial,final:states.at(-1),delay:timer.delay,calls,timers:timers.length}));
    ''')
    assert result == {
        'initial': {'catalog': {'providers': [{'id': 'old'}]}, 'status': 'stale'},
        'final': {'catalog': {'providers': [{'id': 'new'}]}, 'status': 'ready'},
        'delay': 1000, 'calls': 2, 'timers': 0,
    }


def catalog_proxy(monkeypatch,delay,*,timeout=None,clients=1):
    async def run():
        requests=0
        async def handle(request):
            nonlocal requests
            requests+=1
            await asyncio.sleep(delay)
            return web.json_response({'providers':[{'id':'codex','label':'Codex','models':['fixture-current']} ]})
        upstream=web.Application();upstream.router.add_get('/api/spawn-names',handle)
        async with TestServer(upstream) as source,ClientSession(timeout=ClientTimeout(total=.1)) as session:
            monkeypatch.setattr(ob,'DASHBOARD_URL',str(source.make_url('')).rstrip('/'))
            if timeout is not None:monkeypatch.setattr(ob,'CATALOG_PROXY_TIMEOUT',timeout)
            app=web.Application();app[ob.HTTP_SESSION_KEY]=session;app[ob.PROXY_INFLIGHT_KEY]={};app[ob.TMUX_BIN_KEY]='unused'  # Catalog requests never construct or use a tmux transport.
            app[ob.SPAWN_CATALOG_KEY]=ob.SpawnCatalogCache(session,'unused')
            app.router.add_get('/telemetry/spawn-catalog',ob.proxy_dashboard)
            async with TestClient(TestServer(app)) as client:
                async def ask():
                    async with client.get('/telemetry/spawn-catalog') as response:return response.status,await response.json()
                result=await asyncio.gather(*(ask() for _ in range(clients)))
                return result,requests
    return asyncio.run(run())


def test_catalog_can_take_longer_than_the_previous_six_second_poll_limit(monkeypatch):
    result,requests=catalog_proxy(monkeypatch,6.2)
    assert requests==1 and result[0][0]==200
    assert result[0][1]['providers'][0]['models'][0]['id']=='fixture-current'


def test_catalog_timeout_is_bounded_and_concurrent_dialogs_share_the_fetch(monkeypatch):
    result,requests=catalog_proxy(monkeypatch,.15,timeout=.05,clients=2)
    assert requests==1 and result==[(502,{'error':'dashboard slow'})]*2


def test_startup_populates_and_stale_requests_share_a_nonblocking_refresh(monkeypatch):
    class Manager:
        def __init__(self, _): pass
        async def start(self): pass
        async def close(self): pass

    async def run():
        warmed = asyncio.Event()
        started = asyncio.Event()
        release = asyncio.Event()
        release_warmup = asyncio.Event()
        now = 0
        requests = []

        async def handle(request):
            requests.append(request.path)
            if len(requests) == 1:
                warmed.set()
                await release_warmup.wait()
            elif len(requests) == 2:
                started.set()
                await release.wait()
            return web.json_response({'providers': [{'id': 'codex', 'models': [f'model-{len(requests)}']}]})

        upstream = web.Application()
        upstream.router.add_get('/api/spawn-names', handle)
        real_cache = ob.SpawnCatalogCache
        async with TestServer(upstream) as source:
            monkeypatch.setattr(ob, 'DASHBOARD_URL', str(source.make_url('')).rstrip('/'))
            monkeypatch.setattr(ob, 'SessionBridgeManager', Manager)
            monkeypatch.setattr(ob, 'SpawnCatalogCache',
                                lambda session, tmux: real_cache(session, tmux, clock=lambda: now))
            app = ob.create_app(object.__new__(ob.LegacyTargetBoundary))
            try:
                async with TestClient(TestServer(app)) as client:
                    await asyncio.wait_for(warmed.wait(), 2)
                    # Join the startup task without a client request on this route.
                    warmup = app[ob.SPAWN_CATALOG_KEY].refresh()
                    release_warmup.set()
                    await warmup
                    assert requests == ['/api/spawn-names']

                    async def get():
                        async with client.get(ob.SPAWN_CATALOG_ROUTE) as response:
                            model = (await response.json())['providers'][0]['models'][0]['id']
                            return model, response.headers.get('X-Orrery-Catalog-State')

                    assert await get() == ('model-1', None)
                    now = real_cache.FRESH_SECONDS
                    stale = await asyncio.wait_for(asyncio.gather(*(get() for _ in range(4))), 2)
                    assert stale == [('model-1', 'stale')] * 4
                    await asyncio.wait_for(started.wait(), 2)
                    assert len(requests) == 2
                    refresh = app[ob.SPAWN_CATALOG_KEY].refresh()
                    release.set()
                    await refresh
                    assert await get() == ('model-2', None)
                    assert len(requests) == 2
            finally:
                release_warmup.set()
                release.set()

    asyncio.run(run())


def test_background_catalog_request_is_cancelled_at_app_shutdown(monkeypatch):
    class Manager:
        def __init__(self, _): pass
        async def start(self): pass
        async def close(self): pass

    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fetch(*_):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        monkeypatch.setattr(ob, 'SessionBridgeManager', Manager)
        monkeypatch.setattr(ob, 'fetch_proxied', fetch)
        app = ob.create_app(object.__new__(ob.LegacyTargetBoundary))
        async with TestClient(TestServer(app)):
            await asyncio.wait_for(started.wait(), 2)
        assert cancelled.is_set()
        assert app[ob.HTTP_SESSION_KEY].closed

    asyncio.run(run())


def test_failed_refresh_keeps_the_last_snapshot_and_missing_route_clears_it(monkeypatch):
    async def run():
        now = 0
        replies = iter([
            (200, {'providers': []}),
            (200, {'wrong': 'shape'}),
            (503, {'error': 'busy'}),
            (200, {'providers': []}),
            (404, {'error': 'unknown route'}),
            (404, {'error': 'unknown route'}),
        ])

        async def fetch(*_):
            status, body = next(replies)
            return json.dumps(body).encode(), status, 'application/json'

        monkeypatch.setattr(ob, 'fetch_proxied', fetch)
        cache = ob.SpawnCatalogCache(None, 'unused', clock=lambda: now)
        (old, status, _), stale = await cache.read()
        assert status == 200 and not stale
        now = cache.FRESH_SECONDS
        assert (await cache.read())[1]
        await cache.refresh()
        assert (await cache.read())[0][0] == old
        assert cache._pending is None  # The failure backs off before retrying.
        now += 600
        assert (await cache.read())[0][0] == old  # A long idle period is still a cache hit.
        await cache.refresh()
        assert (await cache.read())[0][0] == old
        now += cache.RETRY_SECONDS
        assert (await cache.read())[1]
        await cache.refresh()
        assert not (await cache.read())[1]
        now += cache.FRESH_SECONDS
        assert (await cache.read())[1]
        await cache.refresh()
        assert (await cache.read())[0][1] == 404

    asyncio.run(run())


CUA_TIMEOUT = "Windows Cua Driver did not answer. Check that its daemon is running."
CHROME_TIMEOUT = "ORRERY cannot check Windows Chrome from WSL. Check Windows interop."
DRIVER_MISSING = "Windows Cua Driver executable was not found or is not executable."


def wsl_catalog(computer_reason=None, chrome_reason=None):
    return {
        "providers": [{"id": "claude", "program": "claude-code", "models": ["fixture"]}],
        "computer_use_transport": "orrery-screen",
        "computer_use": computer_reason is None,
        "computer_modes": ["off"] if computer_reason else ["off", "view", "control"],
        "browser_modes": {"claude-code": ["off", "temporary", "personal"]},
        **({"computer_use_reason": computer_reason} if computer_reason else {}),
        **({"personal_browser_status": {"claude-code": {"reason": chrome_reason, "unavailable": False}}}
           if chrome_reason else {}),
    }


def test_wsl_probe_timeouts_back_off_and_retain_the_last_verified_result_per_tool(monkeypatch):
    async def run():
        now = 0
        replies = iter([
            wsl_catalog(CUA_TIMEOUT, CHROME_TIMEOUT),   # warmup before Windows answers
            wsl_catalog(chrome_reason=CHROME_TIMEOUT),  # Cua Driver recovers first
            wsl_catalog(CUA_TIMEOUT),                   # Chrome recovers while Cua Driver times out again
            wsl_catalog(CUA_TIMEOUT, CHROME_TIMEOUT),   # both use the last confirmed results
            wsl_catalog(DRIVER_MISSING),                # a confirmed failure replaces the old result
        ])
        fetches = 0

        async def fetch(*_):
            nonlocal fetches
            fetches += 1
            return json.dumps(next(replies)).encode(), 200, "application/json"

        monkeypatch.setattr(ob, "fetch_proxied", fetch)
        cache = ob.SpawnCatalogCache(None, "unused", clock=lambda: now)
        app = web.Application()
        app[ob.HTTP_SESSION_KEY] = None
        app[ob.SPAWN_CATALOG_KEY] = cache
        app.router.add_get(ob.SPAWN_CATALOG_ROUTE, ob.proxy_dashboard)
        async with TestClient(TestServer(app)) as client:
            async def read():
                async with client.get(ob.SPAWN_CATALOG_ROUTE) as response:
                    assert response.status == 200
                    return await response.json(), response.headers.get("X-Orrery-Catalog-State")

            try:
                await cache.refresh()
                assert await read() == (wsl_catalog(CUA_TIMEOUT, CHROME_TIMEOUT), "checking")
                now += cache.RETRY_SECONDS - 1
                assert await read() == (wsl_catalog(CUA_TIMEOUT, CHROME_TIMEOUT), "checking")
                assert fetches == 1
                for expected, state in [
                    (wsl_catalog(chrome_reason=CHROME_TIMEOUT), "checking"),
                    (wsl_catalog(), "checking"),
                    (wsl_catalog(), "checking"),
                    (wsl_catalog(DRIVER_MISSING), None),
                ]:
                    now += cache.RETRY_SECONDS
                    await read()  # The next request starts a shared background refresh.
                    if cache._pending:
                        await cache._pending
                    assert await read() == (expected, state)
                assert now < cache.FRESH_SECONDS
                assert fetches == 5
                assert await read() == (wsl_catalog(DRIVER_MISSING), None)
            finally:
                await cache.close()

    asyncio.run(run())


def test_open_cockpit_recovers_computer_use_and_keeps_the_draft(tour_browser):
    _, evaluate = tour_browser
    catalog = wsl_catalog(CUA_TIMEOUT, CHROME_TIMEOUT)
    catalog["providers"][0]["models"] = [{"id": "fixture", "default": True}, {"id": "chosen"}]
    recovered = wsl_catalog()
    recovered["providers"] = catalog["providers"]
    result = evaluate('''(async()=>{
      const original=window.fetch;let ready=false,calls=0;
      window.fetch=(url,options)=>{
        if(url==='/telemetry/spawn-catalog'){
          calls++;
          return Promise.resolve(Response.json(ready?READY:TIMEOUT,
            {headers:ready?{}:{'X-Orrery-Catalog-State':'checking'}}));
        }
        if(String(url).startsWith('/telemetry/fs/dirs'))
          return Promise.resolve(Response.json({path:'/workspace',dirs:[]}));
        return original(url,options);
      };
      try{
        openSpawnModal();await loadSpawnCatalog();
        const initial={disabled:spawnComputerUse.getAttribute('aria-disabled'),
          notice:spawnStatus.textContent,visible:!spawnStatus.hidden};
        spawnModelButton.click();
        modelChoices.querySelector('input[value=chosen]').click();
        spawnTask.value='Keep my instruction';
        spawnTask.dispatchEvent(new Event('input'));
        spawnBrowserUse.click();
        spawnBrowserChoices.find(([mode])=>mode==='off')[1].click();
        ready=true;
        const deadline=performance.now()+7500;
        while(spawnComputerUse.getAttribute('aria-disabled')!=='false'){
          if(performance.now()>deadline)throw Error('Computer use did not recover');
          await new Promise(resolve=>setTimeout(resolve,25));
        }
        spawnComputerUse.click();
        const choices=spawnComputerChoices.filter(([,button])=>!button.hidden).map(([mode])=>mode);
        const computerDefault=spawnComputerUse.dataset.computerMode;
        spawnComputerChoices.find(([mode])=>mode==='view')[1].click();
        return {initial,calls,choices,computerDefault,model:selModel,task:spawnTask.value,
          tools:spawnToolOptions().tools,notice:spawnStatus.textContent};
      }finally{closeSpawnModal();window.fetch=original;}
    })()'''.replace('READY', json.dumps(recovered)).replace('TIMEOUT', json.dumps(catalog)))
    assert result == {
        "initial": {"disabled": "true", "visible": True,
                    "notice": f"Computer use: {CUA_TIMEOUT} My Chrome: {CHROME_TIMEOUT}"},
        "calls": 2, "choices": ["off", "view", "control"], "computerDefault": "off",
        "model": "chosen", "task": "Keep my instruction", "notice": "",
        "tools": {"screen": {"server": "orrery-screen", "access": "read"}, "browser_mode": "off"},
    }


def test_open_dialog_automatically_recovers_and_keeps_a_stale_selection(tour_browser):
    _,evaluate=tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch;let mode='fail',calls=0;
      const catalog={providers:[{id:'codex',label:'Codex',program:'codex-cli',models:[{id:'last-good',default:true}],efforts:['low','high']}],naming:{},dirs:[]};
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn-catalog'){calls++;if(mode==='fail')throw Error('slow fixture');return {ok:true,json:async()=>catalog};}
        if(String(url).startsWith('/telemetry/fs/dirs'))return {ok:true,json:async()=>({path:'/workspace',dirs:[]})};
        return original(url,options);
      };
      try{
        spawnOverlay.classList.add('on');spawnTask.value='Fixture task';await loadSpawnCatalog();
        spawnModelButton.click();
        const loading={listed:modelChoices.querySelectorAll('input').length,disabled:spawnSubmit.disabled,status:spawnStatus.textContent};
        mode='good';await new Promise(r=>setTimeout(r,1150));
        const recovered={model:selModel,disabled:spawnSubmit.disabled,status:spawnStatus.textContent};
        mode='fail';await loadSpawnCatalog();
        const input=effortChoices.querySelector('input');input.focus();
        await new Promise(r=>setTimeout(r,1150));
        const stale={model:selModel,disabled:spawnSubmit.disabled,catalogStale:spawnCatalog.stale,
          same:input===effortChoices.querySelector('input'),focus:document.activeElement===input};
        const before=calls;closeSpawnModal(true);await new Promise(r=>setTimeout(r,1200));
        return {loading,recovered,stale,stopped:calls===before};
      }finally{spawnCatalogLoader.stop();window.fetch=original;}
    })()''')
    assert result['loading']==dict(listed=0,disabled=True,status='')
    assert result['recovered']==dict(model='last-good',disabled=False,status='')
    assert result['stale']==dict(model='last-good',disabled=False,catalogStale=True,same=True,focus=True)
    assert result['stopped']


@pytest.mark.parametrize('keep_choice', [True, False])
def test_open_cockpit_adopts_refreshed_rows_and_checks_the_choice(tour_browser, keep_choice):
    _, evaluate = tour_browser
    result = evaluate('''(async()=>{
      const original=window.fetch;let calls=0,serveNew=false;
      window.fetch=(url,options)=>{
        if(url==='/telemetry/spawn-catalog'){
          calls++;
          return Promise.resolve(Response.json({providers:[{
            id:'codex',label:'Codex',program:'codex-cli',
            models:[{id:serveNew?'refreshed':'cached',default:true},
              ...(!serveNew||KEEP_CHOICE?[{id:'selected'}]:[])],
          }],naming:{},dirs:[]},{headers:serveNew?{}:{'X-Orrery-Catalog-State':'stale'}}));
        }
        if(String(url).startsWith('/telemetry/fs/dirs'))
          return Promise.resolve(Response.json({path:'/workspace',dirs:[]}));
        return original(url,options);
      };
      try{
        openSpawnModal();await loadSpawnCatalog();spawnModelButton.click();
        const initial=selModel;
        modelChoices.querySelector('input[value=selected]').click();spawnTask.value='Keep the draft';
        serveNew=true;
        const deadline=performance.now()+4000;
        while(!modelChoices.querySelector('input[value=refreshed]')){
          if(performance.now()>deadline)throw Error('Catalog did not refresh');
          await new Promise(resolve=>setTimeout(resolve,25));
        }
        const checked={initial,chosen:selModel,task:spawnTask.value,calls,stale:spawnCatalog.stale,
          blocked:spawnSubmit.disabled,notice:spawnStatus.textContent};
        if(!KEEP_CHOICE)modelChoices.querySelector('input[value=refreshed]').click();
        return {...checked,canLaunch:!spawnSubmit.disabled};
      }finally{closeSpawnModal();window.fetch=original;}
    })()'''.replace('KEEP_CHOICE', json.dumps(keep_choice)))
    assert result == dict(initial='cached', chosen='selected' if keep_choice else None,
                          task='Keep the draft', calls=2, stale=False, blocked=not keep_choice,
                          notice='' if keep_choice else 'Selected model or harness is no longer available. Choose again.',
                          canLaunch=True)
