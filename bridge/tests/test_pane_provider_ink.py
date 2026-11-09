"""Measure the maker artwork itself, excluding any surrounding badge rim."""
import json

import pytest
from test_pane_head_model import cockpit, prepare, paint


CASES=[('anthropic','claude-code','Opus 5.5'),('openai','codex','GPT-6.1-Sol'),
       ('deepseek','dsh','DeepSeek V4'),('alibaba','hermes','Qwen3 32B'),('zai','hermes','GLM 4.7'),
       ('local','hermes','DeepSeek V4'),('local','hermes','Qwen3 32B'),('local','hermes','GLM 4.7')]


@pytest.mark.parametrize('layout',['single','split'])
@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('width',[1600,280])
def test_provider_artwork_has_a_consistent_visible_extent(cockpit,layout,theme,width):
    js,wait,client=prepare(cockpit,layout)
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=844,deviceScaleFactor=1,mobile=False)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    for provider,program,model in CASES:
        paint(js,dict(provider=provider,program=program,model=model,model_raw=model.lower(),running=True,act_state='wait'))
        wait("modelHead.querySelector('.pane-provider img').naturalWidth>0")
        ink=js("""(()=>{const img=modelHead.querySelector('.pane-provider img'),r=img.getBoundingClientRect(),canvas=document.createElement('canvas');
          canvas.width=canvas.height=256;const ctx=canvas.getContext('2d'),scale=256/Math.max(img.naturalWidth,img.naturalHeight),w=img.naturalWidth*scale,h=img.naturalHeight*scale;
          ctx.drawImage(img,(256-w)/2,(256-h)/2,w,h);const data=ctx.getImageData(0,0,256,256).data;
          let l=256,t=256,right=-1,bottom=-1;for(let y=0;y<256;y++)for(let x=0;x<256;x++)if(data[(y*256+x)*4+3]>=32){l=Math.min(l,x);t=Math.min(t,y);right=Math.max(right,x);bottom=Math.max(bottom,y)}
          return {extent:Math.max((right-l+1)*r.width/256,(bottom-t+1)*r.height/256),slot:modelHead.querySelector('.pane-provider').getBoundingClientRect().width};})()""")
        assert ink['slot']-1.5<=ink['extent']<=ink['slot']+.5,(provider,model,ink)
    paint(js,dict(provider='local',program='hermes',model='Custom model',model_raw='custom-model'))
    assert not js("!!modelHead.querySelector('.pane-provider img')")
    assert js("getComputedStyle(modelHead.querySelector('.pane-provider svg')).display")!='none'
    assert 'Local' in js("modelHead.querySelector('.pane-provider').getAttribute('aria-label')")
