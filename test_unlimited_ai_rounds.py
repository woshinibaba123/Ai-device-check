import unittest
from unittest.mock import Mock, patch
import ai_operator

class UnlimitedRoundsTests(unittest.TestCase):
    def test_legacy_round_limit_is_ignored(self):
        config=ai_operator.validate({'goal':'查看页面','share_page':True,'max_actions':1})
        self.assertNotIn('max_actions',config)
        self.assertEqual(config['seconds'],600)
    def test_execution_retains_time_limit(self):
        e=Mock();e.secrets=[];e.stopped=lambda:False
        with patch('ai_operator.ai_fastpath.compile_goal',return_value=None):
            result=ai_operator.run(e,{'goal':'查看页面','share_page':True,'max_actions':1,'seconds':30,'fast_mode':False},clock=Mock(side_effect=[0,31]))
        self.assertEqual(result['termination'],'time_limit')
