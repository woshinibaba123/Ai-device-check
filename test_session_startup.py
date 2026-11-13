import unittest
from unittest.mock import Mock
import session_startup as startup


class StartupTests(unittest.TestCase):
    def setUp(self):
        startup._ready.clear()
        self.caps = {'platformName': 'Android', 'appium:udid': 'device'}
        self.command = Mock(return_value={'ok': True, 'output': 'boot-one'})
        self.request = Mock(return_value={'sessionId': 'session'})

    def create(self):
        return startup.create(self.caps, self.request, self.command, 'adb', Mock())

    def warm(self):
        return self.request.call_args.args[2]['capabilities']['alwaysMatch'].get('appium:skipDeviceInitialization', False)

    def test_warm_then_reboot(self):
        self.create()
        self.assertFalse(self.warm())
        self.create()
        self.assertTrue(self.warm())
        self.command.return_value['output'] = 'boot-two'
        self.create()
        self.assertFalse(self.warm())
        self.assertNotIn('appium:skipDeviceInitialization', self.caps)

    def test_failure_invalidates_without_retry(self):
        self.create()
        self.request.side_effect = RuntimeError('timeout')
        with self.assertRaises(RuntimeError):
            self.create()
        self.assertEqual(self.request.call_count, 2)
        self.request.side_effect = None
        self.create()
        self.assertFalse(self.warm())

    def test_failed_probe_uses_full_initialization(self):
        self.create()
        self.command.return_value = {'ok': False, 'output': 'error'}
        self.create()
        self.assertFalse(self.warm())
