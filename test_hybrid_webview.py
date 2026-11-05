import unittest
from unittest.mock import Mock
import automation, hybrid_webview, case_runner

class HybridTests(unittest.TestCase):
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
