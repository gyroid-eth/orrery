"""Isolated synthetic TUI; control and input are never sent to a real agent."""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time

import pytest

TUI = r'''
const fs=require('fs');
const file=process.argv[2], log=file+'.keys';
let value,selected=1;
function draw(){
  value=JSON.parse(fs.readFileSync(file,'utf8'));selected=value.selected||1;
  let text=value.text.replace(/^[›❯] /mg,'  ');
  text=text.replace(new RegExp('^  '+selected+'\\.','m'),'› '+selected+'.');
  process.stdout.write('\x1b[2J\x1b[H'+text);
}
process.stdin.setRawMode(true);process.stdin.resume();draw();
process.on('SIGUSR2',draw);
process.on('SIGWINCH',draw);
process.stdin.on('data',data=>{
  fs.appendFileSync(log,JSON.stringify([...data])+'\n');
  const text=data.toString();
  for(let i=0;i<text.length;){
    let match=/^\x1b(?:\[|O)([AB])/.exec(text.slice(i));
    if(match){selected+=match[1]==='B'?1:-1;i+=match[0].length;continue;}
    const c=text[i++];
    if(c==='\r'||c==='y'||c==='p'||c==='\x1b'){
      fs.writeFileSync(file+'.result',JSON.stringify({selected,key:c}));
      if(!value.stay)process.stdout.write('\x1b[2J\x1b[HResponse received\r\nWaiting.');
    }
  }
});
'''


class FakePane:
    def __init__(self,directory,text):
        self.folder=Path(directory);self.screen=self.folder/'screen.json'
        self.screen.write_text(json.dumps(dict(text=text)))
        script=self.folder/'tui.js';script.write_text(TUI)
        tmux=shutil.which('tmux');node=shutil.which('node')
        if not tmux or not node:pytest.skip('tmux and node are required')
        self.prefix=[tmux,'-S',str(self.folder/'socket')]
        self.wrapper=self.folder/'tmux'
        self.wrapper.write_text('#!/bin/sh\nexec '+shlex.join(self.prefix)+' "$@"\n');self.wrapper.chmod(0o700)
        subprocess.run([*self.prefix,'-f','/dev/null','new-session','-d','-s','ApprovalFixture',
                        '-x','180','-y','40','-e','CLAUDECODE=1',node,str(script),str(self.screen)],check=True)
        subprocess.run([*self.prefix,'set-window-option','-t','=ApprovalFixture:0','window-size','manual'],check=True)
        meta=subprocess.check_output([*self.prefix,'display-message','-p','#{pane_id}\t#{pane_pid}'],text=True).strip().split('\t')
        self.pane,self.pid=meta[0],int(meta[1])
        self.keys=Path(str(self.screen)+'.keys');self.result=Path(str(self.screen)+'.result')
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if 'Allow' in self.capture() or 'Read outside' in self.capture() or 'Would you' in self.capture():break
            time.sleep(.03)
    async def harness(self, pane):
        if pane != self.pane:return None
        text=json.loads(self.screen.read_text())['text']
        return 'claude' if 'Read outside the working directories' in text else 'codex'
    def capture(self):
        return subprocess.check_output([*self.prefix,'capture-pane','-p','-J','-t',self.pane],text=True)
    def change(self,text,selected=1,stay=False):
        self.screen.write_text(json.dumps(dict(text=text,selected=selected,stay=stay)))
        os.kill(self.pid,signal.SIGUSR2)
    def close(self):
        subprocess.run([*self.prefix,'kill-server'],capture_output=True)


@pytest.fixture
def fake_pane(tmp_path,monkeypatch):
    # A private socket and HOME, with no inherited managed runtime binding.
    for key in list(os.environ):
        if key.startswith(('AGENTSTACK_','MCP_AGENT_')) or key in ('TMUX','TMUX_PANE','AGENT_NAME','PARENT_AGENT','CHILD_REGISTRATION_TOKEN'):
            monkeypatch.delenv(key,raising=False)
    home=tmp_path/'home';home.mkdir();monkeypatch.setenv('HOME',str(home));monkeypatch.setenv('AGENTSTACK_HOME',str(home))
    from test_reader_approval import MCP
    with tempfile.TemporaryDirectory(prefix='ra-',dir='/private/tmp' if Path('/private/tmp').is_dir() else None) as directory:
        fixture=FakePane(directory,MCP)
        try:yield fixture
        finally:fixture.close()
