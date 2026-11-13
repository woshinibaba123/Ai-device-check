import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('full_suite',Path(__file__).parent/'scripts/run_all_presets.py')
suite=importlib.util.module_from_spec(spec);spec.loader.exec_module(suite)

class SuiteQueueTests(unittest.TestCase):
    def test_first_launch_refreshes_planned_data_but_retry_keeps_it(self):
        flow={'id':'sample','name':'测试','parameters':[],'steps':['填写并提交']}
        with tempfile.TemporaryDirectory() as tmp,patch.object(suite,'OUT',Path(tmp)):
            planned=suite.payload(flow)
            with patch.object(suite.time,'strftime',return_value='NEW_LAUNCH_TIME'):
                launched=suite.payload(flow,fresh=True)
            self.assertNotEqual(planned['ai_live']['data']['test_time'],launched['ai_live']['data']['test_time'])
            self.assertEqual(suite.payload(flow)['ai_live']['data'],launched['ai_live']['data'])

    def test_long_workflow_only_times_out_when_progress_stops(self):
        item={'launched':0}
        self.assertFalse(suite.stalled(item,{'ai_operator':{'steps':[{}]}},2000))
        self.assertFalse(suite.stalled(item,{'ai_operator':{'steps':[{},{}]}},3400))
        self.assertFalse(suite.stalled(item,{'ai_operator':{'steps':[{},{}]}},4800))
        self.assertTrue(suite.stalled(item,{'ai_operator':{'steps':[{},{}]}},5000))

    def test_extended_clean_flow_allows_its_saved_forms(self):
        with patch.object(suite,'api',return_value=[{'id':'clean-robot','readonly':True,'steps':[]} ]):
            flow=suite.flows()[0]
        self.assertFalse(flow['readonly'])
        self.assertIn('排班',flow['steps'][0])

    def test_generated_data_is_stable_on_resume(self):
        flow={'id':'sample','name':'测试','parameters':[{'key':'occurred_at','default':''}],'steps':['填写 {{occurred_at}} 后保存']}
        with tempfile.TemporaryDirectory() as tmp,patch.object(suite,'OUT',Path(tmp)),patch('ai_operator.goal_input_data',side_effect=lambda goal,data:dict(data,schedule_name='本次唯一名称')):
            first=suite.payload(flow)
            with patch.object(suite.time,'strftime',return_value='DIFFERENT_TIME'):
                second=suite.payload(flow)
            self.assertEqual(first['ai_live']['data'],second['ai_live']['data'])
            self.assertEqual(first['ai_live']['goal'],second['ai_live']['goal'])
            self.assertEqual(second['ai_live']['midscene_model'],'glm-5.3-flash')
    def test_multiline_goal_does_not_duplicate_step_numbers(self):
        import workflow_coverage
        flow={'id':'multiline','name':'测试','parameters':[],'steps':['前置：已登录\n1. 检查首页\n2. 返回首页']}
        with tempfile.TemporaryDirectory() as tmp,patch.object(suite,'OUT',Path(tmp)):
            rows=workflow_coverage.requirements(suite.payload(flow)['ai_live']['goal'])
        self.assertEqual([r['id'] for r in rows],['step_1','step_2'])
