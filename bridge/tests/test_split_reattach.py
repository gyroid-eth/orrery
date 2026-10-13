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


@pytest.mark.parametrize('session_gone,tab_remains', [
    ('true', False),
    ('false', True),
    ('undefined', True),
])
def test_closed_removes_the_session_group_only_when_tmux_confirmed_it_is_gone(  # noqa: F811
    tour_browser, session_gone, tab_remains
):
    _, evaluate = tour_browser
    evaluate(SETUP)
    state = evaluate(f"""(()=>{{
      const msg={{type:'status',state:'closed',session:'B'}};
      if({session_gone}!==undefined)msg.sessionGone={session_gone};
      handle(msg);
      return {{tab:sessionGroups.has('B'),noted:closedByBackend.has('B'),
        split:[...splitSessions],attached:attachedSessions.has('B')}};
    }})()""")
    evaluate(CLEANUP)
    assert state['tab'] is tab_remains, state
    assert state['noted'] is tab_remains, state
    assert state['split'] == ['A'], state
    assert state['attached'] is False, state


def test_a_gone_session_can_be_opened_again_under_the_same_name(tour_browser):  # noqa: F811
    _, evaluate = tour_browser
    evaluate(SETUP)
    evaluate("handle({type:'status',state:'closed',session:'B',sessionGone:true})")
    gone = evaluate("sessionGroups.has('B')")
    evaluate("handle({type:'sessions',sessions:['A','C']})")
    evaluate("handle({type:'sessions',sessions:['A','B','C']})")
    state = evaluate("""(()=>{
      const requested=requestAttach('B',true);
      handle({type:'reset',session:'B',panes:[]});
      return {requested,group:sessionGroups.has('B'),attached:attachedSessions.has('B')};
    })()""")
    evaluate(CLEANUP)
    assert gone is False
    assert state == {'requested': True, 'group': True, 'attached': True}


@pytest.mark.parametrize('closed_incarnation,group_remains', [('old', True), ('new', False)])
def test_old_output_new_reset_then_closed_cannot_remove_a_different_incarnation(
    tour_browser, closed_incarnation, group_remains
):
    _, evaluate = tour_browser
    evaluate(SETUP)
    state = evaluate(f"""(()=>{{
      handle({{type:'reset',session:'B',panes:[],incarnation:'old'}});
      // The wire ordering from the shared peer-lock race in the backend test.
      handle({{type:'output',session:'B',data:'old final bytes'}});
      handle({{type:'reset',session:'B',panes:[],incarnation:'new'}});
      handle({{type:'status',state:'closed',session:'B',sessionGone:true,
        incarnation:'{closed_incarnation}'}});
      return {{group:sessionGroups.has('B'),attached:attachedSessions.has('B'),
        noted:closedByBackend.has('B')}};
    }})()""")
    evaluate(CLEANUP)
    assert state == {'group': group_remains, 'attached': group_remains, 'noted': False}


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


def test_a_slot_freed_by_the_same_list_is_there_for_the_return(tour_browser):  # noqa: F811
    # Review of #31: the list that brings B back also drops C; with the
    # cockpit full, B was judged before C left and stayed closed (the
    # backend sends a list only when it changes).
    _, evaluate = tour_browser
    evaluate(SETUP)
    evaluate("handle({type:'status',state:'closed',session:'B'})")
    full = evaluate("""(()=>{const extra=[];for(let i=0;occupiedSessions().size<MAX_ATTACHED_SESSIONS;i++){
      const n='X'+i;extra.push(n);ensureSessionGroup(n);attachedSessions.add(n);}return extra;})()""")
    evaluate(BACK % repr(['A', 'B'] + full).replace("'", '"'))
    after = evaluate(STATE)
    evaluate(CLEANUP)
    assert after['attachB'] and 'C' in after['detached'], after
