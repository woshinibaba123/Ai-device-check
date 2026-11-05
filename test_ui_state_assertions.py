import unittest,json
from unittest.mock import patch
import automation,case_runner as runner,codebuddy_bridge as bridge
from test_automation import FakeDriver

class StateAssertionTests(unittest.TestCase):
    def execute(self,step):
        exp=automation.Explorer(FakeDriver(),'s','Android',lambda x:None,lambda *x:None);exp.app_package='com.example'
        xml='<hierarchy><node text="Home" package="com.example" clickable="true"/><node text="Next" package="com.example" enabled="false"/><node text="请选择"/><node text="请选择"/><node text="请选择"/></hierarchy>'
        case={'id':'S:1','sheet':'S','row':1,'title':'状态断言','group':'App','priority':'P1','precondition':'','mobile':True,'steps':'断言','expected':'精确状态','plan_text':json.dumps({'steps':[step]})}
        with patch.object(exp,'settled_source',return_value=xml),patch.object(exp,'tap'):
            return runner.run(exp,{'cases':[case]}, {},lambda x:None,lambda *a:'/reports/proof.png',lambda x:None,lambda:False,lambda x:None)[0]
    def test_disabled_button_is_observed_but_not_an_action_candidate(self):
        xml='<hierarchy><node text="Next" enabled="false" clickable="true"/></hierarchy>'
        self.assertFalse(automation.parse_ui(xml)[0]['label']=='Next')
        self.assertTrue(any(n['label']=='Next' and not n['enabled'] for n in automation.parse_ui(xml,include_disabled=True)))
        self.assertEqual(self.execute({'action':'assert_enabled','value':'Next','enabled':False})['result'],'pass')
        self.assertEqual(self.execute({'action':'assert_enabled','value':'Next','enabled':True})['result'],'fail')
    def test_count_and_zero_count_assertions(self):
        for value,count in [('请选择',3),('不存在',0)]:self.assertEqual(self.execute({'action':'assert_count','value':value,'count':count})['result'],'pass')
        self.assertEqual(self.execute({'action':'assert_count','value':'请选择','count':2})['result'],'fail')
    def test_partial_operations_survive_without_complete_case_becoming_ready(self):
        d=bridge.business_document({'cases':[{'title':'登录配置','expected':'完整配置','business_steps':[{'action':'检查配置及第二个数据中心','expected':'均可用'}]}]})
        r=bridge.apply_bindings(d,{'bindings':[{'case_id':1,'steps':[{'business_step':1,'operations':[{'action':'assert','value':'数据中心'}],'blocked_reason':'环境缺少第二个数据中心'}]}]})['cases'][0]
        self.assertIsNone(r['plan']);self.assertEqual(r['business_steps'][0]['automation_status'],'partial');self.assertTrue(r['business_steps'][0]['automation_steps'])
