import base64
import unittest
from unittest.mock import patch
import visual_navigation as v
from test_ai_operator import Device
from vision_probe import test_image

class LocateTapTests(unittest.TestCase):
    def device(self,changed=False):
        e=Device();e.platform='iOS';image=base64.b64encode(test_image()).decode();n=[0]
        def call(method,path,*args):
            e.calls.append((method,path,*args))
            if path.endswith('current_package'):return e.app_package
            if path.endswith('window/rect'):return {'width':200,'height':150}
            if path.endswith('screenshot'):
                n[0]+=1
                return base64.b64encode(b'changed').decode() if changed and n[0]>1 else image
        e.call=call
        return e
    def test_scales_and_clicks_once(self):
        e=self.device()
        with patch.object(v.midscene_bridge,'query',return_value={'value':{'center':[300,200]}}):r=v.tap(e,'我的',{})
        self.assertEqual(r['center'],[150,100])
        self.assertEqual(sum(c[0]=='POST' for c in e.calls),1)
    def test_changed_screenshot_never_clicks(self):
        e=self.device(True)
        with patch.object(v.midscene_bridge,'query',return_value={'value':{'center':[300,200]}}):
            with self.assertRaises(ValueError):v.tap(e,'我的',{})
        self.assertFalse(any(c[0]=='POST' for c in e.calls))
    def test_sensitive_target_never_calls_model(self):
        with patch.object(v.midscene_bridge,'query') as query:
            with self.assertRaises(ValueError):v.tap(self.device(),'退出账号',{})
        query.assert_not_called()
    def test_out_of_bounds_never_clicks(self):
        e=self.device()
        with patch.object(v.midscene_bridge,'query',return_value={'value':{'center':[500,200]}}):
            with self.assertRaises(ValueError):v.tap(e,'我的',{})
        self.assertFalse(any(c[0]=='POST' for c in e.calls))

    def test_source_timeout_enters_midscene_click(self):
        import ai_operator as op
        e=Device()
        with patch.object(op,'observe',side_effect=TimeoutError('timeout of 30000ms')), patch.object(op.visual_navigation,'tap',return_value={'center':[10,20]}) as tap, patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,{'goal':'进入我的','share_page':True,'max_actions':1,'seconds':90},ask=lambda *a,**k:self.fail('must not use text planner'))
        tap.assert_called_once()
        self.assertEqual(result['steps'][0]['origin'],'midscene_locate')

    def test_one_source_timeout_switches_remaining_navigation_to_visual(self):
        import ai_operator as op
        e=Device()
        with patch.object(op,'observe',side_effect=TimeoutError('timeout of 30000ms')) as observe, patch.object(op.visual_navigation,'tap',return_value={'center':[10,20]}) as tap, patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,{'goal':'进入我的-通用设置，语言设置为日语','share_page':True,'max_actions':4,'seconds':90})
        self.assertEqual(observe.call_count,1)
        self.assertEqual([call.args[1] for call in tap.call_args_list],['我的','通用设置','语言设置','日语'])
        self.assertEqual(len(result['steps']),4)

class FrameMatchTests(unittest.TestCase):
    def image(self,region=None):
        import io
        from PIL import Image,ImageDraw
        im=Image.new('RGB',(400,800),'white')
        if region:ImageDraw.Draw(im).rectangle(region,fill='black')
        out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()
    def test_status_bar_change_is_ignored(self):
        self.assertTrue(v.frame_matches(self.image(),self.image((0,0,399,25)),[300,700]))
    def test_target_change_is_rejected(self):
        self.assertFalse(v.frame_matches(self.image(),self.image((290,690,310,710)),[300,700]))
    def test_scene_change_is_rejected(self):
        self.assertFalse(v.frame_matches(self.image(),self.image((0,100,399,500)),[300,700]))
