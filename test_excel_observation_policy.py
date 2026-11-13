import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import automation
import case_runner
import codebuddy_bridge as bridge
import excel_ai
import hybrid_webview
from excel_execution_policy import POLICY,search_operations


class ObservationPolicyTests(unittest.TestCase):
    def test_search_prefers_explicit_text_and_fills_missing_text(self):
        ops=[{'action':'web_input','by':'css','value':'input','text':'wrong'}]
        self.assertEqual(search_operations({'action':'搜索框输入 洲际 点击搜索'},ops)[0]['text'],'洲际')
        self.assertEqual(ops[0]['text'],'wrong')
        missing=[{'action':'web_input','by':'css','value':'input'}]
        a=search_operations({'action':'搜索门店'},missing)[0]['text']
        b=search_operations({'action':'搜索门店'},missing)[0]['text']
        self.assertTrue(a.startswith('qa_search_'));self.assertNotEqual(a,b)
        self.assertEqual(search_operations({'action':'清空搜索框后查看列表'},ops)[0]['text'],'')

    def test_native_duplicates_choose_first_only_when_requested(self):
        nodes=automation.parse_ui('<hierarchy><node text="门店" clickable="true"/><node text="门店" clickable="true"/></hierarchy>')
        step={'action':'tap','value':'门店'}
        with self.assertRaises(case_runner.CaseBlocked):case_runner.find_node(nodes,step)
        self.assertEqual(case_runner.find_node(nodes,step,first_match=True)['path'],next(n['path'] for n in nodes if n['label']=='门店'))

    def test_web_duplicate_tap_and_absent_assertion_are_recorded(self):
        e=Mock();e.base='/session/test';e.excel_observation_mode=True
        web=hybrid_webview.WebView(e);web.collect_diagnostics=Mock()
        web.js=Mock(return_value={'count':2,'element':{automation.ELEMENT:'first'},'label':'门店','secure':False})
        web.perform({'action':'web_tap','by':'css','value':'.card'})
        self.assertTrue(web.js.call_args.args[1][-1])
        self.assertEqual(e.call.call_args.args[1],'/session/test/element/first/click')
        web.js.return_value={'count':0}
        evidence=web.perform({'action':'web_assert','by':'css','value':'.missing'})
        self.assertFalse(evidence['present'])
        e.excel_observation_mode=False
        with self.assertRaises(hybrid_webview.DOMTargetMissing):web.perform({'action':'web_assert','by':'css','value':'.missing'})

    def test_current_account_binding_does_not_require_original_account(self):
        from test_codebuddy_bridge import business_sample,bindings_sample
        document=business_sample();document['cases'][0]['precondition']='账号 app_direct01 已登录'
        result=bridge.apply_bindings(bridge.business_document(document),bindings_sample(),observation_mode=True)
        self.assertEqual(result['cases'][0]['plan']['execution_policy'],POLICY)

    def test_absent_button_records_result_then_runs_next_case(self):
        from test_case_workbook import fixture
        import case_workbook
        source='<hierarchy><node class="android.widget.Button" package="com.example" text="首页" clickable="true" selected="true"/><node class="android.widget.Button" package="com.example" text="门店" clickable="true"/><node class="android.widget.Button" package="com.example" text="门店" clickable="true"/></hierarchy>'
        e=automation.Explorer(lambda *args:None,'s','Android',lambda _:None,lambda *args:None)
        e.app_package='com.example';e.settled_source=lambda:source;e.tap=Mock()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cases.xlsx';fixture(p);book=case_workbook.read(p)
            plans={
                '手机全量:6':{'execution_policy':POLICY,'steps':[{'action':'assert','value':'不存在的入口'},{'action':'tap','value':'不存在的入口'}]},
                '手机全量:7':{'execution_policy':POLICY,'steps':[{'action':'tap','value':'门店'},{'action':'assert','value':'门店'}]}}
            results=case_runner.run(e,book,{'priority':'P1','plans':plans},lambda _:None,lambda *args:'/proof.png',lambda _:None,lambda:False,lambda _:None)
        self.assertEqual([r['result'] for r in results],['review','review'])
        self.assertFalse(results[0]['steps'][0]['present'])
        self.assertEqual(results[1]['steps'][-1]['match_count'],2)
        self.assertFalse(hasattr(e,'excel_observation_mode'))
        self.assertTrue(any(c.args[0]['label']=='门店' for c in e.tap.call_args_list))


if __name__=='__main__':unittest.main()
