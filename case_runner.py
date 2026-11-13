import excel_execution_policy as excel_policy
"""Execute explicit case steps with assertions; never infer pass from coverage."""
import json
import re
import time
import automation
import popup_handler
import http_probe
import flow_planner
import hybrid_webview

ALIASES={
    '首页':['Home','首页'],'门店':['Store','门店'],'消息':['Message','消息'],'我的':['Mine','我的'],
    '学习中心':['Learning Center','学习中心'],'解决方案':['Solutions','Solution','解决方案'],
    '课程中心':['Course Center','课程中心'],'附近门店':['Nearby Stores','附近门店'],
    '我的收藏':['My Favorites','我的收藏'],'我的学习':['My Learning','我的学习'],
    '关于':['About','关于'],'更多':['More','更多'],'隐私政策':['Privacy Policy','隐私政策'],
    '通用设置':['General Settings','通用设置'],'语言':['Language','语言'],
}
ALLOWED={'scroll','tap','input','clear','input_local','input_secret','save','dispatch','assert','assert_absent','assert_enabled','assert_count','assert_selected','assert_route','assert_input','back','wait','screenshot','workflow_case','record'} | hybrid_webview.WEB_ACTIONS

def compile_linear(steps_text,expected_text):
    """Strict small grammar for human-written click/back/check use cases."""
    split=lambda text:[s.strip().rstrip('。；;') for s in re.split(r'【\d+】|\n',text) if s.strip()]
    actions=split(steps_text);expectations=split(expected_text)
    if len(actions)!=len(expectations):return None
    steps=[]
    for action,expected in zip(actions,expectations):
        if action in ('返回','点击返回','点击返回按钮','点击左上角返回按钮'):
            steps.append({'action':'back'})
        else:
            click=re.fullmatch(r'点击[“"【\[](.+?)[”"】\]](?:按钮|入口|tab页)?',action)
            simple=re.fullmatch(r'点击(首页|门店|消息|我的)(?:入口|按钮|tab页)?',action)
            if click or simple:steps.append({'action':'tap','value':(click or simple)[1]})
            elif not re.fullmatch(r'查看(?:当前)?(?:页面|首页|搜索框(?:内文案)?)',action):return None
        visible=re.fullmatch(r'(?:页面|搜索框内)?(?:默认)?(?:显示|展示|存在)(?:文案)?[“"](.+?)[”"]',expected)
        absent=re.fullmatch(r'(?:页面)?(?:不显示|不存在)[“"](.+?)[”"]',expected)
        tab=re.fullmatch(r'(?:进入|跳转到|回到)(首页|门店|消息|我的)(?:页面|页)?',expected)
        if visible:steps.append({'action':'assert','value':visible[1]})
        elif absent:steps.append({'action':'assert_absent','value':absent[1]})
        elif tab:steps.append({'action':'assert_selected','value':tab[1]})
        else:return None
    return {'steps':steps} if steps else None

def validate_plan(plan, require_assertion=True):
    if not isinstance(plan,dict):raise ValueError('执行计划必须为 JSON 对象')
    start_state=plan.get('start_state','home')
    observing=plan.get('execution_policy')==excel_policy.POLICY
    if start_state not in ('home','login_config','login'):raise ValueError('未知用例起点')
    steps=plan.get('steps',[]);requires=plan.get('requires',[])
    if not isinstance(steps,list) or not 1<=len(steps)<=80 or not isinstance(requires,list) or len(requires)>20:raise ValueError('需有 1～80 个步骤，最多 20 个前置断言')
    if any(isinstance(s,dict) and s.get('action') in ('record','web_observe') for s in steps) and not observing:raise ValueError('观察记录步骤仅允许Excel观察模式')
    for step in requires+steps:
        if isinstance(step,dict) and step.get('action')=='assert_enabled' and type(step.get('enabled')) is not bool:raise ValueError('enabled断言需要布尔值')
        if isinstance(step,dict) and step.get('action')=='assert_count' and (type(step.get('count')) is not int or not 0<=step['count']<=1000):raise ValueError('count断言需要0～1000整数')
        if not isinstance(step,dict) or step.get('action') not in ALLOWED:raise ValueError('未知用例操作')
        if step['action'] in ('tap','input','clear','input_local','input_secret','save','dispatch','assert','assert_absent','assert_enabled','assert_count','assert_selected','assert_route','assert_input','web_tap','web_assert','web_input','web_assert_input','web_save','workflow_case','record','web_observe'):
            if not isinstance(step.get('value'),str) or not 0<len(step['value'])<=512:raise ValueError('操作需指定 value')
        if step['action'] in ('input','assert_input','web_input','web_assert_input') and (not isinstance(step.get('text'),str) or len(step['text'])>1024):raise ValueError('输入内容无效')
        if step['action'] in ('input_local','input_secret'):
            if start_state=='home':raise ValueError('凭据输入仅限明确的登录测试起点')
            if not isinstance(step.get('text'),str) or not 1<=len(step['text'])<=1024:raise ValueError('登录测试输入无效')
            if step['action']=='input_local' and step['text'] not in ('account','password'):raise ValueError('本机登录数据仅支持 account/password')
        if step['action']=='web_assert' and 'text' in step and (not isinstance(step['text'],str) or not 0<len(step['text'])<=1024):raise ValueError('H5 预期文字无效')
        if step['action']=='workflow_case' and step.get('value') not in ('configure','login','language_page','language_switch','language_all','language_all_full','language_all_restore','language_all_full_restore','language_persistence','language_persistence_zh','language_restore_logout','logout','logout_relogin'):raise ValueError('未知专用回归阶段')
        if step.get('action') in ('input','assert_input','web_input','web_assert_input') and re.search(r'\$\{(?:test_account|test_password|account|password)\}',step.get('text','')):raise ValueError('登录凭据占位符不能作为实际输入，请使用专用登录流程')
        if step.get('action') in ('input','assert_input','web_input','web_assert_input') and re.search(r'\$\{[^}]+\}',step.get('text','')):raise ValueError('测试数据占位符尚未绑定，不能把变量名称直接填入表单')
        if step['action']=='scroll' and (type(step.get('times',1)) is not int or not 1<=step.get('times',1)<=5):raise ValueError('scroll times must be 1..5')
        if step['action']=='wait' and not 0<=float(step.get('seconds',1))<=10:raise ValueError('单次等待不能超过 10 秒')
        allowed_by=('text','css','xpath') if step['action'] in hybrid_webview.WEB_ACTIONS else ('label','id','xpath','field','target')
        default_by='text' if step['action'] in hybrid_webview.WEB_ACTIONS else 'label'
        if step.get('by')=='target' and step['action'] not in ('tap','input','assert','assert_selected','assert_input','clear','input_local','input_secret'):raise ValueError('逻辑目标当前仅支持原生点击、输入和正向断言')
        if step.get('by')=='field' and (start_state=='home' or step.get('value') not in ('search','account','password') or step['action'] not in ('input','clear','input_local','input_secret','assert_input')):raise ValueError('运行时输入框角色仅限登录测试的search/account/password')
        if step.get('by',default_by) not in allowed_by:raise ValueError('控件定位方式不受支持')
        if step['action']=='web_save' and step.get('click_mode','webdriver') not in ('webdriver','dom_checked'):raise ValueError('未知 H5 保存点击方式')
        if step['action'] in ('save','web_save','dispatch'):
            api=step.get('api',{})
            if not isinstance(api,dict) or api.get('method') not in ('POST','PUT','PATCH') or not re.fullmatch(r'/[\w/.-]+',api.get('path','')):raise ValueError('保存步骤必须绑定具体写接口及 method')
            if step['action']=='dispatch' and (api['method']!='POST' or api['path']!='/api/merchant/mobile/miniprogram/v2/call/task'):raise ValueError('呼叫下发仅允许源码确认的 POST 呼叫任务接口')
            if step['action']!='dispatch' and re.search(r'/auth/|/oauth/|password|account|/call/|/task|/delete|/remove|/logout',api['path'],re.I):raise ValueError('凭据变更、删除及机器人任务接口需要专用流程')
            if not isinstance(api.get('codes',[610000,0]),list) or not api.get('codes',[610000,0]) or any(type(code) is not int for code in api.get('codes',[610000,0])):raise ValueError('接口成功码必须为非空整数数组')
            if not isinstance(api.get('equals',{}),dict):raise ValueError('返回值断言 equals 必须为对象')
            http_probe.safe_fields(list(api.get('equals',{})))
            if not 1<=float(api.get('timeout',20))<=60:raise ValueError('保存接口等待时间需为 1～60 秒')
    if any(s['action'] not in ('assert','assert_absent','assert_enabled','assert_count','assert_selected','assert_route','assert_input','web_assert','web_assert_input') for s in requires):raise ValueError('前置检查只能使用断言')
    if require_assertion and not any(s['action'] in ('assert','assert_absent','assert_enabled','assert_count','assert_selected','assert_route','assert_input','save','dispatch','web_assert','web_assert_input','web_save','workflow_case') or observing and s['action'] in ('record','web_observe') for s in steps):raise ValueError('缺少预期结果断言，不能判定 pass')
    policy=plan.get('execution_policy')
    if policy is not None and policy!=excel_policy.POLICY:raise ValueError('未知Excel执行规则')
    return {'requires':requires,'steps':steps,**({'execution_policy':policy} if policy else {}),**({'start_state':start_state} if start_state!='home' else {})}

def compile_case(case,override=None,index=None):
    if not case['mobile']:return None,case['scope_reason']
    if case.get('ai_pending'):return None,case['ai_pending']
    if not case['steps'].strip() or not case['expected'].strip():return None,'缺少操作步骤或预期结果'
    raw=override if override is not None else case.get('plan_text','')
    if raw:
        try:return validate_plan(json.loads(raw) if isinstance(raw,str) else raw,require_assertion=not bool(case.get('ai_incomplete'))),''
        except (ValueError,TypeError,KeyError) as error:return None,'执行计划无效：'+str(error)
    form=flow_planner.compile_form(case,index)
    if form:
        try:return validate_plan(form),''
        except ValueError as error:return None,'表单流程需专用适配：'+str(error)
    pre=case.get('precondition','').strip()
    clean=lambda text:re.sub(r'【\d+】','',text).strip().rstrip('。')
    text=clean(case['steps']);expected=clean(case['expected'])
    contexts={
        '已进入解决方案页面':['学习中心','解决方案'],
        '已进入课程中心页面':['学习中心','课程中心'],
        '已在学习中心页':['学习中心'],
        '已在我的学习页面':['学习中心','我的'],
    }
    if pre in contexts:
        navigation=[{'action':'tap','value':label} for label in contexts[pre]]
        if text in ('在解决方案页点击左上角返回','在课程中心页点击左上角返回') and expected=='回到首页':
            return validate_plan({'steps':navigation+[{'action':'back'},{'action':'assert_selected','value':'首页'}]}),''
        placeholder=re.fullmatch(r'搜索框内默认显示文案["“](.+?)["”]',expected)
        if text=='查看搜索框内文案' and placeholder:
            return validate_plan({'steps':navigation+[{'action':'assert','value':placeholder[1]}]}),''
        if text in ('点击"我的"','点击“我的”') and expected=='进入我的学习页面，包括我的收藏/我的学习':
            return validate_plan({'steps':navigation+[{'action':'tap','value':'我的'},{'action':'assert','value':'我的收藏'},{'action':'assert','value':'我的学习'}]}),''
    if pre=='账号有学习中心权限' and text=='在首页点击学习中心入口\n解决方案、课程中心、我的tab页相互切换' and expected=='默认进入"解决方案"tab页\n进入对应页面，且无异常':
        return validate_plan({'requires':[{'action':'assert','value':'学习中心'}],'steps':[{'action':'tap','value':'学习中心'},{'action':'assert_selected','value':'解决方案'},{'action':'tap','value':'课程中心'},{'action':'assert_selected','value':'课程中心'},{'action':'tap','value':'我的'},{'action':'assert','value':'我的收藏'},{'action':'assert','value':'我的学习'}]}),''
    # Only compile complete, unambiguous tab-switch cases automatically.
    # Longer business descriptions need explicit steps/assertions, not guessed clicks.
    if pre and not re.fullmatch(r'(?:某账号|账号|用户)?已登录[，,。\s]*|在首页|已在首页|已登录，在首页',pre):return None,'前置条件需转换为可验证的 requires 断言或准备测试数据'
    linear=compile_linear(case['steps'],case['expected'])
    if linear:return validate_plan(linear),''
    text=re.sub(r'【\d+】','',case['steps']).strip().rstrip('。')
    match=re.fullmatch(r'(?:在首页)?点击[“"【]?(首页|门店|消息|我的)[”"】]?(?:tab(?:键|页)?|Tab|入口|按钮)?(?:[，,]?进入(?:对应)?页面)?',text)
    if match:
        tab=match[1]
        if re.fullmatch(r'(?:【\d+】)?(?:进入|跳转(?:到)?)(?:对应|'+re.escape(tab)+r')(?:页面|页)[，,。\s]*(?:且无异常)?',case['expected'].strip()):
            return validate_plan({'steps':[{'action':'tap','value':tab},{'action':'assert_selected','value':tab}]}),''
    return None,'自然语言业务步骤尚未完整转换；请补充“自动化步骤”JSON（含断言），不会仅凭点击判 pass'

def selected_cases(book,options):
    sheet=options.get('sheet','');priority=options.get('priority','')
    ids=options.get('case_ids')
    if ids is not None:
        if not isinstance(ids,list) or not ids or len(ids)>10000 or any(not isinstance(i,str) for i in ids):raise ValueError('定向重测 case_ids 必须是非空用例编号数组')
        if set(ids)-{c['id'] for c in book['cases']}:raise ValueError('定向重测包含不存在的用例编号')
    return [c for c in book['cases'] if c['mobile'] and (not sheet or c['sheet']==sheet) and (not priority or c['priority']==priority) and (ids is None or c['id'] in ids)]

def preview(book,options,index=None):
    overrides=options.get('plans',{})
    if not isinstance(overrides,dict):raise ValueError('执行计划映射必须为 JSON 对象')
    if set(overrides)-{c['id'] for c in book['cases']}:raise ValueError('执行计划含有不存在的用例 ID，请按工作表名:原行号填写')
    cases=selected_cases(book,options);rows=[]
    for case in cases:
        plan,reason=compile_case(case,overrides.get(case['id']),index)
        rows.append({**{k:case[k] for k in ('id','sheet','row','title','group','priority','precondition','steps','expected')},'ready':bool(plan),'reason':reason,'plan':plan,'partial_reason':case.get('ai_incomplete','')})
    return {'selected':len(rows),'ready':sum(r['ready'] for r in rows),'pending':sum(not r['ready'] for r in rows),'cases':rows,'excluded':[{'id':c['id'],'title':c['title'],'reason':c['scope_reason']} for c in book['cases'] if not c['mobile']]}

class CaseBlocked(RuntimeError):pass

def api_note(event):
    """用例异常时若能对应到接口，标注 method/path/状态码/业务码，便于定位服务端问题。"""
    if not isinstance(event,dict):return ''
    parts=['最近接口：'+str(event.get('method') or '?')+' '+str(event.get('path') or '?')]
    if event.get('http_status') is not None:parts.append('HTTP '+str(event['http_status']))
    if event.get('code') is not None:parts.append('业务码 '+str(event['code']))
    if event.get('error'):parts.append('网络错误 '+str(event['error']))
    return '（'+('，'.join(parts)+'）')

def find_node(nodes,step,aliases=None,adapter=None,first_match=False):
    value=step['value'];by=step.get('by','label')
    def choose(matches):
        if not first_match and len(matches)>1 and step['action'] in ('tap','input','clear','input_local','input_secret','save','dispatch','assert_input'):raise CaseBlocked('操作控件未唯一匹配：'+value+'（'+str(len(matches))+' 个），未选择第一个控件猜测执行')
        return matches[0] if matches else None
    if by=='target':
        import app_adapter
        return app_adapter.resolve(nodes,value,adapter,first_match=first_match)
    if by=='field':
        fields=[n for n in nodes if n['editable']]
        if value=='password':fields=[n for n in fields if n['secure']]
        else:fields=[n for n in fields if not n['secure']]
        if not fields or len(fields)!=1 and not first_match:
            detail='：'+'、'.join(((n.get('hint','') or n['label'] or n['kind']).strip()[:20] or '未命名输入框') for n in fields[:3]) if fields else ''
            raise CaseBlocked('登录测试输入框角色未唯一确认：'+value+'（非密码输入框 '+str(len(fields))+' 个'+detail+'）')
        return fields[0]
    if by=='id':
        exact=[n for n in nodes if n['id']==value]
        if exact:return choose(exact)
        # Flutter shared controls carry a component scope. Only our reserved
        # identity namespace permits suffix resolution, still requiring uniqueness.
        return choose([n for n in nodes if value.startswith('flutter.') and n['id'].endswith('/'+value)])
    if by=='xpath':return next((n for n in nodes if n['path']==value),None)
    labels=list(dict.fromkeys(ALIASES.get(value,[value])+(aliases or {}).get(value,[])))
    def node_texts(n):
        texts=[]
        for line in n['label'].splitlines():
            texts.append(line.strip())
            if '·' in line:texts.extend(seg.strip() for seg in line.split('·') if seg.strip())
        return texts
    matches=[n for n in nodes if any(text in labels for text in node_texts(n)) or (step['action'] in ('input','clear','input_local','input_secret','assert_input') and n.get('hint','') in labels)]
    if step['action'] in ('input','clear','input_local','input_secret','assert_input'):matches=[n for n in matches if n['editable']]
    elif step['action'] in ('tap','save','dispatch'):
        clickable=[n for n in matches if n['clickable']]
        if not clickable:
            # Flutter 常见结构：文字在子节点，可点击属性在祖先容器；沿路径向上找最近的可点击祖先。
            by_path={n['path']:n for n in nodes}
            fallback={}
            for n in matches:
                parts=n['path'].split('/')
                for depth in range(len(parts)-1,0,-1):
                    ancestor=by_path.get('/'.join(parts[:depth]))
                    if ancestor and ancestor['clickable']:fallback.setdefault(ancestor['path'],ancestor);break
            clickable=list(fallback.values())
        matches=clickable
    if step['action']=='assert_selected':
        selected=[]
        for node in matches:
            if node.get('selected'):selected.append(node);continue
            parents=[p for p in nodes if p.get('selected') and re.fullmatch(r'devicecheck-language-[a-z]{2,3}-[A-Z]{2}',p['label']) and node['path'].startswith(p['path']+'/')]
            if parents:selected.append(dict(node,selected=True,selection_evidence=max(parents,key=lambda p:len(p['path']))['label']))
        matches=selected
    return choose(matches)

def run(explorer,book,options,log,capture,progress,stopped,sleep):
    sentinel=object();previous=getattr(explorer,'excel_observation_mode',sentinel)
    try:return _run(explorer,book,options,log,capture,progress,stopped,sleep)
    finally:
        if explorer is not None:
            if previous is sentinel:explorer.__dict__.pop('excel_observation_mode',None)
            else:explorer.excel_observation_mode=previous


def _run(explorer,book,options,log,capture,progress,stopped,sleep):
    if options.get('evidence_policy','screenshots') not in ('screenshots','assertions'):raise ValueError('未知用例证据策略')
    plans=preview(book,options,getattr(explorer,'flow_index',None));results=[]
    seconds=int(options.get('seconds',0))
    if seconds<0:raise ValueError('用例总时长不能为负数；0 表示不限')
    budget_deadline=time.monotonic()+min(max(seconds,30),7200) if seconds else float('inf')
    def back_saves():
        reader=getattr(explorer,'route_reader',None)
        return getattr(explorer,'page_policies',{}).get(reader.read() if reader else '',{}).get('may_save',False)
    def reopen():
        app=getattr(explorer,'app_package','') or getattr(explorer,'app_bundle','')
        if not app:raise CaseBlocked('返回会保存数据，且无法确认 App 边界')
        explorer.call('POST',explorer.base+'/appium/device/terminate_app',{'appId':app})
        explorer.call('POST',explorer.base+'/appium/device/activate_app',{'appId':app})
        return explorer.settled_source()
    def permission_denial_intent(case):
        text=case['title']+' '+case['precondition']+' '+json.dumps(case['plan'],ensure_ascii=False)
        return bool(re.search(r'拒绝|不允许|禁止|不开启|关闭权限|deny|don.t allow',text,re.I))
    denial={'explicit':False};auth={'active':False}
    def stable_source():
        source=explorer.settled_source();popup_taps={}
        for _ in range(4):
            nodes=automation.parse_ui(source)
            if not auth['active'] and any(n['secure'] for n in nodes):raise CaseBlocked('遇到登录/密码页面，未采集截图')
            reader=getattr(explorer,'route_reader',None)
            if not auth['active'] and reader and re.match(r'^/(?:login|staffLogin)(?:/|$)',reader.read() or ''):raise CaseBlocked('已回到登录页面，当前业务用例未完成')
            package=getattr(explorer,'app_package','')
            if package and not any(n['package']==package for n in nodes):raise CaseBlocked('当前页面不属于被测 App 或自动化连接已中断')
            if not any(n['label'] or n['id'] for n in nodes):raise CaseBlocked('页面为空或尚未加载，不能据此判定预期结果成立')
            bundle=getattr(explorer,'app_bundle','')
            if bundle and explorer.call('POST',explorer.base+'/execute/sync',{'script':'mobile: activeAppInfo','args':[]}).get('bundleId')!=bundle:raise CaseBlocked('当前页面不属于被测 App')
            if auth['active']:return source,nodes
            target,reason=popup_handler.permission_target(nodes,denial['explicit'])
            if target is None:target,reason=popup_handler.close_target(nodes)
            if target:
                key=(target['path'],target['label'])
                if popup_taps.get(key,0)>=2:
                    # 弹窗（如打开外部程序确认）连点两次无反应，直接返回离开，不再反复点击。
                    log('弹窗两次点击未关闭，按返回键离开：'+(target['label'] or target['id'])[:60])
                    explorer.back(nodes)
                else:
                    popup_taps[key]=popup_taps.get(key,0)+1
                    if reason.startswith('系统权限'):log(reason)
                    explorer.tap(target)
                source=explorer.settled_source();continue
            if popup_handler.modal_present(nodes):raise CaseBlocked('弹窗无明确关闭按钮，当前用例未完成')
            return source,nodes
        raise CaseBlocked('弹窗多次关闭后仍存在')
    def reset():
        # Known home tab is a checked boundary between independent test cases.
        for attempt in range(7):
            try:source,nodes=stable_source()
            except CaseBlocked:
                if attempt:raise
                source=explorer.source();nodes=automation.parse_ui(source)
                if any(n['secure'] for n in nodes):raise
                recovered=reopen() if back_saves() else explorer.escape_blocked_page(nodes)
                if not recovered:raise CaseBlocked('上条用例页面无法恢复，当前用例未执行')
                continue
            home=find_node(nodes,{'action':'tap','value':'首页'})
            if home:
                explorer.tap(home);return stable_source()
            if attempt==5:
                app=getattr(explorer,'app_package','') or getattr(explorer,'app_bundle','')
                if not app:raise CaseBlocked('无法确认 App 首页边界')
                explorer.call('POST',explorer.base+'/appium/device/terminate_app',{'appId':app})
                explorer.call('POST',explorer.base+'/appium/device/activate_app',{'appId':app})
            elif back_saves():reopen()
            else:explorer.back(nodes)
        raise CaseBlocked('未能恢复首页，未执行当前用例')
    for case in plans['cases']:
        observing=(case.get('plan') or {}).get('execution_policy')==excel_policy.POLICY
        if explorer is not None:explorer.excel_observation_mode=observing
        result={'id':case['id'],'sheet':case['sheet'],'row':case['row'],'title':case['title'],'result':'fail','status':'未执行','reason':'','screenshots':[],'steps':[]}
        if observing:result.update(observation_mode=True,account_source='当前配置或已登录账号',original_expected=case['expected'])
        result['verification_level']='ui_and_api' if case.get('plan') and any(s['action'] in ('save','dispatch','web_save') for s in case['plan']['steps']) else 'ui'
        result['evidence_policy']=options.get('evidence_policy','screenshots')
        if stopped():result.update(status='已停止',reason='用户停止，未完成用例')
        elif time.monotonic()>=budget_deadline:result.update(status='未执行',reason='达到用例批次时间上限')
        elif not case['ready']:result.update(result='skip',status='已跳过',reason=case['reason'])
        else:
            log('执行用例 '+case['id']+'：'+case['title'][:100])
            denial['explicit']=permission_denial_intent(case)
            if getattr(explorer,'http_probe',None):explorer.http_probe.last_event=None
            try:
                auth['active']=case['plan'].get('start_state','home')!='home'
                plan_steps=case['plan']['requires']+case['plan']['steps']
                if not observing and any(s['action']=='assert_route' for s in plan_steps) and not getattr(explorer,'route_reader',None):raise CaseBlocked('当前运行没有源码路由观察器；此用例需要路由断言，未开始操作')
                if any(s['action'] in ('save','dispatch') for s in plan_steps) and not getattr(explorer,'http_probe',None):raise CaseBlocked('当前运行没有原生接口观察器；此用例要求接口结果，未开始操作')
                if any(s.get('by')=='target' for s in plan_steps) and not getattr(explorer,'adapter',None):raise CaseBlocked('此用例使用逻辑目标，请先选择定位适配包')
                prepare=getattr(explorer,'prepare_test_case',None)
                if prepare:prepare(case['plan'].get('start_state','home'))
                elif auth['active']:raise CaseBlocked('登录测试起点准备器未配置，请从源码构建 Android 测试副本')
                if any(s['action']=='workflow_case' for s in case['plan']['steps']):raise CaseBlocked('该用例需要登录与语言专用回归执行器')
                if auth['active']:
                    stable_source()
                elif options.get('start_from_current'):
                    if not case['plan']['requires']:raise CaseBlocked('从当前页开始需要明确的前置断言')
                    stable_source()
                else:reset()
                for number,step in enumerate(case['plan']['requires']+case['plan']['steps'],1):
                    if stopped():raise CaseBlocked('用户停止')
                    if time.monotonic()>=budget_deadline:raise CaseBlocked('达到用例批次时间上限')
                    try:
                        action=step['action'];source,nodes=stable_source()
                        if observing and action=='record':
                            messages=[automation.redact(n['label'],explorer.secrets)[:160] for n in nodes if n.get('label') and not n.get('secure') and not n.get('editable') and re.search(r'未找到|暂无|没有|不能为空|错误|失败|成功|不正确|无效|invalid|no results|empty',n['label'],re.I)]
                            result['steps'].append({'number':number,'action':'record','status':'observed','note':automation.redact(step.get('value',''),explorer.secrets),'messages':list(dict.fromkeys(messages))[:12]})
                            log('观察记录：'+automation.redact(step.get('value',''),explorer.secrets))
                            continue
                        if observing and action=='back':
                            reader=getattr(explorer,'route_reader',None)
                            if reader and reader.read() in ('/loginConfig','/splash'):
                                result['steps'].append({'number':number,'action':'back','status':'observed','executed':False,'reason':'当前为启动或登录配置根页，跳过返回以免退出App'})
                                continue
                        if action in ('input_local','input_secret') and not auth['active']:raise CaseBlocked('登录测试输入不能用于普通业务页面')
                        if action in hybrid_webview.WEB_ACTIONS:
                            if auth['active']:raise CaseBlocked('登录测试不导出 WebView 内容，协议页需使用单独无凭据用例验证')
                            try:
                                with hybrid_webview.WebView(explorer) as web:evidence=web.perform(step)
                            except hybrid_webview.DOMTargetMissing:
                                if observing:result['steps'].append({'number':number,'action':action,'status':'observed','target':step['value'],'present':False})
                                raise
                            source,nodes=stable_source()
                            proof=capture('case-'+str(case['row'])+'-'+str(len(results))+'-step-'+str(number),source)
                            if not proof and options.get('evidence_policy','screenshots')=='screenshots':raise CaseBlocked('H5 步骤截图未保存')
                            if proof:result['screenshots'].append(proof)
                            result['steps'].append({'number':number,'action':action,'status':'observed' if observing and action in ('web_assert','web_assert_input','web_observe') else 'pass','web':evidence})
                            continue
                        if observing and action in ('assert','assert_absent','assert_selected','assert_count','assert_enabled','assert_input','assert_route'):
                            observed_nodes=automation.parse_ui(source,include_disabled=action in ('assert_count','assert_enabled'))
                            found=[n for n in observed_nodes if find_node([n],step,getattr(explorer,'control_aliases',{}))] if action!='assert_route' else []
                            record={'number':number,'action':action,'status':'observed','target':step.get('value'),'present':bool(found),'match_count':len(found)}
                            if found:record['actual_text']='[redacted]' if found[0].get('secure') else automation.redact(found[0].get('label',''),explorer.secrets);record['selected']=found[0].get('selected',False);record['enabled']=found[0].get('enabled',False)
                            if action=='assert_input' and found:
                                record['actual_input']='[redacted]' if found[0].get('secure') else automation.redact(found[0].get('value') or found[0].get('label',''),explorer.secrets)
                                record['input_matches']=not found[0].get('secure') and step.get('text') in (found[0].get('value'),found[0].get('label'))
                            if action=='assert_route':
                                reader=getattr(explorer,'route_reader',None);record['actual_route']=reader.read() if reader else None
                            result['steps'].append(record)
                            log('观察记录：'+str(step.get('value'))+' '+('存在' if found else '不存在')+'，匹配 '+str(len(found))+' 个')
                            continue
                        if action in ('assert_enabled','assert_count'):nodes=automation.parse_ui(source,include_disabled=True)
                        if action=='assert_count':
                            found=[n for n in nodes if find_node([n],step,getattr(explorer,'control_aliases',{}))]
                            found=[n for n in found if not any(m['path'].startswith(n['path']+'/') for m in found if m is not n)]
                            if len(found)!=step['count']:raise AssertionError('控件数量不符：'+step['value']+'，实际 '+str(len(found))+'，预期 '+str(step['count']))
                        node=find_node(nodes,step,getattr(explorer,'control_aliases',{}),getattr(explorer,'adapter',None),first_match=observing) if 'value' in step else None
                        if action=='assert_enabled':
                            found=[n for n in nodes if find_node([n],step,getattr(explorer,'control_aliases',{}))]
                            if len(found)!=1:raise CaseBlocked('启用状态控件未唯一匹配：'+step['value'])
                            if found[0]['enabled']!=step['enabled']:raise AssertionError('控件启用状态不符：'+step['value'])
                        if action in ('assert','assert_selected') and node is None:raise AssertionError('未找到预期控件/状态：'+step['value'])
                        if action=='assert_absent' and node is not None:raise AssertionError('出现了预期不存在的控件：'+step['value'])
                        if action=='assert_route':
                            reader=getattr(explorer,'route_reader',None)
                            if not reader:raise CaseBlocked('缺少路由观察器，不能确认进入预期页面')
                            if reader.read()!=step['value']:raise AssertionError('未进入预期路由：'+step['value'])
                        if action=='assert_input':
                            if not node or node['secure']:raise CaseBlocked('未定位到可验证的普通输入框')
                            if step['text'] not in (node['label'],node.get('value','')):raise AssertionError('输入框实际内容与测试值不一致')
                        api_result=None
                        if action in ('tap','input','clear','input_local','input_secret','save','dispatch'):
                            if node is None:
                                if observing:result['steps'].append({'number':number,'action':action,'status':'observed','target':step['value'],'present':False})
                                raise CaseBlocked('未找到操作控件：'+step['value'])
                            if node['secure'] and action not in ('clear','input_local','input_secret'):raise CaseBlocked('密码字段需使用本机登录测试输入动作')
                            if node['secure'] and not auth['active']:raise CaseBlocked('普通业务用例不能访问密码字段')
                            if action=='input_local' and step['text']=='password' and not node['secure']:raise CaseBlocked('本机密码仅输入系统标记的密码框')
                            blocked=any(word and word in (node['label']+' '+node['id']).casefold() for word in automation.DEFAULT_SKIP.split(','))
                            if action=='dispatch' and options.get('call_acceptance')!='backend_only':raise CaseBlocked('本轮未启用后台呼叫下发验收，未点击呼叫')
                            if action=='dispatch' and re.search(r'删除|注销|支付|取消任务|强制取消|delete|logout|pay|cancel task',node['label'],re.I):raise CaseBlocked('呼叫下发流程不执行删除、支付或取消任务')
                            consent=auth['active'] and action=='tap' and bool(re.fullmatch(r'同意(?:并继续|并登录)?|不同意|取消|登录|登录/注册|下一步|agree(?: and (?:continue|login))?|disagree|cancel|log in|login|sign in|next',node['label'].strip(),re.I))
                            if blocked and not consent and action!='dispatch' and not (action=='save' and re.fullmatch(r'保存|提交|确认|完成|save|submit|confirm|done',node['label'].strip(),re.I)):raise CaseBlocked('该操作涉及删除或设备控制，需要专用测试流程：'+step['value'])
                            if action in ('save','dispatch'):
                                probe=getattr(explorer,'http_probe',None)
                                if not probe:raise CaseBlocked('当前测试包没有接口观察器，请重新从源码构建')
                                if step['api']['path'] not in probe.manifest['paths']:raise CaseBlocked('保存接口未在源码观察范围内，未点击保存')
                                http_probe.safe_fields(list(step['api'].get('equals',{})))
                                if set(step['api'].get('equals',{}))-set(probe.manifest['response_fields']):raise CaseBlocked('响应字段未加入本次构建的观察范围，未点击保存')
                                marker=probe.mark();explorer.tap(node)
                                until=min(budget_deadline,time.monotonic()+float(step['api'].get('timeout',20)))
                                while time.monotonic()<until:
                                    if stopped():raise CaseBlocked('用户停止')
                                    api_result=probe.check(marker,step['api'])
                                    if api_result:break
                                    sleep(.5)
                                if api_result is None:raise AssertionError('点击后未收到本次操作对应的接口响应')
                                if action=='dispatch':
                                    shape=api_result.get('request_shape')
                                    if not isinstance(shape,dict) or not shape.get('storeId') or not shape.get('sceneCode') or not (shape.get('targetPointId') or shape.get('multiPointCount',0)>0):raise CaseBlocked('呼叫接口已返回，但缺少本次目标点位与场景参数的观察证据，不能完整验收')
                            elif action=='tap':explorer.tap(node)
                            else:
                                text='' if action=='clear' else getattr(explorer,'test_credentials',{}).get(step['text'],'') if action=='input_local' else step['text']
                                if action=='input_local' and not text:raise CaseBlocked('本机测试账号或密码未配置')
                                if action in ('input_local','input_secret') and text:
                                    explorer.secrets=list(dict.fromkeys(list(explorer.secrets)+[text]))
                                eid=explorer.find({'by':'xpath','value':node['path']})
                                if action=='clear':explorer.call('POST',explorer.base+'/element/'+eid+'/clear',{})
                                else:explorer.type(eid,text,node)
                        elif action=='back':
                            if back_saves():raise CaseBlocked('源码显示返回会保存数据，需使用 save 步骤绑定接口')
                            explorer.back(nodes)
                        elif action=='scroll':
                            for _ in range(step.get('times',1)):
                                if stopped():raise CaseBlocked('Stopped')
                                explorer.scroll()
                        elif action=='wait':sleep(float(step.get('seconds',1)))
                        source,nodes=stable_source()
                        name='case-'+str(case['row'])+'-'+str(len(results))+'-step-'+str(number)
                        proof=None if auth['active'] else capture(name,source)
                        if not proof and not auth['active'] and options.get('evidence_policy','screenshots')=='screenshots':raise CaseBlocked('当前步骤截图未能保存，不能作为完整用例通过')
                        if proof:result['screenshots'].append(proof)
                        result['steps'].append({'number':number,'action':action,'status':'pass',**({'api':api_result} if api_result else {}),**({'acceptance':'backend_task_accepted_only','robot_motion_verified':False} if action=='dispatch' else {})})
                    except Exception as error:
                        if step['action'] not in ('save','web_save') or stopped():raise
                        import save_outcomes
                        failure=save_outcomes.record(explorer,error)
                        result['steps'].append({'number':number,'action':step['action'],'status':'fail','save':failure})
                        continue
                if observing:result.update(result='review',status='已记录观察结果',reason='按当前账号记录实际页面及搜索结果，未判定原始预期通过')
                elif case.get('partial_reason'):result.update(result='fail',status='执行受阻',reason='已执行连续匹配的部分步骤，完整用例未完成：'+case['partial_reason'])
                else:result.update(result='pass',status='已执行',reason='步骤与显式预期断言全部通过')
                if any(item.get('status')=='fail' or item.get('web',{}).get('status')=='failed_or_unconfirmed' for item in result['steps']):result.update(result='fail',status='保存失败，后续已继续',reason='保存失败或结果未确认，已记录并执行后续步骤')
            except AssertionError as error:
                is_precondition=len(result['steps'])<len(case['plan']['requires'])
                reason=automation.redact(error,explorer.secrets)
                if is_precondition and not result['steps']:
                    reason+='（恢复首页后未通过前置断言：该文案若只在导航后才出现，说明计划缺少从首页出发的导航步骤，需重新匹配自动化步骤）'
                probe=getattr(explorer,'http_probe',None);event=getattr(probe,'last_event',None) if probe else None
                if event:reason+=api_note(event)
                result.update(status='执行受阻' if case.get('partial_reason') else '前置条件不满足' if is_precondition else '断言失败',reason=('部分计划执行未完成：' if case.get('partial_reason') else '')+reason)
            except Exception as error:
                reason=automation.redact(error,explorer.secrets)[:500]
                probe=getattr(explorer,'http_probe',None);event=getattr(probe,'last_event',None) if probe else None
                if event:reason+=api_note(event)
                result.update(status='已停止' if stopped() else '执行受阻',reason=reason[:600])
            if observing and result['result']=='fail' and not stopped():result.update(result='review',status='已记录，继续下一用例',reason=result['reason'] or '当前条目未完成，已保留实际结果')
            probe=getattr(explorer,'http_probe',None)
            if probe and getattr(probe,'last_event',None):result['last_observed_api']=probe.last_event
            if result['result']=='fail' and not stopped() and not auth['active']:
                try:
                    source,nodes=stable_source();proof=capture('case-'+str(len(results))+'-failure',source)
                    if proof:result['screenshots'].append(proof)
                except Exception:pass
        if auth['active']:result['evidence_policy']='登录测试仅保存动作与断言结果，不保存截图和页面结构'
        results.append(result)
        if case['ready'] or result['result']=='skip':log('用例结果 '+case['id']+'：'+result['result']+' / '+result['status']+' · '+result['reason'])
        if case['ready'] or len(results)%25==0 or len(results)==len(plans['cases']):progress(results)
    return results
