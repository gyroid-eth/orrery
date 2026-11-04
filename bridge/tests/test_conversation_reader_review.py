"""Review regressions, generated records only. No live state or CLI processes."""
import json
import os
import random
import sqlite3
import string
import sys
from pathlib import Path

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import conversation_history as history
import conversation_readers as readers
from test_conversation_providers import line,row,page,claude,dsh,make_db


def test_dsh_multiline_frames_before_cursor_strictly_moves_back(tmp_path):
    z=pytest.importorskip('zstandard');path=tmp_path/'session.v4.jsonl.zstd';pack=z.ZstdCompressor().compress
    def message(n):return line(dsh('user/message',dict(source=dict(kind='user'),content=[dict(type='text',text=str(n))]),n))
    path.write_bytes(pack(line(dict(type='session',version=4,id='fixture-session')))+
        b''.join(pack(b''.join(message(n*3+j) for j in range(3))) for n in range(600)))
    r=row(path,'dsh');cursor=None;seen=[]
    for _ in range(30):
        result=page(r,before=cursor)
        assert result['events'],f'empty page after {len(seen)} of 1800 events'
        if cursor:
            old=tuple(map(int,cursor.split(':')[1:]));new=tuple(map(int,result['before'].split(':')[1:]))
            assert new<old,'an earlier page must never advance into future frames'
        seen=[e['text'] for e in result['events']]+seen;cursor=result['before']
        if not result['has_older']:break
    assert seen==list(map(str,range(1800)))


@pytest.mark.parametrize('program',['claude-code','dsh'])
def test_large_jsonl_incremental_record_is_explicit_error_then_latest_recovers(tmp_path,program):
    path=tmp_path/'history.jsonl'
    if program=='claude-code':
        header=b'';record=lambda text:claude('user',text)
    else:
        header=line(dict(type='session',version=4,id='fixture-session'))
        record=lambda text:dsh('user/message',dict(source=dict(kind='user'),content=[dict(type='text',text=text)]))
    path.write_bytes(header+line(record('first')));r=row(path,program);cursor=page(r)['after']
    huge=record('x'*(readers.MAX_SCAN+1024))
    with path.open('ab') as f:f.write(line(huge)+line(record('after oversized record')))
    with pytest.raises(history.HistoryUnavailable,match='record_too_large'):page(r,after=cursor)
    assert page(r)['events'][-1]['text']=='after oversized record'


def test_dsh_completed_first_frame_over_64k_is_not_pending(tmp_path):
    z=pytest.importorskip('zstandard');path=tmp_path/'session.v4.jsonl.zstd';rng=random.Random(7)
    header=line(dict(type='session',version=4,id='fixture-session'))
    event=dsh('user/message',dict(source=dict(kind='user'),content=[dict(type='text',text='visible')]))
    event['unused']=''.join(rng.choices(string.ascii_letters+string.digits,k=100000))
    raw=z.ZstdCompressor().compress(header+line(event));assert 65536<len(raw)<readers.MAX_SCAN
    path.write_bytes(raw);r=row(path,'dsh')
    assert [e['text'] for e in page(r)['events']]==['visible']
    assert page(r)['has_older'] is False
    # Same large frame genuinely torn, unlike the completed frame above.
    path.write_bytes(raw[:-1])
    with pytest.raises(history.HistoryUnavailable,match='history_pending'):page(r)


def make_pair(tmp_path):
    good=tmp_path/'state.db';foreign=tmp_path/'foreign.db'
    for path,text in [(good,'BOUND_FIXTURE'),(foreign,'FOREIGN_FIXTURE')]:
        con=make_db(path);con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user',?,1)",(text,));con.commit();con.close()
    return good,foreign


@pytest.mark.parametrize('replacement',['symlink','regular'])
def test_hermes_replacement_immediately_before_connect_is_rejected_before_query(tmp_path,monkeypatch,replacement):
    good,foreign=make_pair(tmp_path);saved=tmp_path/'saved.db';original=readers.sqlite3.connect;queries=[]
    def raced_connect(*a,**kw):
        good.rename(saved)
        if replacement=='symlink':good.symlink_to(foreign)
        else:foreign.rename(good)
        con=original(*a,**kw);con.set_trace_callback(queries.append);return con
    monkeypatch.setattr(readers.sqlite3,'connect',raced_connect)
    with pytest.raises(history.HistoryUnavailable,match='history_unconfirmed'):page(row(good,'hermes'))
    assert queries==[],'reject after connect before any SQL reads the replaced database'


def test_hermes_recheck_runs_before_connect_even_if_constructor_metadata_check_passed(tmp_path,monkeypatch):
    good,foreign=make_pair(tmp_path);saved=tmp_path/'saved.db';original=readers.Reader.open_db;calls=[]
    def changed(self):
        good.rename(saved);good.symlink_to(foreign);return original(self)
    monkeypatch.setattr(readers.Reader,'open_db',changed)
    monkeypatch.setattr(readers.sqlite3,'connect',lambda *a,**kw:calls.append(a) or pytest.fail('must reject before SQLite open'))
    with pytest.raises(history.HistoryUnavailable,match='history_unconfirmed'):page(row(good,'hermes'))
    assert calls==[]


def test_hermes_replacement_after_query_discards_snapshot(tmp_path,monkeypatch):
    good,foreign=make_pair(tmp_path);saved=tmp_path/'saved.db';original=readers.normalize;done=[False]
    def after_read(item,provider,sid):
        result=original(item,provider,sid)
        if provider=='hermes' and not done[0]:
            done[0]=True;good.rename(saved);good.symlink_to(foreign)
        return result
    monkeypatch.setattr(readers,'normalize',after_read)
    with pytest.raises(history.HistoryUnavailable,match='history_unconfirmed'):page(row(good,'hermes'))


def test_same_uid_sqlite_open_aba_remains_explicitly_accepted_limit(tmp_path,monkeypatch):
    """ProOpus Mail33679: the brief fully-restored ABA is out of threat scope.

    This is a characterization, not proof of prevention. It reproduces Wintry's
    probe so a report cannot claim lightweight pathname checks prevent the ABA.
    """
    good,foreign=make_pair(tmp_path);saved=tmp_path/'saved.db';original=readers.sqlite3.connect
    def raced_connect(*a,**kw):
        good.rename(saved);good.symlink_to(foreign)
        try:return original(*a,**kw)
        finally:good.unlink();saved.rename(good)
    monkeypatch.setattr(readers.sqlite3,'connect',raced_connect)
    assert [e['text'] for e in page(row(good,'hermes'))['events']]==['FOREIGN_FIXTURE']
