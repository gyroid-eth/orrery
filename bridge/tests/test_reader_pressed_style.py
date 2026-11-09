"""Reader state uses a subtle fill while keeping ordinary button borders."""
import json

import pytest
from test_pane_head_model import cockpit, prepare


@pytest.mark.parametrize('layout', ['single', 'split', 'window'])
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_reader_and_full_width_keep_the_subtle_pressed_fill(cockpit, layout, theme):
    js,wait,client=prepare(cockpit,'split' if layout=='split' else 'single')
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    if layout=='window':
        js("document.documentElement.classList.add('pane-window')")
    js("""modelHead.querySelectorAll('button').forEach(b=>b.style.transition='none');
      window.readerToggle=modelHead.querySelector('.conversation-toggle,.split-history-toggle');
      window.fullToggle=modelHead.querySelector('.conversation-expand');
      window.buttonStyle=b=>{const s=getComputedStyle(b);return {border:s.borderTopColor,background:s.backgroundColor,color:s.color}};
      window.fillProbe=document.createElement('span');fillProbe.style.background='rgb(var(--theme-accent-rgb) / .12)';modelHead.append(fillProbe);
      window.pressedFill=getComputedStyle(fillProbe).backgroundColor;fillProbe.remove();
      window.normalBorder=getComputedStyle(modelHead.querySelector('#panePopout,.split-pane-window')).borderTopColor;
      window.closedFill=buttonStyle(readerToggle).background;
      readerToggle.click();""")
    wait("fullToggle.hidden===false")
    assert js("readerToggle.getAttribute('aria-pressed')")=='true'
    assert js("fullToggle.getAttribute('aria-pressed')")=='false'
    assert js('buttonStyle(fullToggle).background')==js('closedFill')
    js('fullToggle.click()')
    for name in ['readerToggle','fullToggle']:
        assert js(name+".getAttribute('aria-pressed')")=='true'
        for interaction in ['normal','hover','focus']:
            js('document.activeElement?.blur()')
            client.call('Input.dispatchMouseEvent',type='mouseMoved',x=0,y=0)
            if interaction=='hover':
                rect=js('(()=>{const r='+name+'.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
                client.call('Input.dispatchMouseEvent',type='mouseMoved',**rect)
            elif interaction=='focus':
                client.call('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
                client.call('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
                js(name+'.focus()')
                assert js(name+".matches(':focus-visible')")
                assert js('getComputedStyle('+name+').outlineStyle')!='none'
            assert js('buttonStyle('+name+').border')==js('normalBorder')
            assert js('buttonStyle('+name+').background')==js('pressedFill')
            assert js('buttonStyle('+name+').background')!=js('closedFill')
    js('document.activeElement?.blur();fullToggle.click()')
    client.call('Input.dispatchMouseEvent',type='mouseMoved',x=0,y=0)
    assert js("fullToggle.getAttribute('aria-pressed')")=='false'
    assert js('buttonStyle(fullToggle).background')==js('closedFill')
    assert js('buttonStyle(readerToggle).background')==js('pressedFill')
    js('readerToggle.click()')
    assert js("readerToggle.getAttribute('aria-pressed')")=='false'
    assert js('buttonStyle(readerToggle).background')==js('closedFill')
    assert js('fullToggle.hidden')
