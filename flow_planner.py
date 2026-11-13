"""Evidence-bearing workflow drafts from workbook context and Flutter source."""
import json
import re
import posixpath
from pathlib import Path
import source_navigation
import stable_identifiers


class EvidenceBudgetExceeded(ValueError):
    """Source selection must be narrowed before any model request."""

KNOWN_ENTRIES={
    'myCurrency':['我的','通用设置'],'myAbout':['我的','关于'],
    'myMore':['我的','关于','更多'],'language':['我的','通用设置','语言'],
    'accountManager':['我的','通用设置','账号管理'],
    'modifyPass':['我的','通用设置','账号管理','修改密码'],
    'notify':['消息','消息设置'],'deviceManager':['我的','设备管理'],
    'grabStores':['首页','抢门店'],
}

def without_comments(text):
    pattern=r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//[^\n]*|/\*.*?\*/'''
    return re.sub(pattern,lambda m:re.sub(r'[^\n]',' ',m[0]) if m[0].startswith(('//','/*')) else m[0],text,flags=re.S)

def call_body(text,opening):
    pattern=r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'"""
    masked=re.sub(pattern,lambda m:' '*len(m[0]),text)
    depth=0
    for position in range(opening,len(text)):
        if masked[position]=='(':depth+=1
        elif masked[position]==')':
            depth-=1
            if depth==0:return text[opening+1:position]
    return ''

def source_index(project):
    project=Path(project).expanduser().resolve()
    if not (project/'pubspec.yaml').is_file():raise ValueError('流程分析需要 Flutter 项目根目录')
    navigation=source_navigation.analyze(project)
    files={str(f.relative_to(project)):without_comments(f.read_text(errors='replace')) for f in (project/'lib').rglob('*.dart')}
    identifiers=stable_identifiers.registry(project)
    class_sources={name:file for file,text in files.items() for name in re.findall(r'\bclass\s+(\w+)',text)}
    package=re.search(r'^name:\s*(\w+)',(project/'pubspec.yaml').read_text(),re.M)
    package=package[1] if package else 'app_phone'
    def imports(file):
        for link in re.findall(r"import\s+['\"]([^'\"]+)['\"]",files.get(file,'')):
            if link.startswith('package:'+package+'/'):target='lib/'+link.split('/',1)[1]
            elif not re.match(r'\w+:',link):target=posixpath.normpath(posixpath.join(posixpath.dirname(file),link))
            else:continue
            if target in files:yield target
    translations={};locale_packs={}
    languages=['zh','en']+sorted(p.stem for p in (project/'assets/i18n').glob('*.json') if p.stem not in ('zh','en'))
    for lang in languages:
        file=project/'assets/i18n'/f'{lang}.json'
        if file.exists():
            values=json.loads(file.read_text());locale_packs[lang]=values
            for key,value in values.items():
                if isinstance(value,str) and value not in translations.setdefault(key,[]):translations[key].append(value)
    def labels(text):
        keys=list(dict.fromkeys(re.findall(r"['\"]([^'\"\n]+)['\"]\.tr",text)))
        return [{'key':key,'labels':translations.get(key,[key])} for key in keys]
    endpoints={}
    api=files.get('lib/http/request_api.dart','')
    for match in re.finditer(r"static\s+const\s+(?:String\s+)?(\w+)\s*=\s*['\"]([^'\"]+)['\"]",api):
        endpoints[match[1]]=match[2]
    calls=[]
    for file,text in files.items():
        if '/repository/' not in file:continue
        methods=list(re.finditer(r'^  (?![ \t])(?:[\w<>?, ]+[ \t]+)?(\w+)[ \t]*(?:<[^\n>]+>)?[ \t]*\(',text,re.M))
        for m in re.finditer(r'(?:DioUtil|RequestExt)\.(get|post|put|delete|patch)(?:<[^>]*>)?\(\s*RequestApi\.(\w+)',text):
            previous=[x for x in methods if x.start()<m.start()]
            calls.append({'repository':Path(file).stem,'method':previous[-1][1] if previous else '', 'http_method':m[1].upper(),'path':endpoints.get(m[2],''),'constant':m[2],'source':file,'line':text.count('\n',0,m.start())+1})
    pages=[]
    for route in navigation['routes']:
        source=next((f for f,t in files.items() if re.search(r'\bclass\s+'+re.escape(route['page'])+r'\b',t)),None) if route['page'] else None
        if not source:continue
        text=files[source];related={source:text}
        # Relative imports and extracted child widgets/controllers carry page evidence.
        frontier=[source]
        for _ in range(3):
            following=[]
            for file in frontier:
                for target in imports(file):
                    local=posixpath.dirname(target)==posixpath.dirname(source)
                    if target not in related and len(related)<30 and (local or 'controller' in target or '/repository/' in target):
                        related[target]=files[target];following.append(target)
            frontier=following
        imported='\n'.join(related.values())
        repositories=set(re.findall(r"http/repository/(\w+)\.dart",imported))
        candidates=[c for c in calls if c['repository'] in repositories and c['method'] and re.search(r'\.'+re.escape(c['method'])+r'\s*\(',imported) and c['path']]
        fields=[]
        for m in re.finditer(r'\b(?:TextField|TextFormField|InputWidget|InputTextWidget|InputTxtWidget|NumberControllerWidget|_buildInputField|_buildPickerField|_selectionField)\s*\(',text):
            snippet=call_body(text,m.end()-1)
            # Helper declarations are not input instances.
            if re.match(r'\s*\{',snippet):continue
            fields.append({'widget':m[0].split('(')[0].strip(),'labels':labels(snippet)[:5],'source':source,'line':text.count('\n',0,m.start())+1,'secure':bool(re.search(r'(?:isPass|obscure|obscureText):\s*true',snippet)),'requires_runtime_binding':True})
        blocked_back=bool(re.search(r'canPop:\s*false|onWillPop:',text))
        bar=re.search(r'appBar:\s*StyledWidgets\.backTransAppBar\s*\(',text)
        bar_body=call_body(text,bar.end()-1) if bar else ''
        saves_on_back=bool(re.search(r'onPressed:\s*\(\)\s*=>\s*(?:update|save|submit)\w*\(',bar_body,re.I))
        title_keys=re.findall(r"\btitle:\s*['\"]([^'\"]+)['\"]\.tr",text)
        device_calls=[{'manager':m[1],'method':m[2],'source':source,'line':text.count('\n',0,m.start())+1,'status':'requires_device_adapter_not_http_save'} for m in re.finditer(r'\b(ApnLanManager)\.ins\(\)\s*\.\s*(\w+)\s*\(',text)]
        pages.append({**route,'source':source,'labels':labels(text),'title_labels':[v for key in title_keys for v in translations.get(key,[key])],'inputs':fields,'api_candidates':candidates,'device_operations':device_calls,'entry_path':KNOWN_ENTRIES.get(route['name'],[]),'entry_status':'source_candidate_requires_runtime_confirmation','return':{'action':'back','intercepted':blocked_back,'may_save':saves_on_back,'source':source},'save_controls':[v for v in labels(text) if any(re.search(r'保存|提交|save|submit',label,re.I) for label in v['labels'])]})
    ownership={}
    for page in pages:
        seen={page['source']};frontier=[page['source']]
        for _ in range(2):
            new=[]
            for file in frontier:
                for target in imports(file):
                    if target in files and '/widgets/' in target and target not in seen:seen.add(target);new.append(target)
            frontier=new
        ownership[page['path']]=seen
    by_route={page['path']:page for page in pages}
    for page in pages:
        page['entry_candidates']=[{'steps':page['entry_path'],'evidence':[],'status':'static_known_pattern'}] if page['entry_path'] else []
    for _ in range(6):
        changed=False
        for edge in navigation['entries']:
            active_lines=files.get(edge['source'],'').splitlines()
            if edge['line']>len(active_lines) or not re.search(r'Get\.(?:toNamed|offNamed|offAllNamed)\(',active_lines[edge['line']-1]):continue
            target=by_route.get(edge['route'])
            chinese=locale_packs.get('zh',{})
            choices=[chinese[key] for key in edge.get('label_keys',[]) if isinstance(chinese.get(key),str)] or [label for label in edge['labels'] if re.search(r'[\u4e00-\u9fff]',label)]
            if not target or not choices or target['entry_candidates']:continue
            label=choices[0]
            for parent in pages:
                if edge['source'] not in ownership[parent['path']] or parent['path']==target['path']:continue
                base=parent['entry_candidates'][0]['steps'] if parent['entry_candidates'] else None
                if parent['path'].startswith('/main'):
                    section='我的' if re.search(r'mine|/my|_my',edge['source']) else '消息' if re.search(r'msg|message',edge['source']) else '门店' if 'store' in edge['source'] else '首页'
                    base=[section]
                if base is not None and len(base)<7:
                    target['entry_candidates']=[{'steps':base+[label],'evidence':[{'source':edge['source'],'line':edge['line'],'route':edge['route']}],'status':'static_graph_candidate'}]
                    changed=True;break
        if not changed:break
    web_return=next((p['return'] for p in pages if p['path']=='/webview'),{'action':'back','intercepted':True,'may_save':False,'source':'lib/widgets/webview/webview_page.dart'})
    recipes=[
        ('pageMineFix','mine_fix',['首页','报修'],'lib/widgets/main/widget/fun_list_widget.dart',['报修']),
        ('pageShop','title_shop',['首页','附近门店'],'lib/widgets/main/widget/fun_list_widget.dart',['附近门店']),
        ('pageSurveyTool','survey_tool',['首页','勘察工具'],'lib/widgets/main/widget/fun_list_widget.dart',['勘察工具']),
        ('pageCreateStore','create_store',['首页','创建门店'],'lib/widgets/main/widget/fun_list_widget.dart',['创建门店']),
        ('pageOrderCenter','order_center',['首页','订单中心'],'lib/widgets/main/widget/fun_list_widget.dart',['订单中心']),
        ('pageTaskRecord','task_record',['首页','任务记录'],'lib/widgets/main/widget/fun_list_widget.dart',['任务记录']),
        ('pageRunReport','run_report',['首页','运行报告'],'lib/widgets/main/widget/fun_list_widget.dart',['运行报告','运行报表']),
        ('pageLearingCenter','title_study',['首页','学习中心'],'lib/widgets/main/widget/fun_list_widget.dart',['学习中心']),
        ('pagePolicy','privacy_policy',['我的','关于','更多','隐私政策','查看协议'],'lib/widgets/about/more_page.dart',['隐私政策','隐私协议']),
        ('pagePrivacySummary','privacy_summary',['我的','关于','更多','隐私政策摘要'],'lib/widgets/about/more_page.dart',['隐私摘要','隐私政策摘要']),
        ('pageAgreement','user_agreement',['我的','关于','更多','用户协议'],'lib/widgets/about/more_page.dart',['用户协议']),
        ('pagePersonalInformation','personal_information',['我的','关于','更多','个人信息收集清单'],'lib/widgets/about/more_page.dart',['个人信息收集清单']),
        ('pageThirdPartyInformation','third_party_information',['我的','关于','更多','第三方信息共享清单'],'lib/widgets/about/more_page.dart',['第三方信息共享清单']),
        ('pageAppPermission','app_permission',['我的','关于','更多','应用权限申请与使用情况说明'],'lib/widgets/about/more_page.dart',['应用权限申请与使用情况说明']),
    ]
    for constant,key,entry,file,terms in recipes:
        match=re.search(r'WebUtil\.webLoadByPage\(PageConst\.'+constant+r'\b',files.get(file,''))
        if not match or key not in translations:continue
        pages.append({'name':constant,'path':'/webview','page':'WebViewPage / '+constant,'kind':'h5_entry','source':file,'labels':[{'key':key,'labels':list(dict.fromkeys(terms+translations[key]))}],'title_labels':terms,'inputs':[],'api_candidates':[],'entry_path':entry,'entry_candidates':[{'steps':entry,'evidence':[{'source':file,'line':files[file].count('\n',0,match.start())+1,'call':'WebUtil.webLoadByPage(PageConst.'+constant+')'}],'status':'source_h5_entry_candidate'}],'entry_status':'h5_internal_controls_require_runtime_inspection','return':web_return,'save_controls':[]})
    success=re.search(r'static\s+const\s+int\s+success\s*=\s*(\d+)',files.get('lib/http/http_exception.dart',''))
    for page in pages:
        page['automation_targets']=stable_identifiers.flutter_targets(page['source'],identifiers,class_sources)
    codes=[int(success[1])] if success else []
    if re.search(r'resultModel\.code\s*==\s*0',files.get('lib/http/dio_util.dart','')):codes.append(0)
    return {'project':str(project),'pages':pages,'api_calls':calls,'translations':translations,'locale_packs':locale_packs,'navigation':navigation,'business_success_codes':codes,'coverage_note':'源码静态关联是候选路径，实际控件、角色和接口调用必须在运行时确认。'}

def compile_form(case,index):
    """Compile a complete small form only with a unique page, input and write API."""
    if not index:return None
    pre=re.sub(r'【\d+】','',case.get('precondition','')).strip()
    match=re.fullmatch(r'(?:已)?在(.+?)页面',pre)
    if not match:return None
    pages=[p for p in index['pages'] if match[1] in p.get('title_labels',[]) and p['entry_path']]
    if len(pages)!=1:return None
    page=pages[0]
    split=lambda text:[v.strip().rstrip('。') for v in re.split(r'【\d+】|\n',text) if v.strip()]
    actions=split(case['steps']);expected=split(case['expected'])
    if len(actions)!=len(expected) or len(actions)<2:return None
    steps=[{'action':'tap','value':label} for label in page['entry_path']]+[{'action':'assert_route','value':page['path']}]
    has_input=False;has_save=False
    for action,outcome in zip(actions,expected):
        field=re.fullmatch(r'(?:在|向)[“"](.+?)[”"](?:中)?(?:输入|填写)[“"](.+?)[”"]',action)
        save=re.fullmatch(r'点击[“"]?(保存|提交)[”"]?(?:按钮)?',action)
        if field:
            label,value=field.groups()
            matching=[f for f in page['inputs'] if any(label==text or label==re.sub(r'^(?:请输入|请填写|输入)','',text) for item in f['labels'] for text in item['labels'])]
            if len(matching)!=1 or http_probe_sensitive(label):return None
            if outcome not in ('输入成功','填写成功','显示“'+value+'”','显示"'+value+'"'):return None
            steps.extend([{'action':'input','value':label,'text':value},{'action':'assert_input','value':label,'text':value}]);has_input=True
        elif save:
            writes=[a for a in page['api_candidates'] if a['http_method'] in ('POST','PUT','PATCH')]
            writes=list({(a['http_method'],a['path']):a for a in writes}.values())
            if len(writes)!=1 or outcome not in ('保存成功','提交成功') or not page['save_controls'] or not index['business_success_codes']:return None
            api=writes[0]
            steps.append({'action':'save','value':save[1],'api':{'path':api['path'],'method':api['http_method'],'codes':index['business_success_codes']}});has_save=True
        else:return None
    return {'steps':steps} if has_input and has_save else None

def http_probe_sensitive(label):
    return bool(re.search(r'密码|验证码|账号|手机|邮箱|password|token|secret|account|phone|email',label,re.I))

def draft(case,index=None):
    context=' | '.join(case.get(k,'') for k in ('module','group','title','precondition'))
    leaf=case.get('group','').split('|')[-1]
    destinations=re.findall(r'(?:移到|跳转到|进入)([^，,。\n]+?)(?:页面|页)',case.get('title',''))
    destination=re.split(r'[-/|]',destinations[-1])[-1].strip('“”"【】 ') if destinations else ''
    matches=[]
    for page in (index or {}).get('pages',[]):
        labels=[value for item in page['labels'] for value in item['labels']]
        generic={'我的','首页','账号','密码','确定','取消','保存','返回','下一步'}
        hits=[value for value in labels if len(value)>=2 and value in context and (value not in generic or value==leaf)]
        if hits:
            exact=any(label==leaf for label in page.get('title_labels',[]))
            entry=page.get('entry_path',[])
            moved=bool(destination and entry and entry[-1]==destination)
            matches.append((max(len(v) for v in hits)+(100 if exact else 0)+(40 if moved else 0),page,hits))
    matches.sort(key=lambda x:x[0],reverse=True)
    candidates=[{**{k:page.get(k,[]) for k in ('name','path','page','source','inputs','api_candidates','entry_path','entry_candidates','entry_status','return','save_controls')},'matched_labels':hits} for score,page,hits in matches[:4]]
    explicit=re.findall(r'(?:输入|填写)[“"\[]([^”"\]\n]+)[”"\]]',case.get('steps',''))
    needs_save=bool(re.search(r'保存|提交|点击确认|点击完成',case.get('steps','')))
    dependencies=[]
    for pattern,reason in [(r'机器人|机型|资源包','需指定测试门店、机器人及资源包状态'),(r'云端|后台|数据库|运营端','需配置或核对后台数据'),(r'不同账号|店长|店员|代理商|销售角色','需匹配角色及权限'),(r'验证码|扫码|微信','需验证码、扫码或第三方联动'),(r'昨日|前日|准确|一致|统计','需可信数据基线，不能仅检查文字存在')]:
        if re.search(pattern,context+' '+case.get('expected','')):dependencies.append(reason)
    api_candidates=list({(a['http_method'],a['path']):a for p in candidates for a in p['api_candidates']}.values())
    actions=[]
    for number,step in enumerate([s.strip() for s in re.split(r'【\d+】|\n',case.get('steps','')) if s.strip()],1):
        kind='input' if re.search(r'输入|填写',step) else 'save_and_assert_api' if re.search(r'保存|提交|点击确认|点击完成',step) else 'return' if '返回' in step else 'tap' if '点击' in step else 'observe'
        actions.append({'number':number,'type':kind,'description':step,'status':'needs_binding' if kind in ('input','save_and_assert_api') else 'needs_runtime_confirmation'})
    entry=candidates[0]['entry_candidates'][0]['steps'] if candidates and candidates[0]['entry_candidates'] else []
    return {'id':case['id'],'sheet':case['sheet'],'row':case['row'],'title':case['title'],'module':case.get('module',''),'group':case.get('group',''),'priority':case.get('priority',''),'scope':'mobile' if case['mobile'] else 'excluded','page_candidates':candidates,'entry_path':entry,'original_preconditions':case.get('precondition',''),'input_values_from_case':explicit,'inputs':candidates[0]['inputs'] if candidates else [],'actions':actions,'save_required':needs_save,'api_candidates':api_candidates,'api_assertion_policy':{'http':'2xx','business_codes':(index or {}).get('business_success_codes',[610000,0]),'must_start_after_action':True,'require_exact_endpoint_and_method':True,'http_200_alone_is_not_pass':True},'return_path':candidates[0]['return'] if candidates else {'action':'back','status':'需运行时确认'},'original_steps':case.get('steps',''),'original_expected':case.get('expected',''),'data_dependencies':dependencies,'unresolved':['入口候选需由实际页面与路由确认']+([] if entry else ['尚未找到入口候选'])+(['保存接口需从候选中绑定到具体按钮，不能任意选择'] if needs_save else []),'status':'draft_not_execution_proof'}

def build(book,index=None):
    return {'source_project':(index or {}).get('project'),'note':'每条流程保留原用例、源码证据和未确认项；草稿不计为已执行。','flows':[draft(c,index) for c in book['cases'] if c['mobile']]}

def markdown(document):
    lines=['# 手机用例操作流程草稿','',document['note'],'','候选路径来自源码静态分析，需由实际页面、路由及接口观察确认。H5 内部页面和浏览器请求不在原生 Dio 观察范围内。','']
    for flow in document['flows']:
        lines+=['## '+flow['id']+' · '+flow['title'],'','- 功能分组：'+flow['group'],'- 入口候选：'+(' → '.join(flow['entry_path']) or '待确认')]
        for page in flow['page_candidates'][:2]:lines.append('- 页面候选：`'+page['path']+'` / '+page['page']+'；源码 `'+page['source']+'`')
        lines+=['- 前置条件：'+(flow['original_preconditions'].replace('\n','；') or '原用例未提供'),'','操作顺序（尚需绑定控件和数据）：','']
        for action in flow['actions']:lines.append(str(action['number'])+'. '+action['description'])
        lines+=['','预期结果：'+flow['original_expected'].replace('\n','；'),'']
        if flow['save_required']:
            writes=[a for a in flow['api_candidates'] if a['http_method'] in ('POST','PUT','PATCH')]
            lines.append('保存接口候选：'+('；'.join('`'+a['http_method']+' '+a['path']+'`（'+a['source']+':'+str(a['line'])+'）' for a in writes) or '待确认，不能凭页面提示判断接口成功'))
            lines.append('验证：匹配操作窗口之后发起的具体接口，核对 HTTP 状态、业务码及指定返回字段。')
        return_path=flow['return_path']
        lines.append('返回：'+('源码显示返回会触发保存，需绑定保存接口后执行。' if return_path.get('may_save') else '实际返回按钮与路径仍需运行时确认。'))
        lines+=['待确认：'+'；'.join(flow['unresolved']+flow['data_dependencies'] or ['静态候选不等于已执行通过']),'']
    return '\n'.join(lines)


def ai_summary(index,outline,max_chars=30000,language=None):
    """Keep relevant control labels and navigation; never cut JSON mid-object."""
    routes=index.get('navigation',{}).get('routes',[])
    paths={r['name']:r['path'] for r in routes}
    requested=set(re.findall(r'/[A-Za-z0-9_/-]+',outline));explicit=requested.copy()
    if re.search(r'首次启动|登录前|启动App|启动应用',outline,re.I):requested.add('/loginConfig')
    if re.search(r'账号密码登录|输入[^。\n]{0,20}账号|登录页',outline):requested.add('/login')
    if re.search(r'我的[^。\n]{0,40}语言|通用设置[^。\n]{0,20}语言',outline):requested.update(('/language','/my/currency'))
    auth_focus=any(path.lower().startswith('/login') for path in requested) or bool(re.search(r'首次启动|登录前|登录页|账号密码登录|输入[^。\n]{0,20}(?:账号|密码)',outline))
    if '我的' in outline and any(p.get('path')=='/main' for p in index['pages']):requested.add('/main')
    def local_labels(value):
        if isinstance(value,list):return [local_labels(v) for v in value]
        if not isinstance(value,dict):return value
        result={k:local_labels(v) for k,v in value.items()}
        if (value.get('key') or value.get('label_key')) and 'labels' in value and index.get('locale_packs'):
            key=value.get('key') or value['label_key'];packs=index['locale_packs'];langs=list(dict.fromkeys(['zh','en',language]))
            result['labels']=list(dict.fromkeys(packs.get(lang,{}).get(key) for lang in langs if isinstance(packs.get(lang,{}).get(key),str))) or value['labels'][:2]
        return result
    def score(page):
        labels=[s for item in page.get('labels',[]) for s in item.get('labels',[])]
        value=sum(3 for s in labels if len(s)>1 and s.casefold() in outline.casefold())
        if page.get('kind')=='h5_entry' and value:value+=500
        if page.get('path') in requested:value+=10000
        if page.get('path') in explicit:value+=20000
        if page.get('name') and re.search(r'\b'+re.escape(page['name'])+r'\b',outline,re.I):value+=100
        if auth_focus and '登录' in outline and page.get('path','').lower().startswith('/login'):value+=1000
        if auth_focus and page.get('path')=='/loginConfig' and re.search(r'登录前|配置页|国家或区域|国家或地区|数据中心选择',outline):value+=5000
        if auth_focus and page.get('path')=='/login' and re.search(r'登录页|账号|密码|协议',outline):value+=4000
        return value
    details=[]
    project=Path(index['project']).resolve()
    for page in sorted(index['pages'],key=score,reverse=True)[:20]:
        item={k:page.get(k) for k in ('name','path','source','kind','entry_status','title_labels','labels','entry_path','entry_candidates','inputs','api_candidates','device_operations','return','save_controls')}
        # Keep the most useful identities (inputs first) without crowding the
        # other requested pages out of a multi-page evidence summary.
        if page.get('automation_targets'):item['automation_targets']=page['automation_targets'][:2]
        source=project/str(page.get('source',''))
        text=without_comments(source.read_text(errors='replace')) if source.is_file() and project in source.resolve().parents else ''
        item['local_state_evidence']={
            'preference_keys':list(dict.fromkeys(re.findall(r'SpUtil\.put\w+\(\s*SPKey\.(\w+)',text))),
            'navigation_targets':[{'method':m[0],'route_name':m[1],'path':paths.get(m[1])} for m in re.findall(r'Get\.(toNamed|offNamed|offAllNamed)\(Routers\.(\w+)',text)],
            'selection_fields':[{'label_key':key,'labels':index.get('translations',{}).get(key,[key])} for key in re.findall(r"_selectionField\(\s*label:\s*['\"]([^'\"]+)['\"]\.tr",text)],
            'note':'仅静态证据；本地选项切换不等于远端写接口，选中值与页面跳转仍需运行时断言'}
        if page.get('path')=='/loginConfig' and 'if (!controller.canContinue)' in text:
            item['local_state_evidence']['next_button_validation']={
                'button_has_callback':'onPressed: ()' in text,
                'when_incomplete':'点击后触发select_country_data_center_tip提示并return；不能推断为disabled',
                'tip_labels':index.get('translations',{}).get('select_country_data_center_tip',[])[:2],
                'when_complete':'controller.save()后导航登录页；持久化正确值仍需运行时验证'}
        if page.get('path')=='/loginConfig':
            manager=project/'lib/manager/data_center_manager.dart';cache_file=project/'lib/utils/data_cache.dart';country_file=project/'lib/utils/country_names.dart'
            manager_text=without_comments(manager.read_text()) if manager.is_file() else ''
            item['local_state_evidence']['data_center_options']=[{'link_id':int(n),'key':key,'labels':list(dict.fromkeys(index.get('locale_packs',{}).get(lang,{}).get(key) for lang in ('zh','en',language) if isinstance(index.get('locale_packs',{}).get(lang,{}).get(key),str)))} for n,key in re.findall(r"case (\d+):\s*return '([^']+)'\.tr",manager_text)]
            cache_text=cache_file.read_text() if cache_file.is_file() else ''
            item['local_state_evidence']['language_options']=[{'name':n,'locale':lang+'_'+country} for n,lang,country in re.findall(r"Language\('([^']+)',\s*'([^']+)',\s*'([^']+)'\)",cache_text)]
            item['local_state_evidence']['country_CN_labels']=list(dict.fromkeys(re.findall(r'"CN":\s*"([^"\n]+)"',country_file.read_text()))) if country_file.is_file() else []
            item['local_state_evidence']['options_note']='选项名称来自该页面依赖的管理器和本地字典；是否对当前环境可用在设备上唯一匹配验证，不代表云端一定返回。'
        if page.get('path')=='/language' and 'DataCache.getAvailableLanguageList' in text:
            cache_file=project/'lib/utils/data_cache.dart'
            cache_text=cache_file.read_text() if cache_file.is_file() else ''
            item['local_state_evidence']['language_options']=[{'name':n,'locale':lang+'_'+country} for n,lang,country in re.findall(r"Language\('([^']+)',\s*'([^']+)',\s*'([^']+)'\)",cache_text)]
            item['local_state_evidence']['availability']='语言项由CloudLanguageService.availableLanguageCodes过滤；准确选项名称是候选，当前云端是否开放必须运行时核对。'
        details.append(item)
    details=[local_labels(p) for p in details]
    selected_paths={p['path'] for p in details}
    edges=[{k:e.get(k) for k in ('route','labels','source','line')} for e in index.get('navigation',{}).get('entries',[]) if e.get('route') in selected_paths][:40]
    while edges and len(json.dumps(edges,ensure_ascii=False))>max_chars//5:edges.pop()
    result={'pages':details,'navigation_entries':edges,'business_success_codes':index.get('business_success_codes',[]),'route_overview':[{k:p.get(k) for k in ('name','path','source')} for p in index['pages']],
            'note':'登录前配置与登录后我的/数据中心是不同页面；源码准确文字可用于候选定位，运行时验证唯一性。'}
    # Remove broad indexes before the very controls that the current cases need.
    if len(json.dumps(result,ensure_ascii=False))>max_chars:result['route_overview']=[]
    if len(json.dumps(result,ensure_ascii=False))>max_chars:result['navigation_entries']=[]
    # Give every explicitly requested route its evidence before optional pages.
    # Never silently remove APIs/navigation: that turns budget pressure into a
    # false "source has no evidence" result.
    ordered=details[:];details.clear()
    for item in ordered:
        details.append(item)
        if len(json.dumps(result,ensure_ascii=False))<=max_chars:continue
        details.pop()
        if item.get('path') in requested or not details:
            compact=dict(item)
            needed={v.get('key') for field in item.get('inputs') or [] for v in field.get('labels',[])}
            compact['labels']=[label for label in item.get('labels') or [] if label.get('key') in needed or any(s in outline for s in label.get('labels',[]))]
            details.append(compact)
            if len(json.dumps(result,ensure_ascii=False))>max_chars:
                if item.get('path') in requested:raise EvidenceBudgetExceeded('目标页面入口、字段与接口证据超过摘要大小，请逐条匹配；未丢弃关键证据')
                details.pop()
    if not details and ordered:details.append(ordered[0])
    if len(json.dumps(result,ensure_ascii=False))>max_chars:raise EvidenceBudgetExceeded('当前页面证据超过摘要大小，请缩小用例范围；未发送缺失控件的空摘要')
    return result
