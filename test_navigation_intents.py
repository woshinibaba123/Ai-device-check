import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import navigation_intents as nav
import ai_fastpath
import action_knowledge as ak
import excel_ai
import excel_plan_cache
from test_action_knowledge import page
import test_excel_fast as fast_tests


class IntentTests(unittest.TestCase):
    def test_navigation_synonyms_share_goal(self):
        goals=['进入通用设置','打开通用设置页面','跳转到常规设置','前往通用设置界面','点击“通用设置”入口']
        self.assertEqual(len({ak.goal_key(g) for g in goals}),1)
        self.assertTrue(all(ai_fastpath.compile_goal(g) for g in goals))
    def test_source_page_synonyms_match_but_different_source_does_not(self):
        self.assertEqual(ak.goal_key('从首页进入通用设置'),ak.goal_key('从主页页面跳转到常规设置界面'))
        self.assertNotEqual(ak.goal_key('从首页进入通用设置'),ak.goal_key('从我的进入通用设置'))
    def test_multi_step_order_and_constraints_preserved(self):
        self.assertEqual(ak.goal_key('先进入我的，然后打开通用设置'),ak.goal_key('打开个人中心，再跳转到常规设置'))
        self.assertNotEqual(ak.goal_key('进入我的，进入通用设置'),ak.goal_key('进入通用设置，进入我的'))
        self.assertNotEqual(ak.goal_key('进入通用设置'),ak.goal_key('进入通用设置，返回首页'))
    def test_negative_and_write_instructions_never_normalized(self):
        for text in ('不要进入通用设置','进入通用设置并删除账号','如果失败再进入通用设置','等待进入通用设置','点击提交按钮'):
            self.assertIsNone(nav.parse(text))
            self.assertNotEqual(ak.goal_key(text),ak.goal_key('进入通用设置'))
    def test_destination_and_language_parameters_preserved(self):
        self.assertNotEqual(ak.goal_key('进入消息'),ak.goal_key('进入我的'))
        self.assertNotEqual(ak.goal_key('切换成法语'),ak.goal_key('切换成英语'))
    def test_generic_named_pages_and_short_navigation_wording(self):
        self.assertEqual(ak.goal_key('打开订单页'),ak.goal_key('前往订单页面'))
        self.assertEqual(ak.goal_key('从首页进入通用设置'),ak.goal_key('在主页到常规设置页面'))
        self.assertEqual(ak.goal_key('我想去个人中心'),ak.goal_key('进入我的'))
    def test_knowledge_reuses_synonym_and_legacy_goal_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'memory.sqlite3';old=ak.Knowledge('app','进入附近门店页面',path=path)
            old.goal=ak.legacy_goal_key('进入附近门店页面')
            old.observe(page('入口'),{'action':'tap'},page('附近门店'),[],label='入口')
            steps=[{'action':'tap','label':'入口','result':'executed'}]
            old.promote(page('附近门店'),steps,['附近门店'])
            current=ak.Knowledge('app','打开附近门店页面',path=path)
            self.assertIsNotNone(current.lookup(page('入口'),[]))
            self.assertEqual(current.completion(page('附近门店'),steps),['附近门店'])
    def test_conflicting_semantic_aliases_do_not_guess(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'memory.sqlite3'
            for goal,after in [('打开附近门店','第一种结果'),('进入附近门店','第二种结果')]:
                old=ak.Knowledge('app',goal,path=path);old.goal=ak.legacy_goal_key(goal)
                old.observe(page('入口'),{'action':'tap'},page(after),[],label='入口')
                old.promote(page(after),[{'action':'tap','label':'入口','result':'executed'}],[after])
            self.assertIsNone(ak.Knowledge('app','跳转到附近门店',path=path).lookup(page('入口'),[]))


class ExcelIntentTests(unittest.TestCase):
    setUp=fast_tests.FastExcelTests.setUp
    generate=fast_tests.FastExcelTests.generate
    responder=fast_tests.FastExcelTests.responder
    def test_rephrased_steps_reuse_cache_without_new_ai_call(self):
        c=self.book['cases'][0];c.update(title='进入通用设置',steps='进入通用设置',expected='进入通用设置页面',precondition='需要自定义前置条件')
        self.generate()
        c.update(title='打开通用设置页面',steps='跳转到常规设置',expected='跳转到通用设置页面')
        result=self.generate()
        self.assertEqual(self.calls,1)
        self.assertEqual(result['generation_stats']['cached'],1)
        self.assertEqual(result['cases'][0]['business_steps'][0]['action'],'跳转到常规设置')
    def test_expected_values_and_input_data_not_fuzzily_merged(self):
        c=self.book['cases'][0];c.update(steps='进入通用设置',expected='显示数值 10')
        self.generate();c['expected']='显示数值 20';self.generate()
        c['test_data']='数值=30';self.generate()
        self.assertEqual(self.calls,3)
    def test_legacy_excel_candidate_found_after_rewording(self):
        c=self.book['cases'][0];c.update(title='导航测试',steps='进入通用设置',expected='显示指定内容',precondition='需要自定义前置条件')
        self.generate()
        # Re-key the current complete candidate using the pre-normalization format.
        import hashlib,json
        scope=excel_plan_cache.scope({'include_source':False,'call_acceptance':'full','target_language':''})
        scope_key=hashlib.sha256((scope+'').encode()).hexdigest()
        old_key=hashlib.sha256(json.dumps([excel_ai.legacy_reusable_key(c),c['precondition'],c['sheet']],ensure_ascii=False).encode()).hexdigest()
        files=list((excel_ai.CACHE/'reusable').glob('*.json'));data=json.loads(files[0].read_text())
        for f in files:f.unlink()
        excel_plan_cache.save(excel_ai.CACHE,scope_key,old_key,data['entry'])
        c['steps']='打开通用设置页面'
        result=self.generate()
        self.assertEqual(self.calls,1)
        self.assertEqual(result['generation_stats']['semantic_reused'],1)


if __name__=='__main__':unittest.main()
