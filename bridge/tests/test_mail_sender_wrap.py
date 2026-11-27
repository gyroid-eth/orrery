"""Hold the Mail timeline's sender, recipient and time on one line."""
import json

import pytest

from test_conversation_review_regressions import cockpit, stable_roster


RECIPIENTS = ['RosyNewton', 'QuietCopernicus', 'MerryLovelace']


@pytest.mark.parametrize('width', [260, 460])
@pytest.mark.parametrize('size', [10, 12, 18])
def test_mail_route_and_time_share_line_at_each_rail_size(cockpit, width, size):
    js, wait, _, _, _ = cockpit
    stable_roster(js)
    wait("Boolean(document.querySelector('#mail .mailcards'))")
    sender = 'AReallyLongSyntheticSenderNameForMail' * 2
    recipient = 'AReallyLongSyntheticRecipientNameForMail' * 2
    messages = [
        dict(id=310, sender=sender, recipients=RECIPIENTS, subject='Multiple', ts=2000000000),
        dict(id=311, sender='ProOpus', recipients=[recipient], subject='Single', ts=2000000001),
    ]
    columns = f'250px minmax(0,1fr) {width}px'
    js("document.querySelector('.grid').style.gridTemplateColumns=" + json.dumps(columns) +
       ";const slider=document.getElementById('rightTextSize');slider.value=" + json.dumps(str(size)) +
       ";slider.dispatchEvent(new Event('input'));"
       "document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:" +
       json.dumps(messages) + "}}));")
    wait("document.querySelectorAll('.mail-timeline-start .mail-route').length===2")
    routes = js("""Object.fromEntries([...document.querySelectorAll('#mail .mail-request')].map(row=>{
      const line=row.querySelector('.mail-requester'), route=line.querySelector('.mail-route');
      const name=route.firstElementChild.lastElementChild, arrow=route.children[1];
      const recipient=route.querySelector('.mail-route-recipients .mail-peer > :last-child');
      const more=route.querySelector('.mail-route-more'), time=line.querySelector('time');
      const rect=el=>el.getBoundingClientRect(), center=el=>rect(el).top+rect(el).height/2;
      const label=el=>[el.textContent,el.parentElement.title,getComputedStyle(el).textOverflow,
        getComputedStyle(el).whiteSpace,el.scrollWidth>el.clientWidth];
      return [row.querySelector('.mail-subject').textContent,{
        sender:label(name), recipient:label(recipient), more:more&&[more.textContent,more.title],
        aligned:[name,arrow,recipient,...(more?[more]:[])].every(el=>Math.abs(center(el)-center(time))<=1),
        arrowGap:rect(recipient.parentElement).left-rect(arrow).right,
        overflow:route.scrollWidth>route.clientWidth+1||line.scrollWidth>line.clientWidth+1,
        timeRight:rect(time).right, lineRight:rect(line).right,
        size:getComputedStyle(line).fontSize,
      }];
    }))""")
    assert routes['Multiple']['sender'] == [sender, sender, 'ellipsis', 'nowrap', True]
    assert routes['Single']['recipient'] == [recipient, recipient, 'ellipsis', 'nowrap', True]
    assert routes['Multiple']['recipient'][:4] == [RECIPIENTS[0], RECIPIENTS[0], 'ellipsis', 'nowrap']
    assert routes['Multiple']['more'] == ['+2', 'Other recipients: ' + ', '.join(RECIPIENTS[1:])]
    assert routes['Single']['more'] is None
    for route in routes.values():
        assert route['aligned'] and not route['overflow']
        assert route['arrowGap'] == pytest.approx(5, abs=1)
        assert route['timeRight'] == pytest.approx(route['lineRight'], abs=1)
        assert route['size'] == f'{size}px'
    assert routes['Single']['timeRight'] == pytest.approx(routes['Multiple']['timeRight'], abs=1)

    js("""document.querySelector('.mail-row-open[aria-label*="Open request: Multiple"]').click()""")
    wait("Boolean(document.querySelector('.maildrawer:not([hidden]) .drawer-route'))")
    assert js("""[...document.querySelectorAll('.maildrawer .drawer-route .mail-route-recipients .mail-peer')]
        .map(peer=>peer.lastElementChild.textContent)""") == RECIPIENTS
