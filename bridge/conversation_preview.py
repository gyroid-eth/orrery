"""Server-issued record references and confined, bounded file previews.

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
from conversation_artifacts import extract_artifacts, secret_path, redact
from conversation_history import open_bound_transcript, assert_transcript_identity, HistoryUnavailable

MAX_RECORD=1024*1024
MAX_TEXT=128*1024
MAX_IMAGE=8*1024*1024
TEXT_EXT={'.txt','.md','.py','.js','.mjs','.cjs','.ts','.tsx','.jsx','.css','.scss','.json','.jsonl',
          '.yaml','.yml','.toml','.ini','.cfg','.csv','.tsv','.xml','.html','.svg','.sh','.bash','.zsh',
          '.rs','.go','.c','.h','.cpp','.hpp','.java','.kt','.sql','.diff','.patch','.log','.rst'}
IMAGE_EXT={'.png','.jpg','.jpeg','.gif','.webp'}


class PreviewUnavailable(ValueError): pass


def binding(row):
    keys=('name','program','history_binding','transcript_path','native_session_id','created','mail_instance_id','mail_agent_id')
    return tuple(row.get(key) for key in keys)


def identity(stream):
    info=os.fstat(stream.fileno());return info.st_dev,info.st_ino


def record_at(stream,offset):
    if offset<0:raise PreviewUnavailable('reference_expired')
    if offset and os.pread(stream.fileno(),1,offset-1)!=b'\n':raise PreviewUnavailable('reference_expired')
    data=os.pread(stream.fileno(),MAX_RECORD+1,offset)
    raw=data.split(b'\n',1)[0]
    if b'\n' not in data or len(raw)>MAX_RECORD:raise PreviewUnavailable('record_too_large')
    try:return json.loads(raw),hashlib.sha256(raw).digest()
    except (ValueError,UnicodeError):raise PreviewUnavailable('reference_expired') from None


def workspace(stream):
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
        self.refs=OrderedDict();self.lock=threading.RLock()

    def prune(self):
        now=self.clock()
        for key,value in list(self.refs.items()):
            if value['expires']<=now:self.refs.pop(key)
        while len(self.refs)>self.max_refs:self.refs.popitem(last=False)

    def policy(self,value,cwd):
        if (not isinstance(value,str) or secret_path(value) or re.search(r'[\x00-\x1f\x7f]|://|^~',value)
                or '..' in Path(value).parts):raise PreviewUnavailable('preview_path_denied')
        if not os.path.isabs(value):
            if cwd is None:raise PreviewUnavailable('preview_path_denied')
            path=cwd/value
        else:path=Path(value)
        canonical=path.resolve()
        # Reject any symlink rather than using its target as a grant. A late
        # replacement is also rejected by the descriptor walk in read_file.
        if canonical!=path:raise PreviewUnavailable('preview_path_denied')
        roots=((*self.workspace_roots,cwd) if cwd else self.workspace_roots)
        is_image=path.suffix.lower() in IMAGE_EXT
        allowed=any(path.is_relative_to(root) for root in roots)
        if not allowed and is_image:allowed=any(path.is_relative_to(root) for root in self.image_roots)
        if not allowed or secret_path(str(path)):raise PreviewUnavailable('preview_path_denied')
        if not is_image and path.suffix.lower() not in TEXT_EXT and path.name not in {'Makefile','Dockerfile','LICENSE'}:
            raise PreviewUnavailable('preview_type_denied')
        return path

    def decorate(self,row,stream,event):
        """Only called on selected events from an already pinned bound transcript."""
        try:
            item,digest=record_at(stream,int(event['id']));projection=extract_artifacts(item);cwd=workspace(stream)
        except (PreviewUnavailable,ValueError):return
        if projection['diff']:
            event['diff']=projection['diff'];event['diff_status']=projection['diff_status']
        refs=[]
        with self.lock:
            self.prune()
            for index,value in enumerate(projection['paths']):
                try:path=self.policy(value,cwd)
                except (PreviewUnavailable,OSError,ValueError):continue
                key=(binding(row),identity(stream),event['id'],digest,index,str(path))
                ref=next((id_ for id_,data in self.refs.items() if data['key']==key),None)
                if ref is None:ref=secrets.token_urlsafe(24)
                self.refs[ref]=dict(key=key,row=binding(row),inode=identity(stream),offset=int(event['id']),digest=digest,index=index,expires=self.clock()+self.ttl)
                self.refs.move_to_end(ref)
                refs.append(dict(id=ref,label=redact(path.name)[:160],kind='image' if path.suffix.lower() in IMAGE_EXT else 'file'))
            self.prune()
        if refs:event['references']=refs

    def read(self,ref,row,*,reveal=False):
        with self.lock:
            self.prune();entry=self.refs.get(ref)
            if not entry or binding(row)!=entry['row']:raise PreviewUnavailable('reference_expired')
            entry=dict(entry)
        try:
            with open_bound_transcript(row['transcript_path']) as stream:
                assert_transcript_identity(row['transcript_path'],stream)
                if identity(stream)!=entry['inode']:raise PreviewUnavailable('reference_expired')
                item,digest=record_at(stream,entry['offset'])
                if digest!=entry['digest']:raise PreviewUnavailable('reference_expired')
                paths=extract_artifacts(item)['paths']
                if entry['index']>=len(paths):raise PreviewUnavailable('reference_expired')
                path=self.policy(paths[entry['index']],workspace(stream))
                if str(path)!=entry['key'][-1]:raise PreviewUnavailable('reference_expired')
                result=self.read_file(path)
                # Revalidate both the source record and file descriptor identity
                # before publishing; append-only transcript growth is allowed.
                if record_at(stream,entry['offset'])[1]!=entry['digest']:raise PreviewUnavailable('reference_expired')
                if self.policy(paths[entry['index']],workspace(stream))!=path:raise PreviewUnavailable('reference_expired')
                assert_transcript_identity(row['transcript_path'],stream)
            return path if reveal else result
        except (HistoryUnavailable,OSError,ValueError,KeyError,TypeError) as exc:
            if isinstance(exc,PreviewUnavailable):raise
            raise PreviewUnavailable('reference_expired') from None

    def owner(self,ref):
        with self.lock:
            self.prune();entry=self.refs.get(ref)
            if not entry:raise PreviewUnavailable('reference_expired')
            return entry['row'][0]

    def read_file(self,path):
        is_image=path.suffix.lower() in IMAGE_EXT
        maximum=MAX_IMAGE if is_image else MAX_TEXT
        with open_file(path) as (fd,info):
            if info.st_size>maximum:raise PreviewUnavailable('preview_too_large')
            data=os.read(fd,maximum+1)
            if len(data)>maximum:raise PreviewUnavailable('preview_too_large')
            if is_image:result=self.raster(data)
            else:
                try:text=data.decode('utf-8')
                except UnicodeError:raise PreviewUnavailable('preview_type_denied') from None
                if '\x00' in text or any(ord(c)<32 and c not in '\n\r\t' for c in text):raise PreviewUnavailable('preview_type_denied')
                result=dict(kind='text',mime='text/plain',text=redact(text))
            after=os.fstat(fd)
            with open_file(path) as (_,current):
                signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
                if signature(info)!=signature(after) or signature(info)!=signature(current):raise PreviewUnavailable('preview_changed')
        return dict(result,label=redact(path.name)[:160],notice='Current file · may differ from the recorded edit')

    def raster(self,data):
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
            return dict(kind='image',mime='image/png',data=base64.b64encode(output.getvalue()).decode('ascii'),width=width,height=height)
        except PreviewUnavailable:
            raise
        except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise PreviewUnavailable('preview_type_denied') from None
