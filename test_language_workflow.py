import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import language_workflow as suite
import codebuddy_bridge,case_runner

def document():
    titles=['登录前配置：中国数据中心中文语言','使用账号密码方式登录成功','进入我的通用设置语言页面','切换其他语言如英文','依次切换其余语言','退出账号登录']
    return codebuddy_bridge.business_document({'cases':[{'title':t,'expected':'实际结果','business_steps':[{'action':t,'expected':'实际结果'}]} for t in titles]})

class AdapterTests(unittest.TestCase):
    def test_complete_suite_uses_dedicated_executor_and_preserves_business(self):
        doc=document();before=[c['business_steps'][0]['action'] for c in doc['cases']]
        result=suite.adapt(doc,{'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]})
        checked=codebuddy_bridge.validate_document(result)
        self.assertTrue(suite.applies(codebuddy_bridge.book(checked)))
        self.assertEqual(before,[c['business_steps'][0]['action'] for c in checked['cases']])
    def test_other_documents_and_incomplete_sources_are_not_automatically_bound(self):
        self.assertIsNone(suite.adapt(document(),{'pages':[]}))
        doc=document();doc['cases'].pop();self.assertFalse(suite.classify(doc))
    def test_login_placeholder_cannot_be_typed_as_literal_test_data(self):
        with self.assertRaisesRegex(ValueError,'占位符'):case_runner.validate_plan({'steps':[{'action':'input','value':'账号','text':'${test_account}'},{'action':'assert','value':'首页'}]})
    def test_unknown_workflow_phase_is_rejected(self):
        with self.assertRaises(ValueError):case_runner.validate_plan({'steps':[{'action':'workflow_case','value':'arbitrary'}]})

class RuntimeTests(unittest.TestCase):
    def test_system_navigation_window_does_not_count_as_ready_app(self):
        w=suite.Workflow.__new__(suite.Workflow);w.e=Mock();w.e.app_package='test.app';w.e.stopped.return_value=False;w.sleep=Mock()
        with patch.object(suite.automation,'parse_ui',side_effect=[[{'package':'com.android.systemui'}],[{'package':'test.app'}]]):
            self.assertEqual(w.nodes(),[{'package':'test.app'}])
        w.sleep.assert_called_once_with(.4)
    def test_route_waits_for_transition_instead_of_failing_on_first_frame(self):
        w=suite.Workflow.__new__(suite.Workflow);w.e=Mock();w.e.stopped.return_value=False
        w.e.route_reader.read.side_effect=['','/loading','/loginConfig'];w.sleep=Mock()
        w.route('/loginConfig')
        self.assertEqual(w.e.route_reader.read.call_count,3)
        self.assertEqual(w.sleep.call_count,2)
    def test_preceding_failure_blocks_login_and_logout(self):
        doc=suite.adapt(document(),{'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]});book=codebuddy_bridge.book(doc)
        e=Mock();e.stopped.return_value=False;e.secrets=[]
        runtime=Mock();runtime.events=[];runtime.shots=[];runtime.configure.side_effect=AssertionError('country mismatch')
        with patch.object(suite,'Workflow',return_value=runtime):
            result=suite.run(e,book,{},'/tmp',lambda _:None,lambda *a:None,lambda _:None)
        self.assertEqual(len(result),6);self.assertTrue(all(r['result']=='fail' for r in result))
        runtime.login.assert_not_called();runtime.logout.assert_not_called()
    def test_selection_requires_both_marker_and_persistent_locale(self):
        w=suite.Workflow.__new__(suite.Workflow);w.catalog={'English':{'lang':'en','country':'US','locale':'en_US'}}
        w.nodes=Mock(return_value=[{'label':'devicecheck-language-en-US','selected':False}]);w.prefs=Mock(return_value={'locale':'en_US'});w.assert_text=Mock();w.text=Mock(return_value='Language')
        with self.assertRaises(AssertionError):w.verify_selected('English')
        w.nodes.return_value[0]['selected']=True;w.verify_selected('English')
        w.prefs.return_value={'locale':'zh_CN'}
        with self.assertRaises(AssertionError):w.verify_selected('English')
    def test_only_runtime_available_languages_are_iterated(self):
        w=suite.Workflow.__new__(suite.Workflow)
        w.languages=[{'name':n} for n in ('中文简体','English','Deutsch','日本語')];w.catalog={x['name']:x for x in w.languages}
        w.nodes=Mock(return_value=[{'label':'中文简体'},{'label':'English'},{'label':'Deutsch'}]);w.route=Mock();w.top=Mock();w.scroll=Mock(return_value=False);w.change=Mock();w.roundtrip=Mock();w.record=Mock()
        w.all_languages();w.change.assert_called_once_with('Deutsch');w.roundtrip.assert_called_once_with('Deutsch')

class PrivacyTests(unittest.TestCase):
    def test_log_redacts_previous_accounts_not_in_current_credentials(self):
        import automation
        text=automation.redact('old@example.test +86 13800138000',[])
        self.assertNotIn('old@example.test',text);self.assertNotIn('13800138000',text)
    def test_selected_country_expectation_follows_actual_picker_behavior(self):
        doc=document();doc['cases'][0]['business_steps'][0]['expected']='中国被选中并高亮'
        result=suite.adapt(doc,{'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]})
        self.assertNotIn('高亮',result['cases'][0]['business_steps'][0]['expected'])
        self.assertIn('回显',result['cases'][0]['business_steps'][0]['expected'])

class PipelineTests(unittest.TestCase):
    def test_six_phase_binding_uses_source_adapter_without_model_or_literal_credentials(self):
        doc=document();doc['cases'][1]['plan']={'steps':[{'action':'input','value':'账号','text':'${test_account}'}]}
        index={'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]}
        with patch('flow_planner.source_index',return_value=index),patch('flow_planner.ai_summary',return_value={}),patch.object(codebuddy_bridge,'ask') as ask:
            result=codebuddy_bridge.generate({'outline':'登录与多语言验证','binding_only':True,'document':doc,'include_source':True,'source':'/test/source'})
        ask.assert_not_called();self.assertTrue(suite.applies(codebuddy_bridge.book(result)))

    def test_temporary_input_setting_is_restored_after_stage_failure(self):
        doc=suite.adapt(document(),{'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]});book=codebuddy_bridge.book(doc)
        e=Mock();e.device_id='emulator-5554';e.stopped.return_value=False;e.secrets=[];e.shell.return_value={'ok':True,'output':'null'}
        runtime=Mock();runtime.events=[];runtime.shots=[];runtime.configure.side_effect=RuntimeError('not ready')
        with patch.object(suite,'Workflow',return_value=runtime):suite.run(e,book,{},'/tmp',lambda _:None,lambda *a:None,lambda _:None)
        self.assertEqual(e.shell.call_args.args[0],['settings','delete','secure','stylus_handwriting_enabled'])

class JobDispatchTests(unittest.TestCase):
    def test_formal_job_dispatches_suite_before_generic_login_and_has_no_session_watchdog(self):
        import app
        doc=suite.adapt(document(),{'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]});book=codebuddy_bridge.book(doc)
        results=[{'id':c['id'],'sheet':c['sheet'],'row':c['row'],'title':c['title'],'result':'pass','status':'已执行','reason':'checked','screenshots':[],'steps':[]} for c in book['cases']]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);apk=root/'app.apk';apk.touch();job={'id':'suite-test','status':'running','logs':[],'screenshots':[]};caps=[]
            def request(method,path,data=None):
                if path=='/session':caps.append(data['capabilities']['alwaysMatch']);return {'sessionId':'fake','capabilities':{'appPackage':'com.test'}}
            with patch.object(app,'ROOT',root),patch.dict(app.JOBS,{'suite-test':job}),patch.object(app,'command',return_value={'ok':True,'output':''}),patch.object(app,'request',side_effect=request),patch.object(app,'raw_request'),patch.object(suite,'run',return_value=results) as run,patch.object(app.automation.Explorer,'login') as generic_login:
                app.run_job('suite-test',{'platform':'Android','device':'fake','app':str(apk),'bundle':'com.test','test_mode':'cases','case_book':book,'flow_index':{'project':tmp,'pages':[],'translations':{}},'login_probe':'devicecheck-login-'+'a'*32+'.json','login':{'enabled':True,'flow':'keenon_china','account':'test','password':'secret'}})
            self.assertEqual(job['status'],'passed');run.assert_called_once();generic_login.assert_not_called()
            self.assertEqual(caps[0]['appium:newCommandTimeout'],0)
            self.assertFalse(caps[0]['appium:appWaitForLaunch'])
            self.assertTrue(caps[0]['appium:hideKeyboard'])
            self.assertTrue(caps[0]['appium:settings']['enableMultiWindows'])

class RewordedPlanTests(unittest.TestCase):
    def merged(self):return json.loads((Path(__file__).parent/'testdata/language-regression-merged.json').read_text())
    def index(self):return {'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]}
    def test_exact_user_attachment_routes_all_languages_restore_and_global_check(self):
        doc=codebuddy_bridge.business_document(self.merged())
        self.assertEqual(suite.resolve_phases(doc),['configure','login','language_page','language_all_full_restore','language_persistence_zh','logout'])
        result=codebuddy_bridge.validate_document(suite.adapt(doc,self.index()))
        self.assertTrue(all(c['plan'] for c in result['cases']))
        self.assertTrue(suite.applies(codebuddy_bridge.book(result)))
        self.assertTrue(result['cases'][0]['adaptation_notes'])
        logout=result['cases'][-1]
        self.assertNotIn('账号管理',' '.join(s['action'] for s in logout['business_steps']))
        self.assertTrue(any('我的→退出账号' in n for n in logout['adaptation_notes']))
    def test_case_count_can_change_without_disabling_capabilities(self):
        doc=self.merged();doc['cases'].pop(4)
        self.assertEqual(len(suite.resolve_phases(doc)),5)
        english=document()['cases'][3]
        doc=self.merged();doc['cases'].insert(3,english)
        phases=suite.resolve_phases(doc)
        self.assertEqual(len(phases),7);self.assertEqual(phases[3],'language_switch');self.assertEqual(phases[4],'language_all_restore')
    def test_local_source_verification_does_not_require_cloud_source_checkbox(self):
        with patch('flow_planner.source_index',return_value=self.index()),patch.object(codebuddy_bridge,'ask') as ask:
            result=codebuddy_bridge.generate({'binding_only':True,'document':self.merged(),'outline':'中国配置登录及语言回归','source':'/local/source','include_source':False})
        ask.assert_not_called();self.assertTrue(suite.applies(codebuddy_bridge.book(result)))
    def test_different_country_is_not_silently_replaced_with_china(self):
        doc=json.loads(json.dumps(self.merged(),ensure_ascii=False).replace('中国','美国'))
        self.assertIsNone(suite.adapt(codebuddy_bridge.business_document(doc),self.index()))
    def test_merged_loop_includes_first_non_chinese_and_restores_chinese(self):
        w=suite.Workflow.__new__(suite.Workflow);w.languages=[{'name':n} for n in ('中文简体','English','Deutsch')];w.catalog={v['name']:v for v in w.languages}
        w.nodes=Mock(return_value=[{'label':n} for n in w.catalog]);w.route=Mock();w.top=Mock();w.scroll=Mock(return_value=False);w.change=Mock();w.roundtrip=Mock();w.record=Mock();w.prefs=Mock(return_value={'locale':'zh_CN'})
        w.all_languages(include_english=True,restore_chinese=True)
        self.assertEqual([c.args[0] for c in w.change.call_args_list],['English','Deutsch','中文简体'])
        self.assertEqual([c.args[0] for c in w.roundtrip.call_args_list],['English','Deutsch','中文简体'])
    def test_global_chinese_verification_fails_if_not_restored(self):
        w=suite.Workflow.__new__(suite.Workflow);w.prefs=Mock(return_value={'locale':'en_US'});w.roundtrip=Mock()
        with self.assertRaises(AssertionError):w.persistence(chinese=True)
        w.roundtrip.assert_not_called()

class RestoreWordingTests(unittest.TestCase):
    def test_restore_wording_does_not_disable_the_restore_capability(self):
        fixture=Path(__file__).parent/'testdata/language-regression-merged.json'
        for action in ['选择回中文','切换回中文','改回中文','恢复为中文']:
            doc=json.loads(fixture.read_text());doc['cases'][3]['business_steps'][-1]['action']=action
            self.assertEqual(suite.resolve_phases(doc)[3],'language_all_full_restore')

class ActualBatchPlanTests(unittest.TestCase):
    def test_actual_five_case_batch_restores_chinese_without_extra_call_navigation(self):
        doc=json.loads((Path(__file__).parent/'testdata/language-regression-five.json').read_text())
        self.assertEqual(suite.resolve_phases(doc),['configure','login','language_page','language_all_full_restore','logout_relogin'])
        result=suite.adapt(codebuddy_bridge.business_document(doc),{'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]})
        self.assertNotIn('呼叫',result['cases'][1]['expected'])
        self.assertTrue(suite.applies(codebuddy_bridge.book(result)))

class ExistingPlanCompatibilityTests(unittest.TestCase):
    def test_existing_bound_plan_gets_missing_restore_and_relogin(self):
        doc=json.loads((Path(__file__).parent/'testdata/language-regression-five.json').read_text())
        book=codebuddy_bridge.book(doc)
        self.assertEqual(suite.phases_for_book(book),['configure','login','language_page','language_all_full_restore','logout_relogin'])
        exported=json.loads(book['content'])
        self.assertTrue(exported['cases'][3]['adaptation_notes'])
        self.assertTrue(exported['cases'][-1]['adaptation_notes'])
    def test_observing_login_page_does_not_add_relogin(self):
        doc=json.loads((Path(__file__).parent/'testdata/language-regression-merged.json').read_text())
        self.assertEqual(suite.resolve_phases(doc)[-1],'logout')

class ReloginCoverageTests(unittest.TestCase):
    def test_explicit_relogin_step_is_executed_and_final_logged_out_state_is_restored(self):
        doc=json.loads((Path(__file__).parent/'testdata/language-regression-five.json').read_text())
        book=codebuddy_bridge.book(doc);e=Mock();e.stopped.return_value=False;e.secrets=[]
        runtime=Mock();runtime.events=[];runtime.shots=[]
        with patch.object(suite,'Workflow',return_value=runtime):result=suite.run(e,book,{},'/tmp',lambda _:None,lambda *a:None,lambda _:None)
        self.assertTrue(all(r['result']=='pass' for r in result))
        self.assertEqual(runtime.login.call_count,2);self.assertEqual(runtime.logout.call_count,2)
    def test_explicit_final_logged_in_state_does_not_add_logout_cleanup(self):
        self.assertFalse(suite.relogin_cleanup({'expected':'退出后重新登录，最终保持已登录'}))
        self.assertTrue(suite.relogin_cleanup({'expected':'退出后账号处于未登录状态'}))

class MergedOutlineTests(unittest.TestCase):
    def four_case(self):
        titles=['登录前配置：国家数据中心选中国语言选中文并进入登录页','账号密码登录：输入账号和密码后登录成功进入主页',
                '语言切换：在通用设置-语言中依次切换其他语言并验证生效','恢复中文并退出账号，返回登录页']
        return codebuddy_bridge.business_document({'cases':[{'title':t,'expected':'实际结果','business_steps':[{'action':t,'expected':'实际结果'}]} for t in titles]})
    def index(self):return {'pages':[{'path':v} for v in ('/loginConfig','/login','/language')]}
    def test_merged_four_case_outline_uses_dedicated_executor(self):
        doc=self.four_case()
        self.assertEqual(suite.resolve_phases(doc),['configure','login','language_all_full','language_restore_logout'])
        result=codebuddy_bridge.validate_document(suite.adapt(doc,self.index()))
        self.assertTrue(all(c['plan'] for c in result['cases']))
        self.assertTrue(suite.applies(codebuddy_bridge.book(result)))
        self.assertTrue(any('恢复中文' in n for n in result['cases'][3]['adaptation_notes']))
    def test_language_restore_logout_navigates_restores_then_logs_out(self):
        doc=suite.adapt(self.four_case(),self.index());book=codebuddy_bridge.book(doc)
        e=Mock();e.stopped.return_value=False;e.secrets=[]
        runtime=Mock();runtime.events=[];runtime.shots=[]
        with patch.object(suite,'Workflow',return_value=runtime):
            result=suite.run(e,book,{},'/tmp',lambda _:None,lambda *a:None,lambda _:None)
        self.assertTrue(all(r['result']=='pass' for r in result))
        self.assertEqual([m[0] for m in runtime.method_calls[-3:]],['ensure_language_page','change','logout'])
        runtime.change.assert_called_once_with('中文简体')
    def test_pure_logout_case_keeps_logout_phase(self):
        doc=json.loads((Path(__file__).parent/'testdata/language-regression-merged.json').read_text())
        self.assertEqual(suite.resolve_phases(codebuddy_bridge.business_document(doc))[-1],'logout')

class PersistenceRestoreTests(unittest.TestCase):
    def book_with(self,cases):
        return {'cases':[{'id':'AI:'+str(i),'sheet':'AI','row':i,'title':t,
                          'plan_text':json.dumps({'requires':[],'steps':[{'action':'workflow_case','value':p}]})}
                         for i,(t,p) in enumerate(cases,1)]}
    def test_persistence_case_with_restore_wording_switches_back_to_chinese(self):
        book=self.book_with([('配置','configure'),('登录','login'),('切换语言后切回中文','language_persistence_zh'),('退出账号','logout')])
        self.assertEqual(suite.phases_for_book(book),['configure','login','language_persistence_zh','logout'])
        e=Mock();e.stopped.return_value=False;e.secrets=[]
        runtime=Mock();runtime.events=[];runtime.shots=[]
        with patch.object(suite,'Workflow',return_value=runtime):
            result=suite.run(e,book,{},'/tmp',lambda _:None,lambda *a:None,lambda _:None)
        self.assertTrue(all(r['result']=='pass' for r in result))
        runtime.persistence.assert_called_once_with(chinese=True,restore=True)
    def test_persistence_restores_chinese_when_requested(self):
        w=suite.Workflow.__new__(suite.Workflow)
        w.languages=[{'name':'中文简体','locale':'zh_CN'}]
        w.prefs=Mock(side_effect=[{'locale':'pt_PT'},{'locale':'zh_CN'}])
        w.change=Mock();w.roundtrip=Mock();w.record=Mock()
        w.persistence(chinese=True,restore=True)
        w.change.assert_called_once_with('中文简体');w.record.assert_called_once()
    def test_persistence_restore_still_fails_if_chinese_not_persisted(self):
        w=suite.Workflow.__new__(suite.Workflow)
        w.prefs=Mock(return_value={'locale':'pt_PT'});w.change=Mock();w.roundtrip=Mock();w.record=Mock()
        with self.assertRaises(AssertionError):w.persistence(chinese=True,restore=True)
        w.change.assert_called_once_with('中文简体');w.roundtrip.assert_called_once()

if __name__=='__main__':unittest.main()
