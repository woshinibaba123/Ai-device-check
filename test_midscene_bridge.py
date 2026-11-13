import json
import subprocess
import unittest
from unittest.mock import patch
import midscene_bridge
from vision_probe import test_image

class BridgeTests(unittest.TestCase):
    def test_sdk_result_and_selected_model_propagate(self):
        result={'engine':'midscene','value':{'state':'loading'}}
        response=subprocess.CompletedProcess([],0,'SDK notice\nDEVICECHECK_RESULT='+json.dumps(result)+'\n','')
        with patch.object(midscene_bridge.shutil,'which',return_value='/mock/node'), patch.object(midscene_bridge.cancellation.Control,'run',return_value=response) as run:
            self.assertEqual(midscene_bridge.query(test_image(),'state',{'model':'hy4free','midscene_model':'glm-5.3-flashx'}),result)
        payload=json.loads(run.call_args.kwargs['input'])
        self.assertEqual(payload['model'],'glm-5.3-flashx')
        self.assertEqual((payload['width'],payload['height']),(400,300))
    def test_no_result_fails_closed(self):
        with patch.object(midscene_bridge.shutil,'which',return_value='/mock/node'), patch.object(midscene_bridge.cancellation.Control,'run',return_value=subprocess.CompletedProcess([],1,'','')):
            with self.assertRaises(ValueError):midscene_bridge.query(test_image(),'state',{})

    def test_midscene_default_does_not_inherit_text_model(self):
        response=subprocess.CompletedProcess([],0,'DEVICECHECK_RESULT={"value":{}}\n','')
        with patch.object(midscene_bridge.shutil,'which',return_value='/mock/node'), patch.object(midscene_bridge.cancellation.Control,'run',return_value=response) as run:
            midscene_bridge.query(test_image(),'state',{'model':'hy4std'})
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['model'],'glm-5.3-flashx')

class ResponseFormatTests(unittest.TestCase):
    def normalize(self,text):
        from midscene.codebuddy_worker import normalize_response
        return normalize_response(text,{'type':'json_object'})
    def test_fenced_json_is_normalized(self):
        self.assertEqual(json.loads(self.normalize('```json\n{"color":"red"}\n```')),{'color':'red'})
    def test_invalid_output_is_not_replaced_by_fake_coordinates(self):
        for text in ('not json','[]',''):
            with self.assertRaises(ValueError):self.normalize(text)

class SourceCircuitTests(unittest.TestCase):
    def test_failed_source_is_not_reissued_during_fallback(self):
        from unittest.mock import Mock
        from automation import Explorer
        call=Mock(side_effect=TimeoutError('timeout'))
        e=Explorer(call,'test','Android',Mock(),Mock())
        e.visual_source_fallback=True
        with self.assertRaises(TimeoutError):e.source()
        with self.assertRaisesRegex(TimeoutError,'冷却'):e.source()
        self.assertEqual(call.call_count,1)

class WrappedJsonTests(unittest.TestCase):
    def test_single_complete_json_object_can_be_unwrapped(self):
        from midscene.codebuddy_worker import normalize_response
        self.assertEqual(json.loads(normalize_response('Result: {"bbox":[1,2,3,4]}',{'type':'json_object'})),{'bbox':[1,2,3,4]})
    def test_multiple_objects_are_rejected(self):
        from midscene.codebuddy_worker import normalize_response
        with self.assertRaises(ValueError):normalize_response('{"x":1} {"x":2}',{'type':'json_object'})

class InsightProtocolTests(unittest.TestCase):
 def test_preserves_sdk_xml_even_with_json_transport(self):
  from midscene.codebuddy_worker import normalize_sdk_response
  text='<data-json>{"state":"equipment_list"}</data-json>'
  self.assertEqual(normalize_sdk_response(text,{'type':'json_object'},'Return <data-json>value</data-json>'),text)
 def test_wraps_valid_bare_json_only_for_sdk_xml(self):
  from midscene.codebuddy_worker import normalize_sdk_response
  self.assertEqual(normalize_sdk_response('{"state":"loading"}',None,'<data-json>'),'<data-json>{"state": "loading"}</data-json>')
 def test_invalid_or_duplicate_envelope_fails(self):
  from midscene.codebuddy_worker import normalize_sdk_response
  for t in ('not JSON','<data-json>{bad}</data-json>','<data-json>{}</data-json><data-json>{}</data-json>'):
   with self.assertRaises(ValueError):normalize_sdk_response(t,None,'<data-json>')

class ReadOnlyRetryTests(unittest.TestCase):
 def test_format_failure_retries_once_and_counts_calls(self):
  failure=subprocess.CompletedProcess([],1,'DEVICECHECK_RESULT={"error":"failed","category":"response_format","detail":"sdk_json_parse"}\n','')
  success=subprocess.CompletedProcess([],0,'DEVICECHECK_RESULT={"value":{"state":"loading"},"model_calls":1}\n','')
  with patch.object(midscene_bridge.shutil,'which',return_value='/mock/node'),patch.object(midscene_bridge.cancellation.Control,'run',side_effect=[failure,success]) as run:
   value=midscene_bridge.query(test_image(),'state',{})
  self.assertEqual(value['model_calls'],2)
  self.assertEqual(run.call_count,2)
 def test_repeated_format_failure_is_bounded(self):
  failure=subprocess.CompletedProcess([],1,'DEVICECHECK_RESULT={"error":"failed","category":"response_format","detail":"sdk_json_parse"}\n','')
  with patch.object(midscene_bridge.shutil,'which',return_value='/mock/node'),patch.object(midscene_bridge.cancellation.Control,'run',return_value=failure) as run:
   with self.assertRaises(ValueError):midscene_bridge.query(test_image(),'state',{})
  self.assertEqual(run.call_count,2)
