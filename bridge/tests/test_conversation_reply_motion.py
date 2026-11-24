"""Recorded reply arrivals and clipboard feedback in the real Reader."""
import json

import pytest

from test_conversation_review_regressions import cockpit
from test_reader_live_text import MORE, SEED, frame, open_fixture, write_frame


WORD = '.conversation-reply-word'
REPLY = 'The chart has **clear axis labels** now. Open [the notes](https://example.com) or run `render`. The vector export remains sharp at small sizes.'
CODE = 'render --format svg'


def dom_row(id):
    return f"document.querySelector('[data-event-id={id}]')"


def prepare(cockpit, mode='cursor'):
    js, wait, client, *_ = cockpit
    client.call('Emulation.setEmulatedMedia', features=[{'name':'prefers-reduced-motion','value':'no-preference'}])
    open_fixture(cockpit, 'codex', 'openai', mode, count=1)
    js(f"""conversationView.close();
      window.replyMode={json.dumps(mode)};
      window.tailRows=[{{id:'initial',kind:'text',role:'assistant',text:'Older recorded answer.',ts:new Date().toISOString()}}];
      window.replyPage=[];
      window.earlierPage=[];
      window.failRead=false;
      window.makeReply=(id,text,ts=new Date().toISOString())=>({{id,kind:'text',role:'assistant',text,ts}});
      OrreryConversationSource.Source.prototype.read=async(name,options)=>{{
        if(failRead)throw Error('Fixture connection lost');
        const events=options.before?earlierPage:options.after?
          replyMode==='cursor'?replyPage:tailRows.concat(replyPage):tailRows;
        return {{mode:replyMode,events,before:'first',after:'last',has_older:!options.before}};
      }};
      conversationView.open();
      window.startedAnimations=[];
      const animate=Element.prototype.animate;
      Element.prototype.animate=function(...args){{
        const effect=animate.apply(this,args);
        if(this.matches('{WORD}'))startedAnimations.push(effect);
        return effect;
      }};
    """)
    wait(f"Boolean({dom_row('initial')})")
    return js, wait, client


@pytest.mark.parametrize('mode', ['cursor', 'snapshot', 'fresh_tail'])
def test_new_assistant_prose_uses_mobile_timing_and_a_twelve_word_limit(cockpit, mode):
    js, wait, _ = prepare(cockpit, mode)
    assert js(f"{dom_row('initial')}.querySelector('{WORD}')===null")
    js(f"""replyPage=[makeReply('stale','An old answer','2020-01-01T00:00:00Z'),
      {{...makeReply('update','A thought update'),variant:'update'}},
      makeReply('answer',{json.dumps(REPLY)}),
      {{...makeReply('user','A user message'),role:'user'}}];
      conversationView.refresh()""")
    wait(f"Boolean({dom_row('answer')})")
    cues = js(f"[...{dom_row('answer')}.querySelectorAll('{WORD}')].map(node=>node.textContent)")
    assert cues == 'The chart has clear axis labels now. Open or run . The'.split()
    assert js("startedAnimations.map(a=>[a.effect.getTiming().delay,a.effect.getTiming().duration])") == [
        [70 * index, 460] for index in range(12)]
    assert js("startedAnimations[0].effect.getKeyframes()[0].top") == '6px'
    assert js(f"{dom_row('answer')}.querySelector('strong').textContent") == 'clear axis labels'
    assert js(f"{dom_row('answer')}.querySelector('a').textContent") == 'the notes'
    assert js(f"{dom_row('answer')}.querySelector('code').textContent") == 'render'
    assert js(f"{dom_row('answer')}.querySelector('.conversation-text').textContent.endsWith('The vector export remains sharp at small sizes.')")
    assert js(f"[{dom_row('stale')},{dom_row('update')},{dom_row('user')}].every(row=>!row.querySelector('{WORD}'))")
    js('conversationView.refresh()')
    assert js('startedAnimations.length') == 12


def test_older_pages_reconnect_and_reader_visibility_do_not_replay_replies(cockpit):
    js, wait, client = prepare(cockpit)
    js("earlierPage=[makeReply('earlier','Earlier recorded message')];document.querySelector('.conversation-older').click()")
    wait(f"Boolean({dom_row('earlier')})")
    js("""document.dispatchEvent(new Event('oc:reader-connection'));
      replyPage=[makeReply('reconnect','Reply while disconnected')];conversationView.refresh()""")
    wait(f"Boolean({dom_row('reconnect')})")
    js("""Object.defineProperty(document,'hidden',{configurable:true,value:true});
      document.dispatchEvent(new Event('visibilitychange'));
      replyPage=[makeReply('hidden','Reply while hidden')];conversationView.refresh()""")
    wait(f"Boolean({dom_row('hidden')})")
    js("""delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));
      replyPage=[makeReply('return','Reply from before restoring the tab')];conversationView.refresh()""")
    wait(f"Boolean({dom_row('return')})")
    assert js('startedAnimations.length') == 0
    client.call('Emulation.setEmulatedMedia', features=[{'name':'prefers-reduced-motion','value':'reduce'}])
    js("replyPage=[makeReply('reduced','Reply with reduced motion')];conversationView.refresh()")
    wait(f"Boolean({dom_row('reduced')})")
    assert js(f"{dom_row('reduced')}.querySelector('{WORD}')===null")
    client.call('Emulation.setEmulatedMedia', features=[{'name':'prefers-reduced-motion','value':'no-preference'}])
    js("replyPage=[makeReply('next','A freshly delivered reply')];conversationView.refresh()")
    wait(f"Boolean({dom_row('next')})")
    assert js('startedAnimations.length') == 4
    js("""Object.defineProperty(document,'hidden',{configurable:true,value:true});
      document.dispatchEvent(new Event('visibilitychange'))""")
    assert js("startedAnimations.every(effect=>effect.playState==='idle')")


def test_snapshot_without_a_known_tail_does_not_animate_a_reloaded_window(cockpit):
    js, wait, _ = prepare(cockpit, 'snapshot')
    js("tailRows=[];replyPage=[makeReply('replacement','Refreshed snapshot')];conversationView.refresh()")
    wait(f"Boolean({dom_row('replacement')})")
    assert js('startedAnimations.length') == 0
    js("replyPage.push(makeReply('new','Genuinely new reply'));conversationView.refresh()")
    wait(f"Boolean({dom_row('new')})")
    assert js('startedAnimations.length') == 3


def test_new_reply_below_the_reading_position_stays_static(cockpit):
    js, wait, _ = prepare(cockpit)
    js("""earlierPage=Array.from({length:36},(_,i)=>makeReply('older-'+i,'Previously recorded reply '+i));
      document.querySelector('.conversation-older').click()""")
    wait(f"Boolean({dom_row('older-35')})")
    js("""window.readingScroll=document.querySelector('.conversation-scroll');
      readingScroll.scrollTop=0;
      replyPage=[makeReply('below','A freshly arrived reply below the viewport')];
      conversationView.refresh()""")
    wait(f"Boolean({dom_row('below')})")
    assert js('startedAnimations.length') == 0
    assert js('readingScroll.scrollTop') == 0


@pytest.mark.parametrize('live_visible', [False, True])
def test_recent_confirmation_of_live_text_skips_second_reveal(cockpit, live_visible):
    js, wait, *_ = cockpit
    open_fixture(cockpit, 'codex', 'openai', 'cursor', count=1)
    write_frame(js, frame('codex', SEED), snapshot=True)
    write_frame(js, frame('codex', MORE))
    assert js("Boolean(document.querySelector('.conversation-live'))")
    if not live_visible:
        js('readerActivity.disconnected()')
        assert js("!document.querySelector('.conversation-live')")
    js(f"""recorded={{id:'confirmed',kind:'text',role:'assistant',text:{json.dumps(MORE)},ts:new Date().toISOString()}};
       conversationView.refresh()""")
    wait(f"Boolean({dom_row('confirmed')})")
    assert js(f"{dom_row('confirmed')}.querySelector('{WORD}')===null")


def test_clipboard_feedback_follows_success_failure_and_reduced_motion(cockpit):
    js, wait, client = prepare(cockpit)
    fenced = f'Check the chart.\n\n```sh\n{CODE}\n```'
    js(f"replyPage=[makeReply('code',{json.dumps(fenced)})];conversationView.refresh()")
    wait(f"Boolean({dom_row('code')})")
    js(f"""window.copyButton={dom_row('code')}.querySelector('.conversation-code-copy');
      window.copyWrap=copyButton.parentElement;
      window.copyMotion=()=>copyWrap.querySelector('.conversation-code-copy-face').getAnimations({{subtree:true}});
      Object.defineProperty(navigator,'clipboard',{{configurable:true,value:{{writeText:text=>{{
        window.copiedCode=text;return new Promise(resolve=>window.completeCopy=resolve);
      }}}}}});
      copyButton.focus();copyButton.click();
    """)
    assert js('copiedCode') == CODE+'\n'
    assert js("copyWrap.dataset.result") == ''
    js('completeCopy()')
    wait("copyWrap.dataset.result==='copied'")
    assert js("copyMotion().map(a=>a.effect.getTiming().duration)") == [580] * 4
    assert js("copyWrap.querySelector('[role=status]').textContent") == 'Copied'
    assert js("document.activeElement===copyButton")
    wait("copyWrap.dataset.result===''")
    assert js("copyMotion().length") == 4
    js("Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw Error('Denied')}}});copyButton.click()")
    wait("copyWrap.dataset.result==='failed'")
    assert js("copyMotion().length") == 0
    assert js("copyWrap.querySelector('[role=status]').textContent") == 'Copy unavailable'
    wait("copyWrap.dataset.result===''")
    client.call('Emulation.setEmulatedMedia', features=[{'name':'prefers-reduced-motion','value':'reduce'}])
    js("Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{}}});copyButton.click()")
    wait("copyWrap.dataset.result==='copied'")
    assert js("copyMotion().length") == 0
