"""A session the backend closed (an EXIT) comes back (a RESUME): its tab
attaches again and, if the split is as it was, it takes its old place
(Full tour recording: the child's tab stayed "closed · waiting…")."""
import json

import pytest

from test_cockpit_tour import tour_browser  # noqa: F401  (static cockpit over CDP)

SETUP = """(()=>{
  window.__sent=[];window.send=m=>{window.__sent.push(m);return true;};
  for(const name of ['A','B','C']){ensureSessionGroup(name);attachedSessions.add(name);}
  handle({type:'sessions',sessions:['A','B','C']});
  replaceSplitSessions(['A','B']);splitVisible=true;
})()"""

STATE = """({split:[...splitSessions],visible:splitVisible,
  attachB:window.__sent.some(m=>m&&m.type==='attach'&&m.session==='B'),
  tabB:sessionGroups.has('B')})"""


@pytest.mark.parametrize('case', ['exit-then-resume', 'closed-by-hand', 'split-changed', 'split-folded'])
def test_a_closed_session_coming_back(tour_browser, case):  # noqa: F811
    _, evaluate = tour_browser
    evaluate(SETUP)
    if case == 'closed-by-hand':
        evaluate("detachSession('B',true)")
    else:
        evaluate("handle({type:'status',state:'closed',session:'B'})")
    if case == 'split-changed':
        evaluate("replaceSplitSessions(['C','A'])")
    if case == 'split-folded':
        evaluate("replaceSplitSessions([]);splitVisible=false")
    mid = evaluate(STATE)
    evaluate("window.__sent.length=0;handle({type:'sessions',sessions:['A','B','C']})")
    after = evaluate(STATE)
    evaluate("for(const n of ['A','B','C']){detachSession(n);}replaceSplitSessions([]);splitVisible=false;")
    if case == 'exit-then-resume':
        assert mid['split'] == ['A'] and mid['tabB']
        assert after['split'] == ['A', 'B'] and after['attachB'], after
    elif case == 'closed-by-hand':
        # Closed by hand: no tab is left, and it is not brought back.
        assert not mid['tabB']
        assert after['split'] == ['A'] and not after['attachB'], after
    elif case == 'split-changed':
        # Its old place is gone: the tab attaches, the split is left alone.
        assert after['split'] == ['C', 'A'] and after['attachB'], after
    else:
        assert after['split'] == [] and not after['visible'] and after['attachB'], after
