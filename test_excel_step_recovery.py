import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import automation
import case_runner
import codebuddy_bridge as bridge
import excel_execution_policy as policy
from test_case_workbook import fixture
import case_workbook


class StepRecoveryTests(unittest.TestCase):
    def test_scroll_times_is_supported_and_still_range_checked(self):
        plan={'steps':[{'action':'scroll','times':2},{'action':'assert','value':'标题'}]}
        self.assertEqual(bridge.checked_plan(plan)['steps'][0]['times'],2)
        for n in (0,6,'2',True):
            with self.assertRaises(ValueError):bridge.checked_plan({'steps':[{'action':'scroll','times':n}]},False)

    def test_conditional_no_list_can_be_recorded_without_operations(self):
        doc=bridge.business_document({'cases':[{'title':'登录配置页','precondition':'已打开配置页','expected':'记录页面结果',
            'business_steps':[{'action':'点击记录进入详情（页面有列表时），再点击返回','expected':'有列表时查看详情'}]}]})
        response={'bindings':[{'case_id':1,'start_state':'login_config','steps':[{'business_step':1,'operations':[],
            'blocked_reason':'本页无列表记录控件，详情条件分支不适用'}]}]}
        row=bridge.apply_bindings(copy.deepcopy(doc),response,observation_mode=True)['cases'][0]
        self.assertIsNotNone(row['plan']);self.assertEqual(row['business_steps'][0]['automation_status'],'candidate')
        self.assertEqual(row['plan']['steps'][0]['action'],'record')
        self.assertIsNone(bridge.apply_bindings(copy.deepcopy(doc),response)['cases'][0]['plan'])

    def test_missing_real_list_evidence_is_not_turned_into_skip(self):
        ops,reason=policy.observation_operations({'action':'有记录时进入详情'},[],'缺少列表定位证据')
        self.assertEqual(ops,[]);self.assertIn('缺少',reason)

    def test_multiple_inputs_keep_values_and_have_feedback_between_them(self):
        ops=[{'action':'input','value':'请输入国家或地区','text':v} for v in ('abc','   ','QATest01')]
        normalized,_=policy.observation_operations({'action':'输入abc、空格和QATest01'},ops)
        self.assertEqual([s['text'] for s in normalized if s['action']=='input'],['abc','   ','QATest01'])
        self.assertEqual([s['action'] for s in normalized],['input','assert_input','record']*3)
        self.assertEqual(ops[0]['text'],'abc')
        web,_=policy.observation_operations({'action':'输入搜索词'},[{'action':'web_input','by':'css','value':'input','text':'a'}])
        self.assertEqual([s['action'] for s in web],['web_input','web_assert_input','web_observe'])
        self.assertEqual(bridge.checked_plan({'execution_policy':policy.POLICY,'steps':web})['steps'],web)

    def test_multi_sample_search_does_not_overwrite_all_values_with_one_literal(self):
        ops=[{'action':'web_input','by':'css','value':'input','text':v} for v in ('abc','   ','QATest01')]
        self.assertEqual([s['text'] for s in policy.search_operations({'action':'搜索框依次输入abc、空格和QATest01'},ops)],['abc','   ','QATest01'])

    def test_duplicate_backs_are_not_replayed_even_across_business_steps(self):
        ops,_=policy.observation_operations({'action':'返回'},[{'action':'back'}]*3)
        self.assertEqual([s['action'] for s in ops],['back','record','record'])
        later,_=policy.observation_operations({'action':'再返回'},[{'action':'back'}],history=ops)
        self.assertEqual(later[0]['action'],'record')

    def test_observation_action_cannot_claim_strict_pass(self):
        with self.assertRaises(ValueError):bridge.checked_plan({'steps':[{'action':'record','value':'无列表'}]})
        with self.assertRaises(ValueError):bridge.checked_plan({'steps':[{'action':'web_observe','value':'提示'}]})

    def test_runtime_does_not_back_out_of_login_config(self):
        source='<hierarchy><node class="android.widget.Button" package="com.example" text="首页" clickable="true" selected="true"/></hierarchy>'
        e=automation.Explorer(lambda *args:None,'s','Android',lambda _:None,lambda *args:None)
        e.app_package='com.example';e.settled_source=lambda:source;e.tap=Mock();e.back=Mock()
        e.route_reader=Mock();e.route_reader.read.return_value='/loginConfig'
        plan={'execution_policy':policy.POLICY,'steps':[{'action':'back'},{'action':'record','value':'记录根页状态'}]}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cases.xlsx';fixture(p);book=case_workbook.read(p)
            results=case_runner.run(e,book,{'case_ids':['手机全量:6'],'plans':{'手机全量:6':plan}},lambda _:None,lambda *args:'/proof.png',lambda _:None,lambda:False,lambda _:None)
        e.back.assert_not_called();self.assertEqual(results[0]['result'],'review')
        self.assertFalse(results[0]['steps'][0]['executed'])


if __name__=='__main__':unittest.main()
