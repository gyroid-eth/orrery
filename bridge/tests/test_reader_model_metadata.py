"""Optional model metadata must stay bounded and never hide visible history."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import conversation_history as history
import conversation_readers as readers


def test_oversized_raw_model_is_rejected_before_stripping_or_scanning():
    class NoScan(str):
        def strip(self,*args):
            raise AssertionError('oversized model must not be stripped')
        def __iter__(self):
            raise AssertionError('oversized model must not be scanned')
    assert history.recorded_model(NoScan(' '*750000+'gpt-6.1-sol')) is None


@pytest.mark.parametrize('padding',[0,750000],ids=['valid','oversized'])
def test_model_is_validated_once_for_all_claude_text_blocks(monkeypatch,padding):
    checks=0
    validate=readers.recorded_model
    def checked(value):
        nonlocal checks
        checks+=1
        return validate(value)
    monkeypatch.setattr(readers,'recorded_model',checked)
    item=dict(type='assistant',sessionId='fixture-session',message=dict(role='assistant',
        model=' '*padding+'gpt-6.1-sol',content=[dict(type='text',text='answer') for _ in range(64)]))
    assert len(json.dumps(item).encode())<readers.MAX_RECORD
    events=[event for _,event in readers.normalize(item,'claude','fixture-session')]
    assert len(events)==64 and all(event['text']=='answer' for event in events)
    assert checks==1
    assert all(event.get('model')==('gpt-6.1-sol' if padding==0 else None) for event in events)


@pytest.mark.parametrize('direction',['latest','older','newer'])
def test_deep_optional_turn_metadata_does_not_hide_visible_messages(tmp_path,direction):
    path=tmp_path/'generated.jsonl'
    # Construct bytes directly: encoding a Python object this deep also recurses.
    metadata=b'{"type":"turn_context","payload":{"model":'+b'['*3000+b'"x"'+b']'*3000+b'}}\n'
    def record(number):
        return (json.dumps(dict(type='response_item',payload=dict(type='message',role='assistant',
            content=[dict(type='output_text',text='answer-'+str(number))])))+'\n').encode()
    path.write_bytes(metadata+b''.join(record(i) for i in range(100)))
    latest=history.read_codex_page(str(path))
    if direction=='latest':
        result=latest;expected=range(20,100)
    elif direction=='older':
        result=history.read_codex_page(str(path),before=latest['before']);expected=range(20)
    else:
        start=latest['after'].split(':')[0]+':0'
        result=history.read_codex_page(str(path),after=start,limit=200);expected=range(100)
    assert [event['text'] for event in result['events']]==['answer-'+str(i) for i in expected]
    assert all('model' not in event for event in result['events'])
