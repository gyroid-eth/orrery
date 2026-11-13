"""Only a single native paste wrapper is removed from human Claude prompts."""
import base64
import json
import os
from pathlib import Path

import pytest

from test_conversation_providers import claude, line
from test_conversation_queued import queued, native_bridge
from test_conversation_submissions import cockpit, prepare
from conversation_readers import normalize


TEXT = 'Reference: Fixture · assistant · 2026-11-13T04:10:00Z\nRecorded message: quote\n> Keep this part.\n\nPlease check this reference.'


@pytest.mark.parametrize('mode',['turn','queued'])
@pytest.mark.parametrize('blocks',[False,True])
@pytest.mark.parametrize('outside',['','\n\n'])
def test_single_paste_envelope_is_removed(mode,blocks,outside):
    wrapped=outside+'<pasted_content id="0c0d">\n'+TEXT+'\n</pasted_content id="0c0d">\n'
    content=[dict(type='text',text=wrapped)] if blocks else wrapped
    record=queued(content) if mode=='queued' else claude('user',content)
    event=normalize(record,'claude','fixture-session')[0][1]
    assert event['text']==TEXT
    assert event['kind']=='text' and event['role']=='user'


@pytest.mark.parametrize('text',[
    'Ordinary text\nwith blank lines\n\nunchanged.',
    'before <pasted_content id="x">\nbody\n</pasted_content id="x">',
    '<pasted_content id="x">\nbody\n</pasted_content id="x"> after',
    '<pasted_content id="x">\nbody\n</pasted_content id="y">',
    '<pasted_content id="x">\nbody\n</pasted_content>',
    '<pasted_content id="x">\na\n</pasted_content id="x"><pasted_content id="x">\nb\n</pasted_content id="x">',
    '<pasted_content id="x">\n<pasted_content id="y">nested</pasted_content id="y">\n</pasted_content id="x">',
    '<pasted_content id="x" extra="1">\nbody\n</pasted_content id="x">',
])
def test_non_envelope_or_mixed_text_is_unchanged(text):
    assert normalize(claude('user',text),'claude','fixture-session')[0][1]['text']==text


def test_inner_whitespace_is_preserved_and_assistant_text_is_literal():
    text='\n  body\n\n'
    wrapped='<pasted_content id="x">\r\n'+text+'\r\n</pasted_content id="x">'
    assert normalize(claude('user',wrapped),'claude','fixture-session')[0][1]['text']==text
    assert normalize(claude('assistant',wrapped),'claude','fixture-session')[0][1]['text']==wrapped


@pytest.mark.parametrize('mode',['turn','queued'])
def test_wrapped_native_record_reconciles_and_displays_without_tags(cockpit,tmp_path,monkeypatch,mode):
    js,wait,client=prepare(cockpit,'claude')
    js('sentText='+json.dumps(TEXT))
    timestamp=js('new Date(clock+1000).toISOString()')
    path=tmp_path/'history.jsonl'
    path.write_bytes(line(dict(claude('assistant','Ready for a reference.'),timestamp=js('new Date(clock-1000).toISOString()'))))
    with native_bridge(path,monkeypatch) as (url,calls):
        js('OrreryConversationSource.Source.prototype.read=async()=>{const r=await fetch('+json.dumps(url+'/telemetry/conversation?agent=ReviewFixture')+');return r.json()};currentAgents[0]={...currentAgents[0],program:"claude-code",provider:"anthropic",history_session_id:"fixture-session",transcript_path:"/fixture/claude.jsonl"};document.dispatchEvent(new Event("oc:agents"))')
        wait("reader.textContent.includes('Ready for a reference.')")
        js('promptInput.value=sentText;sendPrompt()')
        wait('receipts.length===1')
        assert js("reader.querySelectorAll('.conversation-submission').length")==1
        folder=os.environ.get('ORRERY_PASTED_CAPTURE_DIR')
        if folder:
            out=Path(folder);out.mkdir(parents=True,exist_ok=True)
            (out/(mode+'-awaiting.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
        wrapped=('\n\n' if mode=='turn' else '')+'<pasted_content id="0c0d">\n'+TEXT+'\n</pasted_content id="0c0d">'
        record=queued(wrapped,timestamp=timestamp) if mode=='queued' else dict(claude('user',wrapped),timestamp=timestamp)
        with path.open('ab') as stream:stream.write(line(record))
        js('conversationView.refresh()')
        wait("reader.querySelectorAll('.conversation-submission').length===0")
        assert js("reader.querySelector('.conversation-submission-dismiss')===null")
        assert '<pasted_content' not in js('reader.textContent')
        assert 'Recorded message: quote' in js('reader.textContent')
        if folder:
            js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            (out/(mode+'-matched.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
        assert calls
