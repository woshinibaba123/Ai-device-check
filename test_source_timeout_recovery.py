import unittest
from unittest.mock import Mock, patch
from automation import Explorer
from cancellation import Cancelled

class SourceTimeoutTests(unittest.TestCase):
    def explorer(self, call, platform='Android', stopped=lambda:False):
        return Explorer(call,'session',platform,Mock(),Mock(),stopped=stopped)

    def test_socket_timeout_recovers_without_actions(self):
        call=Mock(side_effect=[TimeoutError('timed out'),'<hierarchy/>'])
        with patch('automation.time.sleep'):
            self.assertEqual(self.explorer(call).source(),'<hierarchy/>')
        self.assertTrue(all(c.args==('GET','/session/session/source') for c in call.call_args_list))

    def test_proxy_timeout_is_bounded(self):
        call=Mock(side_effect=RuntimeError('timeout of 30000ms exceeded'))
        with patch('automation.time.sleep'),self.assertRaises(RuntimeError):
            self.explorer(call).source()
        self.assertEqual(call.call_count,3)

    def test_other_error_not_retried(self):
        call=Mock(side_effect=RuntimeError('invalid session id'))
        with self.assertRaises(RuntimeError):self.explorer(call).source()
        self.assertEqual(call.call_count,1)

