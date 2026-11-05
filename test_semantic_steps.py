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
 global.document={querySelectorAll:()=>[{__vue__:{$i18n:i18n}}]};
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
            web.js.side_effect=[['店名'],[{'xpath':'/label','editable':False,'label':'店名'}]]
            result=s.perform(e,s.compile_text('等待报修表单加载完成')[0],Mock())
            self.assertTrue(result['matched'])
            self.assertEqual(web.js.call_args.args[1][1],'text')
            web.perform.assert_not_called()
