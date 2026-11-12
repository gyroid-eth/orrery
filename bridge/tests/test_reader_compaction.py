"""Only adjacent native compaction controls count, never historical prose."""
import subprocess
from pathlib import Path


def test_native_compaction_footer_wrap_completion_and_prose():
    source=Path(__file__).resolve().parents[1]/'reader_activity.js'
    script=r"""
const assert=require('node:assert/strict'),{compaction}=require(process.argv[1]);
const status='• Compacting context (12s • esc to interrupt)';
const input='\n\n› Ask Codex to do anything\n\ngpt-6.1-sol high · 91% context left\n';
assert.deepEqual(compaction(status+input,'codex'),{reader_phase:'compacting',reader_phase_elapsed:'12s'});
assert.deepEqual(compaction('• Compacting context (2m 03s •\nesc to interrupt)\nMaking room to continue.'+input,'codex'),{reader_phase:'compacting',reader_phase_elapsed:'2m 03s'});
for(const text of [status+'\n\n• Completed reply.'+input,status+'\nContext compacted · 12s'+input,
  'Compacting context'+input,'Please show Compacting context while waiting.'+input,
  '• Working (12s • esc to interrupt)'+input,status+'\n› pending input\nunknown footer',
  status+input+'\n• Later reply\n'+input,status+'\n› pending\nHooks need review']){
  assert.equal(compaction(text,'codex'),null,text);
}
assert.equal(compaction(status+input,'hermes'),null);
assert.equal(compaction(status+input,'claude-code'),null);
assert.equal(compaction('x'.repeat(65537),'codex'),null);
console.log('native current controls only');
"""
    result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
