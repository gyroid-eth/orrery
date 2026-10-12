#!/usr/bin/env python3
"""Use the installed operator proof and return non-secret cockpit ownership."""
import argparse
import json
import os
from pathlib import Path
import runpy
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


def probe(service, port):
    home=Path(os.environ['AGENTSTACK_HOME'])
    helper=runpy.run_path(str(home/'dashboard/http_operator.py'))
    origin=os.environ['ORRERY_DASHBOARD_URL'].rstrip('/')
    result=helper['probe'](home,service=service,telemetry_url=origin,
        cockpit_port=port,config_path=os.environ['AGENTSTACK_GLOBAL_SERVER_CONFIG'])
    if service=='cockpit':
        origin='http://127.0.0.1:'+str(port)
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise RuntimeError('UPSTREAM_REDIRECT_REFUSED')
        request=Request(origin+'/telemetry/health',headers={
            'Authorization':'Bearer '+helper['read_capability'](home),'Origin':origin})
        with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=5) as reply:
            result=json.loads(reply.read(1048577))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service',choices=('telemetry','cockpit'))
    parser.add_argument('--port',type=int,default=8791)
    args=parser.parse_args()
    try:
        print(json.dumps(probe(args.service,args.port)));return 0
    except Exception as exc:
        print(json.dumps({'ok':False,'reason':str(exc) if isinstance(exc,RuntimeError) else 'COCKPIT_GLOBAL_CAPABILITY_REQUIRED'}));return 1

if __name__=='__main__':raise SystemExit(main())
