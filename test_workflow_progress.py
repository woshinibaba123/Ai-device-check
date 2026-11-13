import unittest
from unittest.mock import patch
import workflow_progress as progress
import ai_operator as op
from test_ai_operator import Device


def step(label, action='tap', route='/form', **kw):
    return dict(label=label, action=action, route=route, result='executed', **kw)


class ProgressTests(unittest.TestCase):
    def test_failed_schedule_continues_independent_check_without_reopening(self):
        e=Device();e.prefer_webview=True
        form={'route':'/#/map/addScheduleTask','text':'任务名称','controls':[{'id':'name','text':'任务名称','editable':True}]}
        home={'route':'/','text':'机器人首页','controls':[{'id':str(i),'text':label,'editable':False}
            for i,label in enumerate(('今日','昨日','七日','机器人名称','清洁记录','排班列表','清洁模式','任务报告设置'))]}
        current=[form];actions=[]
        def observe(*args):
            page=current[0]
            return page,{'name':('web',{})},'<hierarchy/>',page['text']
        def execute(device,decision,*args):
            actions.append(decision)
            if decision['action']=='input':
                current[0]=home
                raise op.hybrid_webview.H5InputMismatch('mismatch')
        validate=op.validate
        with patch.object(op,'validate',side_effect=lambda cfg:dict(validate(cfg),seconds=30)),patch.object(op,'observe',side_effect=observe),patch.object(op,'execute',side_effect=execute),patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,{'goal':'排班列表、清洁记录、清洁模式；单项受阻后继续独立检查','share_page':True,'seconds':30,'fast_mode':False,'data':{'name':'test'}},
                ask=lambda *a,**k:{'action':'input','target':'name','data_key':'name'},
                clock=lambda:31 if len(actions)>1 else 0)
        self.assertEqual([a['action'] for a in actions],['input','tap'])
        self.assertEqual(actions[-1]['target'],'4')
        self.assertEqual(actions[-1]['origin'],'local_independent_check')
        self.assertEqual(result['blocked_items'][0]['module'],'排班列表')
        self.assertTrue(home['controls'][5]['blocked'])

    def test_independent_recovery_does_not_guess_or_repeat_checks(self):
        labels=('今日','昨日','七日','机器人名称','清洁记录','排班列表','清洁模式')
        page={'controls':[{'id':str(i),'text':s} for i,s in enumerate(labels)]}
        items=[{'route':'/#/map/addScheduleTask'}]
        goal='排班列表、清洁记录、清洁模式；受阻后继续独立检查'
        decision=op.local_independent_step(goal,page,[step('清洁记录')],items)
        self.assertEqual(decision['target'],'6')
        self.assertIsNone(op.local_independent_step(goal,page,[step('清洁记录'),step('清洁模式')],items))
        self.assertIsNone(op.local_independent_step('仅检查排班列表',page,[],items))
        self.assertIsNone(op.local_independent_step(goal,{'controls':[{'id':'x','text':'清洁记录'}]},[],items))
        page['controls'].append({'id':'duplicate','text':'清洁记录'})
        self.assertEqual(op.local_independent_step(goal,page,[],items)['target'],'6')

    def test_long_loop_ignores_volatile_target_ids(self):
        block=[step(x) for x in ('区域','新建','列表','区域1','确认','返回')]
        self.assertEqual(progress.cycle_length(block*2,step('区域')),6)
        self.assertEqual(progress.cycle_length(block*2,step('区域',route='/other')),0)

    def test_assertions_and_rejected_actions_do_not_hide_cycle(self):
        history=[step('A'),step('B')]*2+[dict(action='tap',result='page_changed_not_executed')]
        self.assertEqual(progress.cycle_length(history,step('A')),2)
        self.assertEqual(progress.cycle_length([step('刷新')]*2,step('刷新')),0)

    def test_field_state_never_contains_value(self):
        self.assertEqual(progress.field_state({'value':'private@example.com'}),{'filled':True})
        self.assertEqual(progress.field_state({'value':''}),{'filled':False})
        self.assertEqual(progress.field_state({'value':'secret','secure':True}),{})

    def test_save_scoped_to_form_and_exit(self):
        history=[step('保存',round=1)]
        self.assertIsNotNone(progress.pending_save(history,'/form'))
        self.assertIsNone(progress.pending_save(history,'/other'))
        self.assertIsNone(progress.pending_save(history+[step('',action='back')],'/form'))
        self.assertIsNone(progress.pending_save([step('保存',origin='local_region_save')],'/form'))

    def test_save_is_observed_twice_without_model_refill(self):
        e=Device();e.prefer_webview=True
        controls=[{'id':'w0','text':'保存','editable':False}, {'id':'w1','text':'任务名称','editable':True,'filled':True}]
        page=({'route':'/form','text':'表单','controls':controls},{'w0':('web',{'text':'保存','tag':'button'})},'<hierarchy/>','fixed')
        with patch.object(op,'observe',return_value=page),patch.object(op,'execute') as execute,patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,{'goal':'填写表单并保存','share_page':True,'seconds':30,'fast_mode':False,'checkpoints':['结果']},ask=lambda *a,**k:{'action':'tap','target':'w0'})
        self.assertEqual([c.args[1]['action'] for c in execute.call_args_list],['tap','wait','wait'])
        self.assertEqual(result['steps'][0]['save_outcome'],'unconfirmed')
        self.assertEqual(len(result['blocked_items']),1)

    def test_region_one_available_row_not_all_select_or_toggle(self):
        goal='列表选择，不重复点击同一区域'
        labels=['取消','确认','区域','全选','区域1','无文字图标 内嵌图片，位置306,285']
        page={'route':'/#/map/areaSetting/areaSelect','controls':[dict(id='w'+str(i),text=t) for i,t in enumerate(labels)]}
        history=[step('列表选择')]
        decision=op.local_region_list_step(goal,page,history)
        self.assertEqual(decision['target'],'w5')
        history.append(step(labels[-1],origin='local_region_select',region_row='区域1'))
        # Reassigned IDs must not cause a second toggle.
        page['controls'][-1]['id']='w99'
        self.assertEqual(op.local_region_list_step(goal,page,history)['target'],'w1')

    def test_canvas_region_list_does_not_call_visual_model(self):
        from types import SimpleNamespace
        e=SimpleNamespace(platform='Android',device_id='phone',secrets=[])
        snapshot={'path':'/#/map/areaSetting/areaSelect','text':'列表选择','visual_regions':[{'kind':'canvas'}],
                  'controls':[{'tag':'button','text':'列表选择'},{'tag':'input','text':'请选择','filled':True}]}
        with patch.object(op.hybrid_webview,'WebView') as web,patch('h5_visual.describe_canvas') as describe:
            web.return_value.__enter__.return_value.snapshot.return_value=snapshot
            page,*_=op.observe_webview(e)
        describe.assert_not_called()
        self.assertTrue(page['controls'][1]['filled'])
        self.assertNotIn('value',page['controls'][1])

    def test_visual_loop_is_rejected_before_device_tap(self):
        import io
        from PIL import Image
        from unittest.mock import Mock
        import visual_flow
        out=io.BytesIO();Image.new('RGB',(108,240)).save(out,format='PNG')
        explorer=Mock();explorer.stopped.return_value=False
        history=[step(x,route='') for x in ('区域','列表','确认')]*2
        decision={'action':'tap','label':'区域','center_normalized':[.5,.5]}
        with patch.object(visual_flow,'suppress_debug_overlay'),patch.object(visual_flow,'AndroidVisual') as transport,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':decision}):
            transport.return_value.screenshot.return_value=out.getvalue()
            with self.assertRaisesRegex(ValueError,'流程重复'):
                visual_flow._step(explorer,{'goal':'检查表单'},history,30)
            transport.return_value.tap.assert_not_called()

    def test_visual_save_cannot_restart_form_on_same_scene(self):
        import io
        from PIL import Image
        from unittest.mock import Mock
        import visual_flow
        out=io.BytesIO();Image.new('RGB',(108,240)).save(out,format='PNG');frame=out.getvalue()
        explorer=Mock();explorer.stopped.return_value=False
        scene=visual_flow.navigation_key(frame,{'goal':'scene-identity'})
        history=[step('保存',route='',scene=scene,round=1)]
        decision={'action':'input','label':'名称','data_key':'name','center_normalized':[.5,.5]}
        with patch.object(visual_flow,'suppress_debug_overlay'),patch.object(visual_flow,'AndroidVisual') as transport,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':decision}):
            transport.return_value.screenshot.return_value=frame
            with self.assertRaisesRegex(ValueError,'保存结果尚未确认'):
                visual_flow._step(explorer,{'goal':'检查表单','data':{'name':'test'}},history,30)
            transport.return_value.tap.assert_not_called()

    def test_visual_wait_is_bounded_even_without_save(self):
        import io
        from PIL import Image
        from unittest.mock import Mock
        import visual_flow
        out=io.BytesIO();Image.new('RGB',(108,240)).save(out,format='PNG');frame=out.getvalue()
        explorer=Mock();explorer.stopped.return_value=False
        scene=visual_flow.navigation_key(frame,{'goal':'scene-identity'})
        history=[step('',action='wait',route='',scene=scene)]*3
        with patch.object(visual_flow,'suppress_debug_overlay'),patch.object(visual_flow,'AndroidVisual') as transport,patch.object(visual_flow.midscene_bridge,'query',return_value={'value':{'action':'wait'}}):
            transport.return_value.screenshot.return_value=frame
            with self.assertRaisesRegex(ValueError,'连续等待三次'):
                visual_flow._step(explorer,{'goal':'等待加载'},history,30)
            transport.return_value.tap.assert_not_called()

    def test_existing_h5_value_is_not_cleared_and_retyped(self):
        from unittest.mock import Mock
        import hybrid_webview
        import automation
        e=Mock();e.base='/session/test';e.call.return_value={'count':1,'element':{automation.ELEMENT:'x'},'editable':True,'value':'already set'}
        result=hybrid_webview.WebView(e).perform({'action':'web_input','value':'#name','by':'css','text':'already set'})
        self.assertTrue(result['input_unchanged'])
        self.assertEqual(e.call.call_count,1)

    def test_existing_native_value_is_not_retyped(self):
        from test_ai_operator import node
        e=Device()
        op.execute(e,{'action':'input','target':'n0','data_key':'name'},
                   {'n0':('native',node('名称',hint='名称',editable=True,value='already set'))},{'name':'already set'})
        self.assertEqual(e.calls,[])

    def test_input_mismatch_records_issue_and_continues_to_next_action(self):
        import hybrid_webview
        e=Device();e.prefer_webview=True
        controls=[{'id':'w0','text':'任务名称','editable':True}]
        page=({'route':'/form','text':'表单','controls':controls},{'w0':('web',{'text':'任务名称','tag':'input'})},'<hierarchy/>','fixed')
        answers=iter([{'action':'input','target':'w0','data_key':'name'}, {'action':'tap','target':'w0'}, {'action':'blocked','reason':'后续已检查'}])
        def execute(*args):
            if args[1]['action']=='input':raise hybrid_webview.H5InputMismatch('H5 输入内容与预期不一致')
        with patch.object(op,'observe',return_value=page),patch.object(op,'execute',side_effect=execute) as runner,patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,{'goal':'填写并检查表单','share_page':True,'fast_mode':False,'data':{'name':'test'}},ask=lambda *a,**k:next(answers))
        self.assertFalse(result['steps'][0]['input_verified'])
        self.assertEqual(result['blocked_items'][0]['kind'],'input_mismatch')
        self.assertEqual(runner.call_args_list[1].args[1]['action'],'tap')

    def test_mismatch_does_not_retry_input_or_submit_dependent_form(self):
        import hybrid_webview
        for followup in ({'action':'input','target':'w0','data_key':'name'}, {'action':'tap','target':'w1'}):
            with self.subTest(followup=followup):
                e=Device();e.prefer_webview=True
                controls=[{'id':'w0','text':'任务名称','editable':True},{'id':'w1','text':'保存','editable':False}]
                page=({'route':'/form','text':'表单','controls':controls},{'w0':('web',{'text':'任务名称','tag':'input'}),'w1':('web',{'text':'保存','tag':'button'})},'<hierarchy/>','fixed')
                answers=iter([{'action':'input','target':'w0','data_key':'name'},followup,{'action':'blocked','reason':'已继续独立检查'}])
                def execute(*args):
                    if args[1]['action']=='input':raise hybrid_webview.H5InputMismatch('H5 输入内容与预期不一致')
                with patch.object(op,'observe',return_value=page),patch.object(op,'execute',side_effect=execute) as runner,patch.object(op.cancellation.Control,'sleep'):
                    op.run(e,{'goal':'填写并检查表单','share_page':True,'fast_mode':False,'data':{'name':'test'}},ask=lambda *a,**k:next(answers))
                self.assertEqual([c.args[1]['action'] for c in runner.call_args_list],['input','back'])
