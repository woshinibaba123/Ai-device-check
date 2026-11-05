import host_runtime
"""Excel-to-AI planning with immutable workbook identity and row mapping."""
import hashlib
import json
import re
import uuid
import copy
from pathlib import Path
import automation
import case_workbook
import case_runner

ROOT = host_runtime.root()
CACHE=ROOT/'.runtime/excel-ai-plans'
BATCH_SIZE=10


def batches(cases):
    # Bound output complexity as well as case count to avoid truncated replies.
    chunk=[];steps=0;chars=0
    for case in cases:
        count=len(str(case.get('steps','')).splitlines()) or 1
        size=sum(len(str(case.get(k,''))) for k in ('title','steps','expected','precondition','test_data'))
        if chunk and (len(chunk)>=BATCH_SIZE or steps+count>80 or chars+size>18000):
            yield chunk
            chunk=[];steps=0;chars=0
        chunk.append(case);steps+=count;chars+=size
    if chunk:yield chunk


def fingerprint(book):return hashlib.sha256(book['content']).hexdigest()


def read_selected(options):
    if not isinstance(options,dict):raise ValueError('Excel 选择配置无效')
    book=case_workbook.read(options.get('path',''))
    if options.get('fingerprint')!=fingerprint(book):raise ValueError('Excel 已变化或尚未读取，请重新读取并筛选用例')
    selected=case_runner.selected_cases(book,options)
    if not selected:raise ValueError('当前筛选没有手机用例')
    return book,selected


def safe_text(value):
    text=str(value or '')
    samples={'13800000000':'__QA_SAMPLE_PHONE__','+12025550123':'__QA_SAMPLE_OVERSEAS_PHONE__','qa@example.com':'__QA_SAMPLE_EMAIL__'}
    for sample,marker in samples.items():text=re.sub(r'(?<![\w@.+-])'+re.escape(sample)+r'(?![\w@.+-])',marker,text)
    # Literal login credentials embedded in the workbook stay local.
    text=re.sub(r'((?:密码|password|passwd|token|密钥|secret|账号|account)\s*[:：=]\s*)[^\s，,；;]+',r'\1[本机数据]',text,flags=re.I)
    text=automation.redact(text,[])
    for sample,marker in samples.items():text=text.replace(marker,sample)
    return text


def reusable_key(case):
    values={k:case.get(k,'') for k in ('title','module','group','steps','expected','precondition','test_data')}
    values['precondition']=re.sub(r'^当前为[^（\n]{1,80}（[A-Za-z-]+）[；;]','当前为本轮语言；',values['precondition'])
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def localize_candidate(entry,cache,locale):
    """Reuse only native, source-translatable operations for identical business cases."""
    packs=(cache.flutter or {}).get('locale_packs',{})
    if locale not in packs:return None
    mapping={}
    for key,target in packs[locale].items():
        if not isinstance(target,str):continue
        for pack in packs.values():
            value=pack.get(key)
            if isinstance(value,str):mapping.setdefault(value,set()).add(target)
    row=copy.deepcopy(entry)
    def translate(operations):
        for step in operations:
            action=step['action']
            if action not in ('tap','input','save','assert','assert_absent','assert_selected','assert_route','assert_input','back','wait','screenshot'):return False
            if action in ('assert_route','back','wait','screenshot'):continue
            by=step.get('by','label')
            if by=='id':continue
            if by!='label' or len(mapping.get(step['value'],set()))!=1:return False
            step['value']=next(iter(mapping[step['value']]))
        return True
    if not translate(row['plan'].get('requires',[])+row['plan']['steps']):return None
    for business in row.get('business_steps',[]):
        if not translate(business.get('automation_steps',[])):return None
    return row


def partial_candidate(row):
    """A contiguous prefix only: never jump across an unbound business step."""
    import codebuddy_bridge as bridge
    steps=[];state=bridge.infer_start_state(row)
    for business in row.get('business_steps',[]):
        operations=business.get('automation_steps',[])
        if business.get('automation_status') not in ('candidate','partial') or not operations:break
        actual_state=business.get('automation_start_state','home')
        if actual_state!='home':
            if steps and state!=actual_state:break
            state=actual_state
        if any('[本机数据]' in str(s.get('text','')) or '[已隐藏]' in str(s.get('text','')) for s in operations):break
        steps.extend(copy.deepcopy(operations))
        if business.get('automation_status')=='partial':break
    if not steps:return None
    return bridge.checked_plan({'requires':[],'steps':steps,'start_state':state},require_assertion=False)


def business_case(case,call_acceptance='full'):
    if not case.get('steps','').strip() or not case.get('expected','').strip():raise ValueError('原用例缺少操作步骤或预期结果')
    actions=[s.strip() for s in re.split(r'\n|【\d+】',safe_text(case['steps'])) if s.strip()]
    if not 1<=len(actions)<=30 or any(len(s)>1500 for s in actions) or len(safe_text(case['expected']))>1500:raise ValueError('用例内容过长，请在 Excel 中拆分步骤后重新生成')
    expected=safe_text(case['expected']).strip()
    if call_acceptance=='backend_only' and re.search(r'呼叫|多点任务',case['title']) and re.search(r'下发',case['steps']):
        actions=[('监听本次页面点击触发的呼叫任务下发接口，核对场景及目标点位参数已携带、HTTP成功与业务成功码；不验证机器人实际移动，不发送额外取消或结束任务请求。' if re.search(r'机器人(?:实际)?(?:接收|执行|移动)|隔离场地结束任务',action) and re.search(r'检查|校验|核对|验证',action) else action) for action in actions]
        expected=re.sub(r'机器人(?:实际)?接收[/、与及]?执行[^；。]*','后台任务下发接口成功即可满足呼叫下发验收，不验证机器人实际移动',expected)
        expected+='\n本轮按用户确认仅验收后台任务下发；不验证机器人移动。'
    precondition=(safe_text(case.get('precondition',''))+('\n测试数据：'+safe_text(case['test_data']) if case.get('test_data') else '')).strip()
    if len(precondition)>6000:raise ValueError('前置条件和测试数据过长，请拆分用例')
    return {'title':safe_text(case['title']).strip(),'precondition':precondition,
            'expected':expected,'priority':case['priority'] if case['priority'] in ('P0','P1','P2','P3') else 'P1',
            'business_steps':[{'action':a,'expected':expected if n==len(actions)-1 else '完成本步操作；最终验收以原用例整体预期为准'} for n,a in enumerate(actions)]}


def generate(cfg,progress):
    import codebuddy_bridge as bridge
    options=cfg['excel'];book,selected=read_selected(options)
    entries={};base=dict(cfg);base.pop('excel',None)
    base['call_acceptance']=options.get('call_acceptance','full')
    cache=base.get('_excel_source_context')
    base['_excel_source_context']=cache if isinstance(cache,bridge.ExcelSourceContext) else bridge.ExcelSourceContext()
    cache=base['_excel_source_context']
    chunks=list(batches(selected));total_batches=len(chunks);offset=0
    progress('excel_read','已读取 Excel，共 '+str(len(selected))+' 条用例，将分 '+str(total_batches)+' 批生成运行步骤（每批最多 '+str(BATCH_SIZE)+' 条，复杂用例自动缩小批次）')
    # Small requests avoid truncating a whole workbook into a single model response.
    for batch_number,chunk in enumerate(chunks,1):
        start=offset;offset+=len(chunk)
        batch_label='第 '+str(batch_number)+'/'+str(total_batches)+' 批'
        progress('excel_batch',batch_label+'：开始生成用例 '+str(start+1)+'～'+str(offset)+' / '+str(len(selected)))
        pairs=[]
        for case in chunk:
            try:
                business=business_case(case,base['call_acceptance'])
                stored=cache.native_plans.get(reusable_key(case))
                reused=localize_candidate(stored,cache,base.get('target_language')) if stored else None
                if reused:
                    reused.update(id=case['id'],sheet=case['sheet'],row=case['row'],title=safe_text(case['title']),reused_candidate=True,reused_from=stored['id'])
                    reused['plan']=bridge.checked_plan(reused['plan']);entries[case['id']]=reused
                    progress('excel_reuse',batch_label+'：按源码语言文案复用相同业务步骤，仍需在当前语言实际执行验证')
                else:pairs.append((case,business))
            except ValueError as error:entries[case['id']]={'id':case['id'],'plan':None,'blocked_reason':str(error)}
        if not pairs:continue
        document=bridge.business_document({'cases':[row for _,row in pairs]})
        settings=dict(base,outline='严格按导入的 Excel 原始步骤与整体预期匹配具体运行指令。不得减少、合并用例，不得弱化预期或猜测测试数据。中间步骤仅作操作说明，必须覆盖最后一步所列全部原始预期。出现[本机数据]或[已隐藏]的输入数据时标记缺少本机运行数据，禁止把脱敏占位文字作为输入值。',binding_only=True,document=document,auto_bind=True,strict_excel=True)
        settings['outline']+='\n当前批次源码检索依据（仅为用例数据）：\n'+safe_text('\n'.join(c['title']+'\n'+c['steps'] for c,_ in pairs))[:12000]
        platforms={c.get('module','').split(' / ')[0] for c,_ in pairs}
        if base.get('source','').strip() and platforms=={'App'} and not any('H5' in c['steps']+' '+c['expected'] for c,_ in pairs):settings['_excel_native_only']=True
        if platforms=={'H5'}:settings['_excel_h5_only']=True
        def report(stage,label):progress('excel_'+stage,batch_label+' · 用例 '+str(start+1)+'～'+str(offset)+' / '+str(len(selected))+'：'+label)
        try:
            response=bridge.generate(settings,report)
            rows=response['cases']
            if len(rows)!=len(pairs):raise ValueError('AI 返回用例数量与 Excel 不一致')
            for (case,original),row in zip(pairs,rows):
                if any(row.get(k,'')!=original.get(k,'') for k in ('title','precondition','expected')):raise ValueError('AI 改写了原用例，已拒绝该批计划')
                if [s['action'] for s in row.get('business_steps',[])]!=[s['action'] for s in original['business_steps']]:raise ValueError('AI 改写了原步骤，已拒绝该批计划')
            for (case,_),row in zip(pairs,rows):
                plan=row['plan'];reason=row.get('blocked_reason','')
                if plan and any('[本机数据]' in str(s.get('text','')) or '[已隐藏]' in str(s.get('text','')) for s in plan.get('steps',[])):
                    plan=None;reason='缺少本机运行测试数据；不能输入脱敏占位文字'
                if plan:plan=bridge.checked_plan(plan)
                entries[case['id']]={'id':case['id'],'title':safe_text(case['title']),'sheet':case['sheet'],'row':case['row'],'plan':plan,'blocked_reason':reason or ('' if plan else '尚未生成完整运行步骤'),'business_steps':row.get('business_steps',[])}
                if not plan and options.get('allow_partial'):
                    try:entries[case['id']]['partial_plan']=partial_candidate(row)
                    except ValueError:entries[case['id']]['partial_plan']=None
                if plan:cache.native_plans[reusable_key(case)]=copy.deepcopy(entries[case['id']])
        except Exception as error:
            reason=str(error) if isinstance(error,ValueError) else 'AI 生成请求失败，请检查连接或缩小筛选范围后重试'
            for case,_ in pairs:entries[case['id']]={'id':case['id'],'plan':None,'blocked_reason':safe_text(reason)[:600]}
    # Recheck before publishing: an edited workbook must never reuse stale row IDs.
    if fingerprint(case_workbook.read(book['path']))!=fingerprint(book):raise ValueError('生成期间 Excel 已被修改，请重新读取并生成')
    rows=[entries[c['id']] for c in selected];identifier=uuid.uuid4().hex
    complete=sum(bool(r['plan']) for r in rows);partial=sum(bool(r.get('partial_plan')) for r in rows)
    result={'excel_plan_id':identifier,'fingerprint':fingerprint(book),'sheet':options.get('sheet',''),'priority':options.get('priority',''),'call_acceptance':options.get('call_acceptance','full'),'allow_partial':bool(options.get('allow_partial')),'source':cfg.get('source','').strip(),'h5_source':cfg.get('h5_source','').strip(),'cases':rows,'ready':complete+partial,'complete_ready':complete,'partial_ready':partial,'selected':len(rows)}
    CACHE.mkdir(parents=True,exist_ok=True)
    (CACHE/(identifier+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    progress('excel_ready','Excel 步骤已生成：完整 '+str(complete)+' 条，连续部分步骤 '+str(partial)+' 条，共 '+str(len(rows))+' 条；部分执行不会判为通过')
    return result


def apply(book,options):
    identifier=options.get('ai_plan_id')
    if not identifier:return book
    if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):raise ValueError('Excel AI 计划标识无效')
    path=CACHE/(identifier+'.json')
    if not path.is_file():raise ValueError('Excel AI 计划不存在，请重新生成')
    if options.get('plans'):raise ValueError('请先清空手动步骤配置，再使用 Excel AI 计划')
    result=json.loads(path.read_text())
    if result['fingerprint']!=fingerprint(book):raise ValueError('Excel 已变化，AI 计划已失效，请重新生成')
    if result.get('call_acceptance','full')!=options.get('call_acceptance','full'):raise ValueError('呼叫验收口径已变化，请重新生成计划')
    if result.get('allow_partial',False)!=bool(options.get('allow_partial')):raise ValueError('部分步骤执行设置已变化，请重新生成计划')
    if any(result.get(k,'')!=options.get(k,'') for k in ('sheet','priority','source','h5_source')):raise ValueError('筛选条件或源码目录已变化，请重新生成 AI 运行步骤')
    selected=case_runner.selected_cases(book,options)
    if [c['id'] for c in selected]!=[c['id'] for c in result['cases']]:raise ValueError('AI 计划与原始 Excel 行号不一致')
    mapping={r['id']:r for r in result['cases']};rows=[]
    for case in book['cases']:
        row=dict(case)
        if case['id'] in mapping:
            entry=mapping[case['id']]
            plan=entry['plan'] or entry.get('partial_plan')
            row['plan_text']=json.dumps(plan,ensure_ascii=False) if plan else ''
            row['ai_pending']=entry['blocked_reason'] if not plan else ''
            row['ai_incomplete']=entry['blocked_reason'] if plan and not entry['plan'] else ''
        rows.append(row)
    return dict(book,cases=rows,excel_ai_plan=identifier,excel_ai_document=result)
