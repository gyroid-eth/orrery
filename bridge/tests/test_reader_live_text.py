"""Reader projection from real xterm cells and authoritative History pages."""
import json
from pathlib import Path
import subprocess

import pytest

from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout


PROGRAMS = [
    ('claude-code', 'anthropic', 'cursor'),
    ('codex', 'openai', 'cursor'),
    ('dsh', 'deepseek', 'cursor'),
    ('dsh', 'local', 'fresh_tail'),
    ('hermes', 'local', 'snapshot'),
]
SEED = 'The original chart is sharp.'
MORE = SEED + ' The export loses detail.'
FINAL = MORE + ' Use a vector export.'


def frame(program, text, *, style='', extra='', head=''):
    reset = '\x1b[0m'
    if program == 'hermes':
        label = head or '╭─ ☤ Hermes ─────────────────────────╮'
        lines = [label, *(f'\x1b[38;2;255;248;220m{style}{line}{reset}' for line in text.split('\n')),
                 '', '  Working…']
    elif program == 'codex':
        lines = [f'\x1b[2m•{reset} {style}{text}{reset}', '', '› Ask Codex to do anything', '', 'gpt-5.4 high · 91% context left']
    elif program == 'dsh':
        lines = [f'  \x1b[38;2;232;230;224m●{reset} {style}{text}{reset}', '', '  ● Searching… (7s · ↓ ↓ 20 tokens)',
                 '  ╭' + '─' * 32 + '╮', '  ⌸ ❯ ', '  ╰' + '─' * 32 + '╯']
    else:
        lines = [f'\x1b[38;2;255;255;255m⏺{reset} {style}{text}{reset}', '', '✻ Working… (5s · ↓ 20 tokens)',
                 '─' * 32, '❯ ', '─' * 32, 'esc to interrupt']
    alternate = '\x1b[?1049h' if program == 'dsh' else ''
    return alternate + '\x1b[H\x1b[2J' + '\r\n'.join([*([extra] if extra else []), *lines])


def open_fixture(cockpit, program, provider, mode, *, count=28):
    js, wait, _, _, enable = cockpit
    stable_roster(js)
    enable(count=1)
    js(f"""conversationView.close();
      currentAgents[0]={{...currentAgents[0],program:{json.dumps(program)},provider:{json.dumps(provider)},
        running:true,act_state:'work',model_id:'fixture-model'}};
      window.rows=Array.from({{length:{count}}},(_,i)=>({{id:'history-'+i,role:'user',kind:'text',
        text:i==={count}-1?'Why does the exported chart look blurry?':'Earlier note '+i+'. The source report can be opened at full resolution.',
        ts:'2026-11-23T01:30:00Z'}}));
      window.recorded=null;
      window.reads=0;
      OrreryConversationSource.Source.prototype.read=async(name,options)=>{{
        ++reads;
        const rowsToRead=options.after&&{json.dumps(mode)}==='cursor'?[]:rows;
        return {{mode:{json.dumps(mode)},provider:{json.dumps(program.replace('-code', ''))},
          events:recorded?[...rowsToRead,recorded]:rowsToRead,before:'first',after:'last',has_older:false}};
      }};
      document.dispatchEvent(new Event('oc:agents'));conversationView.open();""")
    wait(f"document.querySelectorAll('[data-event-id^=history]').length==={count}")


def write_frame(js, data, *, snapshot=False):
    js(f"""(()=>{{const pane=panes.get('%901');
      writePaneOutput(pane,{{data:{json.dumps(data)},snapshot:{json.dumps(snapshot)}}});
      return new Promise(resolve=>pane.term.write('',()=>setTimeout(resolve,40)));}})()""")


def live_text(js):
    return js("document.querySelector('.conversation-live .conversation-text')?.textContent")


def commit(js, text=FINAL):
    js(f"""recorded={{id:'confirmed',role:'assistant',kind:'text',text:{json.dumps(text)},ts:'2026-11-23T01:30:15Z'}};
      conversationView.refresh()""")


@pytest.mark.parametrize('program,provider,mode', PROGRAMS)
def test_live_rows_extend_and_become_the_authoritative_message(cockpit, program, provider, mode):
    js, wait, *_ = cockpit
    open_fixture(cockpit, program, provider, mode)
    write_frame(js, frame(program, SEED), snapshot=True)
    assert live_text(js) is None
    write_frame(js, frame(program, MORE))
    assert live_text(js) == MORE
    assert js("""window.liveArticle=document.querySelector('.conversation-live');
      window.liveBody=liveArticle.querySelector('.conversation-text').firstChild;
      liveArticle.dataset.role==='assistant'&&!liveArticle.dataset.eventId&&Boolean(liveArticle.querySelector('.conversation-speaker'))""")
    assert js("""(()=>{const scroll=document.querySelector('.conversation-scroll');
      return scroll.scrollHeight-scroll.clientHeight-scroll.scrollTop<2;})()""")
    write_frame(js, frame(program, MORE + ' Use a'))
    assert live_text(js) == MORE + ' Use a'
    assert js("liveArticle.querySelector('.conversation-text').firstChild===liveBody")
    commit(js)
    wait("Boolean(document.querySelector('[data-event-id=confirmed]'))")
    assert live_text(js) is None
    assert js("document.querySelector('[data-event-id=confirmed]')===liveArticle")
    assert js("document.querySelector('[data-event-id=confirmed] .conversation-text').textContent") == FINAL
    assert js("document.querySelectorAll('[data-event-id=confirmed]').length") == 1
    write_frame(js, frame(program, FINAL))
    assert live_text(js) is None


def test_live_updates_keep_the_scroll_anchor_and_drop_ambiguous_redraw(cockpit):
    js, wait, *_ = cockpit
    open_fixture(cockpit, 'codex', 'openai', 'cursor')
    wait_reading_layout(js)
    js("""window.readScroll=document.querySelector('.conversation-scroll');
      readScroll.dispatchEvent(new WheelEvent('wheel'));readScroll.scrollTop=90;
      readScroll.dispatchEvent(new Event('scroll'));""")
    top = js('readScroll.scrollTop')
    write_frame(js, frame('codex', SEED), snapshot=True)
    write_frame(js, frame('codex', MORE))
    assert live_text(js) == MORE
    assert js('readScroll.scrollTop') == top
    write_frame(js, frame('codex', 'This is a different screen.'))
    assert live_text(js) is None
    write_frame(js, frame('codex', 'This is a different screen. It was rewritten.'))
    assert live_text(js) is None
    commit(js)
    wait("Boolean(document.querySelector('[data-event-id=confirmed]'))")
    assert js('readScroll.scrollTop') == top


def test_binding_loss_discards_an_unrecorded_terminal_row(cockpit):
    js, _, *_ = cockpit
    open_fixture(cockpit, 'claude-code', 'anthropic', 'cursor')
    write_frame(js, frame('claude-code', ''), snapshot=True)
    write_frame(js, frame('claude-code', MORE))
    assert live_text(js) == MORE
    js('readerActivity.disconnected()')
    assert live_text(js) is None
    write_frame(js, frame('claude-code', FINAL))
    assert live_text(js) is None


def test_word_springs_stagger_once_and_finalize_without_animation(cockpit):
    js, wait, client, *_ = cockpit
    client.call('Emulation.setEmulatedMedia',features=[{'name':'prefers-reduced-motion','value':'no-preference'}])
    open_fixture(cockpit, 'codex', 'openai', 'cursor', count=3)
    assert js("!document.querySelector('.conversation-activity').hidden")
    write_frame(js, frame('codex', SEED), snapshot=True)
    write_frame(js, frame('codex', MORE))
    delays=js("""window.wordNodes=[...document.querySelectorAll('.conversation-stream-word')];
       window.entrances=wordNodes.map(word=>word.getAnimations()[0]);
       entrances.map(a=>a?.effect.getTiming().delay)""")
    assert len(delays)>2 and abs(delays[1]-delays[0]-70)<1
    assert js("document.querySelector('.conversation-activity').hidden")
    write_frame(js, frame('codex', MORE))
    write_frame(js, frame('codex', MORE+' Use'))
    assert js("""wordNodes.every((word,index)=>document.querySelectorAll('.conversation-stream-word')[index]===word
        &&word.getAnimations().every(animation=>animation===entrances[index]))""")
    js("""window.projected=document.querySelector('.conversation-live');
       window.originTop=projected.getBoundingClientRect().top""")
    commit(js,MORE+' Use')
    wait("Boolean(document.querySelector('[data-event-id=confirmed]'))")
    assert js("""projected===document.querySelector('[data-event-id=confirmed]')
       &&projected.getAnimations({subtree:true}).length===0
       &&Math.abs(projected.getBoundingClientRect().top-originTop)<=1""")


def test_reduced_motion_and_hidden_tab_never_queue_words(cockpit):
    js, _, client, *_ = cockpit
    client.call('Emulation.setEmulatedMedia',features=[{'name':'prefers-reduced-motion','value':'reduce'}])
    open_fixture(cockpit, 'codex', 'openai', 'cursor', count=3)
    write_frame(js, frame('codex', SEED), snapshot=True)
    write_frame(js, frame('codex', MORE))
    assert live_text(js)==MORE
    assert js("document.querySelector('.conversation-live').getAnimations({subtree:true}).length===0")
    js("Object.defineProperty(document,'hidden',{value:true,configurable:true});document.dispatchEvent(new Event('visibilitychange'))")
    write_frame(js,frame('codex',FINAL))
    assert live_text(js) is None
    client.call('Emulation.setEmulatedMedia',features=[{'name':'prefers-reduced-motion','value':'no-preference'}])
    js("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
    assert live_text(js)==FINAL
    assert js("""[...document.querySelectorAll('.conversation-stream-word')].filter(word=>word.getAnimations().length)
      .every(word=>['Use','a','vector','export.'].includes(word.textContent))""")


def test_japanese_groups_are_short_and_keep_the_original_text():
    source = Path(__file__).resolve().parents[1] / 'conversation_motion.js'
    subprocess.run(['node', '-e', r"""
      require(process.argv[1]);
      const {pieces}=globalThis.OrreryConversationMotion;
      const assert=require('node:assert/strict'),text='SVGで目盛りを確認。\n  読みやすく。';
      const parts=pieces(text);
      assert.equal(parts.join(''),text);
      assert.deepEqual(parts,['SVG','で目盛り','を確認。','\n  ','読みやす','く。']);
    """, str(source)], check=True, timeout=10)


def test_hermes_ink_response_uses_its_own_gutter_and_busy_composer(cockpit):
    js, wait, *_ = cockpit
    open_fixture(cockpit, 'hermes', 'local', 'snapshot')
    footer = '\r\n\r\n ☤ fixture-model │ 12% │ ─ Working\r\n' + '─' * 35 + '\r\n☤ ❯ Thinking\r\n' + '─' * 35
    write_frame(js, '\x1b[?1049h\x1b[H\x1b[2J  ┊  ' + SEED + footer, snapshot=True)
    write_frame(js, '\x1b[H\x1b[2J  ┊  ' + MORE + footer)
    assert live_text(js) == MORE
    commit(js)
    wait("Boolean(document.querySelector('[data-event-id=confirmed]'))")
    assert live_text(js) is None


@pytest.mark.parametrize('program,provider,mode', PROGRAMS)
def test_live_projection_rejects_private_or_unstable_terminal_rows(cockpit, program, provider, mode):
    js, _, *_ = cockpit
    open_fixture(cockpit, program, provider, mode)
    pairs = [
        (frame(program, SEED, style='\x1b[2;3m'), frame(program, MORE, style='\x1b[2;3m')),
        (frame(program, '```python'), frame(program, '```python\r\n  print("fixture")')),
        (frame(program, 'The same words repeat.', extra='The same words repeat.'),
         frame(program, MORE, extra=MORE)),
        (frame(program, 'A' * 500), frame(program, 'A' * 520)),
    ]
    if program == 'hermes':
        pairs.append((frame(program, SEED, head='┌─ Thinking ─┐'), frame(program, MORE, head='┌─ Thinking ─┐')))
    else:
        pairs.append((frame(program, 'Read(fixture.txt)', style='\x1b[1m'),
                      frame(program, 'Read(fixture.txt) -> file content', style='\x1b[1m')))
    for first, second in pairs:
        write_frame(js, first, snapshot=True)
        write_frame(js, second)
        assert live_text(js) is None


def test_tracker_requires_growth_and_blocks_rewrites_at_the_same_terminal_anchor():
    source = Path(__file__).resolve().parents[1] / 'reader_activity.js'
    script = r"""
      const assert=require('node:assert/strict');
      const {advanceLiveText}=require(process.argv[1]);
      const sample=(row,text)=>({row,text});
      let previous=advanceLiveText(null,sample(3,'The initial reply'));
      assert.equal(previous.confirmed,false);
      previous.id=20;
      assert.equal(advanceLiveText(previous,sample(3,'The initial reply')),previous);
      previous=advanceLiveText(previous,sample(3,'The initial reply continues.'));
      assert.equal(previous.confirmed,true);
      assert.equal(previous.id,20);
      const moved=advanceLiveText(previous,sample(5,previous.text));
      assert.equal(moved.blocked,true);
      assert.equal(advanceLiveText(moved,sample(5,previous.text+' More.')),moved);
      const rewritten=advanceLiveText(previous,sample(3,'The redraw replaced the reply.'));
      assert.equal(rewritten.blocked,true);
      assert.equal(rewritten.confirmed,false);
      const missing=advanceLiveText(previous,null);
      assert.equal(missing.confirmed,false);
      const repeated=advanceLiveText(missing,sample(3,previous.text));
      assert.equal(repeated.blocked,true);
      assert.equal(advanceLiveText(repeated,sample(3,previous.text+' Repainted.')),repeated);
    """
    result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
