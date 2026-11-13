import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import app,app_adapter,automation,case_runner,execution_profile,login_flow,run_events

HOME='<hierarchy><node class="android.widget.Button" text="首页" clickable="true"/><node class="android.widget.Button" text="我的" clickable="true"/></hierarchy>'
FORM='<hierarchy><node class="android.widget.EditText" text="账号"/><node class="android.widget.EditText" password="true"/><node class="android.widget.Button" text="首页" clickable="true"/></hierarchy>'

class ProfileTests(unittest.TestCase):
 def test_installed_mode_cannot_inherit_build_or_probes(self):
  original={'execution_mode':'installed','bundle':'com.example','source':'/old/source','app':'/old/app.apk','login_probe':'old','http_manifest':{'paths':['/api']},'route_tracking':True}
  cfg=execution_profile.normalize(original)
  self.assertEqual(cfg['source'],'');self.assertEqual(cfg['app'],'')
  for key in ('login_probe','http_manifest','route_tracking'):self.assertNotIn(key,cfg)
  self.assertEqual(original['source'],'/old/source')
 def test_installed_mode_requires_existing_device_and_identity(self):
  for cfg in [{'execution_mode':'installed'}, {'execution_mode':'installed','bundle':'com.example','targets':[{'profile':{'id':'mi17'}}]}]:
   with self.assertRaises(ValueError):execution_profile.normalize(cfg)
 def test_source_reused_artifact_retains_observer(self):
  cfg=execution_profile.normalize({'execution_mode':'source','business_source':'/source','app':'/test.apk','login_probe':'valid'},runtime=True)
  self.assertEqual(cfg['login_probe'],'valid')
 def test_old_package_ui_proof_does_not_claim_observer(self):
  login={'enabled':True,'flow':'keenon_china','success':{'value':'首页'}}
  self.assertEqual(execution_profile.login_policy(login,'installed'),'ui')
  with self.assertRaises(ValueError):execution_profile.login_policy(dict(login,verification='observer'),'installed')
 def test_ui_proof_requires_noncredential_marker(self):
  for login in [{'enabled':True},{'enabled':True,'account':'test','success':{'value':'test'}}]:
   with self.assertRaises(ValueError):execution_profile.login_policy(login,'installed')
 def test_preview_never_echoes_credentials(self):
  result=execution_profile.preview({'execution_mode':'installed','bundle':'com.example','login':{'enabled':True,'account':'private-name','password':'private-secret','success':{'value':'首页'}}})
  text=json.dumps(result);self.assertNotIn('private-name',text);self.assertNotIn('private-secret',text)
  self.assertEqual(result['capabilities']['network_observer'],'不可用')

class TargetTests(unittest.TestCase):
 def setUp(self):self.adapter=app_adapter.load('keenon_legacy')
 def test_logical_identity_does_not_require_source_key(self):
  nodes=automation.parse_ui(HOME)
  node=app_adapter.resolve(nodes,'main.mine',self.adapter)
  self.assertEqual(node['label'],'我的')
  self.assertIs(case_runner.find_node(nodes,{'action':'tap','by':'target','value':'main.mine'},adapter=self.adapter),node)
 def test_wrong_page_and_duplicate_buttons_are_blocked(self):
  for xml in ['<hierarchy><node text="我的" clickable="true"/></hierarchy>',HOME.replace('</hierarchy>','<node text="我的" clickable="true"/></hierarchy>')]:
   with self.assertRaises(case_runner.CaseBlocked):app_adapter.resolve(automation.parse_ui(xml),'main.mine',self.adapter)
 def test_parent_child_duplicates_are_one_target(self):
  xml='<hierarchy><node text="账号"/><node class="android.widget.Button" clickable="true"><node text="账号密码登录"/></node></hierarchy>'
  self.assertTrue(app_adapter.resolve(automation.parse_ui(xml),'login.password_mode',self.adapter)['clickable'])
 def test_target_plan_validates_without_source(self):
  result=case_runner.validate_plan({'steps':[{'action':'tap','by':'target','value':'main.mine'},{'action':'assert','by':'target','value':'main.mine'}]})
  self.assertEqual(result['steps'][0]['by'],'target')
 def test_adapter_paths_cannot_escape_registry(self):
  with self.assertRaises(ValueError):app_adapter.load('../secret')

class UiLoginTests(unittest.TestCase):
 def test_login_form_never_proves_home(self):
  e=Mock();e.source.return_value=FORM
  self.assertIsNone(login_flow.ui_confirmation(e,{'value':'首页'}))
 def test_duplicate_home_markers_do_not_prove_success(self):
  e=Mock();e.source.return_value=HOME.replace('</hierarchy>','<node text="首页" clickable="true"/></hierarchy>')
  self.assertIsNone(login_flow.ui_confirmation(e,{'value':'首页'}))
 def test_existing_old_package_session_has_explicit_ui_level(self):
  e=automation.Explorer(lambda *args:HOME,'s','Android',lambda *args:None,lambda *args:None)
  with patch('automation.time.sleep'):
   result=e.login({'enabled':True,'flow':'keenon_china','verification':'ui','account':'test','password':'secret','success':{'value':'首页'}})
  self.assertEqual(result['verification_level'],'ui');self.assertFalse(result['backend_verified'])
 def test_preset_submits_without_source_probe_using_ui_evidence(self):
  from test_automation import FakeDriver
  driver=FakeDriver(login=True);source=driver.source
  driver.source=lambda:HOME if driver.state=='A' else source()
  e=automation.Explorer(driver,'s','Android',lambda *args:None,lambda *args:self.fail('login screenshot'))
  with patch('automation.time.sleep'),patch('login_flow.prepare'),patch('login_flow.fill_account'),patch('login_flow.agree_checkbox'),patch('login_flow.agree_dialog'):
   result=e.login({'enabled':True,'flow':'keenon_china','verification':'ui','account':'test','password':'secret','success':{'value':'首页'}})
  self.assertIn('登录',driver.clicked);self.assertEqual(result['verification_level'],'ui')

class EventTests(unittest.TestCase):
 def test_event_records_counts_and_failure_without_payload(self):
  with tempfile.TemporaryDirectory() as tmp:
   job={'id':'run'};rec=run_events.Recorder(Path(tmp),job)
   self.assertEqual(rec.call('input',lambda:'private-response'),'private-response')
   def fail():raise RuntimeError('private-secret')
   with self.assertRaises(RuntimeError):rec.call('input',fail)
   text=(Path(tmp)/'events.jsonl').read_text()
   self.assertNotIn('private-response',text);self.assertNotIn('private-secret',text)
   self.assertEqual(job['command_timings']['input']['failures'],1)

class InstalledJobTests(unittest.TestCase):
 def test_installed_job_never_builds_uninstalls_or_clears_data(self):
  requests=[];commands=[]
  def request(method,path,data=None):
   requests.append((method,path,data))
   if path=='/session':return {'sessionId':'fake','capabilities':{'appPackage':'com.example'}}
   if path.endswith('/source'):return HOME
   if path.endswith('/screenshot'):return 'aGVsbG8='
   return None
  def command(args):commands.append(args);return {'ok':True,'output':'versionName=2.7.0 versionCode=72'}
  monitor=Mock();monitor.result={'issues':[],'api_errors':[]};monitor.current_issues=[];monitor.should_capture.return_value=False
  with tempfile.TemporaryDirectory() as tmp,patch.object(app,'ROOT',Path(tmp)),patch.object(app,'request',side_effect=request),patch.object(app,'raw_request'),patch.object(app,'command',side_effect=command),patch.object(app,'android_tools',return_value=('/mock/adb','/mock/emulator')),patch.object(app.hybrid_webview,'ensure_driver',return_value=None),patch.object(app.page_diagnostics,'Monitor',return_value=monitor),patch.object(app.threading,'Thread'),patch.object(app.cancellation.Control,'sleep'),patch.object(app.host_runtime,'copy_source') as copy_source:
   job={'id':'old','status':'running','logs':[],'screenshots':[]};app.JOBS['old']=job
   import runtime_metrics
   prior_recorder=runtime_metrics.recorder.get()
   app.run_job('old',{'execution_mode':'installed','platform':'Android','device':'mock-device','bundle':'com.example','source':'/stale/source','app':'/stale/app.apk','steps':[]})
   self.assertIs(runtime_metrics.recorder.get(),prior_recorder)
   self.assertEqual(job['status'],'passed',job['logs']);copy_source.assert_not_called()
   caps=requests[0][2]['capabilities']['alwaysMatch'];self.assertNotIn('appium:app',caps);self.assertTrue(caps['appium:noReset'])
   self.assertFalse(any('uninstall' in c or ('pm' in c and 'clear' in c) for c in commands))
   self.assertEqual(job['app_identity']['version_name'],'2.7.0')
   self.assertEqual(job['capabilities']['network_observer'],'unavailable')
   self.assertTrue((Path(tmp)/'reports/old/events.jsonl').exists())


class CaseEvidenceTests(unittest.TestCase):
 def run_plan(self,steps,policy='assertions'):
  from types import SimpleNamespace
  e=SimpleNamespace(settled_source=lambda:HOME,source=lambda:HOME,secrets=[],tap=Mock())
  row={'id':'S:1','sheet':'S','row':1,'title':'UI检查','group':'App','priority':'P1','precondition':'','mobile':True,'steps':'明确步骤','expected':'明确断言','plan_text':json.dumps({'requires':[{'action':'assert','value':'首页'}],'steps':steps})}
  result=case_runner.run(e,{'cases':[row]},{'start_from_current':True,'evidence_policy':policy},lambda *args:None,lambda *args:None,lambda *args:None,lambda:False,lambda *args:None)[0]
  return e,result
 def test_normal_assertions_do_not_require_a_screenshot_each_step(self):
  e,result=self.run_plan([{'action':'tap','value':'我的'},{'action':'assert','value':'我的'}])
  self.assertEqual(result['result'],'pass',result);self.assertEqual(result['verification_level'],'ui');self.assertEqual(result['screenshots'],[])
 def test_screenshot_policy_does_not_hide_failed_assertion(self):
  e,result=self.run_plan([{'action':'assert','value':'不存在的内容'}])
  self.assertEqual(result['result'],'fail');self.assertEqual(result['status'],'断言失败')
 def test_missing_route_observer_blocks_before_any_tap(self):
  e,result=self.run_plan([{'action':'tap','value':'我的'},{'action':'assert_route','value':'/my'}])
  e.tap.assert_not_called();self.assertEqual(result['status'],'执行受阻');self.assertIn('观察器',result['reason'])
 def test_legacy_strict_screenshot_policy_is_retained(self):
  e,result=self.run_plan([{'action':'assert','value':'我的'}],'screenshots')
  self.assertEqual(result['result'],'fail');self.assertIn('截图',result['reason'])

if __name__=='__main__':unittest.main()
