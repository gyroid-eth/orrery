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
