import unittest
from unittest.mock import Mock, patch
import manual_steps


class ManualStepsTests(unittest.TestCase):
    def test_web_wait_retries_only_read_assertions(self):
        e=Mock();e.stopped.return_value=False
        with patch('manual_steps.hybrid_webview.WebView') as ctx:
            web=ctx.return_value.__enter__.return_value
            web.perform.side_effect=[AssertionError('not ready'),{'matched':True}]
            sleep=Mock()
            result=manual_steps.perform(e,{'action':'web_wait_for','by':'css','value':'#repair'},sleep)
            self.assertEqual(result['action'],'web_wait_for')
            self.assertTrue(all(c.args[0]['action']=='web_assert' for c in web.perform.call_args_list))
            sleep.assert_called_once_with(.5)

    def test_web_wait_does_not_retry_session_errors(self):
        e=Mock();e.stopped.return_value=False
        with patch('manual_steps.hybrid_webview.WebView') as ctx:
            web=ctx.return_value.__enter__.return_value
            web.perform.side_effect=RuntimeError('session lost')
            with self.assertRaisesRegex(RuntimeError,'session lost'):
                manual_steps.perform(e,{'action':'web_wait_for','value':'Title'},Mock())
            self.assertEqual(web.perform.call_count,1)

    def test_app_back_uses_page_navigation_instead_of_raw_system_back(self):
        e=Mock();e.source.return_value='<hierarchy />'
        manual_steps.perform(e,{'action':'app_back'},Mock())
        e.back.assert_called_once()
        e.call.assert_not_called()

    def test_web_save_binding_is_validated_before_opening_webview(self):
        e=Mock()
        with patch('manual_steps.hybrid_webview.WebView') as web:
            with self.assertRaises(ValueError):
                manual_steps.perform(e, {'action':'web_save','value':'提交'}, Mock())
            web.assert_not_called()

    def test_h5_action_restores_context_via_context_manager(self):
        step={'action':'web_assert','value':'报修'}
        with patch('manual_steps.hybrid_webview.WebView') as web:
            manual_steps.perform(Mock(), step, Mock())
            web.return_value.__enter__.return_value.perform.assert_called_once_with(step)
            web.return_value.__exit__.assert_called_once()

    def test_wait_uses_read_only_lookup_and_does_not_click(self):
        e=Mock();e.base='/session/test';e.stopped.return_value=False
        e.call.side_effect=[[],[{'ELEMENT':'target'}]];sleep=Mock()
        result=manual_steps.perform(e,{'action':'wait_for','value':'首页'},sleep)
        self.assertTrue(result['matched']);sleep.assert_called_once_with(.5)
        self.assertTrue(all(c.args[1].endswith('/elements') for c in e.call.call_args_list))

    def test_broken_session_is_not_hidden_by_wait(self):
        e=Mock();e.base='/session/test';e.stopped.return_value=False
        e.call.side_effect=RuntimeError('session lost')
        with self.assertRaisesRegex(RuntimeError,'session lost'):
            manual_steps.perform(e,{'action':'wait_for','value':'首页'},Mock())

if __name__=='__main__':unittest.main()
