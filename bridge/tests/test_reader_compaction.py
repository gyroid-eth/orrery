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


def test_other_harnesses_require_the_current_compaction_widget():
    source=Path(__file__).resolve().parents[1]/'reader_activity.js'
    script=r"""
const assert=require('node:assert/strict'),{compaction}=require(process.argv[1]);
const phase=elapsed=>({reader_phase:'compacting',reader_phase_elapsed:elapsed});
const rule='─'.repeat(64);
// Claude Code 2.1.331, captured in an isolated PTY against a delayed local API.
const claude='✶ Compacting conversation… (12s)\n'
  +'  ⎿ \u00a0Tip: Use Plan Mode to prepare for a complex request before\n'
  +'     making changes. Press shift+tab twice to enable.\n'
  +'                                               ● high · /effort\n';
const input=rule+'\n❯\n'+rule+'\n  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt';
for(const program of ['claude','claude-code']){
  assert.deepEqual(compaction(claude+input,program),phase('12s'));
  assert.deepEqual(compaction('✻ Compacting conversation… (1m 51s)\n'+input,program),phase('1m 51s'));
  assert.equal(compaction(claude+input.replace(' · esc to interrupt',''),program),null);
  assert.equal(compaction(claude+'⏺ A later reply.\n'+input,program),null);
  assert.equal(compaction('❯ ✶ Compacting conversation… (12s)\n'+input,program),null);
}

// dsh-tui 0.16.1 CompactionStatusRow, SpinnerAnimationRow and ActivityLine.
const dshInput='\n╭'+rule+'╮\n  ⌸ ❯                                                         ⛶\n╰'+rule+'╯\nctx 19% (24k/128k)';
for(const [status,elapsed] of [
  ['● Summarizing earlier turns… · reading context… · 12s · Esc cancels','12s'],
  ['● Summarizing earlier turns… · ↓ 1.2k tokens · 1m 3s · Esc cancels','1m 3s'],
  ['● 正在压缩会话… · 读取上下文… · 12s · Esc 取消','12s'],
  ['● Searching… (compacting · 12s · ↓ ↓ 20 tokens)','12s'],
  ['✦ Searching · total 1m3s · ↓ 20 tokens · compacting','1m 3s'],
]){
  assert.deepEqual(compaction(status+dshInput,'dsh'),phase(elapsed));
}
assert.equal(compaction('● Summarizing earlier turns… · 12s\n⏺ Later reply'+dshInput,'dsh'),null);
assert.equal(compaction('● Searching… (12s · ↓ ↓ 20 tokens)'+dshInput,'dsh'),null);

// Hermes managed Ink status rule can be above or below its composer.
const hermes='─ ☤ compacting…      · 12s │ fixture-model │ 19%';
assert.deepEqual(compaction(hermes+'\n ❯','hermes'),phase('12s'));
assert.deepEqual(compaction(' ❯\n'+hermes,'hermes'),phase('12s'));
assert.deepEqual(compaction('─ ⠋ compressing 8 messages (~1,200 tok)… │ fixture-model\n ❯','hermes'),phase(''));
assert.equal(compaction(hermes+'\n┊  Later reply.\n─ ready │ fixture-model\n ❯','hermes'),null);
assert.equal(compaction('─ ready │ fixture-model\n ❯ compacting… · 12s','hermes'),null);
"""
    result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
