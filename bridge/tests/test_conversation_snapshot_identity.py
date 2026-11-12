"""Unchanged native snapshots must leave a selected Reader passage attached."""
import pytest

from test_conversation_review_regressions import cockpit
from test_conversation_inline_images import message, prepare


@pytest.mark.parametrize('mode', ['snapshot', 'fresh_tail'])
def test_unchanged_snapshot_keeps_selection_tool_focus_and_dom(cockpit, mode):
    events=[message('selected', 'A passage selected for a reference reply.'),
            dict(message('tool', 'read_file'), kind='tool'),
            dict(message('result', 'Recorded tool output.'), kind='tool_result'),
            message('last', 'Later reply.')]
    js, wait, _=prepare(cockpit, events)
    js("OrreryConversationSource.Source.prototype.read=async()=>({ok:true,agent:'ReviewFixture',mode:"+repr(mode)+",events:inlineEvents,after:'snapshot'});conversationView.refresh()")
    wait("document.querySelectorAll('.conversation-event').length===4")
    js("""window.readerPolls=0;
      OrreryConversationSource.Source.prototype.read=async()=>{readerPolls++;return {ok:true,agent:'ReviewFixture',mode:"""+repr(mode)+""",events:inlineEvents,after:'snapshot'}};
      const button=document.querySelector('.conversation-tool-group');button.click();button.focus();
      window.selectedTextNode=document.querySelector('[data-event-id=selected] .conversation-text').firstChild;
      const range=document.createRange();range.selectNodeContents(selectedTextNode);
      getSelection().removeAllRanges();getSelection().addRange(range);
      window.domChanges=0;window.snapshotObserver=new MutationObserver(records=>domChanges+=records.length);
      snapshotObserver.observe(document.querySelector('.conversation-events'),{subtree:true,childList:true,characterData:true});
      conversationView.refresh();
    """)
    wait('readerPolls>0')
    js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    assert js('domChanges')==0
    assert js('getSelection().toString()')=='A passage selected for a reference reply.'
    assert js('getSelection().anchorNode===selectedTextNode')
    assert js("document.activeElement.classList.contains('conversation-tool-group')")
    assert js("document.querySelector('.conversation-tool-group').getAttribute('aria-expanded')")=='true'
    js("snapshotObserver.disconnect();inlineEvents[0]={...inlineEvents[0],text:'Changed passage.'};conversationView.refresh()")
    wait("document.querySelector('[data-event-id=selected] .conversation-text').textContent==='Changed passage.'")
    assert js("document.querySelectorAll('.conversation-event').length")==4
