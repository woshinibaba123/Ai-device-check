import unittest
from unittest.mock import patch,MagicMock
import ai_operator as op
class H5ObserveTests(unittest.TestCase):
 def test_h5_success_does_not_read_native_source(self):
  e=MagicMock();e.prefer_webview=True;e.secrets=[]
  with patch.object(op.hybrid_webview,'WebView') as cls:
   cls.return_value.__enter__.return_value.snapshot.return_value={'path':'/clean/detail','text':'清洁记录','controls':[{'text':'清洁记录','tag':'BUTTON'}]}
   page,targets,_,_=op.observe(e)
  e.source.assert_not_called()
  self.assertEqual(page['route'],'/clean/detail')
  self.assertEqual(targets['w0'][0],'web')
 def test_h5_back_uses_header_flow_without_native_tree(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  e=SimpleNamespace(prefer_webview=True,source=Mock(),back=Mock())
  with patch.object(op.hybrid_webview,'WebView') as cls:
   op.execute(e,{'action':'back'},{},{})
  cls.return_value.__enter__.return_value.perform.assert_called_once_with({'action':'web_back'})
  e.source.assert_not_called();e.back.assert_not_called()

class LiveDecisionTests(unittest.TestCase):
 def test_fenced_decision_is_accepted(self):
  self.assertEqual(op.parse_live_decision('```json\n{"action":"tap","target":"w1"}\n```'),{'action':'tap','target':'w1'})
 def test_truncated_or_multiple_decisions_rejected(self):
  for value in ('{"action":"tap"','{"action":"tap"}{"action":"back"}','[]'):
   with self.assertRaises(ValueError):op.parse_live_decision(value)

class H5ScrollTests(unittest.TestCase):
 def test_web_scroll_does_not_query_native_dimensions(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  e=SimpleNamespace(prefer_webview=True,scroll=Mock())
  with patch.object(op.hybrid_webview,'WebView') as cls:op.execute(e,{'action':'scroll'},{},{})
  cls.return_value.__enter__.return_value.perform.assert_called_once_with({'action':'web_scroll'})
  e.scroll.assert_not_called()

class RootExitTests(unittest.TestCase):
 def test_resumed_home_does_not_exit_before_business_checks(self):
  from test_ai_operator import Device
  e=Device();e.prefer_webview=True
  labels=['今日','昨日','七日','机器人名称','清洁记录']
  controls=[{'id':'w'+str(i),'text':v,'editable':False} for i,v in enumerate(labels)]
  page=({'text':'C4:3C:B0:AA:F9:CF 清洁记录','route':'/','controls':controls},{'w0':('web',{'text':'今日','tag':'div'})},'<hierarchy/>','same')
  cfg={'goal':'进入门店列表，搜索测试门店，查看今日和清洁记录','target_robot':'C4:3C:B0:AA:F9:CF','recover_start':True,'share_page':True,'seconds':60,'max_actions':3}
  prompts=[]
  def ask(prompt,*a,**kw):prompts.append(prompt);return {'action':'back'}
  with patch.object(op,'observe',return_value=page),patch.object(op.ai_fastpath,'next_step',return_value=None),patch.object(op,'execute') as execute,patch.object(op.cancellation.Control,'sleep'):
   result=op.run(e,cfg,ask=ask)
  execute.assert_not_called()
  self.assertEqual(result['termination'],'premature_h5_exit')
  self.assertIn('门店搜索和设备进入已完成',prompts[0])
  self.assertTrue(e.prefer_webview)
