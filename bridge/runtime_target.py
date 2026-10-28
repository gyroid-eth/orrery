"""Legacy cockpit adapter for Telemetry's single target admission boundary.

Global terminal protocol belongs to a later change. Missing/old helpers only
retain the old behavior when fixed-layout absence has been proved here.
"""
from __future__ import annotations

import asyncio
import os
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import stat
import subprocess
import threading
import time

# At most one roster interval; destructive operations never reuse a proof.
PANE_PROOF_SECONDS = 5.0


class TargetRefused(RuntimeError):
    pass


STARTUP_KEYS = ('AGENTSTACK_RUNTIME_MODE', 'AGENTSTACK_FRESH_CLIENT_CONTEXT',
    'ORRERY_FRESH_MAIL_INSTANCE_ID', 'AGENTSTACK_HOME', 'AGENTSTACK_PYTHON',
    'AGENTSTACK_CLIENT_CONFIG', 'AGENTSTACK_GLOBAL_SERVER_CONFIG')


def startup_environment(*, environ=None, config=None):
    """Read only installed literal settings; never load a binding or a DB."""
    env=dict(os.environ if environ is None else environ)
    config={} if config is None else config
    chosen=config.get('telemetry_home')
    if chosen is not None and (not isinstance(chosen,str) or not chosen.strip()):
        raise TargetRefused('FRESH_HOST_PREPARATION_REQUIRED')
    home=Path(env.get('AGENTSTACK_HOME') or chosen or Path(env.get('HOME',str(Path.home())))/'.agentstack')
    saved={};path=home/'env.sh'
    if path.exists() or path.is_symlink():
        reader=home/'hooks/project-context.sh'
        try:
            # Old/default cockpit installs may have only the legacy env file.
            # Parse the mode as literal data before permitting that absence;
            # a saved fresh selection must never fall back to legacy.
            if not reader.exists() and not reader.is_symlink():
                for line in path.read_text().splitlines():
                    words=shlex.split(line,comments=True)
                    if len(words)==2 and words[0]=='export' and words[1].startswith('AGENTSTACK_RUNTIME_MODE='):
                        saved['AGENTSTACK_RUNTIME_MODE']=words[1].split('=',1)[1]
                if env.get('AGENTSTACK_RUNTIME_MODE',saved.get('AGENTSTACK_RUNTIME_MODE','legacy'))=='fresh':raise ValueError
                mode=env.get('AGENTSTACK_RUNTIME_MODE',saved.get('AGENTSTACK_RUNTIME_MODE','legacy'))
                if mode not in {'legacy','global'}:raise ValueError
                return {key:env[key] for key in STARTUP_KEYS if key in env} | {'AGENTSTACK_RUNTIME_MODE':mode}
            stamps=[]
            for item in (path,reader):
                info=item.lstat()
                if (item.resolve()!=item or not stat.S_ISREG(info.st_mode)
                        or info.st_uid!=os.getuid() or info.st_mode&0o022):raise ValueError
                stamps.append((info.st_dev,info.st_ino,info.st_mtime_ns,info.st_ctime_ns,info.st_size))
            keys=(*STARTUP_KEYS,'AGENTSTACK_PORT')
            result=subprocess.run(['/bin/bash','-c',
                '. "$1"; shift; file="$1"; shift; for key do '
                'agentstack_installed_env_value "$key" "$file" --shell || exit 2; printf "\\n"; done',
                'cockpit-startup',str(reader),str(path),*keys],env=env,capture_output=True,text=True,timeout=10)
            if result.returncode:raise ValueError
            for line in result.stdout.splitlines():
                if not line:continue
                words=shlex.split(line)
                if len(words)!=2 or words[0]!='export' or '=' not in words[1]:raise ValueError
                key,value=words[1].split('=',1)
                if key not in keys or key in saved:raise ValueError
                saved[key]=value
            for item,expected in zip((path,reader),stamps):
                info=item.lstat()
                if expected!=(info.st_dev,info.st_ino,info.st_mtime_ns,info.st_ctime_ns,info.st_size):raise ValueError
        except (OSError,ValueError,subprocess.SubprocessError):
            raise TargetRefused('FRESH_STARTUP_SETTINGS_UNAVAILABLE') from None
    values={key:env[key] if key in env else saved[key] for key in STARTUP_KEYS if key in env or key in saved}
    mode=values.get('AGENTSTACK_RUNTIME_MODE','legacy')
    if mode not in {'legacy','global','fresh'}:raise TargetRefused('FRESH_CONTEXT_REQUIRED')
    values['AGENTSTACK_RUNTIME_MODE']=mode
    if mode=='fresh':
        if any(values.get(k) for k in ('AGENTSTACK_CLIENT_CONFIG','AGENTSTACK_GLOBAL_SERVER_CONFIG')):
            raise TargetRefused('FRESH_CONTEXT_REQUIRED')
        values['AGENTSTACK_HOME']=str(home)
        for key in ('AGENTSTACK_HOME','AGENTSTACK_FRESH_CLIENT_CONTEXT'):
            value=Path(values.get(key,''))
            if not value.is_absolute() or value.resolve()!=value:
                raise TargetRefused('FRESH_HOST_PREPARATION_REQUIRED')
        if not re.fullmatch(r'[a-f0-9]{32}',values.get('ORRERY_FRESH_MAIL_INSTANCE_ID','')):
            raise TargetRefused('FRESH_INSTANCE_REQUIRED')
        python=Path(values.get('AGENTSTACK_PYTHON',''))
        if not python.is_absolute() or not python.is_file() or not os.access(python,os.X_OK):
            raise TargetRefused('FRESH_HOST_PREPARATION_REQUIRED')
        if not env.get('ORRERY_DASHBOARD_URL'):
            port=env.get('AGENTSTACK_PORT') or saved.get('AGENTSTACK_PORT','8770')
            if not port.isdigit() or not 1024<=int(port)<=65535:raise TargetRefused('FRESH_STARTUP_SETTINGS_UNAVAILABLE')
            values['ORRERY_DASHBOARD_URL']='http://127.0.0.1:'+port
    if env.get('ORRERY_DASHBOARD_URL'):values['ORRERY_DASHBOARD_URL']=env['ORRERY_DASHBOARD_URL']
    return values


def startup_projection(*, environ=None, config=None):
    env=dict(os.environ if environ is None else environ)
    values=startup_environment(environ=env,config=config);env.update(values)
    identity={'runtime_mode':values['AGENTSTACK_RUNTIME_MODE']}
    if identity['runtime_mode']=='fresh':
        target=FreshTargetBoundary(env.get('TMUX_BIN','tmux'),environ=env)
        target.call({'operation':'catalog'})
        identity.update(mail_instance_id=target.instance,context_digest=target.host_pin['context_digest'],
                        host_epoch=target.host_pin['epoch'])
    return {'env':values,'identity':identity}


class FreshEffectProof:
    """A single consumer's bounded proof; never shared with another consumer."""
    def __init__(self,target,purpose,*,membership=None):
        if purpose not in {'input','capture'}:raise ValueError('invalid purpose')
        self.target=target;self.purpose=purpose;self.expires=0.0;self.closed=False
        self.lock=asyncio.Lock();self.generation=0;self.refresh=None;self.failed=False;self.failure=None
        self.membership=membership;self.timer=None;self.timer_task=None

    def _cancel_timer(self):
        if self.timer is not None:self.timer.cancel();self.timer=None
        if self.timer_task is not None:self.timer_task.cancel();self.timer_task=None

    def close(self):
        self.closed=True;self.expires=0.0;self.generation+=1
        self._cancel_timer()

    def _schedule_refresh(self,generation):
        self._cancel_timer()
        loop=asyncio.get_running_loop()
        def start():
            self.timer=None
            if self.closed or self.failed or self.generation!=generation:return
            async def refresh_idle():
                async with self.lock:
                    if not self.closed and not self.failed and self.generation==generation and self.refresh is None:
                        self.refresh=asyncio.create_task(self._refresh(generation))
            task=loop.create_task(refresh_idle());self.timer_task=task
            def done(completed):
                if self.timer_task is completed:self.timer_task=None
            task.add_done_callback(done)
        self.timer=loop.call_later(max(0,self.expires-2-time.monotonic()),start)

    async def _refresh(self,generation):
        started=time.monotonic()
        try:
            await asyncio.to_thread(self.target.admit,self.purpose,pane=self.target.pane_id)
            if time.monotonic()>=started+PANE_PROOF_SECONDS:
                raise TargetRefused('FRESH_TARGET_PROOF_EXPIRED')
            async with self.lock:
                if not self.closed and self.generation==generation:
                    self.expires=started+PANE_PROOF_SECONDS
                    self._schedule_refresh(generation)
        except Exception as exc:
            async with self.lock:
                if not self.closed and self.generation==generation:
                    self.expires=0.0;self.failed=True;self.generation+=1
                    self.failure=exc if isinstance(exc,TargetRefused) else TargetRefused('FRESH_TARGET_UNAVAILABLE')
                    self._cancel_timer()
        finally:
            async with self.lock:
                if self.refresh is asyncio.current_task():self.refresh=None

    async def check(self):
        async with self.lock:
            if self.closed:raise TargetRefused('FRESH_TARGET_VIEW_CHANGED')
            if self.failed:raise self.failure or TargetRefused('FRESH_TARGET_UNAVAILABLE')
            now=time.monotonic();generation=self.generation
            if self.refresh is None and (now>=self.expires or self.expires-now<=2):
                self.refresh=asyncio.create_task(self._refresh(generation))
            pending=self.refresh if now>=self.expires else None
        if pending is not None:
            await asyncio.shield(pending)
        async with self.lock:
            if self.failed:raise self.failure or TargetRefused('FRESH_TARGET_UNAVAILABLE')
            if self.closed or self.generation!=generation or time.monotonic()>=self.expires:
                raise TargetRefused('FRESH_TARGET_PROOF_EXPIRED')
            deadline=self.expires
        try:
            if self.membership is None:await asyncio.to_thread(self.target.membership)
            else:await self.membership(deadline=deadline)
        except BaseException:
            async with self.lock:
                self.expires=0.0;self.failed=True;self.failure=TargetRefused('FRESH_TARGET_UNAVAILABLE');self.generation+=1
                self._cancel_timer()
            raise
        async with self.lock:
            if self.failed:raise self.failure or TargetRefused('FRESH_TARGET_UNAVAILABLE')
            if self.closed or self.generation!=generation or time.monotonic()>=self.expires:
                raise TargetRefused('FRESH_TARGET_PROOF_EXPIRED')


class FreshTargetBoundary:
    """Trusted host wrapper, never a second credential or tmux resolver."""
    def __init__(self,binary,*,environ=None):
        self.binary=binary;self.environment=dict(os.environ if environ is None else environ)
        env=self.environment
        if (env.get('AGENTSTACK_RUNTIME_MODE')!='fresh' or not env.get('AGENTSTACK_FRESH_CLIENT_CONTEXT')
                or any(env.get(k) for k in ('AGENTSTACK_CLIENT_CONFIG','AGENTSTACK_GLOBAL_SERVER_CONFIG'))):
            raise TargetRefused('FRESH_CONTEXT_REQUIRED')
        self.instance=env.get('ORRERY_FRESH_MAIL_INSTANCE_ID','')
        self.truncated=False
        if not re.fullmatch(r'[a-f0-9]{32}',self.instance):raise TargetRefused('FRESH_INSTANCE_REQUIRED')
        root=Path(env.get('AGENTSTACK_HOME',''))
        python=Path(env.get('AGENTSTACK_PYTHON',''))
        self.wrapper=root/'bin/agentstack-runtime-client'
        if not root.is_absolute() or not python.is_absolute():raise TargetRefused('FRESH_HOST_PREPARATION_REQUIRED')
        try:
            info=self.wrapper.lstat()
            if (self.wrapper.resolve()!=self.wrapper or not stat.S_ISREG(info.st_mode)
                    or info.st_uid!=os.getuid() or info.st_mode&0o022 or not os.access(python,os.X_OK)):
                raise TargetRefused('FRESH_HOST_PREPARATION_REQUIRED')
        except OSError:raise TargetRefused('FRESH_HOST_PREPARATION_REQUIRED') from None
        try:
            helper = root/'bin/lib/runtime_tmux.py'
            info = helper.lstat()
            if (helper.resolve()!=helper or not stat.S_ISREG(info.st_mode)
                    or info.st_uid!=os.getuid() or info.st_mode&0o022):raise ValueError
            self.host_api=runpy.run_path(str(helper))
            self.host_path=self.host_api['fresh_host_path'](env['AGENTSTACK_FRESH_CLIENT_CONTEXT'])
        except (OSError,ValueError,KeyError,RuntimeError):raise TargetRefused('FRESH_HOST_PREPARATION_REQUIRED') from None
        self.host_lock=threading.Lock()
        self.host_pin=None
        self.host_socket=None

    def __str__(self):return str(self.binary)

    def call(self,payload):
        try:
            with self.host_lock:
                if self.host_pin is None:
                    self.host_socket, hello=self.host_api['fresh_host_call'](self.host_path,{'operation':'hello'})
                    if 'error' in hello:
                        reason=hello['error']
                        raise TargetRefused(reason if isinstance(reason,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',reason) else 'FRESH_HOST_UNAVAILABLE')
                    pin=hello.get('pin'); result=hello.get('result')
                    if (not isinstance(pin,dict) or set(pin)!={'contract','mail_instance_id','operator_id','generation','context_digest','epoch','wrapper_root'}
                            or pin['contract']!='orrery-fresh-host-v1' or pin['mail_instance_id']!=self.instance
                            or pin['wrapper_root']!=str(self.wrapper.parent.parent) or result!={'ok':True}
                            or type(pin['operator_id']) is not int or type(pin['generation']) is not int
                            or not all(isinstance(pin[k],str) and re.fullmatch(r'[a-f0-9]{64}',pin[k]) for k in ('epoch','context_digest'))):
                        raise TargetRefused('FRESH_HOST_RESPONSE_INVALID')
                    self.host_pin=pin
                _, reply=self.host_api['fresh_host_call'](self.host_path,dict(payload,pin=self.host_pin),expected_socket=self.host_socket)
            if 'error' in reply:
                reason=reply['error']
                raise TargetRefused(reason if isinstance(reason,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',reason) else 'FRESH_TARGET_UNAVAILABLE')
            if set(reply)!={'pin','result'} or reply['pin']!=self.host_pin:raise TargetRefused('FRESH_HOST_CHANGED')
            value=reply['result']
            if not isinstance(value,dict) or value.get('ok') is not True:raise TargetRefused('FRESH_HOST_RESPONSE_INVALID')
            if value.get('mail_instance_id')!=self.instance:raise TargetRefused('INSTANCE_MISMATCH')
            return value
        except TargetRefused:raise
        except (OSError,ValueError,KeyError,RuntimeError):raise TargetRefused('FRESH_HOST_UNAVAILABLE') from None

    def catalog(self):
        value=self.call({'operation':'catalog'})
        if (set(value)!={'ok','mail_instance_id','agents','truncated'} or not isinstance(value['agents'],list)
                or len(value['agents'])>128 or type(value['truncated']) is not bool):raise TargetRefused('FRESH_HOST_RESPONSE_INVALID')
        rows=[]
        self.truncated=value['truncated']
        for row in value['agents']:
            if (not isinstance(row,dict) or set(row)!={'session','mail_instance_id','mail_agent_id'}
                    or row['mail_instance_id']!=self.instance or type(row['mail_agent_id']) is not int or row['mail_agent_id']<=0
                    or not isinstance(row['session'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,95}',row['session'])):
                raise TargetRefused('FRESH_HOST_RESPONSE_INVALID')
            rows.append(row)
        return rows

    def resolve(self,session,ref=None):
        if ref is not None and (not isinstance(ref,dict) or set(ref)!={'mail_instance_id','mail_agent_id'}):
            raise TargetRefused('FRESH_TARGET_QUERY_INVALID')
        query={'session':session} if ref is None else dict(ref,session=session)
        if set(query)-{'session','mail_instance_id','mail_agent_id'}:raise TargetRefused('FRESH_TARGET_QUERY_INVALID')
        return FreshPaneBoundary(self,self.call(dict(operation='inspect',**query)))


class FreshPaneBoundary:
    """One immutable I/A/current/route, re-admitted before every effect."""
    def __init__(self,parent,proof):
        self.parent=parent;self.proof=proof
        try:
            self.name=proof['session'];self.revision=proof['revision']
            self.ref={k:proof[k] for k in ('mail_instance_id','mail_agent_id')}
            self.session_id=proof['route']['pane']['session_id'];self.pane_id=proof['route']['pane']['pane_id']
            self.prefix=proof['transport_argv'];self.binary=self.prefix[0]
            if (not re.fullmatch(r'\$[0-9]+',self.session_id) or not re.fullmatch(r'%[0-9]+',self.pane_id)
                    or not re.fullmatch(r'[a-f0-9]{64}',self.revision) or type(self.ref['mail_agent_id']) is not int
                    or self.ref['mail_instance_id']!=parent.instance or len(self.prefix)!=3 or self.prefix[1]!='-S'
                    or not Path(self.binary).is_absolute() or self.prefix[2]!=proof['route']['socket_path']):raise ValueError
        except (KeyError,TypeError,ValueError,IndexError):raise TargetRefused('FRESH_HOST_RESPONSE_INVALID') from None
        self.key='fresh-'+hashlib.sha256(json.dumps([self.ref,proof['current'],self.revision],sort_keys=True).encode()).hexdigest()
        self.wire_pane='fresh-'+self.key[6:]+'-'+self.pane_id[1:]
        self.history_key=self.key

    def __str__(self):return self.binary

    def env(self):
        env={k:v for k,v in self.parent.environment.items() if k not in {'TMUX','TMUX_PANE','LC_ALL'}}
        env['LC_CTYPE']='C.UTF-8';return env

    def allow_new_session(self):raise TargetRefused('FRESH_TARGET_CREATION_UNAVAILABLE')

    def membership(self):
        api=self.parent.host_api;row=self.proof['route']
        try:
            if self.parent.host_socket is None or api['fresh_host_identity'](self.parent.host_path)!=self.parent.host_socket:
                raise TargetRefused('FRESH_HOST_CHANGED')
            transport=api['Transport'](Path(row['socket_path']),binary=self.binary)
            if list(transport.identity)!=row['socket_identity']:
                raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
            actual=api['panes'](transport,pane=self.pane_id)
            if len(actual)!=1 or any(actual[0][key]!=value for key,value in row['pane'].items()):
                raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
            if api['fresh_host_identity'](self.parent.host_path)!=self.parent.host_socket:
                raise TargetRefused('FRESH_HOST_CHANGED')
        except TargetRefused:raise
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):
            raise TargetRefused('FRESH_TARGET_UNAVAILABLE') from None

    def control_membership_transport(self):
        """Validate endpoints without starting a client; the live control stream queries."""
        api=self.parent.host_api;row=self.proof['route']
        try:
            if self.parent.host_socket is None or api['fresh_host_identity'](self.parent.host_path)!=self.parent.host_socket:
                raise TargetRefused('FRESH_HOST_CHANGED')
            transport=api['Transport'](Path(row['socket_path']),binary=self.binary)
            if list(transport.identity)!=row['socket_identity']:
                raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
            return transport
        except TargetRefused:raise
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):
            raise TargetRefused('FRESH_TARGET_UNAVAILABLE') from None

    def check_control_membership(self,transport,lines):
        api=self.parent.host_api;row=self.proof['route']
        try:
            if len(lines)!=1:raise ValueError
            fields=lines[0].split('\t')
            if (len(fields)!=4 or re.fullmatch(r'\$[0-9]+',fields[0]) is None
                    or re.fullmatch(r'%[0-9]+',fields[2]) is None
                    or not fields[3].isdigit() or int(fields[3])<1):raise ValueError
            actual=dict(session_id=fields[0],session=fields[1],pane_id=fields[2],pid=int(fields[3]))
            if any(actual[key]!=value for key,value in row['pane'].items()):raise ValueError
            if api['validate_socket'](transport.path)!=transport.identity:raise ValueError
            if api['fresh_host_identity'](self.parent.host_path)!=self.parent.host_socket:
                raise TargetRefused('FRESH_HOST_CHANGED')
        except TargetRefused:raise
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):
            raise TargetRefused('FRESH_TMUX_TARGET_CHANGED') from None

    def admit(self,operation,*,session=None,pane=None,window=None,reuse=False):
        if session is not None and session not in {self.name,self.session_id}:raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
        if pane is not None and pane!=self.pane_id:raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
        if operation not in {'attach','capture','input','window'}:raise TargetRefused('FRESH_TARGET_OPERATION_UNAVAILABLE')
        current=self.parent.call(dict(operation='inspect',purpose='input' if operation=='input' else 'capture',
            expected=self.revision,**self.ref))
        if current!=self.proof:raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
        if window is not None:
            # Window policy is wider than a pane: allow it only if this exact
            # window contains the selected pane alone in the selected session.
            try:
                done=subprocess.run([*self.prefix,'list-panes','-s','-t',self.session_id,'-F',
                    '#{pane_id}\t#{window_id}'],capture_output=True,text=True,timeout=3,env=self.env())
                rows=[line.split('\t') for line in done.stdout.splitlines()]
                if any(len(r)!=2 or not re.fullmatch(r'%[0-9]+',r[0]) or not re.fullmatch(r'@[0-9]+',r[1]) for r in rows):raise ValueError
                own=[r for r in rows if len(r)==2 and r[0]==self.pane_id]
                if (done.returncode or len(own)!=1 or own[0][1]!=window
                        or [r for r in rows if len(r)==2 and r[1]==window]!=own):raise ValueError
            except (OSError,ValueError,subprocess.SubprocessError):raise TargetRefused('FRESH_WINDOW_TARGET_UNAVAILABLE') from None
        return current

    def command(self,args,*,session):
        target=args[args.index('-t')+1] if '-t' in args and args.index('-t')+1<len(args) else None
        if args[0]=='refresh-client' and '-A' in args:
            index=args.index('-A')+1
            if index>=len(args) or args[index] not in {self.pane_id+':'+action for action in ('on','off','continue','pause')}:
                raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
            return self.admit('capture',session=session,pane=self.pane_id)
        if args[0]=='refresh-client' and '-C' in args:
            value=args[args.index('-C')+1];match=re.fullmatch(r'(@[0-9]+):[0-9]+x[0-9]+',value)
            if match is None:raise TargetRefused('FRESH_TARGET_QUERY_INVALID')
            target=match[1]
        if args[0] in {'resize-window','set-option','show-window-options','refresh-client'}:
            if not isinstance(target,str) or not re.fullmatch(r'@[0-9]+',target):raise TargetRefused('FRESH_TARGET_QUERY_INVALID')
            return self.admit('window',session=session,window=target)
        if (args==['display-message','-p','-t',target,'#{window_width}\t#{window_height}']
                and isinstance(target,str) and re.fullmatch(r'@[0-9]+',target)):
            return self.admit('window',session=session,window=target)
        if args[0] in {'capture-pane','list-panes','display-message','list-clients','show-options'}:
            if target not in {None,self.name,self.session_id,self.pane_id}:raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
            return self.admit('capture',session=session,pane=self.pane_id)
        if args[0]=='send-keys':return self.admit('input',session=session,pane=target)
        raise TargetRefused('FRESH_TARGET_OPERATION_UNAVAILABLE')


class LegacyTargetBoundary:
    """One frozen endpoint per consumer, with bounded pane proofs and fresh destructive admission."""

    def __init__(self, binary, *, home=None, environ=None):
        self.binary = binary
        self._pin_lock = threading.Lock()  # ephemeral consumer pin, no lock file
        self.environment = dict(os.environ if environ is None else environ)
        self.home = Path(home or self.environment.get('AGENTSTACK_HOME') or Path.home() / '.agentstack')
        self.shared = None
        self.transport = None
        self.pin = None
        self._pane_proofs = {}
        self.validate = None
        self._settings_stamp = None
        self._settings_hint = False
        module = self.home / 'bin/lib/runtime_tmux.py'
        if module.exists() or module.is_symlink():
            try:
                info = module.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o022 or module.resolve() != module):
                    raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
                shared = runpy.run_path(str(module))
                if (shared.get('CONTRACT') != 'orrery-tmux-target-v1'
                        or not {'legacy-transport', 'legacy-target-admission', 'legacy-window-target-admission'} <= set(shared.get('CAPABILITIES', []))):
                    raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
                validator = runpy.run_path(str(module.with_name('schema_contract.py')))
                self.validate = validator['validate_schema']
                for key in ('legacy_transport', 'legacy_admission', 'result_schema', 'check_pinned_transport', 'global_proofs', 'REASONS', 'TargetError'):
                    if key not in shared:
                        raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
                self.shared = shared
            except (Exception, SystemExit):
                self.shared = None
        if self.shared is not None:
            try:
                self.transport = self.shared['legacy_transport'](binary=binary, environ=self.environment)
                self.pin = self.transport.public()
                self.validate({'contract':self.shared['CONTRACT'],'ok':True,**self.pin}, self.shared['result_schema']('legacy-transport'))
                self.prefix = self.transport.argv
            except (Exception, SystemExit) as exc:
                self._helper_failure(exc)
                self.shared = None
                self.prefix = self._legacy_bootstrap()
        else:
            self.prefix = self._legacy_bootstrap()

    def __str__(self):
        return str(self.binary)

    def env(self):
        if self.shared is None:
            return dict(self.environment)  # old bare-tmux endpoint semantics
        return {k: v for k, v in self.environment.items() if k not in ('TMUX', 'TMUX_PANE')}

    def _installed_hint(self):
        """Reuse the installed literal reader; never execute env.sh or parse it twice."""
        if self.shared is not None:
            try:
                values = self.shared['installed_hints'](self.home, time.monotonic()+5)
                return (values.get('AGENTSTACK_RUNTIME_MODE','legacy') not in ('','legacy')
                        or bool(values.get('AGENTSTACK_GLOBAL_SERVER_CONFIG'))
                        or bool(values.get('AGENTSTACK_CLIENT_CONFIG')))
            except (Exception, SystemExit):
                return True
        path = self.home / 'env.sh'
        if not path.exists() and not path.is_symlink():
            return False
        try:
            info = path.lstat()
            stamp = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
            if stamp == self._settings_stamp:
                return self._settings_hint
            reader = self.home / 'hooks/project-context.sh'
            reader_info = reader.lstat()
            if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(reader_info.st_mode)
                    or info.st_uid != os.getuid() or reader_info.st_uid != os.getuid()
                    or info.st_mode & 0o022 or reader_info.st_mode & 0o022
                    or path.resolve() != path or reader.resolve() != reader):
                return True
            result = subprocess.run(['/bin/bash', '-c',
                '. "$1"; for key in AGENTSTACK_RUNTIME_MODE AGENTSTACK_GLOBAL_SERVER_CONFIG AGENTSTACK_CLIENT_CONFIG; do '
                'agentstack_installed_env_value "$key" "$2" --shell || exit 2; printf "\\n"; done',
                'runtime-target-settings', str(reader), str(path)],
                capture_output=True, text=True, timeout=5, env=self.env())
            if result.returncode:
                return True
            values = {}
            for line in result.stdout.splitlines():
                if not line:
                    continue
                tokens = shlex.split(line)
                if len(tokens) != 2 or tokens[0] != 'export' or '=' not in tokens[1]:
                    return True
                name, value = tokens[1].split('=', 1)
                if name in values:
                    return True
                values[name] = value
            hint = (values.get('AGENTSTACK_RUNTIME_MODE', 'legacy') not in ('', 'legacy')
                    or bool(values.get('AGENTSTACK_GLOBAL_SERVER_CONFIG'))
                    or bool(values.get('AGENTSTACK_CLIENT_CONFIG')))
            after = path.lstat()
            if stamp != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size):
                return True
            self._settings_stamp, self._settings_hint = stamp, hint
            return hint
        except (OSError, ValueError, subprocess.SubprocessError):
            return True

    def global_hint(self):
        # This is missing-helper admission, not a runtime mode selector.
        paths = [self.home / 'clients', self.home / 'runtime-client.json']
        for key in ('AGENTSTACK_CLIENT_CONFIG', 'AGENTSTACK_GLOBAL_SERVER_CONFIG'):
            if self.environment.get(key):
                return True
        if self.environment.get('AGENTSTACK_RUNTIME_MODE', 'legacy') not in ('', 'legacy'):
            return True
        try:
            return any(p.exists() or p.is_symlink() for p in paths) or self._installed_hint()
        except OSError:
            return True

    def _legacy_bootstrap(self):
        # Old installs retain their original tmux behavior. Do not copy the
        # shared endpoint resolver or invent a second socket/PID proof.
        inherited = self.environment.get('TMUX', '').rsplit(',', 2)[0]
        if Path(inherited).parent.resolve() == Path('/tmp').resolve() / ('orrery-tmux-' + str(os.getuid())):
            raise TargetRefused('GLOBAL_TMUX_LEGACY_CONSUMER_REFUSED')
        return [self.binary]

    def _fallback_admit(self):
        if self.global_hint():
            raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')

    def _helper_failure(self, exc):
        # Only the shared helper defines domain refusals. Broken/old helpers
        # use the same negative admission as a missing helper.
        if self.shared is not None and isinstance(exc, self.shared['TargetError']):
            reason = str(exc)
            if self.shared['REASONS'].get(reason) in ('target', 'transport'):
                raise TargetRefused(reason) from exc
        if self.global_hint():
            raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE') from exc

    def allow_new_session(self):
        # No target exists yet. Establish placement completeness before the
        # atomic tmux new-session; never create first and discover uncertainty.
        if self.shared is None:
            if self.global_hint():
                raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
            return
        try:
            self.shared['global_proofs'](self.home)
        except (Exception, SystemExit) as exc:
            self._helper_failure(exc)

    def admit(self, operation, *, session=None, pane=None, window=None, reuse=False):
        if self.shared is None:
            self._fallback_admit()
            return  # Proven pure legacy; preserve its existing target rules.
        try:
            key = (session, pane, window)
            cacheable = reuse and window is None and operation in ('input', 'capture')
            # The cheap shared pane query validates the pinned socket inode
            # on both sides. PID/membership changes invalidate a cached proof.
            if cacheable and self.transport.identity is not None:
                rows = self.shared['panes'](self.transport, session=session, pane=pane)
                with self._pin_lock:
                    cached = self._pane_proofs.get(key)
                if cached and time.monotonic() < cached[0] and rows == cached[1]:
                    return {**cached[2], 'operation': operation}
            proof_started = time.monotonic()
            refreshed = self.shared['legacy_transport'](binary=self.binary, environ=self.environment)
            public = refreshed.public()
            self.validate({'contract':self.shared['CONTRACT'],'ok':True,**public},
                          self.shared['result_schema']('legacy-transport'))
            with self._pin_lock:
                self.pin = self.shared['check_pinned_transport'](self.pin, public)
                if self.transport.identity is None:
                    self.transport = refreshed
                transport = self.transport
            selector = {'window':window} if window is not None else {'session':session,'pane':pane}
            value = self.shared['legacy_admission'](transport, self.home,
                **selector, operation=operation)
            self.validate(value, self.shared['result_schema']('legacy-target'))
            with self._pin_lock:
                self.shared['check_pinned_transport'](self.pin, value)
                if cacheable:
                    rows = [{k:v for k,v in row.items() if k != 'process_start'} for row in value['panes']]
                    # Retain only active, bounded proofs in consumer memory.
                    now = time.monotonic()
                    self._pane_proofs = {k:v for k,v in self._pane_proofs.items() if v[0] > now}
                    self._pane_proofs[key] = (proof_started + PANE_PROOF_SECONDS, rows, value)
                else:
                    self._pane_proofs.clear()
            return value
        except (Exception, SystemExit) as exc:
            self._helper_failure(exc)
            self._fallback_admit()
            return  # Helper unavailable, and fixed layout proves pure legacy.


def admit_creation(binary):
    if isinstance(binary, (LegacyTargetBoundary,FreshPaneBoundary)):
        binary.allow_new_session()


def require_target(binary, operation, *, session=None, pane=None):
    if isinstance(binary, (LegacyTargetBoundary,FreshPaneBoundary)):
        return binary.admit(operation, session=session, pane=pane)


def tmux_argv(binary, *args):
    """Transport is a value, never arguments hidden in an executable wrapper."""
    return [*(binary.prefix if isinstance(binary, (LegacyTargetBoundary,FreshPaneBoundary)) else [binary]), *args]


def tmux_env(binary):
    return {'env': binary.env()} if isinstance(binary, (LegacyTargetBoundary,FreshPaneBoundary)) else {}


def admit_command(binary, args, *, session):
    if isinstance(binary,FreshPaneBoundary):return binary.command(args,session=session)
    if not isinstance(binary, LegacyTargetBoundary):
        return  # Private pure helpers retain their legacy unit-test interface.
    target = None
    if '-t' in args and args.index('-t') + 1 < len(args):
        target = args[args.index('-t') + 1]
    if args[0] == 'refresh-client' and '-C' in args:
        index = args.index('-C') + 1
        size = args[index] if index < len(args) else ''
        match = re.fullmatch(r'(@[0-9]+):[0-9]+x[0-9]+', size)
        if match is None:
            raise TargetRefused('TMUX_TARGET_INPUT_INVALID')
        target = match[1]
    operation = ('split' if args[0] == 'split-window' else
                 'close' if args[0] == 'kill-pane' else
                 'kill-session' if args[0] == 'kill-session' else
                 'capture' if args[0] in ('capture-pane', 'list-panes', 'display-message') else 'input')
    if isinstance(target,str) and re.fullmatch(r'@[0-9]+',target):
        # A moved/linked window is not the bridge's configured session. Check
        # every current pane in the actual window; never reuse an old proof.
        binary.admit(operation, window=target)
    elif isinstance(target, str) and re.fullmatch(r'%[0-9]+', target):
        binary.admit(operation, pane=target, reuse=True)
    else:
        binary.admit(operation, session=session, reuse=True)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--startup-json']:
        raise SystemExit('FRESH_STARTUP_ARGUMENTS_INVALID')
    try:
        path=Path.home()/'.orrery/config.json'
        try:
            settings=json.loads(path.read_text())
            if not isinstance(settings,dict):settings={}
        except (OSError,ValueError):settings={}
        print(json.dumps(startup_projection(config=settings),separators=(',',':')))
    except (TargetRefused,OSError,ValueError,KeyError,TypeError) as exc:
        print(str(exc) if isinstance(exc,TargetRefused) else 'FRESH_STARTUP_UNAVAILABLE',file=sys.stderr)
        raise SystemExit(2)
