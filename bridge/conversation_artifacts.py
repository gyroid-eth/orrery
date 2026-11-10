"""Pure, bounded projection of structured provider calls. Never execute tool code.

Raw arguments/results and arbitrary Markdown paths are deliberately not emitted.
The tiny JS-literal reader handles static calls in Codex's functions.exec wrapper;
computed expressions, interpolation and unknown syntax are ignored.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePath

MAX_DIFF = 48 * 1024
MAX_INPUT = 1024 * 1024
MAX_REFS = 24


class Literal:
    """Subset of data literals, with bounded recursion; no eval, code or getters."""
    def __init__(self,text,pos=0): self.text,self.pos=text,pos

    def space(self):
        while self.pos<len(self.text):
            if self.text[self.pos].isspace(): self.pos+=1
            elif self.text.startswith('//',self.pos):
                end=self.text.find('\n',self.pos);self.pos=len(self.text) if end<0 else end+1
            elif self.text.startswith('/*',self.pos):
                end=self.text.find('*/',self.pos+2)
                if end<0: raise ValueError
                self.pos=end+2
            else: break

    def string(self):
        quote=self.text[self.pos];self.pos+=1;out=[]
        while self.pos<len(self.text):
            ch=self.text[self.pos];self.pos+=1
            if ch==quote: return ''.join(out)
            if quote=='`' and ch=='$' and self.text[self.pos:self.pos+1]=='{': raise ValueError
            if ch=='\\':
                if self.pos>=len(self.text): raise ValueError
                ch=self.text[self.pos];self.pos+=1
                if ch in {'u','x'}:
                    count=4 if ch=='u' else 2
                    code=self.text[self.pos:self.pos+count]
                    if not re.fullmatch('[0-9a-fA-F]{'+str(count)+'}',code): raise ValueError
                    out.append(chr(int(code,16)));self.pos+=count;continue
                ch={'n':'\n','r':'\r','t':'\t','b':'\b','f':'\f','v':'\v','\n':''}.get(ch,ch)
            out.append(ch)
        raise ValueError

    def value(self,depth=0):
        if depth>8: raise ValueError
        self.space()
        if self.pos>=len(self.text): raise ValueError
        char=self.text[self.pos]
        if char in '\"\'`': return self.string()
        if char in '{[':
            object_=char=='{';end='}' if object_ else ']';self.pos+=1;out={} if object_ else []
            for _ in range(256):
                self.space()
                if self.text[self.pos:self.pos+1]==end:self.pos+=1;return out
                if object_:
                    if self.text[self.pos:self.pos+1] in {'"',"'"}: key=self.string()
                    else:
                        match=re.match(r'[A-Za-z_$][\w$]*',self.text[self.pos:])
                        if not match:raise ValueError
                        key=match[0];self.pos+=len(key)
                    self.space()
                    if self.text[self.pos:self.pos+1]!=':':raise ValueError
                    self.pos+=1;out[key]=self.value(depth+1)
                else:out.append(self.value(depth+1))
                self.space()
                if self.text[self.pos:self.pos+1]==end:self.pos+=1;return out
                if self.text[self.pos:self.pos+1]!=',':raise ValueError
                self.pos+=1
            raise ValueError
        match=re.match(r'(?:true|false|null|-?\d+(?:\.\d+)?)\b',self.text[self.pos:])
        if not match:raise ValueError
        self.pos+=len(match[0]);return json.loads(match[0])


# ORRERY Mail's local show_files tool, as each harness records its name: Claude
# and dsh `mcp__orrery-mail__show_files`; Codex and Hermes `mcp__orrery_mail__show_files`.
# Only this server's tool; a same-named tool of another server grants nothing.
SHOW_FILES=re.compile(r'mcp__orrery[-_]mail__show_files')


def completed_show_files(item):
    """Codex's Paginated and Legacy histories record MCP completions.

    Only the known completion envelope and its structured arguments count.
    Wrapper source, tool-result prose and other item_completed events do not.
    """
    if not isinstance(item,dict) or item.get('type')!='event_msg':return None
    payload=item.get('payload')
    if not isinstance(payload,dict):return None
    if payload.get('type')=='item_completed':
        call=payload.get('item')
        if (not isinstance(call,dict) or call.get('type')!='McpToolCall'
                or call.get('status')!='completed'):return None
    elif payload.get('type')=='mcp_tool_call_end':
        # McpToolCallEndEvent.result is Result<CallToolResult,String>.
        # Only Ok is success; CallToolResult uses the wire key isError, which
        # may be absent/null/false. Never use text inside its content as paths.
        result=payload.get('result')
        if not isinstance(result,dict) or set(result)!={'Ok'}:return None
        result=result['Ok']
        if (not isinstance(result,dict) or not isinstance(result.get('content'),list)
                or 'is_error' in result
                or result.get('isError') is not None and result['isError'] is not False):return None
        call=payload.get('invocation')
    else:return None
    if (not isinstance(call,dict) or call.get('server')!='orrery-mail'
            or call.get('tool')!='show_files' or not isinstance(call.get('arguments'),dict)):return None
    return call['arguments']


def static_calls(text,names=('apply_patch','view_image','read_file','write_file','Edit','Read','SendUserFile',
                             'mcp__orrery_mail__show_files')):
    reader=Literal(text)
    pattern=r'tools\.('+ '|'.join(re.escape(name) for name in names)+r')\s*\('
    while reader.pos<len(text):
        try:
            reader.space()
            if reader.pos>=len(text):return
            if text[reader.pos] in '\"\'`': reader.string();continue
            # Slash syntax outside strings/comments may be a JS regexp (whose
            # contents are not calls) or an expression. Refuse the ambiguous
            # remainder rather than parsing code-like text inside a regexp.
            if text[reader.pos]=='/':return
            match=(re.match(pattern,text[reader.pos:])
                   if reader.pos==0 or not re.match(r'[\w$.]',text[reader.pos-1]) else None)
            if match:
                reader.pos+=len(match[0]);value=reader.value();reader.space()
                if text[reader.pos:reader.pos+1]==')':yield match[1],value
            reader.pos+=1
        except (ValueError,IndexError):
            # A computed call is not a reference grant. Skip its remainder;
            # scanning inside it could misclassify an embedded string as code.
            return


def extract_artifacts(item: dict) -> dict:
    result=dict(paths=[],shown_paths=[],diff='',diff_status='Recorded edit request · outcome unconfirmed')
    if not isinstance(item,dict):return result
    completed=completed_show_files(item)
    if completed is not None:
        item=dict(type='response_item',payload=dict(type='function_call',
                  name='mcp__orrery_mail__show_files',arguments=completed))
    if item.get('type')=='recorded_fs_result':
        # dsh-tool-fs stores contextual before/after hunks at result time.
        paths=[];diffs=[]
        values=item.get('diffs')
        for value in values[:MAX_REFS] if isinstance(values,list) else []:
            if not isinstance(value,dict):continue
            path=value.get('path');old=value.get('oldText');new=value.get('newText')
            if (not isinstance(path,str) or len(path)>4096
                    or not (old is None or isinstance(old,str)) or not isinstance(new,str)):continue
            paths.append(path)
            diffs.extend(['--- '+PurePath(path).name,'+++ '+PurePath(path).name,'@@ recorded result hunk @@'])
            diffs.extend('-'+x for x in (old or '')[:MAX_DIFF].splitlines())
            diffs.extend('+'+x for x in new[:MAX_DIFF].splitlines())
            if sum(map(len,diffs))>=MAX_DIFF:break
        return dict(paths=paths,shown_paths=[],diff='\n'.join(diffs)[:MAX_DIFF],diff_status='Recorded file tool result · contextual hunk')
    if item.get('type')!='response_item':return result
    p=item.get('payload')
    if not isinstance(p,dict) or p.get('type') not in {'function_call','custom_tool_call'}:return result
    if not isinstance(p.get('name'),str):return result
    name=p['name'].split('.')[-1]
    value=p.get('input')
    if not isinstance(value,str):
        value=p.get('arguments')
        if isinstance(value,str) and len(value)<=MAX_INPUT:
            try:value=json.loads(value)
            except ValueError:return result
    if isinstance(value,str) and len(value)>MAX_INPUT:return result
    wrapped=name=='exec' and isinstance(value,str)
    calls=list(static_calls(value)) if wrapped else [(name,value)]
    diffs=[];diff_bytes=0
    def diff(line):
        nonlocal diff_bytes
        if diff_bytes>=MAX_DIFF:return
        line=line[:MAX_DIFF-diff_bytes]
        diffs.append(line);diff_bytes+=len(line)+1
    def path(value,*,shown=False):
        if (isinstance(value,str) and 0<len(value)<4096
                and not re.search(r'[\x00-\x1f\x7f]|://|^~',value)):
            if value not in result['paths'] and len(result['paths'])<MAX_REFS:result['paths'].append(value)
            # A wrapper's lexical paths keep their old root restrictions.
            # Only recorded calls, not source text, grant an external image.
            if shown and value in result['paths'] and value not in result['shown_paths']:result['shown_paths'].append(value)
    for name,value in calls[:MAX_REFS]:
        if SHOW_FILES.fullmatch(name) and isinstance(value,dict):
            # The agent names files to show; the preview's own checks decide.
            paths=value.get('paths')
            for filename in paths[:MAX_REFS] if isinstance(paths,list) else []:path(filename,shown=not wrapped)
        elif name=='SendUserFile' and isinstance(value,dict):
            # Claude's native delivery call records files: string[]. Caption,
            # status and tool-result prose never grant additional references.
            files=value.get('files')
            for filename in files[:MAX_REFS] if isinstance(files,list) else []:path(filename,shown=not wrapped)
        elif name=='apply_patch' and isinstance(value,str):
            safe=False
            for line in value.splitlines()[:4000]:
                match=re.match(r'\*\*\* (Add|Update|Delete) File: (.+)$',line)
                if match:
                    operation,filename=match[1],match[2];safe=True
                    label=PurePath(filename).name if filename.startswith('/') else filename
                    path(filename)
                    diff('--- '+('/dev/null' if operation=='Add' else 'a/'+label))
                    diff('+++ '+('/dev/null' if operation=='Delete' else 'b/'+label))
                    if operation=='Delete':diff('[recorded deletion request; original content unavailable]')
                elif line.startswith('*** Move to: '):
                    target=line[13:]
                    if safe:path(target);diff('rename to '+(PurePath(target).name if target.startswith('/') else target))
                elif safe and (line.startswith(('+','-',' ','@@')) or line=='*** End of File'):
                    diff(line)
                if diff_bytes>=MAX_DIFF:break
        elif isinstance(value,dict) and name in {'view_image','read_file','write_file','Read','Write','Edit','read','write','edit','patch'}:
            path(value.get('path',value.get('file_path')))
            if name in {'Edit','edit','patch'}:
                old,new=value.get('old_string'),value.get('new_string')
                filename=value.get('file_path',value.get('path'))
                if isinstance(filename,str) and filename and isinstance(old,str) and isinstance(new,str):
                    for line in ['@@ recorded replacement @@']+['-'+x for x in old[:MAX_DIFF].splitlines()]+['+'+x for x in new[:MAX_DIFF].splitlines()]:diff(line)
            if name=='patch' and isinstance(value.get('patch'),str):
                # Hermes unified patch request. Only explicit file headers grant
                # paths; omit incomplete file hunks and all arbitrary prose.
                safe=False;previous=None
                for line in value['patch'][:MAX_INPUT].splitlines()[:4000]:
                    if line.startswith(('--- ','+++ ')):
                        target=line[4:].split('\t',1)[0]
                        if target.startswith(('a/','b/')):target=target[2:]
                        if line.startswith('--- '):
                            previous=target;safe=False
                        else:
                            safe=previous is not None
                            if safe:
                                for prefix,filename in [('--- ',previous),('+++ ',target)]:
                                    if filename!='/dev/null':path(filename)
                                    diff(prefix+PurePath(filename).name)
                            else:diff('[incomplete file edit omitted]')
                    elif safe and line.startswith(('+','-',' ','@@')):diff(line)
    result['diff']='\n'.join(diffs)[:MAX_DIFF]
    return result
