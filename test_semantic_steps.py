import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import semantic_steps as s


class CompilerTests(unittest.TestCase):
    def test_entire_ui_example_preserves_user_values_and_result_checks(self):
        import re
        html=Path('index.html').read_text()
        text=re.search(r'<textarea id="businessSteps"[^>]*>(.*?)</textarea>',html,re.S)[1]
        steps=s.compile_text(text)
        self.assertEqual(steps[0]['op'],'login')
        self.assertEqual([x['op'] for x in steps].count('submit'),1)
        self.assertIn('submission_result',[x['op'] for x in steps])
        self.assertEqual([x['text'] for x in steps if x.get('target')=='联系人'],['自动化测试人员'])
        self.assertEqual([x['choice'] for x in steps if x['op']=='select' and x['target']=='门店'],['乘梯测试门店---cy'])
        self.assertEqual(steps[-1]['op'],'assert')
        self.assertEqual(steps[-1]['target'],'首页')

    def test_unsupported_lines_fail_with_line_number_before_execution(self):
        with self.assertRaisesRegex(ValueError,'第 2 行'):
            s.compile_text('点击我的\n自动处理所有问题')

    def test_numbering_and_quoted_literals(self):
        result=s.compile_text('1. 联系人填写“张三”\n2、问题描述填写“中文原样，不能翻译”')
        self.assertEqual([r['text'] for r in result],['张三','中文原样，不能翻译'])

    def test_assertion_words_inside_input_are_not_executed(self):
        steps=s.compile_text('问题描述填写“出现异常，检查时不要提交”')
        self.assertEqual(len(steps),1)
        self.assertEqual(steps[0]['text'],'出现异常，检查时不要提交')

    def test_wait_is_bounded(self):
        with self.assertRaises(ValueError):s.compile_text('等待999秒')


class TranslationTests(unittest.TestCase):
    def test_chinese_resolves_source_key_in_french_without_translating_input(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'assets/i18n';folder.mkdir(parents=True)
            (folder/'zh.json').write_text(json.dumps({'mine':'我的'}))
            (folder/'fr.json').write_text(json.dumps({'mine':'Mon espace'}))
            groups=s.load_groups(d)
            self.assertIn('mon espace',s.terms('我的',groups))
            e=Mock();e.secrets=[];e.business_groups=groups;e.app_package='test.app';e.stopped.return_value=False
            e.source.return_value='<hierarchy><node package="test.app" clickable="true" content-desc="Mon espace&#10;Tab 4 of 4" /></hierarchy>'
            result=s.perform(e,s.compile_text('点击底部“我的”')[0],Mock())
            e.tap.assert_called_once();self.assertEqual(result['target'],'我的')

    def test_h5_js_translation_keys_extend_multiple_locales(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'src/lang/common';folder.mkdir(parents=True)
            (folder/'index.js').write_text("const zh = {\n contacts: '联系人',\n}\nconst fr = {\n contacts: 'Interlocuteur',\n}\n")
            self.assertIn('interlocuteur',s.terms('联系人',s.load_groups(h5_source=d)))

    def test_launcher_home_cannot_match_app_home(self):
        e=Mock();e.app_package='test.app'
        e.source.return_value='<hierarchy><node package="launcher" text="Home" clickable="true" /></hierarchy>'
        self.assertIsNone(s._native(e,'首页',s.GROUPS)[0])

    def test_ambiguous_native_controls_never_click(self):
        e=Mock();e.app_package='test.app';e.business_groups=s.GROUPS;e.stopped.return_value=False
        e.source.return_value='<hierarchy><node package="test.app" text="Mine" clickable="true"/><node package="test.app" text="Mine" clickable="true"/></hierarchy>'
        with self.assertRaisesRegex(ValueError,'多个'):s.perform(e,s.compile_text('点击我的')[0],Mock())
        e.tap.assert_not_called()


class SubmissionTests(unittest.TestCase):
    def test_generic_submit_is_blocked_outside_bound_repair_form(self):
        e=Mock();e.business_groups=s.GROUPS
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            web=ctx.return_value.__enter__.return_value;web.js.return_value=False
            with self.assertRaisesRegex(RuntimeError,'没有已适配'):s.perform(e,s.compile_text('点击提交')[0],Mock())
            web.perform.assert_not_called()

    def test_report_submit_requires_current_api_evidence(self):
        e=Mock();e.business_groups=s.GROUPS;e.business_submission=None
        with self.assertRaisesRegex(RuntimeError,'尚无'):s.perform(e,s.compile_text('检查是否提交成功')[0],Mock())

    def test_unconfigured_login_never_passes(self):
        with self.assertRaisesRegex(RuntimeError,'启用'):
            s.perform(Mock(),s.compile_text('自动登录')[0],Mock(),{'status':'not_confirmed'})


class DOMScriptTests(unittest.TestCase):
    def test_associated_translated_field_selects_control_and_keeps_input_verbatim(self):
        e=Mock();e.business_groups=s.GROUPS;e.app_package='test.app';e.stopped.return_value=False
        e.source.return_value='<hierarchy><node package="test.app" class="android.webkit.WebView" /></hierarchy>'
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            web=ctx.return_value.__enter__.return_value
            web.js.return_value=[{'xpath':'/html[1]/body[1]/input[1]','editable':True,'label':''}]
            s.perform(e,s.compile_text('联系人填写“中文原样”')[0],Mock())
            self.assertIn('contact',web.js.call_args.args[1][0])
            calls=web.perform.call_args_list
            self.assertEqual([c.args[0]['action'] for c in calls],['web_input','web_assert_input'])
            self.assertTrue(all(c.args[0]['text']=='中文原样' for c in calls))

if __name__=='__main__':unittest.main()

class PreviewAPITests(unittest.TestCase):
    def test_chinese_preview_and_unsupported_line_response(self):
        import app,threading,urllib.request,urllib.error
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(text):
            return urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/steps/preview',data=json.dumps({'text':text}).encode(),headers={'Content-Type':'application/json'})
        try:
            with opener.open(request('点击我的\n联系人填写“中文原样”')) as response:
                data=json.load(response)
                self.assertEqual(data['steps'][1]['text'],'中文原样')
            with self.assertRaises(urllib.error.HTTPError) as error:opener.open(request('随便操作'))
            self.assertEqual(error.exception.code,400)
        finally:server.shutdown();server.server_close()

class SettingsNavigationTests(unittest.TestCase):
    def explorer(self):
        e=Mock();e.platform='Android';e.app_package='test.app';e.business_groups=s.GROUPS;e.secrets=[];e.stopped.return_value=False
        return e

    def settings(self,title):
        return '<hierarchy><node package="test.app" class="android.widget.ImageView" clickable="true" bounds="[0,69][127,219]"/><node package="test.app" text="'+title+'" /></hierarchy>'

    def root(self):
        return '<hierarchy><node package="test.app" clickable="true" content-desc="Home&#10;Tab 1 of 4"/><node package="test.app" clickable="true" content-desc="Mine&#10;Tab 4 of 4"/></hierarchy>'

    def test_after_language_switch_unwinds_settings_then_clicks_home(self):
        e=self.explorer();e.source.side_effect=[self.settings('语言'),self.settings('通用设置'),self.root()]
        result=s.perform(e,s.compile_text('回到首页')[0],Mock())
        self.assertEqual(result['navigation_returns'],2)
        self.assertEqual(e.tap.call_count,3)
        self.assertEqual(e.tap.call_args.args[0]['label'],'Home\nTab 1 of 4')
        e.back.assert_not_called()

    def test_root_tab_does_not_send_back(self):
        e=self.explorer();e.source.return_value=self.root()
        s.perform(e,s.compile_text('回到我的')[0],Mock())
        e.tap.assert_called_once();e.back.assert_not_called();e.settled_source.assert_not_called()

    def test_unknown_page_is_not_unwound(self):
        e=self.explorer();e.source.return_value='<hierarchy><node package="test.app" text="未知页面" /></hierarchy>'
        self.assertIsNone(s.navigate_tab(e,'首页',s.GROUPS,Mock()))
        e.tap.assert_not_called();e.back.assert_not_called()

    def test_launcher_or_webview_never_receives_recovery_back(self):
        e=self.explorer()
        for xml in ('<hierarchy><node package="launcher" text="Language" /></hierarchy>', '<hierarchy><node package="test.app" class="android.webkit.WebView" text="Language" /></hierarchy>'):
            e.source.return_value=xml
            self.assertIsNone(s.navigate_tab(e,'首页',s.GROUPS,Mock()))
        e.tap.assert_not_called();e.back.assert_not_called()

    def test_broken_settings_navigation_has_a_finite_return_budget(self):
        e=self.explorer();e.source.return_value=self.settings('通用设置')
        with self.assertRaisesRegex(AssertionError,'停止恢复'):s.navigate_tab(e,'首页',s.GROUPS,Mock())
        self.assertEqual(e.tap.call_count,3)
        e.back.assert_not_called()

class RuntimeTranslationTests(unittest.TestCase):
    def test_active_locale_uses_chinese_key_without_cross_language_collisions(self):
        import subprocess,shutil
        node=shutil.which('node')
        if not node:self.skipTest('Node required for browser script verification')
        messages={'zh':{'common':{'storeName':'门店名称','contacts':'联系人','phone':'联系方式'}},
                  'en':{'common':{'storeName':'Store Name','contacts':'Contact','phone':'Contact information'}},
                  'ja':{'common':{'storeName':'店名','contacts':'連絡担当者','phone':'連絡先'}},
                  'ko':{'common':{'storeName':'매장명','contacts':'연락처','phone':'연락 방법'}},
                  'fr':{'common':{'storeName':'Nom du magasin','contacts':'Personne de contact','phone':'Coordonnées'}},
                  'th':{'common':{'storeName':'ชื่อร้าน','contacts':'ติดต่อ','phone':'ข้อมูลติดต่อ'}},
                  'zht':{'common':{'storeName':'門店名稱','contacts':'聯絡人','phone':'聯絡方式'}}}
        script='const messages='+json.dumps(messages)+';const discover=new Function('+json.dumps(s.RUNTIME_TRANSLATIONS)+''');
const result={};
for(const locale of Object.keys(messages)){
 const i18n={messages,locale};
 global.document={readyState:'complete',querySelectorAll:()=>[{__vue__:{$i18n:i18n}}]};
 result[locale]=['门店名称','联系人','联系方式'].map(target=>discover(['Contact','연락처','联系方式','联系人'],target));
}
console.log(JSON.stringify(result));'''
        result=json.loads(subprocess.check_output([node,'-e',script],text=True))
        for locale,data in messages.items():
            self.assertEqual(result[locale],[[s.norm(data['common'][key])] for key in ('storeName','contacts','phone')])

    def test_quoted_translation_keys_and_apostrophes(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'src/lang/common';folder.mkdir(parents=True)
            (folder/'index.js').write_text('const zh = {\n "contacts": "联系人",\n}\nconst fr = {\n "contacts": "Contact de l’hôtel",\n}\n')
            self.assertIn('contact de l’hôtel',s.terms('联系人',s.load_groups(h5_source=d)))

    def test_loaded_page_dictionary_extends_missing_source_translation(self):
        web=Mock()
        web.js.side_effect=[['店名'],[{'xpath':'/label','editable':False,'label':'店名'}]]
        self.assertEqual(s._web_find(web,'门店名称',s.GROUPS)['label'],'店名')
        self.assertEqual(web.js.call_args.args[1],[['店名'],'text'])

    def test_repair_page_assertion_accepts_readonly_store_label(self):
        e=Mock();e.business_groups=s.GROUPS;e.app_package='test.app';e.stopped.return_value=False
        e.source.return_value='<hierarchy><node package="test.app" class="android.webkit.WebView" /></hierarchy>'
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            web=ctx.return_value.__enter__.return_value
            web.js.return_value=True
            result=s.perform(e,s.compile_text('等待报修表单加载完成')[0],Mock())
            self.assertTrue(result['matched'])
            self.assertEqual(web.js.call_args.args[0],s.PAGE_READY)
            self.assertEqual(web.js.call_args.args[1],['/repairForm','#repair .repair-form'])
            web.perform.assert_not_called()

class FormAliasRegressionTests(unittest.TestCase):
    def test_field_aliases_resolve_form_key_instead_of_generic_navigation_key(self):
        for target,canonical in s.FIELD_TARGETS.items():
            with self.subTest(target=target):
                web=Mock();web.js.side_effect=[['translated field'],[{'xpath':'/input','editable':True}]]
                self.assertIsNotNone(s._web_find(web,target,s.GROUPS,'field'))
                self.assertEqual(web.js.call_args_list[0].args[1][1],canonical)

    def test_store_navigation_retains_generic_key(self):
        web=Mock();web.js.side_effect=[['店舗'],[{'xpath':'/button'}]]
        s._web_find(web,'门店',s.GROUPS,'text')
        self.assertEqual(web.js.call_args_list[0].args[1][1],'门店')

    def test_japanese_store_selection_after_form_loaded(self):
        e=Mock();e.business_groups=s.GROUPS;e.app_package='test.app';e.stopped.return_value=False
        e.source.return_value='<hierarchy><node package="test.app" class="android.webkit.WebView" /></hierarchy>'
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            web=ctx.return_value.__enter__.return_value
            def js(script,args=None,**kwargs):
                if script==s.RUNTIME_TRANSLATIONS:
                    return ['店名'] if args[1]=='门店名称' else ['店舗'] if args[1]=='门店' else args[0]
                words,mode=args
                if mode=='field' and words==['店名']:return [{'xpath':'/store/input','editable':True}]
                if mode=='option' and '乘梯测试门店---cy' in words:return [{'xpath':'/options/li','editable':False}]
                return []
            web.js.side_effect=js
            result=s.perform(e,s.compile_text('门店选择“乘梯测试门店---cy”')[0],Mock())
            self.assertTrue(result['matched'])
            actions=[c.args[0] for c in web.perform.call_args_list]
            self.assertEqual(actions[0]['value'],'/store/input')
            self.assertEqual(actions[0]['text'],'乘梯测试门店---cy')
            self.assertEqual(actions[1]['value'],'/options/li')
            self.assertEqual(actions[2]['action'],'web_assert_input')

class SourcePageAssertionTests(unittest.TestCase):
    def test_enter_is_compiled_without_changing_target(self):
        self.assertEqual(s.compile_text('进入附近门店')[0]['target'],'附近门店')

    def test_nearby_page_uses_route_and_dom_even_when_title_matches(self):
        e=Mock();e.app_package='test.app';e.business_groups=s.GROUPS;e.stopped.return_value=False
        e.source.return_value='<hierarchy><node package="test.app" class="android.webkit.WebView"/><node package="test.app" text="附近门店"/></hierarchy>'
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            web=ctx.return_value.__enter__.return_value;web.js.return_value=True
            result=s.perform(e,s.compile_text('确认附近门店页面打开')[0],Mock())
            self.assertEqual(result['route'],'/storeMap')
            self.assertEqual(web.js.call_args.args[1],['/storeMap','.store-map .map-page'])

    def test_matching_title_on_wrong_route_does_not_pass(self):
        e=Mock();e.app_package='test.app';e.business_groups=s.GROUPS;e.stopped.return_value=False
        e.source.return_value='<hierarchy><node package="test.app" class="android.webkit.WebView"/><node package="test.app" text="附近门店"/></hierarchy>'
        with patch.object(s.hybrid_webview,'WebView') as ctx,patch.object(s.time,'monotonic',side_effect=[0,91]):
            ctx.return_value.__enter__.return_value.js.return_value=False
            with self.assertRaisesRegex(AssertionError,'路由或页面结构不匹配'):
                s.perform(e,s.compile_text('确认附近门店页面打开')[0],Mock())

class SourceBackTests(unittest.TestCase):
    def test_nearby_back_clicks_source_header_instead_of_browser_history(self):
        e=Mock();e.app_package='test.app';e.business_groups=s.GROUPS
        e.source.return_value='<hierarchy><node package="test.app" class="android.webkit.WebView" /></hierarchy>'
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            web=ctx.return_value.__enter__.return_value
            web.js.return_value='.store-map .city-area .van-icon-arrow-left'
            result=s.perform(e,s.compile_text('返回')[0],Mock())
            self.assertEqual(result['via'],'h5_header')
            e.back.assert_not_called()
            web.perform.assert_called_once_with({'action':'web_tap','by':'css','value':'.store-map .city-area .van-icon-arrow-left'})

class PageDOMScriptTests(unittest.TestCase):
    def test_map_assertion_rejects_visible_list_overlay_and_wrong_routes(self):
        import subprocess,shutil
        node=shutil.which('node')
        if not node:self.skipTest('Node required')
        script='const check=new Function('+json.dumps(s.PAGE_READY)+''');
const el={getClientRects:()=>[{}]};
global.getComputedStyle=()=>({visibility:'visible',display:'block'});
let listVisible=true;
global.document={readyState:'complete',querySelectorAll:s=>s==='.store-list-page'?(listVisible?[el]:[]):[el]};
global.location={hash:'#/storeMap?redacted'};
const args=['/storeMap','.store-map .map-page','.store-list-page'];
const results=[check(...args)];listVisible=false;results.push(check(...args));
location.hash='#/study';results.push(check(...args));
console.log(JSON.stringify(results));'''
        self.assertEqual(json.loads(subprocess.check_output([node,'-e',script],text=True)),[False,True,False])

class BusinessPermissionTests(unittest.TestCase):
    def test_nearby_location_permission_is_resolved_before_page_assertion(self):
        e=Mock();e.app_package='test.app';e.business_groups=s.GROUPS;e.stopped.return_value=False
        e.source.side_effect=[
            '<hierarchy><node package="com.google.android.permissioncontroller" text="Allow location?"/><node package="com.google.android.permissioncontroller" text="While using the app" clickable="true"/></hierarchy>',
            '<hierarchy><node package="test.app" class="android.webkit.WebView"/></hierarchy>']
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            ctx.return_value.__enter__.return_value.js.return_value=True
            result=s.perform(e,s.compile_text('确认附近门店页面打开')[0],Mock())
        self.assertEqual(result['route'],'/storeMap')
        self.assertEqual(e.tap.call_args.args[0]['label'],'While using the app')

    def test_generic_app_allow_button_is_not_granted_by_business_handler(self):
        e=Mock();e.app_package='test.app';e.business_groups=s.GROUPS;e.stopped.return_value=False
        e.source.return_value='<hierarchy><node package="test.app" text="location permission"/><node package="test.app" text="Allow" clickable="true"/><node package="test.app" class="android.webkit.WebView"/></hierarchy>'
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            ctx.return_value.__enter__.return_value.js.return_value=True
            s.perform(e,s.compile_text('确认附近门店页面打开')[0],Mock())
        e.tap.assert_not_called()

class CourseCenterVariantTests(unittest.TestCase):
    def test_source_defined_course_paths_require_visible_search_control(self):
        import subprocess,shutil
        node=shutil.which('node')
        if not node:self.skipTest('Node required')
        script='const ready=new Function('+json.dumps(s.PAGE_READY)+''');
global.location={pathname:'/sub-app/study/courseCenter/list',hash:''};
let shown=true;const input={getClientRects:()=>shown?[{}]:[]};
global.getComputedStyle=()=>({visibility:'visible',display:'block'});
global.document={readyState:'complete',querySelectorAll:()=>[input]};
const args=['@path:/sub-app/study/courseCenter/list','input:not([type=hidden])'];
const results=[ready(...args)];shown=false;results.push(ready(...args));shown=true;
location.pathname='/login';results.push(ready(...args));
location.pathname='/webos/sub-app/study/courseCenter/list';results.push(ready('@path:'+location.pathname,args[1]));
console.log(JSON.stringify(results));'''
        self.assertEqual(json.loads(subprocess.check_output([node,'-e',script],text=True)),[True,False,False,True])

    def test_course_back_requires_unique_header_icon(self):
        import subprocess,shutil
        node=shutil.which('node')
        if not node:self.skipTest('Node required')
        script='const back=new Function('+json.dumps(s.H5_BACK)+''');
global.location={pathname:'/sub-app/study/courseCenter/list',hash:''};
global.getComputedStyle=()=>({visibility:'visible',display:'block'});
const root={nodeType:1,tagName:'HTML',parentElement:null,previousElementSibling:null};
function icon(x=10){return {nodeType:1,tagName:'I',namespaceURI:'http://www.w3.org/1999/xhtml',parentElement:root,previousElementSibling:null,getAttribute:()=>'',closest:()=>null,contains:()=>false,getClientRects:()=>[{}],getBoundingClientRect:()=>({left:x,top:10,width:20,height:20})}}
let icons=[icon()];global.document={readyState:'complete',querySelectorAll:s=>s==='body *'?icons:[],elementFromPoint:x=>icons.find(e=>{const r=e.getBoundingClientRect();return x>=r.left&&x<=r.left+r.width})};
const first=back();icons=[icon(10),icon(30)];const second=back();console.log(JSON.stringify([first,second]));'''
        result=json.loads(subprocess.check_output([node,'-e',script],text=True))
        self.assertEqual(result[0],{'by':'xpath','value':'/html[1]/i[1]'})
        self.assertTrue(result[1]['unresolved'])

class HybridNativeAmbiguityTests(unittest.TestCase):
    def test_h5_contact_fields_use_dom_instead_of_ambiguous_native_synonyms(self):
        e=Mock();e.app_package='test.app';e.stopped.return_value=False
        e.business_groups=[['联系人','联系方式','連絡担当者','連絡先']]
        e.source.return_value='<hierarchy><node package="test.app" class="android.webkit.WebView"><node package="test.app" text="連絡担当者"/><node package="test.app" text="連絡先"/></node></hierarchy>'
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            web=ctx.return_value.__enter__.return_value
            web.js.side_effect=[['連絡担当者'],[{'xpath':'/html[1]/body[1]/input[1]','editable':True,'label':''}]]
            result=s.perform(e,s.compile_text('联系人填写“自动化测试人员”')[0],Mock())
            self.assertTrue(result['matched'])
            self.assertEqual(web.perform.call_args_list[0].args[0]['text'],'自动化测试人员')
            self.assertEqual(web.js.call_args.args[1][0],['連絡担当者'])
        e.tap.assert_not_called()

class PendingH5TransitionTests(unittest.TestCase):
    def test_native_entry_label_does_not_satisfy_h5_page_assertion(self):
        e=Mock();e.app_package='test.app';e.business_groups=s.GROUPS;e.stopped.return_value=False
        e.source.side_effect=[
            '<hierarchy><node package="test.app" text="附近门店" clickable="true"/></hierarchy>',
            '<hierarchy><node package="test.app" class="android.webkit.WebView"/></hierarchy>']
        with patch.object(s.hybrid_webview,'WebView') as ctx:
            ctx.return_value.__enter__.return_value.js.return_value=True
            result=s.perform(e,s.compile_text('确认附近门店页面打开')[0],Mock())
        self.assertEqual(result['route'],'/storeMap');e.tap.assert_not_called()

class PageLoadingMaskTests(unittest.TestCase):
    def test_visible_search_under_full_page_loading_mask_is_not_ready(self):
        import subprocess,shutil
        node=shutil.which('node')
        if not node:self.skipTest('Node required')
        script='const ready=new Function('+json.dumps(s.PAGE_READY)+''');
global.location={pathname:'/sub-app/study/courseCenter/list',hash:''};global.innerWidth=400;global.innerHeight=800;
global.getComputedStyle=()=>({visibility:'visible',display:'block'});
const input={getClientRects:()=>[{}]};let loading=true;
const mask={getClientRects:()=>loading?[{}]:[],getBoundingClientRect:()=>({width:400,height:800})};
global.document={readyState:'complete',querySelectorAll:s=>s.startsWith('.el-loading-mask')?[mask]:[input]};
const args=['@path:/sub-app/study/courseCenter/list','input'];const first=ready(...args);loading=false;
console.log(JSON.stringify([first,ready(...args)]));'''
        self.assertEqual(json.loads(subprocess.check_output([node,'-e',script],text=True)),[False,True])
