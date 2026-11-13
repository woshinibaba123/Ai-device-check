import unittest
from unittest.mock import Mock
import automation, hybrid_webview, case_runner

class HybridTests(unittest.TestCase):
    def test_calendar_back_closes_only_unique_visible_close_button(self):
        import json, shutil, subprocess
        if not shutil.which('node'):self.skipTest('Node required for DOM script test')
        e=self.explorer();web=hybrid_webview.WebView(e)
        web.js=Mock(return_value='calendar_close')
        web.perform({'action':'web_back'})
        script=web.js.call_args.args[0]
        fixture="""
let clicked=0;
const close={getBoundingClientRect:()=>({left:0,top:0,width:20,height:20}),contains:e=>false,click:()=>clicked++};
const popup={getBoundingClientRect:()=>({width:300,height:600}),querySelectorAll:()=>Array(count).fill(close)};
const calendar={closest:()=>popup};
const document={querySelectorAll:s=>s==='.van-calendar'?[calendar]:[],elementFromPoint:()=>close};
const getComputedStyle=()=>({display:'block'});
const result=(new Function('document','getComputedStyle',SCRIPT))(document,getComputedStyle);
process.stdout.write(JSON.stringify({result,clicked}));
""".replace('SCRIPT',json.dumps(script))
        for count in (0,1,2):
            # Two distinct candidates must remain ambiguous.
            code=('const count='+str(count)+';'+fixture).replace('Array(count).fill(close)', 'Array.from({length:count},()=>({...close}))' if count==2 else 'Array(count).fill(close)')
            data=json.loads(subprocess.check_output(['node','-e',code],text=True))
            self.assertEqual(data['clicked'],1 if count==1 else 0)
            if count==1:self.assertEqual(data['result'],'calendar_close')
            else:self.assertTrue(data['result']['blocked'])

    def test_live_input_accepts_only_exact_dom_length_truncation(self):
        e=self.explorer()
        e.call.return_value={'count':1,'element':{automation.ELEMENT:'x'},'value':'任务名称','maxlength':4}
        web=hybrid_webview.WebView(e)
        step={'action':'web_assert_input','by':'css','value':'input','text':'任务名称_唯一后缀','allow_maxlength_truncation':True}
        self.assertTrue(web.perform(step)['input_truncated'])
        # Strict test-case assertions retain the original expected value.
        with self.assertRaises(hybrid_webview.H5InputMismatch):web.perform(dict(step,allow_maxlength_truncation=False))
        for actual,limit in [('任务',4),('其他名称',4),('任务名称',-1),('任务名称',None)]:
            e.call.return_value={'count':1,'element':{automation.ELEMENT:'x'},'value':actual,'maxlength':limit}
            with self.assertRaises(hybrid_webview.H5InputMismatch):web.perform(step)

    def test_truncation_uses_browser_utf16_length(self):
        e=self.explorer();e.call.return_value={'count':1,'element':{automation.ELEMENT:'x'},'value':'A😀','maxlength':3}
        result=hybrid_webview.WebView(e).perform({'action':'web_assert_input','value':'input','text':'A😀B','allow_maxlength_truncation':True})
        self.assertTrue(result['input_truncated'])

    def test_live_input_updates_local_data_for_later_readback(self):
        import ai_operator
        from test_ai_operator import Device
        from unittest.mock import patch
        e=Device();data={'name':'任务名称_后缀'}
        with patch.object(hybrid_webview,'WebView') as web:
            web.return_value.__enter__.return_value.perform.side_effect=[{}, {'input_truncated':True,'maxlength':4}]
            ai_operator.execute(e,{'action':'input','target':'w0','data_key':'name'},
                {'w0':('web',{'tag':'input','text':'任务名称','selector':'input'})},data)
        self.assertEqual(data['name'],'任务名称')
        self.assertIn('任务名称',e.secrets)

    def explorer(self):
        e=Mock();e.base='/session/test';e.app_package='com.example.app';return e

    def test_context_is_scoped_to_exact_app(self):
        e=self.explorer();e.call.return_value=['NATIVE_APP','WEBVIEW_com.example.app.other']
        with self.assertRaises(RuntimeError):
            with hybrid_webview.WebView(e):pass
        self.assertEqual(e.call.call_count,1)

    def test_native_context_restored_after_assertion_failure(self):
        e=self.explorer();e.call.side_effect=[['NATIVE_APP','WEBVIEW_com.example.app'],None,{'count':0},None]
        with self.assertRaises(AssertionError):
            with hybrid_webview.WebView(e) as web:web.perform({'action':'web_assert','value':'Absent'})
        self.assertEqual(e.call.call_args.args,('POST','/session/test/context',{'name':'NATIVE_APP'}))

    def test_ambiguous_match_never_clicks(self):
        e=self.explorer();e.call.return_value={'count':2}
        with self.assertRaises(AssertionError):hybrid_webview.WebView(e).perform({'action':'web_tap','value':'More'})
        self.assertEqual(e.call.call_count,1)

    def test_secure_field_is_not_edited(self):
        e=self.explorer();e.call.return_value={'count':1,'secure':True}
        with self.assertRaises(RuntimeError):hybrid_webview.WebView(e).perform({'action':'web_input','value':'Password','text':'test'})
        self.assertEqual(e.call.call_count,1)

    def test_input_assertion_checks_actual_value_without_returning_it(self):
        e=self.explorer();e.call.return_value={'count':1,'element':{automation.ELEMENT:'x'},'value':'test','label':''}
        web=hybrid_webview.WebView(e)
        self.assertNotIn('value',web.perform({'action':'web_assert_input','value':'#search','by':'css','text':'test'}))
        with self.assertRaises(AssertionError):web.perform({'action':'web_assert_input','value':'#search','by':'css','text':'other'})

    def test_h5_plan_requires_results_and_separate_locator_types(self):
        with self.assertRaises(ValueError):case_runner.validate_plan({'steps':[{'action':'web_tap','value':'Open'}]})
        with self.assertRaises(ValueError):case_runner.validate_plan({'steps':[{'action':'web_assert','value':'Open','by':'id'}]})
        case_runner.validate_plan({'steps':[{'action':'web_assert','value':'h1','by':'css','text':'Title'}]})


class InventoryTests(unittest.TestCase):
    def test_failed_capture_always_releases_session_without_discovery_route(self):
        import runtime_inventory
        from pathlib import Path
        def call(method,path,data=None):
            if path=='/session':return {'sessionId':'capture'}
            if path.endswith('/source'):raise RuntimeError('device disconnected')
        request=Mock(side_effect=call)
        with unittest.mock.patch.object(hybrid_webview,'driver_path',return_value=None):
            with self.assertRaises(RuntimeError):runtime_inventory.collect(request,{'device':'emulator-5554','bundle':'com.example.app'},Path('.'))
        self.assertEqual(request.call_args.args,('DELETE','/session/capture'))
        self.assertFalse(any(c.args[1]=='/sessions' for c in request.call_args_list))

    def test_invalid_target_is_rejected_before_device_access(self):
        import runtime_inventory
        from pathlib import Path
        call=Mock()
        with self.assertRaises(ValueError):runtime_inventory.collect(call,{'device':'avd:../../other','bundle':'com.example.app'},Path('.'))
        call.assert_not_called()

class DriverTests(unittest.TestCase):
    def test_incompatible_driver_is_not_forced_on_other_devices(self):
        from pathlib import Path
        from types import SimpleNamespace
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'.runtime/chromedriver/chromedriver';p.parent.mkdir(parents=True);p.touch()
            with patch.object(hybrid_webview.subprocess,'run',side_effect=[SimpleNamespace(stdout='Current WebView package (name, version): (com.google.android.webview, 120.0.1)'),SimpleNamespace(stdout='ChromeDriver 149.0.7827.155')]):
                self.assertIsNone(hybrid_webview.driver_path(tmp,'emulator-5554'))
            with patch.object(hybrid_webview.subprocess,'run',side_effect=[SimpleNamespace(stdout='Current WebView package (name, version): (com.google.android.webview, 149.0.7827.5)'),SimpleNamespace(stdout='ChromeDriver 149.0.7827.155')]):
                self.assertEqual(hybrid_webview.driver_path(tmp,'emulator-5554'),str(p))

class WebSubmissionTests(unittest.TestCase):
    def test_save_requires_dedicated_api_flow(self):
        e=Mock();e.base='/session/test';e.call.return_value={'count':1,'element':{automation.ELEMENT:'x'},'label':'保存'}
        with self.assertRaises(RuntimeError):hybrid_webview.WebView(e).perform({'action':'web_tap','value':'#save','by':'css'})
        self.assertEqual(e.call.call_count,1)

if __name__=='__main__':unittest.main()

class ClosedWindowTests(unittest.TestCase):
    def test_read_only_discovery_rebinds_unique_live_window_once(self):
        e=Mock();e.base='/session/test'
        e.call.side_effect=[RuntimeError('no such window: target window already closed'),['live'],None,{'fields':[]}]
        self.assertEqual(hybrid_webview.WebView(e).js('return document.title',read_only=True),{'fields':[]})
        self.assertEqual(e.call.call_args_list[2].args,('POST','/session/test/window',{'handle':'live'}))
    def test_uncertain_mutation_is_never_replayed(self):
        e=Mock();e.base='/session/test';e.call.side_effect=RuntimeError('no such window')
        with self.assertRaises(RuntimeError):hybrid_webview.WebView(e).js('arguments[0].click()')
        self.assertEqual(e.call.call_count,1)

class LegacyDriverDownloadTests(unittest.TestCase):
    def test_113_uses_legacy_official_driver_distribution(self):
        import tempfile,io,zipfile,urllib.request
        from pathlib import Path
        from unittest.mock import patch
        from types import SimpleNamespace
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:archive.writestr('chromedriver',b'official-driver-test')
        responses=[io.BytesIO(b'113.0.5672.63'),io.BytesIO(data.getvalue())]
        with tempfile.TemporaryDirectory() as tmp,patch.object(hybrid_webview,'driver_path',return_value=None),patch.object(hybrid_webview.subprocess,'run',side_effect=[SimpleNamespace(stdout='Current WebView package (name, version): (com.google.android.webview, 113.0.5672.136)'),SimpleNamespace(stdout='ChromeDriver 113.0.5672.63 (revision)')]),patch('platform.machine',return_value='arm64'),patch.object(urllib.request,'urlopen',side_effect=responses) as fetch:
            result=hybrid_webview.ensure_driver(tmp,'emulator-5554',lambda _:None)
            self.assertTrue(Path(result).exists())
            self.assertEqual(fetch.call_args_list[0].args[0],'https://chromedriver.storage.googleapis.com/LATEST_RELEASE_113.0.5672')
            self.assertEqual(fetch.call_args_list[1].args[0],'https://chromedriver.storage.googleapis.com/113.0.5672.63/chromedriver_mac_arm64.zip')

class DebugOverlayTests(unittest.TestCase):
    def test_only_known_vconsole_launcher_is_hidden(self):
        import subprocess,json,shutil
        node=shutil.which('node')
        if not node:self.skipTest('Node required')
        script='const setup=new Function('+json.dumps(hybrid_webview.DEBUG_OVERLAY_SETUP+'\nreturn hiddenDebugSwitches;')+''');
function element(){return {style:{visibility:'',setProperty(k,v){this[k]=v}}}}
const launcher=element(),business=element();
global.document={getElementById:id=>id==='__vconsole'?{querySelectorAll:s=>s==='.vc-switch'?[launcher]:[]}:null};
const first=setup(),second=setup();
console.log(JSON.stringify({first,second,launcher:launcher.style.visibility,business:business.style.visibility}));'''
        self.assertEqual(json.loads(subprocess.check_output([node,'-e',script],text=True)),{'first':1,'second':0,'launcher':'hidden','business':''})

class PersistentContextTests(unittest.TestCase):
    def test_h5_context_is_reused_and_native_source_restores_it(self):
        from types import SimpleNamespace
        e=automation.Explorer(Mock(), 'reuse', 'Android', Mock(), Mock())
        e.app_package='com.example.app';e.prefer_webview=True
        e.call.side_effect=[['WEBVIEW_com.example.app'],None,None,'<hierarchy/>']
        with hybrid_webview.WebView(e):pass
        with hybrid_webview.WebView(e):pass
        self.assertEqual(e.call.call_count,2)
        self.assertEqual(e.source(),'<hierarchy/>')
        self.assertEqual(e.call.call_args_list[2].args,('POST','/session/reuse/context',{'name':'NATIVE_APP'}))
        self.assertIsNone(e._active_webview_context)
    def test_h5_error_restores_native_context(self):
        e=automation.Explorer(Mock(), 'reuse', 'Android', Mock(), Mock())
        e.app_package='com.example.app';e.prefer_webview=True
        e.call.side_effect=[['WEBVIEW_com.example.app'],None,None]
        with self.assertRaises(ValueError):
            with hybrid_webview.WebView(e):raise ValueError('test')
        self.assertIsNone(e._active_webview_context)
