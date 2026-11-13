import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import action_knowledge as ak
import ai_operator as op
from test_ai_operator import Device,node


def page(label, ident='real', selected=False):
    return {'route':'/page','text':label,'controls':[{'id':ident,'text':label,'selected':selected,'checked':False,'editable':False,'blocked':False}]}


class KnowledgeTests(unittest.TestCase):
    def test_verified_navigation_reusable_before_whole_run_finishes(self):
        before=page('排班列表')
        self.k.observe(before,self.decision,self.b,[],label='排班列表')
        replay=ak.Knowledge('app-v1','测试某个导航',path=self.path).lookup(page('排班列表','new-id'),[])
        self.assertEqual(replay['target'],'new-id')

    def test_stable_navigation_survives_history_change_across_runs(self):
        before=page('排班列表')
        self.k.observe(before,self.decision,self.b,[],label='排班列表')
        replay=ak.Knowledge('app-v1','测试某个导航',path=self.path)
        result=replay.lookup(page('排班列表','fresh'),[{'action':'tap','label':'清洁记录','result':'executed'}])
        self.assertEqual(result['target'],'fresh')
        self.assertEqual(replay.last_lookup_reason,'stable_navigation_hit')
        self.assertIsNone(replay.lookup(page('排班列表',selected=True),[]))

    def test_history_fallback_rejects_repeat_and_conflicting_destinations(self):
        before=page('排班列表')
        self.k.observe(before,self.decision,self.b,[],label='排班列表')
        history=[{'action':'tap','label':'排班列表','result':'executed'}]
        self.assertIsNone(self.k.lookup(before,history))
        self.assertEqual(self.k.last_lookup_reason,'repeat_target_rejected')
        self.k.observe(before,self.decision,page('另一个页面'),[{'action':'back','result':'executed'}],label='排班列表')
        self.assertIsNone(self.k.lookup(before,[{'action':'tap','label':'我的','result':'executed'}]))
        self.assertEqual(self.k.last_lookup_reason,'conflicting_transitions')

    def test_history_fallback_never_replays_promoted_save(self):
        before=page('保存')
        self.k.observe(before,self.decision,self.b,[],label='保存')
        self.k.promote(self.b,[],['详情'])
        self.assertIsNone(self.k.lookup(before,[{'action':'back','result':'executed'}]))

    def test_form_navigation_enabled_without_full_completion(self):
        for label in ('新建任务','清洁区域','新建区域','列表选择','请选择【字段：任务类型】'):
            before=page(label)
            self.assertTrue(self.k.observe(before,self.decision,self.b,[],label=label))
            self.assertIsNotNone(self.k.lookup(before,[]))
        self.k.observe(page('请选择'),self.decision,self.b,[],label='请选择')
        self.assertIsNone(self.k.lookup(page('请选择'),[]))
        self.assertEqual(self.k.last_lookup_reason,'step_not_enabled')

    def test_field_identity_and_icon_noise(self):
        self.assertNotEqual(ak.page_key(page('请选择【字段：任务类型】')),ak.page_key(page('请选择【字段：清洁时间】')))
        self.assertEqual(ak.page_key(page('无文字图标 内嵌图片，位置301,-1')),ak.page_key(page('无文字图标 内嵌图片，位置302,0')))
        self.assertNotEqual(ak.page_key(page('保存')),ak.page_key(page('确认')))

    def test_existing_navigation_migrates_but_invalidated_rule_stays_disabled(self):
        before=page('新建区域')
        self.k.observe(before,self.decision,self.b,[],label='新建区域')
        with self.k.connect() as db:db.execute('UPDATE transitions SET enabled=0')
        replay=ak.Knowledge('app-v1','测试某个导航',path=self.path)
        hit=replay.lookup(before,[])
        self.assertIsNotNone(hit)
        replay.invalidate(hit['knowledge_key'])
        replay=ak.Knowledge('app-v1','测试某个导航',path=self.path)
        self.assertIsNone(replay.lookup(before,[]))

    def test_region_confirmation_blocks_exact_and_history_cache(self):
        history=[{'action':'tap','label':label,'result':'executed'} for label in ('新建区域','列表选择','区域18','确认')]
        before=page('列表选择')
        self.k.observe(before,self.decision,self.b,history,label='列表选择')
        self.assertIsNone(self.k.lookup(before,history))
        self.assertEqual(self.k.last_lookup_reason,'workflow_stage_completed')
        self.assertTrue(ak.region_selection_confirmed(history))
        self.assertFalse(ak.region_selection_confirmed(history+[{'label':'保存','result':'executed'}]))
        self.assertFalse(ak.region_selection_confirmed(history+[{'label':'新建区域','result':'executed'}]))

    def test_region_save_only_on_outer_page_and_explicit_goal(self):
        history=[{'action':'tap','label':label,'result':'executed'} for label in ('新建区域','列表选择','区域18','确认')]
        outer={'controls':[{'id':'list','text':'列表选择'},{'id':'save','text':'保存'}]}
        self.assertEqual(op.local_region_save_step('列表选择 → 确认 → 保存',outer,history)['target'],'save')
        self.assertIsNone(op.local_region_save_step('查看区域',outer,history))
        self.assertIsNone(op.local_region_save_step('列表选择确认保存',{'controls':outer['controls']+[{'id':'ok','text':'确认'}]},history))
        self.assertIsNone(op.local_region_save_step('列表选择确认保存',outer,history[:2]))

    def test_submit_not_enabled_by_navigation_learning(self):
        self.k.observe(page('保存'),self.decision,self.b,[],label='保存')
        self.assertIsNone(self.k.lookup(page('保存'),[]))

    def test_legacy_time_limit_no_longer_applies(self):
        cfg=op.validate({'goal':'检查页面','share_page':True,'seconds':600})
        self.assertEqual(cfg['seconds'],float('inf'))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'knowledge.sqlite3'
        self.k=ak.Knowledge('app-v1','测试某个导航',path=self.path)
        self.a=page('入口');self.b=page('详情')
        self.decision={'action':'tap','origin':'ai'}
    def learn(self):
        self.k.observe(self.a,self.decision,self.b,[],label='入口')
        self.k.promote(self.b,[{'action':'tap','label':'入口','result':'executed'}],['详情'])
    def test_unverified_trace_cannot_be_replayed(self):
        self.k.observe(self.a,self.decision,self.b,[],label='入口')
        self.assertIsNone(self.k.lookup(self.a,[]))
        self.assertEqual(self.k.counts(),{'enabled':0,'recorded':1})
    def test_success_promotes_and_rebinds_current_id(self):
        self.learn()
        decision=self.k.lookup(page('入口','new-device-id'),[])
        self.assertEqual(decision['target'],'new-device-id')
        self.assertEqual(decision['origin'],'knowledge')
    def test_goal_and_app_version_are_isolated(self):
        self.learn()
        for scope,goal in [('app-v2','测试某个导航'),('app-v1','另一个目标')]:
            self.assertIsNone(ak.Knowledge(scope,goal,path=self.path).lookup(self.a,[]))
    def test_navigation_prefix_does_not_merge_different_remaining_goals(self):
        first='进入门店列表，搜索上海擎朗研发部，查看详情'
        second='进入门店列表，搜索上海擎朗研发部，下发呼叫任务'
        self.assertNotEqual(ak.goal_key(first),ak.goal_key(second))
        self.assertNotEqual(ak.goal_key('查看门店列表，然后查看详情'),ak.goal_key('查看门店列表，然后下发任务'))

    def test_selected_state_and_history_are_part_of_match(self):
        self.learn()
        self.assertIsNone(self.k.lookup(page('入口',selected=True),[]))
        self.assertIsNone(self.k.lookup(self.a,[{'action':'back','label':'','result':'executed'}]))
    def test_changed_page_invalidates_rule(self):
        self.learn();decision=self.k.lookup(self.a,[])
        self.k.invalidate(decision['knowledge_key'])
        self.assertIsNone(self.k.lookup(self.a,[]))
    def test_tap_without_page_change_not_learned(self):
        self.assertFalse(self.k.observe(self.a,self.decision,self.a,[],label='入口'))
    def test_inputs_and_redacted_labels_not_learned(self):
        self.assertFalse(self.k.observe(self.a,{'action':'input'},self.b,[],label='字段'))
        self.assertFalse(self.k.observe(self.a,self.decision,self.b,[],label='[已隐藏]'))
    def test_completion_requires_quotes_still_visible(self):
        self.learn();steps=[{'action':'tap','label':'入口','result':'executed'}]
        self.assertEqual(self.k.completion(self.b,steps),['详情'])
        altered=dict(self.b,text='加载中')
        self.assertIsNone(self.k.completion(altered,steps))
    def test_goal_and_body_text_not_stored(self):
        self.a['text']='私人资料 PRIVATE_SECRET account@example.test'
        self.learn()
        with self.k.connect() as db:
            stored=json.dumps(db.execute('SELECT * FROM transitions').fetchall())+json.dumps(db.execute('SELECT * FROM events').fetchall())
        self.assertNotIn('PRIVATE_SECRET',stored)
        self.assertNotIn('account@example.test',stored)
        self.assertNotIn('测试某个导航',stored)
    def test_installed_identity_is_stable_and_changes_on_reinstall(self):
        cfg={'execution_mode':'installed','platform':'Android','installed_app_identity':{'version_code':'1','version_name':'1.0','last_update_time':'2026-11-10 12:00'}}
        first=ak.application_scope(cfg,'app')
        self.assertTrue(first)
        self.assertEqual(first,ak.application_scope(cfg,'app'))
        cfg['installed_app_identity']['last_update_time']='2026-11-10 13:00'
        self.assertEqual(first,ak.application_scope(cfg,'app'))

    def test_version_changes_with_source_and_artifact(self):
        root=Path(self.tmp.name);(root/'lib').mkdir();file=root/'lib/page.dart';file.write_text('one')
        cfg={'source':str(root),'entrypoint':'lib/main_eng.dart'}
        first=ak.application_scope(cfg,'app');file.write_text('two')
        self.assertEqual(first,ak.application_scope(cfg,'app'))
        self.assertTrue(ak.application_scope({},'app'))
        self.assertNotEqual(first,ak.application_scope(cfg,'other.app'))


class LoopKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'knowledge.sqlite3'
        self.cfg={'goal':'先打开目标页再进入详情','checkpoints':[],'share_page':True,'max_actions':5,'seconds':60}
        self.e=Device();self.index=0
        self.pages=['起点入口','下一页入口','完成页面']
        self.e.nodes=[node(self.pages[0])]
        self.mutations=[]
        self.e.call=self.call
        self.parser=patch.object(op.automation,'parse_ui',side_effect=lambda _:self.e.nodes);self.parser.start();self.addCleanup(self.parser.stop)
        self.sleep=patch.object(op.cancellation.Control,'sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
    def call(self,*args):
        self.mutations.append(args);self.index+=1;self.e.nodes=[node(self.pages[self.index])]
    def book(self):return ak.Knowledge('app-v1',self.cfg['goal'],path=self.path)
    def teach(self):
        responses=iter([{'action':'tap','target':'n0'},{'action':'tap','target':'n0'},{'action':'done'},{'satisfied':True,'evidence':['完成页面']}])
        return op.run(self.e,self.cfg,ask=lambda *a,**kw:next(responses),knowledge=self.book())
    def reset(self):
        self.index=0;self.e.nodes=[node(self.pages[0])];self.mutations=[]
    def test_second_run_uses_zero_model_requests_including_completion(self):
        first=self.teach();self.assertEqual(first['model_calls'],4)
        self.reset()
        def no_ai(*a,**kw):raise AssertionError('Knowledge replay must not call the model')
        second=op.run(self.e,self.cfg,ask=no_ai,knowledge=self.book())
        self.assertEqual(second['model_calls'],0)
        self.assertEqual(second['knowledge_hits'],3)
        self.assertEqual(second['termination'],'knowledge_goal_supported')
        self.assertEqual(len(self.mutations),2)
        self.assertEqual(second['status'],'review')
    def test_unexpected_after_page_disables_rule_and_asks_ai_without_reclick(self):
        self.teach();self.reset();self.pages[1]='意外页面'
        calls=[]
        def ask(*a,**kw):calls.append(1);return {'action':'blocked'}
        result=op.run(self.e,self.cfg,ask=ask,knowledge=self.book())
        self.assertEqual(len(self.mutations),1)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['knowledge_mismatches'],1)
        self.assertIsNone(self.book().lookup(op.observe(self.e)[0],[]))
    def test_failed_goal_keeps_new_rules_disabled(self):
        responses=iter([{'action':'tap','target':'n0'},{'action':'blocked'}])
        op.run(self.e,self.cfg,ask=lambda *a,**kw:next(responses),knowledge=self.book())
        self.assertEqual(self.book().counts()['enabled'],0)
        self.assertEqual(self.book().counts()['recorded'],1)


if __name__=='__main__':unittest.main()
