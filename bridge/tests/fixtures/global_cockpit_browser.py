"""Synthetic browser fixture: real cockpit admission, fake provider-free upstream."""
import asyncio,json,os,runpy,shutil,tempfile,signal
from pathlib import Path
from aiohttp import web
import sys
BRIDGE=Path(__file__).resolve().parents[2]
TELEMETRY=Path(os.environ.get('ORRERY_TEST_TELEMETRY_ROOT',BRIDGE.parent/'.telemetry'))
sys.path.insert(0,str(BRIDGE))
info_path=Path(sys.argv[1])
root=Path(tempfile.mkdtemp(prefix='rh6c-browser-')).resolve();home=root/'agentstack';home.mkdir(mode=0o700);(home/'dashboard').mkdir()
shutil.copy2(TELEMETRY/'dashboard/http_operator.py',home/'dashboard/http_operator.py')
helper=runpy.run_path(str(home/'dashboard/http_operator.py'));helper['configure'](home);token=helper['read_capability'](home)
os.environ.update(HOME=str(root),AGENTSTACK_HOME=str(home),AGENTSTACK_RUNTIME_MODE='global',AGENTSTACK_GLOBAL_SERVER_CONFIG=str(root/'server-config.json'),AGENTSTACK_LABEL_PREFIX='test-rh6c')
import orrery_backend as backend
from global_cockpit import GlobalCockpit
rows=[dict(agent_id=i,name=n,program='codex',model='fixture',task_description='Synthetic fixture',retired_at=None) for i,n in [(1,'Alpha'),(2,'Beta')]]
messages=[dict(id=i,sender={'agent_id':1 if i%2 else 2,'name':'Alpha' if i%2 else 'Beta'},to=[{'agent_id':2 if i%2 else 1,'name':'Beta' if i%2 else 'Alpha'}],cc=[],bcc=[],subject='A long synthetic subject · '+('detail '*15),body_md='Synthetic body\n'+('Long text for the narrow rail. '*30),created_ts='2026-10-12T10:00:00Z',reply_to=(i-1 if i>1 else None),history_incomplete=i==1) for i in range(1,7)]
async def probe(self):return dict(binding={'expected_server_instance_id':'fixture','candidate_generation':'1','authority_epoch':'1'},telemetry_api=18,capabilities={'global_runtime_observation':1,'operator_session':1})
GlobalCockpit.probe=probe
class Manager:
 def __init__(self,*a):pass
 async def start(self):pass
 async def close(self):pass
 async def disconnect(self,*a):pass
 async def handle_message(self,*a):pass
backend.SessionBridgeManager=Manager;backend.list_tmux_sessions=lambda *a:[]
async def upstream(r):
 if r.path in ('/','/network/') :return web.Response(text='Fixture network',content_type='text/html')
 if r.path.startswith('/api/'):
  if r.path=='/api/agents':value={'data':{'items':rows,'next_before_agent_id':None}}
  elif r.path=='/api/runtime-observations':value={'items':[dict(agent_id=1,liveness='live',session_count=1,act_state='work',ctx_used=42,parent_state='none')]}
  elif r.path=='/api/instruction-migration':value={'data':dict(disk_state='needs_review',session_state='unknown',findings=[dict(source_path='/fixture/CLAUDE.md',kind='legacy',cleanup_argv=['agentstack-instruction-block','--remove-legacy-block','--path','/fixture/CLAUDE.md'])])}
  elif r.path=='/api/quotas':value={'providers':[{'provider':'codex','status':'ok','buckets':[{'label':'5h','remaining_percent':75}]}]}
  elif r.path=='/api/mail/conversation':value={'data':{'items':[dict(source_message_ids=list(range(1,7)),origin={'source_provenance':'fixture'})],'next_cursor':None}}
  elif r.path=='/api/mail/message':value={'data':messages[int(r.query['id'])-1]}
  else:value={'data':{'items':messages,'next_cursor':None}}
  return web.json_response(value)
 p=(TELEMETRY/'dashboard')/r.path.lstrip('/')
 if p.is_file():return web.FileResponse(p)
 return web.Response(status=404)
async def main():
 app=web.Application();app.router.add_route('*','/{tail:.*}',upstream);runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();backend.DASHBOARD_URL='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
 cr=web.AppRunner(backend.create_app());await cr.setup();cs=web.TCPSite(cr,'127.0.0.1',0);await cs.start();port=cs._server.sockets[0].getsockname()[1]
 info_path.write_text(json.dumps({'url':f'http://127.0.0.1:{port}/cockpit.html','token':token,'root':str(root)}));info_path.chmod(0o600);print('synthetic fixture ready',flush=True)
 stop=asyncio.Event();loop=asyncio.get_running_loop()
 for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
 try:await stop.wait()
 finally:
  await cr.cleanup();await runner.cleanup();shutil.rmtree(root)
asyncio.run(main())
