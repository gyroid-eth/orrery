"""Recorded references and bounded previews, plus explicit local file clicks.

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
import shlex
import stat
import threading
import time
import warnings
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from conversation_artifacts import extract_artifacts
from conversation_history import codex_event, codex_user_content, open_bound_transcript, assert_transcript_identity, HistoryUnavailable, open_reader
from conversation_history import conversation_binding as binding
from conversation_images import input_images, saved_path, dsh_image_path
from conversation_markdown_images import IMAGE_EXT, local_image_target, markdown_image_targets
import conversation_step_command as step_command
import conversation_step_diff as step_diff
from mobile_attachment_store import ATTACHMENT_NAME, DIRECTORIES, FILE_SUFFIX, attachment_label, valid_extension

MAX_RECORD=1024*1024
MAX_TEXT=128*1024
MAX_IMAGE=8*1024*1024
# The phone relay independently checks these bounds on the PNG it publishes.
MOBILE_IMAGE_BYTES=4*1024*1024
MOBILE_IMAGE_PIXELS=8_000_000
TEXT_EXT={'.txt','.md','.py','.js','.mjs','.cjs','.ts','.tsx','.jsx','.css','.scss','.json','.jsonl',
          '.yaml','.yml','.toml','.ini','.cfg','.csv','.tsv','.xml','.html','.svg','.sh','.bash','.zsh',
          '.rs','.go','.c','.h','.cpp','.hpp','.java','.kt','.sql','.diff','.patch','.log','.rst'}
RASTER_FORMATS=('PNG','JPEG','GIF','WEBP')
COMPOSER_ATTACHMENT=re.compile(rf'@?(\./\.orrery-input-(?:images|files)/[a-f0-9]{{32}}(?:\.{FILE_SUFFIX})?)\Z')
PHONE_ATTACHMENT=re.compile(r"(?:\A| )\[(image|file): ('(?:[^']|'\\'')*')\]\Z")


def resolve_clicked_path(value):
    if (not isinstance(value,str) or len(value)>2000
            or not value.startswith(('/', '~/')) or re.search(r'[\x00-\x1f\x7f]',value)):
        raise PreviewUnavailable('preview_path_denied')
    try:
        original=Path(value).expanduser()
        path=original.resolve(strict=True)
        if (original.suffix.lower() in IMAGE_EXT)!=(path.suffix.lower() in IMAGE_EXT):
            raise PreviewUnavailable('preview_type_denied')
        return original,path
    except (OSError,ValueError,RuntimeError) as exc:
        if isinstance(exc,PreviewUnavailable):raise
        raise PreviewUnavailable('preview_unavailable') from None


def clicked_path(value):
    """Explicit local path click, independent of record grants."""
    original,path=resolve_clicked_path(value)
    try:
        result=ReferenceStore().read_file(path)
        if original.resolve(strict=True)!=path:raise PreviewUnavailable('preview_changed')
        result.pop('notice',None)
        return result
    except (OSError,ValueError,RuntimeError) as exc:
        if isinstance(exc,PreviewUnavailable):raise
        raise PreviewUnavailable('preview_unavailable') from None


class PreviewUnavailable(ValueError): pass


def identity(stream):
    info=os.fstat(stream.fileno());return info.st_dev,info.st_ino


def record_at(stream,offset,cache=None,*,normalized=False):
    if hasattr(stream,'provider'):
        if stream.provider!='codex':return stream.record_at(str(offset),cache,normalized=normalized)
        stream=stream.stream
    if offset<0:raise PreviewUnavailable('reference_expired')
    if offset and os.pread(stream.fileno(),1,offset-1)!=b'\n':raise PreviewUnavailable('reference_expired')
    data=os.pread(stream.fileno(),MAX_RECORD+1,offset)
    raw=data.split(b'\n',1)[0]
    if b'\n' not in data or len(raw)>MAX_RECORD:raise PreviewUnavailable('record_too_large')
    try:
        projection=codex_event(raw,offset) if normalized else json.loads(raw)
        payload=projection.get('payload') if isinstance(projection,dict) else None
        if isinstance(payload,dict) and payload.get('type')=='message' and payload.get('role')=='user':
            payload['content'],_=codex_user_content(payload.get('content'),payload)
        return projection,hashlib.sha256(raw).digest()
    except (ValueError,UnicodeError,RecursionError):raise PreviewUnavailable('reference_expired') from None


def workspace(stream):
    if hasattr(stream,'provider'):
        if stream.provider!='codex':return root_path(stream.cwd) if isinstance(stream.cwd,str) else None
        stream=stream.stream
    try:
        first=json.loads(os.pread(stream.fileno(),65536,0).split(b'\n',1)[0])
        cwd=first['payload']['cwd'] if first.get('type')=='session_meta' else None
        return root_path(cwd) if isinstance(cwd,str) else None
    except (ValueError,KeyError,TypeError):return None


def _step_inputs(stream, event_id, call_id, records=None):
    if stream.provider=='codex' and call_id is None:
        item,digest=record_at(stream,int(event_id))
        return (item,), (digest,)
    if stream.provider=='claude' and call_id is not None:
        call,_,call_digest=stream.claude_step_at(call_id,records)
        result,metadata,digest=stream.claude_step_at(event_id,records)
        return (call,result,metadata), (digest,call_digest)
    raise PreviewUnavailable('reference_expired')


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


def private_attachment(info):
    return info.st_uid==os.getuid() and (stat.S_IMODE(info.st_mode)&0o077)==0


def stored_attachment(path, cwd):
    """Only the attachment store layout under the recording's workspace."""
    if cwd is None or path.parent.parent!=cwd:
        return None
    kind=next((kind for kind,folder in DIRECTORIES.items() if path.parent.name==folder),None)
    name=ATTACHMENT_NAME.fullmatch(path.name)
    if not kind or not name or not valid_extension(kind, name[1] or ''):
        return None
    try:
        folder=path.parent.lstat()
        if not stat.S_ISDIR(folder.st_mode) or not private_attachment(folder):
            return None
        # This marker is written by the upload route, including in old stores.
        with open_file(path.parent/'.gitignore') as (fd,marker):
            if not private_attachment(marker) or os.read(fd,3)!=b'*\n':return None
        with open_file(path) as (_,info):
            if not private_attachment(info) or info.st_size==0:
                return None
            signature=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        label=''
        try:
            with open_file(path.with_name(path.name+'.label')) as (fd,meta):
                if private_attachment(meta) and meta.st_size<=640:
                    label=attachment_label(os.read(fd,641).decode('utf-8'))
        except (PreviewUnavailable,UnicodeError):
            pass  # Older uploads have no original filename.
        return dict(path=str(path),kind=kind,signature=signature,label=label,extension=name[1] or '')
    except (OSError,PreviewUnavailable):
        return None


def attachment_trailer(text,cwd,uploads=None):
    """Validate only the suffix emitted by the desktop or phone composer."""
    if cwd is None and not uploads:return text,[]
    parts=text.rstrip().rsplit('\n\n',1)
    lines=parts[-1].splitlines()
    if 0<len(lines)<=8 and all(COMPOSER_ATTACHMENT.fullmatch(line) for line in lines):
        displayed=[];attachments=[]
        for line in lines:
            value=COMPOSER_ATTACHMENT.fullmatch(line)[1].removeprefix('./')
            uploaded=(uploads or {}).get(value)
            if uploaded is not None:
                attachment=stored_attachment(uploaded,uploaded.parent.parent)
            else:
                attachment=stored_attachment(cwd/value,cwd) if cwd is not None else None
            if attachment:attachments.append(attachment)
            else:displayed.append(line)
        caption='\n\n'.join([*parts[:-1],*(['\n'.join(displayed)] if displayed else [])]) if attachments else text
        return caption,attachments
    remaining=text.rstrip();attachments=[]
    for _ in range(8):
        marker=PHONE_ATTACHMENT.search(remaining)
        if not marker:break
        try:paths=shlex.split(marker[2])
        except ValueError:break
        if len(paths)!=1:break
        attachment=stored_attachment(Path(paths[0]),cwd)
        if not attachment or attachment['kind']!=marker[1]:break
        attachments.append(attachment);remaining=remaining[:marker.start()]
    return (remaining,attachments[::-1]) if attachments else (text,[])


def resize_to_pixels(image, limit):
    width,height=image.size
    scale=(limit/(width*height))**0.5
    return image.resize((max(1,int(width*scale)),max(1,int(height*scale))),Image.Resampling.LANCZOS)


class ReferenceStore:
    def __init__(self,*,image_roots=(),workspace_roots=(),ttl=900,max_refs=4096,clock=time.monotonic,max_pixels=16_000_000):
        self.image_roots=tuple(root for value in image_roots if (root:=root_path(value)))
        self.workspace_roots=tuple(root for value in workspace_roots if (root:=root_path(value)))
        self.ttl,self.max_refs,self.clock,self.max_pixels=ttl,max_refs,clock,max_pixels
        self.refs=OrderedDict();self.by_key={};self.lock=threading.RLock()
        self.uploads=OrderedDict()

    def remember_upload(self,name,relative,path):
        """A verified composer upload also covers providers with no native cwd."""
        with self.lock:
            key=(name,relative.removeprefix('./'))
            self.uploads[key]=Path(path)
            self.uploads.move_to_end(key)
            while len(self.uploads)>1024:self.uploads.popitem(last=False)

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
        missing=object();cwd=missing;records={};images={}
        for event in events:
            if cwd is missing:
                try:cwd=workspace(stream)
                except (PreviewUnavailable,ValueError):cwd=None
            self.decorate(row,stream,event,cwd=cwd,records=records,images=images)
        self.decorate_step_details(row,stream,events,records)

    def decorate_step_details(self,row,stream,events,records):
        provider=getattr(stream,'provider',None)
        calls={}
        if provider=='claude':
            tools=step_diff.CLAUDE_EDIT_TOOLS | step_command.CLAUDE_COMMAND_TOOLS
            seen={step['id']:event for event in events if (step:=event.get('step',{})).get('phase')=='call'}
            calls={key:(event['id'],event['step']['tool']) for key,event in seen.items() if event['step'].get('tool') in tools}
            missing={step['id']:int(event['id'].split(':',1)[0]) for event in events
                     if (step:=event.get('step',{})).get('phase')=='result'
                     and step['id'] not in seen}
            calls.update(stream.claude_step_calls_before(missing,tools))
        elif provider!='codex':
            return
        owner,inode=binding(row),identity(stream)
        grants=[]
        for event in events:
            step=event.get('step',{})
            call=None
            if provider=='claude':
                match=calls.get(step.get('id'))
                if step.get('phase')!='result' or match is None:continue
                call,tool=match
                is_command=tool in step_command.CLAUDE_COMMAND_TOOLS
            else:
                tool=step.get('tool')
                if tool not in {'apply_patch','Shell'}:continue
                is_command=tool=='Shell'
            if not is_command and step.get('status')!='done':continue
            try:
                inputs,digests=_step_inputs(stream,event['id'],call,records)
                fields={}
                if is_command:
                    build=step_command.claude_command if provider=='claude' else step_command.codex_command
                    command=build(*inputs)
                    if command is None:continue
                    if command.exit_code is not None:fields['exit_code']=command.exit_code
                    if command.interrupted or command.exit_code not in (None,0):fields['status']='failed'
                else:
                    build=step_diff.claude_diff if provider=='claude' else step_diff.codex_diff
                    changes=step_diff.stat(build(*inputs))
                    if changes is None:continue
                    fields['diff_stat']=changes
            except (OSError,ValueError,UnicodeError,RecursionError):
                continue
            grants.append((event,call,digests,is_command,fields))
        if not grants:return
        with self.lock:
            self.prune()
            for event,call,digests,is_command,fields in grants:
                event_id=event['id']
                kind='step_command' if is_command else 'step_diff'
                key=(owner,inode,kind,event_id,call,digests)
                ref=self.by_key.get(key)
                if ref not in self.refs or self.refs[ref]['key']!=key:ref=secrets.token_urlsafe(24)
                self.by_key[key]=ref
                self.refs[ref]=dict(key=key,row=owner,inode=inode,step=(kind,event_id,call,digests),
                                    expires=self.clock()+self.ttl)
                self.refs.move_to_end(ref)
                fields['detail_ref' if is_command else 'diff_ref']=ref
                event['step']=dict(event['step'],**fields)
            self.prune()

    def decorate(self,row,stream,event,*,cwd=False,records=None,images=None):
        """Only called on selected events from an already pinned bound transcript."""
        try:
            offset=event['id'] if hasattr(stream,'provider') and stream.provider!='codex' else int(event['id'])
            targets=markdown_image_targets(event)
            if targets:
                self.decorate_markdown(row,stream,event,offset,targets,records,images)
            if event.get('kind')=='mail' or event.get('kind')=='text' and event.get('role')=='assistant':return
            item,digest=record_at(stream,offset,records)
            projection=extract_artifacts(item)
            if cwd is False:cwd=workspace(stream)
        except ValueError:return
        if event.get('kind')=='text' and event.get('role')=='user':
            attachments=self.decorate_attachments(row,stream,event,digest,cwd)
            self.decorate_input(row,stream,event,item,digest,exclude=attachments)
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

    def markdown_image_path(self,target):
        """Check a pinned local raster header before offering a reference."""
        if not local_image_target(target):raise PreviewUnavailable('preview_type_denied')
        original,path=resolve_clicked_path(target)
        with open_file(path) as (fd,info):
            if info.st_size>MAX_IMAGE:raise PreviewUnavailable('preview_too_large')
            try:
                with warnings.catch_warnings(),os.fdopen(os.dup(fd),'rb') as file:
                    warnings.simplefilter('error',Image.DecompressionBombWarning)
                    with Image.open(file,formats=RASTER_FORMATS) as image:
                        width,height=image.size
                        if width>8192 or height>8192 or width*height>self.max_pixels:
                            raise PreviewUnavailable('preview_too_large')
            except PreviewUnavailable:raise
            except (OSError,ValueError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning):
                raise PreviewUnavailable('preview_not_image') from None
        if original.resolve(strict=True)!=path:raise PreviewUnavailable('preview_changed')
        return path

    def decorate_markdown(self,row,stream,event,offset,targets,records,images):
        # A page may have been read before an in-place transcript edit. Only
        # targets also present in the record we actually pin may grant an ID.
        try:current,digest=record_at(stream,offset,records,normalized=True)
        except ValueError:return
        allowed=set(markdown_image_targets(current))
        images={} if images is None else images
        grants=[]
        for target in targets:
            if target not in allowed:continue
            if target not in images:
                try:images[target]=self.markdown_image_path(target)
                except (OSError,ValueError,RuntimeError):images[target]=None
            if images[target] is not None:grants.append((target,images[target]))
        if not grants:return
        owner,inode=binding(row),identity(stream)
        refs=[]
        with self.lock:
            self.prune()
            for target,path in grants:
                key=(owner,inode,event['id'],digest,'markdown_image',target,str(path))
                ref=self.by_key.get(key)
                if ref not in self.refs or self.refs[ref]['key']!=key:ref=secrets.token_urlsafe(24)
                self.by_key[key]=ref
                self.refs[ref]=dict(key=key,row=owner,inode=inode,offset=offset,digest=digest,
                                    markdown_image=target,expires=self.clock()+self.ttl)
                self.refs.move_to_end(ref)
                refs.append(dict(target=target,id=ref))
            self.prune()
        event['markdown_images']=refs

    @staticmethod
    def image_key(image):
        return hashlib.sha256(json.dumps(image,sort_keys=True).encode()).digest()

    def decorate_attachments(self,row,stream,event,digest,cwd):
        if event.get('truncated'):return set()
        text=event['text'];suffix=''
        if event.get('input_image_marker')=='suffix' and text.endswith('\n[image attachment]'):
            suffix='\n[image attachment]';text=text.removesuffix(suffix)
        # Most records use their bound native workspace, including after a
        # bridge restart. The small upload cache also covers agy and cd'd panes.
        uploads={}
        if COMPOSER_ATTACHMENT.fullmatch(text.rstrip().rsplit('\n',1)[-1]):
            with self.lock:
                uploads={value:path for (agent,value),path in self.uploads.items() if agent==row.get('name')}
        caption,attachments=attachment_trailer(text,cwd,uploads)
        if not attachments:return set()
        event['input_display_text']=caption+suffix
        if any(attachment['kind']=='image' for attachment in attachments):event['input_images']=True
        refs=[]
        with self.lock:
            self.prune()
            for index,attachment in enumerate(attachments):
                key=(binding(row),identity(stream),event['id'],digest,'attachment',index,self.image_key(attachment))
                ref=self.by_key.get(key)
                if ref not in self.refs or self.refs[ref]['key']!=key:ref=secrets.token_urlsafe(24)
                self.by_key[key]=ref
                offset=event['id'] if hasattr(stream,'provider') and stream.provider!='codex' else int(event['id'])
                extension=attachment['extension']
                label=attachment['label'] or f"Attachment {index+1}"+('.'+extension if extension else '')
                self.refs[ref]=dict(key=key,row=binding(row),inode=identity(stream),offset=offset,
                                    digest=digest,attachment=attachment,label=label,expires=self.clock()+self.ttl)
                self.refs.move_to_end(ref)
                projected=dict(id=ref,label=label,kind=attachment['kind'])
                if attachment['kind']=='image':projected['input_image']=True
                refs.append(projected)
            self.prune()
        event['references']=refs
        return {attachment['path'] for attachment in attachments}

    def decorate_input(self,row,stream,event,item,digest,*,exclude=()):
        refs=[]
        with self.lock:
            self.prune()
            for index,image in enumerate(input_images(item)):
                if image.get('path') in exclude:continue
                key=(binding(row),identity(stream),event['id'],digest,index,self.image_key(image))
                ref=self.by_key.get(key)
                if ref not in self.refs or self.refs[ref]['key']!=key:ref=secrets.token_urlsafe(24)
                self.by_key[key]=ref
                self.refs[ref]=dict(key=key,row=binding(row),inode=identity(stream),offset=event['id'] if hasattr(stream,'provider') and stream.provider!='codex' else int(event['id']),
                                    digest=digest,index=index,input_image=True,expires=self.clock()+self.ttl)
                self.refs.move_to_end(ref)
                projected=dict(id=ref,label=f'Input image {index+1}.png',kind='image',input_image=True)
                if 'slot' in image:projected['input_image_slot']=image['slot']
                refs.append(projected)
            self.prune()
        if refs:event['references']=(refs+event.get('references',[]))[:8];event['input_images']=True

    def read_input(self,image,stream,*,thumbnail=False,mobile=False):
        if image['kind']=='data':
            data=base64.b64decode(image['url'].split(',',1)[1],validate=True)
            if len(data)>MAX_IMAGE:raise PreviewUnavailable('preview_too_large')
            return self.raster(data,thumbnail=thumbnail,mobile=mobile)
        if image['kind']=='dsh':
            path=dsh_image_path(stream.path,image['digest'])
            if path is None:raise PreviewUnavailable('preview_unavailable')
            return self.read_file(path,thumbnail=thumbnail,mobile=mobile,image_digest=image['digest'])
        path=saved_path(image['path'])
        if path is None:raise PreviewUnavailable('reference_expired')
        result=self.read_file(path,thumbnail=thumbnail,mobile=mobile)
        if result['kind']!='image' or saved_path(image['path'])!=path:raise PreviewUnavailable('reference_expired')
        return result

    def read(self,ref,row,*,reveal=False,thumbnail=False,mobile=False):
        with self.lock:
            self.prune();entry=self.refs.get(ref)
            if not entry or 'step' in entry or binding(row)!=entry['row']:raise PreviewUnavailable('reference_expired')
            entry=dict(entry)
        try:
            with open_reader(row) as stream:
                stream.assert_identity()
                if identity(stream)!=entry['inode']:raise PreviewUnavailable('reference_expired')
                item,digest=record_at(stream,entry['offset'])
                if digest!=entry['digest']:raise PreviewUnavailable('reference_expired')
                markdown=entry.get('markdown_image')
                attachment=entry.get('attachment')
                if markdown:
                    if reveal:raise PreviewUnavailable('preview_unavailable')
                    original,path=resolve_clicked_path(markdown)
                    if str(path)!=entry['key'][-1] or path.suffix.lower() not in IMAGE_EXT:
                        raise PreviewUnavailable('reference_expired')
                    result=self.read_file(path,thumbnail=thumbnail,mobile=mobile)
                elif attachment:
                    path=Path(attachment['path'])
                    cwd=path.parent.parent  # Already admitted when this bound reference was issued.
                    if reveal or stored_attachment(path,cwd)!=attachment:raise PreviewUnavailable('reference_expired')
                    result=self.read_file(path,thumbnail=thumbnail,mobile=mobile)
                    result=dict(result,label=entry['label'],notice='Recorded input attachment')
                elif entry.get('input_image'):
                    if reveal:raise PreviewUnavailable('preview_unavailable')
                    images=input_images(item)
                    if entry['index']>=len(images) or self.image_key(images[entry['index']])!=entry['key'][-1]:raise PreviewUnavailable('reference_expired')
                    result=self.read_input(images[entry['index']],stream,thumbnail=thumbnail,mobile=mobile)
                    result=dict(result,label=f"Input image {entry['index']+1}.png",notice='Recorded input image')
                else:
                    projection=extract_artifacts(item);paths=projection['paths']
                    if entry['index']>=len(paths):raise PreviewUnavailable('reference_expired')
                    value=paths[entry['index']];shown=value in projection['shown_paths']
                    path=self.policy(value,workspace(stream),shown=shown)
                    if str(path)!=entry['key'][-1]:raise PreviewUnavailable('reference_expired')
                    result=self.read_file(path,thumbnail=thumbnail,mobile=mobile)
                # Revalidate both the source record and file descriptor identity
                # before publishing; append-only transcript growth is allowed.
                if record_at(stream,entry['offset'])[1]!=entry['digest']:raise PreviewUnavailable('reference_expired')
                if markdown:
                    if original.resolve(strict=True)!=path:raise PreviewUnavailable('reference_expired')
                elif attachment:
                    if stored_attachment(path,cwd)!=attachment:raise PreviewUnavailable('reference_expired')
                elif not entry.get('input_image') and self.policy(value,workspace(stream),shown=shown)!=path:raise PreviewUnavailable('reference_expired')
                stream.assert_identity()
            return path if reveal else result
        except (HistoryUnavailable,OSError,ValueError,KeyError,TypeError) as exc:
            if isinstance(exc,PreviewUnavailable):raise
            raise PreviewUnavailable('reference_expired') from None

    def read_step_diff(self,ref,row):
        def render(provider,inputs):
            build=step_diff.claude_diff if provider=='claude' else step_diff.codex_diff
            files=build(*inputs)
            return step_diff.detail(files) if step_diff.stat(files) is not None else None
        return self.read_step(ref,row,'step_diff',render)

    def read_step_command(self,ref,row):
        def render(provider,inputs):
            build=step_command.claude_command if provider=='claude' else step_command.codex_command
            command=build(*inputs)
            return step_command.detail(command) if command is not None else None
        return self.read_step(ref,row,'step_command',render)

    def read_step(self,ref,row,kind,render):
        with self.lock:
            self.prune()
            entry=self.refs.get(ref)
            pinned=entry and entry.get('step')
            if not pinned or pinned[0]!=kind or binding(row)!=entry['row']:
                raise PreviewUnavailable('reference_expired')
        _,event_id,call_id,expected=pinned
        try:
            with open_reader(row,expect_inode=entry['inode']) as stream:
                inputs,digests=_step_inputs(stream,event_id,call_id)
                if digests!=expected:raise PreviewUnavailable('reference_expired')
                result=render(stream.provider,inputs)
                if result is None or _step_inputs(stream,event_id,call_id)[1]!=expected:
                    raise PreviewUnavailable('reference_expired')
                stream.assert_identity()
                return result
        except (OSError,ValueError,TypeError,KeyError,RecursionError):
            raise PreviewUnavailable('reference_expired') from None

    def owner(self,ref):
        with self.lock:
            self.prune();entry=self.refs.get(ref)
            if not entry:raise PreviewUnavailable('reference_expired')
            return entry['row'][0]

    def read_file(self,path,*,thumbnail=False,mobile=False,image_digest=None):
        is_image=image_digest is not None or path.suffix.lower() in IMAGE_EXT
        maximum=MAX_IMAGE if is_image else MAX_TEXT*4  # Up to four UTF-8 bytes per character.
        too_large='preview_too_large' if is_image else 'preview_text_too_large'
        with open_file(path) as (fd,info):
            if info.st_size>maximum:raise PreviewUnavailable(too_large)
            data=os.read(fd,maximum+1)
            if len(data)>maximum:raise PreviewUnavailable(too_large)
            if image_digest is not None and hashlib.sha256(data).hexdigest()!=image_digest:raise PreviewUnavailable('preview_changed')
            if is_image:result=self.raster(data,thumbnail=thumbnail,mobile=mobile)
            else:
                try:text=data.decode('utf-8')
                except UnicodeError:raise PreviewUnavailable('preview_not_text') from None
                if len(text)>MAX_TEXT:raise PreviewUnavailable(too_large)
                if any(ord(c)<32 and c not in '\n\r\t' for c in text):raise PreviewUnavailable('preview_not_text')
                result=dict(kind='text',mime='text/plain',text=text)
            after=os.fstat(fd)
            with open_file(path) as (_,current):
                signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
                if signature(info)!=signature(after) or signature(info)!=signature(current):raise PreviewUnavailable('preview_changed')
        return dict(result,label=path.name[:160],notice='Current file · may differ from the recorded edit')

    def raster(self,data,*,thumbnail=False,mobile=False):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in RASTER_FORMATS:raise PreviewUnavailable('preview_type_denied')
                    width,height=image.size
                    if width>8192 or height>8192 or width*height>self.max_pixels:raise PreviewUnavailable('preview_too_large')
                    image.seek(0);image.load()
                    clean=image.convert('RGBA')
                    # Copy only pixels: original EXIF/ICC/text/animation metadata
                    # never leaves this process.
                    pixels=Image.frombytes('RGBA',clean.size,clean.tobytes())
                    if thumbnail:
                        pixels.thumbnail((320,200),Image.Resampling.LANCZOS)
                    elif mobile and width*height>MOBILE_IMAGE_PIXELS:
                        pixels=resize_to_pixels(pixels,MOBILE_IMAGE_PIXELS)
                    limit=MOBILE_IMAGE_BYTES if mobile else MAX_IMAGE
                    output=io.BytesIO();pixels.save(output,format='PNG')
                    if output.tell()>limit:
                        # Allow for four RGBA bytes per pixel, PNG row filters
                        # and compression overhead even for noisy images.
                        pixels=resize_to_pixels(pixels,limit//5)
                        output=io.BytesIO();pixels.save(output,format='PNG')
                    if output.tell()>limit:raise PreviewUnavailable('preview_too_large')
                    # The relay checks its reported dimensions against the PNG header.
                    if mobile or not thumbnail:width,height=pixels.size
            return dict(kind='image',mime='image/png',data=base64.b64encode(output.getvalue()).decode('ascii'),width=width,height=height)
        except PreviewUnavailable:
            raise
        except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise PreviewUnavailable('preview_type_denied') from None
