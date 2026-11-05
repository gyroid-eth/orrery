"""Native Claude SendUserFile shape; all values here are synthetic."""
import sys,json
from pathlib import Path
import pytest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_conversation_providers import line,claude,row,page,history
from test_conversation_preview import call,setup,preview
from conversation_artifacts import extract_artifacts,MAX_REFS
from conversation_preview import ReferenceStore,PreviewUnavailable


def test_send_user_file_extracts_only_bounded_explicit_files():
    value=dict(files=['plot.png','notes.txt','plot.png','https://example.invalid/x.png',None,{'path':'never.txt'}],caption='do not grant caption.txt',status='done')
    result=extract_artifacts(call('SendUserFile',value))
    assert result['paths']==['plot.png','notes.txt']
    assert not result['diff']
    assert len(extract_artifacts(call('SendUserFile',dict(files=[str(i)+'.txt' for i in range(100)])))['paths'])==MAX_REFS
    assert not extract_artifacts(call('SendUserFile',dict(files='not-a-list.png')))['paths']
    assert not extract_artifacts(call('SendUserFile',dict(path='not-the-schema.png')))['paths']


def test_send_user_file_static_wrapper_ignores_computed_code():
    assert extract_artifacts(call('functions.exec',input='await tools.SendUserFile({files:["plot.png"]});'))['paths']==['plot.png']
    assert not extract_artifacts(call('functions.exec',input='await tools.SendUserFile({files:[computed]});'))['paths']


def test_native_claude_delivery_yields_opaque_image_and_text_chips(tmp_path):
    Image.new('RGB',(20,12),'teal').save(tmp_path/'plot.png');(tmp_path/'notes.txt').write_text('Generated delivery text')
    path=tmp_path/'claude.jsonl';path.write_bytes(line(claude('user','Generated start',cwd=str(tmp_path)))+line(claude('assistant',[
      dict(type='tool_use',id='generated-call',name='SendUserFile',input=dict(files=[str(tmp_path/'plot.png'),str(tmp_path/'notes.txt')],caption='Generated caption',status='done'))]))+
      line(claude('user',[dict(type='tool_result',tool_use_id='generated-call',content='Generated delivery result')])) )
    r=row(path,'claude-code');store=ReferenceStore()
    with history.open_reader(r) as reader:
        events=reader.read_page()['events'];event=next(e for e in events if e['kind']=='tool');store.decorate(r,reader,event)
    assert [ref['label'] for ref in event['references']]==['plot.png','notes.txt']
    assert all('/' not in ref['id'] for ref in event['references'])
    assert store.read(event['references'][0]['id'],r)['kind']=='image'
    assert store.read(event['references'][1]['id'],r)['text']=='Generated delivery text'
    assert 'caption' not in json.dumps(events) and 'Generated delivery result' not in json.dumps(events)


@pytest.mark.parametrize('case',['outside','url','symlink','pixels','bytes'])
def test_send_user_file_keeps_existing_preview_policy(tmp_path,case):
    work=tmp_path/'work';work.mkdir();target=work/'plot.png';Image.new('RGB',(20,12)).save(target);name='plot.png';options={}
    if case=='outside':name=str(tmp_path/'outside.png');Image.new('RGB',(20,12)).save(name)
    if case=='url':name='https://example.invalid/p.png'
    if case=='symlink':target.unlink();target.symlink_to(tmp_path/'outside.png');Image.new('RGB',(20,12)).save(tmp_path/'outside.png')
    if case=='pixels':options['max_pixels']=10
    if case=='bytes':target.write_bytes(b'\0'*(12*1024*1024+1))
    store,r,event=setup(work,call('SendUserFile',dict(files=[name])),**options)
    if case in ['outside','url','symlink']:assert not event.get('references')
    else:
        with pytest.raises(PreviewUnavailable):preview(store,r,event)


def test_send_user_file_secret_like_name_is_previewed(tmp_path):
    work=tmp_path/'work';work.mkdir();(work/'auth.json').write_text('Generated named fixture')
    store,r,event=setup(work,call('SendUserFile',dict(files=['auth.json'])))
    assert [ref['label'] for ref in event['references']]==['auth.json']
    assert preview(store,r,event)['text']=='Generated named fixture'
