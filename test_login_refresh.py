import unittest,itertools
from unittest.mock import Mock,patch
import login_flow
from automation import LoginBlocked
EMPTY='<hierarchy/>'
PASS='<hierarchy><node class="android.widget.EditText"/><node class="android.widget.EditText" password="true"/></hierarchy>'
VERIFY='<hierarchy><node class="android.widget.EditText"/><node class="android.widget.EditText"/><node class="android.widget.Button" text="账号密码登录"/></hierarchy>'
class LoginRefreshTests(unittest.TestCase):
 def explorer(self):
  e=Mock();e.stopped.return_value=False;e.base='/session/s';return e
 def test_empty_frame_then_password_does_not_trigger_rewrite(self):
  e=self.explorer();e.source.side_effect=[EMPTY,EMPTY,PASS]
  with patch('login_flow.time.sleep'):nodes=login_flow.wait_login_snapshot(e)
  self.assertIsNotNone(login_flow.password_field(nodes));e.type.assert_not_called()
 def test_actual_verify_mode_is_recognized(self):
  e=self.explorer();e.source.return_value=VERIFY
  self.assertIsNone(login_flow.password_field(login_flow.wait_login_snapshot(e)))
 def test_persistent_empty_frame_blocks_without_input(self):
  e=self.explorer();e.source.return_value=EMPTY;ticks=itertools.count()
  with patch('login_flow.time.sleep'),patch('login_flow.time.monotonic',side_effect=lambda:next(ticks)):
   with self.assertRaisesRegex(LoginBlocked,'未将其判为验证码模式'):login_flow.wait_login_snapshot(e,2)
  e.type.assert_not_called()
 def test_account_locator_waits_for_refreshed_tree(self):
  e=self.explorer();e.source.side_effect=[EMPTY,'<hierarchy><node class="android.widget.EditText"/></hierarchy>','<hierarchy><node class="android.widget.EditText"/></hierarchy>'];e.find.return_value='account';e.call.return_value='synthetic-account'
  with patch('login_flow.time.sleep'):login_flow.fill_account(e,'synthetic-account')
  e.type.assert_called_once()
class TargetedAccountRetryTests(unittest.TestCase):
 def test_failed_ime_input_retries_field_then_requires_readback(self):
  import itertools
  e=Mock();e.stopped.return_value=False;e.base='/session/s';e.find.return_value='field';state={'value':''}
  def call(method,path,data=None):
   if method=='POST' and path.endswith('/value'):state['value']=data['text']
   return state['value']
  e.call.side_effect=call;ticks=itertools.count()
  with patch('login_flow.time.sleep'),patch('login_flow.time.monotonic',side_effect=lambda:next(ticks)):
   login_flow.fill_account(e,'synthetic-account',{'by':'id','value':'account'})
  e.type.assert_called_once();self.assertEqual(state['value'],'synthetic-account')
  self.assertNotIn('synthetic-account',str(e.log.call_args_list))
if __name__=='__main__':unittest.main()
