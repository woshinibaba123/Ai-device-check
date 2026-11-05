"""Explicitly authorized Keenon onboarding; no coordinates or generic consent clicks."""
import re
import time

AGREE={'同意并继续','继续并同意','agree and continue','agree & continue'}
PASSWORD={'账号密码登录','帐号密码登录','password login','log in with password','account password login','login by pwd'}
NEXT={'下一步','next'}
CHINA={'中国','中国大陆','china','china mainland','mainland china','china (cn)','中国 (cn)'}

def normalized(text):return re.sub(r'\s+',' ',text.strip()).lower()

def matching(nodes, labels):
    return [n for n in nodes if normalized(n['label']) in labels]

def prepare(explorer):
    from automation import parse_ui, LoginBlocked
    deadline=time.monotonic()+90
    country_open=False; country_open_since=0; searched=False; country_selected=False; taps=0
    unrecognized_since=None
    while time.monotonic()<deadline and taps<20:
        if explorer.stopped():raise LoginBlocked('登录前流程已停止。')
        nodes=parse_ui(explorer.wait_ui())
        fields=[n for n in nodes if n['editable']]
        if any(n['secure'] for n in fields):
            explorer.log('已进入账号密码登录页。')
            return
        if len(fields)>=2 and matching(nodes,PASSWORD):
            explorer.log('已到达登录页；此版本需先输入账号，才能判断并切换密码登录。')
            return
        target=None
        for labels, message in [(AGREE,'自动同意并继续。'),(PASSWORD,'自动切换账号密码登录。')]:
            found=matching(nodes,labels)
            if len(found)==1:
                target=found[0];explorer.log(message);break
        if target is None and country_open:
            found=matching(nodes,CHINA)
            if found:
                target=next((n for n in found if n['clickable']),found[-1])
                country_open=False;country_selected=True
                explorer.log('选择中国，保留 App 自动匹配的数据中心。')
            elif fields and not searched:
                explorer.type(explorer.find({'by':'xpath','value':fields[0]['path']}),'China',fields[0])
                searched=True;time.sleep(.5);continue
            else:
                if time.monotonic()-country_open_since<20:
                    time.sleep(.7);continue
                raise LoginBlocked('国家列表等待 20 秒后仍未识别中国；未修改数据中心。')
        if target is None:
            next_buttons=matching(nodes,NEXT)
            is_config=any(normalized(n['label']) in {'国家或区域','国家或地区','country or region','country/region','data center','数据中心'} for n in nodes)
            if is_config and next_buttons:
                china=matching(nodes,CHINA)
                if not country_selected:
                    # First placeholder belongs to country; data center is never selected directly.
                    choices=matching(nodes,{'请选择','please select','select'})
                    if choices:
                        target=choices[0];country_open=True;country_open_since=time.monotonic()
                        explorer.log('打开国家或地区选择。')
                    elif china:
                        country_selected=True
                    else:
                        raise LoginBlocked('国家尚未确认中国，未继续；请检查国家选择控件。')
                if target is None and country_selected:
                    if matching(nodes,{'请选择','please select','select'}):
                        time.sleep(.5);continue
                    target=next_buttons[0];explorer.log('点击下一步。')
        if target is None:
            now=time.monotonic()
            dialog=next((n for n in nodes if n['clickable'] and normalized(n['label']) in {'ok','got it','确定','知道了','我知道了','以后再说','稍后','later','dismiss',"don't show again","dont show again"}),None)
            if dialog:
                explorer.log('关闭系统弹窗：'+(dialog['label'][:30] or dialog['kind']))
                explorer.tap(dialog);taps+=1;time.sleep(.7);continue
            if unrecognized_since is None: unrecognized_since=now
            if now-unrecognized_since<10:
                time.sleep(1);continue
            raise LoginBlocked('未识别到预设登录前页面；未继续点击。请检查 App 版本或使用自定义流程。')
        unrecognized_since=None
        explorer.tap(target);taps+=1;time.sleep(.7)
    raise LoginBlocked('登录前流程超过时间或操作次数上限。')

def agree_checkbox(explorer):
    from automation import parse_ui, LoginBlocked
    nodes=parse_ui(explorer.source())
    boxes=[n for n in nodes if 'CheckBox' in n['kind'] or n['kind']=='XCUIElementTypeSwitch']
    if len(boxes)>1:raise LoginBlocked('登录页存在多个勾选框，无法确认协议勾选框。')
    if boxes and not boxes[0]['checked']:
        explorer.tap(boxes[0]);explorer.log('勾选登录协议。')

def agree_dialog(explorer):
    from automation import parse_ui
    nodes=parse_ui(explorer.source())
    buttons=matching(nodes,{'同意并登录','同意并登陆','agree and log in','agree and login','agree and sign in'})
    if len(buttons)==1:explorer.tap(buttons[0]);explorer.log('确认同意并登录。')


ONBOARDING_LABELS={'skip','agree with','同意','允许','next','got it','确定','知道了','我知道了','以后再说','关闭','close','取消','cancel','暂不','稍后','later','跳过'}

def dismiss_onboarding(explorer):
    """登录成功后依次关闭引导轮播、隐私更新弹窗、气泡提示；绝不点击不同意/退出。"""
    from automation import parse_ui
    quiet=0;taps=0
    deadline=time.monotonic()+25
    while time.monotonic()<deadline and taps<15:
        if explorer.stopped():return
        nodes=parse_ui(explorer.source())
        import popup_handler
        target,_=popup_handler.close_target(nodes)
        if target is None:target,_=popup_handler.permission_target(nodes)
        if target is None:
            quiet+=1
            if quiet>=2:explorer.log('引导弹窗已清理完毕。') if taps else None
            if quiet>=2:return
            time.sleep(1);continue
        quiet=0;taps+=1
        explorer.log('关闭引导弹层：'+target['label'][:30])
        explorer.tap(target);time.sleep(1)


PASSWORD_MODE_SWITCH={'验证码登录','验证码登陆','login by verify','verification code login'}
ACCOUNT_ERRORS={'账号信息获取失败，请检查网络后重试','unable to check account. please retry'}

def password_field(nodes):
    secure=next((n for n in nodes if n['editable'] and n['secure']),None)
    if secure:return secure
    # Visible-password fields may not carry the platform secure flag. Require the
    # password-mode switch AND an editable field whose OWN label IS the password
    # label; free page text like "Forgot Password" must never count.
    fields=[n for n in nodes if n['editable']]
    if len(fields)==2 and matching(nodes,PASSWORD_MODE_SWITCH) and any(re.fullmatch(r'(?:password|密码)',n['label'].strip(),re.I) for n in fields):
        return fields[-1]
    return None

def dismiss_keyboard(explorer):
    if explorer.platform=='Android':
        try:explorer.call('POST',explorer.base+'/appium/device/hide_keyboard',{})
        except Exception:
            if explorer.stopped():
                from automation import LoginBlocked
                raise LoginBlocked('登录已停止。')

def wait_login_snapshot(explorer, timeout=12):
    """An empty Flutter semantics frame is not evidence of a mode change."""
    from automation import parse_ui, LoginBlocked
    deadline=time.monotonic()+timeout
    while True:
        if explorer.stopped():raise LoginBlocked('登录已停止。')
        nodes=parse_ui(explorer.source())
        if password_field(nodes) or (sum(n['editable'] for n in nodes)>=2 and matching(nodes,PASSWORD)):
            return nodes
        if time.monotonic()>=deadline:
            raise LoginBlocked('登录控件暂不可读或页面未稳定，未将其判为验证码模式，未继续填写或提交。')
        time.sleep(.5)

def ensure_password(explorer):
    from automation import parse_ui, LoginBlocked
    nodes=parse_ui(explorer.source())
    # Hiding the keyboard alone leaves Flutter's account Focus active. Move focus
    # to the empty second field before switching modes so its blur callback and
    # account lookup cannot reset a password mode selected moments earlier.
    if not getattr(explorer, '_account_focus_settled', False):
        fields=[n for n in nodes if n['editable']]
        if len(fields)==2 and (fields[1]['bounds'] or explorer.platform=='iOS'):
            explorer.tap(fields[1])
            explorer._account_focus_settled=True
            explorer.log('先让账号框失焦，等待账号判断，再切换密码模式。')
            time.sleep(1.3)
            nodes=parse_ui(explorer.source())
    if password_field(nodes):return
    dismiss_keyboard(explorer)
    explorer.log('收起键盘，等待账号输入及账号类型判断完成。')
    deadline=time.monotonic()+45
    ready_at=time.monotonic()+1
    last_click=None;clicks=0;last_state=None;last_error_click=None
    while time.monotonic()<deadline:
        if explorer.stopped():raise LoginBlocked('登录已停止。')
        nodes=parse_ui(explorer.source())
        if password_field(nodes):
            pf=password_field(nodes)
            labels='; '.join((n['label'] or n['kind'])+'@'+n['bounds'] for n in nodes if n['editable'])
            explorer.log('已识别密码输入框：'+(pf['label'] or pf['kind'])+' bounds='+pf['bounds']+'；页面输入框：'+labels)
            return
        buttons=matching(nodes,PASSWORD)
        now=time.monotonic()
        if matching(nodes,ACCOUNT_ERRORS):
            if not buttons or clicks>=2:
                raise LoginBlocked('App 提示账号信息获取失败，请检查测试账号对应的环境和网络；尚未发送登录请求。')
            if last_error_click!=clicks:
                last_error_click=clicks;ready_at=now+3
                explorer.log('账号类型查询暂时失败，等待提示消失后重试一次模式切换。')
        if len(buttons)==1 and now>=ready_at and clicks<2 and (last_click is None or now-last_click>=13):
            dismiss_keyboard(explorer)
            explorer.tap(buttons[0]);clicks+=1;last_click=time.monotonic()
            # A slow driver call must not consume the response window for the
            # click it just completed, nor make two real clicks occur back-to-back.
            deadline=max(deadline,last_click+15)
            explorer.log('点击账号密码登录，等待页面切换（第 '+str(clicks)+' 次）。')
        state='验证码模式' if buttons else '未识别到模式切换按钮'
        if state!=last_state:
            explorer.log('当前登录页：'+state+'，可识别输入框 '+str(sum(n['editable'] for n in nodes))+' 个。')
            last_state=state
        time.sleep(.5)
    raise LoginBlocked('45 秒内仍未识别密码输入框；已收起键盘并最多尝试两次切换，未填密码、未发送验证码或登录请求。')


def fill_account(explorer, account, selector=None):
    """Do not switch login mode until the account field reports the actual value."""
    from automation import parse_ui, LoginBlocked
    selector=selector or {}
    def locate():
        if selector.get('value','').strip():
            return explorer.find(selector), None
        fields=[n for n in parse_ui(explorer.source()) if n['editable'] and not n['secure']]
        if not fields:return None,None
        return explorer.find({'by':'xpath','value':fields[0]['path']}), fields[0]
    expected=account.strip();writes=0;stable=0
    # Native typing and a Flutter semantics refresh can each take several
    # seconds on a cold emulator. Allow two confirmed reads after that work.
    deadline=time.monotonic()+60;next_write=0
    while time.monotonic()<deadline:
        if explorer.stopped():raise LoginBlocked('登录已停止。')
        eid,node=locate()
        if eid is None:
            stable=0;time.sleep(.5);continue
        now=time.monotonic()
        if writes<2 and stable==0 and now>=next_write:
            explorer._account_focus_settled=False
            if writes==0:explorer.type(eid,account,node)
            else:
                explorer.log('账号回读未确认，改用字段定向输入重试一次；未提交登录。')
                explorer.call('POST',explorer.base+'/element/'+eid+'/clear',{})
                explorer.call('POST',explorer.base+'/element/'+eid+'/value',{'text':account})
            writes+=1;next_write=now+3
        value=None
        try:value=explorer.call('GET',explorer.base+'/element/'+eid+'/text')
        except Exception:
            if explorer.stopped():raise LoginBlocked('登录已停止。')
        matches=isinstance(value,str) and value.strip()==expected
        if not matches:
            try:
                raw=explorer.call('GET',explorer.base+'/element/'+eid+'/attribute/value')
                matches=isinstance(raw,str) and raw.strip()==expected
            except Exception:
                if explorer.stopped():raise LoginBlocked('登录已停止。')
        if not matches and node is not None:
            # Flutter can replace the element reference after typing. Verify fresh UI data in memory.
            fresh=[n for n in parse_ui(explorer.source()) if n['editable'] and not n['secure']]
            if fresh:matches=any(isinstance(value,str) and value.strip()==expected for value in (fresh[0]['label'],fresh[0]['value']))
        stable=stable+1 if matches else 0
        if stable>=2:
            explorer.log('已确认测试账号填入输入框，接下来判断账号类型并切换密码登录。')
            return
        time.sleep(.3)
    raise LoginBlocked('账号输入内容未能确认，未点击账号密码登录；请检查账号输入框定位。')


def wait_post_login(explorer, sleep, timeout=90):
    """A successful API callback can precede navigation and leave a loading overlay."""
    from automation import parse_ui, has_controls, LoginBlocked
    deadline=time.monotonic()+timeout
    markers=('password','login by verify','other login methods','already read and agree')
    while time.monotonic()<deadline:
        if explorer.stopped():raise LoginBlocked('登录等待已停止。')
        nodes=parse_ui(explorer.source())
        labels=' '.join(n['label'].casefold() for n in nodes)
        reader=getattr(explorer,'route_reader',None)
        route=reader.read() if reader else ''
        if has_controls(nodes) and not any(n['editable'] for n in nodes) and not any(m in labels for m in markers) and not route.startswith('/login'):
            return
        sleep(.7)
    raise LoginBlocked('登录接口已确认成功，但登录后的页面持续加载，90 秒内未就绪。')
