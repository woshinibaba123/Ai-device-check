import unittest,json
from pathlib import Path
from unittest.mock import Mock,patch
import automation,source_navigation,popup_handler
from automation import Explorer,parse_ui,page_ready
class ReportRegressionTests(unittest.TestCase):
 def test_actual_notification_and_scan_are_displayed_not_loading(self):
  for name in ['notification','scan']:
   p=Path('test_fixtures/exploration')/(name+'.xml')
   self.assertTrue(page_ready(parse_ui(p.read_text())))
 def test_translated_menu_does_not_repeat_completed_branch(self):
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.state='root';e.lang='Settings'
  def source():
   label=e.lang if e.state=='root' else 'Detail'
   return '<hierarchy><node class="android.widget.Button" package="test.app" text="'+label+'" clickable="true"/></hierarchy>'
  e.source=source;e.settled_source=source
  e.tap=Mock(side_effect=lambda n:setattr(e,'state','detail'))
  def back(n):e.state='root';e.lang='Configuración'
  e.back=back;e.route_reader=Mock();e.route_reader.read.side_effect=lambda:'/main' if e.state=='root' else '/detail'
  # Detail is a visible leaf rather than a second navigation action.
  original=source
  def source2():
   return original() if e.state=='root' else '<hierarchy><node class="android.view.View" package="test.app" text="Detail"/><node class="android.view.View" package="test.app" text="Body"/></hierarchy>'
  e.source=source2;e.settled_source=source2
  with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0})
  self.assertEqual(e.tap.call_count,1);self.assertEqual(r['termination'],'reachable_controls_exhausted')
 def test_changed_root_with_different_tabs_is_not_back_failure(self):
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.state='root';e.changed=False
  def source():
   if e.state=='web':return '<hierarchy><node class="android.webkit.WebView" package="test.app" text="H5"/><node class="android.widget.Button" package="test.app" text="vconsole" clickable="true"/></hierarchy>'
   extra='' if e.changed else '<node class="android.view.View" package="test.app" text="Home&#10;Tab 1 of 4"/><node class="android.view.View" package="test.app" text="Mine&#10;Tab 4 of 4"/>'
   return '<hierarchy>'+extra+'<node class="android.widget.Button" package="test.app" text="Repair" clickable="true"/><node class="android.widget.Button" package="test.app" text="Other" clickable="true"/></hierarchy>'
  e.source=source;e.settled_source=source;e.taps=[]
  def tap(n):
   e.taps.append(n['label'])
   if n['label']=='Repair':e.state='web'
  def back(n):e.state='root';e.changed=True
  e.tap=tap;e.back=back;e.route_reader=Mock();e.route_reader.read.side_effect=lambda:'/webview' if e.state=='web' else '/main/agent'
  with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0})
  self.assertIn('Other',e.taps);self.assertNotEqual(r['termination'],'back_failed')
  self.assertTrue(any(x.get('matched_root_route') for x in r['transitions']))
 def test_actual_restart_splash_is_not_a_ready_page(self):
  nodes=parse_ui(Path('test_fixtures/exploration/startup.xml').read_text())
  self.assertFalse(page_ready(nodes))
 def test_root_route_waits_for_native_tree_after_splash(self):
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None)
  splash=Path('test_fixtures/exploration/startup.xml').read_text()
  root='<hierarchy><node class="android.widget.Button" package="test.app" text="Other" clickable="true"/></hierarchy>'
  e.source=Mock(side_effect=[splash,splash,root]);e.route_reader=Mock();e.route_reader.read.return_value='/main/agent'
  with patch('automation.time.sleep'):result=e.wait_root_snapshot('/main/agent','test.app')
  self.assertEqual(result,root);self.assertEqual(e.source.call_count,3)
 def test_all_language_options_share_one_depth_budget(self):
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.state='root';e.lang=-1;e.taps=[]
  def source():
   if e.state=='root':return '<hierarchy><node class="android.widget.Button" package="test.app" text="Languages" clickable="true"/></hierarchy>'
   return '<hierarchy><node class="android.view.View" package="test.app" text="Language state '+str(e.lang)+'"/>'+''.join('<node class="android.widget.Button" package="test.app" text="L%d" clickable="true" selected="%s"/>'%(i,str(i==e.lang).lower()) for i in range(11))+'</hierarchy>'
  def tap(n):
   e.taps.append(n['label'])
   if n['label']=='Languages':e.state='language'
   else:e.lang=int(n['label'][1:])
  e.source=source;e.settled_source=source;e.tap=tap;e.back=lambda n:setattr(e,'state','root')
  e.route_reader=Mock();e.route_reader.read.side_effect=lambda:'/main' if e.state=='root' else '/language'
  with patch('automation.time.sleep'):r=e.explore({'max_depth':1,'max_scrolls':0,'max_actions':100})
  self.assertEqual([x for x in e.taps if x!='Languages'],['L'+str(i) for i in range(11)])
  self.assertEqual(r['termination'],'reachable_controls_exhausted')
 def test_spanish_logout_is_excluded_by_semantic_key(self):
  xml='<hierarchy><node class="android.widget.Button" package="test.app" text="Cerrar sesión" clickable="true"/></hierarchy>'
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.source=lambda:xml;e.settled_source=e.source;e.tap=Mock()
  with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0,'source_plan':{'label_keys':{'cerrar sesión':'mine_exit_account'}}})
  e.tap.assert_not_called();self.assertEqual(r['skipped'][0]['semantic'],'mine_exit_account')
 def test_form_cancel_loop_recovers_once_and_continues_other_entry(self):
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.state='root';e.form_data_active=True;e.taps=[]
  root='<hierarchy><node class="android.widget.Button" package="test.app" text="Repair" clickable="true"/><node class="android.widget.Button" package="test.app" text="Other" clickable="true"/></hierarchy>'
  web='<hierarchy><node class="android.webkit.WebView" package="test.app" text="Form"/><node class="android.widget.Button" package="test.app" text="vconsole" clickable="true"/></hierarchy>'
  dialog='<hierarchy><node class="android.widget.Button" package="test.app" text="Cancel" clickable="true"/></hierarchy>'
  e.source=lambda:root if e.state=='root' else dialog if e.state=='dialog' else web;e.settled_source=lambda **kwargs:e.source()
  def tap(n):
   e.taps.append(n['label'])
   if n['label']=='Repair':e.state='web'
  e.tap=tap;e.back=lambda n:setattr(e,'state','dialog')
  def call(method,path,data=None):
   if path.endswith('/activate_app'):e.state='root'
  e.call=Mock(side_effect=call);e.route_reader=Mock();e.route_reader.read.side_effect=lambda:'/main' if e.state=='root' else '/webview'
  with patch('automation.time.sleep'),patch('auto_forms.visit',side_effect=lambda *args:(e.state=='web',None)):
   r=e.explore({'max_scrolls':0,'max_actions':25})
  self.assertNotIn('Cancel',e.taps);self.assertIn('Other',e.taps)
  self.assertEqual(sum(c.args[1].endswith('/activate_app') for c in e.call.call_args_list),1)
  self.assertTrue(any(x['type']=='form_abandoned' for x in r['observations']))
 def test_unfinished_branch_can_be_revisited_after_language_change(self):
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.state='root';e.locale='Settings';e.taps=[]
  def source():
   labels=[e.locale] if e.state=='root' else ['Jump','Remaining']
   return '<hierarchy>'+''.join('<node class="android.widget.Button" package="test.app" text="'+x+'" clickable="true"/>' for x in labels)+'</hierarchy>'
  def tap(n):
   e.taps.append(n['label'])
   if n['label'] in ('Settings','Configuración'):e.state='detail'
   elif n['label']=='Jump':e.state='root';e.locale='Configuración'
  e.source=source;e.settled_source=source;e.tap=tap;e.back=lambda n:setattr(e,'state','root')
  e.route_reader=Mock();e.route_reader.read.side_effect=lambda:'/main' if e.state=='root' else '/detail'
  with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0,'max_actions':30,'source_plan':{'label_keys':{'settings':'settings','configuración':'settings'}}})
  self.assertIn('Remaining',e.taps);self.assertIn('Configuración',e.taps)
  self.assertEqual(r['termination'],'reachable_controls_exhausted')
 def test_h5_ambiguous_plus_does_not_open_system_picker(self):
  xml='<hierarchy><node class="android.webkit.WebView" package="test.app" text="Chat"/><node class="android.widget.Button" package="test.app" text="+" clickable="true"/></hierarchy>'
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.source=lambda:xml;e.settled_source=e.source;e.tap=Mock();e.route_reader=Mock();e.route_reader.read.return_value='/webview'
  with patch('automation.time.sleep'),patch('auto_forms.visit',return_value=(False,None)):r=e.explore({'max_scrolls':0})
  e.tap.assert_not_called();self.assertIn('加号',r['skipped'][0]['reason'])
 def test_relaunch_splash_waits_instead_of_backing_to_launcher(self):
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.state='root';e.taps=[];e.waits=[]
  root='<hierarchy><node class="android.widget.Button" package="test.app" text="Open" clickable="true"/><node class="android.widget.Button" package="test.app" text="Other" clickable="true"/></hierarchy>'
  splash='<hierarchy><node class="android.view.View" package="test.app" text="Keenon"/><node class="android.view.View" package="test.app" text="Copyright ©"/></hierarchy>'
  e.source=lambda:root if e.state=='root' else splash
  def settled(**kwargs):
   e.waits.append(kwargs.get('timeout'))
   if kwargs.get('timeout')==60:e.state='root'
   return e.source()
  def tap(n):
   e.taps.append(n['label'])
   if n['label']=='Open':e.state='splash'
  e.settled_source=settled;e.tap=tap;e.back=Mock(side_effect=AssertionError('must not back out of splash'))
  e.route_reader=Mock();e.route_reader.read.return_value='/main'
  with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0,'max_actions':10})
  self.assertIn(60,e.waits);self.assertIn('Other',e.taps);e.back.assert_not_called()
  self.assertEqual(r['termination'],'reachable_controls_exhausted')
 def test_empty_loading_surface_is_not_ready(self):
  self.assertFalse(page_ready(parse_ui('<hierarchy><node class="android.view.View"/></hierarchy>')))
 def test_local_action_does_not_retry_or_claim_navigation_failure(self):
  for label in ['Search','Refresh','Read All','Unread']:
   xml='<hierarchy><node class="android.widget.Button" package="test.app" text="'+label+'" clickable="true"/></hierarchy>'
   e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.source=lambda:xml;e.settled_source=lambda:xml;e.tap=Mock()
   with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0})
   self.assertEqual(e.tap.call_count,1);self.assertFalse(any(i.get('type')=='entry_unreachable' for i in r['issues']))
 def test_three_successful_password_returns_do_not_exhaust_global_limit(self):
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.app_package='test.app';e.state='root';e.backs=0
  root='<hierarchy>'+''.join('<node class="android.widget.Button" package="test.app" text="Entry%d" clickable="true"/>'%i for i in range(3))+'</hierarchy>'
  secure='<hierarchy><node class="android.widget.EditText" package="test.app" password="true"/></hierarchy>'
  e.source=lambda:root if e.state=='root' else secure;e.settled_source=e.source
  e.tap=lambda n:setattr(e,'state','secure')
  def back(n):e.backs+=1;e.state='root'
  e.back=back;e.route_reader=Mock();e.route_reader.read.side_effect=lambda:'/main' if e.state=='root' else '/user/modifyPass'
  with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0})
  self.assertEqual(e.backs,3);self.assertEqual(r['termination'],'reachable_controls_exhausted')
 def test_observed_route_is_not_reported_as_unvisited_or_passed(self):
  reader=Mock();reader.observed={'/login','/my/notify'}
  plan={'routes':[{'path':p} for p in ['/login','/my/notify','/robot','/splash','/main']]}
  c=source_navigation.coverage(plan,{'/main'},reader,[],'stopped')
  statuses={r['path']:r['status'] for r in c['route_details']}
  self.assertEqual(statuses,{'/login':'observed','/my/notify':'observed','/robot':'not_observed','/splash':'startup_unobserved','/main':'displayed'})
 def test_cancel_account_is_skipped_in_source_defined_translation(self):
  xml='<hierarchy><node class="android.widget.Button" package="test.app" text="Cancelar cuenta" clickable="true"/></hierarchy>'
  e=Explorer(Mock(),'s','Android',lambda x:None,lambda *x:None);e.source=lambda:xml;e.settled_source=e.source;e.tap=Mock()
  with patch('automation.time.sleep'):r=e.explore({'max_scrolls':0,'source_plan':{'label_keys':{'cancelar cuenta':'logoff'}}})
  e.tap.assert_not_called();self.assertTrue(r['skipped'])
 def test_unsaved_discard_requires_context_not_generic_confirm(self):
  nodes=parse_ui('<hierarchy><node text="Unsaved changes"/><node class="android.widget.Button" text="Discard" clickable="true"/></hierarchy>')
  self.assertEqual(popup_handler.discard_target(nodes)['label'],'Discard')
  self.assertIsNone(popup_handler.discard_target(parse_ui('<hierarchy><node class="android.widget.Button" text="Confirm" clickable="true"/></hierarchy>')))
if __name__=='__main__':unittest.main()

class CompletionStatusTests(unittest.TestCase):
 def test_incomplete_exploration_is_blocked_instead_of_review(self):
  for end in ['page_tree_unavailable','outside_app','back_failed','unreachable_pending_branches','startup_not_ready']:
   self.assertEqual(automation.exploration_status({'termination':end,'issues':[{'error':'incomplete'}]}),'blocked')
 def test_data_followup_and_completed_scope_are_distinct(self):
  self.assertEqual(automation.exploration_status({'termination':'reachable_controls_exhausted','forms':[{'automatic':True}]}),'review')
  self.assertEqual(automation.exploration_status({'termination':'reachable_controls_exhausted'}),'passed')
