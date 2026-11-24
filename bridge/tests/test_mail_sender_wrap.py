"""Verify sender sizing and recipient wrapping in the Mail timeline."""
import json

import pytest

from test_conversation_review_regressions import cockpit, stable_roster


RECIPIENTS = ['RosyNewton', 'QuietCopernicus', 'MerryLovelace']


@pytest.mark.parametrize('sender,recipients,width,clipped', [
    ('ProOpus', RECIPIENTS[:1], 306, False),
    ('ProOpus', RECIPIENTS, 306, False),
    ('AReallyLongSyntheticSenderNameForMail', RECIPIENTS[:1], 306, True),
    ('ProOpus', RECIPIENTS, 210, False),
], ids=['single-recipient', 'three-recipients', 'long-sender', 'narrow-rail'])
def test_sender_keeps_one_line_in_timeline(cockpit, sender, recipients, width, clipped):
    js, wait, _, _, _ = cockpit
    stable_roster(js)
    wait("Boolean(document.querySelector('#mail .mailcards'))")
    message = dict(id=310, sender=sender, recipients=recipients,
                   subject='Verify the fixture layout', ts=2000000000)
    columns = f'250px minmax(0,1fr) {width}px'
    js("document.querySelector('.grid').style.gridTemplateColumns=" + json.dumps(columns) +
       ";document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[" +
       json.dumps(message) + "]}}));")
    wait("Boolean(document.querySelector('.mail-timeline-start .mail-route'))")
    route = js("""(()=>{
      const route=document.querySelector('.mail-timeline-start .mail-route');
      const peer=route.firstElementChild,name=peer.lastElementChild,style=getComputedStyle(name);
      const targets=[...route.querySelectorAll('.mail-route-recipients .mail-peer')];
      return {name:name.textContent,title:name.title,ellipsis:style.textOverflow==='ellipsis',
        oneLine:name.getBoundingClientRect().height<=parseFloat(style.lineHeight)+1,
        clipped:name.scrollWidth>name.clientWidth,overflow:route.scrollWidth>route.clientWidth+1,
        recipients:targets.map(p=>[p.lastElementChild.textContent,p.lastElementChild.title,
          getComputedStyle(p.lastElementChild).whiteSpace]),
        recipientRows:new Set(targets.map(p=>p.getBoundingClientRect().top)).size};
    })()""")
    assert route['name'] == route['title'] == sender
    assert route['ellipsis'] and route['oneLine']
    assert route['clipped'] is clipped
    assert not route['overflow']
    assert route['recipients'] == [[recipient, recipient, 'nowrap'] for recipient in recipients]
    assert route['recipientRows'] == len(recipients)
