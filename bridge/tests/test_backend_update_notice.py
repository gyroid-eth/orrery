import shutil
import subprocess
from pathlib import Path

import pytest


def test_backend_update_waits_once_reports_failure_and_reconnects():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the cockpit script")
    html = Path(__file__).resolve().parents[1] / "cockpit.html"
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[1], 'utf8');
const start = html.indexOf('const backendUpdate=document.');
const script = html.slice(start, html.indexOf('async function openExternalUrl',start));
const text={}, button={addEventListener(){}};
const notice={dataset:{},querySelector(tag){return tag==='span'?text:button;}};
const store=new Map();
const restartCalls=[];
const commit='b'.repeat(40);
const stale={state:'stale',boot:'1-7',running_commit:'a'.repeat(40),installed_commit:commit};
const current={state:'current',boot:'2-8',running_commit:commit,installed_commit:commit};
const rolledBack={...current,running_commit:stale.running_commit,installed_commit:stale.running_commit};
let phase='checkout', status=stale, reloads=0, hide;
const context={
  document:{getElementById:()=>notice,addEventListener(){}}, location:{reload(){reloads++;}},
  sessionStorage:{getItem:key=>store.get(key)??null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
  setTimeout(fn){hide=fn;return 1;},clearTimeout(){},
  backendRestarting:false,promptBusy:true,bulkActionBusy:null,permissionChangeBusy:false,
  pendingAgentExits:new Map(),
  appInvoke:()=>async (name,args)=>{
    if(name==='check_backend_version')return status;
    assert.equal(name,'restart_cockpit_backend');
    restartCalls.push(JSON.parse(JSON.stringify(args)));
    if(phase==='checkout')return {state:'busy',operations:['checkout','batch send']};
    if(phase==='failed')throw new Error('The updated backend did not become ready.');
    if(phase==='stale-boot')return {...current,boot:stale.boot};
    if(phase==='rollback')return rolledBack;
    if(phase==='up-to-date')return {...rolledBack,boot:stale.boot,restarted:false};
    return current;
  }
};
(async()=>{
  vm.createContext(context);
  vm.runInContext(script,context);
  await context.checkBackendUpdate();
  assert.equal(restartCalls.length,0);
  context.promptBusy=false;
  await context.checkBackendUpdate();
  assert.equal(notice.dataset.state,'waiting');
  assert.match(text.textContent,/checkout/);
  phase='failed';
  await context.checkBackendUpdate();
  assert.deepEqual(restartCalls.at(-1).waited,['send','checkout','batch send']);
  assert.equal(notice.dataset.state,'failed');
  assert.equal(text.title,'The updated backend did not become ready.');
  assert.equal(button.hidden,false);
  await context.checkBackendUpdate();
  assert.equal(restartCalls.length,2);
  assert.equal(reloads,0);
  phase='stale-boot';
  await context.requestBackendUpdate(stale,false);
  assert.equal(notice.dataset.state,'failed');
  assert.match(text.textContent,/Could not confirm/);
  assert.equal(reloads,0);
  phase='rollback';
  await context.requestBackendUpdate(stale,false);
  assert.equal(restartCalls.at(-1).automatic,false);
  assert.equal(reloads,1);
  status=rolledBack;
  await context.checkBackendUpdate();
  assert.equal(notice.dataset.state,'success');
  assert.equal(text.textContent,'Backend updated to aaaaaaaa');
  assert.equal(button.hidden,true);
  hide();
  assert.equal(notice.hidden,true);
  phase='up-to-date';
  await context.requestBackendUpdate(stale,false);
  assert.equal(notice.dataset.state,'success');
  assert.equal(text.textContent,'Backend is up to date');
  assert.equal(button.hidden,true);
  assert.equal(reloads,1);
  hide();
  assert.equal(notice.hidden,true);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run([node, "-e", script, str(html)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
