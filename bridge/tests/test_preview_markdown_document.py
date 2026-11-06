"""The file preview's Markdown document view (conversation_markdown.js renderDocument).

Runs in node with a minimal DOM that serializes what the renderer built. Every
text reaches it as a text node, so a `<` in the output is always markup the
renderer made itself, never the file's.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MARKDOWN = Path(__file__).resolve().parents[1] / 'conversation_markdown.js'

DOM = r"""
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
class Text{constructor(t){this.data=String(t);}get textContent(){return this.data;}html(){return esc(this.data);}}
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.className='';this.dataset={};this.style={};this.attrs={};}
  appendChild(c){this.children.push(c);return c;}
  append(...c){c.forEach(x=>this.appendChild(x));}
  setAttribute(k,v){this.attrs[k]=String(v);}
  addEventListener(){}
  set textContent(t){this.children=[new Text(t)];}
  get textContent(){return this.children.map(c=>c.textContent).join('');}
  html(){
    const a=[];if(this.className)a.push(`class="${esc(this.className)}"`);
    for(const k of ['href','target','rel','title','start'])if(this[k]!==undefined&&this[k]!=='')a.push(`${k}="${esc(this[k])}"`);
    for(const [k,v] of Object.entries(this.dataset))a.push(`data-${k}="${esc(v)}"`);
    return `<${this.tag}${a.length?' '+a.join(' '):''}>`+this.children.map(c=>c.html()).join('')+`</${this.tag}>`;
  }
}
globalThis.document={createElement:t=>new Element(t),createTextNode:t=>new Text(t)};
require(process.argv[1]);
const md=globalThis.OrreryConversationMarkdown;
const show=text=>md.renderDocument(text,new Element('div')).children.map(c=>c.html()).join('\n');
"""


def run(body, *args):
    if shutil.which('node') is None:
        pytest.skip('node is not installed')
    result = subprocess.run(['node', '-e', DOM + body, str(MARKDOWN), *args], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return result.stdout


def html(text):
    return json.loads(run('console.log(JSON.stringify(show(process.argv[2])));', text))


def test_blocks_are_drawn():
    out = html('# Title\n\nA paragraph\nnext line.\n\n## Section ##\n\n- one\n- two\n  - nested\n\n3. three\n4. four\n\n'
               '> quoted **bold**\n\n---\n\n```py\nx = 1 < 2\n```\n\n    indented code\n\n- [ ] todo\n- [x] done\n')
    assert out.split('\n')[:3] == ['<h1 class="markdown-heading">Title</h1>', '<p>A paragraph', 'next line.</p>']
    assert '<h2 class="markdown-heading">Section</h2>' in out
    assert '<ul><li>one</li>\n<li>two' not in out                    # one element per block
    assert '<ul><li>one</li><li>two<ul><li>nested</li></ul></li></ul>' in out
    assert '<ol start="3"><li>three</li><li>four</li></ol>' in out
    assert '<blockquote><p>quoted <strong>bold</strong></p></blockquote>' in out
    assert '<hr></hr>' in out
    assert '<pre class="markdown-code" data-language="py"><code>x = 1 &lt; 2</code></pre>' in out
    assert '<pre class="markdown-code"><code>indented code</code></pre>' in out
    assert ('<ul><li class="markdown-task" data-checked="false"><span class="markdown-task-box">☐ </span>todo</li>'
            '<li class="markdown-task" data-checked="true"><span class="markdown-task-box">☑ </span>done</li></ul>') in out


def test_inline_marks_are_drawn():
    out = html('Use `a <b>` and **strong** and *em* and _em2_ and ~~gone~~ and snake_case_name and \\*literal\\*.')
    assert out == ('<p>Use <code>a &lt;b&gt;</code> and <strong>strong</strong> and <em>em</em> and <em>em2</em>'
                   ' and <del>gone</del> and snake_case_name and *literal*.</p>')


def test_a_table_is_drawn_with_inline_marks_in_cells():
    out = html('| Name | Value |\n|:-----|------:|\n| `a` | **1** |\n| b |\n')
    assert '<th>Name</th><th>Value</th>' in out
    assert '<td><code>a</code></td><td><strong>1</strong></td>' in out
    assert '<td>b</td><td></td>' in out                              # a short row is padded
    assert 'Copy Markdown' in out


def test_front_matter_stays_text():
    out = html('---\ntitle: Note\ntags: [a]\n---\n# Body\n')
    assert out.split('\n')[0] == '<pre class="markdown-code markdown-front-matter"><code>---'
    assert '<h1 class="markdown-heading">Body</h1>' in out


@pytest.mark.parametrize('source', [
    '<script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
    '<a href="javascript:alert(1)">x</a>',
    '<svg onload=alert(1)></svg>',
    '<iframe src="https://example.com"></iframe>',
])
def test_raw_html_is_text(source):
    out = html(source + '\n\nafter')
    assert out == '<p>' + source.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;') + '</p>\n<p>after</p>'


@pytest.mark.parametrize('target', [
    'javascript:alert%281%29', 'JaVaScRiPt:void0', 'data:text/html,x', 'vbscript:x', 'file:///etc/passwd',
    'other.md', '../secret.md', '#anchor', '//example.com/x',
])
def test_an_unsafe_or_relative_link_is_not_a_link(target):
    out = html(f'[label]({target})')
    assert '<a' not in out
    assert out == f'<p><span class="markdown-link-text" title="{target}">label</span></p>'


def test_a_target_with_parentheses_stays_text():
    assert html('[label](javascript:alert(1))') == '<p>[label](javascript:alert(1))</p>'


def test_safe_links_open_in_a_new_tab_without_referrer():
    out = html('[site](https://example.com/a?b=1) <https://example.org> [mail](mailto:a@example.com)')
    assert '<a href="https://example.com/a?b=1" target="_blank" rel="noopener noreferrer" title="https://example.com/a?b=1">site</a>' in out
    assert '<a href="https://example.org/" target="_blank" rel="noopener noreferrer" title="https://example.org/">https://example.org</a>' in out
    assert '<a href="mailto:a@example.com"' in out


def test_an_image_is_a_label_and_is_never_fetched():
    out = html('![chart](https://example.com/x.png) ![](local.png)')
    assert out == ('<p><span class="markdown-image" title="https://example.com/x.png">[image: chart]</span>'
                   ' <span class="markdown-image" title="local.png">[image]</span></p>')
    assert '<img' not in out


def test_deep_nesting_and_unclosed_marks_stay_bounded():
    out = html('>' * 50 + ' deep\n\n' + '**' * 5000 + '\n\n' + '`' * 3001 + '\n\n' + '*a' * 20000)
    assert out.count('<blockquote>') == 8                             # then text
    assert '&gt;' in out


def test_a_large_file_renders_quickly():
    body = r"""
const parts=[];
for(let i=0;i<1400;i++)parts.push('## Section '+i+'\n\nSome *text* with `code` and a [link](https://example.com/'+i+').\n\n- a\n- b\n\n| x | y |\n|---|---|\n| 1 | 2 |\n');
const text=parts.join('\n').slice(0,131072);
const t=process.hrtime.bigint();show(text);const ms=Number(process.hrtime.bigint()-t)/1e6;
const worst=('*a _b `c [d '.repeat(12000)).slice(0,131072);
const t2=process.hrtime.bigint();show(worst);const ms2=Number(process.hrtime.bigint()-t2)/1e6;
console.log(JSON.stringify({bytes:text.length,ms,worst:ms2}));
"""
    result = json.loads(run(body))
    assert result['bytes'] > 100000
    assert result['ms'] < 1000 and result['worst'] < 1000, result


def test_the_conversation_table_rendering_is_unchanged():
    out = json.loads(run("const h=new Element('div');md.render('a <b>\\n| x | y |\\n|---|---|\\n| **1** | 2 |\\n',h);"
                         "console.log(JSON.stringify(h.children.map(c=>c.html()).join('')));"))
    assert out.startswith('<span>a &lt;b&gt;\n</span><div class="conversation-table">')
    assert '<td>**1**</td>' in out                                    # cells stay text in the conversation


# In the cockpit: a .md file preview, its Source switch, and other text files.
import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_conversation_review_regressions import cockpit  # noqa: E402,F401

SAMPLE = ('# Generated note\\n\\n| Step | State |\\n|---|---|\\n| build | **ok** |\\n\\n'
          '<img src=https://example.test/never onerror="window.pwned=1">\\n\\n'
          '[bad](javascript:void0) [good](https://example.com/)\\n')


def open_preview(js, wait, label):
    js("""window.previewRequests=[];OrreryConversationSource.Source.prototype.reference=async(ref,options)=>{
      previewRequests.push(ref);return {ok:true,kind:'text',text:'""" + SAMPLE + """'};};
      OrreryConversationSource.Source.prototype.read=async()=>({mode:'cursor',events:[{id:'artifacts',kind:'tool',role:'assistant',text:'functions.exec',
        references:[{id:'A'.repeat(32),label:""" + json.dumps(label) + """,kind:'file'}]}],before:'file:0',after:'file:1',has_older:false});
      conversationView.close();conversationView.open();""")
    wait("document.querySelector('.conversation-file')!==null")
    js("document.querySelector('.conversation-file').click()")
    wait("document.querySelector('.conversation-preview-content').textContent.includes('Generated note')")


def test_a_markdown_preview_is_a_document_with_a_source_switch(cockpit):  # noqa: F811
    js, wait, client, requests, enable = cockpit
    enable(mode='cursor', count=2)
    open_preview(js, wait, 'NOTES.md')
    body = "document.querySelector('.conversation-preview-content')"
    assert js(body + ".querySelector('h1').textContent") == 'Generated note'
    assert js(body + ".querySelector('td strong').textContent") == 'ok'
    assert js(body + ".querySelectorAll('img,script,iframe,[onerror]').length") == 0
    assert js(body + ".textContent.includes('<img src=https://example.test/never')")
    assert js("window.pwned===undefined")
    assert js(body + ".querySelectorAll('a').length") == 1
    assert js(body + ".querySelector('a').rel") == 'noopener noreferrer'
    assert js(body + ".querySelector('a').target") == '_blank'
    source = "document.querySelector('.conversation-preview-source')"
    assert js(source + ".getAttribute('aria-pressed')") == 'false'
    js(source + ".click()")
    assert js(body + ".querySelector('.conversation-preview-text').textContent.startsWith('# Generated note')")
    assert js(body + ".querySelector('h1')") is None
    assert js(source + ".getAttribute('aria-pressed')") == 'true'
    # The reader keeps the choice for the next .md it opens, then switches back.
    js("document.querySelector('.conversation-file').click()")
    wait("document.querySelector('.conversation-preview-source')!==null&&previewRequests.length===2")
    wait(body + ".querySelector('.conversation-preview-text')!==null")
    js(source + ".click()")
    assert js(body + ".querySelector('h1').textContent") == 'Generated note'


@pytest.mark.parametrize('label', ['notes.txt', 'page.html', 'README.md.txt'])
def test_other_text_files_stay_plain_text(cockpit, label):  # noqa: F811
    js, wait, client, requests, enable = cockpit
    enable(mode='cursor', count=2)
    open_preview(js, wait, label)
    assert js("document.querySelector('.conversation-preview-text').textContent.startsWith('# Generated note')")
    assert js("document.querySelector('.conversation-preview-source')") is None
    assert js("document.querySelectorAll('.conversation-preview-content h1,.conversation-preview-content img').length") == 0


# Review r1: one long line must not make a block or inline pattern backtrack
# over itself (a 128 KiB '#' line with spaces took 35.6 s and froze the tab).
LONG_LINES = {
    'heading-spaces': "'# a'+' '.repeat(N)+'b'",
    'heading-after-paragraph': "'para\\n# a'+' '.repeat(N)+'b'",
    'heading-tabs': "'# a'+'\\t'.repeat(N)+'b'",
    'fence-backtick': "'```'+' '.repeat(N)+'`'",
    'fence-tilde': "'~~~'+' '.repeat(N)+'`'",
    'rule-spaces': "'- - -'+' '.repeat(N)+'x'",
    'item-spaces': "'-'+' '.repeat(N)+'x'",
    'quote-spaces': "'>'+' '.repeat(N)+'x'",
    'table-pipes': "'|'.repeat(N)+'\\n|---|\\n'",
    'brackets': "'['.repeat(N)",
    'image-brackets': "'!['.repeat(N/2)",
    'link-unclosed': "'[a]('.repeat(N/4)",
    'stars': "'**'+'a '.repeat(N/2)",
    'backticks': "'`a'.repeat(N/2)",
    'autolink': "'<https://'.repeat(N/9)",
}


@pytest.mark.parametrize('name', list(LONG_LINES))
def test_one_long_line_renders_in_linear_time(name):
    result = json.loads(run(
        'const N=131060;const text=(' + LONG_LINES[name] + ');'
        'const s=process.hrtime.bigint();show(text);'
        'console.log(JSON.stringify({chars:text.length,ms:Number(process.hrtime.bigint()-s)/1e6}));'))
    assert result['chars'] > 60000
    assert result['ms'] < 1000, (name, result)


def test_a_badge_is_a_link_labelled_with_its_image():
    out = html('[![CI](https://img.example/x.svg)](https://example.com/repo) after')
    assert out == ('<p><a href="https://example.com/repo" target="_blank" rel="noopener noreferrer" title="https://example.com/repo">'
                   '<span class="markdown-image" title="https://img.example/x.svg">[image: CI]</span></a> after</p>')


def test_a_link_inside_a_link_label_stays_text():
    out = html('[a <https://x.example> [b](https://z.example)](https://y.example)')
    # A label ends at its first `]`; inside it an autolink stays text: one <a>, never nested.
    assert out == ('<p><a href="https://z.example/" target="_blank" rel="noopener noreferrer" title="https://z.example/">'
                   'a &lt;https://x.example&gt; [b</a>](https://y.example)</p>')


def test_links_after_many_unmatched_brackets_still_work():
    out = html('[' * 3000 + ' [x](https://a.example) ](nope) [y](https://b.example)')
    assert out.count('<a ') == 2
    assert 'href="https://a.example/"' in out and 'href="https://b.example/"' in out


def test_a_heading_with_closing_hashes_and_a_hashtag():
    assert html('## Title ##') == '<h2 class="markdown-heading">Title</h2>'
    assert html('# C#') == '<h1 class="markdown-heading">C#</h1>'
    assert html('#tag') == '<p>#tag</p>'
    assert html('#') == '<h1 class="markdown-heading"></h1>'
    assert html('```js title="x"\ncode\n```') == '<pre class="markdown-code" data-language="js"><code>code</code></pre>'
    assert html('``` `not a fence`') == '<p>``` <code>not a fence</code></p>'


def test_a_table_with_short_delimiter_cells_is_drawn():
    # GFM: one or more hyphens per delimiter cell; |:--|--:| is common in hand-written tables.
    out = html('| Month | Sales |\n|:--|-:|\n| Jan | 12 |\n')
    assert '<th>Month</th><th>Sales</th>' in out and '<td>Jan</td><td>12</td>' in out
    assert html('| a | b |\n|:|:|\n') == '<p>| a | b |\n|:|:|</p>'          # no hyphen, no table
