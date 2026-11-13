"""Shared local execution statistics and exact-scene navigation memory."""
import hashlib
import json
import sqlite3
import time
from contextlib import closing
import host_runtime


def connect():
    path=host_runtime.root()/'.runtime/action-knowledge/execution.sqlite3'
    path.parent.mkdir(parents=True,exist_ok=True)
    return sqlite3.connect(path,timeout=3)


def record(scope,operation,ok,duration):
    with closing(connect()) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS operations(scope TEXT,operation TEXT,count INTEGER,failures INTEGER,total_ms REAL,PRIMARY KEY(scope,operation))')
        db.execute('INSERT INTO operations VALUES(?,?,1,?,?) ON CONFLICT(scope,operation) DO UPDATE SET count=count+1,failures=failures+excluded.failures,total_ms=total_ms+excluded.total_ms',(scope,operation,int(not ok),duration))


def navigation(scope,key,value=None):
    with closing(connect()) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS navigation(scope TEXT,key TEXT,value TEXT,updated REAL,PRIMARY KEY(scope,key))')
        if value is not None:
            db.execute('INSERT OR REPLACE INTO navigation VALUES(?,?,?,?)',(scope,key,json.dumps(value,ensure_ascii=False),time.time()))
            db.execute('DELETE FROM navigation WHERE rowid NOT IN (SELECT rowid FROM navigation ORDER BY updated DESC LIMIT 512)')
            return
        row=db.execute('SELECT value FROM navigation WHERE scope=? AND key=?',(scope,key)).fetchone()
        return json.loads(row[0]) if row else None


def scope(package,platform,goal):
    return hashlib.sha256(json.dumps([v if isinstance(v,str) else "" for v in (package,platform,goal)],ensure_ascii=False).encode()).hexdigest()
