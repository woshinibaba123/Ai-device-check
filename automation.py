"""Bounded native UI exploration. Credentials are never added to report structures."""
import hashlib
import popup_handler
import login_flow
import language_tests
import json
import re
import time
import xml.etree.ElementTree as ET

ELEMENT = 'element-6066-11e4-a52e-4f735466cecf'
DEFAULT_SKIP = 'vconsole,debug console,调试控制台,agree,consent,choose file,select file,upload,上传,上傳,选择文件,選擇檔案,download,donwload,下载,下載,删除,注销,退出登录,退出,支付,购买,下单,提交,发送,重置,恢复出厂,解绑,启动任务,开始配送,同意,允许,不同意,accept,delete,remove,pay,purchase,buy,submit,send,logout,log out,reset,unpair,start delivery,quit,disagree'

class LoginBlocked(RuntimeError): pass


def exploration_status(result):
    end=result.get('termination')
    if end=='stopped':return 'stopped'
    if end in {'login_or_secure_form','no_accessible_controls','page_tree_unavailable','root_snapshot_unavailable','startup_not_ready','webview_context_failed','outside_app','loading_recovery_failed','back_failed','unreachable_pending_branches'}:return 'blocked'
    if result.get('issues') or result.get('observations') or any(p.get('localization_findings') for p in result.get('pages',[])) or any(f.get('automatic') for f in result.get('forms',[])):return 'review'
    return 'passed'


def redact(value, secrets):
    result = str(value)
    for secret in sorted((str(v) for v in secrets if v),key=len,reverse=True):
        result = result.replace(secret, '[已隐藏]')
    result=re.sub(r'[A-Za-z0-9_.+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', '[已隐藏]',result)
    result=re.sub(r'(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)', '[已隐藏]',result)
    return result


def xpath_literal(value):
    if "'" not in value: return "'"+value+"'"
    if '"' not in value: return '"'+value+'"'
    return 'concat('+',"\'",'.join("'"+v+"'" for v in value.split("'"))+')'


def parse_ui(source, include_disabled=False):
    root = ET.fromstring(source)
    nodes = []
    def walk(el, path):
        a = el.attrib
        kind = a.get('class', a.get('type', el.tag))
        label = a.get('content-desc') or a.get('label') or a.get('text') or a.get('name') or ''
        editable = 'EditText' in kind or 'TextField' in kind or 'TextView' in kind and kind.startswith('XCUI')
        secure = a.get('password')=='true' or 'SecureText' in kind
        visible = a.get('displayed', a.get('visible','true')) != 'false'
        clickable = a.get('clickable')=='true' or kind in ('XCUIElementTypeButton','XCUIElementTypeCell','XCUIElementTypeLink','XCUIElementTypeSwitch','XCUIElementTypeTab')
        if visible and (include_disabled or a.get('enabled','true')!='false'):
            nodes.append({'path':path,'enabled':a.get('enabled','true')!='false','kind':kind,'label':label,'hint':a.get('hint',''),'id':a.get('resource-id',''),'editable':editable,'secure':secure,'clickable':clickable,'scrollable':a.get('scrollable')=='true' or kind in ('XCUIElementTypeScrollView','XCUIElementTypeTable','XCUIElementTypeCollectionView'),'package':a.get('package',''),'bounds':a.get('bounds',''),'value':a.get('value',''),'checked':a.get('checked')=='true' or a.get('value')=='1','selected':a.get('selected')=='true' or a.get('isSelected')=='true'})
        counts = {}
        for child in el:
            counts[child.tag]=counts.get(child.tag,0)+1
            walk(child,path+'/'+child.tag+'['+str(counts[child.tag])+']')
    walk(root,'/'+root.tag+'[1]')
    # Flutter often puts text on a child while the tappable parent has no label.
    for node in nodes:
        if not node['clickable'] or node['label']:continue
        children=[child for child in nodes if child['path'].startswith(node['path']+'/')]
        if any(child['clickable'] for child in children):continue
        labels=list(dict.fromkeys(child['label'] for child in children if child['label'] and not child['editable']))
        if labels and len(' · '.join(labels))<=160:node['label']=' · '.join(labels)
    return nodes


def has_controls(nodes):
    # An anonymous full-screen Flutter loading surface is clickable but is not a ready page.
    return any(n['editable'] or n['scrollable'] or (n['clickable'] and (n['label'] or n['id'])) for n in nodes)


def startup_screen(nodes):
    labels={n['label'].strip() for n in nodes if n['package'] not in popup_handler.SYSTEM_PACKAGES and n['label'].strip()}
    return bool(labels) and all(re.fullmatch(r'keenon|copyright.*|©.*',s,re.I) for s in labels)


def page_ready(nodes):
    if has_controls(nodes):return True
    if any('ProgressBar' in n['kind'] or 'ActivityIndicator' in n['kind'] for n in nodes):return False
    labels={n['label'].strip() for n in nodes if n['package'] not in popup_handler.SYSTEM_PACKAGES and n['label'].strip()}
    labels={s for s in labels if not re.fullmatch(r'loading[. …]*|加载中[. …]*',s,re.I)}
    if startup_screen(nodes):return False
    # A rendered title and body are evidence of a displayed page, even when
    # Flutter omits click flags. They do not prove its controls were exercised.
    return len(labels)>=2


def capture_after_form_allowed(nodes, secrets):
    """Compatibility for an already running server's unmasked capture callback."""
    if not has_controls(nodes):return False
    if any(n['secure'] or n['editable'] or 'WebView' in n['kind'] for n in nodes):return False
    visible='\n'.join(n.get('label','')+'\n'+n.get('value','') for n in nodes)
    return not any(str(value) in visible for value in secrets if value)


def signature(nodes):
    # Ignore text-field values and clocks; this is a screen-state approximation, not a route ID.
    parts=[]
    for n in nodes:
        if n['package'] in ('com.android.systemui','com.apple.springboard'): continue
        label='' if n['editable'] else re.sub(r'\b\d{1,2}:\d{2}(?::\d{2})?\b','<time>',n['label'])
        parts.append((n['kind'],n['id'],label,n['bounds'],n['clickable']))
    return hashlib.sha256(json.dumps(parts,ensure_ascii=False).encode()).hexdigest()[:16]


def navigation_key(nodes, route):
    if not route:return signature(nodes)
    # The WebView title identifies the H5 screen; its scroll offsets and clock
    # text must not create another exploration budget for the same screen.
    titles=tuple(n['label'] for n in nodes if 'WebView' in n['kind'] and n['label'])
    selected=tuple((re.search(r'Tab \d+ of \d+',n['label']).group(0) if re.search(r'Tab \d+ of \d+',n['label']) else n.get('id') or n['path']) for n in nodes if n.get('selected'))
    if route=='/language':selected=()
    return json.dumps((route,titles,selected),ensure_ascii=False)


def scrub_xml(source,secrets):
    root=ET.fromstring(source)
    for el in root.iter():
        a=el.attrib
        if a.get('password')=='true' or 'SecureText' in a.get('type',el.tag):
            for key in ('text','value','label','content-desc'):
                if key in a:a[key]='[已隐藏]'
        for key,value in list(a.items()):a[key]=redact(value,secrets)
    return ET.tostring(root,encoding='unicode')


class Explorer:
    def __init__(self, call, sid, platform, log, capture, stopped=lambda:False, secrets=(), shell=None):
        self.call=call;self.sid=sid;self.platform=platform;self.log=log;self.capture=capture;self.stopped=stopped;self.secrets=secrets;self.shell=shell
        self.base='/session/'+sid

    def source(self):
        for attempt in range(3):
            try:return self.call('GET',self.base+'/source')
            except RuntimeError as error:
                if self.platform!='Android' or 'AccessibilityNodeInfo' not in str(error):raise
                if attempt==2:
                    package=getattr(self,'app_package','')
                    if not getattr(self,'allow_source_recovery',False) or not package or getattr(self,'source_recoveries',0)>=2:raise
                    self.source_recoveries=getattr(self,'source_recoveries',0)+1
                    self.log('控件树连续读取失败，重新打开被测 App 后恢复自动化。')
                    self.call('POST',self.base+'/appium/device/terminate_app',{'appId':package})
                    self.call('POST',self.base+'/appium/device/activate_app',{'appId':package})
                    time.sleep(2)
                    source=self.call('GET',self.base+'/source')
                    if hasattr(self,'recovery_events'):self.recovery_events.append({'type':'accessibility_recovered','message':'控件树连续读取失败，重新打开 App 后恢复。'})
                    return source
                self.log('页面控件树正在重建，重试读取。')
                time.sleep(.7)

    def wait_root_snapshot(self,route,package,timeout=20,allow_transition=False):
        """Route callbacks can precede the native tree after a cold relaunch."""
        reader=getattr(self,'route_reader',None)
        deadline=time.monotonic()+timeout
        while not self.stopped():
            source=self.source();nodes=parse_ui(source)
            current=reader.read() if reader else ''
            if current!=route and not allow_transition:return None
            if current==route and has_controls(nodes) and (not package or any(n['package']==package for n in nodes)) and not any(n['secure'] or 'WebView' in n['kind'] for n in nodes):return source
            if time.monotonic()>=deadline:return None
            time.sleep(.5)
        return None
    def wait_ui(self,timeout=20):
        deadline=time.monotonic()+timeout
        source=self.source()
        while not self.stopped():
            nodes=parse_ui(source)
            if has_controls(nodes):return source
            if time.monotonic()>=deadline:break
            time.sleep(.5);source=self.source()
        return source
    def _note_route(self,source):
        """Log page transitions with observed open duration; route reader optional."""
        reader=getattr(self,'route_reader',None)
        if reader:
            try:route=reader.read()
            except Exception:route=''
            now=time.monotonic()
            prev=getattr(self,'_route_track',None)
            self._route_track=(route,now)
            if route and prev and prev[0] and prev[0]!=route:
                self.log('页面跳转：%s → %s（页面打开耗时 %.1f 秒）'%(prev[0],route,now-prev[1]))
        return source

    def settled_source(self, timeout=15):
        """Wait through transient loading states before recording or navigating."""
        deadline=time.monotonic()+timeout
        previous=None;stable=0
        source=self.source()
        while not self.stopped():
            nodes=parse_ui(source)
            loading=any('ProgressBar' in n['kind'] or 'ActivityIndicator' in n['kind'] or re.fullmatch(r'loading[. …]*|加载中[. …]*',n['label'],re.I) for n in nodes)
            interactive=page_ready(nodes)
            current=signature(nodes)
            stable=stable+1 if current==previous else 0
            if not loading and interactive and stable>=2:return self._note_route(source)
            if time.monotonic()>=deadline:
                if loading or not interactive:self.log('页面等待超过 %.0f 秒仍未稳定，可能卡住或加载异常。'%timeout)
                return self._note_route(source)
            previous=current
            time.sleep(.5);source=self.source()
        return self._note_route(source)

    def find(self, selector):
        by=selector.get('by','accessibility id');value=selector.get('value','').strip()
        if not value:raise LoginBlocked('登录控件定位内容为空。')
        if by not in ('accessibility id','id','xpath'):raise LoginBlocked('登录定位方式仅支持 accessibility id、id、xpath。')
        element=self.call('POST',self.base+'/element',{'using':by,'value':value})
        return element.get(ELEMENT) or element.get('ELEMENT')
    def tap(self,node):
        self.auto_form_epoch=getattr(self,'auto_form_epoch',0)+1
        # Use native coordinate injection; adb's Java input command may time out under load.
        if self.platform=='Android':
            m=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
            if m:
                x=(int(m[1])+int(m[3]))//2;y=(int(m[2])+int(m[4]))//2
                try:
                    self.log('点击方式 native-gesture-v2：'+redact(node.get('label',''),self.secrets)[:60]+' @'+str(x)+','+str(y))
                    if node.get('label','').strip().casefold()=='agree with':
                        self.log('隐私确认原生点击坐标：'+str(x)+','+str(y))
                        self._privacy_diagnostic('before')
                    self.call('POST',self.base+'/execute/sync',{'script':'mobile: clickGesture','args':[{'x':x,'y':y}]})
                    if node.get('label','').strip().casefold()=='agree with':
                        time.sleep(.5);self._privacy_diagnostic('after')
                    return
                except Exception:
                    if self.stopped():raise
                    # A failed injection is never reported as a successful tap.
                    self.log('坐标点击未生效，改用控件定位点击。')
        eid=self.find({'by':'xpath','value':node['path']})
        self.call('POST',self.base+'/element/'+eid+'/click',{})
    def _privacy_diagnostic(self, stage):
        """Temporary, credential-free evidence for the specific privacy overlay."""
        import base64
        from pathlib import Path
        try:
            source=self.source();nodes=parse_ui(source)
            if any(n['secure'] or n['editable'] for n in nodes):return
            folder=Path(__file__).resolve().parent/'.runtime/privacy-diagnostic'
            folder.mkdir(exist_ok=True)
            data=self.call('GET',self.base+'/screenshot')
            (folder/(stage+'.png')).write_bytes(base64.b64decode(data))
            (folder/(stage+'.xml')).write_text(scrub_xml(source,self.secrets))
        except Exception:
            pass

    def type(self,eid,text,node=None):
        if self.platform=='Android' and node and node.get('bounds'):
            # Delegate IME activation/restoration to Appium. Manual shell input
            # followed by an immediate keyboard restore can truncate Flutter text.
            self.tap(node)
            time.sleep(.5)
            fresh=self.find({'by':'xpath','value':node['path']})
            self.call('POST',self.base+'/element/'+fresh+'/clear',{})
            sent=self.call('POST',self.base+'/execute/sync',{'script':'mobile: type','args':[{'text':text}]})
            if sent is False:raise LoginBlocked('原生输入服务未接受文本，未继续提交。')
            time.sleep(.5)
            return
        self.call('POST',self.base+'/element/'+eid+'/clear',{})
        self.call('POST',self.base+'/element/'+eid+'/value',{'text':text})
    def back(self,nodes):
        self.auto_form_epoch=getattr(self,'auto_form_epoch',0)+1
        if self.platform=='Android':
            # WebView Back may only change browser history. Prefer the App's header back control.
            if any('WebView' in n['kind'] for n in nodes):
                header=next((n for n in nodes if n['clickable'] and re.fullmatch(r'返回|后退|back|navigate up',n['label'],re.I)),None)
                if header is None:
                    # Observed H5 back icon (iconfont U+E668) has a DOM handler,
                    # but WebView exposes it as a non-clickable TextView.
                    for n in nodes:
                        bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.get('bounds',''))
                        if n['label'].strip() in {'\ue668','‹','←'} and bounds and int(bounds[1])<180 and int(bounds[2])<300 and int(bounds[3])-int(bounds[1])<180 and int(bounds[4])-int(bounds[2])<180:
                            header=n;break
                if header is None:
                    for n in nodes:
                        bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n['bounds'])
                        if n['clickable'] and 'ImageView' in n['kind'] and bounds and int(bounds[1])<160 and int(bounds[2])<300 and not any('WebView' in v['kind'] and n['path'].startswith(v['path']+'/') for v in nodes):
                            header=n;break
                if header is not None:self.tap(header);return
            self.call('POST',self.base+'/back',{});return
        explicit=next((n for n in nodes if n['clickable'] and re.fullmatch(r'返回|后退|关闭|back|close',n['label'],re.I)),None)
        if explicit:self.tap(explicit);return
        nav=next((n for n in nodes if n['kind']=='XCUIElementTypeButton' and 'NavigationBar' in n['path']),None)
        if not nav:raise RuntimeError('未识别到 iOS 返回按钮，需为此页面配置稳定的返回标识。')
        self.tap(nav)
    def escape_blocked_page(self, nodes):
        """Leave one stuck overlay without accepting its business action."""
        before=signature(nodes)
        self.back(nodes)
        after=self.settled_source()
        if signature(parse_ui(after))!=before:return after
        package=getattr(self,'app_package','') if self.platform=='Android' else getattr(self,'app_bundle','')
        if not package:return None
        self.log('返回未改变页面，重新打开 App 恢复到可操作页面。')
        self.call('POST',self.base+'/appium/device/terminate_app',{'appId':package})
        self.call('POST',self.base+'/appium/device/activate_app',{'appId':package})
        after=self.settled_source(timeout=45)
        return after if signature(parse_ui(after))!=before else None

    def scroll(self):
        rect=self.call('GET',self.base+'/window/rect');w=int(rect['width']);h=int(rect['height'])
        self.call('POST',self.base+'/actions',{'actions':[{'type':'pointer','id':'finger','parameters':{'pointerType':'touch'},'actions':[{'type':'pointerMove','duration':0,'x':w//2,'y':int(h*.75)},{'type':'pointerDown','button':0},{'type':'pointerMove','duration':600,'x':w//2,'y':int(h*.3)},{'type':'pointerUp','button':0}]}]})

    def login(self,config):
        if not config.get('enabled'):return {'status':'not_requested'}
        if not config.get('account') or not config.get('password'):raise LoginBlocked('请填写测试账号和密码。')
        success=config.get('success',{}).get('value','').strip()
        preset=config.get('flow')=='keenon_china'
        probe=getattr(self,'login_probe',None)
        if preset and probe is None:raise LoginBlocked('接口登录验证未配置，需使用 Flutter 源码构建测试包。')
        if not success and not preset:raise LoginBlocked('请填写登录成功标识，例如登录后首页独有的控件文字或 ID。')
        self.log('开始登录：登录期间不截图、不保存页面结构。')
        if preset:
            login_flow.prepare(self)
            probe.reset()
        for text in ([] if preset else config.get('prepare',[])):
            if self.stopped():raise LoginBlocked('登录已停止。')
            matches=[n for n in parse_ui(self.source()) if n['clickable'] and n['label']==text]
            if len(matches)!=1:raise LoginBlocked('登录前按钮未唯一匹配，请检查文字或改用自定义步骤。')
            self.tap(matches[0])
            time.sleep(.7)
        try:
            if preset:raise LoginBlocked('内置流程每次重新验证登录接口')
            self.find(config['success'])
            self.log('已检测到登录成功标识，复用当前登录状态。')
            return {'status':'confirmed','confirmation':'existing_session'}
        except Exception:pass
        nodes=parse_ui(self.wait_ui())
        fields=[n for n in nodes if n['editable']]
        def locate(key, fallback):
            selector=config.get(key,{})
            if selector.get('value','').strip():return self.find(selector)
            if not fallback:raise LoginBlocked('未识别到'+{'account_selector':'账号输入框','password_selector':'密码输入框','submit_selector':'登录按钮'}[key]+'；请先配置进入登录页的操作，或展开高级登录定位。')
            return self.find({'by':'xpath','value':fallback['path']})
        secure=next((n for n in fields if n['secure']),None)
        plain=next((n for n in fields if not n['secure']),None)
        account=locate('account_selector',plain)
        if preset:
            login_flow.fill_account(self,config['account'],config.get('account_selector'))
            login_flow.ensure_password(self)
            # App 在账号框首次失焦时会强制回退验证码模式（_onAccountFocusChanged）。
            # 先点一次密码框消耗掉这次回退，再重新切换密码登录，之后输入才稳定。
            if self.platform=='Android':
                nodes=parse_ui(self.source())
                secure=login_flow.password_field(nodes)
                if secure:
                    self.tap(secure)
                    time.sleep(1.2)
                    nodes=parse_ui(self.source())
                    if not login_flow.password_field(nodes):
                        nodes=login_flow.wait_login_snapshot(self)
                    if not login_flow.password_field(nodes):
                        self.log('首次聚焦密码框触发模式回退，重新切换密码登录。')
                        login_flow.ensure_password(self)
        else:self.type(account,config['account'],plain)
        nodes=parse_ui(self.source())
        fields=[n for n in nodes if n['editable']]
        secure=next((n for n in fields if n['secure']),None)
        if preset:
            secure=login_flow.password_field(nodes)
            if secure:self.log('准备输入密码框：'+(secure['label'] or secure['kind'])+' bounds='+secure['bounds']+' secure='+str(secure['secure']))
        password=locate('password_selector',secure)
        self.login_entry_evidence={'password_masked':bool(secure and secure['secure']),'account_verified':preset}
        self.type(password,config['password'],secure)
        if preset:
            # 密码输入可能因页面回退验证码模式而落空；检测到回退时重填账号与密码一次。
            time.sleep(1.5)
            nodes=parse_ui(self.source())
            if not login_flow.password_field(nodes):
                nodes=login_flow.wait_login_snapshot(self)
            if not login_flow.password_field(nodes):
                self.log('检测到页面回退验证码模式，重新填写账号与密码。')
                login_flow.fill_account(self,config['account'],config.get('account_selector'))
                login_flow.ensure_password(self)
                nodes=parse_ui(self.source())
                secure=login_flow.password_field(nodes)
                if not secure:raise LoginBlocked('重试后仍未进入密码登录模式；未继续提交。')
                password=locate('password_selector',secure)
                self.type(password,config['password'],secure)
                time.sleep(1.5)
                if not login_flow.password_field(login_flow.wait_login_snapshot(self)):
                    raise LoginBlocked('密码输入后页面再次回退；未继续提交，请人工检查。')
        if preset:login_flow.dismiss_keyboard(self)
        if preset and probe.read():
            self.log('已确认登录接口业务成功回调；页面已离开登录表单。')
            return {'status':'confirmed','confirmation':'login_api_success_callback'}
        nodes=parse_ui(self.source())
        submit=next((n for n in nodes if n['clickable'] and re.fullmatch(r'登录|登 录|登入|登錄|login|log in|sign in',n['label'].strip(),re.I)),None)
        if preset:login_flow.agree_checkbox(self)
        # Checkbox taps and keyboard dismissal can rebuild Flutter semantics.
        # Resolve the submit control again and use the same checked native gesture
        # path as other controls; adb shell input may return a failed result.
        if not config.get('submit_selector',{}).get('value'):
            # Flutter can temporarily clear semantics after keyboard dismissal.
            # Wait for the actual control instead of treating that frame as final.
            submit_deadline=time.monotonic()+15
            while True:
                if self.stopped():raise LoginBlocked('登录已停止。')
                if preset and probe.read():
                    self.log('已确认登录接口业务成功回调；页面已离开登录表单。')
                    return {'status':'confirmed','confirmation':'login_api_success_callback'}
                nodes=parse_ui(self.source())
                submit=next((n for n in nodes if n['clickable'] and re.fullmatch(r'登录|登 录|登入|登錄|login|log in|sign in',n['label'].strip(),re.I)),None)
                if submit or time.monotonic()>=submit_deadline:break
                time.sleep(.5)
        button=locate('submit_selector',submit)
        if submit and not config.get('submit_selector',{}).get('value'):
            self.log('点击登录按钮：'+submit['label']+' bounds='+submit['bounds'])
            self.tap(submit)
        else:
            self.call('POST',self.base+'/element/'+button+'/click',{})
        deadline=time.monotonic()+60
        last_diag=0
        while time.monotonic()<deadline:
            if self.stopped():raise LoginBlocked('登录验证已停止。')
            if preset:
                if probe.read():
                    self.log('已确认登录接口业务成功回调；不保存账号、密码或 Token。')
                    return {'status':'confirmed','confirmation':'login_api_success_callback'}
                try:login_flow.agree_dialog(self)
                except RuntimeError as error:
                    if 'AccessibilityNodeInfo' not in str(error):raise
                    if probe.read():
                        self.log('登录接口已成功；控件树暂不可读，交给登录后恢复机制处理。')
                        return {'status':'confirmed','confirmation':'login_api_success_callback'}
                    self.log('登录结果尚未确认，控件树暂不可读，继续检查接口成功回调。')
                    time.sleep(.5);continue
                if probe.read():
                    self.log('已确认登录接口业务成功回调；不保存账号、密码或 Token。')
                    return {'status':'confirmed','confirmation':'login_api_success_callback'}
                now=time.monotonic()
                if now-last_diag>=5:
                    last_diag=now
                    try:
                        nodes=parse_ui(self.source())
                        fields='; '.join((n['label'] or n['kind'])+'@'+n['bounds'] for n in nodes if n['editable'])
                        btns='; '.join(n['label'][:20] for n in nodes if n['clickable'] and n['label'])[:200]
                        self.log('等待中页面：输入框['+fields+'] 可点击['+btns+']')
                    except Exception:pass
                time.sleep(.5)
                continue
            try:
                self.find(config['success'])
                self.log('登录成功标识已确认，开始后续测试。')
                return {'status':'confirmed','confirmation':'configured_element'}
            except LoginBlocked:raise
            except Exception:time.sleep(1)
        if preset:raise LoginBlocked('60 秒内未收到登录接口成功结果，未继续探索；请检查账号、网络或二次验证。')
        raise LoginBlocked('未在 30 秒内找到登录成功标识。可能需要验证码、二次验证或账号配置有误；未继续探索。')

    BUILTIN_STEP_ALIASES={'我的':['我的','Mine','My'],'通用设置':['通用设置','Common setting','General settings','Settings'],'语言':['语言','Language','Langue','Idioma','Sprache','言語','언어','Ngôn ngữ','Lingua']}
    def _step_labels(self,step):
        """把路径步骤展开为该文案在全部语言下的候选文字（内置别名 + 源码 i18n 基线）。"""
        candidates=list(self.BUILTIN_STEP_ALIASES.get(step,[step]))
        index=getattr(self,'flow_index',None)
        translations=index.get('translations',{}) if isinstance(index,dict) else {}
        for key,values in translations.items():
            if step in values:
                candidates.extend(values)
                candidates.extend(getattr(self,'runtime_translation_aliases',{}).get(key,[]))
        seen=[]
        for value in candidates:
            if value not in seen:seen.append(value)
        return seen
    @staticmethod
    def _rows_with_label(nodes,labels):
        # Flutter 设置行常为多行 label（如「语言\n中文简体」），按行匹配而非全等。
        wanted={labels} if isinstance(labels,str) else {v for v in labels}
        return [n for n in nodes if n['clickable'] and wanted & {v.strip() for v in n['label'].splitlines()}]
    def _unique_row(self,nodes,label):
        candidates=self._step_labels(label) if isinstance(label,str) else list(label)
        matches=self._rows_with_label(nodes,candidates)
        if len(matches)>1:
            exact=[n for n in matches if n['label'].strip() in candidates]
            if len(exact)==1:matches=exact
        return matches
    def switch_language(self,config):
        self.log('切换 App 内语言：'+config['name'])
        # 两个官方入口都支持：登录后默认走「我的→通用设置→语言」；登录前配置页默认点「语言」。
        if config.get('path'):
            steps=list(config['path'])
        else:
            steps=['语言'] if config.get('phase')=='before_login' else ['我的','通用设置','语言']
        steps=steps+[config['choice']]
        for index,label in enumerate(steps):
            if self.stopped():raise LoginBlocked('语言测试已停止。')
            matches=self._unique_row(parse_ui(self.wait_ui()),label)
            last=index==len(steps)-1
            if not matches and last:
                # 目标语言选项可能在列表下方，向下滚动后再找。
                for _ in range(10):
                    if self.stopped():raise LoginBlocked('语言测试已停止。')
                    self.scroll();time.sleep(.4)
                    matches=self._unique_row(parse_ui(self.source()),label)
                    if matches:break
            if len(matches)!=1:
                nodes=parse_ui(self.source())
                visible=[n['label'].replace('\n','⏎')[:40] for n in nodes if n['clickable'] and n['label']][:8]
                raise LoginBlocked('语言切换第 %d/%d 步「%s」未唯一匹配（匹配到 %d 个，候选：%s；页面可见可点击：%s）。请检查该语言的切换路径或云端是否开放此语言。'%(
                    index+1,len(steps),label,len(matches),'、'.join(self._step_labels(label)[:6]),'、'.join(visible) or '（无可点击控件）'))
            self.tap(matches[0]);time.sleep(.7)
        for label in config.get('return_path',[]):
            if self.stopped():raise LoginBlocked('语言测试已停止。')
            matches=self._unique_row(parse_ui(self.wait_ui()),label)
            if len(matches)!=1:raise LoginBlocked('语言切换后的返回路径未唯一匹配。')
            self.tap(matches[0]);time.sleep(.5)
        if self.stopped():raise LoginBlocked('语言测试已停止。')
        self.log('已点击目标语言选项，继续测试；未验证翻译文字。')
        return {'code':config['code'],'name':config['name'],'status':'switched','confirmation':'language_option_clicked'}

    def explore(self,config):
        action_limit=int(config.get('max_actions',0))
        time_limit=int(config.get('seconds',0))
        if action_limit<0 or time_limit<0:raise ValueError('探索上限不能为负数；0 表示不限')
        budget=max(1,min(action_limit,500)) if action_limit else float('inf')
        seconds=max(10,min(time_limit,1800)) if time_limit else float('inf')
        max_depth=max(1,min(int(config.get('max_depth',6)),20))
        max_scrolls=max(0,min(int(config.get('max_scrolls',2)),10))
        words=[x.strip().casefold() for x in (DEFAULT_SKIP+',exit account,no file chosen,未选择文件,'+config.get('skip','')).split(',') if x.strip()]
        pages={};edges=[];skipped=[];issues=getattr(self,'recovery_events',[]);self.recovery_events=issues;path=[];nav_edges={};actions=0;scrolls={};deadline=time.monotonic()+seconds
        self.log('等待页面可交互控件加载…')
        initial_source=self.wait_ui()
        root_nodes=parse_ui(initial_source)
        root_tabs={m.group(0) for n in root_nodes if (m:=re.search(r'\nTab \d+ of \d+',n['label']))}
        packages=[n['package'] for n in root_nodes if n['package'] and n['package']!='com.android.systemui']
        target_package=getattr(self,'app_package','') or (packages[0] if packages else '')
        ios_bundle=''
        if self.platform=='iOS':
            info=self.call('POST',self.base+'/execute/sync',{'script':'mobile: activeAppInfo','args':[]})
            ios_bundle=getattr(self,'app_bundle','') or info.get('bundleId','')
            if not ios_bundle:raise RuntimeError('无法识别 iOS App 边界，未开始自动点击。')
        plan=config.get('source_plan',{})
        label_keys=plan.get('label_keys',{})
        def control_id(node,route):
            tab=re.search(r'Tab \d+ of \d+',node['label'])
            if tab:return ('tab',tab.group(0))
            label=node['label'].strip().splitlines()[0] if node['label'].strip() else ''
            semantic=label_keys.get(label.casefold())
            return (node['id'],semantic or (node['path'] if route and route not in ('/webview','/language') else node['label']))
        entry_labels=set(plan.get('entry_labels',[]));tab_labels=set(plan.get('tab_labels',[]))
        visited_routes=set();popup_dismissals=[];popup_attempts={};popup_backs={};outside_recoveries={};secure_recoveries={};observations=[]
        attempted_by_page={}
        import form_runner
        form_config=form_runner.validate(config.get('form'))
        form_results=[];form_attempted=False;auto_form_cache={}
        self.secrets=list(self.secrets)+form_runner.values(form_config)
        termination='action_limit';depth_limited=False;depth_pruned=set();form_abort_attempts=set()
        blocked_recoveries={};back_retries={};tree_retries={};tree_restarts={}
        entry_failures={};active_entries={};blocked_entries=set();leaving_form=False;revisit_counts={};final_restarts=0
        def retryable(node):
            if any(v in node['kind'] for v in ('CheckBox','Switch','RadioButton','SeekBar')):return False
            return not re.search(r'保存|提交|发送|删除|支付|购买|注销|退出|同意|确认|确定|上传|下发|呼叫|开始|启动|\b(save|submit|send|delete|pay|buy|logout|agree|confirm|ok|upload|start|run|apply|call)\b',node['label'],re.I)
        def local_action(node):
            key=label_keys.get(node['label'].strip().casefold(),'')
            return bool(re.search(r'^(?:search|refresh|read all|unread|read|搜索|刷新|全部已读|未读|已读)$',node['label'].strip(),re.I) or key in ('search','refresh','read_all','unread','read','logUpload','app_log_upload') or key.startswith('data_center_')) or not retryable(node)
        def abandon(record,reason):
            blocked_entries.add(record['identity'])
            skipped.append({'page':record['page'],'label':redact(record['label'],self.secrets),'reason':reason,'failed_attempts':entry_failures.get(record['identity'],0)})
            self.log('跳过受阻入口：'+redact(record['label'],self.secrets)+' · '+reason)
        def rearm(record):
            attempted_by_page.get(record['context'],set()).discard(record['control'])
            for known in pages.values():
                if known.get('navigation_key')==record['context']:
                    known['attempted'].discard(record['raw_key']);known['exhausted']=False
        def enter(sig,page,node,raw_key,action='tap'):
            nonlocal actions
            context=page.get('navigation_key',sig);identity=(context,node['id'],node['label'])
            record={'identity':identity,'context':context,'id':node['id'],'label':node['label'],'raw_key':raw_key,'page':page['id'],'retryable':retryable(node) and not local_action(node),'control':control_id(node,page.get('route',''))}
            if identity in blocked_entries:return False
            active_entries[sig]=record
            limit=2 if record['retryable'] else 1
            while entry_failures.get(identity,0)<limit and actions<budget and time.monotonic()<deadline and not self.stopped():
                attempt=entry_failures.get(identity,0)+1;actions+=1
                self.log('尝试入口 '+str(attempt)+'/'+str(limit)+'：'+redact(node['label'] or node['id'],self.secrets))
                self.tap(node)
                after_source=self.settled_source();after=parse_ui(after_source);new=signature(after)
                if new==sig and not local_action(node) and not self.stopped():
                    # Slow H5/WebView targets may still be pushing the route
                    # when the native tree already looks stable. Give the
                    # transition a grace window before judging it ineffective.
                    grace=time.monotonic()+8
                    while time.monotonic()<grace and not self.stopped():
                        time.sleep(1)
                        after_source=self.source();after=parse_ui(after_source)
                        if signature(after)!=sig:break
                    new=signature(after)
                remember(new,after,after_source)
                edges.append({'from':page['id'],'action':action,'label':redact(node['label'],self.secrets),'attempt':attempt,'to_state':new,'changed':new!=sig})
                if new!=sig:
                    if page_ready(after) and not popup_handler.has_popup(after) and (not target_package or any(n['package']==target_package for n in after)):
                        entry_failures.pop(identity,None)
                    nav_edges.setdefault(sig,[]).append({'target':new,'label':node['label'],'id':node['id'],'control':record['control']})
                    # Selecting another language or filter changes state, not
                    # navigation depth. H5 pages sharing /webview remain pushes.
                    destination=pages.get(new,{})
                    same_native_route=page.get('route') and page.get('route')==destination.get('route') and page.get('route')!='/webview'
                    if same_native_route or local_action(node):
                        edges[-1]['same_page_state']=True
                    else:path.append(sig)
                    return True
                if local_action(node):
                    edges[-1]['outcome']='操作已点击，页面未跳转；业务结果未验证'
                    return False
                if page.get('route')=='/webview' or any('WebView' in n['kind'] for n in after):
                    # H5 页内的 Tab/筛选切换不改变原生控件树，无法据此判定跳转失败。
                    # 按页内操作记录一次即可，不再重试或计入受阻入口。
                    edges[-1]['outcome']='H5 页内操作未引起原生状态变化；业务结果未验证'
                    observations.append({'type':'webview_local_tap','page':page['id'],'route':page.get('route',''),'label':redact(node['label'],self.secrets),'reason':'H5 页内切换未引起原生状态变化；需专用用例验证业务结果'})
                    return False
                entry_failures[identity]=attempt
                if attempt<limit:self.log('跳转未生效，再尝试一次；最多两次。')
            if entry_failures.get(identity,0)>=limit:
                reason='连续两次跳转未生效，留在原页并继续其他入口' if limit==2 else '操作未改变页面，不重复点击可能写入数据的控件'
                abandon(record,reason)
                issues.append({'type':'entry_unreachable','page':page['id'],'label':redact(node['label'],self.secrets),'attempts':entry_failures.get(identity,0),'error':reason})
            return False
        def remember(sig,nodes,source):
            if popup_handler.has_popup(nodes):return
            if not page_ready(nodes):return
            if any(n['secure'] for n in nodes):return
            if target_package and not any(n['package']==target_package for n in nodes):return
            if ios_bundle:
                info=self.call('POST',self.base+'/execute/sync',{'script':'mobile: activeAppInfo','args':[]})
                if info.get('bundleId')!=ios_bundle:return
            if sig not in pages:
                pages[sig]={'id':'P'+str(len(pages)+1),'attempted':set(),'exhausted':False,'controls':sum(n['clickable'] for n in nodes),'editable_fields':sum(n['editable'] for n in nodes),'localization_findings':language_tests.text_findings(nodes,self.secrets)}
                reader=getattr(self,'route_reader',None)
                route=reader.read() if reader else ''
                if route and re.match(r'^/(?:login|staffLogin)(?:/|$)',route):
                    del pages[sig];return
                pages[sig]['navigation_key']=redact(navigation_key(nodes,route),self.secrets)
                if route:
                    pages[sig]['route']=route;visited_routes.add(route)
                if not has_controls(nodes):
                    observations.append({'type':'display_only','page':pages[sig]['id'],'route':route,'reason':'页面内容已展示，但控件未提供可点击标记；已采集页面，未执行控件交互'})
                if route in ('/robot-flow/scan','/login/scan'):
                    observations.append({'type':'test_data_required','page':pages[sig]['id'],'route':route,'reason':'扫码后的流程需要有效测试二维码或激活码，由专用用例提供；本次只核验页面展示'})
                self.log('发现页面状态 '+pages[sig]['id']+(' · '+route if route else ''))
                self.capture('explore-'+str(len(pages)),source)
        def escape_overlay(sig, nodes, reason):
            nonlocal actions
            if blocked_recoveries.get(sig,0)>=2 or sum(blocked_recoveries.values())>=6 or actions>=budget:return False
            blocked_recoveries[sig]=blocked_recoveries.get(sig,0)+1
            actions+=1
            self.log('弹窗无法正常关闭，尝试离开此分支并继续其他页面。')
            # 关闭控件连续无效时，先用系统返回键兜底；每个页面只尝试一次。
            if popup_backs.get(sig,0)<1 and not self.stopped():
                popup_backs[sig]=1
                try:
                    self.call('POST',self.base+'/back',{})
                    after=parse_ui(self.settled_source(timeout=8))
                except Exception as error:
                    if self.stopped():raise
                else:
                    if popup_handler.close_target(after)[0] is None or signature(after)!=sig:
                        edges.append({'from':pages.get(sig,{}).get('id','弹窗'),'action':'blocked_page_recovery','to_state':signature(after),'changed':True})
                        issues.append({'type':'popup_recovered','message':reason+'；系统返回键已关闭弹窗，继续其他页面。'})
                        return True
            try:
                recovered=self.escape_blocked_page(nodes)
                if not recovered:return False
                after=parse_ui(recovered);new=signature(after)
                edges.append({'from':pages.get(sig,{}).get('id','弹窗'),'action':'blocked_page_recovery','to_state':new,'changed':True})
                issues.append({'type':'popup_recovered','message':reason+'；已返回或重新打开 App，继续其他页面。'})
                return True
            except Exception as error:
                if self.stopped():raise
                issues.append({'type':'recovery','error':redact(error,self.secrets)[:300]})
                return False
        while actions<budget:
            if self.stopped():termination='stopped';break
            if time.monotonic()>=deadline:termination='time_limit';break
            source=self.source();nodes=parse_ui(source);sig=signature(nodes)
            # Dismiss overlays before screenshotting or validating the foreground App.
            popup,reason=popup_handler.permission_target(nodes)
            if popup is None and leaving_form:
                popup=popup_handler.discard_target(nodes)
                if popup:reason='放弃本轮未提交的表单编辑并返回'
            if popup is None:popup,reason=popup_handler.close_target(nodes)
            if popup is not None and leaving_form and getattr(self,'form_data_active',False) and popup['label'].strip().casefold() in {'cancel','取消','cancelar','キャンセル'} and target_package and pages:
                origin=pages.get(path[-1],{}).get('navigation_key','form') if path else 'form'
                if origin not in form_abort_attempts:
                    form_abort_attempts.add(origin);actions+=1
                    self.log('表单返回确认没有明确的放弃按钮；不再重复取消，重开 App 恢复首页。')
                    self.call('POST',self.base+'/appium/device/terminate_app',{'appId':target_package})
                    self.call('POST',self.base+'/appium/device/activate_app',{'appId':target_package})
                    root_route=next(iter(pages.values())).get('route','')
                    restored=self.wait_root_snapshot(root_route,target_package,timeout=60,allow_transition=True) if root_route else None
                    if restored:
                        path=[];back_retries.clear();leaving_form=False
                        observations.append({'type':'form_abandoned','reason':'未提交的测试表单通过重开 App 离开；已确认首页恢复，继续其他入口'})
                        continue
                    issues.append({'type':'form_return_failed','error':'重开后仍未确认首页就绪；未提交表单'})
                    termination='root_snapshot_unavailable';break
            packages_now={n['package'] for n in nodes if n['package']}
            allowed=not target_package or packages_now <= ({target_package}|popup_handler.SYSTEM_PACKAGES)
            if ios_bundle:
                active=self.call('POST',self.base+'/execute/sync',{'script':'mobile: activeAppInfo','args':[]}).get('bundleId','')
                allowed=active in (ios_bundle,'com.apple.springboard')
            if popup and allowed:
                key=(sig,popup['path'],popup['label'],popup['id'])
                if popup_attempts.get(key,0)>=2:
                    if escape_overlay(sig,nodes,'弹窗关闭控件连续点击后未消失'):continue
                    issues.append({'type':'popup','error':'弹窗关闭控件连续点击后仍未消失，停止以避免重复操作。'})
                    termination='popup_blocked';break
                popup_attempts[key]=popup_attempts.get(key,0)+1;actions+=1
                label=redact(popup['label'] or popup['id'],self.secrets)
                try:
                    self.log('关闭弹窗：'+label[:100]);self.tap(popup)
                    after=self.settled_source()
                    wait_until=min(deadline,time.monotonic()+max(0,min(float(config.get('popup_wait_seconds',10)),15)))
                    while not self.stopped() and time.monotonic()<wait_until:
                        pending,_=popup_handler.close_target(parse_ui(after))
                        if pending is None or (pending['label'],pending['id'])!=(popup['label'],popup['id']):break
                        time.sleep(.5);after=self.source()
                    popup_dismissals.append({'label':label,'reason':reason,'changed':signature(parse_ui(after))!=sig})
                except Exception as e:
                    if self.stopped():raise
                    if escape_overlay(sig,nodes,'关闭弹窗时操作失败'):continue
                    issues.append({'type':'popup','error':redact(e,self.secrets)[:500]});termination='popup_blocked';break
                continue
            if popup_handler.modal_present(nodes) and allowed:
                if escape_overlay(sig,nodes,'弹窗没有可识别的关闭或取消按钮'):continue
                issues.append({'type':'popup','error':'识别到弹窗，但没有明确的关闭或取消控件，需补充可访问性标识。'})
                termination='popup_blocked';break
            if ios_bundle:
                info=self.call('POST',self.base+'/execute/sync',{'script':'mobile: activeAppInfo','args':[]})
                if info.get('bundleId')!=ios_bundle:
                    termination='outside_app';issues.append({'type':'outside_app','message':'跳转到了 App 以外的界面，停止探索。'});break
            if any(n['secure'] for n in nodes):
                reader=getattr(self,'route_reader',None)
                secure_route=reader.read() if reader else ''
                secure_key=(secure_route,path[-1] if path else '')
                if secure_route and not re.match(r'^/(?:login|staffLogin)(?:/|$)',secure_route) and path and secure_recoveries.get(secure_key,0)<2:
                    secure_recoveries[secure_key]=secure_recoveries.get(secure_key,0)+1;actions+=1
                    parent=path.pop()
                    self.log('遇到业务密码页，跳过敏感输入并返回，继续其他入口。')
                    try:
                        self.back(nodes);after=self.settled_source();after_nodes=parse_ui(after)
                        new_route=reader.read()
                        if any(n['secure'] for n in after_nodes) or re.match(r'^/(?:login|staffLogin)(?:/|$)',new_route):
                            raise RuntimeError('密码页未能安全返回或已回到登录页面')
                        new=signature(after_nodes)
                        skipped.append({'page':pages.get(parent,{}).get('id','未知'),'label':'业务密码页','route':secure_route,'reason':'已跳过密码输入并返回，未保存该页截图'})
                        visited_routes.add(secure_route)
                        secure_recoveries.pop(secure_key,None)
                        edges.append({'from':pages.get(parent,{}).get('id','未知'),'action':'secure_form_recovery','to_state':new,'expected_state':parent,'matched':new==parent})
                        if new in path:path=path[:path.index(new)]
                        continue
                    except Exception as error:
                        if self.stopped():raise
                        issues.append({'type':'secure_form_return','error':redact(error,self.secrets)[:300]})
                termination='login_or_secure_form';self.log('遇到登录或无法安全返回的密码页，停止探索，未保存该页截图。');break
            if target_package and not any(n['package']==target_package for n in nodes):
                origin=edges[-1] if edges else {}
                recovery_key=(origin.get('from',''),origin.get('label',''),origin.get('action',''))
                active=None
                if self.platform=='Android':
                    try:
                        value=self.call('GET',self.base+'/appium/device/current_package')
                        if isinstance(value,str) and value:active=value
                    except Exception:
                        if self.stopped():raise
                foreign_packages={n['package'] for n in nodes if n['package']} - popup_handler.SYSTEM_PACKAGES - {target_package}
                # A disappearing accessibility root is not proof of leaving the App.
                # Never send Back on a transient H5 tree when the App is foreground.
                if active==target_package or (active is None and not foreign_packages):
                    tree_retries[recovery_key]=tree_retries.get(recovery_key,0)+1
                    if tree_retries[recovery_key]<=3:
                        self.log('被测 App 控件树暂不可用，等待重新读取；未执行返回。')
                        self.settled_source(timeout=8)
                        continue
                    if active==target_package and getattr(self,'allow_source_recovery',False) and tree_restarts.get(recovery_key,0)<1 and sum(tree_restarts.values())<2:
                        tree_restarts[recovery_key]=1;actions+=1
                        self.log('被测 App 仍在前台但控件树持续不可用，重新打开 App 恢复探索。')
                        try:
                            self.call('POST',self.base+'/appium/device/terminate_app',{'appId':target_package})
                            self.call('POST',self.base+'/appium/device/activate_app',{'appId':target_package})
                            self.settled_source(timeout=45);tree_retries[recovery_key]=0
                            issues.append({'type':'page_tree_recovery','message':'前台仍是被测 App；控件树持续不可用，已尝试重新打开，后续以实际页面为准。'})
                            continue
                        except Exception:
                            if self.stopped():raise
                    termination='page_tree_unavailable'
                    issues.append({'type':'page_tree_unavailable','foreground_package':active,'visible_packages':sorted(packages_now),'message':'无法读取被测页面控件，未将其误报为离开 App；探索覆盖不完整。'})
                    break
                if outside_recoveries.get(recovery_key,0)<2 and actions<budget:
                    actions+=1;outside_recoveries[recovery_key]=outside_recoveries.get(recovery_key,0)+1
                    try:
                        self.log('误入 App 外部页面，返回被测 App 并继续。')
                        self.call('POST',self.base+'/back',{})
                        recovered=parse_ui(self.settled_source())
                        if not any(n['package']==target_package for n in recovered):
                            self.call('POST',self.base+'/appium/device/activate_app',{'appId':target_package})
                            recovered=parse_ui(self.settled_source())
                        if any(n['package']==target_package for n in recovered):
                            issues.append({'type':'outside_app_recovered','message':'已返回被测 App，继续其他入口。'})
                            continue
                        if self.platform=='Android':
                            value=self.call('GET',self.base+'/appium/device/current_package')
                            if isinstance(value,str):active=value
                            if active==target_package:
                                self.log('已恢复到被测 App 前台，等待页面控件就绪；未判定为外部页面。')
                                issues.append({'type':'foreground_recovered','message':'已恢复被测 App 前台；页面控件尚未就绪，继续等待核验。'})
                                continue
                    except Exception as e:issues.append({'type':'outside_app_recovery','error':redact(e,self.secrets)[:300]})
                termination='outside_app';issues.append({'type':'outside_app','foreground_package':active,'visible_packages':sorted(packages_now),'message':'外部页面恢复失败或达到恢复上限；探索覆盖不完整。'});break
            else:tree_retries.clear()
            if startup_screen(nodes):
                self.log('App 仍在启动画面，等待首页加载；此时不发送返回指令。')
                ready_source=self.settled_source(timeout=60)
                if page_ready(parse_ui(ready_source)):continue
                issues.append({'type':'startup_not_ready','error':'启动画面等待 60 秒后仍未就绪；未反复返回或重开'})
                termination='startup_not_ready';break
            if not page_ready(nodes):
                self.capture('blocked-loading-'+str(actions),source)
                if path:
                    parent=path.pop();actions+=1
                    failed_entry=active_entries.get(parent) if edges and edges[-1].get('action') in ('tap','revisit') else None
                    if failed_entry:
                        identity=failed_entry['identity'];entry_failures[identity]=entry_failures.get(identity,0)+1
                        if failed_entry['retryable'] and entry_failures[identity]<2:
                            rearm(failed_entry);self.log('目标页面未就绪，返回后允许最后一次跳转尝试。')
                        else:abandon(failed_entry,'目标页面两次仍未就绪，返回上层并跳过该入口' if failed_entry['retryable'] else '目标页面未就绪，返回上层；不重复可能写入数据的操作')
                    issues.append({'action':'load','error':'目标页面等待后仍无可交互控件，返回并继续其他入口。'})
                    try:
                        self.back(nodes);after=self.settled_source();new=signature(parse_ui(after))
                        if new==sig:
                            if blocked_recoveries.get(sig,0)>=2 or sum(blocked_recoveries.values())>=6:
                                termination='loading_recovery_failed';break
                            blocked_recoveries[sig]=blocked_recoveries.get(sig,0)+1
                            self.log('加载页面返回无效，尝试重新打开 App 后继续其他入口。')
                            recovered=self.escape_blocked_page(parse_ui(after))
                            if not recovered:
                                termination='loading_recovery_failed';break
                            new=signature(parse_ui(recovered))
                        edges.append({'from':pages.get(parent,{}).get('id','未知'),'action':'loading_recovery','to_state':new,'expected_state':parent,'matched':new==parent})
                        if new!=parent:
                            path.append(parent)
                            self.log('返回尚未到达上层页面，保留返回路径继续恢复。')
                        continue
                    except Exception as e:
                        issues.append({'action':'back','error':redact(e,self.secrets)[:500]});termination='back_failed';break
                termination='no_accessible_controls';break
            reader=getattr(self,'route_reader',None)
            route=reader.read() if reader else ''
            if route and re.match(r'^/(?:login|staffLogin)(?:/|$)',route):
                termination='login_or_secure_form';break
            remember(sig,nodes,source)
            page=pages[sig]
            page_key=page.get('navigation_key',sig)
            # Recovery can reach the root with a changed banner/text hash.
            # A later branch must not inherit the previous branch's Back budget.
            root_page=next(iter(pages.values()))
            if page_key==root_page.get('navigation_key') and not any('WebView' in n['kind'] for n in nodes):
                path=[];back_retries.clear()
            attempted_controls=attempted_by_page.setdefault(page_key,set())
            if not page_ready(nodes):
                termination='no_accessible_controls';break
            current_tabs={m.group(0) for n in nodes if (m:=re.search(r'\nTab \d+ of \d+',n['label']))}
            if len(root_tabs)>=2 and root_tabs.issubset(current_tabs):
                # Bottom-level tab switches are siblings, not nested pushes.
                # Loading recovery may also return to a root with changed text.
                path=[];back_retries.clear()
            elif sig in path:path=path[:path.index(sig)]
            auto_page=False
            if form_config.get('mode')=='auto':
                import auto_forms
                auto_page,outcome=auto_forms.visit(self,nodes,route,form_config,auto_form_cache)
                if outcome:
                    actions+=1;form_results.append(outcome)
                    self.log('自动识别表单：'+outcome['status']+' · '+outcome.get('reason',''))
                    if outcome['status'] in ('partial','blocked'):issues.append({'type':'auto_form','page':page['id'],'status':outcome['status'],'error':outcome.get('reason','')})
                    if outcome.get('stop_exploration'):termination='webview_context_failed';break
                    continue
            form_page=auto_page or (form_config.get('mode')!='auto' and form_config.get('enabled') and any(form_config['page'] in [n['label'].strip(),*[v.strip() for v in n['label'].splitlines()]] for n in nodes))
            if form_page and form_config.get('mode')!='auto' and not form_attempted:
                form_attempted=True;actions+=1;self.form_data_active=True
                self.log('开始填写指定测试表单；字段值不写入报告。')
                is_web=page.get('route')=='/webview' or any('WebView' in n['kind'] for n in nodes)
                outcome=form_runner.execute(self,form_config,web=is_web);form_results.append(outcome)
                self.log('表单结果：'+outcome['status']+' · '+outcome.get('reason',''))
                if outcome['status']!='passed':issues.append({'type':'form','page':page['id'],'status':outcome['status'],'error':outcome.get('reason','')})
                continue
            candidates=[]
            for n in ([] if form_page else nodes):
                if not n['clickable'] or n['editable']:continue
                if n.get('selected') and re.search(r'\nTab \d+ of \d+',n['label']):continue
                if target_package and n['package'] and n['package']!=target_package:continue
                key=n['path']+'|'+n['id']+'|'+n['label']
                if key in page['attempted'] or control_id(n,route) in attempted_controls:continue
                if not n['label'] and not n['id']:
                    page['attempted'].add(key);skipped.append({'page':page['id'],'label':n['kind'],'reason':'缺少可读标识，需要为控件补充可访问性标识。'});continue
                name=(n['label']+' '+n['id']).casefold()
                if route=='/webview' and n['label'].strip() in {'+','＋'}:
                    page['attempted'].add(key);attempted_controls.add(control_id(n,route))
                    skipped.append({'page':page['id'],'label':n['label'],'reason':'未明确用途的 H5 加号入口，可能打开附件或系统选择器，需专用用例绑定'});continue
                semantic=label_keys.get(n['label'].strip().casefold(),'')
                if semantic in ('logUpload','app_log_upload'):
                    page['attempted'].add(key);attempted_controls.add(control_id(n,route))
                    skipped.append({'page':page['id'],'label':redact(n['label'],self.secrets),'semantic':semantic,'reason':'日志上传需专用用例验证，本次未上传；不按跳转失败处理'});continue
                if semantic in ('logoff','logout','exit_account','mine_exit_account','delete_account','modify_pass'):
                    page['attempted'].add(key);attempted_controls.add(control_id(n,route))
                    skipped.append({'page':page['id'],'label':redact(n['label'],self.secrets),'semantic':semantic,'reason':'敏感账号操作，使用专用用例验证，不参与通用探索'});continue
                nested=' '.join(v['label'] for v in nodes if v['path'].startswith(n['path']+'/')).casefold()
                blocked=next((word for word in words if word in name+' '+nested),None)
                if blocked:
                    page['attempted'].add(key);skipped.append({'page':page['id'],'label':redact(n['label'] or n['id'] or n['kind'],self.secrets),'reason':'跳过关键词：'+blocked});continue
                if re.fullmatch(r'返回|后退|关闭|back|close',n['label'],re.I):continue
                candidates.append((key,n))
            if candidates and len(path)>=max_depth:
                retained=[]
                for item in candidates:
                    if route=='/language' or local_action(item[1]):retained.append(item)
                    else:depth_pruned.add((page_key,control_id(item[1],route)))
                candidates=retained
            depth_limited=any(control not in attempted_by_page.get(context,set()) for context,control in depth_pruned)
            if candidates:
                # Finish this tab's content before switching to another tab.
                candidates.sort(key=lambda item: 3 if re.search(r'\nTab \d+ of \d+',item[1]['label']) else 1 if item[1]['label'].strip() in entry_labels else 2)
                key,node=candidates[0];page['attempted'].add(key);attempted_controls.add(control_id(node,route))
                label=redact(node['label'] or node['id'] or node['kind'],self.secrets)
                self.log('自动点击 '+page['id']+'：'+label[:100])
                try:enter(sig,page,node,key)
                except Exception as e:issues.append({'page':page['id'],'action':'tap','label':label,'error':redact(e,self.secrets)[:500]})
                continue
            if any(n['scrollable'] for n in nodes) and scrolls.get(page_key,0)<max_scrolls:
                scrolls[page_key]=scrolls.get(page_key,0)+1;actions+=1
                try:
                    self.scroll()
                    after_source=self.settled_source();after=parse_ui(after_source);new=signature(after)
                    remember(new,after,after_source)
                    edges.append({'from':page['id'],'action':'scroll','to_state':new,'changed':new!=sig})
                except Exception as e:issues.append({'page':page['id'],'action':'scroll','error':redact(e,self.secrets)[:500]})
                continue
            for previous_page in pages.values():
                if previous_page.get('navigation_key')==page_key:previous_page['exhausted']=True
            page['exhausted']=True
            if not path:
                # Tabs form cycles. Revisit known branches that still have untried controls.
                queue=[(sig,[])];visited={sig};route=[]
                while queue:
                    current,steps=queue.pop(0)
                    if current!=sig and current in pages and not pages[current]['exhausted']:
                        if steps:
                            first=steps[0]
                            possible=[n for n in nodes if n['clickable'] and (control_id(n,page.get('route',''))==tuple(first.get('control',())) or n['label']==first['label'] and n['id']==first['id'])]
                            if len(possible)==1:route=steps;break
                    for edge in nav_edges.get(current,[]):
                        identity=(pages.get(current,{}).get('navigation_key',current),edge['id'],edge['label'])
                        if identity in blocked_entries:continue
                        if edge['target'] not in visited:
                            visited.add(edge['target']);queue.append((edge['target'],steps+[edge]))
                    # Scrolling changes the state hash while leaving the same
                    # navigation context. Reuse its previously observed exits.
                    context=pages.get(current,{}).get('navigation_key')
                    for alias,known_page in pages.items():
                        if context and alias not in visited and known_page.get('navigation_key')==context:
                            visited.add(alias);queue.append((alias,steps))
                if route:
                    step=route[0]
                    matches=[n for n in nodes if n['clickable'] and (control_id(n,page.get('route',''))==tuple(step.get('control',())) or n['label']==step['label'] and n['id']==step['id'])]
                    node=matches[0] if len(matches)==1 else None
                    if node:
                        # 反复进出同一分支（进入成功、返回也成功）不会触发任何失败计数，
                        # 必须单独限制重访次数，否则空状态 H5 页会造成无限往返。
                        revisit_key=(page.get('navigation_key',sig),step.get('id'),step['label'])
                        revisit_counts[revisit_key]=revisit_counts.get(revisit_key,0)+1
                        if revisit_counts[revisit_key]>2:
                            blocked_entries.add(revisit_key)
                            target_key=pages.get(step['target'],{}).get('navigation_key')
                            for known in pages.values():
                                if target_key and known.get('navigation_key')==target_key:known['exhausted']=True
                            if step['target'] in pages:pages[step['target']]['exhausted']=True
                            self.log('该分支已反复进出仍未展开，标记为不再重试：'+redact(node['label'],self.secrets))
                            continue
                        self.log('继续未完成分支：'+redact(node['label'],self.secrets))
                        try:
                            raw_key=node['path']+'|'+node['id']+'|'+node['label']
                            if not enter(sig,page,node,raw_key,'revisit'):pages.get(step['target'],{})['exhausted']=True
                            continue
                        except Exception as e:issues.append({'action':'revisit','error':redact(e,self.secrets)[:300]})
                pending=any(not p['exhausted'] for p in pages.values())
                if pending and not depth_limited and target_package and final_restarts<1 and actions<budget and time.monotonic()<deadline and not self.stopped():
                    # 收尾仍有未达分支时，重开 App 回到首页再做一轮分支重访，
                    # 常可经由底部 Tab 重新进入此前"无法返回"的入口。
                    final_restarts=1;actions+=1
                    self.log('仍有入口无法返回，重新打开 App 后再做一轮分支重访。')
                    try:
                        self.call('POST',self.base+'/appium/device/terminate_app',{'appId':target_package})
                        self.call('POST',self.base+'/appium/device/activate_app',{'appId':target_package})
                        self.settled_source(timeout=45)
                        continue
                    except Exception as e:
                        if self.stopped():raise
                        issues.append({'type':'navigation','error':redact(e,self.secrets)[:300]})
                if pending and not depth_limited and not final_restarts:
                    issues.append({'type':'navigation','error':'仍有已发现入口未探索，但当前页面无法返回这些入口；本次覆盖不完整。'})
                termination='depth_limit' if depth_limited else 'unreachable_pending_branches' if pending else 'reachable_controls_exhausted';break
            parent=path.pop();actions+=1
            try:
                leaving_form=form_page
                self.log('测试返回：'+page['id']);self.back(nodes)
                after_nodes=parse_ui(self.settled_source());new=signature(after_nodes)
                if new==sig:
                    self.log('返回指令未改变页面，尝试恢复被卡住的分支。')
                    recovered=self.escape_blocked_page(nodes)
                    if not recovered:
                        issues.append({'page':page['id'],'action':'back','error':'返回及恢复后页面仍未变化。'})
                        termination='back_failed';break
                    after_nodes=parse_ui(recovered);new=signature(after_nodes)
                edges.append({'from':page['id'],'action':'back','to_state':new,'expected_state':parent,'matched':new==parent})
                # The root may change banners, locale and selected tab after a
                # relaunch. Confirm its route before spending a stale Back budget.
                reader=getattr(self,'route_reader',None)
                returned_route=reader.read() if reader else ''
                root_route=next(iter(pages.values())).get('route','')
                if returned_route and returned_route==root_route:
                    fresh=self.wait_root_snapshot(root_route,target_package)
                    if fresh:
                        after_nodes=parse_ui(fresh);new=signature(after_nodes)
                        edges[-1]['to_state']=new
                    elif not self.stopped():
                        issues.append({'type':'root_snapshot_unavailable','error':'首页路由已返回，但页面控件未同步就绪；未继续使用旧分支返回计数'})
                        path.append(parent);back_retries.pop(parent,None)
                        # Reuse the bounded accessibility recovery rather than
                        # sending Back again on the startup screen.
                        root_waits=getattr(self,'root_snapshot_waits',0)+1;self.root_snapshot_waits=root_waits
                        if root_waits>=2 and target_package and not self.stopped():
                            actions+=1
                            self.log('首页控件持续未就绪，重新打开 App 后再等待一次。')
                            try:
                                self.call('POST',self.base+'/appium/device/terminate_app',{'appId':target_package})
                                self.call('POST',self.base+'/appium/device/activate_app',{'appId':target_package})
                            except Exception as error:
                                if self.stopped():raise
                            self.settled_source(timeout=45)
                            fresh=self.wait_root_snapshot(root_route,target_package,timeout=30) if root_route else None
                            if fresh:
                                self.root_snapshot_waits=0;path=[];back_retries.clear()
                                issues.append({'type':'root_snapshot_recovered','message':'重开 App 后首页控件就绪，继续探索其他入口。'})
                                continue
                        if root_waits>=2:termination='root_snapshot_unavailable';break
                        continue
                if returned_route and returned_route==root_route and page_ready(after_nodes) and (not target_package or any(n['package']==target_package for n in after_nodes)) and not any('WebView' in n['kind'] or n['secure'] for n in after_nodes):
                    edges[-1]['matched_root_route']=True
                    path=[];back_retries.clear();leaving_form=False
                    self.root_snapshot_waits=0
                    self.log('已确认返回首页路由，清除旧分支返回计数，继续其他入口。')
                    continue
                if new!=parent:
                    issues.append({'page':page['id'],'action':'back','error':'返回后页面状态变化，重新识别当前 App 页面并继续探索。'})
                    self.log('返回后页面发生变化，继续识别可达控件。')
                    if new in path:path=path[:path.index(new)]
                    elif (len(root_tabs)>=2 and not root_tabs.issubset({m.group(0) for n in after_nodes if (m:=re.search(r'\nTab \d+ of \d+',n['label']))})) or any('WebView' in n['kind'] for n in after_nodes):
                        back_retries[parent]=back_retries.get(parent,0)+1
                        if back_retries[parent]>3:
                            issues.append({'type':'navigation','error':'连续返回仍未恢复上层页面，保留未覆盖入口，停止当前探索。'})
                            termination='back_failed';break
                        path.append(parent)
                        self.log('尚未返回上层页面，保留未探索入口并继续返回（最多 3 次）。')
                else:back_retries.pop(parent,None)
            except Exception as e:
                issues.append({'page':page['id'],'action':'back','error':redact(e,self.secrets)[:500]});termination='back_failed';break
        if form_config.get('enabled') and form_config.get('mode')!='auto' and not form_results:
            form_results.append({'page':form_config['page'],'status':'not_reached','submitted':False,'reason':'未到达指定表单页面，未执行填写或提交'})
            issues.append({'type':'form','status':'not_reached','error':'未到达指定表单页面'})
        for edge in edges:
            edge['to']=pages.get(edge['to_state'],{}).get('id','未继续采集')
        return {'pages':[{'state':sig,**{k:v for k,v in p.items() if k!='attempted'},'attempted_controls':len(p['attempted'])} for sig,p in pages.items()],'transitions':edges,'skipped':skipped,'issues':issues,'actions':actions,'termination':termination,'popup_dismissals':popup_dismissals,'observations':observations,'forms':form_results,'form_mode':form_config.get('mode','manual'),'source_coverage':__import__('source_navigation').coverage(plan,visited_routes,getattr(self,'route_reader',None),skipped,termination),'coverage_note':'基于可访问控件的有限探索，不代表所有页面、业务分支或接口均已验证。'+('自动填表仅验证输入状态，未执行提交验收。' if form_config.get('mode')=='auto' else '')}
