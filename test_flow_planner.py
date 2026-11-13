import tempfile
import unittest
from pathlib import Path
import json
import flow_planner
import http_probe
import case_runner
from automation import Explorer
from unittest.mock import patch
from xml.sax.saxutils import escape

class SourceFlowTests(unittest.TestCase):
    def test_relative_controller_api_and_custom_input_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            files={'pubspec.yaml':'name: example',
                   'lib/routes/routers.dart':"static const login='/login'; GetPage(name: login, page: () => LoginPage())",
                   'lib/http/request_api.dart':"static const save='/api/test/save';",
                   'lib/http/repository/account_repository.dart':"class AccountRepository {\n  save() { DioUtil.post(RequestApi.save); }\n}",
                   'lib/login/controller.dart':"import '../http/repository/account_repository.dart'; void submit() { AccountRepository().save(); }",
                   'lib/login/page.dart':"import 'controller.dart'; class LoginPage { void build() { InputTxtWidget(title:'account'.tr, hint:'account_hint'.tr); InputTxtWidget(title:'password'.tr, isPass:true); _buildInputField(label:'other'.tr); } Widget _buildInputField({String label}) { return TextField(); } }"}
            for file,text in files.items():
                path=root/file;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            page=flow_planner.source_index(root)['pages'][0]
            self.assertEqual([api['path'] for api in page['api_candidates']],['/api/test/save'])
            custom=[field for field in page['inputs'] if field['widget']=='InputTxtWidget']
            self.assertEqual(len(custom),2);self.assertTrue(custom[1]['secure'])
            helpers=[field for field in page['inputs'] if field['widget']=='_buildInputField']
            self.assertEqual(len(helpers),1)

    def test_callback_navigation_does_not_borrow_previous_sibling_label(self):
        import source_navigation
        text="""class Page {
  Widget build() { return Column(children: [
    ItemTxtWidget(text:'business'.tr, onTap: () { Get.toNamed(Routers.business); }),
    ItemTxtWidget(text:'queue'.tr, onTap: () { _openQueue(); }),
  ]); }
  void _openQueue() async { Get.toNamed(Routers.queue); }
  void _unlabeled() { Get.toNamed(Routers.unknown); }
}"""
        self.assertEqual(source_navigation.navigation_label_keys(text,text.index('Get.toNamed(Routers.queue)')),['queue'])
        self.assertEqual(source_navigation.navigation_label_keys(text,text.index('Get.toNamed(Routers.unknown)')),[])

    def test_source_methods_inputs_and_save_on_return_are_evidence_bearing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            files={'pubspec.yaml':'name: app_phone',
              'assets/i18n/zh.json':json.dumps({'title':'通用设置','save':'保存','hint':'请输入名称'}),
              'assets/i18n/en.json':json.dumps({'title':'General Settings','save':'Save','hint':'Enter name'}),
              'lib/routes/routers.dart':"class Routers { static const myCurrency = '/my/currency'; static final pages=[GetPage(name: myCurrency, page: () => const SettingsPage())]; }",
              'lib/http/request_api.dart':"class RequestApi { static const String update = '/api/test/store/settings'; static const String list = '/api/test/store/list'; }",
              'lib/http/http_exception.dart':'class HttpCodeHelper { static const int success = 123; }',
              'lib/http/dio_util.dart':'if (resultModel.code == 0) {}',
              'lib/http/repository/store_repository.dart':"class StoreRepository {\n  saveName(String value) {\n    checkToken();\n    DioUtil.post(RequestApi.update);\n  }\n  list() { DioUtil.get(RequestApi.list); }\n}",
              'lib/settings.dart':"import 'package:app_phone/http/repository/store_repository.dart'; class SettingsPage { var bar=Scaffold(appBar: StyledWidgets.backTransAppBar(title:'title'.tr,onPressed: () => saveName())); void build() { TextField(hintText: 'hint'.tr); var save='save'.tr; onPressed: () => saveName(); canPop: false; store.saveName('test'); /* store.list(); */ } }"}
            for file,text in files.items():
                target=p/file;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
            index=flow_planner.source_index(p)
            self.assertEqual(index['business_success_codes'],[123,0])
            page=index['pages'][0]
            self.assertTrue(page['return']['may_save']);self.assertTrue(page['return']['intercepted'])
            self.assertEqual([c['method'] for c in page['api_candidates']],['saveName'])
            self.assertTrue(page['inputs']);self.assertEqual(page['entry_path'],['我的','通用设置'])
            case={'id':'S:2','sheet':'S','row':2,'mobile':True,'title':'通用设置保存','module':'我的','group':'我的|通用设置','steps':'【1】输入“test”\n【2】点击保存','expected':'保存成功','precondition':'已登录'}
            draft=flow_planner.draft(case,index)
            self.assertEqual(draft['status'],'draft_not_execution_proof')
            self.assertEqual(draft['actions'][1]['type'],'save_and_assert_api')
            self.assertTrue(draft['api_candidates']);self.assertIn('test',draft['input_values_from_case'])
            form_case={**case,'precondition':'在通用设置页面','steps':'【1】在“名称”输入“qa-001”\n【2】点击保存','expected':'【1】输入成功\n【2】保存成功'}
            form=flow_planner.compile_form(form_case,index)
            self.assertEqual([s['action'] for s in form['steps']],['tap','tap','assert_route','input','assert_input','save'])
            self.assertEqual(form['steps'][-1]['api']['path'],'/api/test/store/settings')
            self.assertIsNotNone(case_runner.compile_case(form_case,index=index)[0])
            page['api_candidates'].append({**page['api_candidates'][0],'path':'/api/test/store/other'})
            self.assertIsNone(flow_planner.compile_form(form_case,index))
    def test_comments_removed_without_changing_strings_or_line_numbers(self):
        text="var url='https://host/path'; // ignored\n/* hidden\n */ active();"
        result=flow_planner.without_comments(text)
        self.assertIn('https://host/path',result);self.assertNotIn('ignored',result)
        self.assertEqual(text.count('\n'),result.count('\n'))

class HttpObserverTests(unittest.TestCase):
    def probe(self,events,run='r'):
        manifest={'file':'devicecheck-http-'+'a'*32+'.json','paths':['/api/test/store/settings'],'response_fields':['data.count'],'success_codes':[610000,0]}
        probe=http_probe.Probe('Android','emulator-test','com.test',manifest,lambda x:None,'adb')
        probe.read=lambda:{'run':run,'counter':8,'events':events}
        return probe
    def event(self,**changes):
        return {'request_seq':6,'path':'/api/test/store/settings','method':'POST','http_status':200,'code':610000,'error':None,'response_fields':{'data.count':3},**changes}
    def test_matching_response_and_fields_confirmed(self):
        probe=self.probe([self.event()])
        result=probe.check({'run':'r','counter':5},{'path':'/api/test/store/settings','method':'POST','equals':{'data.count':3}})
        self.assertEqual(result['code'],610000)
    def test_old_inflight_request_cannot_confirm_new_save(self):
        probe=self.probe([self.event(request_seq=5)])
        self.assertIsNone(probe.check({'run':'r','counter':5},{'path':'/api/test/store/settings','method':'POST'}))
    def test_business_error_and_missing_code_are_not_http_success(self):
        for code in (500001,None):
            probe=self.probe([self.event(code=code)])
            with self.assertRaises(AssertionError):probe.check({'run':'r','counter':5},{'path':'/api/test/store/settings','method':'POST'})
    def test_http_failure_and_field_mismatch_fail(self):
        probe=self.probe([self.event(http_status=500)])
        with self.assertRaises(AssertionError):probe.check({'run':'r','counter':5},{'path':'/api/test/store/settings','method':'POST'})
        probe=self.probe([self.event()])
        with self.assertRaises(AssertionError):probe.check({'run':'r','counter':5},{'path':'/api/test/store/settings','method':'POST','equals':{'data.count':4}})
    def test_app_restart_and_ambiguous_responses_block(self):
        for probe in (self.probe([self.event()],run='new'),self.probe([self.event(),self.event(request_seq=7)])):
            with self.assertRaises(RuntimeError):probe.check({'run':'r','counter':5},{'path':'/api/test/store/settings','method':'POST'})
    def test_wrong_method_and_endpoint_do_not_match(self):
        probe=self.probe([self.event(method='GET')])
        self.assertIsNone(probe.check({'run':'r','counter':5},{'path':'/api/test/store/settings','method':'POST'}))
    def test_sensitive_response_fields_rejected(self):
        for field in ('data.accessToken','data.password','data.email','data.account.name'):
            with self.assertRaises(ValueError):http_probe.safe_fields([field])
    def test_instrumentation_uses_observer_and_excludes_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp);file=project/'lib/http/dio_client.dart';file.parent.mkdir(parents=True)
            file.write_text('void init() { dio = Dio(options); }')
            manifest=http_probe.instrument(project,{'api_calls':[{'path':'/api/test/store/settings'},{'path':'/api/auth/login'}],'business_success_codes':[610000,0]},['data.count'])
            self.assertNotIn('/api/auth/login',manifest['paths'])
            code=(project/'lib/devicecheck_http_observer.dart').read_text()
            self.assertNotIn('options.data',code);self.assertNotIn('options.headers',code)
            self.assertIn('handler.next(response)',code);self.assertIn("RegExp(r'\\b\\d{11,}\\b')",code)
    def test_save_plan_must_have_exact_endpoint_and_no_credential_change(self):
        good={'steps':[{'action':'input','value':'名称','text':'test'},{'action':'save','value':'保存','api':{'method':'POST','path':'/api/test/store/settings','equals':{'data.count':3}}}]}
        self.assertEqual(case_runner.validate_plan(good)['steps'][1]['action'],'save')
        for path in ('/api/auth/login','/api/store/delete','/api/robot/call/task'):
            good['steps'][1]['api']['path']=path
            with self.assertRaises(ValueError):case_runner.validate_plan(good)

class SaveFlowTests(unittest.TestCase):
    def execute(self,has_probe=True,business_ok=True):
        operations=[];state={'value':''}
        def source():
            return '<hierarchy><node class="android.widget.Button" package="com.test" text="Home&#10;Tab 1 of 4" clickable="true"/><node class="android.widget.EditText" package="com.test" hint="Name" text="'+escape(state['value'],{'"':'&quot;'})+'"/><node class="android.widget.Button" package="com.test" text="Save" clickable="true"/></hierarchy>'
        exp=Explorer(lambda *args:None,'s','Android',lambda x:None,lambda *args:None)
        exp.app_package='com.test'
        class Probe:
            manifest={'paths':['/api/test/store/settings'],'response_fields':['data.count']}
            last_event=None
            def mark(self):operations.append('mark');return 'marker'
            def check(self,marker,expect):
                self_check=operations.index('tap:Save')>operations.index('mark')
                if not self_check:raise AssertionError('save was not clicked')
                if not business_ok:raise AssertionError('business failure')
                self.last_event={'http_status':200,'code':610000,'response_fields':{'data.count':3}}
                return self.last_event
        if has_probe:exp.http_probe=Probe()
        def type_value(eid,text,node):state['value']=text;operations.append('input')
        plan={'steps':[{'action':'input','value':'Name','text':'qa-001'},{'action':'assert_input','value':'Name','text':'qa-001'},{'action':'save','value':'Save','api':{'path':'/api/test/store/settings','method':'POST','equals':{'data.count':3}}}]}
        case={'id':'S:2','sheet':'S','row':2,'title':'save name','group':'test','priority':'P0','mobile':True,'steps':'explicit','expected':'explicit','precondition':'','plan_text':json.dumps(plan)}
        with patch.object(exp,'settled_source',side_effect=source),patch.object(exp,'find',return_value='field'),patch.object(exp,'tap',side_effect=lambda node:operations.append('tap:'+node['label'].split('\n')[0])),patch.object(exp,'type',side_effect=type_value):
            results=case_runner.run(exp,{'cases':[case]}, {},lambda x:None,lambda *args:'/proof.png',lambda x:None,lambda:False,lambda x:None)
        return results[0],operations
    def test_input_readback_and_exact_api_save_pass_together(self):
        result,operations=self.execute()
        self.assertEqual(result['result'],'pass')
        self.assertLess(operations.index('input'),operations.index('mark'))
        self.assertEqual(result['steps'][-1]['api']['code'],610000)
    def test_save_is_not_clicked_without_observer(self):
        result,operations=self.execute(has_probe=False)
        self.assertEqual(result['result'],'fail');self.assertNotIn('tap:Save',operations)
    def test_http_response_with_business_failure_is_not_pass(self):
        result,operations=self.execute(business_ok=False)
        self.assertEqual(result['result'],'fail');self.assertEqual(result['status'],'断言失败')

if __name__=='__main__':unittest.main()

class AISummaryTests(unittest.TestCase):
    def test_login_controls_and_local_navigation_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'lib').mkdir()
            (p/'lib/config.dart').write_text("_selectionField(label: 'language'.tr, value: selectedLanguage); SpUtil.putString(SPKey.selectedLocale, locale); Get.offAllNamed(Routers.login);")
            login={'name':'loginConfig','path':'/loginConfig','source':'lib/config.dart','labels':[{'key':'language','labels':['语言','Language']}],'title_labels':[]}
            misleading={'name':'myScene','path':'/my/scene','source':'lib/config.dart','labels':[{'key':'data_center','labels':['数据中心']}],'title_labels':['数据中心']}
            index={'project':tmp,'pages':[misleading,login],'translations':{'language':['语言','Language']},'navigation':{'routes':[{'name':'login','path':'/login'}]}}
            result=flow_planner.ai_summary(index,'登录前配置语言')
            page=result['pages'][0]
            self.assertEqual(page['name'],'loginConfig')
            self.assertEqual(page['labels'][0]['labels'],['语言','Language'])
            self.assertEqual(page['local_state_evidence']['preference_keys'],['selectedLocale'])
            self.assertEqual(page['local_state_evidence']['navigation_targets'][0]['path'],'/login')
            self.assertEqual(page['local_state_evidence']['selection_fields'][0]['label_key'],'language')

    def test_summary_budget_drops_whole_pages_instead_of_cutting_json(self):
        index={'project':'/tmp','pages':[{'name':str(i),'path':'/p'+str(i),'labels':[{'labels':['x'*1000]}]} for i in range(10)]}
        summary=flow_planner.ai_summary(index,'',max_chars=1800)
        self.assertLessEqual(len(json.dumps(summary,ensure_ascii=False)),1800)
        self.assertEqual(json.loads(json.dumps(summary)),summary)

    def test_exact_route_is_prioritized_over_generic_login_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'page.dart').write_text('Text("test");')
            common={'source':'page.dart','labels':[{'labels':['登录','语言','保存']}]}
            pages=[dict(common,name='login',path='/login')]+[dict(common,name='noise'+str(i),path='/noise'+str(i)) for i in range(30)]+[dict(common,name='queueLimit',path='/deployment/queueLimitCount')]
            result=flow_planner.ai_summary({'project':tmp,'pages':pages},'登录后进入/deployment/queueLimitCount保存语言')
            self.assertEqual(result['pages'][0]['path'],'/deployment/queueLimitCount')

    def test_language_aliases_include_all_locales_but_prompt_is_scoped(self):
        index={'project':'/tmp','pages':[{'name':'language','path':'/language','labels':[{'key':'language','labels':['语言','Language','言語','Sprache']}]}],'locale_packs':{'zh':{'language':'语言'},'en':{'language':'Language'},'ja':{'language':'言語'},'de':{'language':'Sprache'}}}
        result=flow_planner.ai_summary(index,'语言',language='ja')
        self.assertEqual(result['pages'][0]['labels'][0]['labels'],['语言','Language','言語'])
        self.assertIn('Sprache',index['pages'][0]['labels'][0]['labels'])

class EvidenceBudgetRegressionTests(unittest.TestCase):
    def test_login_and_post_login_language_pages_are_kept_together(self):
        pages=[{'path':'/loginConfig','name':'loginConfig','labels':[{'labels':['国家或区域']}]} ,
               {'path':'/login','name':'login','labels':[{'labels':['账号','密码']}],'inputs':[{'widget':'InputTxtWidget'}]},
               {'path':'/language','name':'language','labels':[{'labels':['语言']}],'entry_candidates':[{'steps':['我的','通用设置','语言']}]},
               {'path':'/my/currency','name':'myCurrency','labels':[{'labels':['通用设置']}]}]
        pages += [{'path':'/login/noise'+str(i),'name':'noise'+str(i),'labels':[{'labels':['登录','密码','账号','协议']}]} for i in range(25)]
        summary=flow_planner.ai_summary({'project':'/tmp','pages':pages},'首次启动，账号密码登录；我的→通用设置→语言，选择中文简体',max_chars=3600)
        self.assertTrue({'/loginConfig','/login','/language','/my/currency'} <= {p['path'] for p in summary['pages']})

    def test_target_api_navigation_and_business_codes_survive_budget(self):
        api={'http_method':'POST','path':'/api/test/save'}
        page={'name':'form','path':'/form','labels':[{'labels':['noise'*1000]}],
              'api_candidates':[api],'entry_candidates':[{'steps':['我的','表单']}],
              'inputs':[{'labels':[{'key':'name','labels':['名称']}]}]}
        index={'project':'/tmp','pages':[page],'business_success_codes':[610000]}
        result=flow_planner.ai_summary(index,'打开/form，填写名称保存',max_chars=1800)
        self.assertEqual(result['business_success_codes'],[610000])
        self.assertEqual(result['pages'][0]['api_candidates'],[api])
        self.assertEqual(result['pages'][0]['entry_candidates'],page['entry_candidates'])
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),1800)

    def test_login_config_controls_survive_protocol_pages_and_large_route_overview(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as tmp:
            config={'name':'loginConfig','path':'/loginConfig','labels':[{'key':k,'labels':[label]} for k,label in [('country','国家或区域'),('search','请输入国家或地区'),('empty','未找到匹配的国家或地区'),('next','下一步')]]}
            pages=[{'name':'webview'+str(n),'path':'/webview','kind':'h5_entry','labels':[{'labels':['协议']}],'source':'long'+('x'*100)+str(n)} for n in range(30)]+[config]
            result=flow_planner.ai_summary({'project':tmp,'pages':pages},'登录前配置页、国家或区域搜索、协议打开',max_chars=2300)
            self.assertEqual(result['pages'][0]['path'],'/loginConfig')
            encoded=json.dumps(result,ensure_ascii=False)
            self.assertIn('请输入国家或地区',encoded);self.assertIn('未找到匹配的国家或地区',encoded)
            self.assertLessEqual(len(encoded),2300)
    def test_selection_field_labels_use_target_language_budget(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'page.dart').write_text("_selectionField(label: 'country'.tr)")
            labels={'zh':{'country':'国家'},'en':{'country':'Country'},'de':{'country':'Land'}}
            result=flow_planner.ai_summary({'project':tmp,'pages':[{'path':'/loginConfig','source':'page.dart'}],'locale_packs':labels,'translations':{'country':['国家','Country','Land']}},'登录前配置页')
            self.assertEqual(result['pages'][0]['local_state_evidence']['selection_fields'][0]['labels'],['国家','Country'])
