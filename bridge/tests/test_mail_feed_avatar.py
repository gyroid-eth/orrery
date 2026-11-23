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
        group=>group.querySelector('.mail-assignee-name > :last-child').textContent===name);
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
        group.querySelector('.mail-request').getAttribute('aria-label').endsWith('high importance'))""")


def test_roster_refresh_keeps_focused_assignment_and_drops_stale_portrait(cockpit):
    js, _ = prepare(cockpit)
    js("""window.keptGroup=groupFor('BuildNode');window.keptRequest=keptGroup.querySelector('.mail-request');
      keptRequest.focus();currentAgents=currentAgents.filter(agent=>agent.name!=='BuildNode');
      document.dispatchEvent(new Event('oc:agents'));""")
    assert js("document.activeElement===keptRequest&&keptGroup===groupFor('BuildNode')")
    assert js("keptGroup.querySelector('.conversation-avatar')") is None
    assert js("Boolean(keptGroup.querySelector('.mail-assignee-fallback'))")


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
    assert js("portraits('.mail-timeline-start').find(peer=>peer[0]==='ExternalNode')") == ['ExternalNode', None]
    js("document.querySelector('.mail-timeline-replies button').click()")
    wait("document.querySelector('.mail-md').textContent==='Fixture reply'")
    assert js("portraits('#mailSelectedRoute')") == reply
    assert js("portraits('.drawer-body')") == reply
    js("""currentAgents.find(a=>a.name==='BuildNode').provider='anthropic';
      document.dispatchEvent(new Event('oc:agents'));""")
    assert js("portraits('.drawer-body')[0]") == ['BuildNode', 'cockpit-assets/anthropic.svg']
