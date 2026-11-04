"""Recorded notification/send projection, generated native formats only."""
import json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import conversation_history as history
from test_conversation_providers import claude,dsh,line,row,make_db

NOTICE='ORRERY Mail notification: message from ParentFixture [high]: Review ready. Body (complete; no inbox fetch needed): Generated full message\nSecond line.'
PREVIEW='ORRERY Mail notification: message from ParentFixture [normal]: Short preview. Body preview: Generated excerpt ... Fetch inbox to read the rest.'
ARGS=dict(to=['ParentFixture'],subject='Generated report',body_md='Generated outgoing body',importance='normal',registration_token='HIDDEN_TOKEN',auth=dict(token='HIDDEN_AUTH'))
TOOL='mcp__orrery_mail__send_message'

def native(tmp_path,p,text=NOTICE,args=None,tool=TOOL):
    path=tmp_path/('state.db' if p=='hermes' else 'fixture.jsonl')
    if p=='codex':
        payload=dict(type='function_call',name=tool,arguments=json.dumps(args)) if args is not None else dict(type='message',role='user',content=[dict(type='input_text',text=text)])
        path.write_bytes(line(dict(type='response_item',payload=payload)));r=row(path,'codex')
    elif p=='claude':
        path.write_bytes(line(claude('assistant',[dict(type='tool_use',id='fixture',name=tool,input=args)]) if args is not None else claude('user',text)));r=row(path,'claude-code')
    elif p=='dsh':
        event=dsh('tool/call',dict(name=tool,arguments=json.dumps(args))) if args is not None else dsh('user/message',dict(source=dict(kind='user'),content=[dict(type='text',text=text)]))
        path.write_bytes(line(dict(type='session',version=4,id='fixture-session'))+line(event));r=row(path,'dsh')
    else:
        db=make_db(path)
        calls=json.dumps([dict(function=dict(name=tool,arguments=json.dumps(args)))]) if args is not None else None
        db.execute('INSERT INTO messages(session_id,role,content,tool_calls,timestamp) VALUES(?,?,?,?,?)',('fixture-session','assistant' if args is not None else 'user','' if args is not None else text,calls,1793775600));db.commit();db.close();r=row(path,'hermes')
    with history.open_reader(r) as reader:return reader.read_page()['events']

@pytest.mark.parametrize('provider',['codex','claude','dsh','hermes'])
@pytest.mark.parametrize('text,coverage',[(NOTICE,'complete'),(PREVIEW,'preview'),('ORRERY Mail notification: message from ParentFixture [normal]: No body. Please call fetch_inbox to read it.','unavailable')])
def test_recorded_notification_is_mail_with_coverage(tmp_path,provider,text,coverage):
    event=native(tmp_path,provider,text)[0]
    assert event['kind']=='mail'
    assert event['mail'][0]['direction']=='received'
    assert event['mail'][0]['sender']=='ParentFixture'
    assert event['mail'][0]['coverage']==coverage
    assert 'fetch_inbox' not in event['mail'][0]['body']

@pytest.mark.parametrize('provider',['codex','claude','dsh','hermes'])
def test_send_is_mail_allowlist_not_raw_arguments_or_confirmation(tmp_path,provider):
    event=native(tmp_path,provider,args=ARGS)[0]
    assert event['kind']=='mail'
    assert event['mail'][0]['direction']=='sent'
    assert event['mail'][0]['coverage']=='request'
    assert event['mail'][0]['recipients']==['ParentFixture']
    assert event['mail'][0]['subject']=='Generated report'
    assert event['mail'][0]['body']=='Generated outgoing body'
    assert 'HIDDEN' not in json.dumps(event)

@pytest.mark.parametrize('provider',['codex','claude','dsh','hermes'])
def test_ordinary_quoted_notification_and_unrelated_send_stay_ordinary(tmp_path,provider):
    assert native(tmp_path,provider,'Please discuss this example:\n'+NOTICE)[0]['kind']=='text'
    path=tmp_path/'other';path.mkdir()
    assert native(path,provider,args=ARGS,tool='mcp__another_service__send_message')[0]['kind']=='tool'


def test_codex_static_exec_mail_projection_rejects_quoted_and_computed_calls(tmp_path):
    code='await tools.mcp__orrery_mail__send_message('+json.dumps(ARGS)+');'
    def read(text):
        return history.codex_event(line(dict(type='response_item',payload=dict(type='custom_tool_call',name='functions.exec',input=text))),0)
    result=read(code)
    assert result['kind']=='tool' and result['mail'][0]['subject']=='Generated report'
    assert read(json.dumps(dict(code=code)))['mail'][0]['subject']=='Generated report'
    assert read(json.dumps(code))['kind']=='tool'
    assert read('await tools.mcp__orrery_mail__send_message(dynamicArgs)')['kind']=='tool'


def test_mail_projection_redacts_caps_and_never_exports_auth_or_results():
    from conversation_mail import sent,received,MAX_BODY
    event=dict(id='fixture',kind='tool',role='assistant',text=TOOL)
    value=dict(ARGS,importance=[],body_md='api_key=fixture-secret\n'+'z'*(MAX_BODY+100))
    result=sent(event,TOOL,value)
    mail=result['mail'][0]
    assert mail['importance']=='normal' and mail['truncated'] and len(mail['body'])<=MAX_BODY
    assert 'fixture-secret' not in json.dumps(result) and 'HIDDEN_' not in json.dumps(result)
    assert sent(event,['invalid'],value)==event
    assert sent(event,TOOL,[])==event
    user=dict(id='n',kind='text',role='user',text=NOTICE.replace('Generated full message','password=fixture-secret'))
    assert 'fixture-secret' not in json.dumps(received(user))


def test_mail_static_batch_is_bounded_and_quoted_tool_text_is_not_a_send():
    from conversation_mail import sent,MAX_ITEMS,MAX_TOTAL
    event=dict(id='fixture',kind='tool',role='assistant',text='functions.exec')
    args=dict(ARGS,body_md='x'*16384)
    code=';'.join('await tools.mcp__orrery_mail__send_message('+json.dumps(args)+')' for _ in range(10))
    result=sent(event,'functions.exec',code)
    assert 0<len(result['mail'])<=MAX_ITEMS
    assert sum(len(item['body']) for item in result['mail'])<=MAX_TOTAL
    assert sent(event,'functions.exec','// '+code)==event


def test_complete_recorded_body_keeps_full_text_within_existing_reader_limit(tmp_path):
    body='Generated long body. '*1500+'END_FULL_MAIL'
    event=native(tmp_path,'codex',NOTICE.split('Generated full message')[0]+body)[0]
    assert event['mail'][0]['body']==body and not event['mail'][0]['truncated']

@pytest.mark.parametrize('tool',['mcp__agentstack__send_message','mcp_agentstack_send_message'])
def test_bound_proxy_aliases_inside_static_exec_preserve_tool_projection(tool):
    from conversation_mail import sent
    event=dict(id='fixture',kind='tool',role='assistant',text='functions.exec')
    code='await tools.'+tool+'('+json.dumps(ARGS)+');'
    result=sent(event,'functions.exec',code)
    assert result['kind']=='tool' and result['text']=='functions.exec'
    assert result['mail'][0]['subject']==ARGS['subject']
    assert 'HIDDEN_' not in json.dumps(result)
