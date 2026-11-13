import unittest
from unittest.mock import patch, Mock
from automation import Explorer, LoginBlocked, ELEMENT, parse_ui, scrub_xml, signature

A='<hierarchy><node class="android.widget.Button" package="com.example" text="详情" clickable="true"/><node class="android.widget.Button" package="com.example" text="删除账号" clickable="true"/></hierarchy>'
B='<hierarchy><node class="android.widget.Button" package="com.example" text="返回" clickable="true"/></hierarchy>'
LOGIN='<hierarchy><node class="android.widget.EditText" package="com.example"/><node class="android.widget.EditText" package="com.example" password="true"/><node class="android.widget.Button" package="com.example" text="登录" clickable="true"/></hierarchy>'

class FakeDriver:
    def __init__(self,login=False):self.state='login' if login else 'A';self.clicked=[];self.elements={};self.typed=[]
    def source(self):return LOGIN if self.state=='login' else A.replace('</hierarchy>', '<node class="android.widget.TextView" package="com.example" content-desc="首页"/></hierarchy>') if self.state=='A' else B
    def __call__(self,method,path,data=None):
        if path.endswith('/source'):return self.source()
        if path.endswith('/element'):
            if data['using']=='accessibility id':
                if data['value']=='首页' and self.state=='A':return {ELEMENT:'home'}
                raise RuntimeError('not found')
            n=next(n for n in parse_ui(self.source()) if n['path']==data['value'])
            eid='e'+str(len(self.elements));self.elements[eid]=n;return {ELEMENT:eid}
        if path.endswith('/clear'):return None
        if path.endswith('/value'):self.typed.append(data['text']);return None
        if path.endswith('/click'):
            label=self.elements[path.split('/')[-2]]['label'];self.clicked.append(label)
            if label=='详情':self.state='B'
            if label=='登录':self.state='A'
            return None
        if path.endswith('/back'):self.state='A';return None
        raise AssertionError(path)

class AutomationTests(unittest.TestCase):
    def test_accessibility_failure_recovers_only_after_confirmed_login(self):
        calls=[];reads=[0]
        def call(method,path,data=None):
            calls.append(path)
            if path.endswith('/source'):
                reads[0]+=1
                if reads[0]<=3:raise RuntimeError('root AccessibilityNodeInfo unavailable')
                return A
            return True
        exp=Explorer(call,'s','Android',lambda x:None,lambda *args:None)
        exp.app_package='com.example';exp.allow_source_recovery=True;exp.recovery_events=[]
        with patch('automation.time.sleep'):self.assertEqual(exp.source(),A)
        self.assertEqual(exp.source_recoveries,1)
        self.assertEqual(len(exp.recovery_events),1)
        self.assertTrue(any(p.endswith('/terminate_app') for p in calls))
        reads[0]=0;calls.clear();exp.allow_source_recovery=False
        with patch('automation.time.sleep'),self.assertRaises(RuntimeError):exp.source()
        self.assertFalse(any(p.endswith('/terminate_app') for p in calls))

    def test_unlimited_run_survives_large_elapsed_time_and_exhausts_controls(self):
        driver=FakeDriver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None)
        ticks=iter(range(0,1000000000,100000))
        with patch('automation.time.sleep'),patch('automation.time.monotonic',side_effect=lambda:next(ticks)):
            result=exp.explore({'seconds':0,'max_actions':0})
        self.assertEqual(result['termination'],'reachable_controls_exhausted')
        self.assertIn('详情',driver.clicked)

    def test_navigation_back_and_risky_button_skip(self):
        driver=FakeDriver();captures=[]
        exp=Explorer(driver,'s','Android',lambda x:None,lambda *x:captures.append(x))
        with patch('automation.time.sleep'):
            result=exp.explore({'max_actions':10})
        self.assertEqual(driver.clicked,['详情'])
        self.assertEqual(result['actions'],2)
        self.assertEqual(len(result['pages']),2)
        self.assertTrue(any(e['action']=='back' and e['matched'] for e in result['transitions']))
        self.assertTrue(any('删除' in e['reason'] for e in result['skipped']))
        self.assertEqual(result['termination'],'reachable_controls_exhausted')

    def test_login_confirmed_before_exploration(self):
        driver=FakeDriver(login=True);logs=[]
        exp=Explorer(driver,'s','Android',logs.append,lambda *x:self.fail('login must not capture'))
        cfg={'enabled':True,'account':'test-account','password':'secret-test-42','success':{'by':'accessibility id','value':'首页'}}
        result=exp.login(cfg)
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(driver.typed,['test-account','secret-test-42'])
        self.assertNotIn('secret-test-42',str(logs)+str(result))

    def test_login_requires_success_marker(self):
        exp=Explorer(FakeDriver(login=True),'s','Android',lambda x:None,lambda *x:None)
        with self.assertRaises(LoginBlocked):exp.login({'enabled':True,'account':'a','password':'b'})

    def test_stop_without_clicking(self):
        driver=FakeDriver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *x:None,lambda:True)
        result=exp.explore({})
        self.assertEqual(result['termination'],'stopped');self.assertEqual(driver.clicked,[])

    def test_action_budget_is_enforced(self):
        driver=FakeDriver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *x:None)
        with patch('automation.time.sleep'):result=exp.explore({'max_actions':1})
        self.assertEqual(result['actions'],1);self.assertEqual(result['termination'],'action_limit')

    def test_xml_credentials_redacted(self):
        xml='<hierarchy><node password="true" text="super-secret"/><node text="test-account"/></hierarchy>'
        scrubbed=scrub_xml(xml,['test-account','super-secret'])
        self.assertNotIn('test-account',scrubbed);self.assertNotIn('super-secret',scrubbed)

    def test_secure_page_not_captured(self):
        driver=FakeDriver(login=True);exp=Explorer(driver,'s','Android',lambda x:None,lambda *x:self.fail('secure page captured'))
        result=exp.explore({});self.assertEqual(result['termination'],'login_or_secure_form')

class CredentialReportTests(unittest.TestCase):
    def test_credentials_not_in_saved_report_or_tree(self):
        import app,tempfile,json
        from pathlib import Path
        driver=FakeDriver(login=True)
        def call(method,path,data=None):
            if path=='/session':return {'sessionId':'s'}
            if path.endswith('/appium/settings'):return {}
            if path.endswith('/screenshot'):return 'aGVsbG8='
            if method=='DELETE':return None
            return driver(method,path,data)
        cfg={'platform':'Android','device':'mock','bundle':'com.example','test_mode':'explore','steps':[], 'explore':{'max_actions':2},'login':{'enabled':True,'account':'private-account-xyz','password':'private-secret-xyz','success':{'by':'accessibility id','value':'首页'}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'ROOT',Path(tmp)),patch.object(app,'request',call),patch('automation.time.sleep'):
            app.JOBS['credential-test']={'logs':[],'screenshots':[],'status':'running'}
            app.run_job('credential-test',cfg)
            self.assertEqual(app.JOBS['credential-test']['status'],'passed')
            for p in (Path(tmp)/'reports/credential-test').iterdir():
                if p.suffix in ('.json','.xml'):
                    self.assertNotIn('private-account-xyz',p.read_text());self.assertNotIn('private-secret-xyz',p.read_text())

    def test_failed_login_saves_no_screenshot(self):
        import app,tempfile
        from pathlib import Path
        driver=FakeDriver(login=True)
        def call(method,path,data=None):
            if path=='/session':return {'sessionId':'s'}
            if path.endswith('/appium/settings'):return {}
            if path.endswith('/screenshot'):self.fail('failed login screenshot')
            if method=='DELETE':return None
            return driver(method,path,data)
        cfg={'platform':'Android','device':'mock','bundle':'com.example','login':{'enabled':True,'account':'private-account','password':'private-secret','success':{'by':'accessibility id','value':'首页'},'account_selector':{'by':'id','value':'missing'}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'ROOT',Path(tmp)),patch.object(app,'request',call):
            app.JOBS['login-fail']={'logs':[],'screenshots':[],'status':'running'}
            app.run_job('login-fail',cfg)
            self.assertEqual(app.JOBS['login-fail']['status'],'blocked')
            self.assertEqual(app.JOBS['login-fail']['screenshots'],[])

class LoadingStateTests(unittest.TestCase):
    def test_empty_control_tree_is_not_reported_as_exhausted(self):
        exp=Explorer(lambda *a:'<hierarchy/>','s','Android',lambda x:None,lambda *x:None)
        with patch.object(exp,'wait_ui',return_value='<hierarchy/>'):
            result=exp.explore({})
        self.assertEqual(result['termination'],'no_accessible_controls')
        self.assertEqual(result['actions'],0)

class ReturnRecoveryTests(unittest.TestCase):
    def test_changed_parent_continues_to_remaining_control(self):
        class ChangedParent(FakeDriver):
            def source(self):
                if self.state=='changed':return A.replace('详情','其他入口')
                return super().source()
            def __call__(self,method,path,data=None):
                if path.endswith('/back'):self.state='changed';return None
                return super().__call__(method,path,data)
        driver=ChangedParent();captures=[]
        exp=Explorer(driver,'s','Android',lambda x:None,lambda *x:captures.append(x))
        with patch('automation.time.sleep'):
            result=exp.explore({'max_actions':8})
        self.assertIn('其他入口',driver.clicked)
        self.assertNotEqual(result['termination'],'return_mismatch')
        self.assertEqual(len(captures),len(result['pages']))
        self.assertEqual(len({c[0] for c in captures}),len(captures))

class LoadingTransitionTests(unittest.TestCase):
    def test_transient_spinner_is_not_saved_as_destination(self):
        driver=FakeDriver();original=driver.__call__;remaining=[0];captures=[]
        def call(method,path,data=None):
            if path.endswith('/source') and remaining[0]:
                remaining[0]-=1
                return '<hierarchy><node package="com.example" class="android.widget.ProgressBar"/></hierarchy>'
            result=original(method,path,data)
            if path.endswith('/click'):remaining[0]=2
            return result
        exp=Explorer(call,'s','Android',lambda x:None,lambda name,source:captures.append(source))
        with patch('automation.time.sleep'):
            result=exp.explore({'max_actions':4})
        self.assertEqual(len(result['pages']),2)
        self.assertFalse(any('ProgressBar' in source for source in captures))

class SourceCoverageTests(unittest.TestCase):
    def test_observed_routes_are_separate_from_source_candidates(self):
        from unittest.mock import Mock
        driver=FakeDriver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *x:None)
        exp.route_reader=Mock();exp.route_reader.read.side_effect=lambda:'/main' if driver.state=='A' else '/details'
        plan={'routes':[{'path':'/main'},{'path':'/details'},{'path':'/restricted'}]}
        with patch('automation.time.sleep'):
            result=exp.explore({'max_actions':5,'source_plan':plan})
        self.assertEqual(result['source_coverage']['visited_routes'],['/details','/main'])
        self.assertEqual([r['path'] for r in result['source_coverage']['unvisited_routes']],['/restricted'])
        self.assertEqual(result['source_coverage']['unvisited_routes'][0]['status'],'not_observed')

    def test_manual_revisits_only_capture_one_image(self):
        import app,tempfile
        from pathlib import Path
        def call(method,path,data=None):
            if path=='/session':return {'sessionId':'s'}
            if path.endswith('/source'):return A
            if path.endswith('/screenshot'):return 'aGVsbG8='
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'ROOT',Path(tmp)),patch.object(app,'request',call),patch.object(app,'raw_request'):
            app.JOBS['dedup']={'logs':[],'screenshots':[],'status':'running'}
            app.run_job('dedup',{'platform':'Android','device':'mock','bundle':'com.example','screenshot_policy':'all','steps':[{'action':'screenshot'},{'action':'screenshot'}]})
            self.assertEqual(len(app.JOBS['dedup']['screenshots']),1)
            self.assertEqual(app.JOBS['dedup']['status'],'passed')

class NestedEntryTests(unittest.TestCase):
    def test_distinct_system_permission_entries_each_recover(self):
        class Driver(FakeDriver):
            def source(self):
                labels=['Location','Photos','Camera'] if self.state=='A' else ['Settings']
                package='com.example' if self.state=='A' else 'com.android.settings'
                return '<hierarchy>'+''.join('<node class="android.widget.Button" package="'+package+'" text="'+s+'" clickable="true"/>' for s in labels)+'</hierarchy>'
            def __call__(self,method,path,data=None):
                if path.endswith('/click'):
                    self.clicked.append(self.elements[path.split('/')[-2]]['label']);self.state='outside';return
                return super().__call__(method,path,data)
        driver=Driver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None)
        with patch('automation.time.sleep'):result=exp.explore({'max_scrolls':0})
        self.assertEqual(driver.clicked,['Location','Photos','Camera'])
        self.assertEqual(result['termination'],'reachable_controls_exhausted')
        self.assertEqual(sum(e.get('type')=='outside_app_recovered' for e in result['issues']),3)

    def test_root_tab_switch_does_not_spend_page_depth_or_back_out_of_app(self):
        class Driver(FakeDriver):
            root_backs=0
            def source(self):
                if self.state=='S':return B
                def button(label,selected=False):return '<node class="android.widget.Button" package="com.example" text="'+label+'" clickable="true" selected="'+str(selected).lower()+'"/>'
                return '<hierarchy>'+button('Home&#10;Tab 1 of 2',self.state=='A')+button('Mine&#10;Tab 2 of 2',self.state=='M')+button('Settings' if self.state=='M' else 'Help')+'</hierarchy>'
            def __call__(self,method,path,data=None):
                if path.endswith('/click'):
                    label=self.elements[path.split('/')[-2]]['label'];self.clicked.append(label)
                    self.state={'Home\nTab 1 of 2':'A','Mine\nTab 2 of 2':'M','Settings':'S'}.get(label,self.state);return
                if path.endswith('/back'):
                    if self.state!='S':self.root_backs+=1
                    self.state='M';return
                return super().__call__(method,path,data)
        driver=Driver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None)
        with patch('automation.time.sleep'):result=exp.explore({'max_depth':1,'max_scrolls':0})
        self.assertIn('Settings',driver.clicked)
        self.assertEqual(driver.root_backs,0)
        self.assertEqual(result['termination'],'reachable_controls_exhausted')

    def test_english_exit_account_is_not_clicked(self):
        class Driver(FakeDriver):
            def source(self):return A.replace('删除账号','Exit account') if self.state=='A' else B
        driver=Driver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None)
        with patch('automation.time.sleep'):exp.explore({'max_actions':10})
        self.assertNotIn('Exit account',driver.clicked)

    def test_business_password_returns_and_continues_but_login_stops(self):
        from types import SimpleNamespace
        for route,expected in [('/my/password','reachable_controls_exhausted'),('/login','login_or_secure_form')]:
            class Driver(FakeDriver):
                def source(self):return LOGIN if self.state=='B' else A
            driver=Driver();captures=[]
            exp=Explorer(driver,'s','Android',lambda x:None,lambda name,source:captures.append(source))
            exp.route_reader=SimpleNamespace(read=lambda:route if driver.state=='B' else '/main')
            with patch('automation.time.sleep'):result=exp.explore({'max_actions':10})
            self.assertEqual(result['termination'],expected)
            self.assertTrue(all('password="true"' not in source for source in captures))
            self.assertEqual(any(e['action']=='secure_form_recovery' for e in result['transitions']),route!='/login')

    def test_debug_launcher_is_skipped_and_open_panel_is_closed_without_capture(self):
        debug='<hierarchy><node class="android.webkit.WebView" package="com.example">'+''.join('<node class="android.widget.Button" text="'+label+'" clickable="true" package="com.example"/>' for label in ('Log','System','Network','Storage','Hide'))+'<node text="fake-sensitive-diagnostic-marker"/></node></hierarchy>'
        class Driver(FakeDriver):
            def __init__(self):super().__init__();self.state='debug'
            def source(self):
                if self.state=='debug':return debug
                return A.replace('删除账号','vConsole') if self.state=='A' else B
            def __call__(self,method,path,data=None):
                if path.endswith('/click') and self.elements[path.split('/')[-2]]['label']=='Hide':
                    self.clicked.append('Hide');self.state='A';return None
                return super().__call__(method,path,data)
        driver=Driver();captures=[];exp=Explorer(driver,'s','Android',lambda x:None,lambda name,source:captures.append(source))
        with patch('automation.time.sleep'):result=exp.explore({'max_actions':10})
        self.assertEqual(driver.clicked[0],'Hide');self.assertNotIn('vConsole',driver.clicked)
        self.assertTrue(any('vconsole' in item['reason'] for item in result['skipped']))
        self.assertTrue(all('fake-sensitive-diagnostic-marker' not in source for source in captures))

    def test_tab_content_is_explored_before_switching_away(self):
        class Driver(FakeDriver):
            def source(self):
                def button(label,selected=False):
                    return '<node class="android.widget.Button" package="com.example" text="'+label+'" clickable="true" selected="'+str(selected).lower()+'"/>'
                return '<hierarchy>'+button('Home&#10;Tab 1 of 2',self.state=='A')+button('Mine&#10;Tab 2 of 2',self.state=='mine')+button('Settings' if self.state=='mine' else 'Help')+'</hierarchy>'
            def __call__(self,method,path,data=None):
                if path.endswith('/click'):
                    label=self.elements[path.split('/')[-2]]['label'];self.clicked.append(label)
                    if label.startswith('Mine\n'):self.state='mine'
                    if label.startswith('Home\n'):self.state='A'
                    return None
                return super().__call__(method,path,data)
        driver=Driver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None)
        with patch('automation.time.sleep'):
            exp.explore({'max_actions':20})
        self.assertIn('Settings',driver.clicked)
        start=driver.clicked.index('Mine\nTab 2 of 2')
        self.assertEqual(driver.clicked[start+1],'Settings')

    def test_flutter_parent_uses_child_text_for_navigation(self):
        xml='<hierarchy><node clickable="true" class="android.view.View"><node text="Settings" class="android.widget.TextView"/></node></hierarchy>'
        nodes=parse_ui(xml)
        self.assertEqual(next(n for n in nodes if n['clickable'])['label'],'Settings')

class LoadingRecoveryTests(unittest.TestCase):
    def test_loading_with_ignored_back_reopens_app_and_continues(self):
        class Driver(FakeDriver):
            def source(self):
                if self.state=='B':return '<hierarchy><node package="com.example" class="android.widget.ProgressBar"/></hierarchy>'
                return A.replace('删除账号','Settings')
            def __call__(self,method,path,data=None):
                if path.endswith('/back'):return None
                if path.endswith('/terminate_app'):return None
                if path.endswith('/activate_app'):self.state='A';return None
                return super().__call__(method,path,data)
        driver=Driver()
        exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None)
        exp.app_package='com.example'
        with patch('automation.time.sleep'),patch.object(exp,'settled_source',side_effect=lambda **kwargs:driver.source()):
            result=exp.explore({'max_actions':8})
        self.assertIn('Settings',driver.clicked)
        self.assertEqual(result['termination'],'reachable_controls_exhausted')

    def test_failed_loading_returns_to_other_entry(self):
        class Driver(FakeDriver):
            def source(self):
                if self.state=='B':return '<hierarchy><node package="com.example" class="android.widget.ProgressBar"/></hierarchy>'
                return A.replace('删除账号','Settings')
        driver=Driver();captures=[]
        exp=Explorer(driver,'s','Android',lambda x:None,lambda name,source:captures.append(source))
        with patch('automation.time.sleep'),patch.object(exp,'settled_source',side_effect=lambda **kwargs:driver.source()):
            result=exp.explore({'max_actions':8})
        self.assertIn('Settings',driver.clicked)
        self.assertTrue(any(edge['action']=='loading_recovery' for edge in result['transitions']))
        self.assertTrue(any('ProgressBar' in source for source in captures))

class WebViewRecoveryTests(unittest.TestCase):
    def test_app_header_back_preferred_over_web_history(self):
        xml='<hierarchy><node class="android.widget.ImageView" clickable="true" bounds="[0,45][120,170]"/><node class="android.webkit.WebView"/></hierarchy>'
        exp=Explorer(lambda *args:self.fail('system Back should not be used'),'s','Android',lambda x:None,lambda *args:None)
        with patch.object(exp,'tap') as tap:
            exp.back(parse_ui(xml));self.assertEqual(tap.call_args.args[0]['kind'],'android.widget.ImageView')
    def test_external_page_is_recovered(self):
        class Driver(FakeDriver):
            def source(self):
                if self.state=='external':return '<hierarchy><node class="android.widget.Button" package="com.browser" text="Browser" clickable="true"/></hierarchy>'
                return super().source()
            def __call__(self,method,path,data=None):
                result=super().__call__(method,path,data)
                if path.endswith('/click') and self.state=='B':self.state='external'
                return result
        driver=Driver();exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None,shell=lambda args:setattr(driver,'state','A'))
        with patch('automation.time.sleep'):
            result=exp.explore({'max_actions':6})
        self.assertNotEqual(result['termination'],'outside_app')
        self.assertTrue(any(issue['type']=='outside_app_recovered' for issue in result['issues']))

class AccessibilityRetryTests(unittest.TestCase):
    def test_transient_window_root_failure_retries_only_source(self):
        from unittest.mock import Mock
        call=Mock(side_effect=[RuntimeError('root AccessibilityNodeInfo timed out'),A])
        exp=Explorer(call,'s','Android',lambda x:None,lambda *args:None)
        with patch('automation.time.sleep'):self.assertEqual(exp.source(),A)
        self.assertEqual(call.call_count,2)
        self.assertTrue(all(c.args==('GET','/session/s/source') for c in call.call_args_list))

class NativeClickTests(unittest.TestCase):
    def test_coordinate_click_uses_native_driver_not_adb(self):
        from unittest.mock import Mock
        call=Mock(return_value=None);shell=Mock()
        exp=Explorer(call,'s','Android',lambda x:None,lambda *args:None,shell=shell)
        node={'path':'/hierarchy/node[1]','bounds':'[100,200][300,400]'}
        exp.tap(node)
        call.assert_called_once_with('POST','/session/s/execute/sync',{'script':'mobile: clickGesture','args':[{'x':200,'y':300}]})
        shell.assert_not_called()
    def test_failed_native_and_element_click_are_not_reported_successful(self):
        from unittest.mock import Mock
        call=Mock(side_effect=RuntimeError('driver failed'))
        exp=Explorer(call,'s','Android',lambda x:None,lambda *args:None,shell=Mock(return_value={'ok':False}))
        with self.assertRaises(RuntimeError):exp.tap({'path':'/node','bounds':'[0,0][100,100]'})

class TabFrontierTests(unittest.TestCase):
    def test_tab_cycle_does_not_drop_unfinished_settings_branch(self):
        class Driver(FakeDriver):
            def source(self):
                labels={'A':['Mine','Details'],'M':['Home','Settings'],'S':['Back'],'B':['Back']}[self.state]
                return '<hierarchy>'+''.join('<node class="android.widget.Button" package="com.example" text="'+label+'" clickable="true"/>' for label in labels)+'</hierarchy>'
            def __call__(self,method,path,data=None):
                if path.endswith('/click'):
                    label=self.elements[path.split('/')[-2]]['label'];self.clicked.append(label)
                    self.state={'Mine':'M','Home':'A','Settings':'S','Details':'B'}.get(label,self.state);return
                if path.endswith('/back'):self.state='M' if self.state=='S' else 'A';return
                return super().__call__(method,path,data)
        d=Driver();exp=Explorer(d,'s','Android',lambda x:None,lambda *args:None)
        with patch('automation.time.sleep'):
            result=exp.explore({'max_actions':20,'source_plan':{'tab_labels':['Home','Mine']}})
        self.assertIn('Settings',d.clicked)
        self.assertTrue(any(edge['action']=='revisit' for edge in result['transitions']))

class NativeInputTests(unittest.TestCase):
    def test_direct_replacement_uses_fresh_element_without_adb_ime(self):
        from unittest.mock import Mock,patch
        driver=Mock(side_effect=lambda method,path,data=None: {ELEMENT:'fresh'} if path.endswith('/element') else True)
        exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None,shell=Mock())
        node={'path':'/hierarchy/node[1]','bounds':'[10,10][100,60]','label':''}
        with patch('automation.time.sleep'):exp.type('stale','test-value',node)
        payloads=[call.args[2] for call in driver.call_args_list if len(call.args)>2]
        self.assertIn({'script':'mobile: replaceElementValue','args':[{'elementId':'fresh','text':'test-value'}]},payloads)
        self.assertFalse(any(p.get('script')=='mobile: type' for p in payloads if isinstance(p,dict)))
        self.assertFalse(any(c.args[1].endswith('/clear') for c in driver.call_args_list))
        exp.shell.assert_not_called()

class StableNavigationBudgetTests(unittest.TestCase):
    def test_webview_scroll_budget_survives_content_changes(self):
        from types import SimpleNamespace
        class Driver:
            count=0
            def __call__(self,method,path,data=None):
                if path.endswith('/source'):
                    return '<hierarchy><node class="android.webkit.WebView" text="Detail" package="com.example" scrollable="true"><node text="row '+str(self.count)+'"/></node></hierarchy>'
                if path.endswith('/window/rect'):return {'width':400,'height':800}
                if path.endswith('/actions'):self.count+=1;return None
                raise AssertionError(path)
        d=Driver();exp=Explorer(d,'s','Android',lambda *a:None,lambda *a:None)
        exp.route_reader=SimpleNamespace(read=lambda:'/webview')
        with patch('automation.time.sleep'),patch.object(exp,'settled_source',side_effect=lambda:d('GET','/source')):
            result=exp.explore({'max_actions':20,'max_scrolls':2})
        self.assertEqual(d.count,2)
        self.assertEqual(result['termination'],'reachable_controls_exhausted')
        self.assertEqual(len(result['pages']),3)

class H5IconReturnTests(unittest.TestCase):
    def test_nonclickable_h5_back_icon_is_used(self):
        xml='<hierarchy><node class="android.webkit.WebView"><node class="android.widget.TextView" text="&#xe668;" bounds="[46,106][100,161]" clickable="false"/></node></hierarchy>'
        exp=Explorer(lambda *args:self.fail('blocked system Back should not be used'),'s','Android',lambda *a:None,lambda *a:None)
        with patch.object(exp,'tap') as tap:
            exp.back(parse_ui(xml))
            self.assertEqual(tap.call_args.args[0]['label'],'\ue668')


class SwitchLanguageTests(unittest.TestCase):
    def explorer(self,pages):
        exp=Explorer.__new__(Explorer)
        exp.logs=[];exp.log=exp.logs.append;exp.stopped=lambda:False;exp.platform='Android'
        exp.call=lambda *a,**k:{}
        state={'pages':list(pages),'taps':[],'scrolls':0}
        exp.wait_ui=lambda:(state['pages'].pop(0) if len(state['pages'])>1 else state['pages'][0])
        exp.source=lambda:state['pages'][0]
        def tap(node):
            state['taps'].append(node['label'])
        exp.tap=tap
        exp.scroll=lambda:state.update(scrolls=state['scrolls']+1,pages=[state['pages'][-1]+'<more>'])
        exp.state=state
        return exp
    def node(self,label):
        return '<node text="%s" clickable="true" package="test.app" bounds="[0,0][100,100]"/>'%label
    def test_multiline_settings_rows_match_by_line(self):
        settings='<hierarchy>'+self.node('语言&#10;中文简体')+self.node('账号管理')+'</hierarchy>'
        langlist='<hierarchy>'+self.node('English&#10;English')+self.node('中文简体&#10;中文简体')+'</hierarchy>'
        exp=self.explorer([settings,langlist])
        result=exp.switch_language({'name':'中文简体','code':'zh-CN','path':['语言'],'choice':'中文简体'})
        self.assertEqual(exp.state['taps'],['语言\n中文简体','中文简体\n中文简体'])
        self.assertEqual(result['status'],'switched')
    def test_choice_below_the_fold_is_found_by_scrolling(self):
        blank='<hierarchy>'+self.node('语言&#10;English')+self.node('English&#10;English')+'</hierarchy>'
        revealed='<hierarchy>'+self.node('语言&#10;English')+self.node('English&#10;English')+self.node('日本語&#10;日本語')+'</hierarchy>'
        exp=self.explorer([blank])
        exp.source=lambda:revealed if exp.state['scrolls'] else blank
        exp.scroll=lambda:exp.state.update(scrolls=exp.state['scrolls']+1)
        result=exp.switch_language({'name':'日本語','code':'ja-JP','path':['语言'],'choice':'日本語'})
        self.assertGreater(exp.state['scrolls'],0);self.assertEqual(result['status'],'switched')
    def test_ambiguous_rows_prefer_exact_label(self):
        page='<hierarchy>'+self.node('语言')+self.node('语言&#10;中文简体')+'</hierarchy>'
        exp=self.explorer([page,page])
        exp.switch_language({'name':'中文简体','code':'zh-CN','path':['语言'],'choice':'中文简体'})
        self.assertEqual(exp.state['taps'][0],'语言')
    def test_default_after_login_path_walks_mine_settings_language(self):
        home='<hierarchy>'+self.node('首页&#10;Tab 1 of 4')+self.node('我的&#10;Tab 4 of 4')+'</hierarchy>'
        settings='<hierarchy>'+self.node('账号管理')+self.node('通用设置')+self.node('语言&#10;English')+'</hierarchy>'
        langlist='<hierarchy>'+self.node('English&#10;English')+self.node('中文简体&#10;中文简体')+'</hierarchy>'
        exp=self.explorer([home,settings,settings,langlist])
        result=exp.switch_language({'name':'中文简体','code':'zh-CN','path':[],'choice':'中文简体','phase':'after_login'})
        self.assertEqual([t.split('\n')[0] for t in exp.state['taps']],['我的','通用设置','语言','中文简体'])
        self.assertEqual(result['status'],'switched')
    def test_default_before_login_path_uses_config_language_row(self):
        config='<hierarchy>'+self.node('国家&#10;中国')+self.node('语言&#10;中文简体')+'</hierarchy>'
        picker='<hierarchy>'+self.node('中文简体')+self.node('English')+'</hierarchy>'
        exp=self.explorer([config,picker])
        result=exp.switch_language({'name':'English','code':'en-US','path':[],'choice':'English','phase':'before_login'})
        self.assertEqual([t.split('\n')[0] for t in exp.state['taps']],['语言','English'])
        self.assertEqual(result['status'],'switched')
    def test_default_path_follows_current_app_language_via_translations(self):
        settings='<hierarchy>'+self.node('Account management')+self.node('Common setting')+self.node('Language&#10;中文简体')+'</hierarchy>'
        langlist='<hierarchy>'+self.node('English&#10;English')+self.node('中文简体&#10;中文简体')+'</hierarchy>'
        exp=self.explorer([
            '<hierarchy>'+self.node('Home&#10;Tab 1 of 4')+self.node('Mine&#10;Tab 4 of 4')+'</hierarchy>',
            settings,settings,langlist])
        exp.flow_index={'translations':{'mine':['我的','Mine'],'mine_general_settings':['通用设置','Common setting'],'language':['语言','Language']}}
        result=exp.switch_language({'name':'中文简体','code':'zh-CN','path':[],'choice':'中文简体','phase':'after_login'})
        self.assertEqual([t.split('\n')[0] for t in exp.state['taps']],['Mine','Common setting','Language','中文简体'])
        self.assertEqual(result['status'],'switched')

class NestedWebReturnTests(unittest.TestCase):
    def explorer(self,never_returns=False):
        exp=Explorer(Mock(),'s','Android',lambda _:None,lambda *a:None)
        exp.app_package='com.example';exp.state='root';exp.taps=[];exp.backs=0
        root='<hierarchy><node package="com.example" class="android.widget.Button" text="Learning Center" clickable="true"/><node package="com.example" class="android.widget.Button" text="Other" clickable="true"/></hierarchy>'
        def source():
            if exp.state=='root':return root
            return '<hierarchy><node package="com.example" class="android.webkit.WebView" text="H5 '+str(exp.backs)+'"/><node package="com.example" class="android.widget.Button" text="vconsole" clickable="true"/></hierarchy>'
        def tap(n):
            exp.taps.append(n['label'])
            if n['label']=='Learning Center':exp.state='web'
        def back(nodes):
            exp.backs+=1
            if exp.backs>=2 and not never_returns:exp.state='root'
        exp.source=source;exp.settled_source=source;exp.tap=tap;exp.back=back
        return exp
    def test_h5_history_does_not_drop_root_with_unvisited_entries(self):
        exp=self.explorer()
        with patch('automation.time.sleep'):r=exp.explore({'max_scrolls':0})
        self.assertEqual(exp.taps,['Learning Center','Other','Other'])
        self.assertEqual(exp.backs,2)
        self.assertEqual(r['termination'],'reachable_controls_exhausted')
    def test_unrecoverable_h5_does_not_claim_all_controls_exhausted(self):
        exp=self.explorer(never_returns=True)
        with patch('automation.time.sleep'):r=exp.explore({'max_scrolls':0})
        self.assertEqual(r['termination'],'back_failed');self.assertLessEqual(exp.backs,4)
        self.assertNotIn('Other',exp.taps);self.assertTrue(r['issues'])

class ForegroundEvidenceTests(unittest.TestCase):
    ROOT='<hierarchy><node package="test.app" class="android.widget.Button" text="打开" clickable="true"/></hierarchy>'
    MISSING='<hierarchy><node package="com.android.systemui" class="android.widget.Button" text="Home" clickable="true"/></hierarchy>'
    PAGE='<hierarchy><node package="test.app" class="android.widget.Button" text="返回" clickable="true"/></hierarchy>'
    def explorer(self,recovers=True):
        exp=Explorer(Mock(),'s','Android',lambda _:None,lambda *a:None);exp.app_package='test.app';exp.state='root';exp.calls=[];exp.backs=[]
        exp.source=lambda:self.ROOT if exp.state=='root' else self.PAGE if exp.state=='page' else self.MISSING
        exp.settled_source=lambda **kwargs:exp.source()
        def tap(n):exp.state='missing'
        def back(nodes):
            exp.backs.append(exp.state)
            if exp.state!='page':raise AssertionError('must not back out of foreground App on missing tree')
            exp.state='root'
        def call(method,path,data=None):
            exp.calls.append(path)
            if path.endswith('/current_package'):
                if recovers:exp.state='page'
                return 'test.app'
            raise AssertionError('unexpected command '+path)
        exp.tap=tap;exp.back=back;exp.call=call
        return exp
    def test_foreground_app_with_transient_missing_tree_is_not_sent_back(self):
        exp=self.explorer()
        with patch('automation.time.sleep'):r=exp.explore({'max_scrolls':0})
        self.assertEqual(exp.backs,['page']);self.assertEqual(r['termination'],'reachable_controls_exhausted')
        self.assertFalse(any(x['type']=='outside_app' for x in r['issues'] if 'type' in x))
    def test_persistent_missing_tree_is_reported_as_tree_failure_not_external_app(self):
        exp=self.explorer(recovers=False)
        with patch('automation.time.sleep'):r=exp.explore({'max_scrolls':0})
        self.assertEqual(r['termination'],'page_tree_unavailable');self.assertEqual(exp.backs,[])
        self.assertEqual(r['issues'][-1]['foreground_package'],'test.app')
        self.assertLessEqual(len(exp.calls),4)

class RelaunchForegroundTests(unittest.TestCase):
    def test_activation_is_verified_before_declaring_external_recovery_failed(self):
        root='<hierarchy><node package="test.app" class="android.widget.Button" text="打开" clickable="true"/></hierarchy>'
        foreign='<hierarchy><node package="com.browser" class="android.widget.Button" text="Browser" clickable="true"/></hierarchy>'
        opening='<hierarchy><node package="com.android.systemui" class="android.widget.Button" text="Home" clickable="true"/></hierarchy>'
        e=Explorer(Mock(),'s','Android',lambda _:None,lambda *a:None);e.app_package='test.app';e.state='root'
        e.source=lambda:root if e.state=='root' else opening if e.state=='opening' else foreign
        e.settled_source=lambda **kwargs:e.source()
        e.tap=lambda n:setattr(e,'state','foreign')
        def call(method,path,data=None):
            if path.endswith('/current_package'):
                if e.state=='opening':e.state='root';return 'test.app'
                return 'com.browser'
            if path.endswith('/activate_app'):e.state='opening';return
            if path.endswith('/back'):return
            raise AssertionError(path)
        e.call=call
        with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0})
        self.assertNotEqual(r['termination'],'outside_app')
        self.assertTrue(any(x.get('type')=='foreground_recovered' for x in r['issues']))

class TwoAttemptNavigationTests(unittest.TestCase):
    def test_unchanged_entry_is_clicked_twice_without_backing_out_of_original_page(self):
        class Driver(FakeDriver):
            backs=0
            def __call__(self,method,path,data=None):
                if path.endswith('/click'):
                    self.clicked.append(self.elements[path.split('/')[-2]]['label']);return
                if path.endswith('/back'):self.backs+=1;return
                return super().__call__(method,path,data)
        d=Driver();e=Explorer(d,'s','Android',lambda _:None,lambda *a:None)
        with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0})
        self.assertEqual(d.clicked,['详情','详情']);self.assertEqual(d.backs,0)
        self.assertTrue(any(x.get('failed_attempts')==2 for x in r['skipped']))
    def test_second_attempt_can_succeed(self):
        class Driver(FakeDriver):
            attempts=0
            def __call__(self,method,path,data=None):
                if path.endswith('/click') and self.elements[path.split('/')[-2]]['label']=='详情':
                    self.attempts+=1
                    if self.attempts==1:self.clicked.append('详情');return
                return super().__call__(method,path,data)
        d=Driver();e=Explorer(d,'s','Android',lambda _:None,lambda *a:None)
        with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0})
        self.assertEqual(d.attempts,2);self.assertTrue(any(x.get('attempt')==2 and x.get('changed') for x in r['transitions']))
    def test_two_loading_failures_return_and_continue_next_entry(self):
        class Driver(FakeDriver):
            backs=0
            def source(self):
                if self.state=='B':return '<hierarchy><node package="com.example" class="android.widget.ProgressBar"/></hierarchy>'
                return A.replace('删除账号','Settings')
            def __call__(self,method,path,data=None):
                if path.endswith('/back'):self.backs+=1
                return super().__call__(method,path,data)
        d=Driver();e=Explorer(d,'s','Android',lambda _:None,lambda *a:None)
        with patch('automation.time.sleep'),patch.object(e,'settled_source',side_effect=d.source):r=e.explore({'max_scrolls':0})
        self.assertEqual(d.clicked.count('详情'),2);self.assertEqual(d.backs,2);self.assertIn('Settings',d.clicked)
        self.assertEqual(r['termination'],'reachable_controls_exhausted')
        self.assertTrue(any(x.get('label')=='详情' and x.get('failed_attempts')==2 for x in r['skipped']))
    def test_side_effect_button_is_not_double_clicked(self):
        class Driver(FakeDriver):
            def source(self):return A.replace('详情','Save')
        d=Driver();e=Explorer(d,'s','Android',lambda _:None,lambda *a:None)
        with patch('automation.time.sleep'):e.explore({'max_scrolls':0})
        self.assertEqual(d.clicked,['Save'])

if __name__=='__main__':unittest.main()
