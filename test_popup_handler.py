import unittest
from unittest.mock import patch
from automation import Explorer,parse_ui
from test_automation import FakeDriver,A
import popup_handler

POPUP='<hierarchy><node class="android.app.Dialog" package="com.example"><node class="android.widget.Button" package="com.example" text="稍后" clickable="true"/></node></hierarchy>'

class PopupTests(unittest.TestCase):
    def test_explicit_close_icon_and_cancel(self):
        for attributes in ('text="×"','resource-id="com.example:id/iv_close"','text="キャンセル"'):
            nodes=parse_ui('<hierarchy><node class="android.widget.Button" clickable="true" '+attributes+'/></hierarchy>')
            self.assertIsNotNone(popup_handler.close_target(nodes)[0])
    def test_business_confirmation_is_not_dismissal(self):
        for label in ('确定','支付','同意','允许','Next','删除账号'):
            nodes=parse_ui(f'<hierarchy><node class="android.widget.Button" clickable="true" text="{label}"/></hierarchy>')
            self.assertIsNone(popup_handler.close_target(nodes)[0])
    def test_popup_closed_before_page_capture(self):
        class Driver(FakeDriver):
            def __init__(self):super().__init__();self.state='popup'
            def source(self):return POPUP if self.state=='popup' else super().source()
            def __call__(self,method,path,data=None):
                if path.endswith('/click') and self.state=='popup':self.state='A';self.clicked.append('稍后');return None
                return super().__call__(method,path,data)
        driver=Driver();captures=[]
        exp=Explorer(driver,'s','Android',lambda x:None,lambda name,source:captures.append(source))
        with patch('automation.time.sleep'):result=exp.explore({'max_actions':6})
        self.assertEqual(driver.clicked[0],'稍后')
        self.assertEqual(len(result['popup_dismissals']),1)
        self.assertFalse(any('android.app.Dialog' in source for source in captures))
        self.assertEqual(len(result['pages']),2)
    def test_unclosable_modal_stops_background_actions(self):
        source=POPUP.replace('稍后','支付')
        exp=Explorer(lambda *args:source,'s','Android',lambda x:None,lambda *args:self.fail('modal screenshot'))
        result=exp.explore({})
        self.assertEqual(result['termination'],'popup_blocked')
        # 2026-11-04 新增返回键兜底：escape_overlay 先用一次返回键再放弃，故为 2 次操作。
        self.assertEqual(result['actions'],2)
    def test_repeated_nonclosing_button_is_bounded(self):
        driver=FakeDriver();driver.source=lambda:POPUP
        exp=Explorer(driver,'s','Android',lambda x:None,lambda *args:None)
        with patch('automation.time.sleep'):result=exp.explore({'max_actions':20,'popup_wait_seconds':0})
        self.assertEqual(result['termination'],'popup_blocked');self.assertEqual(result['actions'],3)

class PrivacyUpdateTests(unittest.TestCase):
    def test_known_privacy_update_confirmed_before_policy_link(self):
        xml='''<hierarchy><node text="Warm Reminder"/><node text="We have updated the Privacy Policy"/><node text="Privacy Policy" clickable="true"/><node text="Disagree and quit" clickable="true"/><node text="agree with" clickable="true"/></hierarchy>'''
        target,reason=popup_handler.close_target(parse_ui(xml))
        self.assertEqual(target['label'],'agree with')
        self.assertIn('隐私更新',reason)
        self.assertTrue(popup_handler.has_popup(parse_ui(xml)))
    def test_generic_agree_is_not_privacy_update(self):
        nodes=parse_ui('<hierarchy><node text="agree with" clickable="true"/></hierarchy>')
        self.assertIsNone(popup_handler.close_target(nodes)[0])


class TutorialLayerTests(unittest.TestCase):
    def test_tutorial_above_privacy_is_advanced_first(self):
        xml='<hierarchy><node text="Click here to view the information"/><node text="Next" clickable="true"/><node text="Warm Reminder"/><node text="Privacy Policy"/><node text="Disagree and quit" clickable="true"/><node text="agree with" clickable="true"/></hierarchy>'
        target,reason=popup_handler.close_target(parse_ui(xml))
        self.assertEqual(target['label'],'Next')
        self.assertIn('新手引导',reason)
        without_guide=xml.replace('<node text="Click here to view the information"/>','').replace('<node text="Next" clickable="true"/>','')
        self.assertEqual(popup_handler.close_target(parse_ui(without_guide))[0]['label'],'agree with')
    def test_generic_next_is_not_tutorial(self):
        self.assertIsNone(popup_handler.close_target(parse_ui('<hierarchy><node text="Next" clickable="true"/></hierarchy>'))[0])
    def test_i_know_pager_guide_is_advanced_first(self):
        # 2026-10-27 实测：后续引导步骤按钮为 previous step / I know，遮罩拦截隐私弹窗点击。
        xml='<hierarchy><node text="skip" clickable="true"/><node text="Warm Reminder"/><node text="Privacy Policy"/><node text="Disagree and quit" clickable="true"/><node text="agree with" clickable="true"/><node text="previous step" clickable="true"/><node text="I know" clickable="true"/><node text="Click on the message to see all your notifications"/></hierarchy>'
        target,reason=popup_handler.close_target(parse_ui(xml))
        # 2026-11-10 实测：引导层同时出现跳过时优先点跳过，最快脱离遮挡。
        self.assertEqual(target['label'],'skip')
        self.assertIn('新手引导',reason)
        without_guide=xml.replace('<node text="previous step" clickable="true"/>','').replace('<node text="I know" clickable="true"/>','').replace('<node text="skip" clickable="true"/>','')
        self.assertEqual(popup_handler.close_target(parse_ui(without_guide))[0]['label'],'agree with')
    def test_tutorial_skip_preferred_over_next(self):
        # 2026-11-10 真机实测：门店页引导同时出现「跳过」和「下一步」，此前要求按钮唯一导致卡死。
        xml='<hierarchy><node text="点击，可返回门店页面"/><node text="跳过" clickable="true"/><node text="下一步" clickable="true"/></hierarchy>'
        target,reason=popup_handler.close_target(parse_ui(xml))
        self.assertEqual(target['label'],'跳过')
        self.assertIn('新手引导',reason)
    def test_guide_pair_skipped_without_whitelisted_text(self):
        # 未收录的引导文案：跳过+下一步并存即视为引导遮挡，任何页面都先跳过。
        xml='<hierarchy><node text="这是全新的功能介绍哦"/><node text="跳过" clickable="true"/><node text="下一步" clickable="true"/></hierarchy>'
        target,reason=popup_handler.close_target(parse_ui(xml))
        self.assertEqual(target['label'],'跳过')
    def test_guide_pair_not_claimed_without_skip(self):
        # 只有下一步的业务页面（无跳过、无引导文案）不能被当作引导关闭。
        xml='<hierarchy><node text="这是全新的功能介绍哦"/><node text="下一步" clickable="true"/></hierarchy>'
        self.assertIsNone(popup_handler.close_target(parse_ui(xml))[0])
        self.assertIsNone(popup_handler.dismiss_target(parse_ui(xml))[0])
    def test_dismiss_target_covers_permission_and_guide_not_business_cancel(self):
        permission='<hierarchy><node text="需要相机权限才能拍摄照片"/><node text="允许" clickable="true"/><node text="拒绝" clickable="true"/></hierarchy>'
        self.assertIsNotNone(popup_handler.dismiss_target(parse_ui(permission))[0])
        business='<hierarchy><node text="确认删除该设备？"/><node text="取消" clickable="true"/><node text="确定" clickable="true"/></hierarchy>'
        self.assertIsNone(popup_handler.dismiss_target(parse_ui(business))[0])

class PopupRecoveryTests(unittest.TestCase):
    def test_stuck_close_returns_and_continues_other_pages(self):
        class Driver(FakeDriver):
            def __init__(self):super().__init__();self.state='popup'
            def source(self):return POPUP if self.state=='popup' else super().source()
            def __call__(self,method,path,data=None):
                if path.endswith('/click') and self.state=='popup':return None
                return super().__call__(method,path,data)
        d=Driver();exp=Explorer(d,'s','Android',lambda *a:None,lambda *a:None)
        with patch('automation.time.sleep'):
            result=exp.explore({'max_actions':10,'popup_wait_seconds':0})
        self.assertTrue(any(i.get('type')=='popup_recovered' for i in result['issues']))
        self.assertTrue(any(e['action']=='blocked_page_recovery' for e in result['transitions']))
        self.assertGreater(len(result['pages']),0)
        self.assertIn('详情',d.clicked)

class PermissionDefaultTests(unittest.TestCase):
    PERMISSION=('<hierarchy><node class="android.app.Dialog" package="com.android.permissioncontroller">'
                '<node text="允许应用访问位置信息？"/>'
                '<node text="拒绝" clickable="true"/><node text="仅在使用中允许" clickable="true"/><node text="允许" clickable="true"/>'
                '</node></hierarchy>')
    def test_system_permission_dialog_defaults_to_grant(self):
        target,reason=popup_handler.permission_target(parse_ui(self.PERMISSION))
        self.assertEqual(target['label'],'允许');self.assertIn('允许',reason)
    def test_explicit_denial_request_taps_deny(self):
        target,_=popup_handler.permission_target(parse_ui(self.PERMISSION),deny=True)
        self.assertEqual(target['label'],'拒绝')
    def test_textual_permission_dialog_defaults_to_grant(self):
        xml='<hierarchy><node text="需要相机权限才能拍摄照片"/><node text="取消" clickable="true"/><node text="允许" clickable="true"/></hierarchy>'
        self.assertEqual(popup_handler.permission_target(parse_ui(xml))[0]['label'],'允许')
    def test_non_permission_dialog_is_not_claimed(self):
        xml='<hierarchy><node text="即将前往微信打开此文章，使用完整服务。"/><node text="Cancel" clickable="true"/><node text="Proceed" clickable="true"/></hierarchy>'
        self.assertIsNone(popup_handler.permission_target(parse_ui(xml))[0])
        self.assertEqual(popup_handler.close_target(parse_ui(xml))[0]['label'],'Cancel')
    def test_permission_dialog_without_allow_option_stays_unclaimed(self):
        xml='<hierarchy><node text="存储权限说明"/><node text="知道了" clickable="true"/></hierarchy>'
        self.assertIsNone(popup_handler.permission_target(parse_ui(xml))[0])
