"""Keenon login/configuration/language/logout regression with runtime assertions."""
import json,re,time
from pathlib import Path
from xml.etree import ElementTree as ET
import automation,login_flow,popup_handler

PHASES=('configure','login','language_page','language_switch','language_all','logout')
LANGUAGE_PHASES={'language_switch','language_all','language_all_full','language_all_restore','language_all_full_restore','language_persistence','language_persistence_zh','language_restore_logout'}


def valid_sequence(phases):
    middle=lambda ps:all(p=='language_page' or p in LANGUAGE_PHASES for p in ps)
    if len(phases)>=5 and tuple(phases[:3])==('configure','login','language_page'):
        return phases[-1] in {'logout','logout_relogin'} and middle(phases[3:-1])
    # Merged outlines: 进入语言页/切换语言等阶段可并入语言用例，恢复中文可与退出合并。
    return (len(phases)>=4 and tuple(phases[:2])==('configure','login')
            and phases[-1] in {'logout','logout_relogin','language_restore_logout'} and middle(phases[2:-1]))


def resolve_phases(document):
    """Resolve supported capabilities from business actions, not case numbers."""
    cases=document.get('cases',[])
    if not isinstance(cases,list) or not 1<=len(cases)<=30:return None
    phases=[]
    for case in cases:
        actions=' '.join(s.get('action','') for s in case.get('business_steps',[])) or case.get('description','')
        text=case.get('title','')+' '+actions
        if '退出' in text and ('登录' in text or '账号' in text):
            if re.search(r'(?:恢复|选(?:择)?回|切(?:换)?回|改回|设(?:置)?回|选(?:择)).{0,8}中文',text):
                phase='language_restore_logout'
            else:
                relogin=any(re.search(r'(?:重新|再次).{0,40}登录',step.get('action','')) and ('输入' in step.get('action','') or re.search(r'登录成功|进入首页',step.get('expected',''))) for step in case.get('business_steps',[]))
                phase='logout_relogin' if relogin else 'logout'
        elif '数据中心' in text and '中国' in text and '中文' in text and any(v in text for v in ('登录前','登录配置','国家')):phase='configure'
        elif '密码' in text and '登录' in text:phase='login'
        elif '语言' in text:
            selection=bool(re.search(r'选择|选取|切换',actions))
            all_requested=selection and bool(re.search(r'依次|逐[一种个项]|每.{0,3}种|其余|剩余|全部',text))
            restore=bool(re.search(r'(?:恢复|选(?:择)?回|切(?:换)?回|改回|设(?:置)?回).{0,8}中文',actions))
            if all_requested:
                phase='language_all' if 'language_switch' in phases else 'language_all_full'
                if restore:phase+='_restore'
            elif selection and any(v in text for v in ('英文','英语','English','另一种','其他语言')):phase='language_switch'
            elif ('返回' in actions and any(v in actions for v in ('再次','重新'))) or '全局' in text:
                chinese=bool(re.search(r'(?:恢复|保持|选中|当前).{0,8}中文',case.get('precondition','')+' '+case.get('expected','')))
                phase='language_persistence_zh' if chinese else 'language_persistence'
            elif '通用设置' in text and '我的' in text:phase='language_page'
            else:return None
        else:return None
        phases.append(phase)
    return phases if valid_sequence(phases) else None


def classify(document):return resolve_phases(document) is not None


def adapt(document,index):
    phases=resolve_phases(document)
    if phases is None:return None
    paths={p['path'] for p in index.get('pages',[])}
    if not {'/loginConfig','/login','/language'}.issubset(paths):return None
    for case,phase in zip(document['cases'],phases):
        operation={'action':'workflow_case','value':phase}
        case.update(plan={'requires':[],'steps':[operation]},blocked_reason='')
        notes=case.setdefault('adaptation_notes',[])
        if phase=='configure':
            for step in case['business_steps']:
                if '高亮' in step['expected']:
                    step['expected']='选择后返回配置页，“中国”回显为当前国家，国家配置已保存。'
                    notes.append('国家列表选择后会关闭，按配置页回显和持久化值验证，不要求列表保留高亮。')
                if ('启动' in step['action'] or '查看页面' in step['action']) and '中文' in step['expected']:
                    step['expected']='页面展示国家/地区、数据中心、语言及下一步入口，初始文案随当前语言显示。'
                    notes.append('中文显示在选择中文后验证，初始页可随系统或已保存语言显示。')
        if phase=='login' and '呼叫' in case['expected'] and any(v in case['expected'] for v in ('底部','导航')):
            notes.append('底部导航随账号角色而不同，本登录流程按首页及登录态验证，不把“呼叫”固定当作登录成功条件。')
            case['expected']=re.sub(r'，?底部(?:导航)?(?:展示|显示).*?(?:。|$)','，可进入“我的”页面。',case['expected'])
            for step in case['business_steps']:
                if '呼叫' in step['expected'] and any(v in step['expected'] for v in ('底部','导航')):
                    step['expected']=re.sub(r'，?底部(?:导航)?(?:展示|显示).*?(?:。|$)','，可进入“我的”页面。',step['expected'])
        if phase in {'logout','logout_relogin','language_restore_logout'} and any('账号管理' in s['action'] for s in case['business_steps']):
            notes.append('源码退出入口为“我的→退出账号”，账号管理页不含退出入口，已按实际路径修正。')
            for step in case['business_steps']:
                if '我的' in step['action'] and '通用设置' in step['action']:
                    step.update(action='返回“我的”页面，查看账户功能入口。',expected='我的页面正常展示。')
                elif '账号管理' in step['action']:
                    step.update(action='在“我的”页面找到“退出账号”入口。',expected='我的页面展示退出账号入口。')
                elif '退出登录' in step['action'] and '确认' not in step['action']:
                    step['action']='点击“退出账号”。'
        if phase=='language_restore_logout':
            notes.append('已合并执行：先进入语言设置页恢复中文并验证，再按专用退出流程退出账号。')
        if phase=='logout_relogin':
            notes.append('按末步验证退出后再次登录；验证后再次退出，最终保持整体预期的未登录状态。' if relogin_cleanup(case) else '按末步验证退出后再次登录，最终保持已登录状态。')
        case['description']='\n'.join(str(i)+'. '+step['action'] for i,step in enumerate(case['business_steps'],1))
        case['adaptation_notes']=list(dict.fromkeys(notes))
        for step in case['business_steps']:
            step.update(automation_status='candidate',automation_reason='',automation_steps=[dict(operation)])
    return document


def phases_for_book(book):
    values=[]
    for case in book.get('cases',[]):
        try:p=json.loads(case.get('plan_text',''))
        except (ValueError,TypeError):return None
        steps=p.get('steps',[])
        if len(steps)!=1 or steps[0].get('action')!='workflow_case':return None
        values.append(steps[0].get('value'))
    return values if valid_sequence(values) else None


def applies(book):return phases_for_book(book) is not None


def relogin_cleanup(case):
    expected=case.get('expected','')
    return '未登录' in expected and not re.search(r'最终.{0,6}已登录|保持.{0,3}已登录',expected)


def upgrade_bound_plan(document):
    expected=resolve_phases(document)
    if expected is None:return document
    current=[]
    for case in document['cases']:
        steps=(case.get('plan') or {}).get('steps',[])
        if len(steps)!=1 or steps[0].get('action')!='workflow_case':return document
        current.append(steps[0].get('value'))
    allowed={('language_all','language_all_restore'),('language_all_full','language_all_full_restore'),('logout','logout_relogin')}
    for case,old,new in zip(document['cases'],current,expected):
        if old==new:continue
        if (old,new) not in allowed:raise ValueError('专用执行计划与业务步骤不一致，请重新匹配自动化步骤')
        case['plan']['steps'][0]['value']=new
        for step in case.get('business_steps',[]):
            for operation in step.get('automation_steps',[]):
                if operation.get('action')=='workflow_case' and operation.get('value')==old:operation['value']=new
        note='已按原业务步骤补齐全部语言验证后的恢复中文。'
        if new=='logout_relogin':note='已补齐退出后的再次登录验证；验证后再次退出，最终保持未登录。' if relogin_cleanup(case) else '已补齐退出后的再次登录验证，最终保持已登录。'
        case.setdefault('adaptation_notes',[]).append(note)
    return document


def instrument(project):
    file=Path(project)/'lib/widgets/currency/language_setting.dart'
    text=file.read_text();start=text.index('class _LanguageItemWidget ')
    head,tail=text[:start],text[start:]
    if 'devicecheck-language-' in tail:return
    if 'return Container(' not in tail:raise ValueError('语言控件源码结构变化，无法添加选中状态证据')
    tail=tail.replace('return Container(',"return Semantics(selected: selected, label: 'devicecheck-language-${language.language}-${language.country}', child: Container(",1)
    tail=tail.replace('    );\n  }\n}', '    ));\n  }\n}',1)
    file.write_text(head+tail)
    state=Path(project)/'lib/manager/user_manager.dart'
    content=state.read_text()
    helper="""
  void _devicecheckSessionState() {
    try { File('${Directory.systemTemp.path}/devicecheck-session-state.json').writeAsStringSync(jsonEncode({'token_present': userToken.isNotEmpty, 'user_info_present': userInfo != null})); } catch (_) {}
  }
"""
    if '_devicecheckSessionState' not in content:
        content="import 'dart:io';\nimport 'dart:convert';\n"+content
        marker='  void cacheUserInfo(UserInfoBean userInfoBean) {'
        if marker not in content or '    userToken = token.token;' not in content:raise ValueError('登录态源码结构变化，无法添加布尔状态证据')
        content=content.replace(marker,helper+marker,1)
        content=content.replace('    userInfo = userInfoBean;','    userInfo = userInfoBean;\n    _devicecheckSessionState();',1)
        content=content.replace('    userToken = token.token;','    userToken = token.token;\n    _devicecheckSessionState();',1)
        content=content.replace('    await SpUtil.remove(SPKey.loginProduct);','    await SpUtil.remove(SPKey.loginProduct);\n    _devicecheckSessionState();')
        state.write_text(content)


class Workflow:
    def __init__(self,explorer,project,capture,sleep=time.sleep):
        self.e=explorer;self.project=Path(project);self.capture=capture;self.sleep=sleep;self.events=[];self.shots=[]
        text=(self.project/'lib/utils/data_cache.dart').read_text()
        self.languages=[{'name':n,'lang':l,'country':c,'locale':l+'_'+c} for n,l,c in re.findall(r"Language\('([^']+)',\s*'([^']+)',\s*'([^']+)'\)",text)]
        self.catalog={v['name']:v for v in self.languages};self.chosen=None
        country_file=self.project/'lib/utils/country_names.dart'
        names=re.findall(r'"CN":\s*"([^"\n]+)"',country_file.read_text()) if country_file.is_file() else []
        self.china_names=login_flow.CHINA | {login_flow.normalized(n) for n in names}

    def nodes(self):
        deadline=time.monotonic()+20
        while True:
            if self.e.stopped():raise RuntimeError('用户已停止')
            nodes=automation.parse_ui(self.e.wait_ui())
            if any(n['package']==self.e.app_package for n in nodes):return nodes
            permission,_=popup_handler.permission_target(nodes)
            if permission:
                self.e.tap(permission);self.sleep(.6)
            if time.monotonic()>=deadline:raise RuntimeError('等待被测 App 页面就绪超时，当前只能读取其他窗口')
            self.sleep(.4)

    def prefs(self):
        package=self.e.app_package
        if not re.fullmatch(r'[\w.]+',package):raise RuntimeError('无效包名')
        result=self.e.shell(['run-as',package,'cat','/data/user/0/'+package+'/shared_prefs/FlutterSharedPreferences.xml'])
        if not result['ok']:raise RuntimeError('无法读取测试包的本地状态证据，请使用 debug 测试副本')
        values={n.attrib.get('name','').removeprefix('flutter.'):n.text or '' for n in ET.fromstring(result['output'])}
        try:center=json.loads(values.get('selected_data_center','{}'))
        except ValueError:center={}
        session=self.e.shell(['run-as',package,'cat','/data/user/0/'+package+'/code_cache/devicecheck-session-state.json'])
        try:state=json.loads(session['output']) if session['ok'] else {}
        except ValueError:state={}
        return {'locale':values.get('selected_locale',''),'country':values.get('selected_country',''),
                'center_country':center.get('iso2','') if isinstance(center,dict) else '',
                'state_observed':type(state.get('token_present')) is bool and type(state.get('user_info_present')) is bool,
                'token_present':state.get('token_present',False),'user_info_present':state.get('user_info_present',False)}

    def record(self,label,proof):
        self.e.log('断言通过：'+label)
        self.events.append({'number':len(self.events)+1,'action':'check','check':label,'status':'pass','evidence':proof})
        source=self.e.source()
        if not any(n['secure'] or n['editable'] for n in automation.parse_ui(source)):
            shot=self.capture('language-workflow-'+str(len(self.events))+'-'+str(time.monotonic_ns()),source)
            if shot:self.shots.append(shot)

    def matching(self,nodes,text,clickable=False):
        return [n for n in nodes if (not clickable or n['clickable']) and text in [v.strip() for v in n['label'].splitlines()]]

    def tap(self,text,scroll=False):
        for _ in range(14 if scroll else 1):
            nodes=self.nodes();matches=self.matching(nodes,text,True)
            unique={n['bounds']:n for n in matches}
            if len(unique)==1:self.e.tap(next(iter(unique.values())));self.sleep(.6);return
            if len(unique)>1:raise RuntimeError('控件不唯一：'+text)
            if not scroll or not self.scroll('down'):break
        raise AssertionError('未找到可点击控件：'+text)

    def scroll(self,direction):
        nodes=self.nodes();bounds=[list(map(int,re.findall(r'\d+',n['bounds']))) for n in nodes if n['bounds']]
        width=max(b[2] for b in bounds);height=max(b[3] for b in bounds)
        more=self.e.call('POST',self.e.base+'/execute/sync',{'script':'mobile: scrollGesture','args':[{'left':20,'top':int(height*.28),'width':width-40,'height':int(height*.6),'direction':direction,'percent':.8}]})
        self.sleep(.35)
        return more

    def top(self):
        for _ in range(15):
            if not self.scroll('up'):return
        raise RuntimeError('语言列表无法回到顶部')

    def field(self,labels):
        nodes=self.nodes();found=[n for n in nodes if n['label'] in labels]
        if len(found)!=1:raise RuntimeError('配置字段标识未唯一匹配：'+str(labels))
        b=list(map(int,re.findall(r'\d+',found[0]['bounds'])));bottom=b[3]
        choices=[]
        for n in nodes:
            if not n['clickable']:continue
            box=list(map(int,re.findall(r'\d+',n['bounds'])))
            if len(box)==4 and box[1]>=bottom and box[1]-bottom<220:choices.append((box[1],n))
        if not choices:raise RuntimeError('未找到配置字段的选项入口')
        choices.sort(key=lambda x:x[0]);self.e.tap(choices[0][1]);self.sleep(.6)

    def route(self,path):
        reader=getattr(self.e,'route_reader',None)
        if not reader:raise AssertionError('未启用页面路由观察器')
        deadline=time.monotonic()+30
        while reader.read()!=path:
            if self.e.stopped():raise RuntimeError('用户已停止')
            if time.monotonic()>=deadline:raise AssertionError('等待页面切换超时，预期路由 '+path)
            self.sleep(.4)

    def text(self,key,locale=None):
        locale=locale or self.prefs()['locale'];lang=locale.split('_')[0]
        file=self.project/'assets/i18n'/(lang+'.json')
        if not file.is_file():raise RuntimeError('该语言缺少可核对的文案基线：'+lang)
        value=json.loads(file.read_text()).get(key)
        if not isinstance(value,str) or not value:raise RuntimeError('文案基线缺少 '+key)
        return value

    def verify_copy(self,kind):
        file=self.project/('lib/widgets/mine/mine_info_home.dart' if kind=='mine' else 'lib/widgets/currency/currency_setting.dart')
        keys=set(re.findall(r"['\"]([^'\"]+)['\"]\.tr",file.read_text()))
        dictionaries=[json.loads(p.read_text()) for p in (self.project/'assets/i18n').glob('*.json')]
        locale=self.prefs()['locale'];target=json.loads((self.project/'assets/i18n'/(locale.split('_')[0]+'.json')).read_text())
        labels={line.strip() for node in self.nodes() for line in node['label'].splitlines() if line.strip()}
        if any('\ufffd' in label for label in labels):raise AssertionError('可见菜单出现字符替换符，疑似乱码')
        checked=[]
        for key in keys:
            expected=target.get(key)
            variants={d[key] for d in dictionaries if isinstance(d.get(key),str)}
            visible=labels & variants
            if visible and isinstance(expected,str):
                if visible!={expected}:raise AssertionError('可见菜单文案与所选语言不一致：'+key)
                checked.append(key)
        if not checked:raise AssertionError('没有可核对的页面菜单文案')
        self.record('页面可见菜单文案验证',{'page':kind,'locale':locale,'keys':sorted(checked)})

    def assert_text(self,text):
        deadline=time.monotonic()+6
        while not self.matching(self.nodes(),text):
            if time.monotonic()>=deadline:raise AssertionError('未出现预期文案：'+text)
            self.sleep(.25)

    def configure(self):
        deadline=time.monotonic()+90
        while True:
            try:
                nodes=self.nodes()
                if any(n['secure'] or n['label'] in {'国家或区域','Country or region'} or n['label'].lower() in login_flow.AGREE for n in nodes) or (getattr(self.e,'route_reader',None) and self.e.route_reader.read()=='/loginConfig'):break
            except RuntimeError:
                if self.e.stopped():raise
            if time.monotonic()>=deadline:raise RuntimeError('启动后未进入配置或登录页面，未执行配置操作')
            self.sleep(.5)
        if any(n['secure'] for n in nodes):
            back=[n for n in nodes if n['clickable'] and n['kind']=='android.widget.ImageView' and not n['label'] and len(re.findall(r'\d+',n['bounds']))==4 and int(re.findall(r'\d+',n['bounds'])[1])<300]
            if len(back)!=1:raise RuntimeError('登录页返回配置入口不唯一')
            self.e.tap(back[0]);self.sleep(.6)
        elif any(n['label'].lower() in login_flow.AGREE for n in nodes):
            self.tap(next(n['label'] for n in nodes if n['label'].lower() in login_flow.AGREE))
        self.route('/loginConfig')
        self.field({'国家或区域','Country or region',self.text('country_or_region')})
        nodes=self.nodes();china=[n['label'] for n in nodes if n['clickable'] and login_flow.normalized(n['label']) in self.china_names]
        if not china:
            for _ in range(15):
                if not self.scroll('down'):break
                china=[n['label'] for n in self.nodes() if n['clickable'] and login_flow.normalized(n['label']) in self.china_names]
                if china:break
        if not china:raise AssertionError('国家列表没有中国')
        self.tap(china[0])
        if self.prefs()['country'].upper()!='CN':raise AssertionError('国家未保存为 CN')
        self.record('国家已保存',{'country':self.prefs()['country']})
        self.field({'数据中心','Data Center',self.text('data_center')})
        names=[n['label'] for n in self.nodes() if n['clickable'] and login_flow.normalized(n['label']) in {'china','china data center','中国','中国数据中心'}]
        if not names:raise AssertionError('数据中心列表没有中国')
        self.tap(names[0]);self.field({'语言','Language',self.text('language')});self.tap('中文简体')
        if self.prefs()['locale']!='zh_CN':raise AssertionError('中文未保存为 zh_CN')
        self.record('中文已保存',{'locale':self.prefs()['locale']})
        self.tap('下一步');self.route('/login')
        state=self.prefs()
        if state['locale']!='zh_CN' or state['country'].upper()!='CN' or state['center_country'].upper()!='CN':raise AssertionError('中国数据中心或中文配置未持久保存')
        self.assert_text('登录');self.record('配置完成并进入中文登录页',{'route':'/login','locale':state['locale'],'country':state['country'],'center_country':state['center_country']})

    def login(self,config):
        self.e.shell(['run-as',self.e.app_package,'rm','-f','/data/user/0/'+self.e.app_package+'/code_cache/devicecheck-session-state.json'])
        result=self.e.login(config)
        if result.get('confirmation')!='login_api_success_callback':raise AssertionError('未获得本次登录接口成功证据')
        login_flow.wait_post_login(self.e,self.sleep);login_flow.dismiss_onboarding(self.e)
        if not self.prefs()['state_observed'] or not self.prefs()['token_present']:raise AssertionError('登录后未获得有效登录态布尔证据')
        entry=getattr(self.e,'login_entry_evidence',{})
        if not entry.get('password_masked') or not entry.get('account_verified'):raise AssertionError('缺少账号输入验证或密码掩码证据')
        self.assert_text('首页')
        self.record('本次登录成功',{'confirmation':result['confirmation'],'token_present':True,'password_masked':True,'account_verified':True});self.e.login_result=result

    def open_languages(self):
        self.tap(self.text('mine'));self.tap(self.text('mine_general_settings'))
        for key in ('account_manager','language','notify_manager'):self.assert_text(self.text(key))
        self.record('通用设置菜单验证',{'keys':['account_manager','language','notify_manager']})
        self.tap(self.text('language'))
        self.route('/language');self.assert_text(self.text('language'))
        locale=self.prefs()['locale']
        names=[v['name'] for v in self.languages if v['locale']==locale]
        self.verify_selected(names[0] if len(names)==1 else '中文简体')
        self.record('进入语言列表',{'route':'/language','locale':locale})

    def ensure_language_page(self):
        """Merged outlines may reach a language phase without a language_page phase."""
        reader=getattr(self.e,'route_reader',None)
        if reader and reader.read()=='/language':
            self.top();return
        for _ in range(6):
            route=reader.read() if reader else ''
            if route.startswith('/main'):break
            self.e.back(self.nodes());self.sleep(.5)
        self.open_languages()

    def verify_selected(self,name):
        item=self.catalog[name];expected='devicecheck-language-'+item['lang']+'-'+item['country']
        selected=[n for n in self.nodes() if expected in n['label'] and n['selected']]
        if len(selected)!=1:raise AssertionError('未验证语言选中标记：'+name)
        if self.prefs()['locale']!=item['locale']:raise AssertionError('语言配置未持久保存：'+name)
        self.assert_text(self.text('language',item['locale']))

    def change(self,name):
        self.route('/language');self.top();self.tap(name,scroll=True)
        self.verify_selected(name);self.chosen=name
        self.record('语言选中与页面文案生效',{'language':name,'locale':self.catalog[name]['locale']})

    def roundtrip(self,name):
        self.e.back(self.nodes());self.sleep(.5);self.assert_text(self.text('mine_general_settings'));self.verify_copy('settings')
        self.e.back(self.nodes());self.sleep(.5);self.assert_text(self.text('mine_general_settings'));self.verify_copy('mine')
        self.record('通用设置与我的页面文案生效',{'language':name,'locale':self.prefs()['locale']})
        self.tap(self.text('mine_general_settings'));self.tap(self.text('language'));self.route('/language');self.top()
        # Selected item may be below the viewport.
        for _ in range(14):
            if self.matching(self.nodes(),name):break
            if not self.scroll('down'):break
        self.verify_selected(name);self.record('往返后选中与配置保持',{'language':name,'locale':self.prefs()['locale']})

    def all_languages(self,include_english=False,restore_chinese=False):
        self.route('/language');self.top();available=set()
        for _ in range(15):
            nodes=self.nodes()
            for name in self.catalog:
                if self.matching(nodes,name):available.add(name)
            if not self.scroll('down'):break
        if not available:raise AssertionError('语言列表没有可验证选项')
        excluded={'中文简体'} | (set() if include_english else {'English'})
        targets=[v['name'] for v in self.languages if v['name'] in available and v['name'] not in excluded]
        if not targets:raise AssertionError('当前列表没有其余语言，未执行逐种验证')
        for name in targets:self.change(name);self.roundtrip(name)
        self.record('已遍历实际语言列表的其余选项',{'tested':targets,'available':sorted(available)})
        if restore_chinese:
            self.change('中文简体');self.roundtrip('中文简体')
            self.record('全部语言验证后恢复中文',{'locale':self.prefs()['locale']})

    def persistence(self,chinese=False,restore=False):
        locale=self.prefs()['locale']
        if chinese and restore and locale!='zh_CN':
            self.change('中文简体');self.roundtrip('中文简体')
            locale=self.prefs()['locale']
            if locale!='zh_CN':raise AssertionError('执行恢复中文后语言配置未持久保存')
            self.record('已按用例恢复中文并验证持久保存',{'locale':'zh_CN'})
        if chinese and locale!='zh_CN':raise AssertionError('当前语言未按计划恢复为中文')
        names=[v['name'] for v in self.languages if v['locale']==locale]
        if len(names)!=1:raise AssertionError('无法确认当前保存的语言选项')
        self.roundtrip(names[0])

    def logout(self):
        if not self.prefs()['token_present']:raise AssertionError('退出前无登录态')
        for _ in range(4):
            current=self.e.route_reader.read()
            if current.startswith('/main'):break
            if current not in {'/language','/my/currency'}:raise RuntimeError('当前页面不在已验证的退出路径内')
            self.e.back(self.nodes());self.sleep(.5)
        self.tap(self.text('mine'))
        self.tap(self.text('mine_exit_account'),scroll=True);self.assert_text(self.text('tip_logout'))
        nodes=self.nodes();labels={self.text('sure')}
        matches=[n['label'] for n in nodes if n['clickable'] and n['label'] in labels]
        if len(matches)!=1:raise RuntimeError('退出确认按钮不唯一')
        self.tap(matches[0])
        for _ in range(30):
            if not self.prefs()['token_present']:break
            self.sleep(.5)
        self.route('/login');state=self.prefs()
        if not state['state_observed'] or state['token_present'] or state['user_info_present']:raise AssertionError('退出后登录态或个人信息未清理')
        fields=[n for n in self.nodes() if n['editable'] and not n['secure']]
        if not fields:raise AssertionError('退出后没有可重新输入账号的登录表单')
        self.record('退出成功且登录态已清除',{'route':'/login','token_present':False,'user_info_present':False,'account_editable':True})
        self.e.call('POST',self.e.base+'/appium/device/terminate_app',{'appId':self.e.app_package})
        self.e.call('POST',self.e.base+'/appium/device/activate_app',{'appId':self.e.app_package})
        deadline=time.monotonic()+25
        while True:
            try:
                fields=[n for n in self.nodes() if n['editable'] and not n['secure']]
                if fields and self.e.route_reader.read()=='/login':break
            except RuntimeError:
                if self.e.stopped():raise
            if time.monotonic()>=deadline:raise AssertionError('退出后重启 App 未保持未登录状态')
            self.sleep(.5)
        self.record('退出后重启仍需登录',{'route':'/login','account_editable':True})


def run(explorer,book,login_config,project,log,capture,progress,sleep=time.sleep):
    if not applies(book):raise ValueError('不是完整的六阶段语言回归计划')
    workflow=Workflow(explorer,project,capture,sleep);results=[];failure=None
    previous=None
    if str(getattr(explorer,'device_id','')).startswith('emulator-'):
        setting=explorer.shell(['settings','get','secure','stylus_handwriting_enabled'])
        if setting['ok']:
            previous=setting['output'].strip()
            explorer.shell(['settings','put','secure','stylus_handwriting_enabled','0'])
    try:
        for phase,case in zip(phases_for_book(book),book['cases']):
            result={k:case[k] for k in ('id','sheet','row','title')};result.update(result='fail',status='未执行',reason='',steps=[],screenshots=[])
            start=len(workflow.events);shots=len(workflow.shots)
            try:
                if failure:raise RuntimeError('前序阶段未通过：'+failure)
                log('执行专用回归阶段：'+phase)
                if phase=='configure':workflow.configure()
                elif phase=='login':workflow.login(login_config)
                elif phase=='language_page':workflow.open_languages()
                elif phase=='language_switch':
                    workflow.ensure_language_page();workflow.change('English');workflow.roundtrip('English')
                elif phase in {'language_all','language_all_full','language_all_restore','language_all_full_restore'}:
                    workflow.ensure_language_page();workflow.all_languages(include_english='_full' in phase,restore_chinese=phase.endswith('_restore'))
                elif phase in {'language_persistence','language_persistence_zh'}:
                    workflow.ensure_language_page()
                    wording=case.get('title','')+' '+' '.join(s.get('action','') for s in case.get('business_steps',[]))
                    restore=bool(re.search(r'(?:恢复|选(?:择)?回?|切(?:换)?回|改回|设(?:置)?回).{0,8}中文',wording))
                    workflow.persistence(chinese=phase.endswith('_zh'),restore=restore)
                elif phase=='language_restore_logout':
                    workflow.ensure_language_page();workflow.change('中文简体');workflow.logout()
                elif phase in {'logout','logout_relogin'}:
                    workflow.logout()
                    if phase=='logout_relogin':
                        workflow.login(login_config)
                        if relogin_cleanup(case):workflow.logout()
                result.update(result='pass',status='已执行',reason='本阶段页面、选中状态及本地状态断言通过')
            except Exception as error:
                result.update(status='已停止' if explorer.stopped() else '前序阶段未通过' if failure else '断言失败' if isinstance(error,AssertionError) else '执行受阻',reason=automation.redact(error,explorer.secrets)[:500]);failure=failure or phase
            result['steps']=workflow.events[start:];result['screenshots']=workflow.shots[shots:];results.append(result);progress(results)
        return results
    finally:
        if previous is not None:
            restore=explorer.__dict__.get('cleanup_shell') or explorer.shell
            try:restore(['settings','delete','secure','stylus_handwriting_enabled'] if previous=='null' else ['settings','put','secure','stylus_handwriting_enabled',previous])
            except Exception:log('临时输入法设置恢复失败，请在模拟器设置中复核')
