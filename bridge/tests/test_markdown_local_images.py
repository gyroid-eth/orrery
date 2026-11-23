"""Reader Markdown images use the validated local preview route."""
import json
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conversation_preview import PreviewUnavailable, clicked_path
from test_conversation_review_regressions import cockpit, stable_roster


def reply(path):
    try:
        return {'ok': True, **clicked_path(path)}
    except PreviewUnavailable as error:
        return {'ok': False, 'error': str(error)}


def prepare(cockpit, text, previews, *, delayed=False, report=None):
    js, wait, client, _, enable = cockpit
    stable_roster(js)
    js('window.fixtures='+json.dumps(previews)+';window.reportPath='+json.dumps(report)+';window.delayImage='+json.dumps(delayed)+''';
      window.previewPosts=[];window.originalFixtureFetch=window.fetch;
      window.fetch=(url,options)=>{
        if(url==='/telemetry/conversation/path-image'){
          const payload=JSON.parse(options.body);
          const {method,signal,backgroundPreview}=options;
          previewPosts.push({method,signal,payload,backgroundPreview,userRequest:OrreryConversation.userRequest(url,options)});
          const data=fixtures[payload.path];
          const result=()=>new Response(JSON.stringify(data),{status:data.ok?200:400});
          if(delayImage)return new Promise(resolve=>window.finishImage=()=>resolve(result()));
          return Promise.resolve(result());
        }
        if(url==='/telemetry/conversation/path-probe'){
          const paths=JSON.parse(options.body).texts.map(text=>text===reportPath?{shown:text,path:text}:null);
          return Promise.resolve(new Response(JSON.stringify({ok:true,paths})));
        }
        return originalFixtureFetch(url,options);
      };''')
    enable(count=1)
    js('conversationView.close();window.fixtureText='+json.dumps(text)+''';
      OrreryConversationSource.Source.prototype.read=async()=>({provider:'codex',mode:'cursor',after:'tail',events:[{
        id:'markdown-image',kind:'text',role:'assistant',text:fixtureText,ts:'2026-11-23T13:00:00Z'
      }]});
      conversationView.open();''')
    wait("Boolean(document.querySelector('[data-event-id=markdown-image]'))")
    return js, wait, client


def test_inline_image_uses_validated_png_and_opens_the_existing_preview(cockpit, tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    path = '~/Tall chart.png'
    missing = str(tmp_path / 'missing.png')
    oversize = tmp_path / 'over-limit.png'
    with oversize.open('wb') as out:
        out.truncate(8 * 1024 * 1024 + 1)
    Image.new('RGB', (650, 1200), '#83aacd').save(tmp_path / 'Tall chart.png')
    text = (f'![Tall chart](<{path}>)\n\n![Missing]({missing})\n\n![Too large]({oversize})'
            '\n\n![Remote chart](https://fixture.invalid/never.png)'
            '\n\n<img src="https://fixture.invalid/raw.png" onerror="window.rawImageRan=true">')
    js, wait, _ = prepare(cockpit, text, {value: reply(value) for value in (path, missing, str(oversize))})
    wait("document.querySelector('[data-markdown-image=\"Tall chart\"] img')?.naturalHeight>320&&previewPosts.length>=3")
    assert js("""(()=>{const link=document.querySelector('[data-markdown-image="Tall chart"]'),image=link.querySelector('img');
      const rect=image.getBoundingClientRect(),body=link.closest('.conversation-text');
      return image.alt==='Tall chart'&&image.src.startsWith('blob:')&&
        rect.height>0&&rect.height<=320&&rect.width<=body.clientWidth;
    })()""")
    assert js("document.querySelector('[data-markdown-image=Missing] .markdown-image-label').textContent") == f'Missing · {missing}'
    assert js("document.querySelector('[data-markdown-image=\"Too large\"] .markdown-image-label').textContent") == f'Too large · {oversize}'
    assert js("!document.querySelector('[data-markdown-image=Missing] img').hasAttribute('src')")
    assert js("!document.querySelector('[data-markdown-image=\"Too large\"] img').hasAttribute('src')")
    assert js("[...document.querySelectorAll('.conversation-text a[href^=https]')].some(a=>a.textContent==='Remote chart · https://fixture.invalid/never.png')")
    assert '<img src="https://fixture.invalid/raw.png" onerror="window.rawImageRan=true">' in js("document.querySelector('.conversation-text').textContent")
    assert js("!document.querySelector('.conversation-text img[onerror]')&&!window.rawImageRan")
    assert js("performance.getEntriesByType('resource').every(entry=>!entry.name.startsWith('https://fixture.invalid/'))")
    assert js("previewPosts.every(call=>call.method==='POST'&&Object.keys(call.payload).join(',')==='path')")
    assert js('previewPosts.every(call=>call.backgroundPreview===true&&!call.userRequest)')

    js("document.querySelector('[data-markdown-image=\"Tall chart\"]').click()")
    wait("document.querySelector('.conversation-preview-image')?.naturalHeight>0")
    assert js("document.querySelector('.conversation-preview-title').textContent") == 'Tall chart.png'
    assert js('previewPosts.at(-1).payload.path') == path
    assert js('previewPosts.at(-1).userRequest')
    js("document.querySelector('[data-markdown-image=Missing]').click()")
    wait("document.querySelector('.conversation-preview-notice')?.textContent.length>0")
    assert js("document.querySelector('.conversation-preview-text').textContent") == missing


def test_local_images_in_markdown_file_preview_share_the_same_action(cockpit, tmp_path):
    path = str(tmp_path / 'chart.png')
    report = str(tmp_path / 'report.md')
    Image.new('RGB', (640, 400), '#61c1ab').save(path)
    previews = {path: reply(path), report: {'ok': True, 'kind': 'text', 'text': f'# Report\n\n![Chart]({path})'}}
    js, wait, _ = prepare(cockpit, f'[Report]({report})', previews, report=report)
    wait("Boolean(document.querySelector('.conversation-text [data-local-path]'))")
    js("document.querySelector('.conversation-text [data-local-path]').click()")
    wait("document.querySelector('.conversation-preview-markdown [data-markdown-image] img')?.naturalWidth===640")
    js("document.querySelector('.conversation-preview-markdown [data-markdown-image]').click()")
    wait("document.querySelector('.conversation-preview-image')?.naturalWidth===640")
    assert js('previewPosts.map(call=>call.payload.path)') == [report, path, path]


def test_closing_reader_aborts_a_pending_markdown_image(cockpit, tmp_path):
    path = str(tmp_path / 'chart.png')
    Image.new('RGB', (640, 400), '#61c1ab').save(path)
    js, wait, _ = prepare(cockpit, f'![Chart]({path})', {path: reply(path)}, delayed=True)
    wait('Boolean(window.finishImage)')
    js("""window.createdImages=0;const create=URL.createObjectURL.bind(URL);
      URL.createObjectURL=blob=>{createdImages++;return create(blob);};
      conversationView.close();finishImage();""")
    assert js('previewPosts[0].signal.aborted')
    assert js('createdImages') == 0
