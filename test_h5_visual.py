import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
import ai_operator as op,hybrid_webview
class FallbackTests(unittest.TestCase):
 def test_only_missing_dom_tap_uses_visual(self):
  e=SimpleNamespace(prefer_webview=True,secrets=[],h5_visual_config={})
  with patch.object(op.hybrid_webview,'WebView') as web,patch('h5_visual.tap',return_value={'model_calls':1}) as tap:
   web.return_value.__enter__.return_value.perform.side_effect=hybrid_webview.DOMTargetMissing('missing')
   op.execute(e,{'action':'tap','target':'w0'},{'w0':('web',{'text':'清洁记录','tag':'div'})},{})
  tap.assert_called_once()
 def test_ambiguous_and_uncertain_click_are_not_replayed(self):
  for error in (AssertionError('ambiguous'),TimeoutError('click uncertain')):
   e=SimpleNamespace(prefer_webview=True,secrets=[])
   with patch.object(op.hybrid_webview,'WebView') as web,patch('h5_visual.tap') as tap:
    web.return_value.__enter__.return_value.perform.side_effect=error
    with self.assertRaises(type(error)):op.execute(e,{'action':'tap','target':'w0'},{'w0':('web',{'text':'清洁记录','tag':'div'})},{})
    tap.assert_not_called()
 def test_successful_dom_does_not_use_model(self):
  e=SimpleNamespace(prefer_webview=True,secrets=[])
  with patch.object(op.hybrid_webview,'WebView'),patch('h5_visual.tap') as tap:
   op.execute(e,{'action':'tap','target':'w0'},{'w0':('web',{'text':'清洁记录','tag':'div'})},{})
   tap.assert_not_called()

class CanvasTests(unittest.TestCase):
 def test_identical_canvas_reuses_summary(self):
  from vision_probe import test_image
  import h5_visual
  e=SimpleNamespace(stopped=lambda:False,log=Mock())
  with patch.object(h5_visual,'AndroidVisual') as transport,patch.object(h5_visual.midscene_bridge,'query',return_value={'value':{'map_state':'empty','visible_labels':'暂无地图'},'model_calls':1}) as query:
   transport.return_value.screenshot.return_value=test_image()
   first=h5_visual.describe_canvas(e,{})
   self.assertEqual(h5_visual.describe_canvas(e,{}),first)
   query.assert_called_once()
   transport.return_value.tap.assert_not_called()
 def test_visual_fallback_cannot_click_save(self):
  import h5_visual
  e=SimpleNamespace()
  with patch.object(h5_visual,'AndroidVisual') as transport:
   with self.assertRaises(ValueError):h5_visual.tap(e,'保存',{})
   transport.assert_not_called()
