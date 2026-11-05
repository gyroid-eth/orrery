"""Native provider adapters. Bound paths only, no discovery or provider imports.

JSONL cursors address a record/block; Zstd cursors address a frame/line/block.
Hermes is a bounded active-segment snapshot because native rows can be rewritten.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import quote
from conversation_mail import received, sent

from conversation_history import (HistoryUnavailable, MAX_SCAN, MAX_TEXT, PAGE_SIZE,
    open_bound_transcript, assert_transcript_identity, read_codex_page)

try:
    import zstandard as zstd
except ImportError:
    zstd = None

MAX_RECORD = 1024 * 1024
MAX_BLOCKS = 64
NATIVE_CURSOR = re.compile(r'([a-f0-9]{24}):(\d{1,20}):(\d{1,10}):(\d{1,3})\Z')
MAGIC = b'\x28\xb5\x2f\xfd'


def provider(row):
    p = row.get('program')
    return {'codex':'codex','codex-cli':'codex','claude':'claude','claude-code':'claude',
            'dsh':'dsh','hermes':'hermes'}.get(p)


def parse(raw):
    try:
        value=json.loads(raw)
        return value if isinstance(value,dict) else {}
    except (ValueError,UnicodeError):return {}


def epoch(value, divisor=1):
    try:
        if isinstance(value,bool):return ''
        return datetime.fromtimestamp(float(value)/divisor,timezone.utc).isoformat().replace('+00:00','Z')
    except (ValueError,TypeError,OverflowError,OSError):return ''


def text_event(text,role,ts):
    if not isinstance(text,str) or not text.strip():return None
    return received(dict(kind='text',role=role,text=text[:MAX_TEXT],truncated=len(text)>MAX_TEXT,ts=ts))


def tool_event(name,ts,*,result=False,failed=False):
    if not isinstance(name,str):name='Tool'
    return dict(kind='tool_result' if result else 'tool',role='assistant',
                text=(name[:160]+(' · failed' if failed else ' · completed')) if result else name[:160],ts=ts)


def blocks_text(content):
    if isinstance(content,str):return content
    if not isinstance(content,list):return ''
    return '\n'.join(b['text'][:MAX_TEXT] for b in content[:MAX_BLOCKS] if isinstance(b,dict)
        and b.get('type')=='text' and isinstance(b.get('text'),str))[:MAX_TEXT+1]


def normalize(item,p,sid):
    """Return (block-index,event) pairs; hidden/reasoning/raw tool bodies excluded."""
    out=[]
    def add(index,event):
        if event:out.append((index,event))
    if p=='claude':
        if item.get('sessionId')!=sid or item.get('isSidechain') or item.get('isMeta'):return []
        role=item.get('type');message=item.get('message')
        if role not in {'user','assistant'} or not isinstance(message,dict) or message.get('role')!=role:return []
        content=message.get('content');ts=str(item.get('timestamp') or '')[:128]
        if isinstance(content,str):add(0,text_event(content,role,ts))
        elif isinstance(content,list):
            for i,b in enumerate(content[:MAX_BLOCKS]):
                if not isinstance(b,dict):continue
                if b.get('type')=='text':add(i,text_event(b.get('text'),role,ts))
                elif b.get('type')=='tool_use' and role=='assistant':add(i,sent(tool_event(b.get('name'),ts),b.get('name'),b.get('input')))
                elif b.get('type')=='tool_result' and role=='user':
                    add(i,tool_event('Tool result',ts,result=True,failed=bool(b.get('is_error'))))
                elif b.get('type') in {'image','document'}:add(i,text_event('[attachment]',role,ts))
    elif p=='dsh':
        if item.get('surfaceOp','append')!='append':return []
        kind=item.get('type');data=item.get('data');ts=epoch(item.get('time'),1000)
        if not isinstance(data,dict):return []
        if kind=='user/message' and isinstance(data.get('source'),dict) and data['source'].get('kind')=='user':
            add(0,text_event(blocks_text(data.get('content')),'user',ts))
        elif kind=='assistant/message' and isinstance(data.get('message'),dict):
            add(0,text_event(blocks_text(data['message'].get('content')),'assistant',ts))
        elif kind=='tool/call':add(0,sent(tool_event(data.get('name'),ts),data.get('name'),data.get('arguments')))
        elif kind=='tool/result' and isinstance(data.get('message'),dict):
            add(0,tool_event('Tool result',ts,result=True,failed=bool(data['message'].get('isError'))))
    elif p=='hermes':
        ts=epoch(item.get('timestamp'));role=item.get('role')
        if role in {'user','assistant'}:add(0,text_event(item.get('content'),role,ts))
        if role=='assistant':
            calls=item.get('tool_calls')
            if isinstance(calls,str):
                try:calls=json.loads(calls)
                except ValueError:calls=[]
            for i,call in enumerate(calls[:MAX_BLOCKS] if isinstance(calls,list) else []):
                if isinstance(call,dict) and isinstance(call.get('function'),dict):
                    add(i+1,sent(tool_event(call['function'].get('name'),ts),call['function'].get('name'),call['function'].get('arguments')))
        elif role=='tool':
            result=parse(item.get('content') or '{}')
            add(0,tool_event(item.get('tool_name') or 'Tool result',ts,result=True,failed=bool(result.get('error') or result.get('is_error') or result.get('success') is False)))
    return out


def artifact_item(item,p,index):
    """Translate known structured calls only, preserving existing artifact policy."""
    name=value=None
    if p=='claude':
        content=item.get('message',{}).get('content')
        if isinstance(content,list) and index<len(content) and isinstance(content[index],dict):
            block=content[index]
            if block.get('type')=='tool_use':name,value=block.get('name'),block.get('input')
    elif p=='dsh':
        data=item.get('data',{})
        if item.get('type')=='tool/call':name,value=data.get('name'),data.get('arguments')
        elif item.get('type')=='tool/result':
            # Only dsh-tool-fs's documented result diff shape, never generic meta.
            return dict(type='recorded_fs_result',diffs=data.get('meta',{}).get('diffs',[]) if isinstance(data.get('meta'),dict) else [])
    elif p=='hermes' and index:
        calls=item.get('tool_calls')
        if isinstance(calls,str):
            try:calls=json.loads(calls)
            except ValueError:return {}
        if isinstance(calls,list) and index<=len(calls) and isinstance(calls[index-1],dict):
            f=calls[index-1].get('function',{})
            if isinstance(f,dict):name,value=f.get('name'),f.get('arguments')
    if not isinstance(name,str):return {}
    return dict(type='response_item',payload=dict(type='function_call',name=name,
                arguments=value if isinstance(value,str) else json.dumps(value)))


class Reader:
    def __init__(self,row,stream):
        self.row,self.stream,self.path=row,stream,row['transcript_path']
        self.provider=provider(row);self.sid=row.get('history_session_id');self.cwd=None;self.db=None;self.frames={};self.data_start=(0,0,0);self.last_fingerprint=None
        st=os.fstat(stream.fileno())
        self.file_id=hashlib.sha256(json.dumps([self.path,st.st_dev,st.st_ino,self.sid,
             row.get('history_receipt_ts'),self.provider]).encode()).hexdigest()[:24]
        self.size=st.st_size
        if self.provider=='codex':return
        if not isinstance(self.sid,str) or not self.sid or len(self.sid)>256:raise HistoryUnavailable('invalid_binding')
        if self.provider=='hermes':self.open_db()
        else:self.check_header()

    def fileno(self):return self.stream.fileno()
    def cursor(self,loc):return self.file_id+':'+':'.join(map(str,loc))
    def location(self,value):
        if value is None:return None
        match=NATIVE_CURSOR.fullmatch(value)
        if not match:raise HistoryUnavailable('invalid_cursor')
        pos,line,block=map(int,match.groups()[1:])
        if block>MAX_BLOCKS or line>MAX_SCAN:raise HistoryUnavailable('invalid_cursor')
        if match[1]!=self.file_id or pos>self.size:raise HistoryUnavailable('history_changed')
        return pos,line,block

    def assert_source_path(self):
        """Current regular pathname and no-follow walk must match the pinned FD."""
        try:
            pinned=os.fstat(self.fileno());current=os.lstat(self.path)
            if (not stat.S_ISREG(current.st_mode) or
                    (pinned.st_dev,pinned.st_ino)!=(current.st_dev,current.st_ino)):
                raise HistoryUnavailable('history_unconfirmed')
            with open_bound_transcript(self.path) as stream:
                walked=os.fstat(stream.fileno())
                if (pinned.st_dev,pinned.st_ino)!=(walked.st_dev,walked.st_ino):
                    raise HistoryUnavailable('history_unconfirmed')
        except (OSError,HistoryUnavailable):
            raise HistoryUnavailable('history_unconfirmed') from None

    def assert_identity(self):
        if self.provider=='hermes':self.assert_source_path()
        else:
            # Avoid the Codex filename/header check for other native providers.
            with open_bound_transcript(self.path) as current:
                a,b=os.fstat(self.fileno()),os.fstat(current.fileno())
                if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino):raise HistoryUnavailable('history_changed')
        if self.provider=='codex':assert_transcript_identity(self.path,self.stream)
        elif self.provider!='hermes':self.check_header()
        elif not self.db.execute('SELECT 1 FROM sessions WHERE id=? AND source=?',(self.sid,'cli')).fetchone():
            raise HistoryUnavailable('history_changed')

    def frame(self,offset,*,data=None,decode=True):
        """Bound physical block walk before bounded streaming decompression.

        Zstd format: 3-byte little-endian block header, last/type/size bits.
        https://github.com/facebook/zstd/blob/dev/doc/zstd_compression_format.md
        A torn final frame stays pending and never advances the cursor.
        """
        if zstd is None:raise HistoryUnavailable('dsh_decoder_unavailable')
        data=os.pread(self.fileno(),MAX_SCAN+1,offset) if data is None else data
        if len(data)<5:return None
        if data[:4]!=MAGIC:raise HistoryUnavailable('history_format_unsupported')
        try:
            header=zstd.frame_header_size(data[:18])
            if len(data)<header:return None
            params=zstd.get_frame_parameters(data[:header])
            if params.window_size>MAX_SCAN:raise HistoryUnavailable('record_too_large')
        except zstd.ZstdError:raise HistoryUnavailable('history_format_unsupported') from None
        end=header
        while True:
            if end+3>len(data):return None
            bits=int.from_bytes(data[end:end+3],'little');end+=3
            last,kind,length=bits&1,(bits>>1)&3,bits>>3
            if kind==3:raise HistoryUnavailable('history_format_unsupported')
            end+=1 if kind==1 else length
            if end>MAX_SCAN:raise HistoryUnavailable('record_too_large')
            if end>len(data):return None
            if last:break
        end+=4 if params.has_checksum else 0
        if end>len(data):return None
        if not decode:return offset+end
        try:
            with zstd.ZstdDecompressor(max_window_size=MAX_SCAN//1024).stream_reader(io.BytesIO(data[:end])) as reader:
                decoded=reader.read(MAX_SCAN+1)
            if len(decoded)>MAX_SCAN:raise HistoryUnavailable('record_too_large')
            return decoded,offset+end
        except zstd.ZstdError:raise HistoryUnavailable('history_format_unsupported') from None

    def check_header(self):
        if self.provider=='dsh' and self.path.endswith('.zstd'):
            frame=self.frame(0)
            if frame is None:raise HistoryUnavailable('history_pending')
            raw=frame[0][:MAX_RECORD].split(b'\n',1)[0];header=parse(raw)
            first_line=frame[0].find(b'\n')+1
            self.data_start=(0,first_line,0) if first_line<len(frame[0]) else (frame[1],0,0)
            if header.get('type')!='session' or header.get('version')!=4:raise HistoryUnavailable('history_format_unsupported')
            if header.get('id')!=self.sid:raise HistoryUnavailable('history_changed')
        else:
            data=os.pread(self.fileno(),min(MAX_SCAN,256*1024),0)
            header=None
            for raw in data.splitlines()[:64]:
                item=parse(raw)
                if self.provider=='dsh':header=item;break
                if item.get('type') in {'user','assistant'}:
                    header=item;break
            if header is None:raise HistoryUnavailable('history_pending')
            if self.provider=='claude':
                if header.get('sessionId')!=self.sid:raise HistoryUnavailable('history_changed')
            else:
                if header.get('type')!='session' or header.get('version')!=4:raise HistoryUnavailable('history_format_unsupported')
                if header.get('id')!=self.sid:raise HistoryUnavailable('history_changed')
                self.data_start=(data.find(b'\n')+1,0,0)
        self.cwd=header.get('cwd')

    def open_db(self):
        # SQLite ro supports committed WAL. immutable=1 would hide WAL records.
        # Pin/check the DB and existing sidecars; never instantiate Hermes/migrate.
        for suffix in ('-wal','-shm'):
            side=self.path+suffix
            if os.path.lexists(side):
                with open_bound_transcript(side):pass
        # A same-UID process already able to read the DB can hide an ABA inside
        # connect. These path checks do not claim to prevent that case.
        self.assert_source_path()
        self.db=sqlite3.connect('file:'+quote(self.path,safe='/')+'?mode=ro',uri=True,timeout=.15,check_same_thread=False)
        try:
            self.assert_source_path()
            self.db.execute('PRAGMA query_only=ON');self.db.execute('PRAGMA trusted_schema=OFF')
            self.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,MAX_SCAN)
            deadline=time.monotonic()+.5;steps=[0]
            def budget():
                steps[0]+=1000
                return int(steps[0]>500_000 or time.monotonic()>deadline)
            self.db.set_progress_handler(budget,1000)
            for table in ('sessions','messages'):
                if self.db.execute('SELECT type FROM sqlite_master WHERE name=?',(table,)).fetchone()!=('table',):
                    raise HistoryUnavailable('history_format_unsupported')
            self.db.execute('BEGIN')
            meta=self.db.execute('SELECT cwd FROM sessions WHERE id=? AND source=?',(self.sid,'cli')).fetchone()
            if not meta:raise HistoryUnavailable('history_unconfirmed')
            self.cwd=meta[0];self.assert_identity()
        except BaseException:
            self.db.close();self.db=None;raise

    def json_records(self,start,end,forward=False):
        data=os.pread(self.fileno(),max(0,end-start),start)
        if forward and len(data)>=MAX_SCAN and b'\n' not in data:
            raise HistoryUnavailable('record_too_large')
        if start and os.pread(self.fileno(),1,start-1)!=b'\n':
            n=data.find(b'\n')
            if n<0:return [],start,start
            start+=n+1;data=data[n+1:]
        records=[];pos=start
        for raw in data.splitlines(keepends=True):
            if not raw.endswith(b'\n'):break
            nxt=pos+len(raw)
            records.append((pos,0,raw,nxt))
            pos=nxt
        return records,start,pos

    def zstd_records(self,start,end,forward):
        frames=[];decoded_bytes=0;first=last=start
        if forward:
            data=os.pread(self.fileno(),end-start,start)
            pos=start
            for _ in range(512):
                if pos>=end:break
                frame=self.frame(pos,data=memoryview(data)[pos-start:])
                if frame is None:
                    if pos==start and end<self.size:raise HistoryUnavailable('record_too_large')
                    break
                raw,nxt=frame
                if nxt>end or decoded_bytes+len(raw)>MAX_SCAN:break
                decoded_bytes+=len(raw);frames.append((pos,raw,nxt));last=nxt;pos=nxt
        else:
            data=os.pread(self.fileno(),end-start,start);candidates=[];at=len(data)
            # Examine at most 8192 recent candidates, never a list proportional
            # to arbitrarily dense magic bytes in a corrupt compressed block.
            for _ in range(8192):
                at=data.rfind(MAGIC,0,at)
                if at<0:break
                candidates.append(start+at)
            chain_end=None;last=None
            for pos in candidates:
                candidate=memoryview(data)[pos-start:]
                try:nxt=self.frame(pos,data=candidate,decode=False)
                except HistoryUnavailable:
                    continue  # Possible magic bytes inside a compressed block.
                if nxt is None:
                    if chain_end is None:chain_end=pos;last=pos
                    continue
                if chain_end is not None and nxt!=chain_end:continue
                if chain_end is None and nxt!=end:
                    # Once a valid frame identifies the next native boundary,
                    # corruption there is an error; a torn last frame is pending.
                    if self.frame(nxt,data=memoryview(data)[nxt-start:],decode=False) is not None:continue
                    chain_end=nxt;last=nxt
                raw,_=self.frame(pos,data=candidate)
                if decoded_bytes+len(raw)>MAX_SCAN or len(frames)>=512:break
                decoded_bytes+=len(raw);frames.append((pos,raw,nxt));chain_end=pos;first=pos
                if last is None:last=nxt
            frames.reverse()
            if last is None:
                if start==0:self.frame(0)  # Explicit corruption/unsupported error.
                return [],start,start
        records=[]
        self.frames={frame:(raw,nxt) for frame,raw,nxt in frames}
        for frame,raw,nxt in frames:
            offset=0
            for line in raw.splitlines(keepends=True):
                if not line.endswith(b'\n'):raise HistoryUnavailable('history_format_unsupported')
                records.append((frame,offset,line,nxt))
                offset+=len(line)
        return records,first,last

    def zstd_backward(self,start,end,bounds):
        """Records of the frame chain ending at `end`, newest first, decoded lazily.

        The same chain walk and budgets as zstd_records(forward=False); a caller
        that stops early leaves older frames undecoded. `bounds` receives the
        oldest decoded frame and the chain end, as zstd_records returns them.
        """
        data=os.pread(self.fileno(),end-start,start);candidates=[];at=len(data)
        bounds.update(first=start,last=start)
        for _ in range(8192):
            at=data.rfind(MAGIC,0,at)
            if at<0:break
            candidates.append(start+at)
        chain_end=None;last=None;decoded_bytes=0;count=0;self.frames={}
        for pos in candidates:
            candidate=memoryview(data)[pos-start:]
            try:nxt=self.frame(pos,data=candidate,decode=False)
            except HistoryUnavailable:
                continue  # Possible magic bytes inside a compressed block.
            if nxt is None:
                if chain_end is None:chain_end=pos;last=pos;bounds['last']=pos
                continue
            if chain_end is not None and nxt!=chain_end:continue
            if chain_end is None and nxt!=end:
                if self.frame(nxt,data=memoryview(data)[nxt-start:],decode=False) is not None:continue
                chain_end=nxt;last=nxt;bounds['last']=nxt
            raw,_=self.frame(pos,data=candidate)
            if decoded_bytes+len(raw)>MAX_SCAN or count>=512:break
            decoded_bytes+=len(raw);count+=1;chain_end=pos;bounds['first']=pos
            if last is None:last=nxt;bounds['last']=nxt
            self.frames[pos]=(raw,nxt)
            lines=[];offset=0
            for line in raw.splitlines(keepends=True):
                if not line.endswith(b'\n'):raise HistoryUnavailable('history_format_unsupported')
                lines.append((pos,offset,line,nxt));offset+=len(line)
            yield from reversed(lines)
        if last is None:
            if start==0:self.frame(0)  # Explicit corruption/unsupported error.
            bounds.update(first=start,last=start)

    def read_page(self,*,before=None,after=None,limit=PAGE_SIZE):
        if before is not None and after is not None:raise HistoryUnavailable('invalid_cursor')
        if not 1<=limit<=200:raise HistoryUnavailable('invalid_limit')
        self.assert_identity()
        if self.provider=='codex':return read_codex_page(self.path,before=before,after=after,limit=limit,stream=self.stream)
        if self.provider=='hermes':return self.snapshot(before,after,limit)
        b,a=self.location(before),self.location(after)
        compressed=self.provider=='dsh' and self.path.endswith('.zstd')
        end=self.size if b is None else min(self.size,b[0]+MAX_SCAN if b[1:]!=(0,0) else b[0])
        if compressed and b is not None and b[1:]!=(0,0):
            # Spend the reverse page's frame/decode budget only on the cursor's
            # frame and its predecessors, never later appended frames.
            frame_end=self.frame(b[0],decode=False)
            if frame_end is None:raise HistoryUnavailable('history_changed')
            end=frame_end
        start=a[0] if a else max(0,end-MAX_SCAN)
        end=min(end,start+MAX_SCAN)
        if not compressed:
            for loc in (a,b):
                if loc and (loc[1] or loc[0] and os.pread(self.fileno(),1,loc[0]-1)!=b'\n'):
                    raise HistoryUnavailable('invalid_cursor')
        entries=[]
        if a is not None:
            records,first,last=self.zstd_records(start,end,True) if compressed else self.json_records(start,end,True)
            for n,(pos,line,raw,nxt) in enumerate(records):
                item=parse(raw);events=normalize(item,self.provider,self.sid)
                for k,(index,event) in enumerate(events):
                    loc=(pos,line,index)
                    if k+1<len(events):next_loc=(pos,line,events[k+1][0])
                    elif compressed and n+1<len(records) and records[n+1][0]==pos:next_loc=(pos,records[n+1][1],0)
                    else:next_loc=(nxt,0,0)
                    if b is not None and loc>=b or loc<a:continue
                    event=dict(event,id=':'.join(map(str,loc)),cursor_before=self.cursor(loc),cursor_after=self.cursor(next_loc))
                    entries.append(event)
        else:
            # Newest first, stopping at the page limit: the same page as the
            # whole window's last `limit` events, without parsing (or for
            # dsh, decompressing) the older records of the window.
            if compressed:
                bounds={};newest=self.zstd_backward(start,end,bounds)
            else:
                records,first,last=self.json_records(start,end,False);newest=reversed(records)
            later=None
            for pos,line,raw,nxt in newest:
                item=parse(raw);events=normalize(item,self.provider,self.sid)
                for k in range(len(events)-1,-1,-1):
                    index,event=events[k];loc=(pos,line,index)
                    if k+1<len(events):next_loc=(pos,line,events[k+1][0])
                    elif compressed and later is not None and later[0]==pos:next_loc=(pos,later[1],0)
                    else:next_loc=(nxt,0,0)
                    if b is not None and loc>=b:continue
                    entries.append(dict(event,id=':'.join(map(str,loc)),cursor_before=self.cursor(loc),cursor_after=self.cursor(next_loc)))
                later=(pos,line)
                if len(entries)>=limit:break
            entries.reverse()
            if compressed:first,last=bounds['first'],bounds['last']
        chosen=entries[:limit] if a is not None else entries[-limit:]
        oldest=chosen[0]['cursor_before'] if chosen else self.cursor((first,0,0))
        newest=(chosen[-1]['cursor_after'] if len(entries)>limit and a is not None else self.cursor((last,0,0)))
        self.assert_identity()
        return dict(events=chosen,before=oldest,after=newest,has_older=self.location(oldest)>self.data_start,
                    has_newer=a is not None and self.location(newest)[0]<self.size and newest!=after,
                    skipped_large_record=False,mode='cursor',notice='Recorded append timeline · not the current model context' if self.provider=='dsh' else '')

    def snapshot_rows(self):
        """The rows a snapshot shows: (rows newest first, limited, boundary id).

        The one scan behind both snapshot() and session_fingerprint(): the same
        SQL, the same MAX_SCAN byte budget and 200-row cap, the same model_only
        exclusion. Rows past the budget are never read, so a session with very
        large rows costs what the snapshot costs.
        """
        self.db.row_factory=sqlite3.Row
        rows=self.db.execute('''SELECT id,role,substr(content,1,65537) AS content,
            substr(tool_calls,1,1048576) AS tool_calls,tool_call_id,tool_name,timestamp,display_metadata
            FROM messages WHERE session_id=? AND active=1 AND role IN ('user','assistant','tool')
            AND COALESCE(display_kind,'')!='hidden' AND COALESCE(_compressed_summary,0)=0
            AND CASE WHEN display_metadata IS NULL THEN 1 WHEN json_valid(display_metadata)
                THEN COALESCE(json_extract(display_metadata,'$.model_only'),0)=0 ELSE 0 END
            ORDER BY id DESC LIMIT 201''',(self.sid,))
        visible=[];budget=0;limited=False;boundary=None
        for row in rows:
            item=dict(row);size=len(json.dumps(item).encode())
            if budget+size>MAX_SCAN or len(visible)>=200:limited=True;boundary=item['id'];break
            budget+=size
            metadata=parse(item.get('display_metadata') or '{}')
            if metadata.get('model_only'):continue
            visible.append(item)
        return visible,limited,boundary

    @staticmethod
    def rows_digest(visible,limited,boundary):
        """Digest of the shown rows and where the window stopped."""
        digest=hashlib.sha256(json.dumps([limited,boundary]).encode())
        for item in visible:
            digest.update(json.dumps(item,sort_keys=True,default=str).encode());digest.update(b'\n')
        return digest.hexdigest()

    def snapshot(self,before,after,limit):
        marker=self.file_id+':snapshot'
        if before is not None or after not in {None,marker}:raise HistoryUnavailable('history_changed')
        visible,limited,boundary=self.snapshot_rows()
        # The same scan's digest: a full read needs no second query for it.
        self.last_fingerprint=self.rows_digest(visible,limited,boundary)
        events=[]
        for item in reversed(visible):
            for index,event in normalize(item,'hermes',self.sid):
                events.append(dict(event,id=f"{item['id']}:0:{index}"))
        self.assert_identity()
        return dict(events=events[-200:],before=None,after=marker,has_older=False,has_newer=False,
                    mode='snapshot',limited=limited or len(events)>200,
                    notice='Hermes · active bound segment snapshot (up to 200 events); earlier/compacted segments are not included')

    def session_fingerprint(self):
        """Hermes: the digest of exactly what a snapshot would show now.

        Another session writing to the shared state.db changes the file but
        not this; any change to a shown row of this session does (a same-length
        edit, a role or tool change, the budget's boundary moving). A row past
        the budget is not shown, so its change does not count. Never published:
        it only lets a held poll tell "nothing new for this session" from
        "read again".
        """
        if self.provider!='hermes':return None
        return self.rows_digest(*self.snapshot_rows())

    def record_at(self,event_id,cache=None):
        """`cache` (one page's decoration only) shares a record among its blocks."""
        try:pos,line,index=map(int,event_id.split(':'))
        except (ValueError,AttributeError):raise HistoryUnavailable('reference_expired') from None
        if cache is not None:
            if (pos,line) not in cache:
                try:cache[(pos,line)]=self.record((pos,line))
                except HistoryUnavailable as exc:cache[(pos,line)]=exc
            found=cache[(pos,line)]
            if isinstance(found,HistoryUnavailable):raise HistoryUnavailable(str(found))
            item,raw,indexes=found
        else:item,raw,indexes=self.record((pos,line))
        if index not in indexes:raise HistoryUnavailable('reference_expired')
        return artifact_item(item,self.provider,index),hashlib.sha256(raw).digest()

    def record(self,location):
        pos,line=location
        if self.provider=='hermes':
            self.db.row_factory=sqlite3.Row
            found=self.db.execute('''SELECT id,role,substr(content,1,65537) AS content,
                substr(tool_calls,1,1048576) AS tool_calls,tool_call_id,tool_name,timestamp,display_metadata
                FROM messages WHERE session_id=? AND id=? AND active=1 AND role IN ('user','assistant','tool')
                AND COALESCE(display_kind,'')!='hidden' AND COALESCE(_compressed_summary,0)=0
                AND CASE WHEN display_metadata IS NULL THEN 1 WHEN json_valid(display_metadata)
                    THEN COALESCE(json_extract(display_metadata,'$.model_only'),0)=0 ELSE 0 END''',(self.sid,pos)).fetchone()
            if not found:raise HistoryUnavailable('reference_expired')
            item=dict(found)
            if parse(item.get('display_metadata') or '{}').get('model_only'):raise HistoryUnavailable('reference_expired')
            raw=json.dumps(item,sort_keys=True).encode()
        elif self.provider=='dsh' and self.path.endswith('.zstd'):
            frame=self.frames.get(pos) or self.frame(pos)
            if frame is None:raise HistoryUnavailable('reference_expired')
            decoded=frame[0]
            if line and decoded[line-1:line]!=b'\n':raise HistoryUnavailable('reference_expired')
            raw=decoded[line:].split(b'\n',1)[0];item=parse(raw)
        else:
            if line or pos and os.pread(self.fileno(),1,pos-1)!=b'\n':raise HistoryUnavailable('reference_expired')
            raw=os.pread(self.fileno(),MAX_RECORD+1,pos).split(b'\n',1)[0];item=parse(raw)
        if len(raw)>MAX_RECORD:raise HistoryUnavailable('reference_expired')
        return item,raw,frozenset(dict(normalize(item,self.provider,self.sid)))

    def close(self):
        if self.db is not None:self.db.close()


class InodeMismatch(HistoryUnavailable):
    """The opened file is not the (dev, inode) the caller confirmed; nothing was read."""


@contextmanager
def open_reader(row,expect_inode=None):
    """`expect_inode`: compare the bare descriptor before the Reader reads a byte."""
    if row.get('history_binding')!='bound':
        raise HistoryUnavailable('history_stale' if row.get('history_binding')=='stale' else 'history_unconfirmed')
    p=provider(row);path=row.get('transcript_path')
    if p is None:raise HistoryUnavailable('provider_unavailable')
    if not isinstance(path,str) or (p in {'codex','claude'} and not path.endswith('.jsonl')
        or p=='dsh' and not path.endswith(('.jsonl','.jsonl.zstd'))
        or p=='hermes' and not path.endswith('/state.db')):raise HistoryUnavailable('invalid_binding')
    reader=None
    try:
        with open_bound_transcript(path) as stream:
            if expect_inode is not None:
                info=os.fstat(stream.fileno())
                if (info.st_dev,info.st_ino)!=tuple(expect_inode):raise InodeMismatch('history_changed')
            reader=Reader(row,stream);yield reader
    except sqlite3.Error:raise HistoryUnavailable('history_unreadable') from None
    finally:
        if reader:reader.close()
