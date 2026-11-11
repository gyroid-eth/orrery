"""4 harness の架空の入力記録と bridge の保存画像。実サービスを使わない。"""
import base64
import hashlib
import io
import json
import shlex
from pathlib import Path

import pytest
from PIL import Image

from test_conversation_providers import row, page, line, claude, dsh, make_db
from conversation_history import open_reader
from conversation_preview import ReferenceStore, PreviewUnavailable


def png():
    out=io.BytesIO();Image.new('RGB',(640,400),'#548eae').save(out,'PNG');return out.getvalue()


def url():return 'data:image/png;base64,'+base64.b64encode(png()).decode()


def codex(content):
    return dict(type='response_item',payload=dict(type='message',role='user',content=content))


def decorate(r):
    store=ReferenceStore();result=page(r)
    with open_reader(r) as reader:store.decorate_all(r,reader,result['events'])
    return store,result['events']


@pytest.mark.parametrize('program',['claude-code','codex','dsh','hermes'])
def test_native_input_image_uses_a_record_bound_reference(tmp_path,program):
    text=dict(type='text',text='この画像を確認してください。')
    if program=='claude-code':
        path=tmp_path/'claude.jsonl'
        path.write_bytes(line(claude('user',[text,dict(type='image',source=dict(type='base64',media_type='image/png',data=base64.b64encode(png()).decode()))],cwd=str(tmp_path))))
    elif program=='codex':
        path=tmp_path/'codex.jsonl'
        path.write_bytes(line(dict(type='session_meta',payload=dict(cwd=str(tmp_path))))+
                         line(codex([text,dict(type='input_image',image_url=url())])))
    elif program=='dsh':
        path=tmp_path/'sessions'/'project'/'fixture-session'/'session.v4.jsonl'
        path.parent.mkdir(parents=True)
        digest=hashlib.sha256(png()).hexdigest()
        image=tmp_path/'attachments'/'v1'/'objects'/digest[:2]/digest
        image.parent.mkdir(parents=True);image.write_bytes(png())
        content=[text,dict(type='image',attachment=dict(attachmentId='sha256:'+digest,mediaType='image/png',width=640,height=400,bytes=len(png())))]
        path.write_bytes(line(dict(type='session',version=4,id='fixture-session',cwd=str(tmp_path)))+
                         line(dsh('user/message',dict(source=dict(kind='user'),content=content))))
    else:
        path=tmp_path/'state.db';db=make_db(path)
        content='\x00json:'+json.dumps([text,dict(type='image_url',image_url=dict(url=url()))])
        db.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('fixture-session','user',?,1)",(content,));db.commit();db.close()
    r=row(path,program);store,events=decorate(r)
    images=[e for e in events if e.get('input_images')]
    assert len(images)==1
    ref=images[0]['references'][0]
    assert ref['input_image'] and ref['kind']=='image'
    assert ref['label']=='Input image 1.png'
    assert url() not in json.dumps(events)
    result=store.read(ref['id'],r)
    assert result['label']=='Input image 1.png'
    assert result['kind']=='image' and (result['width'],result['height'])==(640,400)
    thumb=store.read(ref['id'],r,thumbnail=True)
    assert Image.open(io.BytesIO(base64.b64decode(thumb['data']))).size==(320,200)
    with pytest.raises(PreviewUnavailable):store.read(ref['id'],r,reveal=True)
    with pytest.raises(PreviewUnavailable):store.read(ref['id'],dict(r,history_session_id='other'))
    if program=='dsh':
        image.write_bytes(b'changed')
        with pytest.raises(PreviewUnavailable):store.read(ref['id'],r)


@pytest.mark.parametrize('saving',['mobile','clipboard'])
def test_only_images_saved_by_this_bridge_get_text_path_references(tmp_path,monkeypatch,saving):
    workspace=tmp_path/"workspace 'quoted";workspace.mkdir()
    if saving=='mobile':
        from mobile_image import save_image
        saved=save_image(str(workspace),base64.b64encode(png()).decode())
    else:
        import orrery_backend as backend
        monkeypatch.setenv('ORRERY_CLIPBOARD_DIR',str(workspace/'clipboard'))
        saved=backend.save_clipboard_image(png())
    arbitrary=Path(saved).parent/'arbitrary.png';arbitrary.write_bytes(png())
    content=[dict(type='input_text',text="確認 [image: "+shlex.quote(saved)+"] "+shlex.quote(str(arbitrary)))]
    path=tmp_path/'codex.jsonl'
    path.write_bytes(line(dict(type='session_meta',payload=dict(cwd=str(tmp_path))))+line(codex(content)))
    r=row(path,'codex');store,events=decorate(r)
    refs=events[0]['references'];assert len(refs)==1
    assert store.read(refs[0]['id'],r)['kind']=='image'
    # 再起動前の登録は復元しない。既存 ref でも、登録の無い path は読まない。
    import conversation_images
    monkeypatch.setattr(conversation_images,'_saved',{})
    with pytest.raises(PreviewUnavailable):store.read(refs[0]['id'],r)
    assert not decorate(r)[1][0].get('references')


def test_replaced_saved_image_is_no_longer_an_input_reference(tmp_path):
    from mobile_image import save_image
    saved=save_image(str(tmp_path),base64.b64encode(png()).decode())
    path=tmp_path/'codex.jsonl'
    path.write_bytes(line(dict(type='session_meta',payload=dict(cwd=str(tmp_path))))+
                     line(codex([dict(type='input_text',text=saved)])))
    r=row(path,'codex');store,events=decorate(r);ref=events[0]['references'][0]['id']
    replacement=tmp_path/'replacement.png';replacement.write_bytes(png());replacement.replace(saved)
    with pytest.raises(PreviewUnavailable):store.read(ref,r)
    assert not decorate(r)[1][0].get('references')


def test_remote_urls_arbitrary_paths_and_oversized_embedded_images_are_not_loaded(tmp_path):
    arbitrary=tmp_path/'arbitrary.png';arbitrary.write_bytes(png())
    content=[dict(type='input_text',text=str(arbitrary)),
             dict(type='input_image',image_url='https://example.test/private.png')]
    path=tmp_path/'codex.jsonl'
    header=line(dict(type='session_meta',payload=dict(cwd=str(tmp_path))))
    path.write_bytes(header+line(codex(content)))
    assert not decorate(row(path,'codex'))[1][0].get('references')
    # 既存の 1 MiB record 制限を維持する。
    path.write_bytes(header+line(codex([dict(type='input_image',image_url='data:image/png;base64,'+'A'*(1024*1024))])))
    assert all(not event.get('references') for event in decorate(row(path,'codex'))[1])
