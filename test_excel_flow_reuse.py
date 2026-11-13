import unittest
from excel_flow_reuse import reuse

class FlowReuseTests(unittest.TestCase):
    def test_input_variant_preserves_source(self):
        old={'steps':'进入报修，联系人填写“张三”','expected':'显示成功'}
        new={**old,'steps':'进入报修，联系人填写“李四”'}
        plan={'steps':[{'action':'tap','value':'报修'},{'action':'input','value':'联系人','text':'张三'},{'action':'assert','value':'成功'}]}
        self.assertEqual(reuse(old,new,plan)['steps'][1]['text'],'李四')
        self.assertEqual(plan['steps'][1]['text'],'张三')
    def test_changed_expectation_rejected(self):
        self.assertIsNone(reuse({'steps':'填写“张三”','expected':'成功'},{'steps':'填写“李四”','expected':'必填提示'},{'steps':[]}))
    def test_navigation_not_parameter(self):
        self.assertIsNone(reuse({'steps':'点击“报修”'},{'steps':'点击“删除”'},{'steps':[{'action':'tap','value':'报修'}]}))

class CrossModuleReuseTests(unittest.TestCase):
    def test_selection_in_each_module(self):
        for module in ('报修','附近门店','运行报告','学习中心','门店配置'):
            old={'module':module,'steps':'选择“选项甲”','expected':'显示“选项甲”'}
            new={**old,'steps':'选择“选项乙”','expected':'显示“选项乙”'}
            plan={'steps':[{'action':'tap','value':'选项甲'},{'action':'assert_selected','value':'选项甲'}]}
            result=reuse(old,new,plan)
            self.assertEqual(result['steps'][0]['value'],'选项乙')
            self.assertEqual(result['steps'][1]['value'],'选项乙')
    def test_different_module_not_reused(self):
        self.assertIsNone(reuse({'module':'报修','steps':'填写“甲”'},{'module':'门店','steps':'填写“乙”'},{'steps':[]}))
    def test_empty_input_preserved(self):
        result=reuse({'steps':'填写“甲”'},{'steps':'填写“”'},{'steps':[{'action':'input','value':'联系人','text':'甲'}]})
        self.assertEqual(result['steps'][0]['text'],'')
    def test_changed_check_intent_not_reused(self):
        self.assertIsNone(reuse({'steps':'勾选“协议”'},{'steps':'不勾选“协议”'},{'steps':[]}))
