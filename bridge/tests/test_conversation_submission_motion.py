"""C and M2 run through the real desktop composer and Reader."""
import json

import pytest

from test_conversation_reply_motion import prepare as prepare_arrival, dom_row
from test_conversation_submissions import prepare, cockpit


@pytest.mark.parametrize('with_reference', [False, True])
@pytest.mark.parametrize('cockpit', [False, 'reply-demo'], indirect=True)
def test_prompt_flies_from_real_composer_with_structured_pending_reference(cockpit, with_reference):
    js, wait, client = prepare(cockpit)
    client.call('Emulation.setEmulatedMedia', features=[{'name':'prefers-reduced-motion','value':'no-preference'}])
    js("""
      window.sendFrames=[];window.wire=[];
      const animate=Element.prototype.animate;
      Element.prototype.animate=function(frames,options){
        if(this.matches('.conversation-submission,.conversation-human[data-event-id=new]'))
          sendFrames.push({text:this.textContent,reference:!!this.querySelector('.conversation-reference-link'),
            transform:frames[0].transform, duration:options.duration,state:this.dataset.state});
        return animate.call(this,frames,options);
      };
      document.addEventListener('oc:prompt-sending',e=>wire.push(e.detail));
      window.finishEnter=null;
      const nativeTimeout=window.setTimeout;
      window.setTimeout=(fn,ms,...args)=>ms===250?(window.finishEnter=fn,0):nativeTimeout(fn,ms,...args);
      window.draft='Confirm the chart with Fixture Person.';
    """)
    if with_reference:
        js("""readerReply.add({agent:'ReviewFixture',role:'assistant',eventId:'old',text:'Fixture Person checked the labels.',
          ts:'2026-11-24T01:00:00Z',isCurrent:()=>true});""")
    js("promptInput.value=draft;sendPrompt()")
    assert js("wire[0].origin.width>0 && Number.isFinite(wire[0].origin.top)")
    assert js("sendFrames.length")==1
    [flight] = js("sendFrames")
    assert flight['transform'].startswith('translate(') and flight['duration']==610
    assert flight['reference']==with_reference and flight['state']=='sending'
    assert all(mark not in flight['text'] for mark in ('Reference:', 'Recorded message:', '> '))
    if js("OrreryDemo.on"):
        assert 'Fixture Person' not in flight['text'] and '*' in flight['text']
    assert js("wire[0].text.startsWith('Reference: ')")==with_reference
    js("""window.pendingRow=reader.querySelector('.conversation-submission');
      const flight=pendingRow.getAnimations()[0];flight.currentTime=120;flight.updatePlaybackRate(.05);
      window.newRecord.text=wire[0].text;finishEnter();""")
    wait("receipts.length===1")
    assert js("pendingRow===reader.querySelector('.conversation-submission')&&pendingRow.dataset.state==='awaiting'")
    js("turnDone=true;conversationView.refresh()")
    wait(f"Boolean({dom_row('new')})")
    assert js("!pendingRow.isConnected")
    assert js(f"Boolean({dom_row('new')}.querySelector('.conversation-reference-link'))")==with_reference
    assert js(f"!{dom_row('new')}.textContent.includes('Recorded message:')")
    assert js("sendFrames.length===2 && sendFrames[1].duration<610")
    assert js("packets.filter(p=>p.type==='input').length")==2


@pytest.mark.parametrize('reduced', [False, True])
@pytest.mark.parametrize('cockpit', ['reply-demo'], indirect=True)
def test_mail_showing_sender_arrow_recipients_and_subject_is_live_only(cockpit, reduced):
    js, wait, client = prepare_arrival(cockpit,'snapshot')
    client.call('Emulation.setEmulatedMedia', features=[{'name':'prefers-reduced-motion',
        'value':'reduce' if reduced else 'no-preference'}])
    wait("OrreryDemo.on")
    message=dict(id='mail-arrival',kind='mail',role='assistant',text='',mail=[
        dict(direction='sent',importance='high',recipients=['ArchiveFixture','ChartFixture'],
             subject='Review by Fixture Person keeps the chart clear.',body='Checked',coverage='complete')])
    js("""
      window.mailFrames=[];const base=Element.prototype.animate;
      Element.prototype.animate=function(frames,options){
        if(this.closest('.conversation-mail'))mailFrames.push({
          kind:this.className,delay:options.delay,text:this.textContent,
          complete:this.closest('.conversation-mail')?.textContent});
        return base.call(this,frames,options);
      };
      window.mailArrival="""+json.dumps(message)+""";
      replyPage=[{...mailArrival,ts:new Date().toISOString()}];conversationView.refresh();
    """)
    wait(f"Boolean({dom_row('mail-arrival')})")
    effects = js('mailFrames')
    if reduced:
        assert not effects
    else:
        by_kind = {effect['kind']:effect for effect in effects}
        assert next(effect['delay'] for effect in effects if 'conversation-mail-sender' in effect['kind']) == 0
        assert by_kind['conversation-mail-arrow']['delay'] == 85
        assert {effect['delay'] for effect in effects if 'conversation-mail-peer' in effect['kind'] and
                'conversation-mail-sender' not in effect['kind']} == {170}
        assert [effect['delay'] for effect in effects if effect['kind']=='conversation-mail-arrival-word'] == [245,315,385,455]
        assert all('Fixture Person' not in effect['complete'] for effect in effects)
        assert '*' in by_kind['conversation-mail-subject']['text']
    js('conversationView.refresh()')
    assert js('mailFrames.length')==len(effects)


def test_reduced_motion_keeps_the_structured_receipt_without_a_flight(cockpit):
    js, wait, client = prepare(cockpit)
    client.call('Emulation.setEmulatedMedia', features=[{'name':'prefers-reduced-motion','value':'reduce'}])
    js("""readerReply.add({agent:'ReviewFixture',role:'assistant',eventId:'old',
      text:'These labels are readable.',isCurrent:()=>true});
      promptInput.value='Confirm the chart.';sendPrompt();""")
    wait("Boolean(reader.querySelector('.conversation-submission .conversation-reference-link'))")
    assert js("reader.querySelector('.conversation-submission').getAnimations({subtree:true}).length")==0
    assert js("reader.querySelector('.conversation-submission-text').textContent")=='Confirm the chart.'
