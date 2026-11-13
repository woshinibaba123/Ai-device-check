import unittest
import excel_domain_flows as flows
class DomainFlowsTests(unittest.TestCase):
    def test_clean(self):
        text=flows.context([{'title':'清洁机器人排班'}]);self.assertIn('区域缺失',text);self.assertIn('重新读取验证',text)
    def test_call(self):
        text=flows.context([{'title':'呼叫下发任务并取消'}]);self.assertIn('本次返回任务ID',text);self.assertIn('不能降级',text)
    def test_unrelated(self):self.assertEqual(flows.context([{'title':'学习中心'}]),'')
