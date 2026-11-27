"""Mail's recipient headings use roster portraits and fit narrow desktop rails."""
import json

import pytest

from test_conversation_review_regressions import cockpit, stable_roster


def prepare(cockpit, width=320, theme='dark'):
    js, wait, _, _, _ = cockpit
    stable_roster(js)
    wait("document.querySelector('#mail .mailcards')!==null")
    js("""document.getElementById('mailViewBtn').click();
      rosterAnnotationEpoch++;
      currentAgents=['BuildNode','AuditNode'].map(name=>({name,provider:'openai',running:true}));
      window.mailGroupFixture={id:201,sender:'LaunchNode',subject:'Inspect <img src=x> and the generated trace',
        recipients:['BuildNode','AuditNode','ExternalNode'],importance:'high',ts:2000000000};
      document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[mailGroupFixture]}}));
      OrreryColorTheme.setPreference("""+json.dumps(theme)+""");
      document.querySelector('.grid').style.gridTemplateColumns="""+json.dumps(f'250px minmax(0,1fr) {width}px')+""";
      window.groupFor=name=>[...document.querySelectorAll('#mail .mail-assignee')].find(
        group=>group.querySelector('.mail-assignee-peer > :last-child').textContent===name);
      """)
    wait("document.querySelectorAll('.mail-assignee').length===3")
    return js, wait


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [240, 384])
def test_each_direct_recipient_has_an_accessible_heading(cockpit, theme, width):
    js, _ = prepare(cockpit, width, theme)
    assert js("groupFor('BuildNode').querySelector('.conversation-avatar').getBoundingClientRect().width") == 25
    assert js("groupFor('ExternalNode').querySelector('.conversation-avatar')") is None
    assert js("groupFor('ExternalNode').querySelector('.mail-assignee-fallback').getAttribute('aria-hidden')") == 'true'
    assert not js("Boolean(document.querySelector('.mail-subject img'))")
    assert js("""[...document.querySelectorAll('.mail-assignee')].every(
      group=>group.scrollWidth<=group.clientWidth+1&&
        group.querySelector('.mail-request .mail-row-open').getAttribute('aria-label').endsWith('high importance'))""")


def test_roster_refresh_keeps_focused_assignment_and_drops_stale_portrait(cockpit):
    js, _ = prepare(cockpit)
    js("""window.keptGroup=groupFor('BuildNode');window.keptRequest=keptGroup.querySelector('.mail-request .mail-row-open');
      keptRequest.focus();currentAgents=currentAgents.filter(agent=>agent.name!=='BuildNode');
      document.dispatchEvent(new Event('oc:agents'));""")
    assert js("document.activeElement===keptRequest&&keptGroup===groupFor('BuildNode')")
    assert js("keptGroup.querySelector('.conversation-avatar')") is None
    assert js("Boolean(keptGroup.querySelector('.mail-assignee-fallback'))")


@pytest.mark.parametrize('reduced', [False, True])
def test_live_mail_reveals_in_place_as_existing_rows_move(cockpit, reduced):
    js, wait, client, _, _ = cockpit
    client.call('Emulation.setEmulatedMedia', features=[{
        'name': 'prefers-reduced-motion', 'value': 'reduce' if reduced else 'no-preference',
    }])
    wait("Boolean(document.querySelector('#mail .mailcards'))")
    result = js("""(async()=>{
      await fetch('/telemetry/mail/recent?limit=40');
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      const mail=document.getElementById('mail');
      const receive=id=>document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[{
        id,ts:id,sender:'UnlistedSender',recipient:'FixtureRecipient',subject:'Fixture '+id,
      }]}}));
      const post=2000000000;
      receive(post);
      mail.getAnimations({subtree:true}).forEach(animation=>animation.finish());
      const previous=mail.querySelector('.mail-assignment');
      const originalY=previous.getBoundingClientRect().top;
      receive(post+1);
      const incoming=mail.querySelector('.mail-assignment');
      const effects=element=>element.getAnimations().map(animation=>({
        frames:animation.effect.getKeyframes().map(({transform,clipPath})=>({transform,clipPath})),
        duration:animation.effect.getTiming().duration,
        easing:animation.effect.getTiming().easing,
      }));
      return {incoming:effects(incoming),previous:effects(previous),sameY:previous.getBoundingClientRect().top===originalY,
        cue:incoming.classList.contains('mail-arrival-still'),previousCue:previous.classList.contains('mail-arrival-still'),
        subject:incoming.querySelector('.mail-subject').textContent};
    })()""")
    assert result['subject'] == 'Fixture 2000000001'
    assert result['cue'] is reduced and not result['previousCue']
    if reduced:
        assert result['incoming'] == result['previous'] == []
        assert not result['sameY']
    else:
        incoming, = result['incoming']
        previous, = result['previous']
        assert incoming['duration'] == previous['duration'] == 275
        assert incoming['easing'] == previous['easing']
        assert incoming['frames'] == [{'clipPath': 'inset(0px 0px 100%)'}, {'clipPath': 'inset(0px)'}]
        assert previous['frames'][0]['transform'].startswith('translate(0px, -')
        assert result['sameY']


def test_active_mail_filter_can_be_cleared_with_one_click(cockpit):
    js, wait = prepare(cockpit, width=240)
    js("""window.filterMail=name=>document.dispatchEvent(new CustomEvent('oc:filter-agent',{detail:{agent:name}}));
      window.focusMailPane=name=>document.dispatchEvent(new CustomEvent('oc:focus-agent',{detail:{name}}));
      filterMail('EmptyNode');focusMailPane('EmptyNode');""")
    wait("document.querySelector('.mailempty')?.textContent==='No matching requests'")
    assert js("document.querySelector('.mail-clear-filter').getAttribute('aria-label')") == (
        'Clear mail filters: EmptyNode')
    js("document.querySelector('.mail-clear-filter').click()")
    assert js("document.querySelector('.mail-filter-summary').hidden")
    assert js("document.querySelectorAll('.mail-assignee').length") == 3

    js("""filterMail('BuildNode');
      document.querySelector('.mail-clear-filter').click();
      focusMailPane('BuildNode');""")
    assert js("document.querySelector('.mail-filter-summary').hidden")
    assert js("document.activeElement.id") == 'mailFilterBtn'
    js("filterMail('BuildNode')")
    assert js("document.querySelector('.mail-clear-filter span').textContent") == 'BuildNode'


def test_mini_comets_show_arrival_ripples_and_subjects_for_each_recipient(cockpit):
    js, wait, client, _, _ = cockpit
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'no-preference'},
    ])
    wait("Boolean(window.OrreryRail&&document.querySelector('#mail .mailcards'))")
    stable_roster(js)
    js("""(()=>{
      Object.defineProperty(document,'hidden',{value:false});
      const names=['Sender','FirstRecipient','SecondRecipient'];
      currentAgents=names.map(name=>({name,provider:'openai',running:true,annot:{role:'Original role'}}));
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      const graph=document.getElementById('orrery');
      if(graph.hasAttribute('hidden'))document.getElementById('mailGraphBtn').click();
      const nextFrame=window.requestAnimationFrame;
      const callbacks=[],ripples=[];
      window.requestAnimationFrame=callback=>{
        if(callback.name==='animateFlight'){callbacks.push(callback);return 0;}
        if(callback.name==='animateRipple'){ripples.push(callback);return 0;}
        return nextFrame(callback);
      };
      window.advanceFlights=timestamp=>callbacks.splice(0).forEach(callback=>callback(timestamp));
      window.advanceRipples=timestamp=>ripples.splice(0).forEach(callback=>callback(timestamp));
      window.sendFixtureComet=(id,subject)=>document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[{
        subject,
        id,sender:'Sender',recipient:'FirstRecipient',recipients:['FirstRecipient',{name:'SecondRecipient'}],
      }]}}));
      window.cometFlights=()=>[...graph.querySelectorAll('.orrery-comet-flight')];
      window.arrivalRipples=()=>[...graph.querySelectorAll('.orrery-comet-ripple')];
      window.arrivalCaptions=()=>[...graph.querySelectorAll('.orrery-caption-arrival')];
      sendFixtureComet(142,'First delivery');
    })()""")
    wait('cometFlights().length===2')
    assert js("""advanceFlights(10000);advanceFlights(10850);
      const edges=[...document.querySelectorAll('#orrery .orrery-comm-edge')];
      edges.length===2&&edges.every(edge=>{
        const midpoint=edge.getPointAtLength(edge.getTotalLength()/2);
        return cometFlights().some(flight=>{
          const at=flight.transform.baseVal.getItem(0).matrix;
          return flight.querySelector('linearGradient')&&Math.hypot(at.e-midpoint.x,at.f-midpoint.y)<1;
        });
      })""")
    assert js('advanceFlights(11699);cometFlights().length') == 2
    assert js('arrivalRipples().length') == 0
    assert js('arrivalCaptions().length') == 0
    assert js('advanceFlights(11700);cometFlights().length') == 0
    assert js("""arrivalCaptions().map(caption=>[
      caption.closest('.mini-agent').dataset.agent,caption.textContent,
    ]).sort()""") == [
        ['FirstRecipient', 'First delivery'],
        ['SecondRecipient', 'First delivery'],
    ]
    assert js("""advanceRipples(11700);arrivalRipples().length===2&&
      ['FirstRecipient','SecondRecipient'].every(name=>{
        const graph=document.getElementById('orrery');
        const face=graph.querySelector('[data-agent='+name+'] .orrery-hit').getBoundingClientRect();
        return arrivalRipples().some(ring=>{
          const center=new DOMPoint(ring.cx.baseVal.value,ring.cy.baseVal.value).matrixTransform(ring.getScreenCTM());
          return Math.hypot(center.x-face.x-face.width/2,center.y-face.y-face.height/2)<1;
        });
      })""")
    assert js('advanceRipples(11975);arrivalRipples().map(ring=>ring.r.baseVal.value)') == [19.5, 19.5]
    assert js('advanceRipples(12250);arrivalRipples().length') == 0
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'},
    ])
    assert js("""(async()=>{
      sendFixtureComet(143,'<img src=x> Updated delivery with a long subject for the compact graph');
      await new Promise(requestAnimationFrame);
      return [cometFlights().length,arrivalRipples().length];
    })()""") == [0, 0]
    assert js("""(()=>{
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      return arrivalCaptions().length===2&&arrivalCaptions().every(caption=>{
        const subject=caption.querySelector('.orrery-arrival-subject');
        return caption.querySelector('.orrery-arrival-count').textContent==='+1'&&
          !subject.querySelector('img')&&subject.textContent.startsWith('<img src=x>')&&
          subject.scrollWidth>subject.clientWidth&&subject.getAnimations().length===0;
      });
    })()""")
    wait('arrivalCaptions().length===0')
    assert js("""['FirstRecipient','SecondRecipient'].every(name=>document.querySelector(
      '#orrery [data-agent='+name+'] .orrery-caption-role').textContent==='Original role')""")


def test_mini_graph_remembers_both_states_across_loads(cockpit):
    js, wait, client, _, _ = cockpit
    wait("Boolean(document.querySelector('#mail .mailcards'))")
    client.call('Page.removeScriptToEvaluateOnNewDocument', identifier=js.storage_bootstrap)
    address = js('location.href')
    graph = "document.getElementById('orrery')"
    toggle = "document.getElementById('mailGraphBtn')"
    key = 'oc-mini-mail-graph'

    js('window.beforeGraphReload=true')
    client.call('Page.navigate', url=address)
    wait("!window.beforeGraphReload&&Boolean(document.querySelector('#mail .mailcards'))")
    assert not js(f"{graph}.hasAttribute('hidden')")
    for value in ('0', '1'):
        js(f"{toggle}.click()")
        assert js(f"localStorage.getItem('{key}')") == value
        js('window.beforeGraphReload=true')
        client.call('Page.navigate', url=address)
        wait("!window.beforeGraphReload&&Boolean(document.querySelector('#mail .mailcards'))")
        assert js(f"{toggle}.getAttribute('aria-expanded')") == str(value == '1').lower()
        assert js(f"{graph}.hasAttribute('hidden')") == (value == '0')


def test_old_local_mail_preferences_migrate_once_across_reloads(cockpit):
    js, wait, client, _, _ = cockpit
    wait("Boolean(document.querySelector('#mail .mailcards'))")
    client.call('Page.removeScriptToEvaluateOnNewDocument', identifier=js.storage_bootstrap)
    address = js('location.href')
    js("""localStorage.removeItem('oc-mail-layout-v1');
      localStorage.setItem('oc-mail-view','recipient');localStorage.setItem('oc-mini-mail-graph','0');""")
    client.call('Page.navigate', url=address)
    wait("document.getElementById('mailViewBtn')?.title==='Group by recipient'")
    assert js("localStorage.getItem('oc-mail-layout-v1')") == '1'
    assert js("document.getElementById('mailGraphBtn').getAttribute('aria-expanded')") == 'true'
    js("document.getElementById('mailViewBtn').click();document.getElementById('mailGraphBtn').click();")
    js('OrreryPrefs.flush()')
    client.call('Page.navigate', url=address)
    wait("document.getElementById('mailViewBtn')?.title==='Show thread timeline'")
    assert js("document.getElementById('mailGraphBtn').getAttribute('aria-expanded')") == 'false'


@pytest.mark.parametrize('cockpit',['disabled'],indirect=True)
def test_recipient_portraits_work_with_reader_off(cockpit):
    js, _ = prepare(cockpit)
    assert js("Boolean(groupFor('AuditNode').querySelector('.conversation-avatar'))")
    assert not js("conversationEnabled.checked")
    assert not js("[...document.querySelectorAll('link')].some(l=>l.getAttribute('href')==='conversation_view.css')")


def test_route_portraits_follow_the_roster_in_both_views_and_detail(cockpit):
    js, wait = prepare(cockpit, width=240)
    js("""currentAgents.push({name:'LaunchNode',provider:'anthropic',running:true});
      document.dispatchEvent(new Event('oc:agents'));
      document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[
        {id:202,sender:'BuildNode',recipients:['LaunchNode'],subject:'Reply',ts:2000000001,body_md:'Fixture reply'},
        {id:203,sender:'LaunchNode',subject:'Unaddressed',ts:2000000002,body_md:'Fixture notice'}
      ]}}));
      window.portraits=selector=>[...document.querySelectorAll(selector+' [data-mail-peer]')].map(slot=>[
        slot.dataset.mailPeer,slot.querySelector('.provider-badge img')?.getAttribute('src')||null
      ]);""")
    animated = [['LaunchNode', 'cockpit-assets/anthropic.svg'], ['BuildNode', 'cockpit-assets/openai.svg']]
    reply = list(reversed(animated))
    assert js("portraits('#mail .mail-assignee:nth-child(2) .mail-request')") == animated
    assert js("portraits('#mail .mail-reply:not([hidden])')") == reply
    assert js("groupFor('No direct recipient').querySelectorAll('.mail-route-recipients [data-mail-peer]').length") == 0

    js("document.getElementById('mailViewBtn').click()")
    assert js("portraits('.mail-timeline-replies')") == reply
    assert js("""[...document.querySelectorAll('.mail-route')].every(
      route=>route.scrollWidth<=route.clientWidth+1)""")
    assert js("document.querySelector('.mail-timeline-start .mail-route-more').title") == (
        'Other recipients: AuditNode, ExternalNode')
    js("document.querySelector('.mail-timeline-replies .mail-row-open').click()")
    wait("document.querySelector('.mail-md').textContent==='Fixture reply'")
    assert js("portraits('#mailSelectedRoute')") == reply
    assert js("portraits('.drawer-body')") == reply
    js("""currentAgents.find(a=>a.name==='BuildNode').provider='anthropic';
      document.dispatchEvent(new Event('oc:agents'));""")
    assert js("portraits('.drawer-body')[0]") == ['BuildNode', 'cockpit-assets/anthropic.svg']
