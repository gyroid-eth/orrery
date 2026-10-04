"""A session the backend ended (an EXIT) comes back (a RESUME): its tab
attaches again (Full tour recording: the child's tab stayed "closed ·
waiting…"). Putting it back in a split is left to the person."""
import pytest

from test_cockpit_tour import tour_browser  # noqa: F401  (static cockpit over CDP)

SETUP = """(()=>{
  window.__sent=[];window.send=m=>{window.__sent.push(m);return true;};
  for(const name of ['A','B','C']){ensureSessionGroup(name);attachedSessions.add(name);}
  handle({type:'sessions',sessions:['A','B','C']});
  replaceSplitSessions(['A','B']);splitVisible=true;
})()"""

STATE = """({split:[...splitSessions],
  attachB:window.__sent.some(m=>m&&m.type==='attach'&&m.session==='B'),
  detached:window.__sent.filter(m=>m&&m.type==='detach').map(m=>m.session),
  tabB:sessionGroups.has('B')})"""

BACK = "window.__sent.length=0;handle({type:'sessions',sessions:%s})"

CLEANUP = """(()=>{for(const n of [...occupiedSessions(),...sessionGroups.keys()])detachSession(n);
  manualDetached.clear();closedByBackend.clear();replaceSplitSessions([]);splitVisible=false;})()"""


@pytest.mark.parametrize('case', ['exit-then-resume', 'closed-twice', 'list-first', 'closed-by-hand'])
def test_a_session_the_backend_ended_comes_back_as_an_attached_tab(tour_browser, case):  # noqa: F811
    _, evaluate = tour_browser
    evaluate(SETUP)
    closed = "handle({type:'status',state:'closed',session:'B'})"
    if case == 'closed-by-hand':
        evaluate("detachSession('B',true)")
    elif case == 'closed-twice':
        evaluate(closed)
        evaluate(closed)
    elif case == 'list-first':
        # The session list without B arrives before closed does.
        evaluate("handle({type:'sessions',sessions:['A','C']})")
        evaluate(closed)
    else:
        evaluate(closed)
    mid = evaluate(STATE)
    evaluate(BACK % "['A','B','C']")
    after = evaluate(STATE)
    evaluate(CLEANUP)
    if case == 'closed-by-hand':
        assert not mid['tabB'] and not after['attachB'], (mid, after)
    else:
        assert mid['tabB'], mid
        # The tab attaches again; the split is the person's to change.
        assert after['attachB'] and after['split'] == ['A'], after


def test_with_the_cockpit_full_a_returning_session_displaces_nothing(tour_browser):  # noqa: F811
    _, evaluate = tour_browser
    evaluate(SETUP)
    evaluate("handle({type:'status',state:'closed',session:'B'})")
    full = evaluate("""(()=>{const extra=[];for(let i=0;occupiedSessions().size<MAX_ATTACHED_SESSIONS;i++){
      const n='X'+i;extra.push(n);ensureSessionGroup(n);attachedSessions.add(n);}return extra;})()""")
    names = ['A', 'B', 'C'] + full
    evaluate(BACK % repr(names).replace("'", '"'))
    after = evaluate(STATE)
    evaluate(CLEANUP)
    assert not after['attachB'] and after['detached'] == [], after


def test_a_return_that_could_not_attach_is_tried_again(tour_browser):  # noqa: F811
    # Review of #31: with the link down when the session came back, the note
    # was used up and the tab stayed closed for good.
    _, evaluate = tour_browser
    evaluate(SETUP)
    evaluate("handle({type:'status',state:'closed',session:'B'})")
    evaluate("window.send=m=>{window.__sent.push(m);return false;}")
    evaluate(BACK % "['A','B','C']")
    first = evaluate("({noted:closedByBackend.has('B'),requested:requestedSessions.has('B')})")
    evaluate("window.send=m=>{window.__sent.push(m);return true;}")
    evaluate(BACK % "['A','B','C']")
    after = evaluate(STATE)
    noted_after = evaluate("closedByBackend.has('B')")
    evaluate(CLEANUP)
    assert first == {'noted': True, 'requested': False}, first
    assert after['attachB'] and noted_after is False, after
