"""Recorded model identity and compact speaker headings; synthetic data only."""
import json
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conversation_history as history
from conversation_readers import normalize
from test_conversation_history import record
from test_conversation_providers import claude, dsh
from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout


def test_native_models_belong_to_assistant_text_only():
    for raw, provider in [
        (dict(claude('assistant', [dict(type='text', text='answer'), dict(type='tool_use', name='Read', input={})]),
              message=dict(role='assistant', model='claude-opus-5-5', content=[dict(type='text', text='answer'), dict(type='tool_use', name='Read', input={})])), 'claude'),
        (dsh('assistant/message', dict(message=dict(role='assistant', model='deepseek-v4', content='answer'))), 'dsh'),
        (dict(role='assistant', content='answer', timestamp=1, display_metadata=json.dumps(dict(model='future-model'))), 'hermes'),
    ]:
        events=[e for _,e in normalize(raw, provider, 'fixture-session')]
        assert events[0]['model'] in {'claude-opus-5-5','deepseek-v4','future-model'}
        assert all('model' not in e for e in events[1:])
    raw=claude('user','human');raw['message']['model']='should-not-label-a-human'
    assert 'model' not in normalize(raw,'claude','fixture-session')[0][1]


@pytest.mark.parametrize('value', [None, 12, {}, ['gpt'], 'x'*257, 'bad\nmodel', 'bad\x00model'])
def test_invalid_model_metadata_is_ignored(value):
    raw=claude('assistant','answer');raw['message']['model']=value
    assert 'model' not in normalize(raw,'claude','fixture-session')[0][1]


def test_codex_models_follow_turns_in_the_loaded_window_and_response_wins(tmp_path):
    path=tmp_path/'generated.jsonl'
    context=lambda model:(json.dumps(dict(type='turn_context',payload=dict(model=model,private='DO_NOT_EXPORT')))+'\n').encode()
    path.write_bytes(context('gpt-6.1-sol')+record('first')+record('direct',model='gpt-6.1-terra')+
                     context('gpt-7-nova')+record('second')+record('human','user'))
    result=history.read_codex_page(str(path))
    assert [e.get('model') for e in result['events']]==['gpt-6.1-sol','gpt-6.1-terra','gpt-7-nova',None]
    assert 'DO_NOT_EXPORT' not in json.dumps(result)
    older=history.read_codex_page(str(path),before=result['events'][2]['cursor_before'],limit=1)
    assert older['events'][0]['model']=='gpt-6.1-terra'
    newer=history.read_codex_page(str(path),after=result['events'][1]['cursor_after'])
    assert newer['events'][0]['model']=='gpt-7-nova'
    # No extra lookbehind: the caller uses its roster fallback when context is outside the page.
    newer=history.read_codex_page(str(path),after=result['events'][0]['cursor_after'],limit=1)
    assert newer['events'][0]['model']=='gpt-6.1-terra'
    with path.open('ab') as out:out.write(record('no-context-in-this-delta'))
    assert 'model' not in history.read_codex_page(str(path),after=result['after'])['events'][0]


def prepare_speaker(cockpit, width=1600, theme='dark'):
    js,wait,client,requests,enable=cockpit
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=1000,deviceScaleFactor=1,mobile=False)
    stable_roster(js);enable(count=1)
    js("""conversationView.close();Object.assign(currentAgents[0],{program:'claude-code',provider:'anthropic',model:'Roster model'});
      window.speakerRows=[{id:'first',kind:'text',role:'assistant',text:'First model',ts:'2026-11-09T13:20:00Z',model:'claude-opus-5-5'},
        {id:'second',kind:'text',role:'assistant',text:'Changed model',model:'gpt-6.1-sol'},
        {id:'third',kind:'text',role:'assistant',text:'Another provider',model:'deepseek-v4'},
        {id:'fallback',kind:'text',role:'assistant',text:'Roster fallback'},
        {id:'human',kind:'text',role:'user',text:'Human prompt'},
        {id:'shell',kind:'text',role:'user',text:'<bash-input>pwd</bash-input>'},
        {id:'notice',kind:'system',role:'system',text:'Context compacted',system_detail:'Generated summary'}];
      OrreryConversationSource.Source.prototype.read=async()=>({provider:'claude',mode:'cursor',events:speakerRows,after:'tail'});
      OrreryColorTheme.setPreference("""+json.dumps(theme)+""");conversationView.open();""")
    wait("document.querySelector('.conversation-event[data-event-id=fallback]')!==null")
    js("window.speakerReader=document.querySelector('.conversation-panel:not([hidden])')")
    wait_reading_layout(js)
    return js,wait,client,requests


def test_speaker_name_recorded_model_and_roster_fallback(cockpit):
    js,wait,client,requests=prepare_speaker(cockpit)
    assert js("[...speakerReader.querySelectorAll('.conversation-speaker-name')].map(e=>e.textContent)")==['ReviewFixture']*4
    assert js("[...speakerReader.querySelectorAll('.conversation-speaker-model')].map(e=>e.textContent)")==['Opus 5.5','GPT-6.1-Sol','DeepSeek V4','Roster model']
    assert all('Claude' in label for label in js("[...speakerReader.querySelectorAll('.conversation-speaker')].map(e=>e.ariaLabel)"))
    assert js("speakerReader.querySelector('[data-event-id=human] .conversation-role').textContent")=='You'
    assert js("speakerReader.querySelector('[data-event-id=shell] .conversation-role').textContent")=='Shell'
    assert not js("speakerReader.querySelector('[data-event-id=notice] .conversation-speaker')")
    wait("speakerReader.querySelector('[data-event-id=second] .provider-badge img')?.naturalWidth>0")
    assert js("speakerReader.querySelector('[data-event-id=second] .provider-badge img').getAttribute('src')")=='cockpit-assets/openai.svg'
    # Same portrait source/initial as the roster, and a failed portrait leaves the initial visible.
    js("tileFor(currentAgents[0])")
    assert js("speakerReader.querySelector('.conversation-avatar .face img').getAttribute('src')===tiles.get('ReviewFixture').querySelector('.face img').getAttribute('src')")
    assert js("speakerReader.querySelector('.conversation-avatar .ini').textContent===tiles.get('ReviewFixture').querySelector('.ini').textContent")
    wait("speakerReader.querySelector('.conversation-avatar .face img').style.display==='none'")
    js("window.keptText=speakerReader.querySelector('.conversation-text');const r=document.createRange();r.selectNodeContents(keptText);getSelection().removeAllRanges();getSelection().addRange(r);Object.assign(currentAgents[0],{model:'Updated roster model'});document.dispatchEvent(new Event('oc:agents'))")
    assert js("speakerReader.querySelector('.conversation-text')===keptText&&getSelection().toString()==='First model'")
    assert js("speakerReader.querySelector('[data-event-id=fallback] .conversation-speaker-model').textContent")=='Updated roster model'
    assert js("speakerReader.querySelector('[data-event-id=first] .conversation-speaker-model').textContent")=='Opus 5.5'
    assert js("packets.filter(p=>p.type==='input')")==[]


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('width',[1600,390])
def test_model_is_subdued_and_yields_before_the_name(cockpit,theme,width):
    js,wait,client,_=prepare_speaker(cockpit,width,theme)
    if width==390:
        js("currentAgents.push({name:'OtherFixture',program:'codex',history_binding:'bound'});createPane('OtherFixture',{paneId:'%902',windowId:'@902',width:80,height:20});replaceSplitSessions(['ReviewFixture','OtherFixture']);splitVisible=true;focusSplitSession('ReviewFixture')")
        wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-speaker')!==null")
        js("speakerReader=document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-panel')")
        wait_reading_layout(js)
    js("OrreryConversationSpeaker.paint(speakerReader.querySelector('.conversation-speaker'),{name:'A deliberately long agent name',model:'claude-opus-5-5',harness:'Claude',context:{},renderAvatar:conversationAvatar})")
    metrics=js("""(()=>{const e=speakerReader.querySelector('.conversation-speaker'),n=e.querySelector('.conversation-speaker-name'),m=e.querySelector('.conversation-speaker-model'),a=e.querySelector('.conversation-avatar'),ns=getComputedStyle(n),ms=getComputedStyle(m);return {name:n.getBoundingClientRect().width,model:m.getBoundingClientRect().width,full:n.scrollWidth,avatar:a.getBoundingClientRect().width,nameFont:parseFloat(ns.fontSize),modelFont:parseFloat(ms.fontSize),nameColor:ns.color,modelColor:ms.color,overflow:e.scrollWidth>e.clientWidth+1}})()""")
    assert 18<=metrics['avatar']<=20 and metrics['name']>=8
    assert metrics['modelFont']<metrics['nameFont'] and metrics['modelColor']!=metrics['nameColor']
    assert not metrics['overflow'],metrics
    if metrics['name']<metrics['full']-1:assert metrics['model']<=1,metrics


def test_unknown_name_model_and_harness_fallback_use_literal_text(cockpit):
    js,wait,_,_=prepare_speaker(cockpit)
    assert js("OrreryConversationSpeaker.displayModel('gpt-7.2-nova-mini')")=='GPT-7.2-Nova-Mini'
    assert js("OrreryConversationSpeaker.displayModel('claude-sonnet-8-2-20261109')")=='Sonnet 8.2'
    assert js("OrreryConversationSpeaker.displayModel('<b>Future model</b>')")=='<b>Future model</b>'
    js("window.isolated=document.createElement('span');OrreryConversationSpeaker.paint(isolated,{harness:'Hermes',name:'',context:{},model:'',renderAvatar:null})")
    assert js("isolated.textContent")=='Hermes'
    assert not js("isolated.classList.contains('conversation-speaker')")
    js("OrreryConversationSpeaker.paint(isolated,{harness:'Codex',name:'',context:{},model:'gpt-6.1-sol',renderAvatar:null})")
    assert js("isolated.textContent")=='GPT-6.1-Sol'
    js("OrreryConversationSpeaker.paint(isolated,{harness:'Hermes',name:'<b>Agent</b>',context:{model:'<i>Model</i>'},renderAvatar:null})")
    assert not js("isolated.querySelector('b,i')")


def test_speaker_asset_is_available_on_the_real_backend():
    import orrery_backend
    assert orrery_backend.PUBLIC_FILES['/conversation_speaker.js']=='conversation_speaker.js'


def test_recorded_model_reaches_the_reader_over_http(tmp_path,monkeypatch):
    from test_conversation_history import run_api
    async def scenario(client,url,reads):
        (tmp_path/'bound.jsonl').write_bytes(
            (json.dumps(dict(type='turn_context',payload=dict(model='gpt-6.1-sol',private='DO_NOT_EXPORT')))+'\n').encode()+record('Visible answer'))
        async with client.get(url+'/telemetry/conversation?agent=BoundAgent') as response:
            payload=await response.json()
            assert response.status==200
            assert payload['events'][0]['model']=='gpt-6.1-sol'
            assert 'DO_NOT_EXPORT' not in json.dumps(payload)
    run_api(tmp_path,monkeypatch,scenario)


@pytest.mark.parametrize('theme',['dark','light'])
def test_cross_message_selection_excludes_decorative_avatar_text(cockpit,theme):
    js,wait,client,_=prepare_speaker(cockpit,theme=theme)
    wait("speakerReader.querySelector('[data-event-id=second] .conversation-avatar .face img').style.display==='none'")
    selected=js("""(()=>{const first=speakerReader.querySelector('[data-event-id=first] .conversation-text'),second=speakerReader.querySelector('[data-event-id=second] .conversation-text'),r=document.createRange();r.setStart(first.firstChild,0);r.setEnd(second.firstChild,second.firstChild.length);getSelection().removeAllRanges();getSelection().addRange(r);return getSelection().toString()})()""")
    assert [line.strip() for line in selected.splitlines() if line.strip()]==[
        'First model','ReviewFixture','GPT-6.1-Sol','Changed model'],selected
    assert js("packets.filter(p=>p.type==='input')")==[]
