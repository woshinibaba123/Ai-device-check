import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import page_diagnostics as pd
import diagnostic_privacy as privacy
import http_probe
import web_diagnostics_source
from test_ai_operator import Device,node


class PrivacyTests(unittest.TestCase):
    def test_parameters_are_allowlisted_and_credentials_removed(self):
        result=privacy.params({'storeId':12,'sceneCode':'delivery','password':'secret','account':'person@example.org','description':'private text','language':'private-key'},['private-key'])
        self.assertEqual(result['storeId'],12)
        self.assertEqual(result['sceneCode'],'delivery')
        for k in ('password','account','description','language'):self.assertEqual(result[k],'[redacted]')
    def test_url_strips_query_and_user_info(self):
        self.assertEqual(privacy.url('https://user:password@api.test/api/list?token=private'),'https://api.test/api/list')
        self.assertEqual(privacy.route('https://app.test/#/repair?token=private'),'https://app.test/#/repair')
    def test_malformed_parameters_and_string_codes(self):
        e=privacy.api_event({'url':'/api/list','code':'TOKEN_EXPIRED','params':None})
        self.assertEqual(e['code'],'TOKEN_EXPIRED');self.assertEqual(e['params'],{})


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.e=Device();self.e.call=lambda *a,**kw:{'width':100,'height':200}
        self.route='/home';self.now=0
        class Reader:
            latest={}
            def read(inner):return self.route
        self.e.route_reader=Reader()
        self.job={'id':'test-job'}
        self.m=pd.Monitor(self.e,self.job,self.tmp.name,lambda:True,lambda m:None,clock=lambda:self.now)
        self.parser=patch.object(pd.automation,'parse_ui',side_effect=lambda _:self.e.nodes);self.parser.start();self.addCleanup(self.parser.stop)
    def test_api_error_frame_requires_recent_matching_route(self):
        import io
        from PIL import Image
        png=io.BytesIO();Image.new('RGB',(100,200),'gray').save(png,format='PNG')
        self.m.last={'route':'/form'}
        self.m.result['api_errors']=[{'route':'/other','epoch_ms':100000,'url':'/save'},
                                     {'route':'/form','epoch_ms':80000,'url':'/save'}]
        with patch.object(pd.time,'time',return_value=100):
            self.m.capture_recent_api_error_frame(png.getvalue())
            self.assertEqual(self.m.result['issues'],[])
            self.m.result['api_errors'].append({'route':'/form','epoch_ms':99000,'url':'/save','code':615001})
            self.m.capture_recent_api_error_frame(png.getvalue())
            self.m.capture_recent_api_error_frame(png.getvalue())
        self.assertEqual(len(self.m.result['issues']),1)
        self.assertEqual(self.m.result['issues'][0]['type'],'api_error_page')

    def test_blocked_observation_keeps_frame_and_deduplicates_check(self):
        import io
        from PIL import Image
        png=io.BytesIO();Image.new('RGB',(100,200),'gray').save(png,format='PNG')
        observation={'id':'step_4','status':'blocked','evidence':'改名接口成功但回读仍显示原名称'}
        self.m.capture_blocked_observation(png.getvalue(),observation)
        self.m.capture_blocked_observation(png.getvalue(),observation)
        rows=self.m.result['issues']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['source'],'visual_model_observation')
        self.assertEqual(rows[0]['severity'],'suspected')
        self.assertTrue((Path(self.tmp.name)/Path(rows[0]['screenshot']).name).is_file())
        self.m.sensitive=True
        self.m.capture_blocked_observation(png.getvalue(),dict(observation,id='step_5'))
        self.assertEqual(len(rows),1)

    def test_transient_blank_frame_saved_immediately_and_deduplicated(self):
        import io
        from PIL import Image
        png=io.BytesIO();Image.new('RGB',(1080,2400),'white').save(png,format='PNG')
        self.m.observe('<root/>');self.m.before('POST','/session/test/element/x/click',{})
        self.now=.2
        self.m.observe_frame(png.getvalue());self.m.observe_frame(png.getvalue())
        rows=[x for x in self.m.result['issues'] if x['type']=='transition_blank_frame']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['action_to_sample_ms'],200)
        self.assertTrue((Path(self.tmp.name)/Path(rows[0]['screenshot']).name).is_file())
        self.assertEqual(rows[0]['severity'],'suspected')
    def test_blank_frame_outside_action_or_sensitive_is_not_saved(self):
        import io
        from PIL import Image
        png=io.BytesIO();Image.new('RGB',(100,200),'white').save(png,format='PNG')
        self.m.observe_frame(png.getvalue());self.assertFalse(self.m.result['issues'])
        self.m.before('POST','/session/test/element/x/click',{});self.m.sensitive=True
        self.m.observe_frame(png.getvalue());self.assertFalse(self.m.result['issues'])

    def test_h5_business_200_is_success_but_offline_is_failure(self):
        self.m.event({'kind':'api','url':'/api/clean/model','code':200,'http_status':200},'h5')
        self.assertFalse(self.m.result['api_events'][-1]['failed'])
        self.m.event({'kind':'api','url':'/api/clean/strategy','code':615001,'http_status':200},'h5')
        self.assertTrue(self.m.result['api_events'][-1]['failed'])

    def test_native_navigation_records_ms_without_normal_screenshot(self):
        self.m.observe('<root/>');self.m.before('POST','/session/test/element/x/click',{})
        self.route='/settings';self.now=1.25;self.e.nodes=[node('General Settings')];self.m.observe('<root/>')
        event=self.m.result['navigation'][0]
        self.assertEqual(event['action_to_content_ms'],1250)
        self.assertEqual(event['from'],'/home');self.assertEqual(event['to'],'/settings')
        self.assertFalse(self.m.should_capture('normal'))
    def test_h5_ready_after_intermediate_route_sample(self):
        self.m.observe_h5({'route':'/home','ready':True,'sample':{'content':True}})
        self.m.before('POST','/session/test/element/x/click',{})
        self.now=.3
        self.m.observe_h5({'route':'/#/target','ready':False,'sample':{'content':False}})
        self.now=1.2
        self.m.observe_h5({'route':'/#/target','ready':True,'sample':{'content':True}})
        row=self.m.result['navigation'][0]
        self.assertEqual(row['status'],'content_ready')
        self.assertEqual(row['to'],'/#/target')
        self.assertEqual(row['action_to_content_ms'],1200)

    def test_unready_target_is_preserved_without_load_duration(self):
        self.m.observe_h5({'route':'/home','ready':True,'sample':{'content':True}})
        self.m.before('POST','/session/test/element/x/click',{})
        self.m.observe_h5({'route':'/#/target','ready':False,'sample':{'content':False}})
        self.now=2
        self.m.before('POST','/session/test/element/y/click',{})
        row=self.m.result['navigation'][0]
        self.assertEqual(row['to'],'/#/target')
        self.assertIsNone(row['action_to_content_ms'])
        self.assertEqual(row['observed_elapsed_ms'],2000)

    def test_same_page_ready_does_not_claim_navigation(self):
        data={'route':'/home','ready':True,'sample':{'content':True}}
        self.m.observe_h5(data)
        self.m.before('POST','/session/test/element/x/click',{})
        self.now=1
        self.m.observe_h5(data)
        row=self.m.result['navigation'][0]
        self.assertEqual(row['status'],'same_page_ready')
        self.assertEqual(row['to'],'/home')
        self.assertIsNone(row['action_to_content_ms'])

    def test_native_to_webview_segments_use_device_events(self):
        self.m.action_starts=[{'epoch_ms':1000,'from':'/native','native':True,'clock_uncertainty_ms':4}]
        self.m.event({'kind':'webview_created','id':'web1','epoch_ms':6000},'h5','run1')
        self.m.event({'kind':'h5_ready','id':'web1','epoch_ms':17000,'route':'https://app.test/#/target'},'h5','run1')
        row=self.m.result['webview_transitions'][0]
        self.assertEqual((row['total_ms'],row['action_to_webview_ms'],row['webview_to_h5_content_ms']),(16000,5000,11000))
        import html_report
        self.assertIn('16s（5+11）',html_report.render(self.job))
        self.m.event({'kind':'h5_ready','id':'web1','epoch_ms':19000,'route':'https://app.test/#/next'},'h5','run1')
        self.assertEqual(len(self.m.result['webview_transitions']),1)

    def test_missing_clock_or_h5_action_does_not_invent_segments(self):
        for starts in ([],[{'epoch_ms':1000,'from':'/web','native':False,'clock_uncertainty_ms':2}]):
            self.m.action_starts=starts
            self.m.event({'kind':'webview_created','id':str(starts),'epoch_ms':6000},'h5')
            self.m.event({'kind':'h5_ready','id':str(starts),'epoch_ms':17000},'h5')
        self.assertEqual(self.m.result['webview_transitions'],[])

    def test_action_boundary_is_calibrated_to_device_clock(self):
        from types import SimpleNamespace
        self.m.observe('<root/>')
        self.e.web_probe=SimpleNamespace(device_clock=lambda:{'epoch_ms':1000,'monotonic':50,'uncertainty_ms':5})
        with patch.object(pd.time,'monotonic',return_value=50.2):
            self.m.before('POST','/session/test/element/x/click',{})
        self.assertAlmostEqual(self.m.action_starts[0]['epoch_ms'],1200)
        self.assertTrue(self.m.action_starts[0]['native'])

    def test_device_clock_read_failure_does_not_block_action(self):
        from types import SimpleNamespace
        self.m.observe('<root/>')
        self.e.web_probe=SimpleNamespace(device_clock=lambda:None)
        self.m.before('POST','/session/test/element/x/click',{})
        self.assertIsNotNone(self.m.pending)
        self.assertEqual(self.m.action_starts,[])

    def test_visual_native_entry_records_total_without_source_observers(self):
        self.e.route_reader=None
        self.m.native_page('设备列表（已核对目标MAC）')
        self.m.before('POST','/visual/actions',{})
        self.now=5
        self.m.observe_h5({'route':'https://app.test/','ready':False,'sample':{'content':False}})
        self.now=16
        self.m.observe_h5({'route':'https://app.test/','ready':True,'sample':{'content':True}})
        rows=self.m.result['webview_observations']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['total_ms'],16000)
        self.assertEqual(rows[0]['first_webview_observed_ms'],5000)
        self.assertEqual(self.m.result['webview_transitions'],[])
        import html_report
        report=html_report.render(self.job)
        self.assertIn('16.00s（观察上界；分段未采集）',report)
        self.assertNotIn('16s（5+11）',report)

    def test_native_routes_collected_without_native_ui_source(self):
        self.e.route_reader.latest={'run':'run1','events':[{'from':'/home','route':'/settings','route_started_us':1000,'route_to_first_frame_ms':25}]}
        self.m.collect(force=True)
        self.m.collect(force=True)
        self.assertEqual(len(self.m.result['native_route_frames']),1)
        self.assertEqual(self.m.result['native_route_frames'][0]['from'],'/home')
        import html_report
        self.assertIn('25.0ms',html_report.render(self.job))

    def test_blank_requires_persistence(self):
        self.e.nodes=[];self.m.observe('<root/>');self.assertFalse(self.m.should_capture('normal'))
        self.now=11;self.m.observe('<root/>')
        self.assertTrue(self.m.should_capture('normal'))
        self.assertEqual(self.m.result['issues'][0]['type'],'blank_screen_suspected')
    def test_loading_indicator_not_called_white_screen(self):
        self.e.nodes=[node('',kind='android.widget.ProgressBar',clickable=False)];self.m.observe('<root/>')
        self.now=11;self.m.observe('<root/>');self.assertEqual(self.m.result['issues'],[])
        self.now=31;self.m.observe('<root/>');self.assertEqual(self.m.result['issues'][0]['type'],'loading_stalled')
    def test_visible_error_is_captured_but_secure_form_never_is(self):
        self.e.nodes=[node('页面加载失败')];self.m.observe('<root/>');self.assertTrue(self.m.should_capture('normal'))
        self.e.nodes=[node('password',secure=True)];self.m.observe('<root/>');self.assertFalse(self.m.should_capture(999))
    def test_failure_capture_even_without_visible_error(self):
        self.assertTrue(self.m.should_capture('case-1-failure'));self.assertTrue(self.m.should_capture(999))
        self.assertFalse(self.m.should_capture('case-1-step-2'))
    def test_native_horizontal_clipping_debounced(self):
        self.e.nodes=[node('Button',bounds='[90,50][120,90]')];self.m.observe('<root/>')
        self.assertFalse(self.m.current_issues)
        self.now=1.2;self.m.observe('<root/>');self.assertIn('control_clipped',self.m.current_issues)
    def test_api_business_error_records_address_code_safe_parameters(self):
        event={'kind':'api','url':'https://api.test/api/test?token=secret','method':'POST','http_status':200,'code':610500,'elapsed_ms':42,'params':{'body':{'storeId':10,'password':'secret','description':'private'}}}
        self.m.event(event,'h5');self.m.event(event,'h5')
        self.assertEqual(len(self.m.result['api_errors']),1)
        saved=self.m.result['api_errors'][0]
        self.assertEqual(saved['url'],'https://api.test/api/test?token=secret');self.assertEqual(saved['code'],610500)
        self.assertEqual(saved['params']['body']['password'],'secret')
        self.assertIn('private',json.dumps(self.m.result))
    def test_h5_source_timings_kept_separate_from_driver_observations(self):
        self.m.event({'kind':'h5_ready','epoch_ms':1,'route':'https://app.test/#/repair?token=hidden','webview_created_to_h5_ready_ms':1260,'late_attach':False},'h5','run')
        row=self.m.result['webview_loads'][0]
        self.assertEqual(row['webview_created_to_h5_ready_ms'],1260)
        self.assertEqual(row['route'],'https://app.test/#/repair')
    def test_driver_missing_not_a_blank_screen(self):
        self.e.nodes=[node('',kind='android.webkit.WebView')]
        with patch.object(pd.hybrid_webview,'WebView',side_effect=RuntimeError('driver missing')):
            self.m.observe('<root/>');self.now=15;self.m.observe('<root/>')
        self.assertNotIn('blank_screen_suspected',self.m.current_issues)
        self.assertIn('unavailable',self.m.result['coverage']['h5'])
    def test_unobserved_readiness_is_not_reported_as_success(self):
        self.m.observe('<root/>');self.m.before('POST','/session/test/back',{})
        self.now=2;self.m.finalize()
        self.assertEqual(self.m.result['navigation'][0]['status'],'readiness_not_observed_at_end')


class SourceTests(unittest.TestCase):
    def test_native_monitoring_is_optional_and_records_only_safe_parameters(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);f=p/'lib/http/dio_client.dart';f.parent.mkdir(parents=True);f.write_text('void f(){ dio = Dio(options); }')
            m=http_probe.instrument(p,{'api_calls':[{'path':'/api/example'}],'business_success_codes':[610000,0]},monitor=True)
            text=(p/'lib/devicecheck_http_observer.dart').read_text()
            self.assertIn('options.data?.toString()',text);self.assertIn('options.headers',text);self.assertIn('response_body',text)
            self.assertIn('elapsed_ms',text);self.assertEqual(m['diagnostics_version'],'native_diagnostics_v1')
            self.assertNotIn('events.add(event))',text)


if __name__=='__main__':unittest.main()
