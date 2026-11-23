"""Recipient-grouped Mail works with the cockpit's existing read endpoints."""
import json

from test_conversation_review_regressions import cockpit, stable_roster


MAIL = [
    dict(id=101, thread_id='fixture-change', sender='LeadNode', recipients=['BuildNode'],
         subject='Review the fixture change', excerpt='Inspect the generated change.', ts=2000000001),
    dict(id=102, thread_id='fixture-check', sender='LeadNode', recipients=['BuildNode'],
         subject='Check the generated logs', excerpt='Look for the reconnect marker.', ts=2000000002),
    dict(id=103, thread_id='fixture-change', sender='BuildNode', recipients=['LeadNode'],
         subject='初回報告', excerpt='One check passed.', ts=2000000003),
    dict(id=104, thread_id='fixture-change', sender='BuildNode', recipients=['LeadNode'],
         subject='完了という件名', excerpt='All generated checks passed.', ts=2000000004),
    dict(id=105, thread_id='fixture-check', sender='WatchNode',
         recipient='LeadNode', kind='cc',
         subject='A copied update', excerpt='For visibility.', ts=2000000005),
]

def prepare(cockpit):
    js, wait, client, requests, _ = cockpit
    stable_roster(js)
    wait("document.querySelector('#mail .mailcards')!==null")
    js("""rosterAnnotationEpoch++;
      currentAgents=['LeadNode','BuildNode','WatchNode'].map(name=>({name,provider:'openai',running:true}));
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      window.feedMessages="""+json.dumps(MAIL)+""";
      window.emitFixtureMail=messages=>document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages}}));
      emitFixtureMail([feedMessages[0],feedMessages[1],feedMessages[3],feedMessages[4]]);
      window.findRequest=subject=>[...document.querySelectorAll('#mail .mail-request')]
        .find(el=>el.querySelector('.mail-subject').textContent===subject);
      """)
    wait("Boolean(findRequest('Review the fixture change'))")
    return js, wait, client


def test_assignments_group_under_direct_recipients_and_only_show_reply_arrival(cockpit):
    js, _, _ = prepare(cockpit)
    assert js("""[...document.querySelectorAll('.mail-assignee')].map(group=>[
      group.querySelector('.mail-assignee-name > :last-child').textContent,
      group.querySelectorAll('.mail-request').length
    ])""") == [['No direct recipient', 1], ['BuildNode', 2]]
    assert js("""findRequest('Review the fixture change').getAttribute('aria-label')""") == (
        'Review the fixture change, LeadNode to BuildNode. Reply received')
    assert js("""findRequest('Check the generated logs').title""") == 'Awaiting a reply'
    assert js("document.querySelector('.mail-reply:not([hidden]) .mail-reply-excerpt').textContent") == (
        'All generated checks passed.')
    assert js("document.querySelectorAll('.mail-state.replied').length") == 1
    assert not js("document.querySelector('#mail .mail-completed')")


def test_keyboard_route_and_filter_preserve_the_assignment(cockpit):
    js, wait, client = prepare(cockpit)
    js("""window.kept=findRequest('Review the fixture change');kept.focus();
      window.lastRoute=null;document.addEventListener('oc:mail-route',e=>{window.lastRoute=e.detail});
      kept.blur();kept.focus();""")
    assert js('lastRoute') == {'sender': 'LeadNode', 'recipients': ['BuildNode']}
    assert js("document.querySelectorAll('#orrery .orrery-mail-focus path').length") == 2
    js("document.getElementById('mailFilterBtn').click()")
    wait("document.activeElement.textContent==='Awaiting a reply'")
    js("document.activeElement.click()")
    assert not js("Boolean(findRequest('Review the fixture change'))")
    assert js("Boolean(findRequest('Check the generated logs'))")
    assert js("document.querySelectorAll('.mail-request').length") == 1
    assert js("document.querySelectorAll('.mail-assignee').length") == 1
    assert js("document.activeElement.id") == 'mailFilterBtn'
    js("""document.getElementById('mailFilterBtn').click();document.activeElement.click();
      findRequest('Review the fixture change').focus();""")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    wait("!document.querySelector('.maildrawer').hidden")


def test_thread_load_keeps_scroll_and_focus_during_live_arrival(cockpit):
    js, wait, _ = prepare(cockpit)
    js(r"""window.feedFetch=window.fetch;
      window.fetch=(url,...args)=>{
        const probe=new URL(url,location.href);
        if(probe.pathname==='/telemetry/mail/message'){
          const message={...feedMessages.find(m=>String(m.id)===probe.searchParams.get('id')),
            body_md:probe.searchParams.get('id')==='101'
              ? 'A long fixture line with `code`.\n'.repeat(120):'Original reply body'};
          return Promise.resolve(new Response(JSON.stringify({message})));
        }
        if(probe.pathname==='/telemetry/mail/thread'){
          return new Promise(resolve=>window.finishThread=()=>resolve(
            new Response(JSON.stringify({messages:[feedMessages[0],feedMessages[2],feedMessages[3]]}))));
        }
        return feedFetch(url,...args);
      };
      window.opened=findRequest('Review the fixture change');opened.click();
    """)
    wait("Boolean(document.querySelector('.mail-md code'))")
    assert js("document.activeElement.dataset.action") == 'close'
    js("""window.openedScroll=document.querySelector('.drawer-scroll');
      openedScroll.scrollTop=180;
      emitFixtureMail([{...feedMessages[1],id:106,thread_id:'fixture-new',ts:2000000006,subject:'New live assignment'}]);
      finishThread();
    """)
    wait("document.querySelectorAll('.thread-item').length===2")
    assert js("openedScroll===document.querySelector('.drawer-scroll')&&openedScroll.scrollTop===180")
    assert js("document.activeElement.dataset.action") == 'close'
    js("document.querySelector('[data-reply=\"103\"]').click()")
    wait("document.querySelector('.mail-md').textContent==='Original reply body'")
    js("document.querySelector('[data-action=thread]').click()")
    assert js("document.querySelector('.mail-md code').textContent") == 'code'
    js("document.querySelector('[data-action=close]').click()")
    wait("document.querySelector('.maildrawer').hidden")
    assert js("document.activeElement===opened")
    assert js("Boolean(findRequest('New live assignment'))")


def test_older_request_outside_recent_window_is_restored_in_detail(cockpit):
    js, wait, _ = prepare(cockpit)
    js("""window.feedFetch=window.fetch;
      const original={id:202,thread_id:'older-fixture',sender:'LeadNode',recipients:['BuildNode'],
        subject:'Request outside list window',ts:1999999000,body_md:'Original request body'};
      const reply={id:203,thread_id:'older-fixture',sender:'BuildNode',recipients:['LeadNode'],
        subject:'Most recent reply',ts:2000000008,excerpt:'Only the reply was in recent mail'};
      window.fetch=(url,...args)=>{
        const probe=new URL(url,location.href);
        if(probe.pathname==='/telemetry/mail/thread')return Promise.resolve(new Response(JSON.stringify({messages:[original,reply]})));
        if(probe.pathname==='/telemetry/mail/message')return Promise.resolve(new Response(JSON.stringify({message:reply})));
        return feedFetch(url,...args);
      };
      emitFixtureMail([reply]);findRequest('Most recent reply').click();""")
    wait("document.querySelector('.mail-md').textContent==='Original request body'")
    assert js("document.querySelector('.drawer-body h2').textContent") == 'Request outside list window'
    assert js("document.querySelector('.thread-item').dataset.reply") == '203'


def test_threadless_reports_pair_with_latest_unanswered_request(cockpit):
    js, _, _ = prepare(cockpit)
    js("""window.unthreaded=[
      {id:201,ts:2000000010,thread_id:null,sender:'LeadNode',recipient:'BuildNode',subject:'Check the older run'},
      {id:202,ts:2000000011,thread_id:'',sender:'LeadNode',recipients:['BuildNode'],subject:'Check the newer run',
        body_md:'Review both generated logs.'},
      {id:203,ts:2000000012,sender:'BuildNode',recipients:['LeadNode','WatchNode'],subject:'Generated report',
        excerpt:'The newer run passed.',body_md:'The newer run passed all eight checks.'},
      {id:204,ts:2000000013,sender:'WatchNode',recipients:['WatchNode'],subject:'Release notice',
        body_md:'The generated release was published.'}
    ];
    // Recent and live payloads can arrive out of order.
    emitFixtureMail([...unthreaded].reverse());""")
    assert js("findRequest('Check the older run').title") == 'Awaiting a reply'
    assert js("findRequest('Check the newer run').title") == 'Reply received'
    assert js("findRequest('Check the newer run').nextElementSibling.textContent.includes('The newer run passed.')")
    assert not js("Boolean(findRequest('Generated report'))")
    assert js("findRequest('Release notice').title") == 'Self-addressed notice'
    assert js("getComputedStyle(findRequest('Release notice').querySelector('.mail-state')).visibility") == 'hidden'

    js("""emitFixtureMail([{id:205,ts:2000000014,sender:'LeadNode',recipient:'BuildNode',subject:'One more check'}]);""")
    assert js("findRequest('One more check').title") == 'Awaiting a reply'
    js("""emitFixtureMail([{id:206,ts:2000000015,thread_id:null,sender:'BuildNode',recipient:'LeadNode',
      subject:'Additional report',excerpt:'The extra check passed.'}]);""")
    assert js("findRequest('One more check').title") == 'Reply received'
    assert js("findRequest('Check the older run').title") == 'Awaiting a reply'
    assert js("findRequest('Check the generated logs').title") == 'Awaiting a reply'
    assert not js("Boolean(findRequest('Additional report'))")
    js("""document.getElementById('mailFilterBtn').click();document.activeElement.click();""")
    assert not js("Boolean(findRequest('Release notice'))")
    assert js("Boolean(findRequest('Check the older run'))")


def test_details_identify_explicit_and_inferred_reply_links(cockpit):
    js, wait, _ = prepare(cockpit)
    js("""emitFixtureMail([
      {id:301,ts:2000000020,thread_id:null,sender:'LeadNode',recipient:'BuildNode',
        subject:'Check the generated artifact',body_md:'Artifact path is available.'},
      {id:302,ts:2000000021,thread_id:null,sender:'BuildNode',recipient:'LeadNode',
        subject:'Artifact checked',excerpt:'The generated artifact opens.',body_md:'Full artifact report.'}
    ]);
    findRequest('Check the generated artifact').click();""")
    label = 'Linked by reverse delivery direction (inferred)'
    assert js("document.querySelector('.drawer-link-source').title") == label
    assert js("document.querySelector('.drawer-link-source').getAttribute('aria-label')") == label
    assert js("document.querySelector('.drawer-link-source').textContent") == ''
    assert js("document.querySelector('.drawer-body .mail-md').textContent") == 'Artifact path is available.'
    js("document.querySelector('[data-reply=\"302\"]').click()")
    assert js("document.querySelector('.drawer-body .mail-md').textContent") == 'Full artifact report.'
    assert js("document.querySelector('.drawer-link-source').title") == label
    js("document.querySelector('[data-action=close]').click()")
    wait("document.querySelector('.maildrawer').hidden")
    js("findRequest('Review the fixture change').click()")
    assert js("document.querySelector('.drawer-link-source').title") == 'Linked by thread'
