import copy,unittest
from unittest.mock import Mock,patch
import auto_forms as auto,form_runner
from automation import Explorer,parse_ui


def field(label,kind='text',**extra):return dict({'label':label,'kind':kind,'input_type':'text','required':True,'filled':False},**extra)

class BindingTests(unittest.TestCase):
    def test_automatic_is_default_and_off_is_explicit(self):
        self.assertEqual(form_runner.validate(None)['mode'],'auto')
        self.assertFalse(form_runner.validate({'enabled':False})['enabled'])
    def test_only_name_and_description_get_generated_data(self):
        for label in ('联系人','姓名','Contact name','问题描述','Problem Description'):
            value,source,reason=auto.choose(field(label),{});self.assertEqual(source,'generated');self.assertTrue('自动化' in value or 'Automation' in value)
        for label in ('电话','邮箱','门店','机器人编号','Name','地区'):
            self.assertIsNone(auto.choose(field(label),{})[0])
    def test_configured_values_match_translated_labels_and_override_generated(self):
        self.assertEqual(auto.choose(field('Please enter your phone number'),{'联系电话':'123'})[:2],('123','configured'))
        self.assertEqual(auto.choose(field('Contact name'),{'姓名':'专用测试人'})[:2],('专用测试人','configured'))
    def test_repair_form_placeholders_are_recognized_without_page_configuration(self):
        self.assertEqual(auto.choose(field('Please type in your name'),{})[1],'generated')
        self.assertEqual(auto.choose(field('Please describe the issue in at least 10 words and include screenshots or videos.'),{})[1],'generated')
        self.assertEqual(auto.choose(field('Please enter your phone number or email address'),{'联系电话':'123'})[:2],('123','configured'))
        self.assertEqual(auto.category('Please select the corresponding robot number'),'robot')
    def test_ambiguous_or_invalid_options_are_not_guessed(self):
        self.assertIsNone(auto.choose(field('Phone'),{'电话':'123','联系电话':'456'})[0])
        self.assertIsNone(auto.choose(field('问题类型','select',options=['硬件']),{'问题类型':'软件'})[0])
        self.assertIsNone(auto.choose(field('状态','checkbox'),{'状态':'true'})[0])
    def test_agreements_and_password_fields_are_not_filled(self):
        self.assertIsNone(auto.choose(field('User Privacy Agreement','checkbox'),{'User Privacy Agreement':True})[0])
        self.assertIsNone(auto.choose(field('验证码'),{'验证码':'123456'})[0])
    def test_data_is_local_and_sensitive_values_are_not_reported(self):
        e=Mock();e.stopped.return_value=False;e.secrets=[];d=Mock()
        snapshot={'fields':[field('Phone')],'_driver':d}
        r=auto.fill(e,snapshot,auto.validate({'data':{'电话':'13800138000'}}))
        self.assertEqual(r['status'],'filled');self.assertFalse(r['submitted']);self.assertNotIn('13800138000',str(r));self.assertIn('13800138000',e.secrets)
        d.submit.assert_not_called()
    def test_partial_fill_records_missing_data_without_submission(self):
        e=Mock();e.stopped.return_value=False;e.secrets=[];d=Mock()
        r=auto.fill(e,{'fields':[field('联系人'),field('设备编号')],'_driver':d},auto.validate({}))
        self.assertEqual(r['status'],'partial');self.assertEqual(d.fill.call_count,1);self.assertFalse(r['submitted'])
    def test_existing_values_are_preserved_unless_explicit_data_is_given(self):
        for data,count in (({},0),({'姓名':'测试人'},1)):
            e=Mock();e.stopped.return_value=False;e.secrets=[];d=Mock()
            r=auto.fill(e,{'fields':[field('姓名',filled=True)],'_driver':d},auto.validate({'data':data}))
            self.assertEqual(d.fill.call_count,count);self.assertEqual(r['status'],'filled')
    def test_same_name_fields_are_rejected_before_typing(self):
        e=Mock();e.secrets=[];d=Mock()
        r=auto.fill(e,{'fields':[field('姓名'),field('姓名')],'_driver':d},auto.validate({}))
        self.assertEqual(r['status'],'blocked');d.fill.assert_not_called()

class DiscoveryTests(unittest.TestCase):
    def test_search_login_and_radio_filters_are_not_forms(self):
        self.assertFalse(auto.candidate({'fields':[field('Search')],'buttons':['Search']}))
        self.assertFalse(auto.candidate({'fields':[field('Phone'),field('Verification code')],'buttons':['Login']}))
        self.assertFalse(auto.candidate({'fields':[field('Region','checkbox'),field('Type','checkbox')],'buttons':[]}))
        self.assertTrue(auto.candidate({'fields':[field('姓名')],'buttons':['提交']}))
    def test_otp_page_is_not_left_to_generic_button_clicks(self):
        e=Mock();e.auto_form_epoch=0;e.secrets=[]
        nodes=parse_ui('<hierarchy><node class="android.widget.EditText" hint="Phone"/><node class="android.widget.EditText" hint="Verification code"/><node class="android.widget.Button" text="Verify" clickable="true"/></hierarchy>')
        detected,r=auto.visit(e,nodes,'/otp',auto.validate({}),{})
        self.assertTrue(detected);self.assertEqual(r['status'],'blocked');self.assertFalse(r['submitted']);e.call.assert_not_called()
    def test_native_metadata_does_not_use_an_unknown_input_value_as_a_field_name(self):
        nodes=parse_ui('<hierarchy><node class="android.widget.EditText" text="private-user-value"/></hierarchy>')
        self.assertEqual(auto.native_snapshot(nodes)['fields'][0]['label'],'')
    def test_native_form_is_detected_once_without_page_name_or_checkbox(self):
        xml='<hierarchy><node package="test.app" class="android.widget.EditText" hint="姓名"/><node package="test.app" class="android.widget.EditText" hint="问题描述"/><node package="test.app" class="android.widget.Button" text="提交" clickable="true"/></hierarchy>'
        e=Explorer(Mock(),'s','Android',lambda _:None,lambda *a:None);e.app_package='test.app';e.source=Mock(return_value=xml)
        with patch.object(auto.NativeDriver,'fill') as fill,patch('automation.time.sleep'):
            r=e.explore({'max_scrolls':0})
        self.assertEqual(fill.call_count,2);self.assertEqual(r['form_mode'],'auto');self.assertEqual(len(r['forms']),1)
        self.assertEqual(r['forms'][0]['status'],'filled');self.assertFalse(r['forms'][0]['submitted'])
        e.call.assert_not_called()
    def test_native_binding_follows_unique_hint_after_layout_reorders(self):
        before=parse_ui('<hierarchy><node class="android.widget.EditText" hint="姓名"/><node class="android.widget.EditText" hint="问题描述"/></hierarchy>')
        after='<hierarchy><node class="android.widget.EditText" hint="问题描述"/><node class="android.widget.EditText" hint="姓名"/></hierarchy>'
        e=Mock();e.source.return_value=after
        driver=auto.NativeDriver(e,auto.native_snapshot(before)['fields'])
        self.assertEqual(driver.resolve('姓名','text')['path'],'/hierarchy[1]/node[2]')
    def test_web_context_failure_can_use_reliable_native_fields(self):
        xml='<hierarchy><node class="android.webkit.WebView"/><node class="android.widget.EditText" hint="姓名"/><node class="android.widget.Button" text="提交" clickable="true"/></hierarchy>'
        e=Mock();e.auto_form_epoch=0;e.stopped.return_value=False;e.secrets=[]
        with patch('hybrid_webview.WebView',side_effect=RuntimeError('no matching driver')),patch.object(auto.NativeDriver,'fill') as fill:
            detected,r=auto.visit(e,parse_ui(xml),'/webview',auto.validate({}),{})
        self.assertTrue(detected);self.assertEqual(r['discovery'],'native_accessibility');fill.assert_called_once()
    def test_revisiting_web_form_does_not_fill_again(self):
        e=Mock();e.auto_form_epoch=0;e.stopped.return_value=False;e.secrets=[];w=Mock();w.e=e
        w.js.return_value={'path':'https://test.invalid/form','fields':[field('姓名',element={})],'buttons':['提交']}
        cache={};xml='<hierarchy><node class="android.webkit.WebView"/></hierarchy>'
        with patch('hybrid_webview.WebView') as context,patch.object(auto.WebDriver,'fill') as fill:
            context.return_value.__enter__.return_value=w
            auto.visit(e,parse_ui(xml),'/webview',auto.validate({}),cache)
            e.auto_form_epoch=1
            auto.visit(e,parse_ui(xml),'/webview',auto.validate({}),cache)
        self.assertEqual(fill.call_count,1)
    def test_context_restore_error_never_repeats_fill_using_native(self):
        e=Mock();e.auto_form_epoch=0;e.stopped.return_value=False;e.secrets=[];e.base='/s';w=Mock();w.e=e
        w.js.return_value={'path':'https://test.invalid/form','fields':[field('姓名',element={})],'buttons':['提交']}
        with patch('hybrid_webview.WebView') as context,patch.object(auto.WebDriver,'fill') as webfill,patch.object(auto.NativeDriver,'fill') as nativefill:
            context.return_value.__enter__.return_value=w;context.return_value.__exit__.side_effect=RuntimeError('restore failed')
            detected,r=auto.visit(e,parse_ui('<hierarchy><node class="android.webkit.WebView"/></hierarchy>'),'/webview',auto.validate({}),{})
        self.assertTrue(detected);webfill.assert_called_once();nativefill.assert_not_called();self.assertFalse(r['submitted'])

if __name__=='__main__':unittest.main()
