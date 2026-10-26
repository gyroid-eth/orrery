"""Opt-in pane terminal: finite snapshots and confirmed ACK batches.

Importing observes nothing. Existing cockpit manager/boundary supply targets;
no registration DB, launch binding, provider identity or fallback transport.
"""
from __future__ import annotations
import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import unicodedata

CONTRACT='orrery-mobile-pane-v1'
MAX_TEXT_BYTES=4096
MAX_JSON_BYTES=16384
MAX_CAPTURE_BYTES=65536
MAX_PREVIEW_BYTES=6144
NAME=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,95}\Z')
REVISION=re.compile(r'[a-f0-9]{64}\Z')
EPOCH=re.compile(r'[a-f0-9]{32}\Z')

def _integer(value,minimum=1):return type(value) is int and value>=minimum
class InputRefused(ValueError):pass

def _matches(pattern,value):return isinstance(value,str) and pattern.fullmatch(value) is not None

def encode_json(value):
    try:data=json.dumps(value,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (TypeError,ValueError,UnicodeError):raise InputRefused('input_json_invalid') from None
    if len(data)>MAX_JSON_BYTES:raise InputRefused('input_json_too_large')
    return data

def revision(value):return hashlib.sha256(encode_json(value)).hexdigest()

def terminal_text(lines):
    if not isinstance(lines,list) or not all(isinstance(x,str) for x in lines):raise InputRefused('preview_unavailable')
    text='\n'.join(lines[-40:]);original=text
    # Remove complete and unterminated OSC/DCS/CSI sequences. Never interpret
    # output as HTML, URLs, input, or instructions for the reader itself.
    text=re.sub(r'(?:\x1b\]|\x9d).*?(?:\x07|\x1b\\|\x9c|$)','',text,flags=re.S)
    text=re.sub(r'(?:\x1b[P^_]|[\x90\x98\x9e\x9f]).*?(?:\x1b\\|\x9c|$)','',text,flags=re.S)
    text=re.sub(r'(?:\x1b\[|\x9b)[0-?]*[ -/]*(?:[@-~]|$)','',text)
    text=re.sub(r'\x1b[ -/]*[0-~]?','',text)
    text=''.join(c for c in text if c=='\n' or unicodedata.category(c) not in {'Cc','Cf','Cs','Zl','Zp'})
    removed=text!=original;raw=text.encode('utf-8');shortened=len(lines)>40 or len(raw)>MAX_PREVIEW_BYTES
    if len(raw)>MAX_PREVIEW_BYTES:text=raw[-MAX_PREVIEW_BYTES:].decode('utf-8','ignore')
    return text,shortened,removed

def validate_text(value):
    if not isinstance(value,str) or not value or not value.strip():
        raise InputRefused('input_text_invalid')
    try: raw=value.encode('utf-8',errors='strict')
    except UnicodeError: raise InputRefused('input_text_invalid') from None
    forbidden='\u2028\u2029\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
    if (len(raw)>MAX_TEXT_BYTES or any(unicodedata.category(c) in {'Cc','Cs'} or c in forbidden for c in value)):
        raise InputRefused('input_text_invalid')
    return raw

@contextlib.asynccontextmanager
async def _held_admission(admission,deadline):
    """A cancelled validator can finish reading, but can never dispatch later.

    One worker owns its synchronous proof context. Its lock stays owned until
    the event-loop caller signals release in finally, including cancellation.
    Do not time out that ownership independently of the actual write interval.
    """
    loop=asyncio.get_running_loop(); ready=loop.create_future(); release=threading.Event()
    def publish(value=None,error=None):
        if ready.done(): return
        if release.is_set(): ready.cancel()
        elif error is not None: ready.set_exception(error)
        else: ready.set_result(value)
    def worker():
        try:
            with admission(deadline) as proof:
                loop.call_soon_threadsafe(publish,proof)
                release.wait()
        except Exception as error:
            loop.call_soon_threadsafe(publish,None,error)
            raise
    work=loop.run_in_executor(None,worker)
    cancelled=False
    try:
        proof=await asyncio.shield(ready)
        yield proof
    finally:
        release.set()
        while not work.done():
            try: await asyncio.shield(work)
            except asyncio.CancelledError: cancelled=True
        # Retrieve both exceptions even when the request disappeared while the
        # worker was acquiring its bounded lock. No detached write continuation.
        if ready.done() and not ready.cancelled(): ready.exception()
        if not work.cancelled(): work.result()
        if cancelled: raise asyncio.CancelledError

@contextlib.asynccontextmanager
async def _deadline(deadline):
    # Cockpit supports Python3.10, which predates asyncio.timeout_at.
    task=asyncio.current_task()
    timer=asyncio.get_running_loop().call_later(max(0,deadline-time.monotonic()),task.cancel)
    try: yield
    finally: timer.cancel()

async def confirmed_batch(bridge,pane_id,text,*,admission,valid,claim,deadline=None):
    """Return accepted/refused/unknown; only accepted means every tmux ACK.

    Unknown never authorizes retry. A completed ACK says nothing about the TUI
    reading its buffer or starting a model turn. The write lock covers fresh admission and every write, but not ACK waiting.
    External tmux writers and same-pane program changes remain outside it.
    """
    from control_server import make_tmux_command
    started=False; futures=[]; deadline=time.monotonic()+5 if deadline is None else deadline
    try:
        raw=validate_text(text)
        if not isinstance(pane_id,str) or not re.fullmatch(r'%[0-9]+',pane_id): return 'refused'
        if deadline<=time.monotonic() or deadline>time.monotonic()+5.01 or not valid(): return 'refused'
        commands=[b'\x1b[200~']+[raw[i:i+64] for i in range(0,len(raw),64)]+[b'\x1b[201~\r']
        incarnation=bridge._incarnation
        async with _deadline(deadline):
            async with bridge._write_lock:
                if not valid() or bridge.master_fd is None or bridge._closed: return 'refused'
                async with _held_admission(admission,deadline) as proof:
                    if (not valid() or time.monotonic()>=deadline or bridge._closed
                            or bridge.master_fd is None or bridge._incarnation!=incarnation
                            or proof['session']!=bridge.config.session
                            or proof['pane_id']!=pane_id or proof['incarnation']!=incarnation): return 'refused'
                    if not claim(): return 'refused'
                    for chunk in commands:
                        if not valid() or time.monotonic()>=deadline: raise InputRefused('input_cancelled')
                        future=asyncio.get_running_loop().create_future()
                        futures.append(future); bridge._pending_blocks.append(future)
                        args=['send-keys','-t',pane_id,'-H',*[f'{byte:02x}' for byte in chunk]]
                        # Conservative first-possible-byte boundary. _write_master
                        # may fail after a short write; its exception cannot prove
                        # that no bytes reached the existing control connection.
                        started=True
                        await bridge._write_master((make_tmux_command(args)+'\n').encode('ascii'))
            # Both locks have actually been released before waiting for ACKs.
            results=await asyncio.gather(*futures)
            return 'accepted' if all(result.ok for result in results) else 'unknown'
    except (Exception,asyncio.CancelledError):
        if started:
            bridge._abort_mobile_stream()
            return 'unknown'
        return 'refused'

def decode_json(data):
    if not isinstance(data,bytes) or len(data)>MAX_JSON_BYTES:
        raise InputRefused('input_json_invalid')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value: raise InputRefused('input_json_invalid')
            value[key]=item
        return value
    def constant(value): raise InputRefused('input_json_invalid')
    try:
        value=json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_constant=constant)
    except (ValueError,UnicodeError,RecursionError):
        raise InputRefused('input_json_invalid') from None
    if not isinstance(value,dict): raise InputRefused('input_json_invalid')
    return value

class OSObserver:
    """Only process metadata. No argv, environment, transcripts or credentials."""
    def parent_pid(self): return os.getppid()

    def process(self,pid):
        if not _integer(pid): return None
        try:
            if sys.platform == 'darwin':
                return self._darwin(pid)
            if sys.platform.startswith('linux'):
                directory = Path('/proc') / str(pid)
                before = directory.stat()
                text = (directory/'stat').read_text()
                left,right = text.index('('),text.rindex(')')
                fields = text[right+2:].split()
                if fields[0] not in {'R','S','D'}: return None
                boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                if not re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}',boot): return None
                if int(text[:left].strip()) != pid or not fields[19].isdigit() or int(fields[19]) <= 0: return None
                after = directory.stat()
                if (before.st_dev,before.st_ino,before.st_uid) != (after.st_dev,after.st_ino,after.st_uid): return None
                return dict(pid=int(text[:left].strip()),ppid=int(fields[1]),uid=after.st_uid,
                            comm=text[left+1:right],birth='linux:'+boot+':'+fields[19]+':'+str(after.st_ino))
        except (OSError,ValueError,IndexError,UnicodeError,AttributeError): pass
        return None

    @staticmethod
    def _darwin(pid):
        # Public macOS SDK sys/proc_info.h proc_bsdinfo / PROC_PIDTBSDINFO=3;
        # use kernel timeval, not ps lstart's second-resolution display.
        import ctypes as c
        class BSD(c.Structure):
            _fields_ = [(n,c.c_uint32) for n in ('flags','status','xstatus','pid','ppid','uid','gid','ruid','rgid','svuid','svgid','reserved')]+[
                ('comm',c.c_char*16),('name',c.c_char*32)]+[(n,c.c_uint32) for n in ('nfiles','pgid','jobc','tdev','tpgid')]+[
                ('nice',c.c_int32),('sec',c.c_uint64),('usec',c.c_uint64)]
        # Fail closed on another ABI instead of reading a shifted timestamp.
        if c.sizeof(BSD) != 136 or BSD.sec.offset != 120 or BSD.usec.offset != 128: return None
        system = c.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
        sysctl = system.sysctlbyname
        sysctl.argtypes = [c.c_char_p,c.c_void_p,c.POINTER(c.c_size_t),c.c_void_p,c.c_size_t]
        sysctl.restype = c.c_int
        boot = c.create_string_buffer(64); boot_size = c.c_size_t(c.sizeof(boot))
        if sysctl(b'kern.bootsessionuuid',boot,c.byref(boot_size),None,0) != 0: return None
        if boot_size.value != 37 or boot.raw[36:37] != b'\0': return None
        boot_id = boot.raw[:36].decode('ascii')
        if not re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}',boot_id): return None
        library = c.CDLL('/usr/lib/libproc.dylib',use_errno=True)
        fn = library.proc_pidinfo
        fn.argtypes = [c.c_int,c.c_int,c.c_uint64,c.c_void_p,c.c_int]; fn.restype = c.c_int
        info = BSD()
        if fn(pid,3,0,c.byref(info),c.sizeof(info)) != c.sizeof(info) or info.status not in {2,3}: return None
        if info.pid != pid or info.ppid == 0 or info.sec == 0 or info.usec >= 1000000: return None
        return dict(pid=info.pid,ppid=info.ppid,uid=info.uid,comm=bytes(info.comm).decode(),
                    birth='darwin:'+boot_id+':'+str(info.sec)+':'+str(info.usec))

class PaneResolver:
    """Fresh shared-helper admission plus kernel birth; no pure-legacy fallback."""
    def __init__(self,boundary,observer=None):
        self.boundary=boundary;self.observer=OSObserver() if observer is None else observer

    def read(self,bridge,pane_id,deadline):
        boundary=self.boundary;shared=boundary.shared;transport=boundary.transport
        if (shared is None or transport is None or shared.get('CONTRACT')!='orrery-tmux-target-v1'
                or bridge._closed or bridge.master_fd is None):raise InputRefused('input_helper_unavailable')
        start_incarnation=bridge._incarnation
        before=shared['validate_socket'](transport.path)
        proof=shared['legacy_admission'](transport,boundary.home,
            pane=pane_id,operation='input',deadline=deadline)
        shared['check_pinned_transport'](boundary.pin,proof)
        rows=proof.get('panes',[])
        if (proof.get('allowed') is not True or len(rows)!=1 or rows[0].get('pane_id')!=pane_id
                or rows[0].get('session')!=bridge.config.session):raise InputRefused('input_target_unavailable')
        row=rows[0]
        info=bridge.panes.get(pane_id)
        if (info is None or info.session_id!=row['session_id'] or not _integer(info.height)
                or info.height>10000):raise InputRefused('input_target_changed')
        def process(pid):
            if not _integer(pid):raise InputRefused('input_process_unavailable')
            value=self.observer.process(pid)
            if (not isinstance(value,dict) or value.get('pid')!=pid or value.get('uid')!=os.getuid()
                    or not isinstance(value.get('birth'),str) or not 1<=len(value['birth'])<=256):
                raise InputRefused('input_process_unavailable')
            return value
        server=process(proof['server_pid']);pane=process(row['pid'])
        after=shared['legacy_admission'](transport,boundary.home,
            pane=pane_id,operation='input',deadline=deadline)
        if (after!=proof or before!=shared['validate_socket'](transport.path)
                or process(server['pid'])!=server or process(pane['pid'])!=pane
                or bridge._incarnation!=start_incarnation or bridge._closed
                or bridge.master_fd is None or time.monotonic()>=deadline):raise InputRefused('input_target_changed')
        return dict(session=row['session'],session_id=row['session_id'],pane_id=pane_id,
                    pane_pid=pane['pid'],pane_birth=pane['birth'],server_pid=server['pid'],server_birth=server['birth'],
                    uid=os.getuid(),socket_identity=list(before),socket_path=proof['socket_path'],
                    transport=proof['transport'],incarnation=start_incarnation,height=info.height,width=info.width)

    @contextlib.contextmanager
    def admission(self,row,deadline):
        proof=self.read(row['bridge'],row['pane_id'],deadline)
        if proof!=row['proof']:raise InputRefused('input_target_changed')
        yield proof


class InputCoordinator:
    """One reader/owner scoped, bounded, memory-only pane/confirmation authority."""
    def __init__(self,resolver,get_bridge,*,enabled=False,clock=time.monotonic):
        self.resolver=resolver;self.get_bridge=get_bridge;self.enabled=enabled;self.clock=clock
        self.epoch=secrets.token_hex(16);self.choices={};self.intents={};self.busy=set();self.rates={};self.previews=set()

    def _finish(self,row,state):
        timer=row.pop('timer',None)
        if timer is not None:timer.cancel()
        row.update(state=state,text=None,descriptor=None,finished=self.clock())

    def _prune(self):
        now=self.clock()
        for key,row in tuple(self.choices.items()):
            if now>=row['expires']:del self.choices[key]
        for key,row in tuple(self.intents.items()):
            if row['state']=='prepared' and now>=row['expires']:self._finish(row,'expired')
            if row['state'] not in {'prepared','pending','dispatching'} and now-row['finished']>=600:del self.intents[key]
        for key,times in tuple(self.rates.items()):
            self.rates[key]=[t for t in times if now-t<60]
            if not self.rates[key]:del self.rates[key]

    def close(self):
        self.enabled=False;self.choices.clear()
        for row in self.intents.values():
            row['cancelled']=True
            if row['state']=='prepared':self._finish(row,'cancelled')

    @staticmethod
    def _public(row):
        return dict(contract=CONTRACT,epoch=row['epoch'],intent=row['intent'],target=dict(row['target']),
                    state='pending' if row['state']=='dispatching' else row['state'])

    def _reply(self,**value):
        result=dict(contract=CONTRACT,epoch=self.epoch,**value);encode_json(result);return result

    async def _choice(self,key,scope):
        row=self.choices.get(key) if _matches(REVISION,key) else None
        if row is None or row['scope']!=scope or self.clock()>=row['expires']:raise InputRefused('input_choice_unavailable')
        bridge=await self.get_bridge(row['name'])
        if (bridge is not row['bridge'] or bridge._incarnation!=row['incarnation'] or bridge._closed
                or row['pane_id'] not in bridge.panes):raise InputRefused('input_target_changed')
        return row

    async def request(self,operation,payload):
        fields={'capability':set(),'targets':{'name'},'preview':{'choice'},'prepare':{'choice','revision','text'},
                'commit':{'intent','confirmation'},'cancel':{'intent'},'status':{'intent'}}
        common={'contract','owner','reader_epoch'}|({'epoch'} if operation!='capability' else set())
        if (operation not in fields or not isinstance(payload,dict) or set(payload)!=common|fields[operation]
                or payload.get('contract')!=CONTRACT or not _matches(EPOCH,payload.get('reader_epoch'))):raise InputRefused('input_request_invalid')
        owner=payload.get('owner')
        if (not isinstance(owner,str) or not 1<=len(owner)<=254 or not owner.isascii()
                or any(ord(c)<=32 or ord(c)>=127 for c in owner)):raise InputRefused('input_request_invalid')
        self._prune();scope=(owner,payload['reader_epoch'])
        if operation=='capability':return self._reply(api=31,enabled=self.enabled,supported='legacy-managed-pane',ack='tmux-command-accepted')
        if payload['epoch']!=self.epoch:raise InputRefused('input_epoch_changed')
        if operation in {'targets','preview','prepare'} and not self.enabled:raise InputRefused('input_disabled')
        if operation=='targets':
            name=payload['name']
            if not _matches(NAME,name):raise InputRefused('input_target_invalid')
            bridge=await self.get_bridge(name)
            if not self.enabled:raise InputRefused('input_disabled')
            if (bridge is None or bridge._closed or bridge.master_fd is None or bridge.config.session!=name):raise InputRefused('input_target_unavailable')
            # Old catalog handles for this reader are retired; prepared intents
            # retain their independent immutable descriptor and original expiry.
            self.choices={k:v for k,v in self.choices.items() if v['scope']!=scope}
            available=max(0,128-len(self.choices));targets=[]
            for pane_id,info in sorted(bridge.panes.items())[:available]:
                if not re.fullmatch(r'%[0-9]+',pane_id):continue
                if not _integer(info.height) or info.height>10000:continue
                choice=secrets.token_hex(32)
                label=f'Window {info.window_index} · pane {info.pane_index}'
                # No paths, commands, process metadata or terminal content.
                label,_,_=terminal_text([label]);label=label[:96]
                target={'name':name,'pane_label':label,'choice':choice}
                self.choices[choice]=dict(scope=scope,name=name,bridge=bridge,pane_id=pane_id,
                    height=info.height,incarnation=bridge._incarnation,expires=self.clock()+30,
                    target=target,proof=None)
                try:self._reply(targets=targets+[target],truncated=True)
                except InputRefused:
                    del self.choices[choice];break
                targets.append(target)
            return self._reply(targets=targets,truncated=len(targets)<len(bridge.panes))
        if operation in {'preview','prepare'}:
            key=payload['choice'];row=await self._choice(key,scope)
            preview_key=(id(row['bridge']),row['incarnation'],row['pane_id'])
            if operation=='preview' and preview_key in self.previews:raise InputRefused('preview_busy')
            if row['proof'] is None and sum(v['proof'] is not None for v in self.choices.values())>=16:raise InputRefused('input_capacity')
            deadline=time.monotonic()+3
            if operation=='preview':self.previews.add(preview_key)
            try:
                proof=await asyncio.to_thread(self.resolver.read,row['bridge'],row['pane_id'],deadline)
                if (not self.enabled or self.clock()>=row['expires'] or self.choices.get(key) is not row
                        or row['proof'] is not None and row['proof']!=proof):raise InputRefused('input_target_changed')
                target=dict(row['target'],revision=revision(proof))
            except BaseException:
                if operation=='preview':self.previews.discard(preview_key)
                raise
            if operation=='preview':
                try:
                    result=await row['bridge'].capture_mobile_preview(row['pane_id'],proof['height'],deadline=deadline)
                    after=await asyncio.to_thread(self.resolver.read,row['bridge'],row['pane_id'],deadline)
                    if (not self.enabled or after!=proof or self.choices.get(key) is not row or self.clock()>=row['expires']
                            or await self.get_bridge(row['name']) is not row['bridge']):raise InputRefused('input_target_changed')
                    text,truncated,controls=terminal_text(result.lines)
                    value=self._reply(target=target,text=text,truncated=truncated,controls_removed=controls,
                        observed_at=int(time.time()),max_lines=40,max_bytes=MAX_PREVIEW_BYTES)
                    row['proof']=proof
                    # A foreground preview lease can renew. Prepared Review
                    # proof/text and its independent 30s expiry never renew.
                    row['expires']=self.clock()+30
                    return value
                finally:self.previews.discard(preview_key)
            validate_text(payload['text'])
            if (row['proof'] is None or not _matches(REVISION,payload['revision'])
                    or payload['revision']!=target['revision']):raise InputRefused('input_target_changed')
            self._prune()
            if len(self.intents)>=256 or sum(r['state'] in {'prepared','pending','dispatching'} for r in self.intents.values())>=16:raise InputRefused('input_capacity')
            intent=secrets.token_hex(32);confirmation=secrets.token_hex(32);now=self.clock()
            descriptor={k:row[k] for k in ('bridge','pane_id','proof','name','incarnation')}
            pending=dict(intent=intent,confirmation=confirmation,epoch=self.epoch,scope=scope,target=target,
                descriptor=descriptor,text=payload['text'],state='prepared',expires=now+30,cancelled=False,finished=now)
            self.intents[intent]=pending
            def expire():
                if pending['state']=='prepared':self._finish(pending,'expired')
                elif pending['state'] in {'pending','dispatching'}:pending['cancelled']=True
            pending['timer']=asyncio.get_running_loop().call_later(30,expire)
            return dict(self._public(pending),confirmation=confirmation,expires_in=30,text=payload['text'])
        intent=payload['intent'];row=self.intents.get(intent) if _matches(REVISION,intent) else None
        if row is None or row['scope']!=scope:raise InputRefused('input_intent_unavailable')
        if operation=='cancel':
            row['cancelled']=True
            if row['state']=='prepared':self._finish(row,'cancelled')
            return self._public(row)
        if operation=='status':return self._public(row)
        if not _matches(REVISION,payload['confirmation']) or not secrets.compare_digest(payload['confirmation'],row['confirmation']):raise InputRefused('input_confirmation_invalid')
        if row['state']!='prepared':return self._public(row)
        if not self.enabled:self._finish(row,'refused');return self._public(row)
        descriptor=row['descriptor'];key=(id(descriptor['bridge']),descriptor['incarnation'],descriptor['pane_id'])
        if key in self.busy:self._finish(row,'refused');return self._public(row)
        self.busy.add(key);row['state']='pending';claimed=False
        def valid():return self.enabled and not row['cancelled'] and self.clock()<row['expires'] and row['state'] in {'pending','dispatching'}
        def claim():
            nonlocal claimed
            if claimed or not valid():return False
            times=[t for t in self.rates.get(key,[]) if self.clock()-t<60]
            if len(times)>=6:return False
            claimed=True;self.rates[key]=times+[self.clock()];row['state']='dispatching';return True
        try:
            bridge=await self.get_bridge(descriptor['name'])
            if bridge is not descriptor['bridge'] or not valid():outcome='refused'
            else:
                outcome=await bridge.send_confirmed_input(descriptor['pane_id'],row['text'],
                    admission=lambda deadline:self.resolver.admission(descriptor,deadline),valid=valid,claim=claim,
                    deadline=time.monotonic()+min(5,max(0,row['expires']-self.clock())))
            self._finish(row,outcome if outcome in {'accepted','refused','unknown'} else 'unknown')
        except (Exception,asyncio.CancelledError):self._finish(row,'unknown' if claimed else 'refused')
        finally:row['text']=None;row['descriptor']=None;self.busy.discard(key)
        return self._public(row)

def install_routes(app,coordinator):
    """Install only the finite loopback protocol, with its own request boundary."""
    from aiohttp import web
    operations={'capability','targets','preview','prepare','commit','cancel','status'}
    headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
             'Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"}
    def reply(value,status=200):
        try:data=encode_json(value)
        except InputRefused:data=b'{"error":"input_response_too_large"}';status=503
        return web.Response(body=data,status=status,headers=headers,content_type='application/json')
    def admitted(request,operation):
        sock=request.transport.get_extra_info('sockname') if request.transport is not None else None
        if not sock or request.remote!='127.0.0.1' or request.method!='POST' or operation not in operations:
            return False
        if request.raw_path!=f'/_mobile/terminal/{operation}': return False
        expected=f'127.0.0.1:{sock[1]}'
        one=lambda key,value:request.headers.getall(key,[])==[value]
        if (not one('Host',expected) or not one('Origin','http://'+expected)
                or not one('X-ORRERY-Mobile-Contract',CONTRACT)
                or not one('Content-Type','application/json')): return False
        if any(request.headers.getall(key,[]) for key in ('Authority','Transfer-Encoding','Content-Encoding',
                'Upgrade','Expect','X-HTTP-Method-Override','X-Method-Override','X-HTTP-Method',
                'Forwarded','X-Forwarded-Host','X-Forwarded-Proto','Tailscale-User-Login')): return False
        lengths=request.headers.getall('Content-Length',[])
        return (len(lengths)==1 and re.fullmatch(r'[0-9]{1,5}',lengths[0]) is not None and 0<int(lengths[0])<=MAX_JSON_BYTES
                and request.headers.get('Sec-Fetch-Site','').lower() in {'','none','same-origin'})
    async def handler(request):
        operation=request.match_info['operation']
        if not admitted(request,operation): return reply({'error':'input_request_denied'},403)
        try:
            data=await asyncio.wait_for(request.content.readexactly(int(request.headers['Content-Length'])),5)
            payload=decode_json(data)
        except (Exception,asyncio.CancelledError):
            return reply({'error':'input_request_invalid'},400)
        try:
            return reply(await coordinator.request(operation,payload))
        except InputRefused:
            return reply({'error':'input_unavailable'},403)
        except Exception:
            return reply({'error':'input_unavailable'},503)
    app.router.add_route('*','/_mobile/terminal/{operation}',handler)
    async def shutdown(app):
        close=getattr(coordinator,'close',None)
        if close is not None:close()
    app.on_shutdown.append(shutdown)
    return coordinator
