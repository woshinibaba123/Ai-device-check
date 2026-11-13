import io
import unittest
from unittest.mock import Mock, patch
from PIL import Image
import visual_flow


class VisualFlowTests(unittest.TestCase):
    def test_typed_store_does_not_authorize_wrong_store_submit(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        explorer._repair_selection={'store_id':'OLD','store_label':'旧门店','store_query':'目标门店','robot_count':0}
        cfg={'goal':'提交目标门店报修','preset_id':'repair-full','data':{'store':'目标门店'}}
        decision={'action':'tap','label':'提交','center_normalized':[.5,.8],'observations':[{'id':'step_5','status':'observed','evidence':'搜索框文字已是目标门店所以已选择'}]}
        with patch.object(visual_flow,'suppress_debug_overlay'),patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':decision}):
            cls.return_value.screenshot.return_value=output.getvalue()
            value=visual_flow._step(explorer,cfg,[],60)
            self.assertEqual(value['action'],'wait');self.assertEqual(value['observations'],[])
            cls.return_value.tap.assert_not_called()

    def test_committed_store_and_robot_have_separate_proof(self):
        explorer=Mock();explorer._repair_selection={'store_id':'TARGET','store_label':'目标门店','store_query':'','robot_count':0,'robot_selected':False}
        observed=visual_flow.repair_selection_observation(explorer,{'preset_id':'repair-full','data':{'store':'目标门店'}})
        self.assertTrue(observed['store_target_committed'])
        self.assertFalse(observed['search_text_matches_target'])
        self.assertFalse(observed['robot_selected'])

    def test_scroll_down_without_center_returns_to_upper_content(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'scroll','scroll_direction':'down'}}):
            cls.return_value.screenshot.return_value=output.getvalue()
            visual_flow._step(explorer,{'goal':'返回首页顶部'},[],60)
            cls.return_value.run.assert_called_once_with(['shell','input','swipe','540','720','540','1800','600'])
            cls.return_value.scroll.assert_not_called()

    def test_debug_target_rejected_before_click(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'tap','label':'vConsole底部Hide按钮'}}):
            cls.return_value.screenshot.return_value=output.getvalue()
            with self.assertRaisesRegex(ValueError,'调试浮层'):visual_flow._step(explorer,{'goal':'查看地图'},[],60)
            cls.return_value.tap.assert_not_called()

    def test_done_with_new_evidence_records_before_completion(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        observation={'id':'step_1','status':'observed','evidence':'当前首页可见报修、附近门店和学习中心'}
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'done','observations':[observation]}}):
            cls.return_value.screenshot.return_value=output.getvalue()
            value=visual_flow._step(explorer,{'goal':'核对首页','workflow_coverage':[{'id':'step_1','status':'pending'}]},[],60)
            self.assertEqual(value['action'],'wait')
            self.assertEqual(value['observations'],[observation])
            cls.return_value.tap.assert_not_called()

    def test_page_arrow_back_uses_tap(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        value={'action':'back','label':'左上角返回箭头','center_normalized':[.1,.1]}
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':value}):
            cls.return_value.screenshot.return_value=output.getvalue()
            result=visual_flow._step(explorer,{'goal':'返回原入口'},[],60)
            cls.return_value.tap.assert_called_once()
            self.assertEqual(result['action'],'tap')
            cls.return_value.run.assert_not_called()

    def test_third_identical_tap_is_blocked_before_dispatch(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        history=[{'action':'tap','label':'目标门店卡片'},{'action':'tap','label':'目标门店卡片'}]
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'tap','label':'目标门店卡片'}}):
            cls.return_value.screenshot.return_value=output.getvalue()
            with self.assertRaisesRegex(ValueError,'第三次'):visual_flow._step(explorer,{'goal':'进入门店列表'},history,60)
            cls.return_value.tap.assert_not_called()

    def test_coverage_is_required_before_action_and_requested_as_schema(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        config={'goal':'检查语言','workflow_coverage':[{'id':'step_1','status':'pending'}]}
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'tap','label':'语言','center_normalized':[.5,.4]}}) as query:
            cls.return_value.screenshot.return_value=output.getvalue()
            with self.assertRaisesRegex(ValueError,'observations'):visual_flow._step(explorer,config,[],60)
            self.assertIn('observations',query.call_args.args[1])
            cls.return_value.tap.assert_not_called()

    def test_structured_observations_reach_ledger(self):
        import workflow_coverage
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        rows=workflow_coverage.requirements('1. 检查根导航')
        observation={'id':'step_1','status':'observed','evidence':'截图根导航显示ホーム、店舗、ニュース、設定'}
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'wait','observations':[observation]}}):
            cls.return_value.screenshot.return_value=output.getvalue()
            value=visual_flow._step(explorer,{'goal':'检查语言','workflow_coverage':rows},[],60)
            workflow_coverage.record(rows,value['observations'],1)
        self.assertEqual(rows[0]['status'],'observed')

    def test_changed_scene_combines_verification_and_location(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow,'frame_matches',side_effect=[True,False]),patch.object(visual_flow.midscene_bridge,'query',side_effect=[{'value':{'action':'tap','label':'English','center_normalized':[.5,.4]}},{'value':{'safe':True,'center_normalized':[.3,.5]}}]) as query:
            cls.return_value.screenshot.return_value=output.getvalue()
            visual_flow._step(explorer,{'goal':'切换英语'},[],60)
            self.assertEqual(query.call_count,2)
            cls.return_value.tap.assert_called_once_with(324,1200)

    def test_known_navigation_reuses_exact_scene_without_model(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'tap','label':'通用设置','center_normalized':[.5,.4]}}) as query:
            cls.return_value.screenshot.return_value=output.getvalue()
            visual_flow._step(explorer,{'goal':'切换语言'},[],60)
            visual_flow._step(explorer,{'goal':'切换语言'},[{'label':'返回'}],60)
            query.assert_called_once()
            self.assertEqual(cls.return_value.tap.call_count,2)
            visual_flow._step(explorer,{'goal':'切换语言'},[{'label':'通用设置'}],60)
            self.assertEqual(query.call_count,2)

    def test_business_and_language_changes_are_never_cached(self):
        for label in ('保存','日本語','退出登录','启动任务'):
            self.assertFalse(visual_flow.reusable_navigation({'action':'tap','label':label}))

    def test_safe_claim_without_coordinates_never_clicks(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow,'frame_matches',side_effect=[True,False]),patch.object(visual_flow.midscene_bridge,'query',side_effect=[{'value':{'action':'tap','label':'English','center_normalized':[.5,.4]}},{'value':{'safe':True}}]):
            cls.return_value.screenshot.return_value=output.getvalue()
            self.assertEqual(visual_flow._step(explorer,{'goal':'切换英语'},[],60)['action'],'reobserve')
            cls.return_value.tap.assert_not_called()

    def test_navigation_cache_invalidated_by_scene_or_coverage_change(self):
        a=io.BytesIO();b=io.BytesIO()
        Image.new('RGB',(1080,2400),'black').save(a,format='PNG')
        Image.new('RGB',(1080,2400),'white').save(b,format='PNG')
        config={'goal':'切换语言','workflow_coverage':[{'id':'日语','status':'pending'}]}
        original=visual_flow.navigation_key(a.getvalue(),config)
        self.assertNotEqual(original,visual_flow.navigation_key(b.getvalue(),config))
        self.assertNotEqual(original,visual_flow.navigation_key(a.getvalue(),{**config,'workflow_coverage':[{'id':'日语','status':'observed'}]}))

    def test_navigation_cache_tolerates_small_rendering_noise(self):
        from PIL import ImageDraw
        a=io.BytesIO();b=io.BytesIO();image=Image.new('RGB',(1080,2400),'black')
        image.save(a,format='PNG');ImageDraw.Draw(image).rectangle((20,200,25,205),fill='white');image.save(b,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as cls,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'tap','label':'通用设置','center_normalized':[.5,.4]}}) as query:
            cls.return_value.screenshot.return_value=a.getvalue()
            visual_flow._step(explorer,{'goal':'切换语言'},[],60)
            cls.return_value.screenshot.return_value=b.getvalue()
            visual_flow._step(explorer,{'goal':'切换语言'},[{'action':'back'}],60)
            query.assert_called_once()

    def test_stable_decision_coordinates_need_only_one_model_call(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as cls, patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'tap','label':'English','center_normalized':[.5,.4]}}) as query:
            cls.return_value.screenshot.return_value=output.getvalue()
            visual_flow._step(explorer,{'goal':'切换英语'},[],60)
            query.assert_called_once()
            cls.return_value.tap.assert_called_once_with(540,960)

    def test_changed_decision_frame_requires_fresh_location(self):
        output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as cls, patch.object(visual_flow,'frame_matches',side_effect=[False,True]), patch.object(visual_flow.midscene_bridge,'query',side_effect=[{'value':{'action':'tap','label':'English','center_normalized':[.5,.4]}},{'value':{'center':[200,800]}}]) as query:
            cls.return_value.screenshot.return_value=output.getvalue()
            visual_flow._step(explorer,{'goal':'切换英语'},[],60)
            self.assertEqual(query.call_count,2)
            cls.return_value.tap.assert_called_once_with(200,800)

    def test_changed_frame_redecides_without_replaying_click(self):
        explorer = Mock()
        with patch.object(visual_flow, '_step', side_effect=[{'action': 'reobserve'}, {'action': 'tap', 'label': '任务'}]) as decide:
            result = visual_flow.step(explorer, {'goal': '继续'}, [], 60)
        self.assertEqual(result['label'], '任务')
        self.assertEqual(decide.call_count, 2)

    def test_continuously_changing_frame_has_bounded_retries(self):
        with patch.object(visual_flow, '_step', return_value={'action': 'reobserve'}) as decide:
            with self.assertRaisesRegex(ValueError, '三次'):
                visual_flow.step(Mock(), {'goal': '继续'}, [], 60)
        self.assertEqual(decide.call_count, 3)

    def test_stale_coordinates_never_reach_transport(self):
        output = io.BytesIO()
        Image.new('RGB', (1080, 2400)).save(output, format='PNG')
        explorer = Mock()
        explorer.stopped.return_value = False
        with patch.object(visual_flow, 'AndroidVisual') as cls, patch.object(visual_flow, 'frame_matches', return_value=False), patch.object(visual_flow.midscene_bridge, 'query', side_effect=[{'value': {'action': 'tap', 'label': '任务'}}, {'value': {'center': [500, 2300]}}, {'value': {'safe': False}}]):
            cls.return_value.screenshot.return_value = output.getvalue()
            result = visual_flow._step(explorer, {'goal': '点击任务'}, [], 60)
            cls.return_value.tap.assert_not_called()
        self.assertEqual(result['action'], 'reobserve')

class CoordinateRecoveryTests(unittest.TestCase):
    def test_parse_failure_reobserves_without_replaying_action(self):
        with patch.object(visual_flow, '_step', side_effect=[ValueError('诊断=sdk_coordinate_parse'), {'action': 'wait'}]) as decide:
            self.assertEqual(visual_flow.step(Mock(), {'goal': '继续'}, [], 60)['action'], 'wait')
            self.assertEqual(decide.call_count, 2)

    def test_unrelated_failure_is_not_retried(self):
        with patch.object(visual_flow, '_step', side_effect=ValueError('提交结果不明')) as decide:
            with self.assertRaisesRegex(ValueError, '提交结果不明'):
                visual_flow.step(Mock(), {'goal': '继续'}, [], 60)
            self.assertEqual(decide.call_count, 1)

class MissingTargetRecoveryTests(unittest.TestCase):
    def test_read_only_not_found_reobserves_without_replaying_mutation(self):
        explorer=Mock()
        with patch.object(visual_flow,'_step',side_effect=[ValueError('Midscene 未找到目标；诊断=sdk_error'),{'action':'wait'}]) as query:
            result=visual_flow.step(explorer,{'goal':'查看页面'},[],60)
        self.assertEqual(result['action'],'wait')
        self.assertEqual(query.call_count,2)

class BlockedSubstepNavigationTests(unittest.TestCase):
    def test_failed_header_back_uses_system_back_once(self):
        explorer=Mock();explorer.stopped.return_value=False
        with patch.object(visual_flow,'AndroidVisual') as transport,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'blocked','reason':'多次返回未生效，无法退出该页'}}):
            output=io.BytesIO();Image.new('RGB',(1080,2400)).save(output,format='PNG')
            transport.return_value.screenshot.return_value=output.getvalue()
            result=visual_flow._step(explorer,{'goal':'继续后续步骤'},[],60)
            transport.return_value.run.assert_called_once_with(['shell','input','keyevent','4'])
        self.assertEqual(result['action'],'back')
