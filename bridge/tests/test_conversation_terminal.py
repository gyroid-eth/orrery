"""Pure bounded matching: logical text retains physical xterm row mapping."""
import json,subprocess
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]/'conversation_terminal.js'

def test_soft_wrap_unicode_duplicates_boundaries_and_alternate_do_not_guess():
    script=r"""
const assert=require('assert'),{find}=require(process.argv[1]);
function buffer(values,type='normal'){
 const rows=values.map(v=>typeof v==='string'?{text:v}:v);
 return {type,length:rows.length,getLine:i=>rows[i]&&{isWrapped:!!rows[i].wrapped,translateToString:()=>rows[i].text}};
}
let b=buffer(['prefix','Generated soft ',{text:'wrap 日本語 message',wrapped:true},'suffix']);
let match=find(b,'Generated soft wrap 日本語 message');assert.equal(match.state,'unique');assert.equal(match.line,1);assert.equal(match.endLine,2);
assert.equal(find(buffer(['same repeated message','same repeated message']),'same repeated message').state,'multiple');
assert.equal(find(buffer(['A'.repeat(17)]),'A'.repeat(16)).state,'multiple');
assert.equal(find(buffer(['PREFIX_OK_SUFFIX']),'OK').state,'not_retained');
assert.equal(find(buffer(['OK']),'OK').state,'unique');
assert.equal(find(buffer(['Read-only status']),'Read').state,'not_retained');
assert.equal(find(buffer(['word']),'different').state,'not_retained');
assert.equal(find(buffer(['word']),'word',{alternate:true}).state,'alternate');
assert.equal(find(buffer(['word'],'alternate'),'word',{alternate:true}).state,'unique');
assert.equal(find(buffer(['current'],'alternate'),'old message',{alternate:true}).state,'alternate');
assert.equal(find(buffer(['pre '.repeat(30),'a\t b']),'a b').state,'unique');
const rows=Array.from({length:6600},(_,i)=>'generated line '+i);assert.equal(find(buffer(rows),'generated line 0').state,'limited');
rows[0]=rows[6599]='duplicate retained marker';assert.equal(find(buffer(rows),'duplicate retained marker').state,'limited');
assert.equal(find(buffer(['x'.repeat(65536)]),'x'.repeat(65537)).state,'limited');
console.log(JSON.stringify({softWrap:match,ok:true}));
"""
    result=subprocess.run(['node','-e',script,str(SOURCE)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
