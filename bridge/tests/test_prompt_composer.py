"""Composer behavior on the real cockpit with synthetic panes and CDP."""

import base64
import json
import os
from pathlib import Path

import pytest

from test_conversation_review_regressions import cockpit, stable_roster


def terminal(cockpit):
    js, wait, client, *_ = cockpit
    stable_roster(js)
    js("""window.packets=[];window.send=packet=>{packets.push(packet);return true};
        rosterAnnotationEpoch++;currentAgents=[{name:'ReviewFixture',running:true,program:'codex'}];
        createPane('ReviewFixture',{paneId:'%901',windowId:'@901',width:80,height:20});
        setActive('%901');packets.length=0;""")
    return js, wait, client


def test_card_fills_stage_and_resizes_the_textarea(cockpit):
    js, wait, _ = terminal(cockpit)
    assert js('promptInput.placeholder') == 'Message ReviewFixture'
    assert js("""(()=>{const card=promptInput.closest('.prompt-card').getBoundingClientRect();
        const stage=document.querySelector('.termstage').getBoundingClientRect();
        return [card.left-stage.left,stage.right-card.right]})()""") == [18, 18]
    js(r"promptInput.value='Several lines\n'.repeat(20);promptInput.dispatchEvent(new Event('input'))")
    wait('promptInput.clientHeight===88 && promptInput.scrollHeight>88')
    assert js("packets.filter(packet=>packet.type==='resize')") == []
    js("promptInput.value='';promptInput.dispatchEvent(new Event('input'))")
    wait('promptInput.clientHeight===32')


@pytest.mark.parametrize('reduced', [False, True])
def test_action_switches_to_stop_only_for_an_empty_working_draft(cockpit, reduced):
    js, wait, client = terminal(cockpit)
    if reduced:
        client.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    assert js('promptSendBtn.disabled')
    js("currentAgents[0].act_state='work';document.dispatchEvent(new Event('oc:agents'));promptSendBtn.click()")
    assert js('promptSendBtn.title') == 'Stop agent (Esc)'
    assert js("packets.find(packet=>packet.type==='input').data") == '\x1b'
    square = "document.querySelector('.prompt-square').style.transform==='scale(1)'"
    if reduced:
        assert js(square)
    else:
        wait(square)
    js(r"promptInput.value='First line\nSecond line';promptInput.dispatchEvent(new Event('input'))")
    assert js('promptSendBtn.title') == 'Send message'
    if reduced:
        assert js('promptInput.clientHeight') == 56
    js("packets.length=0;promptSendBtn.click()")
    wait("packets.filter(packet=>packet.type==='input').length===2")
    assert js("packets.filter(packet=>packet.type==='input').map(packet=>packet.data)") == [
        '\x1b[200~First line\nSecond line\x1b[201~', '\r',
    ]


def recipients(cockpit):
    js, wait, client = terminal(cockpit)
    js("""currentAgents.push(
      {name:'QuietCopernicus',running:true,program:'claude-code',category:'agent',annot:{role:'Reader motion'}},
      {name:'EmeraldBose',running:true,program:'codex',category:'agent',annot:{role:'Build verification'}},
      {name:'StillNewton',running:false,program:'codex',category:'agent'});
      for(const [i,name] of ['QuietCopernicus','EmeraldBose','StillNewton'].entries()){
        createPane(name,{paneId:'%'+(902+i),windowId:'@'+(902+i),width:80,height:20});
      }
      setActive('%901');promptInput.focus();""")
    return js, wait, client


def test_mention_matches_name_and_role_and_leaves_file_references(cockpit):
    js, wait, _ = recipients(cockpit)
    for query, found in [('bose', 'EmeraldBose'), ('quiet', 'QuietCopernicus'), ('motion', 'QuietCopernicus')]:
        js(f"promptInput.value='Please ask @{query}';promptInput.setSelectionRange(promptInput.value.length,promptInput.value.length);promptInput.dispatchEvent(new Event('input'))")
        wait(f"[...document.querySelectorAll('.prompt-mention-name')].some(node=>node.textContent==='{found}')")
        assert js("document.querySelector('.prompt-mention-row[aria-selected=true] .prompt-mention-name').textContent") == found
    js("promptInput.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))")
    assert js('promptRecipients.names') == ['QuietCopernicus']
    assert js('promptInput.value') == 'Please ask '
    assert js("document.querySelector('.prompt-chosen').title") == 'QuietCopernicus'
    for token in ('@/tmp/sample.md', '@~/sample.md', '@.agents/skills', '@docs/sample.md', '@summary.md'):
        js(f"promptInput.value='{token}';promptInput.setSelectionRange(promptInput.value.length,promptInput.value.length);promptInput.dispatchEvent(new Event('input'))")
        assert js("promptInput.getAttribute('aria-expanded')") == 'false'
        assert js('promptInput.value') == token
    assert js("OrreryPromptRecipients.queryAt('@docs/sample.md',5,5)") is None
    js("promptInput.setSelectionRange(0,0);promptInput.dispatchEvent(new KeyboardEvent('keydown',{key:'Backspace',bubbles:true,cancelable:true}))")
    assert js('promptRecipients.names') == []
    assert js("packets.filter(packet=>packet.type==='input')") == []


@pytest.mark.parametrize('rejected', [False, True])
def test_roster_selection_sends_each_agent_once_and_keeps_only_failed_targets(cockpit, rejected):
    js, wait, _ = recipients(cockpit)
    js("""currentAgents[0].category='agent';liveRosterAgents=currentAgents;renderRoster();setRosterSelectMode(true);
      for(const name of ['ReviewFixture','QuietCopernicus','EmeraldBose'])bulkSelectedAgents.add(name);
      updateRosterBulkUI();rosterBulkMessage.click();packets.length=0;
      window.receipts=[];
      document.addEventListener('oc:prompt-submitted',event=>receipts.push(event.detail));
      promptInput.value='Shared draft';promptInput.dispatchEvent(new Event('input'));""")
    assert js('promptRecipients.names') == ['ReviewFixture', 'QuietCopernicus', 'EmeraldBose']
    js("""window.send=packet=>{
      packets.push(packet);
      if(packet.inputAck)queueMicrotask(()=>handle({type:'input-ack',paneId:packet.paneId,id:packet.inputAck,
        status:packet.paneId==='%902'&&"""+str(rejected).lower()+"""?'refused':'accepted'}));
      return true;
    };promptSendBtn.click()""")
    wait("!promptBusy")
    assert js('activeId') == '%901'
    expected = ['%901', '%903'] if rejected else ['%901', '%902', '%903']
    assert js(r"packets.filter(packet=>packet.data==='\r').map(packet=>packet.paneId)") == expected
    assert js("receipts.map(receipt=>receipt.broadcastCount)") == [len(expected)] * len(expected)
    assert js('promptRecipients.names') == (['QuietCopernicus'] if rejected else [])
    assert js('promptInput.value') == ('Shared draft' if rejected else '')
    if rejected:
        assert js("toastEl.textContent.includes('Not sent to QuietCopernicus')")


def test_attachment_drop_remove_and_delivery_per_cli(cockpit):
    js, wait, _ = recipients(cockpit)
    js("""window.uploads=[];
      const base=fetch;
      window.fetch=(url,options)=>{
        if(!String(url).includes('/telemetry/prompt-attachment'))return base(url,options);
        uploads.push(JSON.parse(options.body));
        return Promise.resolve(Response.json({path:'./.orrery-input-files/'+'a'.repeat(32)+'.txt'}));
      };
      window.dropFile=()=>{
        const transfer=new DataTransfer();
        transfer.items.add(new File(['Fixture data'],'notes.txt',{type:'text/plain'}));
        document.querySelector('.promptbar').dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));
      };
      dropFile();""")
    assert js("document.querySelector('.prompt-file-name').textContent") == 'notes.txt'
    js("document.querySelector('.prompt-file-remove').click()")
    assert js("document.querySelector('.prompt-attachments').hidden")

    assert js('uploads.length') == 0
    js("""dropFile();promptRecipients.set(['ReviewFixture','QuietCopernicus']);
      window.send=packet=>{
        packets.push(packet);
        if(packet.inputAck)queueMicrotask(()=>handle({type:'input-ack',paneId:packet.paneId,id:packet.inputAck,status:'accepted'}));
        return true;
      };
      promptInput.value='Read this';promptInput.dispatchEvent(new Event('input'));promptSendBtn.click()""")
    wait('!promptBusy')
    assert js("uploads.map(upload=>[upload.session,upload.format,atob(upload.data)])") == [
        ['ReviewFixture', 'txt', 'Fixture data'], ['QuietCopernicus', 'txt', 'Fixture data'],
    ]
    assert js("packets.filter(packet=>packet.data?.includes('Read this')).map(packet=>packet.data)") == [
        '\x1b[200~Read this\n\n./.orrery-input-files/' + 'a' * 32 + '.txt\x1b[201~',
        '\x1b[200~Read this\n\n@./.orrery-input-files/' + 'a' * 32 + '.txt \x1b[201~',
    ]
    assert js("document.querySelector('.prompt-attachments').hidden")


@pytest.mark.parametrize('route, program', [
    ('browser-files', 'claude-code'), ('mac-app', 'claude-code'),
    ('mac-http', 'claude-code'), ('wsl-http', 'claude-code'),
    ('browser-files', 'codex'), ('browser-files', 'dsh'),
    ('browser-files', 'hermes'), ('wsl-http', 'agy'),
])
def test_clipboard_attachments_are_staged_and_removable_until_send(cockpit, route, program):
    from test_conversation_input_images import png

    js, wait, client = recipients(cockpit)
    picture = base64.b64encode(png()).decode()
    snapshot = {'attachments': [
        {'name': 'Clipboard image.png', 'type': 'image/png', 'data': picture},
        {'name': '資料 1.md', 'data': base64.b64encode(b'# Clipboard note').decode()},
    ]}
    js('window.copyFixture='+json.dumps(snapshot)+';window.pasteRoute='+json.dumps(route)+
       ';window.pasteProgram='+json.dumps(program)+r""";
      window.reads=[];window.uploads=[];window.releaseClipboard=null;
      window.clipboardReply=()=>new Promise(resolve=>{releaseClipboard=()=>resolve(copyFixture)});
      const base=fetch;
      window.fetch=(url,options)=>{
        const path=new URL(url,location.href).pathname;
        if(path==='/telemetry/clipboard/attachments'){
          reads.push([path,options.method,options.body]);
          return clipboardReply().then(payload=>Response.json(payload));
        }
        if(path!=='/telemetry/prompt-attachment')return base(url,options);
        uploads.push(JSON.parse(options.body));
        return Promise.resolve(Response.json({path:'./.orrery-input-images/'+'a'.repeat(32)+'.png'}));
      };
      if(pasteRoute==='mac-app')window.__TAURI__={core:{invoke:(cmd,args)=>{
        reads.push([cmd,args.attachments]);return clipboardReply();
      }}};
      hostPlatform={host:pasteRoute.startsWith('mac')?'mac':'wsl',file_paste:pasteRoute!=='browser-files'};
      window.send=packet=>{
        packets.push(packet);
        if(packet.inputAck)queueMicrotask(()=>handle({type:'input-ack',paneId:packet.paneId,id:packet.inputAck,status:'accepted'}));
        return true;
      };
      window.pasteFixture=mode=>{
        const clipboard=new DataTransfer();
        if(mode==='text')clipboard.setData('text/plain','ordinary text');
        else if(pasteRoute==='browser-files'){
          const image=Uint8Array.from(atob(copyFixture.attachments[0].data),c=>c.charCodeAt(0));
          clipboard.items.add(new File([image],'Clipboard image.png',{type:'image/png'}));
          clipboard.items.add(new File(['# Clipboard note'],'資料 1.md',{type:'text/markdown'}));
          clipboard.setData('text/plain','This file paste must not replace the draft.');
        }else if(pasteRoute==='wsl-http'){
          clipboard.setData('text/uri-list','file:///C:/Users/fixture/Notes.md');
          clipboard.setData('text/plain','C:\\Users\\fixture\\Notes.md');
        }
        return promptInput.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}));
      };
      currentAgents[0].program=pasteProgram;
      promptInput.value='Compare the pasted screenshot.';
      promptInput.dispatchEvent(new Event('input'));
      packets.length=0;
    """)
    assert js("pasteFixture('text')") is True
    assert js('reads.length') == 0
    assert not js("pasteFixture('files')")
    if route != 'browser-files':
        wait('releaseClipboard!==null')
        assert js('promptFiles.pending&&promptSendBtn.disabled')
        js('void sendPrompt()')
        assert js('uploads.length') == 0
        assert js("packets.filter(packet=>packet.type==='input').length") == 0
        js('releaseClipboard()')
    wait("document.querySelector('.prompt-file-preview')?.naturalWidth===640")
    assert js("Array.from(document.querySelectorAll('.prompt-file-name'),node=>node.textContent)") == [
        'Clipboard image.png', '資料 1.md']
    expected_reads = ([['clipboard_file_paths', True]] if route == 'mac-app' else
                      [] if route == 'browser-files' else
                      [['/telemetry/clipboard/attachments', 'POST', '{}']])
    assert js('reads') == expected_reads
    assert js('promptInput.value') == 'Compare the pasted screenshot.'
    assert js('uploads.length') == 0
    assert js("packets.filter(packet=>packet.type==='input').length") == 0

    capture = os.environ.get('ORRERY_PASTE_CAPTURE_DIR')
    if capture and route == 'wsl-http' and program == 'claude-code':
        js("document.querySelector('.prompt-ava').src='/cockpit-assets/anthropic.svg'")
        wait("document.querySelector('.prompt-ava').naturalWidth>0")
        for theme in ('dark', 'light'):
            js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
            js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            result = client.call('Page.printToPDF', paperWidth=1600/96, paperHeight=1000/96,
                                 marginTop=0, marginRight=0, marginBottom=0, marginLeft=0,
                                 printBackground=True)
            (Path(capture)/('paste-'+theme+'.pdf')).write_bytes(base64.b64decode(result['data']))

    js("document.querySelector('.prompt-file-remove[aria-label=\"Remove 資料 1.md\"]').click()")
    assert js('promptFiles.entries.length') == 1
    js('void sendPrompt()')
    wait("!promptBusy && promptFiles.entries.length===0")
    assert js("uploads.map(upload=>[upload.kind,upload.label,upload.data])") == [
        ['image', 'Clipboard image.png', picture]]
    [wire,enter] = js("packets.filter(packet=>packet.type==='input'&&packet.inputAck).map(packet=>packet.data)")
    path = './.orrery-input-images/'+'a'*32+'.png'
    reference = '@'+path+' ' if program == 'claude-code' else path
    assert wire == '\x1b[200~Compare the pasted screenshot.\n\n'+reference+'\x1b[201~'
    assert enter == '\r'


def test_reader_shows_selected_attachments_before_and_after_recording(cockpit,tmp_path):
    from test_conversation_submissions import prepare
    from test_conversation_providers import claude,line,row
    from test_conversation_input_images import decorate,png
    from mobile_image import save_image
    from mobile_file import save_file
    js,wait,client=prepare(cockpit,'claude')
    png_data=base64.b64encode(png()).decode()
    paths=[save_image(tmp_path,png_data,label='Comparison.png'),
           save_file(tmp_path,{'format':'md','data':base64.b64encode(b'# File example').decode()},label='Notes.md')]
    paths=['./'+str(Path(path).relative_to(tmp_path)) for path in paths]
    text='Compare these two attachments.'
    sent=text+'\n\n'+'\n'.join('@'+path for path in paths)
    native=tmp_path/'native.jsonl'
    native.write_bytes(line(dict(claude('user',sent,cwd=str(tmp_path)),timestamp=js('new Date(clock+1000).toISOString()'))))
    binding=row(native,'claude-code')
    store,events=decorate(binding)
    picture,document=events[0]['references']
    previews={ref['id']:store.read(ref['id'],binding) for ref in (picture,document)}
    thumbnail=store.read(picture['id'],binding,thumbnail=True)
    js("""window.savedFixturePaths="""+json.dumps(paths)+""";window.uploads=[];
      const base=fetch;
      window.fetch=(url,options)=>{
        if(!String(url).includes('/telemetry/prompt-attachment'))return base(url,options);
        uploads.push(JSON.parse(options.body));return Promise.resolve(Response.json({path:savedFixturePaths[uploads.length-1]}));
      };
      window.send=packet=>{
        packets.push(packet);
        if(packet.inputAck)queueMicrotask(()=>handle({type:'input-ack',paneId:packet.paneId,id:packet.inputAck,status:'accepted'}));
        return true;
      };
      const transfer=new DataTransfer();
      transfer.items.add(new File([Uint8Array.from(atob("""+json.dumps(png_data)+"""),c=>c.charCodeAt(0))],'Comparison.png',{type:'image/png'}));
      transfer.items.add(new File(['# File example'],'Notes.md',{type:'text/markdown'}));
      currentAgents[0].program='claude-code';
      document.querySelector('.promptbar').dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));
      promptInput.value="""+json.dumps(text)+""";void sendPrompt();""")
    wait("reader.querySelector('.conversation-submission img')?.naturalWidth===640&&!promptBusy")
    assert js("reader.querySelector('.conversation-submission').textContent.includes('Notes.md')")
    assert not js("reader.querySelector('.conversation-submission').textContent.includes('.orrery-input-')")
    assert js("uploads.map(upload=>upload.label)")==['Comparison.png','Notes.md']
    assert js(r"packets.find(packet=>packet.data?.startsWith('\x1b[200~Compare')).data.slice(6,-6)")==sent+' '
    capture=os.environ.get('ORRERY_ATTACHMENT_CAPTURE_DIR')
    def save_capture(name):
        if os.environ.get('CDP_PDF_ON_TIMEOUT'):
            result=client.call('Page.printToPDF',paperWidth=1600/96,paperHeight=1000/96,
                               marginTop=0,marginRight=0,marginBottom=0,marginLeft=0,printBackground=True)
            suffix='.pdf'
        else:
            result=client.call('Page.captureScreenshot',format='png')
            suffix='.png'
        (Path(capture)/('desktop-'+name+suffix)).write_bytes(base64.b64decode(result['data']))
    if capture:save_capture('pending')
    js('window.verifiedAttachments='+json.dumps(events)+';window.verifiedPreviews='+json.dumps(previews)+';window.verifiedThumb='+json.dumps(thumbnail)+';'
       'OrreryConversationSource.Source.prototype.reference=async(ref,{thumbnail}={})=>thumbnail?verifiedThumb:verifiedPreviews[ref];'
       'OrreryConversationSource.Source.prototype.read=async()=>({provider:"claude",mode:"cursor",events:[oldRecord,...verifiedAttachments],after:"end"});'
       'conversationView.refresh()')
    wait("reader.querySelector('.conversation-event .conversation-inline-image img')?.naturalWidth===320&&!reader.querySelector('.conversation-submission')")
    assert not js("reader.querySelector('.conversation-event .conversation-input-images').parentElement.textContent.includes('.orrery-input-')")
    assert js("reader.querySelector('.conversation-event button.conversation-file').textContent.includes('Notes.md')")
    if capture:
        for theme in ('dark','light'):
            js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
            js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            save_capture(theme)
    js("reader.querySelector('.conversation-event .conversation-inline-image').click()")
    wait("reader.querySelector('.conversation-preview-image')?.naturalWidth===640")


def test_skill_kind_namespace_retry_switch_and_multiline_fix(cockpit):
    js, wait, _ = recipients(cockpit)
    js("""window.requestedSkills=[];const base=fetch;
      window.fetch=(url,options)=>{
        const parsed=new URL(url,location.href);
        if(parsed.pathname!=='/telemetry/skills')return base(url,options);
        const program=parsed.searchParams.get('program');
        requestedSkills.push(program);
        if(requestedSkills.filter(key=>key===program).length===1&&program==='codex')
          return Promise.resolve(Response.json({}, {status:503}));
        const skills=program==='codex'?[
          {name:'status',kind:'builtin'},{name:'status',kind:'skill'},{name:'release-check',kind:'skill'},{name:'log',kind:'skill'}
        ]:[{name:'ops:review',kind:'skill'}];
        return Promise.resolve(Response.json({skills,prefix:program==='codex'?'$':'/'}));
      };
      skillCatalogs.clear();skillRequests.clear();
      window.draft=value=>{promptInput.value=value;promptInput.focus();
        promptInput.setSelectionRange(value.length,value.length);promptInput.dispatchEvent(new Event('input'));
      };
      draft('/re');""")
    wait("requestedSkills.filter(key=>key==='codex').length===1&&!skillRequests.size")
    js("draft('/rel')")
    wait("slashMenu.textContent.includes('$release-check')")
    assert js("requestedSkills.filter(key=>key==='codex').length") == 2
    js("draft('/sta')")
    assert js("slashMenu.querySelector('.sm-name').textContent") == '/status'
    js("draft('/status');sendPrompt()")
    wait(r"packets.some(packet=>packet.data==='\r')")
    assert js("packets.filter(packet=>packet.type==='input')[0].data") == '\x1b[200~/status\x1b[201~'
    js(r"packets.length=0;draft('  /release-check extra\nsecond note');sendPrompt()")
    assert js('!sendGuard.hidden')
    assert js('guardArmed.fix') == '  $release-check extra\nsecond note'
    js('sendGuardFix.click()')
    wait(r"packets.some(packet=>packet.data==='\r')")
    assert js("packets.filter(packet=>packet.type==='input')[0].data") == '\x1b[200~  $release-check extra\nsecond note\x1b[201~'
    js("draft('/log');sendPrompt()")
    assert js('guardArmed.fix') == '$log'
    js("setActive('%902');draft('/ops:')")
    wait("slashMenu.textContent.includes('/ops:review')")
    js("draft('/re');setActive('%901')")
    assert js("!slashMenu.hidden&&slashMenu.textContent.includes('$release-check')")
    assert js("requestedSkills.filter(key=>key==='codex').length") == 2


def test_a_recipient_pin_survives_the_draft_and_refuses_a_reused_name(cockpit):
    js, wait, _ = recipients(cockpit)
    js("""currentAgentNamed('QuietCopernicus').created=1;
      promptRecipients.set(['QuietCopernicus']);promptInput.value='Keep the intended recipient';saveDraft();""")
    assert js("JSON.parse(localStorage.getItem(PROMPT_RECIPIENTS_KEY))") == [
        {'name': 'QuietCopernicus', 'created': 1},
    ]
    js("currentAgentNamed('QuietCopernicus').created=2;packets.length=0;sendPrompt()")
    wait("!promptBusy")
    assert js("packets.filter(packet=>packet.type==='input')") == []
    assert js("toastEl.textContent") == 'Not sent to QuietCopernicus'
    assert js("promptRecipients.names") == ['QuietCopernicus']
    assert js("promptInput.value") == 'Keep the intended recipient'
