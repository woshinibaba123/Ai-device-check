import json,tempfile,unittest
from pathlib import Path
import stable_identifiers,automation,case_runner,source_navigation

class StableIdentityTests(unittest.TestCase):
 def test_route_inventory_unwraps_identity_components(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'lib').mkdir()
   (root/'lib/routers.dart').write_text("static const login='/login'; GetPage(name: login, page: () => const AutomationTarget(id:'flutter.login', component:true, child: UnifiedLoginPage()));")
   self.assertEqual(source_navigation.analyze(root)['routes'][0]['page'],'UnifiedLoginPage')
 def test_shared_control_scopes_resolve_without_choosing_first(self):
  sites={'lib/page.dart':[{'id':'flutter.login.account','component':True,'widget':'InputWidget'}],
         'lib/input.dart':[{'id':'flutter.input.field','widget':'TextField','component':False}]}
  target=stable_identifiers.flutter_targets('lib/page.dart',sites,{'InputWidget':'lib/input.dart'})[0]
  self.assertEqual(target['value'],'flutter.login.account/flutter.input.field')
  nodes=automation.parse_ui('<hierarchy><node class="android.widget.EditText" resource-id="flutter.page/flutter.login.account/flutter.input.field"/></hierarchy>')
  field=next(n for n in nodes if n['editable'])
  self.assertIs(case_runner.find_node(nodes,{'action':'input','by':'id','value':target['value']}),field)
  with self.assertRaises(case_runner.CaseBlocked):
   case_runner.find_node(nodes+[dict(field,id='flutter.other/'+target['value'])],{'action':'input','by':'id','value':target['value']})
 def test_ios_stable_identifier_is_not_display_label(self):
  nodes=automation.parse_ui('<root><node type="XCUIElementTypeTextField" name="flutter.login.account"/><node type="XCUIElementTypeButton" name="登录"/></root>')
  self.assertEqual(nodes[1]['id'],'flutter.login.account');self.assertEqual(nodes[2]['id'],'')
 def test_registry_rejects_paths_and_foreign_ids(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'automation-identifiers.json').write_text(json.dumps({'sites':[
    {'id':'h5.form.name','source':'src/page.vue'},
    {'id':'h5.invalid','source':'../secret'},
    {'id':'foreign.name','source':'src/page.vue'}]}))
   self.assertEqual(list(stable_identifiers.registry(d)),['src/page.vue'])
 def test_unscoped_native_ids_keep_exact_matching(self):
  nodes=automation.parse_ui('<root><node resource-id="scope/button"/></root>')
  self.assertIsNone(case_runner.find_node(nodes,{'action':'tap','by':'id','value':'button'}))

if __name__=='__main__':unittest.main()
