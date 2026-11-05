import json,unittest
from unittest.mock import patch
from types import SimpleNamespace
import login_credential_store as store

class LoginCredentialTests(unittest.TestCase):
    def test_secret_is_passed_only_through_stdin_and_unicode_roundtrips(self):
        account='测试@example.test';password=' 密码\n"$() '
        with patch.object(store.credential_store,'_run',return_value=SimpleNamespace(returncode=0)) as run,patch.object(store,'read',return_value=password):
            store.save(account,password)
        args,data=run.call_args.args
        self.assertNotIn(password,str(args));self.assertNotIn(account,data)
        self.assertIn(json.dumps({'account':account,'password':password},ensure_ascii=False).encode().hex(),data)
        self.assertNotIn('-A',data)

    def test_saved_password_is_bound_to_account(self):
        with patch.object(store.credential_store,'_run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'account':'other','password':'secret'}))):
            with self.assertRaises(ValueError):store.read('current')

    def test_only_explicit_reference_uses_keychain(self):
        with patch.object(store,'read',return_value='stored') as read:
            self.assertEqual(store.resolve({'enabled':True,'account':'test','password':'','use_saved_password':True})['password'],'stored')
            read.assert_called_once_with('test')
        with patch.object(store,'read') as read:
            self.assertEqual(store.resolve({'enabled':True,'account':'test','password':'new','use_saved_password':True})['password'],'new')
            read.assert_not_called()

    def test_missing_password_does_not_silently_continue(self):
        with patch.object(store,'read',return_value=''):
            with self.assertRaises(ValueError):store.resolve({'enabled':True,'account':'test','password':'','use_saved_password':True})

    def test_missing_entry_and_locked_keychain_are_distinguished(self):
        with patch.object(store.credential_store,'_run',return_value=SimpleNamespace(returncode=44)):
            self.assertFalse(store.saved('test'));self.assertEqual(store.read('test'),'');store.delete('test')
        with patch.object(store.credential_store,'_run',return_value=SimpleNamespace(returncode=36)):
            with self.assertRaises(ValueError):store.saved('test')


class CredentialHTTPTests(unittest.TestCase):
    def test_save_response_never_returns_password_and_foreign_origin_is_rejected(self):
        import app,threading,urllib.request,urllib.error
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/api/login/credentials'
            payload=json.dumps({'operation':'save','account':'test','password':'private-test-value'}).encode()
            with patch.object(store,'save') as save,patch.object(store,'saved',return_value=True):
                request=urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json'},method='POST')
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request) as response:
                    result=response.read().decode()
                self.assertEqual(json.loads(result),{'saved':True});self.assertNotIn('private-test-value',result)
                save.assert_called_once_with('test','private-test-value')
                request=urllib.request.Request(url,data=payload,headers={'Origin':'https://other.example'},method='POST')
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request)
                self.assertEqual(error.exception.code,403);self.assertEqual(save.call_count,1)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
