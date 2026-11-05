"""Inert projection of recorded ORRERY notifications and send requests.

No Mail API, DB, inbox, credentials, acknowledgements or recipient discovery.
A recognized notification is recorded text, not proof of authenticated delivery.
"""
import json
import re
from conversation_artifacts import MAX_INPUT,static_calls

MAX_BODY=65536
MAX_ITEMS=8
MAX_TOTAL=131072
MAIL_TOOLS=frozenset({'mcp__orrery_mail__send_message','mcp__orrery-mail__send_message',
    'mcp_orrery_mail_send_message','mcp__agentstack__send_message','mcp_agentstack_send_message'})
HEADER=re.compile(r'\AORRERY Mail notification: message from ([A-Za-z][A-Za-z0-9_-]{0,95}) \[(low|normal|high|urgent)\]: ')
MARKERS=(('. Body (complete; no inbox fetch needed): ','complete'),('. Body preview: ','preview'),
         ('. Please call fetch_inbox to read it.','unavailable'))


def safe(value,limit):
    return value[:limit] if isinstance(value,str) else ''


def received(event):
    if event.get('kind')!='text' or event.get('role')!='user':return event
    text=event.get('text','')
    # Claude may wrap the hook's complete notification in a system-reminder.
    # Arbitrary preceding user prose/quotes are not classified as notifications.
    if text.startswith('<system-reminder>\n') and text.endswith('\n</system-reminder>'):
        text=text[len('<system-reminder>\n'):-len('\n</system-reminder>')]
    match=HEADER.match(text)
    if not match:return event
    rest=text[match.end():]
    found=[(rest.find(marker),marker,coverage) for marker,coverage in MARKERS if marker in rest]
    if not found:return event
    offset,marker,coverage=min(found)
    subject=rest[:offset]
    if not subject or len(subject)>1024:return event
    body=rest[offset+len(marker):]
    if coverage=='unavailable' and body.strip():return event
    if coverage=='preview':body=body.removesuffix(' ... Fetch inbox to read the rest.')
    mail=dict(direction='received',sender=match[1],recipients=[],subject=safe(subject,512),
        importance=match[2],coverage=coverage,body=safe(body,MAX_BODY),
        truncated=bool(event.get('truncated') or len(body)>MAX_BODY),source='recorded')
    return dict(event,kind='mail',text=mail['subject'],mail=[mail])


def call(name,arguments):
    """Only named fields from a qualified Mail call, never its auth/raw result."""
    if not isinstance(name,str) or name not in MAIL_TOOLS:return None
    if isinstance(arguments,str):
        if len(arguments)>MAX_INPUT:return None
        try:arguments=json.loads(arguments)
        except (ValueError,UnicodeError):return None
    if not isinstance(arguments,dict) or not isinstance(arguments.get('subject'),str):return None
    recipients=[]
    for key in ('to','cc','bcc','to_agent_ids','recipients'):
        values=arguments.get(key,[])
        for item in values[:24] if isinstance(values,list) else []:
            if isinstance(item,str):label=safe(item,160)
            elif type(item) is int and item>0:label='agent #'+str(item)
            elif isinstance(item,dict):
                label=safe(item.get('name') or item.get('agent_name'),160)
                if not label and type(item.get('agent_id')) is int:label='agent #'+str(item['agent_id'])
            else:continue
            if label and label not in recipients:recipients.append(label)
            if len(recipients)>=24:break
    importance=arguments.get('importance','normal')
    if not isinstance(importance,str) or importance not in {'low','normal','high','urgent'}:importance='normal'
    body=arguments.get('body_md')
    return dict(direction='sent',sender='',recipients=recipients[:24],subject=safe(arguments['subject'],512),
        importance=importance,coverage='request',body=safe(body,MAX_BODY),source='recorded',
        truncated=isinstance(body,str) and len(body)>MAX_BODY)


def sent(event,name,arguments):
    if not event or not isinstance(name,str):return event
    items=[];wrapper=name in {'functions.exec','exec'}
    if name in {'functions.exec','exec'}:
        code=arguments
        if isinstance(code,dict):code=code.get('code')
        if not isinstance(code,str) or len(code)>MAX_INPUT:return event
        # Ordinary exec traffic needs no JS-literal scan. Also accept the
        # structured {code: ...} form without unquoting arbitrary JS strings.
        names=tuple(name for name in MAIL_TOOLS if re.fullmatch(r'[A-Za-z_$][\w$]*',name))
        if not any('tools.'+name in code for name in names):return event
        if code.lstrip().startswith('{'):
            try:value=json.loads(code)
            except ValueError:value=None
            if isinstance(value,dict) and isinstance(value.get('code'),str):code=value['code']
        candidates=static_calls(code,names)
    else:candidates=[(name,arguments)]
    budget=MAX_TOTAL
    for name,value in candidates:
        item=call(name,value)
        if not item:continue
        if len(item['body'])>budget:item['body']=item['body'][:budget];item['truncated']=True
        budget-=len(item['body']);items.append(item)
        if len(items)>=MAX_ITEMS or budget<=0:break
    if not items:return event
    # An exec may also contain edits/read calls. Preserve its original tool
    # projection so the existing reference/diff extractor still decorates it.
    if wrapper:return dict(event,mail=items)
    return dict(event,kind='mail',text=' · '.join(item['subject'] for item in items)[:1024],mail=items)
