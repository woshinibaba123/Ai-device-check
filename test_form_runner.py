import json,unittest
from unittest.mock import Mock,patch
import form_runner as forms
from automation import Explorer,parse_ui,ELEMENT


def config():return forms.validate({'enabled':True,'page':'报修','fields':[{'label':'姓名','kind':'text','value':'回归测试'}],'submit':'提交','success':'提交成功'})

class ConfigTests(unittest.TestCase):
    def test_opt_in_requires_all_data_and_success_or_rejects_before_testing(self):
        self.assertEqual(forms.validate(None)['mode'],'auto')
        self.assertFalse(forms.validate({'enabled':False})['enabled'])
        for change in ({'success':''},{'fields':[]},{'page':'提交成功'},{'fields':[{'label':'密码','value':'test'}]}):
            c=config();c.update(change)
            with self.assertRaises(ValueError):forms.validate(c)
        with self.assertRaises(ValueError):forms.validate('bad')
    def test_checkbox_values_are_not_coerced_from_strings(self):
        c=config();c['fields']=[{'label':'复选框','kind':'checkbox','value':'false'}]
        with self.assertRaises(ValueError):forms.validate(c)

class TransactionTests(unittest.TestCase):
    def setup_driver(self):
        e=Mock();e.stopped.return_value=False;e.secrets=['回归测试']
        d=Mock();d.text.side_effect=['报修','提交成功']
        return e,d
    def test_fill_readback_then_submit_success_and_report_has_no_values(self):
        e,d=self.setup_driver()
        with patch.object(forms,'Native',return_value=d):r=forms.execute(e,config())
        self.assertEqual(r['status'],'passed');self.assertTrue(r['submitted'])
        d.preflight.assert_called_once();d.fill.assert_called_once();d.prepare_submit.assert_called_once();d.submit.assert_called_once()
        self.assertNotIn('回归测试',json.dumps(r,ensure_ascii=False))
    def test_failed_input_never_submits_and_driver_error_cannot_leak_data(self):
        e,d=self.setup_driver();d.fill.side_effect=RuntimeError('request text=secret-user-data')
        with patch.object(forms,'Native',return_value=d):r=forms.execute(e,config())
        self.assertFalse(r['submitted']);d.submit.assert_not_called();self.assertNotIn('secret-user-data',str(r))
    def test_preexisting_success_is_not_a_pass(self):
        e,d=self.setup_driver();d.text.side_effect=None;d.text.return_value='报修 提交成功'
        with patch.object(forms,'Native',return_value=d):r=forms.execute(e,config())
        self.assertEqual(r['status'],'blocked');d.submit.assert_not_called()
    def test_invalid_required_field_does_not_attempt_submit(self):
        e,d=self.setup_driver();d.prepare_submit.side_effect=forms.FormError('缺少必填项')
        with patch.object(forms,'Native',return_value=d):r=forms.execute(e,config())
        self.assertFalse(r['submitted']);d.submit.assert_not_called();self.assertIn('必填',r['reason'])
    def test_transport_error_during_submit_is_uncertain_and_not_retried(self):
        e,d=self.setup_driver();d.submit.side_effect=RuntimeError('request text=secret-user-data')
        with patch.object(forms,'Native',return_value=d):r=forms.execute(e,config())
        self.assertEqual(r['status'],'unconfirmed');d.submit.assert_called_once();self.assertNotIn('secret-user-data',str(r))
    def test_business_validation_failure_not_counted_as_pass(self):
        e,d=self.setup_driver();d.text.side_effect=['报修','手机号格式错误']
        with patch.object(forms,'Native',return_value=d):r=forms.execute(e,config())
        self.assertEqual(r['status'],'failed')
    def test_no_success_marker_times_out_without_retry(self):
        e,d=self.setup_driver();d.text.side_effect=None;d.text.return_value='报修'
        with patch.object(forms,'Native',return_value=d),patch.object(forms.time,'monotonic',side_effect=[0,20]):r=forms.execute(e,config())
        self.assertEqual(r['status'],'unconfirmed');d.submit.assert_called_once()
    def test_stop_before_submit(self):
        e,d=self.setup_driver();e.stopped.side_effect=[False,True]
        with patch.object(forms,'Native',return_value=d):r=forms.execute(e,config())
        self.assertFalse(r['submitted']);d.submit.assert_not_called()

class NativeInputTests(unittest.TestCase):
    def test_ambiguous_fields_are_rejected(self):
        e=Mock();e.source.return_value='<hierarchy><node class="android.widget.EditText" hint="姓名"/><node class="android.widget.EditText" hint="姓名"/></hierarchy>'
        with self.assertRaises(forms.FormError):forms.Native(e).resolve('姓名','text')
    def test_input_is_read_back_and_missing_text_fails(self):
        e=Mock();e.base='/s';e.find.return_value='id'
        e.source.side_effect=['<hierarchy><node class="android.widget.EditText" hint="姓名"/></hierarchy>','<hierarchy><node class="android.widget.EditText" hint="姓名" text="wrong"/></hierarchy>']
        with self.assertRaises(forms.FormError):forms.Native(e).fill(config()['fields'][0])

class ExplorationTests(unittest.TestCase):
    SOURCE='<hierarchy><node class="android.widget.TextView" package="test.app" text="报修"/><node class="android.widget.EditText" package="test.app" hint="姓名"/><node class="android.widget.Button" package="test.app" text="提交" clickable="true"/></hierarchy>'
    def explorer(self):
        e=Explorer(Mock(),'s','Android',lambda _:None,lambda *a:None);e.app_package='test.app';e.source=Mock(return_value=self.SOURCE);return e
    def test_form_is_attempted_once_even_if_still_on_same_page(self):
        e=self.explorer()
        with patch.object(forms,'execute',return_value={'status':'unconfirmed','reason':'复核','submitted':True}) as run,patch('automation.time.sleep'):
            r=e.explore({'form':config(),'max_scrolls':0})
        run.assert_called_once();self.assertEqual(len(r['forms']),1);self.assertTrue(r['issues']);e.call.assert_not_called()
    def test_disabled_form_never_fills_or_submits(self):
        e=self.explorer()
        with patch.object(forms,'execute') as run,patch('automation.time.sleep'):r=e.explore({'form':{'enabled':False},'max_scrolls':0})
        run.assert_not_called();self.assertEqual(r['forms'],[]);self.assertTrue(any('提交' in x['label'] for x in r['skipped']))
    def test_unvisited_form_is_explicitly_not_executed(self):
        e=self.explorer();c=config();c['page']='不存在'
        with patch('automation.time.sleep'):r=e.explore({'form':c,'max_scrolls':0})
        self.assertEqual(r['forms'][0]['status'],'not_reached');self.assertTrue(r['issues'])


class WebInputTests(unittest.TestCase):
    def test_web_text_uses_driver_input_and_checks_actual_dom_value(self):
        w=Mock();w.e.base='/session/s';w.js.side_effect=[{ELEMENT:'field'}, {ELEMENT:'field'}, True]
        forms.Web(w).fill(config()['fields'][0])
        paths=[c.args[1] for c in w.e.call.call_args_list]
        self.assertEqual(paths,['/session/s/element/field/clear','/session/s/element/field/value'])
        self.assertIn('value===',w.js.call_args.args[0])
    def test_web_invalid_required_fields_block_click(self):
        w=Mock();w.js.side_effect=[{ELEMENT:'submit'},False]
        with self.assertRaises(forms.FormError):forms.Web(w).prepare_submit(config())
        w.e.call.assert_not_called()
    def test_web_checkbox_verifies_checked_state(self):
        w=Mock();w.e.base='/s';w.js.side_effect=[{ELEMENT:'check'},False,{ELEMENT:'check'},True]
        forms.Web(w).fill({'label':'测试选项','kind':'checkbox','value':True})
        w.e.call.assert_called_once_with('POST','/s/element/check/click',{})

class FormHTTPTests(unittest.TestCase):
    def test_invalid_form_is_rejected_before_batch_queue(self):
        import app,threading,urllib.request,urllib.error
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            c={'test_mode':'explore','explore':{'form':{'enabled':True}},'targets':[{'platform':'Android','device':'mock'}],'bundle':'test.app'}
            u=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with self.assertRaises(urllib.error.HTTPError) as error:
                u.open(urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/batch',data=json.dumps(c).encode(),headers={'Content-Type':'application/json'}))
            self.assertEqual(error.exception.code,400)
            self.assertIn('页面识别文字',json.load(error.exception)['error'])
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
