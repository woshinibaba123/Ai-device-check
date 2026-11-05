import threading
import unittest
from unittest.mock import patch
import app

class BatchReleaseTests(unittest.TestCase):
    def test_finalization_exception_releases_batch(self):
        event=threading.Event();event.set()
        with patch.object(app,'BATCH_RUNNING',event), patch.object(app,'_run_batch'), patch.object(app,'finalize_batch',side_effect=RuntimeError('finalize failed')):
            with self.assertRaisesRegex(RuntimeError,'finalize failed'):app.run_batch([])
        self.assertFalse(event.is_set())

    def test_execution_failure_still_finalizes_and_releases(self):
        event=threading.Event();event.set()
        with patch.object(app,'BATCH_RUNNING',event), patch.object(app,'_run_batch',side_effect=RuntimeError('run failed')), patch.object(app,'finalize_batch') as finalize:
            with self.assertRaisesRegex(RuntimeError,'run failed'):app.run_batch([])
            finalize.assert_called_once_with([])
        self.assertFalse(event.is_set())
