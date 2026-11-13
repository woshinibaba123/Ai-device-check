"""Local, scoped navigation memory. Never contains UI dumps, credentials or pass results."""
import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager, closing
from pathlib import Path
import ai_fastpath
import navigation_intents
import host_runtime

VERSION = 'navigation-v1'
SAFE_NAVIGATION = re.compile(r'首页|门店|我的|消息|通用设置|语言|任务|状态|排班列表|清洁记录|地图|设备|清洁模式|任务报告设置|新建任务|清洁区域|新建区域|列表选择|请选择【字段：(任务类型|清洁循环|清洁时间|清洁区域|清洁模式)】|Home|Store|Mine|Equipment|Map|Schedule|Common setting|Language|Cleaning Records|Cleaning Mode', re.I)


def safe_navigation(label):
    return isinstance(label, str) and bool(SAFE_NAVIGATION.fullmatch(label))



def region_selection_confirmed(steps):
    executed=[s for s in steps if s.get('result')=='executed']
    start=next((i for i in range(len(executed)-1,-1,-1) if executed[i].get('label')=='新建区域'),None)
    if start is None:return False
    labels=[s.get('label','') for s in executed[start+1:]]
    if '保存' in labels:return False
    opened=next((i for i,label in enumerate(labels) if label=='列表选择'),None)
    return opened is not None and any(label in ('确认','确定','Confirm') for label in labels[opened+1:])


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def page_key(page):
    # IDs, bounds, account names/body text and input values are deliberately excluded.
    controls = sorted((re.sub(r'，位置-?\d+,-?\d+$','',c.get('text', '')), bool(c.get('editable')), bool(c.get('selected')), bool(c.get('checked')), bool(c.get('blocked'))) for c in page['controls'])
    return digest([VERSION, page.get('route', ''), controls])


def context_key(steps):
    return digest([(s.get('action'), s.get('label', '')) for s in steps[-4:] if s.get('result') == 'executed'])


def goal_key(goal, checks=()):
    plan = ai_fastpath.compile_goal(goal)
    meaning = {k: plan[k] for k in ('labels', 'kind', 'query', 'store_code') if k in plan} if plan else (navigation_intents.canonical_text(goal))
    if isinstance(meaning,str):meaning=re.sub(r'[\s，,。；;“”「」]', '', meaning)
    if plan and plan.get('kind') == 'store_lookup':
        # A navigation prefix must never make different downstream business
        # goals share a learned completion.
        meaning['goal'] = navigation_intents.canonical_text(goal)
    return digest([VERSION, meaning, list(checks)])


def legacy_goal_key(goal,checks=()):
    plan=ai_fastpath._compile_legacy(goal)
    meaning={k:plan[k] for k in ('labels','kind') if k in plan} if plan else re.sub(r'[\s，,。；;“”「」]','',goal)
    return digest([VERSION,meaning,list(checks)])


def application_scope(config, package, artifact=''):
    # Navigation memory follows the application across iterative releases.
    # Lookup still requires matching goal, context, page and a unique control;
    # the executor checks the resulting page before trusting the transition.
    if not package:
        return ''
    return digest([VERSION, 'application-navigation', package, config.get('platform','')])


def summary(path=None):
    path=Path(path) if path else host_runtime.root()/'.runtime/action-knowledge/navigation.sqlite3'
    if not path.is_file():return {'enabled':0,'recorded':0}
    try:
        with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=2)) as db:
            return {'enabled':db.execute('SELECT COUNT(*) FROM transitions WHERE enabled=1').fetchone()[0],'recorded':db.execute('SELECT COUNT(*) FROM events').fetchone()[0]}
    except sqlite3.Error:return {'enabled':0,'recorded':0,'unavailable':True}


class Knowledge:
    def __init__(self, scope, goal, checks=(), path=None):
        self.scope = scope
        self.goal = goal_key(goal, checks)
        self.goals=list(dict.fromkeys([self.goal]+[legacy_goal_key(v,checks) for v in navigation_intents.variants(goal,96)]))
        self.run_id = uuid.uuid4().hex
        self.path = Path(path) if path else host_runtime.root()/'.runtime/action-knowledge/navigation.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS transitions (key TEXT PRIMARY KEY, scope TEXT, goal TEXT, context TEXT, before TEXT, action TEXT, label TEXT, after TEXT, enabled INTEGER, run TEXT, successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, updated REAL)')
            for key,label in db.execute('SELECT key,label FROM transitions WHERE scope=? AND enabled=0 AND failures=0 AND action=? AND before!=after', (self.scope,'tap')).fetchall():
                if safe_navigation(label):
                    db.execute('UPDATE transitions SET enabled=1 WHERE key=?',(key,))
            db.execute('CREATE TABLE IF NOT EXISTS completions (key TEXT PRIMARY KEY, quotes TEXT, updated REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run TEXT, key TEXT, action TEXT, label TEXT, before TEXT, after TEXT, origin TEXT, updated REAL)')

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            with db:yield db

    def key(self, page, steps):
        return digest([VERSION, self.scope, self.goal, context_key(steps), page_key(page)])

    def keys(self,page,steps):
        context=context_key(steps);before=page_key(page)
        return [digest([VERSION,self.scope,goal,context,before]) for goal in self.goals]

    def lookup(self, page, steps):
        self.last_lookup_reason = 'exact_hit'
        keys=self.keys(page,steps)
        with self.connect() as db:
            rows=db.execute('SELECT key,action,label,after FROM transitions WHERE key IN ('+','.join('?' for _ in keys)+') AND enabled=1',keys).fetchall()
            if not rows:
                # Reuse only unambiguous navigation on the identical semantic page.
                # Goal and application isolation remain mandatory; mutations and
                # completion claims never participate in this history fallback.
                candidates=db.execute('SELECT key,action,label,after FROM transitions WHERE scope=? AND goal IN ('+','.join('?' for _ in self.goals)+') AND before=? AND enabled=1', [self.scope]+self.goals+[page_key(page)]).fetchall()
                rows=[r for r in candidates if r[1]=='tap' and safe_navigation(r[2])]
                recent=[s for s in steps if s.get('result')=='executed'][-1:]
                if recent and any(recent[0].get('label')==r[2] for r in rows):
                    self.last_lookup_reason='repeat_target_rejected'
                    return None
                self.last_lookup_reason='stable_navigation_hit' if rows else 'no_verified_page_match'
                if not rows:
                    count=db.execute('SELECT COUNT(*) FROM transitions WHERE scope=? AND goal IN ('+','.join('?' for _ in self.goals)+')', [self.scope]+self.goals).fetchone()[0]
                    if not count:
                        self.last_lookup_reason='no_records_for_goal'
                    else:
                        matches=db.execute('SELECT enabled FROM transitions WHERE scope=? AND goal IN ('+','.join('?' for _ in self.goals)+') AND before=?',[self.scope]+self.goals+[page_key(page)]).fetchall()
                        if not matches:self.last_lookup_reason='page_not_matched'
                        elif not any(r[0] for r in matches):self.last_lookup_reason='step_not_enabled'
                        else:self.last_lookup_reason='history_not_matched'
                    return None
        if len({tuple(row[1:]) for row in rows})!=1:
            self.last_lookup_reason='conflicting_transitions'
            return None
        key,action,label,after=rows[0]
        executed=[s for s in steps if s.get('result')=='executed']
        if label=='列表选择' and region_selection_confirmed(steps):
            self.last_lookup_reason='workflow_stage_completed'
            return None
        if sum(s.get('action')==action and s.get('label')==label for s in executed[-6:])>=2:
            self.last_lookup_reason='navigation_cycle_rejected'
            return None
        if action == 'tap':
            found = [c for c in page['controls'] if c['text'] == label and not c.get('blocked') and not c.get('editable')]
            if len(found) != 1:
                self.last_lookup_reason='target_missing_blocked_or_ambiguous'
                return None
            decision = {'action': 'tap', 'target': found[0]['id']}
        elif action == 'back':
            decision = {'action': 'back'}
        else:
            self.last_lookup_reason='unsupported_action'
            return None
        return dict(decision, origin='knowledge', knowledge_key=key, expected_page=after)

    def observe(self, before, decision, after, steps, label=''):
        # Only changed-page navigation. An assertion or successful click alone is not learning.
        action = decision.get('action')
        if action not in ('tap', 'back') or page_key(before) == page_key(after):
            return False
        if action == 'tap' and (not label or len(label) > 200 or '[已隐藏]' in label or '[hidden]' in label):
            return False
        # Immediately reusable navigation must exclude business mutations.
        is_safe_navigation=(action=='tap' and safe_navigation(label) and
                            len([c for c in before['controls'] if c.get('text')==label and not c.get('editable') and not c.get('blocked')])==1 and
                            bool(after.get('controls')))
        key = self.key(before, steps)
        now = time.time()
        with self.connect() as db:
            db.execute('INSERT INTO events(run,key,action,label,before,after,origin,updated) VALUES (?,?,?,?,?,?,?,?)', (self.run_id, key, action, label, page_key(before), page_key(after), decision.get('origin', 'ai'), now))
            existing = db.execute('SELECT action,label,after,enabled FROM transitions WHERE key=?', (key,)).fetchone()
            candidate = (action, label, page_key(after))
            if existing and tuple(existing[:3]) == candidate:
                db.execute('UPDATE transitions SET run=?,updated=? WHERE key=?', (self.run_id, now, key))
            elif existing and existing[3]:
                # Conflicting outcomes invalidate the old rule rather than silently replacing it.
                db.execute('UPDATE transitions SET enabled=0,failures=failures+1,run=NULL,updated=? WHERE key=?', (now, key))
            else:
                db.execute('INSERT OR REPLACE INTO transitions(key,scope,goal,context,before,action,label,after,enabled,run,updated) VALUES (?,?,?,?,?,?,?,?,0,?,?)', (key, self.scope, self.goal, context_key(steps), page_key(before), action, label, page_key(after), self.run_id, now))
            if is_safe_navigation and not (existing and existing[3] and tuple(existing[:3])!=candidate):
                db.execute('UPDATE transitions SET enabled=1,successes=successes+1 WHERE key=?',(key,))
        return True

    def invalidate(self, key):
        with self.connect() as db:
            row=db.execute('SELECT context,before FROM transitions WHERE key=? AND scope=?',(key,self.scope)).fetchone()
            if row:db.execute('UPDATE transitions SET enabled=0,failures=failures+1,run=NULL,updated=? WHERE scope=? AND goal IN ('+','.join('?' for _ in self.goals)+') AND context=? AND before=?',[time.time(),self.scope]+self.goals+list(row))

    def promote(self, page, steps, quotes):
        if not isinstance(quotes, list) or not quotes or any(not isinstance(q, str) or not 1 <= len(q) <= 300 or q not in page['text'] or '[已隐藏]' in q or '[hidden]' in q for q in quotes):
            return False
        with self.connect() as db:
            db.execute('UPDATE transitions SET enabled=1,successes=successes+1 WHERE run=?', (self.run_id,))
            db.execute('INSERT OR REPLACE INTO completions(key,quotes,updated) VALUES (?,?,?)', (self.key(page, steps), json.dumps(quotes, ensure_ascii=False), time.time()))
        return True

    def completion(self, page, steps):
        with self.connect() as db:
            keys=self.keys(page,steps)
            rows=db.execute('SELECT quotes FROM completions WHERE key IN ('+','.join('?' for _ in keys)+')',keys).fetchall()
        if not rows or len({r[0] for r in rows})!=1:
            return None
        try:
            quotes = json.loads(rows[0][0])
            if isinstance(quotes, list) and quotes and all(isinstance(q, str) and q in page['text'] for q in quotes):
                return quotes
        except ValueError:
            pass
        return None

    def counts(self):
        with self.connect() as db:
            return {'enabled': db.execute('SELECT COUNT(*) FROM transitions WHERE enabled=1').fetchone()[0], 'recorded': db.execute('SELECT COUNT(*) FROM events').fetchone()[0]}
