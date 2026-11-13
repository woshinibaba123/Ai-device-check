import base64
import unittest
from unittest.mock import patch
import visual_list
from test_ai_operator import Device
from vision_probe import test_image

class VisualRecoveryTests(unittest.TestCase):
    def check(self,state,visible=False):
        e=Device();e.call=lambda *a:base64.b64encode(test_image()).decode()
        with patch.object(visual_list.automation,'parse_ui',return_value=[]), patch.object(visual_list.midscene_bridge,'query',return_value={'value':{'state':state,'target_visible':visible}}):
            return visual_list.decide(e,'<root/>',{},30)
    def test_list_without_target_scrolls(self):
        self.assertEqual(self.check('equipment_list')['action'],'scroll')
    def test_loading_waits(self):
        self.assertEqual(self.check('loading')['action'],'wait')
    def test_target_does_not_trigger_blind_click(self):
        self.assertEqual(self.check('equipment_list',True)['action'],'blocked')
    def test_guide_does_not_scroll(self):
        self.assertEqual(self.check('guide')['action'],'blocked')
    def test_unknown_state_rejected(self):
        with self.assertRaises(ValueError):self.check('invented')

    def test_empty_store_recovers_without_text_planner(self):
        import ai_operator as op
        e=Device();e.nodes=[]
        cfg={'goal':'进入门店搜索测试然后查看清洁机器人','share_page':True,'seconds':30,'max_actions':6,'local_store_navigation':True}
        plan={'kind':'store_lookup','cursor':3,'query':'测试'}
        with patch.object(op.ai_fastpath,'compile_goal',return_value=plan), patch.object(op.automation,'parse_ui',return_value=[]), patch.object(op.cancellation.Control,'sleep'), patch.object(op.visual_list,'decide',return_value={'action':'blocked','origin':'visual_store_review','reason':'视觉测试受阻'}) as vision:
            result=op.run(e,cfg,ask=lambda *a,**k:self.fail('empty evidence must not go to text planner'))
        self.assertEqual(vision.call_count,1)
        self.assertEqual([s['action'] for s in result['steps']],['wait','wait'])
        self.assertIn('受阻',result['termination_detail'])

class RobotIdentityTests(unittest.TestCase):
    def test_exact_identity_required(self):
        target='C4:3C:B0:AA:F9:CF'
        value={'page':'equipment_list','device_id':target.lower(),
               'cleaning_area_visible':True,'unique_match':True}
        self.assertTrue(visual_list.verified_identity(value,target,'equipment_list'))
        for changes in ({'device_id':'C4:3C:B0:AA:F9:00'},
                        {'cleaning_area_visible':False}, {'unique_match':False},
                        {'page':'other'}, {'cleaning_area_visible':'true'}):
            self.assertFalse(visual_list.verified_identity(dict(value,**changes),target,'equipment_list'))

    def test_verified_robot_enters_detail(self):
        import time
        from unittest.mock import Mock
        target='C4:3C:B0:AA:F9:CF'
        image=test_image(); e=Device(); transport=Mock()
        transport.screenshot.return_value=image
        identity={'page':'equipment_list','device_id':target,'cleaning_area_visible':True,'unique_match':True}
        detail=dict(identity,page='robot_detail')
        with patch.object(visual_list.midscene_bridge,'query',side_effect=[
                {'value':identity},{'value':{'center':[100,100]}}]), patch('local_ocr.locate_mac',side_effect=[None,{'center':[100,100]}]), patch.object(visual_list.cancellation.Control,'sleep'):
            result=visual_list.enter_target(e,transport,image,image,{'target_robot':target},time.monotonic()+30,'hash')
        self.assertEqual(result['action'],'entered')
        transport.tap.assert_called_once_with(100,100)
        self.assertFalse(result['detail_ready'])
        self.assertEqual(result['model_calls'],2)

    def test_carousel_change_does_not_block_stationary_mac(self):
        import time,io
        from PIL import Image
        from unittest.mock import Mock
        target='C4:3C:B0:AA:F9:CF';image=test_image();e=Device();transport=Mock()
        with Image.open(io.BytesIO(image)) as im:
            changed=Image.new('RGB',im.size,'blue');buf=io.BytesIO();changed.save(buf,format='PNG')
        transport.screenshot.return_value=buf.getvalue()
        identity={'page':'equipment_list','device_id':target,'cleaning_area_visible':True,'unique_match':True}
        with patch.object(visual_list.midscene_bridge,'query',return_value={'value':identity}), \
             patch('local_ocr.locate_mac',side_effect=[{'center':[100,100]},{'center':[101,100]}]):
            result=visual_list.enter_target(e,transport,image,image,{'target_robot':target},time.monotonic()+30,'hash')
        self.assertEqual(result['action'],'entered')
        transport.tap.assert_called_once_with(101,100)

    def test_moved_or_missing_mac_is_not_clicked(self):
        import time
        from unittest.mock import Mock
        target='C4:3C:B0:AA:F9:CF';image=test_image()
        identity={'page':'equipment_list','device_id':target,'cleaning_area_visible':True,'unique_match':True}
        for fresh in ({'center':[130,100]},None):
            with self.subTest(fresh=fresh):
                e=Device();transport=Mock();transport.screenshot.return_value=image
                with patch.object(visual_list.midscene_bridge,'query',side_effect=[{'value':identity},{'value':{'page':'other'}}]), \
                     patch('local_ocr.locate_mac',side_effect=[{'center':[100,100]},fresh]):
                    with self.assertRaises(ValueError):
                        visual_list.enter_target(e,transport,image,image,{'target_robot':target},time.monotonic()+30,'hash')
                transport.tap.assert_not_called()

    def test_wrong_robot_never_clicked(self):
        import time
        from unittest.mock import Mock
        transport=Mock(); e=Device()
        with patch.object(visual_list.midscene_bridge,'query',return_value={'value':{'page':'equipment_list','device_id':'wrong'}}):
            with self.assertRaises(ValueError):
                visual_list.enter_target(e,transport,test_image(),test_image(),{'target_robot':'C4:3C:B0:AA:F9:CF'},time.monotonic()+30,'hash')
        transport.tap.assert_not_called()

class H5HandoffTests(unittest.TestCase):
    def test_entry_waits_for_dom_without_reclick_or_native_fallback(self):
        import ai_operator as op
        e=Device();e.device_id='serial'
        cfg={'goal':'查看清洁机器人','share_page':True,'seconds':60,'max_actions':4}
        plan={'kind':'store_lookup','cursor':3,'query':'测试'}
        ready=({'text':'今日 清洁记录','route':'/','controls':[{'id':'w0','text':'清洁记录','editable':False}]},{},'<hierarchy/>','dom')
        with patch.object(op.ai_fastpath,'compile_goal',return_value=plan), \
             patch.object(op,'observe',side_effect=TimeoutError('timeout')) as native, \
             patch.object(op,'observe_webview',side_effect=[RuntimeError('not ready'),ready]) as dom, \
             patch.object(op.visual_list,'decide',return_value={'action':'entered','origin':'visual_clean_entry','model_calls':2}) as scan, \
             patch.object(op.ai_fastpath,'next_step',return_value={'action':'blocked','origin':'local_path','reason':'测试完成'}), \
             patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,cfg,ask=lambda *a,**kw:self.fail('Unexpected model'))
        scan.assert_called_once()
        self.assertTrue(e.prefer_webview)
        self.assertEqual(dom.call_count,2)
        self.assertEqual(native.call_count,1)
        self.assertNotEqual(result['termination'],'robot_detail_unreadable')
