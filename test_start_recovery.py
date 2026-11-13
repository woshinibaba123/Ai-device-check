import unittest
from ai_operator import recover_start
class RecoveryTests(unittest.TestCase):
 def test_other_page_returns(self):
  self.assertEqual(recover_start({'text':'通用设置','controls':[]},'门店A')['state'],'back')
 def test_bound(self):
  self.assertEqual(recover_start({'text':'设置','controls':[]},'门店A',backs=6)['state'],'blocked')
 def test_exact_store(self):
  self.assertEqual(recover_start({'text':'门店A\n设备（2）','controls':[]},'门店A')['state'],'store')
 def test_wrong_store_returns(self):
  self.assertEqual(recover_start({'text':'门店B\n设备（2）','controls':[]},'门店A')['state'],'back')
 def test_robot_identity_required(self):
  p={'text':'清洁记录\nAA:BB:CC:DD:EE:FF','controls':[]}
  self.assertEqual(recover_start(p,'门店A','AA:BB:CC:DD:EE:FF')['state'],'robot')
  self.assertEqual(recover_start(p,'门店A','11:22:33:44:55:66')['state'],'back')
 def test_form_not_abandoned(self):
  self.assertEqual(recover_start({'text':'设置','controls':[{'editable':True,'text':'名称'}]},'门店A')['state'],'blocked')

class EmptyStartRecoveryTests(unittest.TestCase):
 def test_empty_native_tree_probes_dom_before_stopping(self):
  from unittest.mock import patch
  import ai_operator as op
  from test_ai_operator import Device
  e=Device();robot='C4:3C:B0:AA:F9:CF'
  empty=({'text':'','controls':[],'route':''},{},'<hierarchy/>','empty')
  dom=({'text':robot+' 清洁记录','controls':[{'id':'w0','text':'清洁记录','editable':False}],'route':'/'},{'w0':('web',{'text':'清洁记录','tag':'div'})},'<hierarchy/>','dom')
  cfg={'goal':'进入门店列表，搜索测试门店，查看清洁机器人','share_page':True,'recover_start':True,'target_robot':robot,'seconds':60,'max_actions':2}
  with patch.object(op,'observe',return_value=empty),patch.object(op,'observe_webview',return_value=dom) as web,patch.object(op.automation,'parse_ui',return_value=[]),patch.object(op.ai_fastpath,'next_step',return_value={'action':'blocked','origin':'local_path','reason':'检查结束'}),patch.object(op.cancellation.Control,'sleep'):
   result=op.run(e,cfg,ask=lambda *a,**k:self.fail('No AI needed'))
  self.assertTrue(e.prefer_webview)
  web.assert_called_once()
  self.assertNotIn('页面结构为空',result.get('termination_detail',''))
 def test_genuinely_empty_start_is_bounded(self):
  from unittest.mock import patch
  import ai_operator as op
  from test_ai_operator import Device
  e=Device();empty=({'text':'','controls':[],'route':''},{},'<hierarchy/>','empty')
  cfg={'goal':'进入门店列表，搜索测试门店','share_page':True,'recover_start':True,'seconds':60,'max_actions':5}
  with patch.object(op,'observe',return_value=empty),patch.object(op,'observe_webview',side_effect=RuntimeError('no webview')) as web,patch.object(op.automation,'parse_ui',return_value=[]),patch.object(op.cancellation.Control,'sleep'):
   result=op.run(e,cfg,ask=lambda *a,**k:self.fail('Empty page must not be guessed'))
  self.assertEqual(web.call_count,3)
  self.assertIn('页面结构为空',result.get('termination_detail',''))

class StoreListVisualStartTests(unittest.TestCase):
 def test_start_verification_requires_exact_store_and_list(self):
  import ai_operator as op
  from unittest.mock import patch,Mock
  from types import SimpleNamespace
  e=SimpleNamespace(platform='Android',device_id='serial',stopped=lambda:False)
  for page,expected in [({'page':'equipment_list','store_name':'目标门店'},True),({'page':'equipment_list','store_name':'其他门店'},False),({'page':'other','store_name':'目标门店'},False)]:
   with patch('android_visual.AndroidVisual'),patch('midscene_bridge.query',return_value={'value':page}):
    self.assertEqual(op.verified_store_list_start(e,'目标门店',{}),expected)
 def test_verified_list_skips_initial_tree(self):
  import ai_operator as op
  from test_ai_operator import Device
  from unittest.mock import patch
  e=Device();cfg={'goal':'进入门店列表，搜索目标门店，查看清洁机器人','recover_start':True,'midscene_first':True,'share_page':True,'seconds':60,'max_actions':1}
  with patch.object(op.visual_navigation,'tap',side_effect=ValueError('cache miss')),patch.object(op,'verified_store_list_start',return_value=True),patch.object(op,'observe') as observe,patch.object(op.visual_list,'decide',return_value={'action':'blocked','origin':'visual_store_review','reason':'测试停止'}),patch.object(op.cancellation.Control,'sleep'):
   result=op.run(e,cfg)
  observe.assert_not_called()
  self.assertNotEqual(result['termination'],'start_page_unreadable')
