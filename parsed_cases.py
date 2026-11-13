"""Durable, editable parsed Excel suites, independent of workbook and temporary caches."""
import copy
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime
from collections import deque
from pathlib import Path

LOCK=threading.RLock()
SETTINGS=('source','h5_source','execution_mode','adapter_id','entrypoint','model','region','target_language','call_acceptance','excel_observation_mode')
FIELDS=('title','priority','precondition','steps','expected','test_data')


def now():return datetime.now().astimezone().isoformat(timespec='seconds')


class Conflict(ValueError):pass


class Store:
    def __init__(self,directory):self.directory=Path(directory)
    def path(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):raise ValueError('已解析用例编号无效')
        return self.directory/(identifier+'.json')
    def write(self,path,value):
        self.directory.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2));temporary.replace(path)
    def get(self,identifier):
        path=self.path(identifier)
        with LOCK:
            if not path.is_file():raise ValueError('已解析用例不存在或已删除')
            return json.loads(path.read_text())
    def check(self,suite,revision):
        if type(revision) is not int or revision!=suite['revision']:raise Conflict('用例已在其他窗口修改，请刷新后继续；本次未覆盖已保存内容')
    def commit(self,suite):
        suite['revision']+=1;suite['updated_at']=now();self.write(self.path(suite['id']),suite)
        return suite
    def record(self,suite,action,message,**details):
        """Audit metadata only; never store passwords, input values or model output."""
        self.path(suite['id'])
        entry={'id':uuid.uuid4().hex,'time':now(),'action':action,'message':message,
               'suite_id':suite['id'],'excel_name':suite.get('source_filename') or suite['name'],
               'revision':suite['revision'],**{k:v for k,v in details.items() if k in ('case_id','fields','count','stage','batch_id')}}
        with LOCK:
            folder=self.directory/'logs';folder.mkdir(parents=True,exist_ok=True)
            with (folder/(suite['id']+'.jsonl')).open('a',encoding='utf-8') as out:
                out.write(json.dumps(entry,ensure_ascii=False)+'\n')
        return entry
    def logs(self,identifier,limit=200):
        self.path(identifier)
        path=self.directory/'logs'/(identifier+'.jsonl')
        with LOCK:
            if not path.is_file():return []
            with path.open(encoding='utf-8') as stream:lines=deque(stream,maxlen=limit)
            rows=[]
            for line in lines:
                try:rows.append(json.loads(line))
                except ValueError:continue
            return rows
    def listing(self):
        with LOCK:
            rows=[]
            for path in self.directory.glob('*.json'):
                if not re.fullmatch(r'[a-f0-9]{32}',path.stem):continue
                try:suite=json.loads(path.read_text())
                except (OSError,ValueError):continue
                cases=suite.get('cases',[])
                rows.append({k:suite.get(k) for k in ('id','name','revision','created_at','updated_at','source_path','source_filename','source_plan_id')}|
                    {'total':len(cases),'ready':sum(bool(c.get('plan')) and not c.get('needs_reanalysis') for c in cases)})
            return sorted(rows,key=lambda r:r['updated_at'],reverse=True)
    def save_generation(self,result,book,settings):
        identifier=uuid.uuid5(uuid.NAMESPACE_URL,'devicecheck-parsed:'+result['excel_plan_id']).hex
        with LOCK:
            tombstones=self.directory/'deleted.json'
            deleted=json.loads(tombstones.read_text()) if tombstones.is_file() else []
            if identifier in deleted:return None
            path=self.path(identifier)
            existing=self.get(identifier) if path.is_file() else None
            original={c['id']:c for c in book.get('cases',[])}
            old={c['id']:c for c in existing['cases']} if existing else {}
            rows=[]
            import excel_plan_cache
            for entry in result['cases']:
                if existing and entry['id'] in existing.get('deleted_cases',[]):continue
                if old.get(entry['id'],{}).get('user_edited'):
                    rows.append(old[entry['id']]);continue
                source=original.get(entry['id'],{})
                business=entry.get('business_steps',[])
                raw={k:source.get(k,'') for k in FIELDS}
                raw['title']=entry.get('title') or raw['title'] or entry['id']
                raw['steps']=raw['steps'] or '\n'.join(s.get('action','') for s in business)
                raw['expected']=raw['expected'] or '\n'.join(s.get('expected','') for s in business)
                raw['priority']=raw['priority'] if raw['priority'] in ('P0','P1','P2','P3') else 'P1'
                row={**raw,'id':entry['id'],'source_sheet':entry.get('sheet',''),'source_row':entry.get('row'),
                     'business_steps':business,'plan':entry.get('plan') or entry.get('partial_plan'),
                     'partial_reason':entry.get('blocked_reason','') if not entry.get('plan') else '',
                     'needs_reanalysis':result.get('binding_schema')!=excel_plan_cache.VERSION,
                     'user_edited':False}
                rows.append(row)
            source_path=book.get('path') or result.get('source_path') or ''
            filename=Path(source_path).name if source_path.lower().endswith('.xlsx') else ''
            suite=existing or {'id':identifier,'name':filename or Path(source_path or '历史Excel解析').stem,'created_at':now(),
                'revision':0,'deleted_cases':[],'source_plan_id':result['excel_plan_id'],'source_path':book.get('path',''),
                'settings':{k:settings[k] for k in SETTINGS if k in settings}}
            if filename:
                if not existing or suite.get('name_origin')!='custom' and (suite['name'].startswith('历史Excel解析') or suite['name']==Path(suite.get('source_path','')).stem):suite['name']=filename
                suite.update(source_path=source_path,source_filename=filename)
                suite.setdefault('name_origin','excel')
            fingerprint=result.get('fingerprint')
            if not fingerprint and isinstance(book.get('content'),bytes):fingerprint=hashlib.sha256(book['content']).hexdigest()
            if fingerprint:suite['source_fingerprint']=fingerprint
            suite['cases']=rows
            self.commit(suite)
            self.record(suite,'parsed_saved','已保存解析结果，共 '+str(len(rows))+' 条',count=len(rows))
            return suite
    def rename(self,identifier,revision,name):
        if not isinstance(name,str) or not 1<=len(name.strip())<=200:raise ValueError('用例组名称需为1～200字')
        with LOCK:
            suite=self.get(identifier);self.check(suite,revision);suite['name']=name.strip();suite['name_origin']='custom'
            self.commit(suite);self.record(suite,'renamed','已修改用例组名称');return suite
    def update_case(self,identifier,revision,case_id,changes):
        if not isinstance(changes,dict) or not changes or set(changes)-set(FIELDS)-{'plan'}:raise ValueError('用例修改字段无效')
        with LOCK:
            suite=self.get(identifier);self.check(suite,revision)
            row=next((c for c in suite['cases'] if c['id']==case_id),None)
            if row is None:raise ValueError('用例不存在或已删除')
            for key,value in changes.items():
                if key=='plan':continue
                if not isinstance(value,str) or len(value)>30000:raise ValueError('用例文本无效或过长')
                if key in ('title','steps','expected') and not value.strip():raise ValueError('标题、业务步骤和预期不能为空')
                if key=='priority' and value not in ('P0','P1','P2','P3'):raise ValueError('用例等级无效')
                row[key]=value
            if any(k in changes for k in ('steps','expected','precondition','test_data')):
                import excel_ai
                row['business_steps']=excel_ai.business_case(row)['business_steps']
                row.update(plan=None,partial_reason='业务描述已修改，需重新 AI 分析或编辑运行步骤',needs_reanalysis=True)
            if 'plan' in changes:
                import codebuddy_bridge
                plan=changes['plan']
                row['plan']=codebuddy_bridge.checked_plan(plan) if plan is not None else None
                row['needs_reanalysis']=plan is None;row['partial_reason']='' if plan is not None else '尚未绑定运行步骤'
            row['user_edited']=True
            self.commit(suite)
            self.record(suite,'case_updated','已自动保存用例修改',case_id=case_id,fields=sorted(changes))
            return suite
    def delete(self,identifier,revision,case_id=None):
        with LOCK:
            suite=self.get(identifier);self.check(suite,revision)
            if case_id is not None:
                if not any(c['id']==case_id for c in suite['cases']):raise ValueError('用例不存在或已删除')
                suite['cases']=[c for c in suite['cases'] if c['id']!=case_id]
                suite.setdefault('deleted_cases',[]).append(case_id)
                self.commit(suite);self.record(suite,'case_deleted','已删除用例',case_id=case_id);return suite
            path=self.directory/'deleted.json'
            deleted=json.loads(path.read_text()) if path.is_file() else []
            if identifier not in deleted:deleted.append(identifier)
            self.write(path,deleted);self.record(suite,'suite_deleted','已删除用例组');self.path(identifier).unlink()
            return {'deleted':True,'id':identifier}
    def recover_sources(self,paths):
        """Recover old names only with an exact workbook fingerprint match."""
        candidates={}
        for value in paths:
            path=Path(value).expanduser()
            if path.is_file() and path.suffix.lower()=='.xlsx':
                candidates[hashlib.sha256(path.read_bytes()).hexdigest()]=path
        recovered=[]
        with LOCK:
            for item in self.listing():
                suite=self.get(item['id']);fingerprint=suite.get('source_fingerprint')
                if not fingerprint:
                    cache=self.directory.parent/'excel-ai-plans'
                    for path in (cache/(suite['source_plan_id']+'.json'),cache/'in-progress'/(suite['source_plan_id']+'.json')):
                        if path.is_file():
                            try:fingerprint=json.loads(path.read_text()).get('fingerprint')
                            except (OSError,ValueError):continue
                            if fingerprint:break
                path=candidates.get(fingerprint)
                if path is None:continue
                if suite.get('source_filename')==path.name and suite.get('source_path')==str(path):continue
                if suite.get('name_origin')!='custom' and (suite['name'].startswith('历史Excel解析') or suite['name']==Path(suite.get('source_path','')).stem):suite['name']=path.name
                suite.update(source_filename=path.name,source_path=str(path),source_fingerprint=fingerprint)
                suite.setdefault('name_origin','excel')
                self.commit(suite);self.record(suite,'source_recovered','已通过 Excel 文件指纹恢复来源名称')
                recovered.append(suite['id'])
        return recovered
    def book(self,identifier,revision=None,case_ids=None):
        suite=self.get(identifier)
        if revision is not None:self.check(suite,revision)
        if case_ids is not None and (not isinstance(case_ids,list) or not case_ids or set(case_ids)-{c['id'] for c in suite['cases']}):raise ValueError('请选择库中存在的用例')
        cases=[]
        for n,row in enumerate(suite['cases'],1):
            if case_ids is not None and row['id'] not in case_ids:continue
            plan=row.get('plan') if not row.get('needs_reanalysis') else None
            cases.append({**{k:row.get(k,'') for k in FIELDS},'id':row['id'],'sheet':'已解析用例','row':n,'module':'已解析用例',
                'group':'手机 App','mobile':True,'scope_reason':'从已解析用例库加载','plan_text':json.dumps(plan,ensure_ascii=False) if plan else '',
                'ai_pending':'' if plan else row.get('partial_reason') or '需要重新 AI 分析或绑定运行步骤',
                'ai_incomplete':row.get('partial_reason','') if plan else ''})
        return {'path':'已解析用例：'+suite['name'],'content':json.dumps(suite,ensure_ascii=False).encode(),
                'cases':cases,'sheets':[],'ai':True,'parsed_suite_id':identifier,'parsed_suite_revision':suite['revision']}
    def import_existing(self,cache):
        """Import persisted results once; deleted suites are never resurrected."""
        cache=Path(cache);ledger=self.directory/'imported.json'
        with LOCK:
            imported=set(json.loads(ledger.read_text())) if ledger.is_file() else set()
            files=list(cache.glob('*.json'));latest={}
            for p in sorted((cache/'in-progress').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                try:data=json.loads(p.read_text());key=data.get('fingerprint')
                except (OSError,ValueError):continue
                if key not in latest:latest[key]=p
            files+=list(latest.values())
            for path in sorted(files,key=lambda p:p.stat().st_mtime):
                key=path.stem
                if key in imported or not re.fullmatch(r'[a-f0-9]{32}',key):continue
                try:
                    data=json.loads(path.read_text())
                    if not data.get('cases'):continue
                    data.setdefault('excel_plan_id',key)
                    suite=self.save_generation(data,{'path':data.get('source_path') or '历史Excel解析-'+key[:8]},data)
                    if suite is not None:
                        suite['updated_at']=datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec='seconds')
                        self.write(self.path(suite['id']),suite)
                    imported.add(key)
                except (OSError,ValueError,KeyError,TypeError):continue
            self.write(ledger,sorted(imported))


def _reanalyze(cfg,progress):
    """Analyze stored business text; commit only if its revision is unchanged."""
    import codebuddy_bridge as bridge
    import excel_ai
    import excel_execution_policy
    import host_runtime
    store=Store(Path(cfg.get('_parsed_store') or host_runtime.root()/'.runtime/parsed-case-library'))
    suite=store.get(cfg['parsed_library_id']);store.check(suite,cfg['parsed_revision'])
    wanted=cfg.get('parsed_case_ids')
    selected=[c for c in suite['cases'] if wanted is None or c['id'] in wanted]
    if not selected or wanted is not None and set(wanted)-{c['id'] for c in selected}:raise ValueError('请选择需要重新分析的用例')
    settings={**suite.get('settings',{}),**{k:cfg[k] for k in SETTINGS if k in cfg}}
    settings.setdefault('excel_observation_mode',True)
    entries={}
    for offset in range(0,len(selected),5):
        batch=selected[offset:offset+5]
        document=bridge.business_document({'cases':[excel_ai.business_case(c) for c in batch]})
        progress('library_binding','正在重新分析 '+str(offset+1)+'～'+str(offset+len(batch))+' / '+str(len(selected))+' 条')
        result=bridge.generate({**settings,'binding_only':True,'auto_bind':True,'strict_excel':True,
            'include_source':bool(settings.get('source') or settings.get('h5_source')),'document':document,
            'outline':excel_execution_policy.RULES if settings['excel_observation_mode'] else '按保存的业务步骤和预期匹配运行步骤'},progress)
        if len(result['cases'])!=len(batch):raise ValueError('重新分析返回的用例数量不一致，未覆盖保存内容')
        for old,new in zip(batch,result['cases']):entries[old['id']]=new
    with LOCK:
        current=store.get(suite['id']);store.check(current,suite['revision'])
        for row in current['cases']:
            if row['id'] not in entries:continue
            new=entries[row['id']];row.update(business_steps=new['business_steps'],plan=new.get('plan'),
                partial_reason=new.get('blocked_reason',''),needs_reanalysis=not bool(new.get('plan')),user_edited=True)
        current['settings']=settings
        saved=store.commit(current)
    return {'cases':list(entries.values()),'library_id':saved['id'],'library_revision':saved['revision']}


def reanalyze(cfg,progress):
    import host_runtime
    import excel_ai
    store=Store(Path(cfg.get('_parsed_store') or host_runtime.root()/'.runtime/parsed-case-library'))
    suite=store.get(cfg['parsed_library_id']);store.check(suite,cfg['parsed_revision'])
    count=len(cfg.get('parsed_case_ids') or suite['cases'])
    store.record(suite,'analysis_started','开始重新 AI 分析，共 '+str(count)+' 条',count=count)
    def report(stage,label):
        progress(stage,label)
        if not stage.endswith(('stream','call_stats','call_done')):
            store.record(suite,'analysis_progress',excel_ai.safe_text(str(label))[:500],stage=stage)
    try:
        result=_reanalyze(cfg,report)
        saved=store.get(suite['id'])
        store.record(saved,'analysis_completed','重新 AI 分析完成，结果已保存',count=len(result['cases']))
        return result
    except Exception as error:
        message=str(error) if isinstance(error,ValueError) else '分析执行异常，结果未覆盖原用例'
        store.record(suite,'analysis_failed','重新 AI 分析未完成：'+excel_ai.safe_text(message)[:300])
        raise
