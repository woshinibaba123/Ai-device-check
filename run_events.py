"""Bounded-shape local command events: never store arguments, responses or credentials."""
import json,time

class Recorder:
    def __init__(self,folder,job):
        self.path=folder/'events.jsonl';self.job=job;self.started=time.monotonic();self.sequence=0
        job['command_timings']={};job['events']='/reports/'+job['id']+'/events.jsonl' if job.get('id') else ''
    def emit(self,kind,**fields):
        self.sequence+=1
        event={'seq':self.sequence,'elapsed_ms':round((time.monotonic()-self.started)*1000,1),'kind':kind}
        event.update(fields)
        with self.path.open('a') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
    def call(self,operation,callback):
        start=time.monotonic();ok=False
        try:
            value=callback();ok=True;return value
        finally:
            elapsed=round((time.monotonic()-start)*1000,1)
            entry=self.job['command_timings'].setdefault(operation,{'count':0,'failures':0,'total_ms':0,'max_ms':0})
            entry['count']+=1;entry['failures']+=not ok;entry['total_ms']=round(entry['total_ms']+elapsed,1);entry['max_ms']=max(entry['max_ms'],elapsed)
            self.emit('command',operation=operation,duration_ms=elapsed,status='ok' if ok else 'error')
            try:
                import execution_memory
                identity=self.job.get('app_identity') or {}
                scope=execution_memory.scope(identity.get('bundle',''),self.job.get('platform',''),'execution')
                execution_memory.record(scope,operation,ok,elapsed)
                self.job.setdefault('execution_memory',{'recorded':0,'failures':0})['recorded']+=1
            except Exception:
                self.job.setdefault('execution_memory',{'recorded':0,'failures':0})['failures']+=1



def operation(method,path):
    if path.endswith('/source'):return 'observe'
    if path.endswith('/value') or path.endswith('/clear'):return 'input'
    if path.endswith('/element') or path.endswith('/elements'):return 'resolve'
    if path.endswith('/click') or path.endswith('/actions'):return 'action'
    if path.endswith('/screenshot'):return 'capture'
    return 'driver'
