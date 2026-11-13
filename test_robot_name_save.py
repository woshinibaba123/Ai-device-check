import unittest
from unittest.mock import Mock, patch
import ai_operator


class RobotNameSaveTests(unittest.TestCase):
    def web(self, results):
        web = Mock()
        web.e.stopped.return_value = False
        web.js.side_effect = results
        return web

    def test_checks_input_clicks_once_and_verifies(self):
        web = self.web([True, {'ELEMENT': 'save'}, True, False, True])
        with patch('ai_operator.time.sleep'):
            ai_operator.save_robot_name.__wrapped__(web, '请输入机器人名称', '测试机器人')
        web.perform.assert_called_once_with({'action': 'web_assert_input', 'value': '请输入机器人名称', 'text': '测试机器人'})
        self.assertEqual(web.js.call_count, 5)

    def test_wrong_input_never_clicks(self):
        web = self.web([])
        web.perform.side_effect = AssertionError('输入不一致')
        with self.assertRaises(AssertionError):
            ai_operator.save_robot_name.__wrapped__(web, '请输入机器人名称', '测试机器人')
        web.js.assert_not_called()

    def test_uncertain_click_stops_without_retry(self):
        web = self.web([True, {'ELEMENT': 'save'}, False])
        with self.assertRaisesRegex(RuntimeError, '停止后续操作'):
            ai_operator.save_robot_name.__wrapped__(web, '请输入机器人名称', '测试机器人')
        self.assertEqual(web.js.call_count, 3)

    def test_missing_verification_stops(self):
        web = self.web([True, {'ELEMENT': 'save'}, True])
        with patch('ai_operator.time.monotonic', side_effect=[0, 11]):
            with self.assertRaisesRegex(RuntimeError, '未重复提交'):
                ai_operator.save_robot_name.__wrapped__(web, '请输入机器人名称', '测试机器人')


class FlowSavePermissionTests(unittest.TestCase):
    def test_save_buttons_allowed_for_authorized_flow(self):
        from types import SimpleNamespace
        e = SimpleNamespace(flow_save_authorized=True)
        for label in ('保存', '确认', '确定', 'Save', 'Confirm', 'OK'):
            self.assertFalse(ai_operator.blocked(label, e), label)

    def test_other_actions_and_unrequested_saves_remain_restricted(self):
        from types import SimpleNamespace
        self.assertTrue(ai_operator.blocked('保存', SimpleNamespace(flow_save_authorized=False)))
        for label in ('删除', '支付', '重置密码', '确认提交订单'):
            self.assertTrue(ai_operator.blocked(label, SimpleNamespace(flow_save_authorized=True)), label)
