"""The replaceable source preserves cancellation and agent identity."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "conversation_source.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_source_has_only_agent_and_cursor_selectors_and_forwards_abort():
    script = r"""
const {Source}=require(process.argv[1]);
(async()=>{
  const requests=[],controller=new AbortController();
  const source=new Source(async(url,options)=>{
    requests.push({url,cache:options.cache,sameSignal:options.signal===controller.signal});
    return {ok:true,json:async()=>({ok:true,agent:'CodexAgent',events:[]})};
  });
  await source.read('CodexAgent',{before:'abc:123',signal:controller.signal});
  let rejected=false;
  const bad=new Source(async()=>({ok:true,json:async()=>({ok:true,agent:'OtherAgent',events:[]})}));
  try{await bad.read('CodexAgent')}catch(_){rejected=true}
  const pending=new Source(async()=>({ok:false,json:async()=>({error:'history_unconfirmed'})}));
  let error;
  try{await pending.read('CodexAgent')}catch(e){error={code:e.code,message:e.message}}
  console.log(JSON.stringify({requests,rejected,error}));
})().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run(["node", "-e", script, str(SOURCE)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["requests"] == [dict(url="/telemetry/conversation?agent=CodexAgent&before=abc%3A123", cache="no-store", sameSignal=True)]
    assert data["rejected"]
    assert data["error"]["code"] == "history_unconfirmed"


@pytest.mark.skipif(shutil.which('node') is None,reason='node is not installed')
def test_unbound_reasons_offer_next_action_without_raw_technical_text():
    script=r"""
const {Source,REASONS,bindingMessage}=require(process.argv[1]);
(async()=>{
 for(const [reason_code,text] of Object.entries(REASONS)){
   const source=new Source(async()=>({ok:false,json:async()=>({error:'history_unconfirmed',reason_code,reason:'RAW_TECHNICAL_TEXT'})}));
   try{await source.read('Agent');throw Error('must reject')}catch(e){
     if(e.reasonCode!==reason_code||e.message!==text||e.message.includes('RAW_'))throw e;
   }
 }
 console.log(JSON.stringify({count:Object.keys(REASONS).length,receipt:REASONS.receipt_unavailable,
   codex:REASONS.hook_not_observed,stale:bindingMessage({error:'history_stale'}),unknown:bindingMessage({error:'history_unconfirmed',reason_code:'new-code'})}));
})();
"""
    result=subprocess.run(['node','-e',script,str(SOURCE)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    data=json.loads(result.stdout)
    assert data['count']>=23
    assert 'newly launched child' in data['receipt']
    assert '/hooks' in data['codex'] and 'new Codex process' in data['codex']
    assert data['stale'].startswith('Previous conversation')
    assert 'retry' in data['unknown']


@pytest.mark.skipif(shutil.which('node') is None,reason='node is not installed')
def test_reason_and_error_lookup_accepts_only_own_string_properties():
    script=r"""
const assert=require('assert');const {bindingMessage,REASONS}=require(process.argv[1]);
const generic=bindingMessage({error:'history_unconfirmed',reason_code:'unknown-code'});
const stale=bindingMessage({error:'history_stale',reason_code:'unknown-code'});
for(const key of ['constructor','__proto__','toString','hasOwnProperty','valueOf']){
 assert.strictEqual(bindingMessage({error:'history_unconfirmed',reason_code:key}),generic,key);
 assert.strictEqual(bindingMessage({error:'history_stale',reason_code:key}),stale,key);
 assert.strictEqual(bindingMessage({error:key}),'Reader could not be loaded.',key);
}
assert.strictEqual(typeof REASONS.invalid_receipt,'string');
assert.ok(bindingMessage({error:'history_unconfirmed',reason_code:'invalid_receipt'}).includes('new child'));
console.log('own property fallback and invalid receipt: OK');
"""
    result=subprocess.run(['node','-e',script,str(SOURCE)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
