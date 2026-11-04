"""Synthetic native records only; no provider process, personal text or live DB."""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import conversation_history as history
from conversation_preview import ReferenceStore, PreviewUnavailable, binding


def line(item):return (json.dumps(item)+'\n').encode()
def row(path,program,sid='fixture-session'):
    return dict(name='FixtureAgent',program=program,history_binding='bound',transcript_path=str(path),
                history_session_id=sid,history_receipt_ts='2026-11-04T07:00:00Z')
def page(r,**kw):
    with history.open_reader(r) as reader:return reader.read_page(**kw)
def claude(role,content,**kw):
    return dict(type=role,sessionId='fixture-session',cwd=kw.pop('cwd',None),timestamp='2026-11-04T07:00:00Z',message=dict(role=role,content=content),**kw)
def dsh(kind,data,seq=1,**kw):return dict(type=kind,seq=seq,time=1793775600000,data=data,surfaceOp='append',**kw)
def make_db(path):
    con=sqlite3.connect(path)
    con.executescript('''CREATE TABLE sessions(id TEXT PRIMARY KEY,source TEXT,cwd TEXT);
    CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,tool_calls TEXT,tool_call_id TEXT,tool_name TEXT,timestamp REAL,active INTEGER DEFAULT 1,compacted INTEGER DEFAULT 0,display_kind TEXT,display_metadata TEXT,_compressed_summary INTEGER DEFAULT 0);
    INSERT INTO sessions VALUES('fixture-session','cli',NULL),('foreign-session','cli',NULL);''')
    return con

def test_claude_visible_blocks_tools_results_and_recorded_edit(tmp_path):
    path=tmp_path/'fixture.jsonl';(tmp_path/'a.txt').write_text('current')
    path.write_bytes(line(claude('user','hello',cwd=str(tmp_path)))+line(claude('assistant',[
        dict(type='thinking',thinking='HIDDEN_REASONING'),dict(type='text',text='answer'),
        dict(type='tool_use',id='call1',name='Edit',input=dict(file_path=str(tmp_path/'a.txt'),old_string='before',new_string='after'))]))+
        line(claude('user',[dict(type='tool_result',tool_use_id='call1',content='HIDDEN_TOOL_OUTPUT',is_error=False)])))
    r=row(path,'claude-code');result=page(r)
    assert [e['kind'] for e in result['events']]==['text','text','tool','tool_result']
    assert [e['text'] for e in result['events']][:3]==['hello','answer','Edit']
    assert 'HIDDEN' not in json.dumps(result)
    store=ReferenceStore()
    with history.open_reader(r) as reader:
        event=result['events'][2];store.decorate(r,reader,event)
    assert '-before\n+after' in event['diff']
    assert store.read(event['references'][0]['id'],r)['text']=='current'

def test_claude_block_paging_has_no_gaps_and_waits_for_newline(tmp_path):
    path=tmp_path/'fixture.jsonl'
    path.write_bytes(line(claude('user','first'))+line(claude('assistant',[
        dict(type='text',text='one'),dict(type='tool_use',name='Read',input={}),dict(type='tool_use',name='Read',input={})])))
    p=page(row(path,'claude-code'),limit=1);found=p['events']
    for _ in range(10):
        if not p['has_older']:break
        p=page(row(path,'claude-code'),before=p['before'],limit=1);found=p['events']+found
    assert len(found)==4 and len({e['id'] for e in found})==4
    last=page(row(path,'claude-code'))['after']
    with path.open('ab') as f:f.write(line(claude('user','pending'))[:-1])
    assert page(row(path,'claude-code'),after=last)['events']==[]
    with path.open('ab') as f:f.write(b'\n')
    assert page(row(path,'claude-code'),after=last)['events'][0]['text']=='pending'

@pytest.mark.parametrize('flag',[dict(isSidechain=True),dict(isMeta=True)])
def test_claude_internal_and_wrong_session_are_never_visible(tmp_path,flag):
    path=tmp_path/'fixture.jsonl';path.write_bytes(line(claude('user','visible'))+line(claude('user','HIDDEN',**flag))+line(dict(claude('user','HIDDEN_OTHER'),sessionId='other')))
    assert [e['text'] for e in page(row(path,'claude-code'))['events']]==['visible']

def test_dsh_concatenated_frames_partial_append_and_millisecond_time(tmp_path):
    z=pytest.importorskip('zstandard');path=tmp_path/'session.v4.jsonl.zstd'
    header=line(dict(type='session',version=4,id='fixture-session',cwd=str(tmp_path)))
    records=[dsh('user/message',dict(role='user',source=dict(kind='user'),content=[dict(type='text',text='hello')])),
        dsh('assistant/message',dict(message=dict(role='assistant',content=[dict(type='text',text='answer'),dict(type='reasoning',text='HIDDEN')]),stream=['HIDDEN_STREAM']),2),
        dsh('tool/call',dict(name='read',callId='call',arguments=json.dumps(dict(file_path='a.txt'))),3),
        dsh('tool/result',dict(message=dict(role='tool',toolCallId='call',content='HIDDEN_RESULT',isError=True)),4)]
    pack=lambda data:z.ZstdCompressor().compress(data)
    path.write_bytes(pack(header)+pack(b''.join(line(x) for x in records)))
    r=row(path,'dsh');result=page(r)
    assert [e['kind'] for e in result['events']]==['text','text','tool','tool_result']
    assert result['events'][0]['ts']=='2026-11-04T07:00:00Z'
    assert 'HIDDEN' not in json.dumps(result)
    final=pack(line(dsh('user/message',dict(role='user',source=dict(kind='user'),content=[dict(type='text',text='new')]),5)))
    with path.open('ab') as f:f.write(final[:-2])
    assert page(r,after=result['after'])['events']==[]
    with path.open('ab') as f:f.write(final[-2:])
    assert page(r,after=result['after'])['events'][0]['text']=='new'
    p=page(r,limit=1);ids=[p['events'][0]['id']]
    for _ in range(10):
        if not p['has_older']:break
        p=page(r,before=p['before'],limit=1);ids=[e['id'] for e in p['events']]+ids
    assert len(ids)==5 and len(set(ids))==5

@pytest.mark.parametrize('kind,extra',[('user/message',dict(source=dict(kind='injection'))),('assistant/attempt',{}),('system/message',{}),('developer/message',{})])
def test_dsh_hidden_sources_are_not_operator_prompts(tmp_path,kind,extra):
    path=tmp_path/'session.v4.jsonl';path.write_bytes(line(dict(type='session',version=4,id='fixture-session'))+line(dsh(kind,dict(content=[dict(type='text',text='HIDDEN')],**extra))))
    assert page(row(path,'dsh'))['events']==[]

@pytest.mark.parametrize('program',['claude-code','dsh','hermes'])
@pytest.mark.parametrize('state',['stale','unbound'])
def test_non_bound_never_opens_a_file(tmp_path,monkeypatch,program,state):
    monkeypatch.setattr(os,'open',lambda *a,**k:pytest.fail('non-bound file opened'))
    with pytest.raises(history.HistoryUnavailable,match='history_stale' if state=='stale' else 'history_unconfirmed'):
        with history.open_reader(dict(row(tmp_path/'missing.jsonl',program),history_binding=state)):pass

def test_hermes_exact_session_readonly_wal_snapshot_and_rewrite(tmp_path):
    path=tmp_path/'state.db';con=make_db(path);con.execute('PRAGMA journal_mode=WAL')
    con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'foreign-session','user','FOREIGN_BODY',1793775600),(2,'fixture-session','user','hello',1793775600),(3,'fixture-session','assistant','answer',1793775600)")
    con.commit();r=row(path,'hermes');result=page(r)
    assert [e['text'] for e in result['events']]==['hello','answer']
    assert result['mode']=='snapshot' and result['events'][0]['ts']=='2026-11-04T07:00:00Z'
    con.execute("UPDATE messages SET content='rewritten' WHERE id=3");con.execute('UPDATE messages SET active=0 WHERE id=2');con.commit()
    assert [e['text'] for e in page(r,after=result['after'])['events']]==['rewritten']
    assert 'FOREIGN_BODY' not in json.dumps(result)
    con.close()

def test_hermes_tool_refs_and_session_switch_cannot_reuse_reference(tmp_path):
    path=tmp_path/'state.db';(tmp_path/'a.txt').write_text('safe');con=make_db(path)
    args=dict(path=str(tmp_path/'a.txt'),old_string='old',new_string='new')
    tools=json.dumps([dict(id='c',type='function',function=dict(name='patch',arguments=json.dumps(args)))])
    con.execute("INSERT INTO messages(id,session_id,role,tool_calls,timestamp) VALUES(1,'fixture-session','assistant',?,1793775600)",(tools,));con.commit();con.close()
    r=row(path,'hermes');store=ReferenceStore(workspace_roots=[str(tmp_path)])
    with history.open_reader(r) as reader:
        event=reader.read_page()['events'][0];store.decorate(r,reader,event)
    assert '-old\n+new' in event['diff']
    assert store.read(event['references'][0]['id'],r)['text']=='safe'
    with pytest.raises((PreviewUnavailable,history.HistoryUnavailable)):
        store.read(event['references'][0]['id'],dict(r,history_session_id='foreign-session'))
    assert binding(r)!=binding(dict(r,history_receipt_ts='later'))

def test_hermes_hidden_reasoning_and_malformed_tools(tmp_path):
    path=tmp_path/'state.db';con=make_db(path)
    con.execute("INSERT INTO messages(id,session_id,role,content,tool_calls,display_kind,timestamp) VALUES(1,'fixture-session','assistant','HIDDEN',NULL,'hidden',1),(2,'fixture-session','assistant','visible','not-json',NULL,1)")
    con.commit();con.close()
    assert [e['text'] for e in page(row(path,'hermes'))['events']]==['visible']

def test_old_dashboard_keeps_codex_only(tmp_path):
    for program in ['claude-code','dsh','hermes']:
        with pytest.raises(history.HistoryUnavailable,match='dashboard_upgrade_required'):
            history.bound_agent(dict(agents=[row(tmp_path/'fake',program)]),'FixtureAgent',api_generation=34)

@pytest.mark.parametrize('program',['claude-code','dsh'])
def test_native_header_mismatch_and_symlink_fail_closed(tmp_path,program):
    path=tmp_path/'history.jsonl'
    path.write_bytes(line(claude('user','hello')) if program=='claude-code' else line(dict(type='session',version=4,id='fixture-session')))
    with pytest.raises(history.HistoryUnavailable,match='history_changed'):page(row(path,program,sid='other'))
    link=tmp_path/'linked.jsonl';link.symlink_to(path)
    with pytest.raises(history.HistoryUnavailable):page(row(link,program))

def test_dsh_missing_decoder_oversized_frame_and_corrupt_complete_frame(tmp_path,monkeypatch):
    import conversation_readers as readers
    z=pytest.importorskip('zstandard');path=tmp_path/'session.v4.jsonl.zstd'
    header=z.ZstdCompressor().compress(line(dict(type='session',version=4,id='fixture-session')))
    path.write_bytes(header+z.ZstdCompressor().compress(b'x'*(readers.MAX_SCAN+1)))
    with pytest.raises(history.HistoryUnavailable,match='record_too_large'):page(row(path,'dsh'))
    path.write_bytes(header+z.ZstdCompressor().compress(line(dsh('tool/call',dict(name='read'))))+b'INVALID_FRAME')
    with pytest.raises(history.HistoryUnavailable,match='history_format_unsupported'):page(row(path,'dsh'))
    monkeypatch.setattr(readers,'zstd',None)
    with pytest.raises(history.HistoryUnavailable,match='dsh_decoder_unavailable'):page(row(path,'dsh'))

def test_dsh_recorded_result_diff_and_injected_replacement_excluded(tmp_path):
    path=tmp_path/'session.v4.jsonl';(tmp_path/'a.txt').write_text('current')
    result=dsh('tool/result',dict(message=dict(role='tool'),meta=dict(diffs=[dict(path='a.txt',oldText='before',newText='after')])))
    path.write_bytes(line(dict(type='session',version=4,id='fixture-session',cwd=str(tmp_path)))+line(result)+
        line(dict(dsh('user/message',dict(source=dict(kind='user'),content=[dict(type='text',text='HIDDEN_REPLACEMENT')])),surfaceOp=dict(op='replace',startSeq=1,endSeq=2))))
    r=row(path,'dsh');store=ReferenceStore()
    with history.open_reader(r) as reader:
        events=reader.read_page()['events'];assert len(events)==1;store.decorate(r,reader,events[0])
    assert '-before\n+after' in events[0]['diff'] and 'Recorded file tool result' in events[0]['diff_status']
    assert store.read(events[0]['references'][0]['id'],r)['text']=='current'

def test_hermes_opens_ro_and_cannot_reuse_foreign_cursor(tmp_path,monkeypatch):
    import conversation_readers as readers
    path=tmp_path/'state.db';con=make_db(path);con.commit();con.close()
    original=readers.sqlite3.connect;calls=[]
    def capture(*a,**kw):calls.append(a[0]);return original(*a,**kw)
    monkeypatch.setattr(readers.sqlite3,'connect',capture)
    r=row(path,'hermes');result=page(r)
    assert calls and all('mode=ro' in uri and 'immutable' not in uri for uri in calls)
    with pytest.raises(history.HistoryUnavailable,match='history_changed'):page(dict(r,history_session_id='foreign-session'),after=result['after'])
    with history.open_reader(r) as reader:
        with pytest.raises(sqlite3.OperationalError):reader.db.execute("DELETE FROM messages")

@pytest.mark.parametrize('program',['claude-code','dsh','hermes'])
def test_api_bound_provider_and_mid_read_native_id_switch(tmp_path,monkeypatch,program):
    import asyncio
    import orrery_backend as backend
    from aiohttp import web,ClientSession
    async def scenario():
        if program=='claude-code':
            path=tmp_path/'history.jsonl';path.write_bytes(line(claude('user','fixture body')))
        elif program=='dsh':
            path=tmp_path/'history.jsonl';path.write_bytes(line(dict(type='session',version=4,id='fixture-session'))+line(dsh('user/message',dict(source=dict(kind='user'),content=[dict(type='text',text='fixture body')]))))
        else:
            path=tmp_path/'state.db';con=make_db(path);con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user','fixture body',1)");con.commit();con.close()
        current=row(path,program);calls=[];switch=[False]
        async def upstream(request):
            if request.path=='/api/version':return web.json_response(dict(api=35))
            calls.append(1);value=dict(current)
            if switch[0] and len(calls)%2==0:value['history_session_id']='foreign-session'
            return web.json_response(dict(agents=[value]))
        async def start(app):
            runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            return runner,'http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        upstream_app=web.Application();upstream_app.router.add_get('/{tail:.*}',upstream)
        up,url=await start(upstream_app);monkeypatch.setattr(backend,'DASHBOARD_URL',url)
        try:
            async with ClientSession() as client:
                app=web.Application();app[backend.HTTP_SESSION_KEY]=client;app[backend.TMUX_BIN_KEY]='fixture-unused';app[backend.CONVERSATION_REFERENCES_KEY]=ReferenceStore()
                app.router.add_get('/telemetry/conversation',backend.serve_conversation)
                runner,base=await start(app)
                try:
                    async with client.get(base+'/telemetry/conversation?agent=FixtureAgent') as response:
                        data=await response.json();assert data['ok'] and data['events'][0]['text']=='fixture body'
                    switch[0]=True
                    async with client.get(base+'/telemetry/conversation?agent=FixtureAgent') as response:
                        data=await response.json();assert data==dict(ok=False,error='history_changed')
                    for state in ['stale','unbound']:
                        current.update(history_binding=state,transcript_path=None,history_binding_reason='fixture reason',history_binding_reason_code='receipt_unavailable');switch[0]=False
                        async with client.get(base+'/telemetry/conversation?agent=FixtureAgent') as response:
                            data=await response.json();assert not data['ok'] and 'events' not in data and data['reason']=='fixture reason' and data['reason_code']=='receipt_unavailable'
                finally:await runner.cleanup()
        finally:await up.cleanup()
    asyncio.run(scenario())

def test_dsh_many_frames_page_back_and_incremental_budget_do_not_skip(tmp_path,monkeypatch):
    import conversation_readers as readers
    z=pytest.importorskip('zstandard');path=tmp_path/'session.v4.jsonl.zstd'
    pack=lambda data:z.ZstdCompressor().compress(data)
    header=pack(line(dict(type='session',version=4,id='fixture-session')))
    def event(n):return pack(line(dsh('user/message',dict(source=dict(kind='user'),content=[dict(type='text',text=str(n))]),n)))
    path.write_bytes(header+event(0));r=row(path,'dsh');initial=page(r)
    with path.open('ab') as f:f.write(b''.join(event(n) for n in range(1,600)))
    seen=[];cursor=initial['after']
    for _ in range(20):
        p=page(r,after=cursor,limit=80);seen.extend(e['text'] for e in p['events']);cursor=p['after']
        if not p['has_newer']:break
    assert seen==list(map(str,range(1,600)))
    p=page(r,limit=80);seen=[e['text'] for e in p['events']]
    for _ in range(20):
        if not p['has_older']:break
        p=page(r,before=p['before'],limit=80);seen=[e['text'] for e in p['events']]+seen
    assert seen==list(map(str,range(600)))

def test_hermes_bound_query_only_and_no_foreign_record_lookup(tmp_path,monkeypatch):
    path=tmp_path/'state.db';con=make_db(path)
    con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user','visible',1),(2,'foreign-session','user','foreign',1)");con.commit();con.close()
    with history.open_reader(row(path,'hermes')) as reader:
        trace=[];reader.db.set_trace_callback(trace.append);reader.read_page()
        assert all("session_id='fixture-session'" in sql for sql in trace if 'FROM messages' in sql)
        with pytest.raises(history.HistoryUnavailable):reader.record_at('2:0:0')

@pytest.mark.parametrize('old,new',[('.env','safe.txt'),('safe.txt','auth.json')])
def test_hermes_unified_patch_never_exposes_sensitive_rename_hunks(old,new):
    from conversation_artifacts import extract_artifacts
    item=dict(type='response_item',payload=dict(type='function_call',name='patch',arguments=json.dumps(dict(patch=f'--- a/{old}\n+++ b/{new}\n@@\n-DO_NOT_SHOW\n+DO_NOT_SHOW'))))
    result=extract_artifacts(item)
    assert not result['paths'] and 'DO_NOT_SHOW' not in result['diff']

def test_hermes_model_only_and_system_rows_are_not_fetched_for_display(tmp_path):
    path=tmp_path/'state.db';con=make_db(path)
    for n,role,meta in [(1,'system',None),(2,'assistant','{"model_only":true}'),(3,'assistant','broken metadata')]:
        con.execute('INSERT INTO messages(id,session_id,role,content,display_metadata,timestamp) VALUES(?,?,?,?,?,1)',(n,'fixture-session',role,'HIDDEN_BODY',meta))
    con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(4,'fixture-session','user','visible',1)")
    con.commit();con.close()
    r=row(path,'hermes')
    assert [e['text'] for e in page(r)['events']]==['visible']
    with history.open_reader(r) as reader:
        for n in (1,2,3):
            with pytest.raises(history.HistoryUnavailable):reader.record_at(f'{n}:0:0')
