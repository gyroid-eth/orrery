"""Generated image labels reconcile receipts without rewriting recorded prose."""
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from test_conversation_submissions import cockpit, prepare
from test_conversation_input_images import png, decorate
from test_conversation_providers import row, line


def native_record(tmp_path, provider, text, stamp, *, image=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    content = [dict(type='input_text' if provider == 'codex' else 'text', text=text)]
    if image:
        data = png()
        if provider == 'dsh':
            digest = hashlib.sha256(data).hexdigest()
            path = tmp_path/'attachments'/'v1'/'objects'/digest[:2]/digest
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            content.append(dict(type='image', attachment=dict(attachmentId='sha256:'+digest,
                                mediaType='image/png', width=640, height=400, bytes=len(data))))
        elif provider == 'claude':
            content.append(dict(type='image', source=dict(type='base64', media_type='image/png',
                                                         data=base64.b64encode(data).decode())))
        else:
            content.append(dict(type='input_image', image_url='data:image/png;base64,'+base64.b64encode(data).decode()))
    path = tmp_path/('session.v4.jsonl' if provider == 'dsh' else provider+'.jsonl')
    timestamp = datetime.fromtimestamp(stamp/1000, timezone.utc).isoformat().replace('+00:00', 'Z')
    if provider == 'dsh':
        path = tmp_path/'sessions'/'project'/'fixture-session'/'session.v4.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [dict(type='session', version=4, id='fixture-session', cwd=str(tmp_path)),
                   dict(type='user/message', seq=1, time=stamp, surfaceOp='append',
                        data=dict(source=dict(kind='user'), content=content))]
    elif provider == 'claude':
        records = [dict(type='user', sessionId='fixture-session', cwd=str(tmp_path), timestamp=timestamp,
                        message=dict(role='user', content=content))]
    else:
        records = [dict(type='session_meta', payload=dict(cwd=str(tmp_path))),
                   dict(type='response_item', timestamp=timestamp, payload=dict(type='message', role='user', content=content))]
    path.write_bytes(b''.join(line(record) for record in records))
    _, events = decorate(row(path, 'claude-code' if provider == 'claude' else provider))
    event = next(event for event in events if event.get('text', '').startswith(text))
    # These separate native fixture files represent successive appended rows.
    event['id'] = tmp_path.name+':'+event['id']
    return event


def publish(js, wait, event, provider):
    js('window.imageRecord='+json.dumps(event)+';OrreryConversationSource.Source.prototype.read=async()=>({provider:'+
       json.dumps(provider)+',events:[oldRecord,imageRecord],after:"image-tail"});conversationView.refresh()')
    wait('reader.querySelectorAll(".conversation-submission").length===0')


def test_native_image_prefix_reconciles_but_typed_labels_stay_literal(cockpit, tmp_path):
    js, wait, client = prepare(cockpit, 'dsh')
    js('OrreryConversationSource.Source.prototype.reference=async()=>('+json.dumps(dict(kind='image', mime='image/png',
       data=base64.b64encode(png()).decode(), width=640, height=400))+')')
    # Both native harnesses record this same prefix. Use their real adapters and
    # reference decoration, rather than assigning image provenance in the UI.
    for index, provider in enumerate(['dsh', 'claude']):
        js('sentText='+json.dumps('ガリー2' if index==0 else '[Image #7] ガリー3')+';promptInput.value=sentText;sendPrompt()')
        wait('receipts.length==='+str(index+1))
        recorded = '[Image #18] '+js('sentText')
        event = native_record(tmp_path/provider, provider, recorded, js('clock+1000'))
        if provider=='claude':assert event['input_image_count']==1
        else:assert event['input_images'] and event['references'][0]['input_image']
        publish(js, wait, event, provider)
        assert js('reader.querySelector("[data-event-id="+CSS.escape(imageRecord.id)+"] .conversation-text").textContent') == recorded
    capture = os.environ.get('ORRERY_IMAGE_MARKER_CAPTURE')
    if capture:
        wait('reader.querySelector(".conversation-inline-thumbnail")?.naturalWidth>0')
        Path(capture).write_bytes(base64.b64decode(client.call('Page.captureScreenshot', format='png')['data']))
    # No attachment: a literal prefix must not turn a different recorded input
    # into a match for the unprefixed send.
    js('clock+=2000;sentText="literal label example";promptInput.value=sentText;sendPrompt()')
    wait('receipts.length===3')
    event = native_record(tmp_path/'literal', 'dsh', '[Image #18] literal label example', js('clock+1000'), image=False)
    js('window.literalRecord='+json.dumps(event)+';OrreryConversationSource.Source.prototype.read=async()=>({provider:"dsh",events:[literalRecord],after:"literal"});conversationView.refresh()')
    wait('reader.querySelector(".conversation-submission")?.dataset.state==="unmatched"')
    assert js('reader.querySelectorAll(".conversation-submission").length') == 1


def test_codex_synthetic_attachment_suffix_reconciles_without_removing_literal_text(cockpit, tmp_path):
    js, wait, client = prepare(cockpit, 'codex')
    js('sentText="Inspect this image\\n[image attachment]";promptInput.value=sentText;sendPrompt()')
    wait('receipts.length===1')
    event = native_record(tmp_path, 'codex', js('sentText'), js('clock+1000'))
    assert event['text'] == js('sentText')+'\n[image attachment]'
    publish(js, wait, event, 'codex')
    assert js('reader.querySelector("[data-event-id="+CSS.escape(imageRecord.id)+"] .conversation-text").textContent') == event['text']


def test_plain_prompt_still_reconciles_exactly(cockpit):
    js, wait, client = prepare(cockpit, 'dsh')
    for index, text in enumerate(['An ordinary prompt', '[Image #18] typed by the person']):
        js('sentText='+json.dumps(text)+';promptInput.value=sentText;sendPrompt()')
        wait('receipts.length==='+str(index+1))
        js('newRecord={...newRecord,id:"plain-'+str(index)+'",text:sentText};turnDone=true;conversationView.refresh()')
        wait('reader.querySelectorAll(".conversation-submission").length===0')
        assert js('reader.querySelector("[data-event-id=plain-'+str(index)+'] .conversation-text").textContent') == text
