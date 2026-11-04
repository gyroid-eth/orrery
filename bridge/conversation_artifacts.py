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
SECRET_PART = re.compile(r'(^|[._-])(auth(?:entication)?|tokens?|secrets?|credentials?|passwords?|private|keys?)([._-]|$)', re.I)


def secret_path(path: str) -> bool:
    for index,part in enumerate(PurePath(path).parts):
        if index==1 and part=='private' and path.startswith('/private/'):
            continue  # macOS canonical /private/tmp and /private/var are roots.
        lower=part.lower()
        if (lower in {'.ssh','.aws','.gnupg','.env','env.sh','storage.sqlite3','id_rsa','id_ed25519'}
                or lower.startswith('.env.') or lower.endswith(('.pem','.key','.p12','.pfx','.sqlite','.sqlite3'))
                or SECRET_PART.search(lower)):
            return True
    return False


def redact(text: str) -> str:
    text=re.sub(r'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b','[redacted]',text)
    text=re.sub(r'(?im)(\bauthorization\s*[:=]\s*(?:bearer\s+)?)[^\s"\']+',r'\1[redacted]',text)
    text=re.sub(r'(?im)((?:api[_-]?key|access[_-]?token|password|secret)\s*["\']?\s*[:=]\s*)[^\n,]+',r'\1[redacted]',text)
    text=re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)','[redacted private key]',text)
    return text


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


def static_calls(text):
    reader=Literal(text)
    while reader.pos<len(text):
        try:
            reader.space()
            if reader.pos>=len(text):return
            if text[reader.pos] in '\"\'`': reader.string();continue
            # Slash syntax outside strings/comments may be a JS regexp (whose
            # contents are not calls) or an expression. Refuse the ambiguous
            # remainder rather than parsing code-like text inside a regexp.
            if text[reader.pos]=='/':return
            match=(re.match(r'tools\.(apply_patch|view_image|read_file|write_file|Edit|Read)\s*\(',text[reader.pos:])
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
    result=dict(paths=[],diff='',diff_status='Recorded edit request · outcome unconfirmed')
    if not isinstance(item,dict) or item.get('type')!='response_item':return result
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
    calls=list(static_calls(value)) if name=='exec' and isinstance(value,str) else [(name,value)]
    diffs=[];diff_bytes=0
    def diff(line):
        nonlocal diff_bytes
        if diff_bytes>=MAX_DIFF:return
        line=line[:MAX_DIFF-diff_bytes]
        diffs.append(line);diff_bytes+=len(line)+1
    def path(value):
        if (isinstance(value,str) and 0<len(value)<4096 and not secret_path(value)
                and not re.search(r'[\x00-\x1f\x7f]|://|^~',value) and len(result['paths'])<MAX_REFS
                and value not in result['paths']):result['paths'].append(value)
    for name,value in calls[:MAX_REFS]:
        if name=='apply_patch' and isinstance(value,str):
            safe=False
            for line in value.splitlines()[:4000]:
                match=re.match(r'\*\*\* (Add|Update|Delete) File: (.+)$',line)
                if match:
                    operation,filename=match[1],match[2];safe=not secret_path(filename)
                    if safe:
                        label=PurePath(filename).name if filename.startswith('/') else filename
                        path(filename)
                        diff('--- '+('/dev/null' if operation=='Add' else 'a/'+redact(label)))
                        diff('+++ '+('/dev/null' if operation=='Delete' else 'b/'+redact(label)))
                        if operation=='Delete':diff('[recorded deletion request; original content unavailable]')
                    else:diff('[sensitive file edit omitted]')
                elif line.startswith('*** Move to: '):
                    target=line[13:]
                    if safe and not secret_path(target):path(target);diff('rename to '+redact(PurePath(target).name if target.startswith('/') else target))
                    else:safe=False;diff('[sensitive file edit omitted]')
                elif safe and (line.startswith(('+','-',' ','@@')) or line=='*** End of File'):
                    diff(redact(line))
                if diff_bytes>=MAX_DIFF:break
        elif isinstance(value,dict) and name in {'view_image','read_file','write_file','Read','Edit'}:
            path(value.get('path',value.get('file_path')))
            if name=='Edit':
                old,new=value.get('old_string'),value.get('new_string')
                if isinstance(old,str) and isinstance(new,str) and not secret_path(str(value.get('file_path',''))):
                    for line in ['@@ recorded replacement @@']+['-'+redact(x) for x in old[:MAX_DIFF].splitlines()]+['+'+redact(x) for x in new[:MAX_DIFF].splitlines()]:diff(line)
    result['diff']='\n'.join(diffs)[:MAX_DIFF]
    return result
