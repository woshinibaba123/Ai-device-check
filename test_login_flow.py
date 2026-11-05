import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from automation import Explorer, LoginBlocked, parse_ui
import login_flow
import login_probe

class Driver:
    def __init__(self, language='zh'):
        self.state='agreement';self.clicked=[];self.typed=[];self.checked=False;self.language=language
    def source(self):
        values={'agreement':[('button','同意并继续')], 'config':[('text','国家或区域'),('button','请选择'),('text','数据中心'),('button','请选择'),('button','下一步')], 'countries':[('edit','search'),('button','中国')], 'selected':[('text','国家或区域'),('button','中国'),('text','数据中心'),('text','中国数据中心'),('button','下一步')], 'verify':[('edit','账号'),('edit','验证码'),('button','账号密码登录')], 'password':[('edit','账号'),('password','密码'),('check',''),('button','登录')], 'done':[('button','首页')]}
        nodes=[]
        for kind,label in values[self.state]:
            cls={'button':'android.widget.Button','text':'android.widget.TextView','edit':'android.widget.EditText','password':'android.widget.EditText','check':'android.widget.CheckBox'}[kind]
            nodes.append(f'<node class="{cls}" text="{label}" clickable="{str(kind in ("button","check")).lower()}" password="{str(kind=="password").lower()}" checked="{str(self.checked).lower()}"/>')
        return '<hierarchy>'+''.join(nodes)+'</hierarchy>'
    def tap(self,node):
        label=node['label'];self.clicked.append(label)
        self.state={'同意并继续':'config','请选择':'countries','中国':'selected','下一步':'verify','账号密码登录':'password','登录':'done'}.get(label,self.state)
        if 'CheckBox' in node['kind']:self.checked=True
    def wait_ui(self):return self.source()
    def stopped(self):return False
    def log(self,*args):pass

class LoginFlowTests(unittest.TestCase):
    def test_success_probe_precedes_unavailable_post_submit_ui(self):
        from test_automation import FakeDriver
        from unittest.mock import Mock
        d=FakeDriver(login=True)
        exp=Explorer(d,'s','Android',lambda *a:None,lambda *a:self.fail('login capture'))
        exp.login_probe=Mock();exp.login_probe.read.side_effect=lambda:d.state=='A'
        with patch('login_flow.fill_account',side_effect=lambda exp,account,sel:exp.type(exp.find({'by':'xpath','value':parse_ui(exp.source())[1]['path']}),account)),patch('login_flow.prepare'),patch('login_flow.agree_checkbox'),patch('login_flow.agree_dialog',side_effect=RuntimeError('AccessibilityNodeInfo unavailable')):
            result=exp.login({'enabled':True,'flow':'keenon_china','account':'test','password':'secret'})
        self.assertEqual(result['confirmation'],'login_api_success_callback')

    def test_all_prelogin_pages_and_skip_data_center(self):
        d=Driver()
        with patch('login_flow.time.sleep'):login_flow.prepare(d)
        self.assertEqual(d.clicked,['同意并继续','请选择','中国','下一步'])
        self.assertEqual(d.state,'verify')
        d.state='password'
        login_flow.agree_checkbox(d)
        self.assertTrue(d.checked)
        login_flow.agree_checkbox(d)
        self.assertEqual(d.clicked.count(''),1)
    def test_existing_password_screen_does_not_repeat_steps(self):
        d=Driver();d.state='password';login_flow.prepare(d);self.assertFalse(d.clicked)
    def test_unknown_screen_stops(self):
        d=Driver();d.state='done'
        with self.assertRaises(LoginBlocked):login_flow.prepare(d)
    def test_probe_does_not_store_credentials_or_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);file=root/login_probe.REPOSITORY;file.parent.mkdir(parents=True)
            file.write_text("success?.call(ResultBean.event(true));\nsuccess?.call(ResultBean.event(true));\n  /// 医疗账号登录后校验\nother")
            name=login_probe.instrument(root)
            self.assertIn(name,file.read_text());self.assertEqual(file.read_text().count('writeAsStringSync'),2)
            self.assertNotIn('accessToken',file.read_text());self.assertNotIn('password',file.read_text())
    def test_changed_source_blocks_instrumentation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):login_probe.validate(Path(tmp))
    def test_stale_event_reset_and_business_success(self):
        calls=[]
        def command(args):
            calls.append(args)
            return {'ok':True,'output':'{"success":true}' if 'cat' in args else ''}
        p=login_probe.Probe('Android','emulator-1','com.example','devicecheck-login-'+'a'*32+'.json',command,'adb')
        p.reset();self.assertIn('rm',calls[0]);self.assertTrue(p.read())

    def test_interface_callback_confirms_without_page_marker(self):
        from test_automation import FakeDriver
        from unittest.mock import Mock
        d=FakeDriver(login=True)
        exp=Explorer(d,'s','Android',lambda *a:None,lambda *a:self.fail('login capture'))
        exp.login_probe=Mock();exp.login_probe.read.return_value=True
        with patch('login_flow.fill_account',side_effect=lambda exp,account,sel:exp.type(exp.find({'by':'xpath','value':parse_ui(exp.source())[1]['path']}),account)),patch('login_flow.prepare'),patch('login_flow.agree_checkbox'),patch('login_flow.agree_dialog'):
            result=exp.login({'enabled':True,'flow':'keenon_china','account':'test','password':'secret'})
        self.assertEqual(result['confirmation'],'login_api_success_callback')
        exp.login_probe.reset.assert_called_once()

    def test_interface_callback_required_even_if_home_visible(self):
        from test_automation import FakeDriver
        from unittest.mock import Mock
        d=FakeDriver(login=True)
        exp=Explorer(d,'s','Android',lambda *a:None,lambda *a:None)
        exp.login_probe=Mock();exp.login_probe.read.return_value=False
        import itertools
        clock=itertools.count(0,31)
        with patch('login_flow.fill_account',side_effect=lambda exp,account,sel:exp.type(exp.find({'by':'xpath','value':parse_ui(exp.source())[1]['path']}),account)),patch('login_flow.prepare'),patch('login_flow.agree_checkbox'),patch('login_flow.agree_dialog'),patch('automation.time.monotonic',side_effect=lambda:next(clock)),patch('automation.time.sleep'):
            with self.assertRaises(LoginBlocked):exp.login({'enabled':True,'flow':'keenon_china','account':'test','password':'secret','success':{'value':'首页'}})

    def test_password_switch_hides_keyboard_before_click(self):
        import itertools
        d=Driver();d.state='verify';d.platform='Android';d.base='/session/s';events=[]
        d.call=lambda *args:events.append('hide_keyboard')
        original=d.tap
        def tap(node):
            self.assertIn('hide_keyboard',events)
            events.append('tap');original(node)
        d.tap=tap
        ticks=itertools.count()
        with patch('login_flow.time.sleep'),patch('login_flow.time.monotonic',side_effect=lambda:next(ticks)*.5):
            login_flow.ensure_password(d)
        self.assertEqual(d.state,'password');self.assertEqual(events.count('tap'),1)

    def test_app_account_query_error_is_reported(self):
        d=Driver();d.platform='Android';d.base='/session/s';d.call=lambda *a:None
        d.source=lambda:'<hierarchy><node class="android.widget.TextView" text="Unable to check account. Please retry"/></hierarchy>'
        with self.assertRaisesRegex(LoginBlocked,'账号信息获取失败'):
            login_flow.ensure_password(d)

    def test_plain_verification_field_is_never_used_as_password(self):
        from automation import parse_ui
        d=Driver();d.state='verify'
        self.assertIsNone(login_flow.password_field(parse_ui(d.source())))

    def test_account_value_is_confirmed_before_continuing(self):
        from unittest.mock import Mock
        exp=Mock();exp.base='/session/s';exp.stopped.return_value=False
        exp.find.return_value='account';exp.call.return_value='test-account'
        with patch('login_flow.time.sleep'):
            login_flow.fill_account(exp,'test-account',{'by':'id','value':'account'})
        exp.type.assert_called_once_with('account','test-account',None)
        self.assertGreaterEqual(exp.call.call_count,2)
        exp.tap.assert_not_called()
        self.assertNotIn('test-account',str(exp.log.call_args_list))

    def test_empty_account_field_blocks_mode_switch(self):
        from unittest.mock import Mock
        import itertools
        exp=Mock();exp.base='/session/s';exp.stopped.return_value=False
        exp.find.return_value='account';exp.call.return_value=''
        ticks=itertools.count()
        with patch('login_flow.time.sleep'),patch('login_flow.time.monotonic',side_effect=lambda:next(ticks)*.5):
            with self.assertRaisesRegex(LoginBlocked,'账号输入内容未能确认'):
                login_flow.fill_account(exp,'test-account',{'by':'id','value':'account'})
        exp.tap.assert_not_called()
        self.assertLessEqual(exp.type.call_count,2)

class FreshAccountReadTests(unittest.TestCase):
    def test_slow_native_typing_still_allows_two_confirmed_reads(self):
        from unittest.mock import Mock,patch
        import login_flow
        exp=Mock();exp.base='/session/s';exp.stopped.return_value=False
        exp.find.return_value='account';exp.call.return_value='test-account'
        with patch('login_flow.time.sleep'),patch('login_flow.time.monotonic',side_effect=[0,0,0,25,26]):
            login_flow.fill_account(exp,'test-account',{'by':'id','value':'account'})
        exp.type.assert_called_once()
        self.assertEqual(exp.call.call_count,2)

    def test_rebuilt_flutter_element_uses_fresh_field_value(self):
        from unittest.mock import Mock,patch
        import login_flow
        exp=Mock();exp.stopped.return_value=False;exp.find.return_value='stale'
        exp.source.return_value='<hierarchy><node class="android.widget.EditText" text="test-account"/></hierarchy>'
        exp.call.return_value=''
        with patch('login_flow.time.sleep'):
            login_flow.fill_account(exp,'test-account')
        exp.type.assert_called_once()
        self.assertNotIn('test-account',str(exp.log.call_args_list))

class PostLoginReadinessTests(unittest.TestCase):
    def test_clickable_loading_surface_is_not_ready(self):
        from unittest.mock import Mock
        import login_flow
        from test_automation import A
        exp=Mock();exp.stopped.return_value=False
        exp.source.side_effect=['<hierarchy><node class="android.view.View" clickable="true"/></hierarchy>',A]
        exp.route_reader.read.side_effect=['/login','/main']
        sleep=Mock();login_flow.wait_post_login(exp,sleep)
        sleep.assert_called_once()
        self.assertEqual(exp.source.call_count,2)

class CountryLoadingTests(unittest.TestCase):
    def test_waits_for_country_picker_to_finish_opening(self):
        class Delayed(Driver):
            def __init__(self):super().__init__();self.loading=0
            def tap(self,node):
                super().tap(node)
                if node['label']=='请选择':self.loading=2
            def source(self):
                if self.loading:
                    self.loading-=1
                    return '<hierarchy><node class="android.widget.Button" text="Next" clickable="true"/></hierarchy>'
                return super().source()
        d=Delayed()
        with patch('login_flow.time.sleep'):login_flow.prepare(d)
        self.assertEqual(d.state,'verify');self.assertIn('中国',d.clicked)

class AsyncModeSwitchTests(unittest.TestCase):
    def test_slow_click_keeps_a_response_window(self):
        now=[0.0]
        d=Driver();d.state='verify';d.platform='Android';d.base='/session/s';d.call=lambda *args:None
        original=d.tap
        def tap(node):
            now[0]+=60
            original(node)
        d.tap=tap
        with patch('login_flow.time.monotonic',side_effect=lambda:now[0]),patch('login_flow.time.sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)):
            login_flow.ensure_password(d)
        self.assertEqual(d.state,'password')
        self.assertEqual(d.clicked,['账号密码登录'])

    def test_does_not_cancel_slow_account_query_by_clicking_twice(self):
        now=[0.0];pending=[None]
        d=Driver();d.state='verify';d.platform='Android';d.base='/session/s';d.call=lambda *args:None
        source=d.source
        def read():
            if pending[0] is not None and now[0]>=pending[0]+10:d.state='password'
            return source()
        def tap(node):
            d.clicked.append(node['label'])
            if node['label']=='账号密码登录':pending[0]=now[0]
        d.source=read;d.tap=tap
        with patch('login_flow.time.monotonic',side_effect=lambda:now[0]),patch('login_flow.time.sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)):
            login_flow.ensure_password(d)
        self.assertEqual(d.clicked,['账号密码登录'])
        self.assertEqual(d.state,'password')

class AccountFocusOrderTests(unittest.TestCase):
    def test_account_blurs_before_password_switch(self):
        d=Driver();d.state='verify';d.platform='Android';d.base='/session/s'
        d.call=lambda *a:None
        original_source=d.source
        d.source=lambda:original_source().replace('class="android.widget.EditText"', 'bounds="[10,10][100,60]" class="android.widget.EditText"')
        original_tap=d.tap;events=[]
        def tap(node):
            events.append(node['label'])
            if node['label']=='账号密码登录':self.assertIn('验证码',events)
            original_tap(node)
        d.tap=tap
        with patch('login_flow.time.sleep'):
            login_flow.ensure_password(d)
        self.assertEqual(events[:2],['验证码','账号密码登录'])
        self.assertEqual(d.state,'password')

class LoginFailureEvidenceTests(unittest.TestCase):
    def test_failure_code_is_reported_without_response_body(self):
        def command(args):return {'ok':True,'output':'{"success":false,"code":610123}'}
        probe=login_probe.Probe('Android','emulator-1','com.example','devicecheck-login-'+'a'*32+'.json',command,'adb')
        with self.assertRaisesRegex(LoginBlocked,'610123'):
            probe.read()
