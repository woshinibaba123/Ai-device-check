import unittest
import app
class CompactTreeTests(unittest.TestCase):
    def test_opt_in_only(self):
        self.assertEqual(app.compact_tree_settings(False),{})
        self.assertEqual(app.compact_tree_settings(True),{'ignoreUnimportantViews':True,'snapshotMaxDepth':50,'waitForIdleTimeout':0,'waitForSelectorTimeout':0,'enableTopmostWindowFromActivePackage':True})
    def test_rejects_non_boolean(self):
        for value in ['false',None,1]:
            with self.assertRaises(ValueError):app.compact_tree_settings(value)

class NativeAdbCaptureTests(unittest.TestCase):
    def test_uses_device_scoped_read_only_capture(self):
        from unittest.mock import Mock
        runner=Mock(return_value=Mock(stdout=b'\x89PNG\r\n\x1a\nexample'))
        self.assertTrue(app.capture_android_png('/adb','phone',runner).startswith(b'\x89PNG'))
        runner.assert_called_once_with(['/adb','-s','phone','exec-out','screencap','-p'])
    def test_rejects_error_output(self):
        from unittest.mock import Mock
        with self.assertRaises(RuntimeError):app.capture_android_png('/adb','phone',Mock(return_value=Mock(stdout=b'permission denied')))
