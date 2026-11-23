"""Both cockpit Mail bodies use the Reader's inert Markdown document renderer."""
import json

import pytest

from test_conversation_review_regressions import cockpit, stable_roster


PATH = '/fixture/export notes.md'
RAW_HTML = '<img src="/fixture/pixel" onerror="window.fixtureExecuted=true">'
BODY = '\n'.join([
    '## Export review', '',
    '| ' + ' | '.join(f'Column {i}' for i in range(1, 9)) + ' |',
    '| ' + ' | '.join(['---'] * 8) + ' |',
    '| **PDF** | high | keep | pass | crisp | vector | proof | archive |', '',
    '- Preserve the original.', '- Check `--scale 2`.', '',
    '```sh', 'export-chart --format pdf', '```', '',
    '[Reference](https://example.com/fixture)', f'[Export notes](<{PATH}>)', '',
    RAW_HTML, '<script>window.fixtureExecuted=true</script>',
    '[Unsafe](javascript:alert(1))', '![Remote image](https://example.com/fixture.png)',
])


@pytest.mark.parametrize('cockpit,view', [(False, 'reader'), ('disabled', 'drawer')], indirect=['cockpit'])
def test_mail_body_renders_safe_markdown_and_scrolls_wide_tables(cockpit, view):
    js, wait, _, requests, enable = cockpit
    stable_roster(js)
    js("""document.querySelector('.grid').style.gridTemplateColumns='250px minmax(0,1fr) 300px';
      window.mailPathHits=[];window.originalMailFetch=window.fetch;
      window.fetch=(url,options)=>String(url)==='/telemetry/conversation/path-probe'
        ?Promise.resolve(new Response(JSON.stringify({ok:true,paths:JSON.parse(options.body).texts.map(text=>{
          mailPathHits.push(text);return text===MAIL_PATH?{shown:text,path:text}:null;
        })}))):originalMailFetch(url,options);
      window.MAIL_PATH=""" + json.dumps(PATH) + ';window.mailText=' + json.dumps(BODY))
    if view == 'reader':
        enable(count=1)
        js("""conversationView.close();
          OrreryConversationSource.Source.prototype.read=async()=>({provider:'codex',mode:'cursor',after:'end',
            events:[{id:'mail-markdown',kind:'mail',role:'user',text:'',ts:'2026-11-09T13:20:00Z',
              mail:[{direction:'sent',subject:'Generated export notes',recipients:['FixturePeer'],body:mailText,coverage:'request'}]}]});
          conversationView.open();""")
        wait("Boolean(document.querySelector('.conversation-mail'))")
        js("document.querySelector('.conversation-mail').open=true;window.mailBody=document.querySelector('.conversation-mail-text')")
        assert js("mailBody.closest('details').querySelector('summary').textContent.includes('Generated export notes')")
    else:
        assert not js('conversationEnabled.checked')
        assert '/conversation_markdown.js' not in requests
        js("""document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[{id:317,
          sender:'FixturePeer',recipients:['ReviewFixture'],subject:'Generated export notes',
          body_md:mailText,excerpt:'Fixture export summary',ts:2000000001}]}}));""")
        wait("Boolean(document.querySelector('.mail-request'))")
        js("document.querySelector('.mail-request').click();window.mailBody=document.querySelector('.mail-md')")
        assert js("mailBody.previousElementSibling.textContent") == 'Generated export notes'
        assert not js('conversationEnabled.checked')

    wait("Boolean(mailBody.querySelector('a[data-local-path]'))")
    assert js("mailBody.querySelector('h2').textContent") == 'Export review'
    assert js("mailBody.querySelectorAll('thead th').length") == 8
    assert js("mailBody.querySelector('tbody strong').textContent") == 'PDF'
    assert js("mailBody.querySelectorAll('ul li').length") == 2
    assert js("mailBody.querySelector('li code').textContent") == '--scale 2'
    assert js("mailBody.querySelector('pre code').textContent") == 'export-chart --format pdf\n'
    assert js("mailBody.querySelector('a[href^=https]').href") == 'https://example.com/fixture'
    assert js("mailBody.querySelector('a[data-local-path]').dataset.localPath") == PATH
    assert js("mailBody.querySelector('a[data-local-path]').textContent") == 'Export notes'
    assert js("mailPathHits.includes(MAIL_PATH)")
    assert js('mailBody.textContent').count(RAW_HTML) == 1
    assert '<script>window.fixtureExecuted=true</script>' in js('mailBody.textContent')
    assert js("!mailBody.querySelector('img,script,[onerror],a[href^=javascript]')&&!window.fixtureExecuted")
    assert js("""(()=>{const table=mailBody.querySelector('.conversation-table-scroll'),style=getComputedStyle(table);
      const scroller=mailBody.closest('.drawer-scroll,.conversation-scroll');
      table.scrollLeft=80;
      return table.scrollWidth>table.clientWidth&&table.clientWidth<=mailBody.clientWidth&&
        scroller.scrollWidth<=scroller.clientWidth+1&&table.scrollLeft>0&&style.overflowX==='auto'&&table.tabIndex===0;
    })()""")
    if view == 'drawer':
        assert '/conversation_view.js' not in requests
        assert not any(path.startswith('/telemetry/conversation?') for path in requests)
        js("""window.mailOpened=null;revealLocalPath=(path,options)=>mailOpened={path,...options};
          mailBody.querySelector('a[data-local-path]').click()""")
        assert js('mailOpened') == {'path': PATH, 'literal': True}
        enable(count=1)
        assert requests.count('/conversation_markdown.js') == 1
        assert requests.count('/conversation_view.css') == 1
