"""An unchanged roster must not rebuild all Reader portrait text nodes."""
from test_reader_speaker import cockpit,prepare_speaker


def test_identical_identity_refresh_keeps_nodes_and_changed_provider_updates(cockpit):
    js,wait,_,_=prepare_speaker(cockpit)
    js("""window.identityChanges=0;window.identityObserver=new MutationObserver(records=>identityChanges+=records.length);
      identityObserver.observe(speakerReader.querySelector('.conversation-events'),{childList:true,subtree:true,characterData:true});
      document.dispatchEvent(new Event('oc:agents'));
    """)
    js('new Promise(resolve=>requestAnimationFrame(resolve))')
    assert js('identityChanges')==0
    js("identityObserver.disconnect();Object.assign(currentAgents[0],{program:'hermes',provider:'deepseek',model:'deepseek-v4',model_raw:'deepseek-v4'});document.dispatchEvent(new Event('oc:agents'))")
    # The historical recorded model keeps its maker; the unrecorded row follows the live maker.
    assert js("speakerReader.querySelector('[data-event-id=second] .provider-logo').getAttribute('src')")=='cockpit-assets/openai.svg'
    assert js("speakerReader.querySelector('[data-event-id=fallback] .provider-logo').getAttribute('src')")=='cockpit-assets/deepseek.svg'
