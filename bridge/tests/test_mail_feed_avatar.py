"""Mail keeps sender names and packs recipients into registered portraits."""
import json
import pytest
from test_conversation_review_regressions import cockpit,stable_roster


def prepare(cockpit,width=840,theme='dark'):
    js,wait,client,requests,_=cockpit
    stable_roster(js);wait("document.querySelector('#mail .mailcards')!==null")
    names=['Aster','Brisk','Cobalt','Dione','Euler','Finch','Gauss']
    people=[dict(name='Sender',provider='anthropic',program='claude-code')]+[dict(name=n,provider='openai',program='codex') for n in names]
    recipients=[names[:1],names[:2]+['Missing'],names+['Missing']]
    messages=[dict(id=201+i,sender='Sender',recipients=r,subject=f'Generated update for {len(r)} recipients',importance='high' if i==0 else 'normal',ts=2000000000-i) for i,r in enumerate(recipients)]
    js('rosterAnnotationEpoch++;currentAgents='+json.dumps(people)+';window.avatarMessages='+json.dumps(messages)+";document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:avatarMessages}}));OrreryColorTheme.setPreference("+json.dumps(theme)+");document.querySelector('.grid').style.gridTemplateColumns="+json.dumps(f'250px minmax(0,1fr) {width}px')+";document.querySelectorAll('#mail .msg').forEach(c=>{c.style.animation='none';c.style.opacity='1';c.style.transform='none'});")
    js('document.fonts.ready')
    assert abs(js("document.querySelector('.col.mail').getBoundingClientRect().width")-width)<1
    return js,wait,client,messages


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('width',[840,380,240])
def test_sender_priority_and_adaptive_recipient_portraits(cockpit,theme,width):
    js,wait,_,messages=prepare(cockpit,width,theme)
    assert js("document.querySelectorAll('#mail .conversation-avatar').length>0")
    for message in messages:
        js('window.avatarCard=document.querySelector(\'#mail .msg[data-mid="'+str(message['id'])+'"]\')')
        assert js("avatarCard.querySelector('.from .conversation-avatar').getBoundingClientRect().width")==18
        assert js("getComputedStyle(avatarCard.querySelector('.conversation-avatar')).userSelect")=='none'
        assert js("avatarCard.querySelector('.from .mail-peer-name').scrollWidth<=avatarCard.querySelector('.from .mail-peer-name').clientWidth+1")
        assert js("avatarCard.querySelector('.to').getAttribute('aria-label')")==', '.join(message['recipients'])
        assert js("avatarCard.querySelector('.to').title")==', '.join(message['recipients'])
        compact=len(message['recipients'])>1 and (width==240 or (len(message['recipients'])==8 and width<840))
        wait("avatarCard.querySelector('.to').classList.contains('is-stacked')==="+json.dumps(compact))
        if compact:
            shown=js("avatarCard.querySelectorAll('.to .mail-peer:not([hidden])').length")
            assert js("avatarCard.querySelector('.mail-more').textContent")=='+'+str(len(message['recipients'])-shown)
            assert js("[...avatarCard.querySelectorAll('.to .mail-peer:not([hidden])')].every(p=>!!p.querySelector('.conversation-avatar'))")
            assert js("avatarCard.querySelector('.to .mail-peer[data-peer-name=Missing]').hidden")
        else:
            assert js("avatarCard.querySelector('.mail-more').hidden")
        assert js("(()=>{const h=avatarCard.querySelector('.mtop'),b=h.querySelector('.imp'),r=h.getBoundingClientRect(),s=b.getBoundingClientRect();return h.scrollWidth<=h.clientWidth+1&&s.right<=r.right+1&&s.left>=r.left})()")
        assert not js("avatarCard.querySelector('.mail-peer[data-peer-name=Missing] .conversation-avatar')")


def test_resize_and_roster_refresh_preserve_card_and_focus(cockpit):
    js,wait,_,_=prepare(cockpit)
    js("window.keptAvatarCard=document.querySelector('#mail .msg[data-mid=\"203\"]');keptAvatarCard.focus();document.querySelector('.grid').style.gridTemplateColumns='250px minmax(0,1fr) 380px'")
    wait("keptAvatarCard.querySelector('.to').classList.contains('is-stacked')")
    js("currentAgents=currentAgents.filter(a=>a.name!=='Aster');document.dispatchEvent(new Event('oc:agents'))")
    assert not js("keptAvatarCard.querySelector('[data-peer-name=Aster] .conversation-avatar')")
    assert js('document.activeElement===keptAvatarCard')
    js("document.querySelector('.grid').style.gridTemplateColumns='250px minmax(0,1fr) 840px'")
    wait("!keptAvatarCard.querySelector('.to').classList.contains('is-stacked')")
    assert js("keptAvatarCard===document.querySelector('#mail .msg[data-mid=\"203\"]')&&document.activeElement===keptAvatarCard")


@pytest.mark.parametrize('registered',[True,False])
def test_compact_recipients_count_every_hidden_or_unknown_peer(cockpit,registered):
    js,wait,_,_=prepare(cockpit,380)
    names=['Aster','Brisk','Cobalt','Dione','Euler','Finch','Gauss','Hopper'] if registered else ['Missing'+str(i) for i in range(8)]
    js("currentAgents.push({name:'Hopper',provider:'anthropic'});document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[{id:204,sender:'Sender',recipients:"+json.dumps(names)+",subject:'Generated count case',importance:'normal',ts:2000000001}]}}))")
    wait("document.querySelector('#mail .msg[data-mid=\"204\"] .to.is-stacked')!==null")
    js("window.countCard=document.querySelector('#mail .msg[data-mid=\"204\"]')")
    assert js("countCard.querySelectorAll('.to .mail-peer:not([hidden])').length")==(8 if registered else 0)
    assert js("countCard.querySelector('.mail-more').hidden")==registered
    if not registered:
        assert js("countCard.querySelector('.mail-more').textContent")=='+8'
        assert not js("countCard.querySelector('.to .conversation-avatar')")


@pytest.mark.parametrize('cockpit',['disabled'],indirect=True)
def test_reader_disabled_avatar_fallback_is_excluded_from_copy(cockpit):
    js,wait,_,_=prepare(cockpit,380)
    wait("document.querySelector('#mail .conversation-avatar .face img')?.style.display==='none'")
    js("document.querySelectorAll('#mail .conversation-avatar .ini').forEach(n=>n.textContent='AVATAR_SENTINEL');const r=document.createRange();r.selectNodeContents(document.querySelector('#mail .mailcards'));getSelection().removeAllRanges();getSelection().addRange(r)")
    assert 'AVATAR_SENTINEL' not in js('getSelection().toString()')
    assert not js('conversationEnabled.checked')
    assert not js("[...document.querySelectorAll('link')].some(l=>l.getAttribute('href')==='conversation_view.css')")
