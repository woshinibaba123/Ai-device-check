import tempfile
import unittest
from pathlib import Path
import runtime_metrics
from run_events import Recorder

class RuntimeMetricsTests(unittest.TestCase):
    def test_success_and_failure_recorded_without_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            job={}
            recorder=Recorder(Path(directory),job)
            token=runtime_metrics.recorder.set(recorder)
            try:
                @runtime_metrics.timed('ai_decision')
                def decision(fail):
                    if fail:raise ValueError('private')
                    return 'private'
                self.assertEqual(decision(False),'private')
                with self.assertRaises(ValueError):decision(True)
            finally:runtime_metrics.recorder.reset(token)
            self.assertEqual(job['command_timings']['ai_decision']['count'],2)
            self.assertEqual(job['command_timings']['ai_decision']['failures'],1)
            self.assertNotIn('private',(Path(directory)/'events.jsonl').read_text())
