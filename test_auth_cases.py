import json,unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
import case_runner as runner,codebuddy_bridge as bridge,auth_case_setup
from test_automation import FakeDriver
from automation import Explorer

class AuthCasesTests(unittest.TestCase):
    def test_generation_prompt_has_one_auth_policy(self):
        doc={'cases':[{'title':'登录页校验','expected':'仍在登录页','business_steps':[{'action':'输入密码','expected':'仍在登录页'}]}]}
        reply={'bindings':[{'case_id':1,'start_state':'login','steps':[{'business_step':1,'operations':[{'action':'input_local','by':'field','value':'password','text':'password'},{'action':'assert_route','value':'/login'}]}]}]}
        with patch.object(bridge,'ask',return_value=reply) as ask:
            bridge.generate({'outline':'匹配登录测试','binding_only':True,'strict_excel':True,'document':doc})
        prompt=ask.call_args.args[0]
        self.assertNotIn('自动登录另行配置，不生成密码输入',prompt)
        self.assertNotIn('通用操作不直接处理密码',prompt)
        self.assertIn('每条binding必须声明start_state',prompt)
        self.assertIn('input_local',prompt)
        self.assertIn('打开“国家或区域/数据中心/语言”选择器不是已选择值',prompt)

    def test_incomplete_config_is_partial_and_starts_before_login(self):
        import excel_ai
        doc=bridge.business_document({'cases':[{'title':'中国数据中心账号密码登录成功','expected':'登录成功',
            'business_steps':[{'action':'首次启动，国家选择中国、数据中心选择中国、语言选择当前目标语言。','expected':'配置正确'}]}]})
        ops=[{'action':'assert_route','value':'/loginConfig'}]+[{'action':'tap','value':v} for v in ['国家或区域','数据中心','语言','下一步']]
        row=bridge.apply_bindings(doc,{'bindings':[{'case_id':1,'steps':[{'business_step':1,'operations':ops}]}]})['cases'][0]
        self.assertIsNone(row['plan'])
        self.assertEqual(row['business_steps'][0]['automation_status'],'partial')
        self.assertIn('缺少目标选项',row['blocked_reason'])
        self.assertIn('缺少选中值',row['blocked_reason'])
        self.assertEqual(excel_ai.partial_candidate(row)['start_state'],'login_config')

    def test_open_login_page_does_not_complete_login(self):
        step={'action':'启动App，完成中国数据中心与登录。'}
        issues=bridge.binding_coverage_issues(step,[{'action':'assert_route','value':'/login'}])
        self.assertTrue(any('缺少登录提交' in reason for reason in issues))
        self.assertEqual(bridge.infer_start_state({'title':'切换为中文简体','business_steps':[step]}),'login_config')

    def test_leading_auth_assertion_corrects_home_start(self):
        state=bridge.binding_start_state({'title':'配置核验'}, {'start_state':'home','steps':[{'business_step':1,'operations':[{'action':'assert_route','value':'/loginConfig'}]}]})
        self.assertEqual(state,'login_config')

    def test_credentials_require_auth_state_and_valid_slot(self):
        step={'action':'input_local','value':'密码','text':'password'}
        with self.assertRaises(ValueError):runner.validate_plan({'steps':[step]})
        for state in ('login','login_config'):
            self.assertEqual(runner.validate_plan({'start_state':state,'steps':[step,{'action':'assert_route','value':'/login'}]})['start_state'],state)
        with self.assertRaises(ValueError):runner.validate_plan({'start_state':'login','steps':[dict(step,text='token')]})
    def test_auth_input_clear_and_consent_without_exporting_page_or_secret(self):
        exp=Explorer(FakeDriver(),'s','Android',lambda x:None,lambda *x:None);exp.app_package='com.example'
        exp.route_reader=SimpleNamespace(read=lambda:'/login');exp.test_credentials={'password':'local-secret'}
        exp.prepare_test_case=Mock();capture=Mock(side_effect=AssertionError('不应导出登录页面'))
        xml='<hierarchy><node class="android.widget.EditText" package="com.example" text="密码" password="true"/><node package="com.example" text="同意并登录" clickable="true"/></hierarchy>'
        plan={'start_state':'login','steps':[{'action':'input_local','value':'密码','text':'password'},{'action':'clear','value':'密码'},{'action':'tap','value':'同意并登录'},{'action':'assert_route','value':'/login'}]}
        case={'id':'S:1','sheet':'S','row':1,'title':'密码测试','group':'App','priority':'P1','precondition':'','mobile':True,'steps':'明确操作','expected':'明确断言','plan_text':json.dumps(plan)}
        with patch.object(exp,'settled_source',return_value=xml),patch.object(exp,'find',return_value='field'),patch.object(exp,'type') as type_text,patch.object(exp,'call') as call,patch.object(exp,'tap') as tap:
            result=runner.run(exp,{'cases':[case]}, {},lambda x:None,capture,lambda x:None,lambda:False,lambda x:None)[0]
        self.assertEqual(result['result'],'pass',result)
        type_text.assert_called_once();self.assertEqual(type_text.call_args.args[1],'local-secret')
        self.assertTrue(any('/clear' in c.args[1] for c in call.call_args_list));tap.assert_called_once()
        capture.assert_not_called();self.assertNotIn('local-secret',json.dumps(result));self.assertEqual(result['screenshots'],[])
        exp.prepare_test_case.assert_called_once_with('login')
    def test_auth_mapping_retains_start_state(self):
        d=bridge.business_document({'cases':[{'title':'登录校验','expected':'登录页','business_steps':[{'action':'输入密码','expected':'仍为登录页'}]}]})
        r=bridge.apply_bindings(d,{'bindings':[{'case_id':1,'start_state':'login','steps':[{'business_step':1,'operations':[{'action':'input_local','value':'密码','text':'password'},{'action':'assert_route','value':'/login'}]}]}]})
        self.assertEqual(r['cases'][0]['plan']['start_state'],'login')
    def test_prepare_login_does_not_submit_and_home_authenticates_once(self):
        exp=SimpleNamespace(login=Mock(return_value={'status':'confirmed'}),switch_language=Mock());reset=Mock()
        auth_case_setup.install(exp,{'account':'a','password':'p'},reset,lambda x:None,lambda x:None)
        with patch('login_flow.prepare') as prepare,patch('login_flow.wait_post_login'),patch('login_flow.dismiss_onboarding'):
            exp.prepare_test_case('login');reset.assert_called_once();prepare.assert_called_once();exp.login.assert_not_called()
            exp.prepare_test_case('home');exp.prepare_test_case('home');exp.login.assert_called_once()

class RuntimeFieldTests(unittest.TestCase):
    def test_ambiguous_fields_are_blocked_and_password_role_requires_secure(self):
        import automation
        nodes=automation.parse_ui('<hierarchy><node class="android.widget.EditText" text="账号"/><node class="android.widget.EditText" text="验证码"/></hierarchy>')
        with self.assertRaises(runner.CaseBlocked):runner.find_node(nodes,{'action':'clear','by':'field','value':'search'})
        with self.assertRaises(runner.CaseBlocked):runner.find_node(nodes,{'action':'input_local','by':'field','value':'password'})
        with self.assertRaises(ValueError):runner.validate_plan({'steps':[{'action':'clear','by':'field','value':'account'},{'action':'assert','value':'账号'}]})
    def test_unique_search_field_can_clear_without_static_xpath(self):
        import automation
        nodes=automation.parse_ui('<hierarchy><node class="android.widget.EditText" text="Search"/></hierarchy>')
        self.assertEqual(runner.find_node(nodes,{'action':'clear','by':'field','value':'search'})['label'],'Search')

class TapMatchingTests(unittest.TestCase):
    def test_tap_matches_merged_row_labels_and_clickable_ancestors(self):
        import automation
        # 合并行标签：parse_ui 把无标签可点击容器的子文字合并为 'A · B'，tap 需按分段匹配。
        merged=automation.parse_ui('<hierarchy><node class="android.widget.LinearLayout" clickable="true"><node class="android.widget.TextView" text="国家或区域"/><node class="android.widget.TextView" text="请选择"/></node></hierarchy>')
        self.assertIsNotNone(runner.find_node(merged,{'action':'tap','value':'国家或区域'}))
        self.assertIsNotNone(runner.find_node(merged,{'action':'tap','value':'请选择'}))
        # 容器已有自身标签时子文字不合并；tap 应回退到最近的可点击祖先。
        split=automation.parse_ui('<hierarchy><node class="android.widget.LinearLayout" clickable="true" content-desc="row_card"><node class="android.widget.TextView" text="国家或区域"/><node class="android.widget.TextView" text="请选择"/></node></hierarchy>')
        self.assertIsNotNone(runner.find_node(split,{'action':'tap','value':'国家或区域'}))
        # 多个候选祖先仍未唯一时必须受阻，不得猜测点击。
        ambiguous=automation.parse_ui('<hierarchy><node class="android.widget.LinearLayout" clickable="true" content-desc="a"><node class="android.widget.TextView" text="请选择"/></node><node class="android.widget.LinearLayout" clickable="true" content-desc="b"><node class="android.widget.TextView" text="请选择"/></node></hierarchy>')
        with self.assertRaises(runner.CaseBlocked):runner.find_node(ambiguous,{'action':'tap','value':'请选择'})
        # 断言匹配不受可点击限制影响。
        self.assertEqual(runner.find_node(split,{'action':'assert','value':'请选择'})['label'],'请选择')
