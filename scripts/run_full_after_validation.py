#!/usr/bin/env python3
"""Continue this explicitly requested run after a verified device smoke check.
Only stores task/report metadata. Login password and provider key stay in Keychain.
"""
import argparse,json,os,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import case_workbook,case_runner

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--validation',required=True);parser.add_argument('--config',required=True);parser.add_argument('--output',required=True);parser.add_argument('--full')
    args=parser.parse_args();folder=Path(args.output).resolve();folder.mkdir(parents=True,exist_ok=True)
    if ROOT not in folder.parents:raise ValueError('输出必须位于工作区')
    state={};opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def api(path,body=None):
        request=urllib.request.Request('http://127.0.0.1:8765'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with opener.open(request,timeout=60) as response:return json.load(response)
    def record(**values):
        state.update(values);state['updated']=time.strftime('%Y-%m-%d %H:%M:%S');temporary=folder/'progress.tmp';temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2));temporary.replace(folder/'progress.json')
    def wait_task(identifier,stage):
        errors=0
        while True:
            try:task=api('/api/language-pipelines/'+identifier);errors=0
            except Exception:
                errors+=1;record(stage=stage,connection_errors=errors)
                if errors>=20:raise RuntimeError('本地服务持续不可用，未宣称测试完成')
                time.sleep(15);continue
            record(stage=stage,pipeline=identifier,status=task['status'],groups=[{k:g.get(k) for k in ('sheet','state','ready','complete_ready','partial_ready','batch','results','reason')} for g in task['groups']])
            if task['status'] not in ('running','stopping'):return task
            time.sleep(15)
    record(stage='validation_wait',validation=args.validation)
    validation=wait_task(args.validation,'validation_wait');proof=False
    for group in validation['groups']:
        if not group.get('batch'):continue
        for job in api('/api/batches/'+group['batch'])['jobs']:
            if job.get('login',{}).get('status')!='confirmed' or job.get('language',{}).get('confirmation')!='persisted_locale':continue
            for case in job.get('case_results',[]):
                steps=case.get('steps',[])
                if case['id']=='01_中文简体:6' and len(steps)>=8 and all(s.get('status')=='pass' for s in steps):proof=True
    if not proof:
        record(stage='needs_repair',reason='定向设备步骤尚未验证通过，未自动启动全量；需要继续修复环境或定位')
        print('NEEDS_REPAIR',flush=True);return 2
    config=json.loads(Path(args.config).read_text());config.pop('prepared_plans',None);config['excel'].pop('case_ids',None)
    config['excel'].update(sheet='',priority='',allow_partial=True,call_acceptance='backend_only');config['build_cache_from']=args.validation
    book=case_workbook.read(config['excel']['path']);expected={c['id'] for c in case_runner.selected_cases(book,config['excel'])}
    task={'id':args.full} if args.full else api('/api/language-pipelines',config);record(stage='full_started',pipeline=task['id'],expected=len(expected),validation_verified=True)
    print('FULL_STARTED '+task['id'],flush=True)
    (folder/'full-task.json').write_text(json.dumps(task))
    result=wait_task(task['id'],'full_running')
    if not result.get('json_report'):raise RuntimeError('任务结束但缺少汇总报告，不能宣称完成')
    report_path=(ROOT/result['json_report'].lstrip('/')).resolve()
    if ROOT/'reports' not in report_path.parents:raise RuntimeError('报告路径无效')
    report=json.loads(report_path.read_text());actual=[r['id'] for r in report['results']]
    if len(actual)!=len(expected) or set(actual)!=expected:raise RuntimeError('汇总报告未覆盖每个筛选用例，不能宣称全量完成')
    for key,name in [('json_report','完整测试报告.json'),('workbook','完整测试报告.xlsx'),('report','完整测试报告.html')]:
        source=(ROOT/result[key].lstrip('/')).resolve()
        if ROOT/'reports' not in source.parents:raise RuntimeError('输出路径无效')
        shutil.copyfile(source,folder/name)
    record(stage='full_processed',status=result['status'],selected=report['selected'],passed=report['passed'],status_counts=report['status_counts'],report=result['report'],workbook=result['workbook'],note='全量筛选用例均已列入报告；受阻、未执行及部分执行不代表通过；机器人移动未验证')
    print('FULL_PROCESSED '+json.dumps(state,ensure_ascii=False),flush=True)
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as error:
        # Do not include request/config data or provider output in logs.
        print('WATCH_FAILED '+type(error).__name__+': '+str(error)[:300],flush=True);sys.exit(1)
