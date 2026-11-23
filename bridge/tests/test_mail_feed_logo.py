"""Recipient-grouped Mail works with the cockpit's existing read endpoints."""
import json

import pytest

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

def prepare(cockpit, *, recipient=True):
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
    if recipient:
        js("document.getElementById('mailViewBtn').click()")
    return js, wait, client


def test_assignments_group_under_direct_recipients_and_only_show_reply_arrival(cockpit):
    js, _, _ = prepare(cockpit)
    assert js("""[...document.querySelectorAll('.mail-assignee')].map(group=>[
      group.querySelector('.mail-assignee-name > :last-child').textContent,
      group.querySelectorAll('.mail-request').length
    ])""") == [['No direct recipient', 1], ['BuildNode', 2]]
    assert js("""findRequest('Review the fixture change').getAttribute('aria-label')""") == (
        'Open request: Review the fixture change, LeadNode to BuildNode. Reply received')
    assert js("""findRequest('Check the generated logs').title""") == 'Open request. Awaiting a reply'
    assert js("document.querySelector('.mail-reply:not([hidden]) .mail-reply-excerpt').textContent") == (
        'All generated checks passed.')
    assert js("document.querySelectorAll('.mail-state.replied').length") == 1
    assert not js("document.querySelector('#mail .mail-completed')")


def test_keyboard_route_and_filter_preserve_the_assignment(cockpit):
    js, wait, client = prepare(cockpit)
    assert js("document.getElementById('orrery').hasAttribute('hidden')")
    assert js("document.getElementById('mailSelectedRoute').hidden")
    js("document.getElementById('mailGraphBtn').click()")
    assert not js("document.getElementById('orrery').hasAttribute('hidden')")
    js("""window.kept=findRequest('Review the fixture change');kept.focus();
      window.lastRoute=null;document.addEventListener('oc:mail-route',e=>{window.lastRoute=e.detail});
      kept.blur();kept.focus();""")
    assert js('lastRoute') == {'sender': 'LeadNode', 'recipients': ['BuildNode']}
    assert js("document.querySelectorAll('#orrery .orrery-mail-focus path').length") == 2
    js("document.getElementById('mailGraphBtn').click()")
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
    assert js("document.getElementById('mailSelectedRoute').getAttribute('aria-label')") == 'LeadNode to BuildNode'
    js("document.querySelector('[data-action=close]').click()")
    assert js("document.getElementById('mailSelectedRoute').hidden")


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
    assert js("document.getElementById('mailSelectedRoute').getAttribute('aria-label')") == 'BuildNode to LeadNode'
    js("document.querySelector('[data-action=thread]').click()")
    assert js("document.querySelector('.mail-md code').textContent") == 'code'
    assert js("document.getElementById('mailSelectedRoute').getAttribute('aria-label')") == 'LeadNode to BuildNode'
    js("document.querySelector('[data-action=close]').click()")
    wait("document.querySelector('.maildrawer').hidden")
    assert js("document.activeElement===opened")
    assert js("Boolean(findRequest('New live assignment'))")


def test_timeline_orders_requests_and_shares_both_kinds_of_reply_link(cockpit):
    js, wait, _ = prepare(cockpit, recipient=False)
    assert js("localStorage.getItem('oc-mail-view')") is None
    assert js("document.getElementById('mailViewBtn').title") == 'Group by recipient'
    js("""emitFixtureMail([feedMessages[2],
      {id:120,sender:'LeadNode',recipients:['BuildNode','WatchNode'],subject:'Run both checks',ts:2000000006},
      {id:121,sender:'WatchNode',recipients:['LeadNode'],subject:'Watch report',ts:2000000007,body_md:'Report one'},
      {id:122,thread_id:'120',sender:'BuildNode',recipients:['LeadNode'],subject:'Build report',ts:2000000008,body_md:'Report two'}
    ]);""")
    assert js("[...document.querySelectorAll('.mail-subject')].map(e=>e.textContent)") == [
        'Run both checks', 'A copied update', 'Check the generated logs', 'Review the fixture change',
    ]
    linked = """subject=>[...findRequest(subject).parentElement.querySelectorAll('.mail-timeline-replies button')]
      .map(e=>e.dataset.reply)"""
    assert js(f"({linked})('Run both checks')") == ['121', '122']
    assert js(f"({linked})('Review the fixture change')") == ['103', '104']
    assert js("Boolean(document.querySelector('[data-reply=\"121\"] [title^=\"Possible reply\"]'))")
    assert not js("Boolean(document.querySelector('[data-reply=\"122\"] [title^=\"Possible reply\"]'))")
    js("document.querySelector('.mail-timeline-replies [data-reply=\"121\"]').click()")
    wait("document.querySelector('.mail-md')?.textContent==='Report one'")
    assert js("document.getElementById('mailSelectedRoute').getAttribute('aria-label')") == 'WatchNode to LeadNode'
    js("document.getElementById('mailViewBtn').click()")
    assert js("localStorage.getItem('oc-mail-view')") == 'recipient'
    assert js("document.querySelectorAll('.mail-assignee').length") == 3
    assert js("document.querySelectorAll('.mail-request').length") == 5


def test_saved_recipient_mode_is_respected_and_mail_uses_compact_type(cockpit):
    js, wait, client = prepare(cockpit, recipient=False)
    assert js("""[...document.querySelectorAll('.mail-request .mail-subject,.mail-route,.mailview-host time')]
      .every(el=>Number.parseFloat(getComputedStyle(el).fontSize)<=12)""")
    assert js("getComputedStyle(document.querySelector('.mail-head')).fontSize") == '13px'
    client.call('Page.addScriptToEvaluateOnNewDocument', source="localStorage.setItem('oc-mail-view','recipient');")
    client.call('Page.reload', ignoreCache=True)
    wait("Boolean(document.getElementById('mailViewBtn')?.querySelector('svg'))")
    assert js("document.getElementById('mailViewBtn').title") == 'Show thread timeline'


@pytest.mark.parametrize('original_id_thread', [False, True])
def test_older_request_outside_recent_window_is_restored_in_detail(cockpit, original_id_thread):
    js, wait, _ = prepare(cockpit)
    js("""window.feedFetch=window.fetch;
      const idThread="""+json.dumps(original_id_thread)+""";
      const original={id:202,thread_id:idThread?null:'older-fixture',sender:'LeadNode',recipients:['BuildNode'],
        subject:'Request outside list window',ts:1999999000,body_md:'Original request body'};
      const reply={id:203,thread_id:idThread?'202':'older-fixture',sender:'BuildNode',recipients:['LeadNode'],
        subject:'Most recent reply',ts:2000000008,excerpt:'Only the reply was in recent mail'};
      window.fetch=(url,...args)=>{
        const probe=new URL(url,location.href);
        if(probe.pathname==='/telemetry/mail/thread'){
          return Promise.resolve(new Response(JSON.stringify({messages:idThread?[reply]:[original,reply]})));
        }
        if(probe.pathname==='/telemetry/mail/message'){
          const message=probe.searchParams.get('id')==='202'?original:reply;
          return Promise.resolve(new Response(JSON.stringify({message})));
        }
        return feedFetch(url,...args);
      };
      emitFixtureMail([reply]);findRequest('Most recent reply').click();""")
    wait("document.querySelector('.mail-md').textContent==='Original request body'")
    assert js("document.querySelector('.drawer-body h2').textContent") == 'Request outside list window'
    assert js("document.querySelector('.thread-item').dataset.reply") == '203'
    assert js("document.querySelector('.drawer-link-source').title") == 'Linked by thread'
    js("document.querySelector('[data-action=close]').click()")
    assert js("findRequest('Request outside list window').title") == 'Open request. Reply received'
    assert not js("Boolean(findRequest('Most recent reply'))")


def test_ambiguous_reverse_reports_leave_requests_waiting(cockpit):
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
    assert js("findRequest('Check the older run').title") == 'Open request. Awaiting a reply'
    assert js("findRequest('Check the newer run').title") == 'Open request. Awaiting a reply'
    assert js("findRequest('Check the newer run').nextElementSibling.hidden")
    assert js("""[...document.querySelectorAll('.mail-subject')]
      .filter(el=>el.textContent==='Generated report').length""") == 2
    assert js("findRequest('Release notice').title") == 'Open message. Self-addressed notice'
    assert js("getComputedStyle(findRequest('Release notice').querySelector('.mail-state')).visibility") == 'hidden'

    js("""emitFixtureMail([{id:205,ts:2000000014,sender:'LeadNode',recipient:'BuildNode',subject:'One more check'}]);""")
    assert js("findRequest('One more check').title") == 'Open request. Awaiting a reply'
    js("""emitFixtureMail([{id:206,ts:2000000015,thread_id:null,sender:'BuildNode',recipient:'LeadNode',
      subject:'Additional report',excerpt:'The extra check passed.'}]);""")
    assert js("findRequest('One more check').title") == 'Open request. Awaiting a reply'
    assert js("findRequest('Check the older run').title") == 'Open request. Awaiting a reply'
    assert js("findRequest('Check the generated logs').title") == 'Open request. Awaiting a reply'
    assert js("Boolean(findRequest('Additional report'))")
    js("""document.getElementById('mailFilterBtn').click();document.activeElement.click();""")
    assert not js("Boolean(findRequest('Release notice'))")
    assert js("Boolean(findRequest('Check the older run'))")
    assert js("Boolean(findRequest('Check the newer run'))")


@pytest.mark.parametrize('recipient_view', [False, True])
def test_explicit_original_id_wins_and_other_deliveries_are_kept(cockpit, recipient_view):
    js, _, _ = prepare(cockpit, recipient=recipient_view)
    js("""emitFixtureMail([
      {id:404,ts:2000000024,thread_id:'401',sender:'DeskNode',recipients:['TraceNode','AuditNode'],
        subject:'Explicit first report',excerpt:'Confirmed first report.'},
      {id:402,ts:2000000022,sender:'TraceNode',recipients:['DeskNode'],subject:'Second trace request'},
      {id:403,ts:2000000023,sender:'DeskNode',recipients:['TraceNode','WatchNode'],
        subject:'Possible trace report',excerpt:'Possibly related to the second request.'},
      {id:401,ts:2000000021,sender:'TraceNode',recipients:['DeskNode'],subject:'First trace request'}
    ]);""")
    assert js("findRequest('First trace request').title") == 'Open request. Reply received'
    assert js("findRequest('Second trace request').title") == 'Open request. Awaiting a reply'
    assert js("findRequest('Explicit first report').getAttribute('aria-label')").startswith(
        'Open request: Explicit first report, DeskNode to AuditNode.')
    assert js("findRequest('Possible trace report').getAttribute('aria-label')").startswith(
        'Open request: Possible trace report, DeskNode to WatchNode.')
    js("""document.getElementById('mailFilterBtn').click();document.activeElement.click();""")
    assert not js("Boolean(findRequest('First trace request'))")
    assert js("Boolean(findRequest('Second trace request'))")
    assert js("""Boolean(findRequest('Second trace request').closest('.mail-assignment')
      .querySelector('[title^="Possible reply"]'))""")


def test_confirmed_explicit_request_cannot_take_a_threadless_report(cockpit):
    js, _, _ = prepare(cockpit)
    js("""emitFixtureMail([
      {id:501,ts:2000000031,sender:'IndexNode',recipient:'RecordNode',subject:'Index request'},
      {id:502,ts:2000000032,sender:'RecordNode',recipient:'IndexNode',subject:'Unrelated notice'},
      {id:503,ts:2000000033,thread_id:'501',sender:'RecordNode',recipient:'IndexNode',
        subject:'Explicit index report',excerpt:'Index is available.'}
    ]);""")
    assert js("Boolean(findRequest('Unrelated notice'))")
    assert js("findRequest('Index request').title") == 'Open request. Reply received'
    assert js("findRequest('Index request').nextElementSibling.querySelector('.mail-reply-excerpt').textContent") == (
        'Index is available.')
    assert not js("Boolean(findRequest('Explicit index report'))")


def test_linked_thread_message_keeps_an_additional_delivery_on_an_existing_route(cockpit):
    js, _, _ = prepare(cockpit)
    js("""emitFixtureMail([
      {id:601,ts:2000000041,thread_id:'release-fixture',sender:'TraceNode',recipient:'DeskNode',
        subject:'Trace review'},
      {id:602,ts:2000000042,thread_id:'release-fixture',sender:'DeskNode',recipient:'AuditNode',
        subject:'Existing delivery'},
      {id:603,ts:2000000043,thread_id:'release-fixture',sender:'DeskNode',recipients:['TraceNode','AuditNode'],
        subject:'Report and separate audit request'}
    ]);""")
    assert js("findRequest('Trace review').title") == 'Open request. Reply received'
    assert js("findRequest('Existing delivery').title") == 'Open request. Awaiting a reply'
    assert js("findRequest('Report and separate audit request').getAttribute('aria-label')") == (
        'Open request: Report and separate audit request, DeskNode to AuditNode. Awaiting a reply')


def test_details_identify_explicit_and_inferred_reply_links(cockpit):
    js, wait, _ = prepare(cockpit)
    js("""emitFixtureMail([
      {id:301,ts:2000000020,thread_id:null,sender:'TraceNode',recipient:'DeskNode',
        subject:'Check the generated artifact',body_md:'Artifact path is available.'},
      {id:302,ts:2000000021,thread_id:null,sender:'DeskNode',recipient:'TraceNode',
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
