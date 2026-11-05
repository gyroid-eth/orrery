"""A hidden cockpit tab never asks the server to hold its History poll."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bridge/tests'))
from test_conversation_submissions import cockpit,prepare  # noqa: F401


def test_hidden_tab_polls_without_wait(cockpit):  # noqa: F811
    js,wait,client=prepare(cockpit,'claude')
    js("""window.tabHidden=false;Object.defineProperty(document,'hidden',{configurable:true,get:()=>tabHidden});
      window.waits=[];const base=OrreryConversationSource.Source.prototype.read;
      OrreryConversationSource.Source.prototype.read=async function(name,options){waits.push(options.after===undefined?'none':(options.wait??0));return base.call(this,name,options);};
      conversationView.refresh();""")
    wait('waits.length===1')
    assert js('waits[0]')==25  # a visible tab asks to be held
    js('tabHidden=true;conversationView.refresh()')
    wait('waits.length===2')
    assert js('waits[1]')==0   # a hidden tab does not


def test_becoming_hidden_ends_a_held_poll(cockpit):  # noqa: F811
    js,wait,client=prepare(cockpit,'claude')
    js("""window.tabHidden=false;Object.defineProperty(document,'hidden',{configurable:true,get:()=>tabHidden});
      window.holdState={started:0,aborted:0};
      OrreryConversationSource.Source.prototype.read=function(name,options){
        if(!options.wait)return Promise.resolve({agent:name,provider:'claude',mode:'cursor',events:[],after:'tail'});
        holdState.started++;
        return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{holdState.aborted++;reject(new DOMException('aborted','AbortError'));}));
      };
      void conversationView.refresh();0;""")  # the held read never resolves: do not await it
    wait('holdState.started===1')
    js("tabHidden=true;document.dispatchEvent(new Event('visibilitychange'))")
    wait('holdState.aborted===1')
    assert js('holdState.started')==1  # and no new poll while hidden


def test_first_poll_after_opening_goes_at_once(cockpit):  # noqa: F811
    js,wait,client=prepare(cockpit,'claude')
    js("""window.reads=[];
      OrreryConversationSource.Source.prototype.read=function(name,options){
        reads.push({at:performance.now(),after:options.after??null,wait:options.wait??0});
        if(options.after===undefined)return Promise.resolve({agent:name,provider:'claude',mode:'cursor',hold:true,events:[{id:'o1',kind:'text',role:'assistant',text:'opened',ts:new Date().toISOString(),cursor_before:'f:0',cursor_after:'f:1'}],before:'f:0',after:'f:1',has_older:false});
        return new Promise(()=>{});  // the held poll
      };
      conversationView.close();conversationView.open();0;""")
    wait('reads.length>=2')
    first,second=js('reads[0]'),js('reads[1]')
    assert first['after'] is None and second['after']=='f:1' and second['wait']==25
    assert second['at']-first['at']<1000   # not the 4 s interval


def test_a_catch_up_page_without_a_slot_keeps_the_interval(cockpit):  # noqa: F811
    js,wait,client=prepare(cockpit,'claude')
    js("""window.reads=[];window.n=0;
      OrreryConversationSource.Source.prototype.read=function(name,options){
        reads.push(performance.now());n++;
        return Promise.resolve({agent:name,provider:'claude',mode:'cursor',has_newer:true,
          events:[{id:'c'+n,kind:'text',role:'assistant',text:'catch '+n,ts:new Date().toISOString(),cursor_before:'f:'+n,cursor_after:'f:'+(n+1)}],after:'f:'+(n+1)});
      };
      void conversationView.refresh();0;""")
    wait('reads.length>=1')
    import time;time.sleep(1.5)
    assert js('reads.length')==1   # has_newer but no slot: not at once


def test_every_pane_of_a_four_way_split_holds(cockpit):  # noqa: F811
    from test_split_pane_headers import setup
    js,wait,client=setup(cockpit,4)
    js("""window.holds=new Set();
      OrreryConversationSource.Source.prototype.read=function(name,options){
        if(options.wait){holds.add(name);return new Promise(()=>{});}
        return Promise.resolve({agent:name,provider:'codex',mode:'cursor',hold:true,
          events:[{id:name+'-1',kind:'text',role:'assistant',text:'opened '+name,ts:new Date().toISOString(),cursor_before:'f:0',cursor_after:'f:1'}],
          before:'f:0',after:'f:1',has_older:false});
      };
      document.querySelectorAll('.split-history-toggle').forEach(e=>e.click());0;""")
    wait('holds.size===4')
    assert sorted(js('[...holds]'))==sorted(['ReviewFixture','OtherFixture','ThirdFixture','FourthFixture'])


HOLD_SOURCE = """window.reads=[];window.aborted=0;
  OrreryConversationSource.Source.prototype.read=function(name,options){
    reads.push({at:performance.now(),before:options.before??null,after:options.after??null,wait:options.wait??0});
    if(options.wait)return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>{aborted++;reject(new DOMException('aborted','AbortError'));}));
    if(options.before)return Promise.resolve({agent:name,provider:'claude',mode:'cursor',hold:true,events:[{id:'older1',kind:'text',role:'assistant',text:'older row',ts:new Date().toISOString(),cursor_before:'f:-1',cursor_after:'f:0'}],before:'f:-1',has_older:false});
    return Promise.resolve({agent:name,provider:'claude',mode:'cursor',hold:true,events:[{id:'o1',kind:'text',role:'assistant',text:'opened',ts:new Date().toISOString(),cursor_before:'f:0',cursor_after:'f:1'}],before:'f:0',after:'f:1',has_older:true});
  };
  conversationView.close();conversationView.open();0;"""


def test_load_earlier_works_while_a_poll_is_held(cockpit):  # noqa: F811
    js,wait,client=prepare(cockpit,'claude')
    js(HOLD_SOURCE)
    wait("reads.some(r=>r.wait===25)")                       # the held poll waits
    assert js("reader.querySelector('.conversation-older').disabled")==False
    js("reader.querySelector('.conversation-older').click()")
    wait("reads.some(r=>r.before==='f:0')")                  # the older read ran at once
    wait("reader.querySelector('[data-event-id=older1]')!==null")
    assert js('aborted')>=1
