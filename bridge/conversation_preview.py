"""Recorded references and bounded previews, plus explicit local image clicks.

No path registration API. An ID is useful only with the same authoritative
agent binding, pinned transcript inode and unchanged originating record.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import secrets
import stat
import threading
import time
import warnings
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from conversation_artifacts import extract_artifacts
from conversation_history import open_bound_transcript, assert_transcript_identity, HistoryUnavailable, open_reader
from conversation_images import input_images, saved_path, dsh_image_path

MAX_RECORD=1024*1024
MAX_TEXT=128*1024
MAX_IMAGE=8*1024*1024
TEXT_EXT={'.txt','.md','.py','.js','.mjs','.cjs','.ts','.tsx','.jsx','.css','.scss','.json','.jsonl',
          '.yaml','.yml','.toml','.ini','.cfg','.csv','.tsv','.xml','.html','.svg','.sh','.bash','.zsh',
          '.rs','.go','.c','.h','.cpp','.hpp','.java','.kt','.sql','.diff','.patch','.log','.rst'}
IMAGE_EXT={'.png','.jpg','.jpeg','.gif','.webp'}


def clicked_image(value):
    """Explicit local path click: image-only, independent of record grants.

    Resolve aliases first, then use the same no-follow descriptor walk and
    raster limits as recorded previews. Recheck the alias after the read.
    """
    if (not isinstance(value,str) or len(value)>2000
            or not value.startswith(('/', '~/')) or re.search(r'[\x00-\x1f\x7f]',value)):
        raise PreviewUnavailable('preview_path_denied')
    original=Path(value).expanduser()
    if original.suffix.lower() not in IMAGE_EXT:raise PreviewUnavailable('preview_type_denied')
    try:
        path=original.resolve(strict=True)
        if path.suffix.lower() not in IMAGE_EXT:raise PreviewUnavailable('preview_type_denied')
        result=ReferenceStore().read_file(path)
        if original.resolve(strict=True)!=path:raise PreviewUnavailable('preview_changed')
        result.pop('notice',None)
        return result
    except (OSError,ValueError,RuntimeError) as exc:
        if isinstance(exc,PreviewUnavailable):raise
        raise PreviewUnavailable('preview_unavailable') from None


class PreviewUnavailable(ValueError): pass


def binding(row):
    keys=('name','program','history_binding','transcript_path','native_session_id','history_session_id','history_receipt_ts','created','mail_instance_id','mail_agent_id')
    return tuple(row.get(key) for key in keys)


def identity(stream):
    info=os.fstat(stream.fileno());return info.st_dev,info.st_ino


def record_at(stream,offset,cache=None):
    if hasattr(stream,'provider'):
        if stream.provider!='codex':return stream.record_at(str(offset),cache)
        stream=stream.stream
    if offset<0:raise PreviewUnavailable('reference_expired')
    if offset and os.pread(stream.fileno(),1,offset-1)!=b'\n':raise PreviewUnavailable('reference_expired')
    data=os.pread(stream.fileno(),MAX_RECORD+1,offset)
    raw=data.split(b'\n',1)[0]
    if b'\n' not in data or len(raw)>MAX_RECORD:raise PreviewUnavailable('record_too_large')
    try:return json.loads(raw),hashlib.sha256(raw).digest()
    except (ValueError,UnicodeError):raise PreviewUnavailable('reference_expired') from None


def workspace(stream):
    if hasattr(stream,'provider'):
        if stream.provider!='codex':return root_path(stream.cwd) if isinstance(stream.cwd,str) else None
        stream=stream.stream
    try:
        first=json.loads(os.pread(stream.fileno(),65536,0).split(b'\n',1)[0])
        cwd=first['payload']['cwd'] if first.get('type')=='session_meta' else None
        return root_path(cwd) if isinstance(cwd,str) else None
    except (ValueError,KeyError,TypeError):return None


def root_path(value):
    if not value or not os.path.isabs(value):return None
    try:root=Path(value).resolve()
    except (OSError,ValueError):return None
    # Broad machine grants cannot be enabled accidentally, even via startup.
    if root in {Path('/'),Path.home(),Path('/Users'),Path('/private'),Path('/private/tmp'),Path('/tmp')} or len(root.parts)<3:return None
    return root if root.is_dir() else None


@contextmanager
def open_file(path):
    """No-follow descriptor walk, including parent directories and the final file."""
    parent=fd=None
    try:
        parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
        for part in path.parts[1:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent);parent=child
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise PreviewUnavailable('preview_type_denied')
        yield fd,info
    except OSError:raise PreviewUnavailable('preview_unavailable') from None
    finally:
        if fd is not None:os.close(fd)
        if parent is not None:os.close(parent)


class ReferenceStore:
    def __init__(self,*,image_roots=(),workspace_roots=(),ttl=900,max_refs=4096,clock=time.monotonic,max_pixels=16_000_000):
        self.image_roots=tuple(root for value in image_roots if (root:=root_path(value)))
        self.workspace_roots=tuple(root for value in workspace_roots if (root:=root_path(value)))
        self.ttl,self.max_refs,self.clock,self.max_pixels=ttl,max_refs,clock,max_pixels
        self.refs=OrderedDict();self.by_key={};self.lock=threading.RLock()

    def prune(self):
        now=self.clock()
        for key,value in list(self.refs.items()):
            if value['expires']<=now:self.refs.pop(key)
        while len(self.refs)>self.max_refs:self.refs.popitem(last=False)
        if len(self.by_key)>len(self.refs):
            self.by_key={value['key']:ref for ref,value in self.refs.items()}

    def policy(self,value,cwd,*,shown=False):
        if (not isinstance(value,str) or re.search(r'[\x00-\x1f\x7f]|://|^~',value)
                or '..' in Path(value).parts):raise PreviewUnavailable('preview_path_denied')
        if not os.path.isabs(value):
            if cwd is None:raise PreviewUnavailable('preview_path_denied')
            path=cwd/value
        else:path=Path(value)
        # OS が置いた固定の別名だけを比較前に展開する。Linux 等で
        # 別名が無い場合はそのままにし、利用者の symlink は後段で拒否する。
        for alias,target in (('/tmp','/private/tmp'),('/var','/private/var'),('/etc','/private/etc')):
            prefix=Path(alias)
            if (path.is_relative_to(prefix) and prefix.is_symlink()
                    and prefix.lstat().st_uid==0 and prefix.resolve()==Path(target)):
                path=Path(target)/path.relative_to(prefix)
                break
        canonical=path.resolve()
        # Reject any symlink rather than using its target as a grant. A late
        # replacement is also rejected by the descriptor walk in read_file.
        if canonical!=path:raise PreviewUnavailable('preview_path_denied')
        roots=((*self.workspace_roots,cwd) if cwd else self.workspace_roots)
        is_image=path.suffix.lower() in IMAGE_EXT
        allowed=any(path.is_relative_to(root) for root in roots)
        # Only explicit delivery calls grant their particular raster image
        # outside configured roots. Callers derive this from the pinned record,
        # never from a client flag, tool result, caption or an adjacent path.
        if not allowed and is_image:allowed=shown or any(path.is_relative_to(root) for root in self.image_roots)
        if not allowed:raise PreviewUnavailable('preview_path_denied')
        if not is_image and path.suffix.lower() not in TEXT_EXT and path.name not in {'Makefile','Dockerfile','LICENSE'}:
            raise PreviewUnavailable('preview_type_denied')
        return path

    def decorate_all(self,row,stream,events):
        """decorate() for one page: the workspace root is resolved once."""
        missing=object();cwd=missing;records={}
        for event in events:
            if cwd is missing:
                try:cwd=workspace(stream)
                except (PreviewUnavailable,ValueError):cwd=None
            self.decorate(row,stream,event,cwd=cwd,records=records)

    def decorate(self,row,stream,event,*,cwd=False,records=None):
        """Only called on selected events from an already pinned bound transcript."""
        try:
            item,digest=record_at(stream,event['id'] if hasattr(stream,'provider') and stream.provider!='codex' else int(event['id']),records);projection=extract_artifacts(item)
            if cwd is False:cwd=workspace(stream)
        except (PreviewUnavailable,ValueError):return
        if event.get('kind')=='text' and event.get('role')=='user':
            self.decorate_input(row,stream,event,item,digest)
            return
        if projection['diff']:
            event['diff']=projection['diff'];event['diff_status']=projection['diff_status']
        refs=[]
        with self.lock:
            self.prune()
            for index,value in enumerate(projection['paths']):
                try:path=self.policy(value,cwd,shown=value in projection['shown_paths'])
                except (PreviewUnavailable,OSError,ValueError):continue
                key=(binding(row),identity(stream),event['id'],digest,index,str(path))
                ref=self.by_key.get(key)
                if ref not in self.refs or self.refs[ref]['key']!=key:ref=secrets.token_urlsafe(24)
                self.by_key[key]=ref
                self.refs[ref]=dict(key=key,row=binding(row),inode=identity(stream),offset=event['id'] if hasattr(stream,'provider') and stream.provider!='codex' else int(event['id']),digest=digest,index=index,expires=self.clock()+self.ttl)
                self.refs.move_to_end(ref)
                refs.append(dict(id=ref,label=path.name[:160],kind='image' if path.suffix.lower() in IMAGE_EXT else 'file'))
            self.prune()
        if refs:event['references']=refs

    @staticmethod
    def image_key(image):
        return hashlib.sha256(json.dumps(image,sort_keys=True).encode()).digest()

    def decorate_input(self,row,stream,event,item,digest):
        refs=[]
        with self.lock:
            self.prune()
            for index,image in enumerate(input_images(item)):
                key=(binding(row),identity(stream),event['id'],digest,index,self.image_key(image))
                ref=self.by_key.get(key)
                if ref not in self.refs or self.refs[ref]['key']!=key:ref=secrets.token_urlsafe(24)
                self.by_key[key]=ref
                self.refs[ref]=dict(key=key,row=binding(row),inode=identity(stream),offset=event['id'] if hasattr(stream,'provider') and stream.provider!='codex' else int(event['id']),
                                    digest=digest,index=index,input_image=True,expires=self.clock()+self.ttl)
                self.refs.move_to_end(ref)
                refs.append(dict(id=ref,label=f'Input image {index+1}.png',kind='image',input_image=True))
            self.prune()
        if refs:event['references']=refs;event['input_images']=True

    def read_input(self,image,stream,*,thumbnail=False):
        if image['kind']=='data':
            data=base64.b64decode(image['url'].split(',',1)[1],validate=True)
            if len(data)>MAX_IMAGE:raise PreviewUnavailable('preview_too_large')
            return self.raster(data,thumbnail=thumbnail)
        if image['kind']=='dsh':
            path=dsh_image_path(stream.path,image['digest'])
            if path is None:raise PreviewUnavailable('preview_unavailable')
            return self.read_file(path,thumbnail=thumbnail,image_digest=image['digest'])
        path=saved_path(image['path'])
        if path is None:raise PreviewUnavailable('reference_expired')
        result=self.read_file(path,thumbnail=thumbnail)
        if result['kind']!='image' or saved_path(image['path'])!=path:raise PreviewUnavailable('reference_expired')
        return result

    def read(self,ref,row,*,reveal=False,thumbnail=False):
        with self.lock:
            self.prune();entry=self.refs.get(ref)
            if not entry or binding(row)!=entry['row']:raise PreviewUnavailable('reference_expired')
            entry=dict(entry)
        try:
            with open_reader(row) as stream:
                stream.assert_identity()
                if identity(stream)!=entry['inode']:raise PreviewUnavailable('reference_expired')
                item,digest=record_at(stream,entry['offset'])
                if digest!=entry['digest']:raise PreviewUnavailable('reference_expired')
                if entry.get('input_image'):
                    if reveal:raise PreviewUnavailable('preview_unavailable')
                    images=input_images(item)
                    if entry['index']>=len(images) or self.image_key(images[entry['index']])!=entry['key'][-1]:raise PreviewUnavailable('reference_expired')
                    result=self.read_input(images[entry['index']],stream,thumbnail=thumbnail)
                    result=dict(result,label=f"Input image {entry['index']+1}.png",notice='Recorded input image')
                else:
                    projection=extract_artifacts(item);paths=projection['paths']
                    if entry['index']>=len(paths):raise PreviewUnavailable('reference_expired')
                    value=paths[entry['index']];shown=value in projection['shown_paths']
                    path=self.policy(value,workspace(stream),shown=shown)
                    if str(path)!=entry['key'][-1]:raise PreviewUnavailable('reference_expired')
                    result=self.read_file(path,thumbnail=thumbnail)
                # Revalidate both the source record and file descriptor identity
                # before publishing; append-only transcript growth is allowed.
                if record_at(stream,entry['offset'])[1]!=entry['digest']:raise PreviewUnavailable('reference_expired')
                if not entry.get('input_image') and self.policy(value,workspace(stream),shown=shown)!=path:raise PreviewUnavailable('reference_expired')
                stream.assert_identity()
            return path if reveal else result
        except (HistoryUnavailable,OSError,ValueError,KeyError,TypeError) as exc:
            if isinstance(exc,PreviewUnavailable):raise
            raise PreviewUnavailable('reference_expired') from None

    def owner(self,ref):
        with self.lock:
            self.prune();entry=self.refs.get(ref)
            if not entry:raise PreviewUnavailable('reference_expired')
            return entry['row'][0]

    def read_file(self,path,*,thumbnail=False,image_digest=None):
        is_image=image_digest is not None or path.suffix.lower() in IMAGE_EXT
        maximum=MAX_IMAGE if is_image else MAX_TEXT
        with open_file(path) as (fd,info):
            if info.st_size>maximum:raise PreviewUnavailable('preview_too_large')
            data=os.read(fd,maximum+1)
            if len(data)>maximum:raise PreviewUnavailable('preview_too_large')
            if image_digest is not None and hashlib.sha256(data).hexdigest()!=image_digest:raise PreviewUnavailable('preview_changed')
            if is_image:result=self.raster(data,thumbnail=thumbnail)
            else:
                try:text=data.decode('utf-8')
                except UnicodeError:raise PreviewUnavailable('preview_type_denied') from None
                if '\x00' in text or any(ord(c)<32 and c not in '\n\r\t' for c in text):raise PreviewUnavailable('preview_type_denied')
                result=dict(kind='text',mime='text/plain',text=text)
            after=os.fstat(fd)
            with open_file(path) as (_,current):
                signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
                if signature(info)!=signature(after) or signature(info)!=signature(current):raise PreviewUnavailable('preview_changed')
        return dict(result,label=path.name[:160],notice='Current file · may differ from the recorded edit')

    def raster(self,data,*,thumbnail=False):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in {'PNG','JPEG','GIF','WEBP'}:raise PreviewUnavailable('preview_type_denied')
                    width,height=image.size
                    if width>8192 or height>8192 or width*height>self.max_pixels:raise PreviewUnavailable('preview_too_large')
                    image.seek(0);image.load()
                    clean=image.convert('RGBA')
                    # Copy only pixels: original EXIF/ICC/text/animation metadata
                    # never leaves this process.
                    pixels=Image.frombytes('RGBA',clean.size,clean.tobytes())
                    output=io.BytesIO();pixels.save(output,format='PNG')
                    if output.tell()>MAX_IMAGE:raise PreviewUnavailable('preview_too_large')
                    # 原寸と同じ制限を通した後、会話内の表示だけ小さい PNG にする。
                    if thumbnail:
                        pixels.thumbnail((320,200),Image.Resampling.LANCZOS)
                        output=io.BytesIO();pixels.save(output,format='PNG')
            return dict(kind='image',mime='image/png',data=base64.b64encode(output.getvalue()).decode('ascii'),width=width,height=height)
        except PreviewUnavailable:
            raise
        except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise PreviewUnavailable('preview_type_denied') from None
