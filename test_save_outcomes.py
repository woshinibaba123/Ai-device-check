import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import save_outcomes

class SaveOutcomeTests(unittest.TestCase):
    def test_failure_is_recorded_and_returned(self):
        e=SimpleNamespace(secrets=[],stopped=lambda:False,log=Mock())
        web=SimpleNamespace(e=e)
        @save_outcomes.nonblocking
        def save(web):raise RuntimeError('save failed')
        result=save(web)
        self.assertEqual(result['status'],'failed_or_unconfirmed')
        self.assertEqual(len(e.save_failures),1)
        self.assertFalse(result['retried'])
    def test_stop_is_not_swallowed(self):
        e=SimpleNamespace(stopped=lambda:True)
        @save_outcomes.nonblocking
        def save(web):raise RuntimeError('stopped')
        with self.assertRaises(RuntimeError):save(SimpleNamespace(e=e))
