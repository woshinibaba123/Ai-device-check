import unittest
from unittest.mock import Mock,patch
import runtime_health

class RuntimeOwnershipTests(unittest.TestCase):
    def test_external_appium_process_is_never_stopped(self):
        with patch('runtime_health.subprocess.run',side_effect=[Mock(stdout='123\n'),Mock(stdout='node /another/project/appium')]),patch('runtime_health.os.kill') as kill:
            with self.assertRaisesRegex(RuntimeError,'未重启外部服务'):
                runtime_health.restart('/owned/deviceCheck',lambda x:None)
            kill.assert_not_called()
