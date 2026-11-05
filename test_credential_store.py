import unittest
from unittest.mock import patch
from types import SimpleNamespace
import credential_store as store

class CredentialStoreTests(unittest.TestCase):
    def test_secret_goes_via_stdin_not_process_arguments(self):
        secret='test-secret-\"-$()'
        with patch.object(store,'_run',return_value=SimpleNamespace(returncode=0)) as run,patch.object(store,'read',return_value=secret):
            store.save(secret)
            args,data=run.call_args.args
            self.assertEqual(args,['-i'])
            self.assertNotIn(secret,str(args))
            self.assertIn(secret.encode().hex(),data)
            self.assertNotIn('-A',data)
    def test_missing_and_locked_keychain_are_distinguished(self):
        with patch.object(store,'_run',return_value=SimpleNamespace(returncode=44)):
            self.assertFalse(store.exists());self.assertEqual(store.read(),'');store.delete()
        with patch.object(store,'_run',return_value=SimpleNamespace(returncode=36)):
            for operation in (store.exists,store.read,store.delete):
                with self.assertRaises(ValueError):operation()
    def test_interactive_command_failure_is_detected_by_readback(self):
        with patch.object(store,'_run',return_value=SimpleNamespace(returncode=0)),patch.object(store,'read',return_value=''):
            with self.assertRaisesRegex(ValueError,'未保存成功'):store.save('test-key')

if __name__=='__main__':unittest.main()
