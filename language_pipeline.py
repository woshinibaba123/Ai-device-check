import host_runtime
"""Generate workbook language groups while a single consumer runs ready groups."""
import copy
import json
import re
import threading
import time
import uuid
import shutil
from pathlib import Path
import case_runner
import case_workbook
import codebuddy_bridge
import excel_ai
import language_tests

ROOT = host_runtime.root()
TASKS={}
LOCK=threading.RLock()


def active():
    with LOCK:return any(t['status'] in ('running','stopping') for t in TASKS.values())


def owns(identifier):
    with LOCK:return identifier in TASKS and TASKS[identifier]['status'] in ('running','stopping')


def snapshot(identifier):
    with LOCK:
        if identifier not in TASKS:raise ValueError('语言接力任务不存在')
        return copy.deepcopy(TASKS[identifier])


def restore_history():
    for path in sorted((ROOT/'.runtime/language-pipelines').glob('*.json'),key=lambda p:p.stat().st_mtime):
        try:
            value=json.loads(path.read_text())
            if not re.fullmatch(r'[a-f0-9]{32}',value.get('id','')) or not isinstance(value.get('groups'),list):continue
            if value.get('status') in ('running','stopping'):
                value.update(status='stopped',label='服务重启，接力已中断；已保存计划和报告保留')
                for group in value['groups']:
                    if group.get('state') in ('pending','generating','ready','queued','running'):group['state']='stopped'
            with LOCK:TASKS[value['id']]=value
        except (OSError,ValueError,TypeError):continue


def update(identifier,**values):
    with LOCK:
        TASKS[identifier].update(values)
        value=copy.deepcopy(TASKS[identifier])
    folder=ROOT/'.runtime/language-pipelines';folder.mkdir(parents=True,exist_ok=True)
    # Status and plan identifiers only. Credentials/configuration never enter this file.
    (folder/(identifier+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))


def group_selection(book,options,languages):
    configured=language_tests.validate(languages)
    if not configured:raise ValueError('请先启用多语言测试，并配置各语言的切换路径及选项文字')
    selected=case_runner.selected_cases(book,options)
    sheets=list(dict.fromkeys(c['sheet'] for c in selected));groups=[]
    for sheet in sheets:
        label=re.sub(r'^\s*\d+[\s_.、-]*','',sheet).strip().casefold()
        matches=[l for l in configured if label in (l['name'].casefold(),l['code'].casefold(),l['code'].split('-')[0].casefold())]
        if len(matches)!=1:raise ValueError('工作表“'+sheet+'”无法唯一对应已配置语言；请用语言名称命名工作表并勾选对应语言')
        groups.append({'sheet':sheet,'language':copy.deepcopy(matches[0]),'selected':sum(c['sheet']==sheet for c in selected),'state':'pending','ready':0})
    return groups


def start(cfg,api):
    """api.post/get use this server's normal validated endpoints, never a second executor."""
    options=cfg.get('excel',{})
    book,_=excel_ai.read_selected(options)
    execution=copy.deepcopy(cfg.get('execution',{}))
    if not execution.get('targets'):raise ValueError('请先选择测试机型或设备')
    if not any(execution.get(k,'').strip() for k in ('source','app','bundle')):raise ValueError('请填写源码、安装包或 App 包名')
    if execution.get('source','').strip()!=cfg.get('source','').strip() or execution.get('h5_source','').strip()!=cfg.get('h5_source','').strip():raise ValueError('生成与测试必须使用相同源码目录')
    if options.get('plans'):raise ValueError('语言接力生成前请清空手动步骤配置')
    groups=group_selection(book,options,execution.get('languages',{}))
    if codebuddy_bridge.status()['busy']:raise ValueError('已有 AI 任务，请等待本轮完成后再启动语言接力')
    identifier=uuid.uuid4().hex
    with LOCK:
        if active():raise ValueError('已有语言接力任务正在运行')
        TASKS[identifier]={'id':identifier,'status':'running','label':'准备按语言生成并测试','groups':groups,'call_acceptance':options.get('call_acceptance','full'),'stop_requested':False,'started':time.strftime('%Y-%m-%d %H:%M:%S')}
    stop=threading.Event();condition=threading.Condition();ready=[];done=threading.Event()
    # Runtime-only controls, deliberately kept outside public/persisted status.
    CONTROLS[identifier]=(stop,condition)
    update(identifier)
    previous=cfg.get('build_cache_from')
    if previous and re.fullmatch(r'[a-f0-9]{32}',previous):
        source=ROOT/'.runtime/pipeline-builds'/previous;target=ROOT/'.runtime/pipeline-builds'/identifier
        if all((source/name).is_file() and not (source/name).is_symlink() for name in ('metadata.json','app-debug.apk')):
            try:
                target.mkdir(parents=True,exist_ok=True)
                for name in ('metadata.json','app-debug.apk'):shutil.copyfile(source/name,target/name)
            except OSError:shutil.rmtree(target,ignore_errors=True)
    cache=codebuddy_bridge.ExcelSourceContext()

    def save_report():
        if book.get('content'):
            try:export_report(identifier,book,options,api)
            except Exception as error:update(identifier,report_error='汇总报告生成失败：'+safe_error(error))

    def change(number,**values):
        with LOCK:TASKS[identifier]['groups'][number].update(values)
        update(identifier)

    def producer():
        try:
            for n,group in enumerate(groups):
                if stop.is_set():break
                change(n,state='generating')
                def progress(stage,label):
                    if stop.is_set():raise PipelineStopped()
                    change(n,progress=label)
                options_for_group=dict(options,sheet=group['sheet'],ai_plan_id='')
                options_for_group.setdefault('allow_partial',True)
                settings={k:v for k,v in cfg.items() if k not in ('execution','excel')}
                locale='zht' if group['language']['code']=='zh-TW' else group['language']['system_language']
                settings.update(excel=options_for_group,_excel_source_context=cache,target_language=locale)
                try:
                    prepared=cfg.get('prepared_plans',{}).get(group['sheet'])
                    if prepared:
                        checked=dict(options_for_group,ai_plan_id=prepared,source=cfg.get('source','').strip(),h5_source=cfg.get('h5_source','').strip())
                        excel_ai.apply(book,checked)
                        result=json.loads((excel_ai.CACHE/(prepared+'.json')).read_text())
                        progress('prepared','复用本轮已保存且与源码、筛选条件一致的计划，直接进入设备验证')
                    else:result=excel_ai.generate(settings,progress)
                    change(n,state='ready' if result['ready'] else 'blocked',ready=result['ready'],complete_ready=result.get('complete_ready',result['ready']),partial_ready=result.get('partial_ready',0),plan_id=result['excel_plan_id'],reason='' if result['ready'] else '该语言没有可执行步骤，未启动设备测试')
                    if result['ready'] and not stop.is_set():
                        with condition:
                            ready.append((n,result,options_for_group));condition.notify_all()
                except PipelineStopped:break
                except Exception as error:
                    change(n,state='failed',reason=safe_error(error))
        finally:
            done.set()
            with condition:condition.notify_all()

    def consumer():
        try:
            while True:
                with condition:
                    condition.wait_for(lambda:ready or done.is_set() or stop.is_set(),timeout=1)
                    if stop.is_set():break
                    if not ready:
                        if done.is_set():break
                        continue
                    n,result,selection=ready.pop(0)
                group=groups[n];change(n,state='queued')
                body=copy.deepcopy(execution)
                body.update(test_mode='cases',cases=dict(selection,ai_plan_id=result['excel_plan_id'],source=cfg.get('source','').strip(),h5_source=cfg.get('h5_source','').strip()),languages={'enabled':True,'selected':[group['language']]},pipeline_id=identifier)
                batch=None
                while not stop.is_set():
                    try:
                        batch=api.post('/api/batch',body);break
                    except QueueBusy:
                        stop.wait(1)
                    except Exception as error:
                        change(n,state='failed',reason=safe_error(error));break
                if not batch:continue
                change(n,state='running',batch=batch['id'])
                while True:
                    report=api.get('/api/batches/'+batch['id'])
                    jobs=report['jobs']
                    if stop.is_set():
                        for job in jobs:
                            if job['status'] in ('running','queued'):api.post('/api/stop',{'id':job['id']});break
                    if all(j['status'] not in ('running','queued') for j in jobs):
                        change(n,state='stopped' if stop.is_set() else 'completed',results=report.get('counts',{}));break
                    stop.wait(1) if not stop.is_set() else time.sleep(1)
            # A running AI request may take time to return; wait before releasing reservation.
            done.wait()
            with LOCK:
                for group in groups:
                    if group['state'] in ('pending','generating','ready','queued'):group['state']='stopped'
                failed=any(g['state'] in ('failed','blocked') or any(g.get('results',{}).get(k,0) for k in ('failed','blocked','review')) for g in groups)
            save_report()
            update(identifier,status='stopped' if stop.is_set() else ('review' if failed else 'done'),label='已停止语言接力' if stop.is_set() else '所有语言已处理；请查看逐语言结果',finished=time.strftime('%Y-%m-%d %H:%M:%S'))
        except Exception as error:
            stop.set();done.wait()
            save_report()
            update(identifier,status='failed',label=safe_error(error))
        finally:
            CONTROLS.pop(identifier,None)
            execution.clear()
            cfg.clear()

    threading.Thread(target=producer,daemon=True).start()
    threading.Thread(target=consumer,daemon=True).start()
    return {'id':identifier,'groups':len(groups)}


class PipelineStopped(BaseException):pass
class QueueBusy(Exception):pass
CONTROLS={}


def stop(identifier):
    if not owns(identifier):raise ValueError('语言接力任务不存在或已结束')
    event,condition=CONTROLS[identifier];event.set()
    update(identifier,status='stopping',stop_requested=True,label='正在停止生成与测试，保留已有计划和报告')
    with condition:condition.notify_all()
    return {'ok':True}


def safe_error(error):
    # Never publish provider bodies/configuration (may contain login data).
    return str(error)[:600] if isinstance(error,ValueError) else '处理失败，请检查服务和语言配置；已有计划及报告保留'


def export_report(identifier,book,options,api):
    """Account for every selected row, including groups that never reached a device."""
    import collections,html
    task=snapshot(identifier);by_id={};reasons={};targets={}
    for group in task['groups']:
        if group.get('plan_id'):
            path=excel_ai.CACHE/(group['plan_id']+'.json')
            if path.is_file():
                for row in json.loads(path.read_text())['cases']:
                    if not row.get('plan'):reasons[row['id']]=row.get('blocked_reason') or '未生成完整可执行步骤'
        if group.get('batch'):
            try:
                jobs=api.get('/api/batches/'+group['batch'])['jobs'];targets[group['sheet']]=[j['id'] for j in jobs]
                for job in jobs:
                    for row in job.get('case_results',[]):by_id.setdefault(row['id'],[]).append(dict(row,job_id=job['id']))
            except Exception:pass
    groups={g['sheet']:g for g in task['groups']};results=[]
    for case in case_runner.selected_cases(book,options):
        records=by_id.get(case['id'],[])
        present={r['job_id'] for r in records}
        for job_id in targets.get(case['sheet'],[]):
            if job_id not in present:records.append({'id':case['id'],'sheet':case['sheet'],'row':case['row'],'title':case['title'],'result':'fail','status':'未执行','reason':'此设备目标未返回该用例的完整执行结果','screenshots':[],'steps':[],'job_id':job_id})
        if records:
            failed=[r for r in records if r.get('result')!='pass'];row=copy.deepcopy((failed or records)[0])
            row['target_results']=records
            row['screenshots']=list(dict.fromkeys(p for r in records for p in r.get('screenshots',[])))
        else:
            group=groups[case['sheet']]
            row={'id':case['id'],'sheet':case['sheet'],'row':case['row'],'title':case['title'],'result':'fail','status':'待转换' if case['id'] in reasons else '未执行','reason':reasons.get(case['id']) or group.get('reason') or '本语言未完成设备执行，不能记为通过','screenshots':[],'steps':[]}
        results.append(row)
    folder=ROOT/'reports'/('language-pipeline-'+identifier);folder.mkdir(parents=True,exist_ok=True)
    counts=dict(collections.Counter(r['status'] for r in results))
    summary={'pipeline_id':identifier,'selected':len(results),'passed':sum(r['result']=='pass' for r in results),'status_counts':counts,'groups':task['groups'],'source_workbook':book['path'],'fingerprint':excel_ai.fingerprint(book),'results':results,'note':'所有筛选用例均列入报告。未执行、待转换、权限和数据受阻不代表产品缺陷；未通过项目不会计入通过。多设备用例仅在全部已记录目标通过时汇总为通过。'}
    if task.get('call_acceptance')=='backend_only':summary['note']+=' 呼叫按用户确认仅验收本次后台任务下发接口成功，未验证机器人实际移动。'
    (folder/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    case_workbook.annotate(book,results,folder/'测试结果.xlsx')
    esc=lambda v:html.escape(str(v))
    table=''.join('<tr><td>'+esc(r['id'])+'</td><td>'+esc(r['title'])+'</td><td>'+esc(r['status'])+'</td><td>'+esc(r['reason'])+'</td><td>'+''.join('<a href="'+esc(url)+'">截图</a> ' for url in r.get('screenshots',[]))+'</td></tr>' for r in results)
    (folder/'summary.html').write_text('<!doctype html><meta charset="utf-8"><title>语言接力测试报告</title><style>body{font:14px sans-serif;padding:28px;color:#23334a}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dce2ec;padding:8px;text-align:left;vertical-align:top}td:nth-child(4){color:#9b382b}a{color:#4057d9}</style><h1>语言接力测试报告</h1><p>筛选 '+str(len(results))+' 条；通过 '+str(summary['passed'])+' 条。</p><p>'+esc(summary['note'])+'</p><p>状态统计：'+esc(counts)+'</p><p><a href="测试结果.xlsx">下载汇总 Excel</a> · <a href="report.json">下载完整 JSON</a></p><table><tr><th>编号</th><th>用例</th><th>状态</th><th>原因</th><th>证据</th></tr>'+table+'</table>')
    prefix='/reports/'+folder.name+'/'
    update(identifier,report=prefix+'summary.html',workbook=prefix+'测试结果.xlsx',json_report=prefix+'report.json',case_counts={'selected':len(results),'passed':summary['passed'],'status_counts':counts})
