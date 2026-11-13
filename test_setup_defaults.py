import json
import tempfile
import unittest
from pathlib import Path
import setup_defaults


class DefaultsTests(unittest.TestCase):
    def test_only_allowlisted_setup_values_never_password_or_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'.runtime/overnight-20261104/pilot-config.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'key':'secret-key','execution':{'source':folder,'entrypoint':'lib/main_eng.dart','token':'secret-token','login':{'enabled':True,'flow':'keenon_china','account':'test-user','password':'secret-password','success':{'value':'private'}}}}))
            result=setup_defaults.read(root)
            self.assertEqual(result['source'],folder)
            self.assertEqual(result['login'],{'enabled':True,'flow':'keenon_china','account':'test-user'})
            self.assertNotIn('secret',json.dumps(result))
    def test_missing_config_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:self.assertEqual(setup_defaults.read(folder),{})
    def test_stale_source_not_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'.runtime/overnight-20261104/pilot-config.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'execution':{'source':str(root/'missing'),'entrypoint':'lib/main.dart'}}))
            self.assertNotIn('source',setup_defaults.read(root))


if __name__=='__main__':unittest.main()
