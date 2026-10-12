"""Connect to an operator-supplied CDP service; never launch a browser."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.theme_axis_browser_test import _WebSocket

CDP=os.environ.get('ORRERY_CDP_URL')
pytestmark=pytest.mark.skipif(not CDP,reason='set ORRERY_CDP_URL to an existing isolated browser service')


def test_global_browser_reply_flow_narrow_themes_and_lock(tmp_path):
    info=tmp_path/'fixture.json'
    process=subprocess.Popen([sys.executable,str(ROOT/'bridge/tests/fixtures/global_cockpit_browser.py'),str(info)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    connection=None;page=None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        deadline=time.monotonic()+25
        while not info.exists():
            assert process.poll() is None,'fixture exited before readiness'
            assert time.monotonic()<deadline,'fixture readiness timeout'
            time.sleep(.05)
        state=json.loads(info.read_text())
        with opener.open(CDP+'/json/version',timeout=3) as response:version=json.load(response)
        browser=_WebSocket(version['webSocketDebuggerUrl'])
        try:page=browser.call('Target.createTarget',url='about:blank')['targetId']
        finally:browser.socket.close()
        with opener.open(CDP+'/json',timeout=3) as response:tabs=json.load(response)
        connection=_WebSocket(next(t['webSocketDebuggerUrl'] for t in tabs if t['id']==page))
        connection.socket.settimeout(30)
        connection.call('Page.enable')
        connection.call('Runtime.enable')
        connection.call('Page.addScriptToEvaluateOnNewDocument',source="window.fixtureErrors=[];window.fixtureNative=[];window.__TAURI__={core:{invoke:(name)=>{fixtureNative.push(name);return Promise.resolve(null);}}};addEventListener('error',e=>fixtureErrors.push(e.message));addEventListener('unhandledrejection',e=>fixtureErrors.push(String(e.reason)));")
        connection.call('Page.navigate',url=state['url'])
        def evaluate(code):
            value=connection.call('Runtime.evaluate',expression=code,awaitPromise=True,returnByValue=True)
            assert 'exceptionDetails' not in value,value.get('exceptionDetails')
            return value['result'].get('value')
        deadline=time.monotonic()+20
        while not evaluate('!!document.querySelector("[name=capability]")'):
            assert time.monotonic()<deadline,'Unlock did not appear';time.sleep(.05)
        assert evaluate("OrreryCockpitGlobal.nativeInvoke()('open_external_url').then(()=>false,()=>true)") is True
        result=evaluate("""(async()=>{
 const wait=async f=>{for(let i=0;i<150;i++){if(f())return;await new Promise(r=>setTimeout(r,50));}throw Error('DOM deadline');};
 const input=document.querySelector('[name=capability]');input.value="""+json.dumps(state['token'])+""";input.form.requestSubmit();
 await wait(()=>document.querySelectorAll('#roster .agent').length===2);
 window.OrreryTour?.firstFlight?.close();window.OrreryTour?.checklist?.close();
 const choice=document.querySelector('[aria-label="Mail viewpoint"]');choice.value='1';choice.dispatchEvent(new Event('change'));
 await wait(()=>document.querySelectorAll('#mail .reply-item').length===6);
 document.querySelectorAll('#mail .reply-more button')[5].click();
 await wait(()=>document.querySelector('#reply-6.selected'));
 document.dispatchEvent(new Event('visibilitychange'));
 return {count:document.querySelectorAll('#mail .reply-item').length,heading:document.querySelector('.cockpit-mail-heading').textContent,gap:document.querySelector('#mail .gap-note').textContent,notice:document.querySelector('#mail .instruction-hint').textContent,unknown:document.getElementById('roster').textContent.includes('ACTIVITY UNKNOWN')};
})()""")
        assert evaluate("performance.getEntriesByType('resource').filter(r=>/\\/telemetry\\/(agents|messages|graph|usage|spawn-catalog)/.test(new URL(r.name).pathname)).length")==0
        assert evaluate("document.getElementById('rosterSelectBtn').disabled && document.getElementById('globalExitNote').textContent==='Global exit is unavailable; required before PR7.'") is True
        evaluate('runBulkExit()')
        assert evaluate("performance.getEntriesByType('resource').some(r=>new URL(r.name).pathname==='/api/exit')") is False
        assert result['count']==6 and result['heading']=='Alpha ⇄ Beta6 visible'
        assert result['gap']=='Earlier mail is unavailable in this view.'
        assert 'English / 日本語' in result['notice'] and result['unknown']
        artifacts=Path(os.environ.get('ORRERY_BROWSER_ARTIFACTS',tmp_path/'screens'));artifacts.mkdir(parents=True,exist_ok=True)
        connection.call('Emulation.setDeviceMetricsOverride',width=1100,height=900,deviceScaleFactor=1,mobile=False)
        for theme in ('dark','light'):
            evaluate("OrreryColorTheme.setPreference("+json.dumps(theme)+")")
            result=evaluate("""(()=>{const rail=document.getElementById('mail');return {rail:rail.clientWidth,overflow:rail.scrollWidth>rail.clientWidth+1,body:getComputedStyle(document.querySelector('#reply-1 .reply-body')).webkitLineClamp};})()""")
            assert result['rail']<=340 and result['overflow'] is False,result
            assert result['body']=='1'
            shot=connection.call('Page.captureScreenshot',format='png')['data']
            (artifacts/('global-cockpit-'+theme+'.png')).write_bytes(base64.b64decode(shot))
        evaluate("document.querySelector('#roster .agent').dispatchEvent(new Event('mouseenter'))")
        result=evaluate("""(()=>{[...document.querySelectorAll('.cockpit-global-tools button')].find(b=>b.textContent==='Lock').click();return {title:document.querySelector('.cockpit-mail-heading').textContent,hidden:document.querySelector('.cockpit-mail-drawer').getAttribute('aria-hidden'),rows:document.querySelectorAll('#mail .reply-item').length,roster:document.getElementById('roster').textContent,detail:document.getElementById('agentDetail').textContent.includes('Alpha'),errors:fixtureErrors};})()""")
        assert evaluate("OrreryCockpitGlobal.nativeInvoke()('open_external_url').then(()=>false,()=>true)") is True
        assert evaluate("fixtureNative.includes('open_external_url')") is False
        assert result==dict(title='— ⇄ —0',hidden='true',rows=0,roster='',detail=False,errors=[]),result
    finally:
        if connection:connection.socket.close()
        if page:
            with opener.open(CDP+'/json/version',timeout=3) as response:version=json.load(response)
            browser=_WebSocket(version['webSocketDebuggerUrl'])
            try:browser.call('Target.closeTarget',targetId=page)
            finally:browser.socket.close()
        process.terminate()
        try:output=process.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:process.kill();output=process.communicate()[0]
        assert process.returncode==0,output[-2000:]
