import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import codebuddy_bridge as bridge
import excel_ai
import excel_plan_cache
import case_workbook
from test_case_workbook import fixture


class FastExcelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'cases.xlsx';fixture(self.path)
        self.book=case_workbook.read(self.path)
        template=next(c for c in self.book['cases'] if c['mobile'])
        self.book['cases']=[dict(template,id='sheet:10',sheet='sheet',row=10,title='复杂操作',steps='在地图上选择三个标记并核对结果',expected='显示三个标记且顺序正确',precondition='已登录',test_data='',plan_text='')]
        self.options={'path':str(self.path),'fingerprint':excel_ai.fingerprint(self.book),'optimize':True}
        self.cache=patch.object(excel_ai,'CACHE',self.root/'plans');self.cache.start();self.addCleanup(self.cache.stop)
        self.read=patch.object(case_workbook,'read',side_effect=lambda p:self.book);self.read.start();self.addCleanup(self.read.stop)
        self.events=[]
        self.calls=0
    def responder(self,cfg,progress):
        self.calls+=1
        d=copy.deepcopy(cfg['document'])
        for row in d['cases']:row.update(plan={'steps':[{'action':'assert','value':'三个标记'}]},blocked_reason='')
        return d
    def generate(self,**kwargs):
        with patch.object(bridge,'generate',side_effect=self.responder):
            return excel_ai.generate(dict(excel=self.options,include_source=False,**kwargs),lambda *e:self.events.append(e))
    def test_simple_navigation_requires_zero_ai_requests(self):
        self.book['cases'][0].update(steps='点击“我的”',expected='进入我的页面')
        result=self.generate()
        self.assertEqual(self.calls,0)
        self.assertEqual(result['generation_stats']['local'],1)
        self.assertEqual(result['cases'][0]['plan']['steps'][-1]['action'],'assert_selected')
    def test_second_run_reuses_persistent_candidate_not_pass_result(self):
        first=self.generate();second=self.generate()
        self.assertEqual(self.calls,1)
        self.assertEqual(second['generation_stats']['cached'],1)
        self.assertNotIn('result',second['cases'][0])
        self.assertEqual(first['cases'][0]['plan'],second['cases'][0]['plan'])
    def test_model_change_reuses_validated_candidate(self):
        self.generate(model='first');result=self.generate(model='second')
        self.assertEqual(self.calls,1)
        self.assertEqual(result['generation_stats']['cached'],1)
    def test_legacy_model_scoped_cache_is_migrated(self):
        cfg={'include_source':False,'model':'old','call_acceptance':'full','target_language':''}
        self.generate(model='old')
        path=next((excel_ai.CACHE/'reusable').glob('*.json'))
        data=json.loads(path.read_text());path.unlink()
        import hashlib
        old_scope=hashlib.sha256((excel_plan_cache.scope(cfg,legacy=True)+'').encode()).hexdigest()
        excel_plan_cache.save(excel_ai.CACHE,old_scope,data['case'],data['entry'])
        result=self.generate(model='old')
        self.assertEqual(self.calls,1)
        self.assertEqual(result['generation_stats']['cached'],1)
        self.generate(model='new');self.assertEqual(self.calls,1)
    def test_cache_hit_skips_source_index_and_reports_before_batch(self):
        (self.root/'lib').mkdir();(self.root/'lib/page.dart').write_text('stable')
        with patch('flow_planner.source_index',return_value={'locale_packs':{}}):self.generate(source=str(self.root))
        self.events=[]
        with patch('flow_planner.source_index',side_effect=AssertionError('unnecessary source analysis')):
            self.generate(source=str(self.root))
        self.assertEqual(self.calls,1)
        self.assertIn('历史完整计划命中 1/1',next(label for stage,label in self.events if stage=='excel_cache_scan'))
    def test_ai_miss_is_reported(self):
        self.generate()
        self.assertTrue(any(stage=='excel_cache_miss' and '1 条未找到' in label for stage,label in self.events))
    def test_local_credential_references_cached_without_values(self):
        entry={'plan':{'start_state':'login','steps':[{'action':'input_local','by':'field','value':'password','text':'password'},{'action':'assert','value':'登录'}]}}
        excel_plan_cache.save(excel_ai.CACHE,'scope','case',entry)
        self.assertEqual(excel_plan_cache.load(excel_ai.CACHE,'scope','case'),entry)
        entry['plan']['steps'][0]['text']='real-secret'
        excel_plan_cache.save(excel_ai.CACHE,'scope','invalid',entry)
        self.assertIsNone(excel_plan_cache.load(excel_ai.CACHE,'scope','invalid'))
    def test_357_duplicates_only_request_one_candidate_but_keep_every_row(self):
        original=self.book['cases'][0]
        self.book['cases']=[dict(original,id='sheet:'+str(i),row=i) for i in range(10,367)]
        result=self.generate()
        self.assertEqual(self.calls,1)
        self.assertEqual(result['selected'],357)
        self.assertEqual(result['complete_ready'],357)
        self.assertEqual(len({r['id'] for r in result['cases']}),357)
        self.assertEqual(result['generation_stats']['deduplicated'],356)
    def test_changed_expectation_requests_new_plan(self):
        self.generate();self.book['cases'][0]['expected']='显示四个标记且顺序正确';self.generate()
        self.assertEqual(self.calls,2)
    def test_row_number_change_rebinds_candidate_to_new_original_row(self):
        self.generate();self.book['cases'][0].update(id='sheet:55',sheet='sheet',row=55)
        result=self.generate()
        self.assertEqual(self.calls,1)
        self.assertEqual(result['cases'][0]['id'],'sheet:55')
        self.assertEqual(result['cases'][0]['row'],55)
    def test_semantic_blockers_reused_until_explicit_retry(self):
        def fail(cfg,progress):return copy.deepcopy(cfg['document'])
        with patch.object(bridge,'generate',side_effect=fail):
            first=excel_ai.generate({'excel':self.options,'include_source':False},lambda *e:None)
        self.assertEqual(first['ready'],0)
        second=self.generate();self.assertEqual(self.calls,0)
        self.assertEqual(second['generation_stats']['blocked_cached'],1)
        self.options['retry_blocked']=True
        self.generate();self.assertEqual(self.calls,1)
    def test_source_content_change_invalidates_candidate(self):
        (self.root/'lib').mkdir();source=self.root/'lib/page.dart';source.write_text('version one')
        with patch('flow_planner.source_index',return_value={'locale_packs':{}}):
            self.generate(source=str(self.root));source.write_text('version two');self.generate(source=str(self.root))
        self.assertEqual(self.calls,2)
    def test_source_change_during_generation_rejects_cache_publication(self):
        (self.root/'lib').mkdir();source=self.root/'lib/page.dart';source.write_text('one')
        def changing(cfg,progress):
            d=self.responder(cfg,progress);source.write_text('two');return d
        with patch('flow_planner.source_index',return_value={'locale_packs':{}}),patch.object(bridge,'generate',side_effect=changing):
            with self.assertRaisesRegex(ValueError,'源码已变化'):excel_ai.generate({'excel':self.options,'source':str(self.root)},lambda *e:None)
        self.assertFalse((excel_ai.CACHE/'reusable').exists())
    def test_corrupted_cache_rebuilds(self):
        self.generate()
        for file in (excel_ai.CACHE/'reusable').glob('*.json'):file.write_text('broken')
        self.generate();self.assertEqual(self.calls,2)
    def test_credential_input_is_not_persistently_cached(self):
        entry={'plan':{'steps':[{'action':'input','value':'字段','text':'real-person@example.org'},{'action':'assert','value':'成功'}]}}
        excel_plan_cache.save(excel_ai.CACHE,'scope','case',entry)
        self.assertIsNone(excel_plan_cache.load(excel_ai.CACHE,'scope','case'))
    def test_acceptance_policy_change_does_not_reuse(self):
        self.generate();self.options['call_acceptance']='backend_only';self.generate()
        self.assertEqual(self.calls,2)
    def test_password_field_is_not_cached_even_without_email_or_phone(self):
        excel_plan_cache.save(excel_ai.CACHE,'scope','case',{'plan':{'steps':[{'action':'input','value':'密码','text':'SomeSecret'},{'action':'assert','value':'首页'}]}})
        self.assertIsNone(excel_plan_cache.load(excel_ai.CACHE,'scope','case'))
    def test_native_plan_reused_across_languages_with_verified_source_packs(self):
        (self.root/'lib').mkdir();(self.root/'lib/page.dart').write_text('stable source')
        packs={'fr-FR':{'home':'Accueil'},'en-US':{'home':'Home'},'zh-CN':{'home':'首页'}}
        def response(cfg,progress):
            d=self.responder(cfg,progress)
            d['cases'][0]['plan']={'steps':[{'action':'assert','value':'Accueil'}]}
            return d
        with patch('flow_planner.source_index',return_value={'locale_packs':packs}),patch.object(bridge,'generate',side_effect=response):
            excel_ai.generate({'excel':self.options,'source':str(self.root),'target_language':'fr-FR'},lambda *e:None)
            result=excel_ai.generate({'excel':self.options,'source':str(self.root),'target_language':'en-US'},lambda *e:None)
        self.assertEqual(self.calls,1)
        self.assertEqual(result['cases'][0]['plan']['steps'][0]['value'],'Home')
        self.assertEqual(result['generation_stats']['translated'],1)
    def test_different_language_sheets_not_blindly_deduplicated(self):
        first=self.book['cases'][0]
        self.book['cases']=[dict(first,sheet='中文',id='中文:10'),dict(first,sheet='English',id='English:10')]
        result=self.generate()
        self.assertEqual(result['generation_stats']['ai_cases'],2)
        self.assertEqual(result['generation_stats']['deduplicated'],0)
    def test_language_precondition_changes_not_blindly_reused(self):
        self.book['cases'][0]['precondition']='当前为法语（fr-FR）；已登录'
        self.generate()
        self.book['cases'][0]['precondition']='当前为英语（en-US）；已登录'
        self.generate()
        self.assertEqual(self.calls,2)
    def test_streamed_candidate_survives_interruption_before_batch_finishes(self):
        first=self.book['cases'][0]
        self.book['cases'].append(dict(first,id='sheet:11',row=11,title='另一个复杂操作'))
        def interrupted(cfg,progress):
            d=self.responder(cfg,progress)
            cfg['_excel_on_candidate']([d['cases'][0]])
            raise KeyboardInterrupt('simulate process interruption')
        with patch.object(bridge,'generate',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):excel_ai.generate({'excel':self.options,'include_source':False},lambda *e:None)
        checkpoints=list((excel_ai.CACHE/'in-progress').glob('*.json'))
        self.assertEqual(json.loads(checkpoints[0].read_text())['processed'],1)
        self.calls=0
        result=self.generate()
        self.assertEqual(self.calls,1)
        self.assertEqual(result['generation_stats']['cached'],1)
        self.assertEqual(result['generation_stats']['ai_cases'],1)
        self.assertEqual(result['ready'],2)
    def test_transient_timeout_not_cached_as_semantic_blocker(self):
        with patch.object(bridge,'generate',side_effect=ValueError('AI 请求超时')):
            excel_ai.generate({'excel':self.options,'include_source':False},lambda *e:None)
        self.generate();self.assertEqual(self.calls,1)
    def test_blocker_expires_and_is_reanalyzed(self):
        with patch.object(bridge,'generate',side_effect=lambda cfg,p:copy.deepcopy(cfg['document'])):
            excel_ai.generate({'excel':self.options,'include_source':False},lambda *e:None)
        import time
        with patch.object(excel_plan_cache.time,'time',return_value=time.time()+31*86400):self.generate()
        self.assertEqual(self.calls,1)
    def test_blocker_still_reused_next_day(self):
        with patch.object(bridge,'generate',side_effect=lambda cfg,p:copy.deepcopy(cfg['document'])):
            excel_ai.generate({'excel':self.options,'include_source':False},lambda *e:None)
        import time
        with patch.object(excel_plan_cache.time,'time',return_value=time.time()+86400):result=self.generate()
        self.assertEqual(self.calls,0)
        self.assertEqual(result['generation_stats']['blocked_cached'],1)


class BindingBatchTests(unittest.TestCase):
    def document(self):
        return bridge.business_document({'cases':[{'title':'表单'+str(i),'expected':'完整验证结果','precondition':'已登录','business_steps':[{'action':'操作'+str(n),'expected':'检查'+str(n)} for n in range(4)]} for i in range(4)]})
    def test_short_complex_excel_cases_use_two_case_requests(self):
        with patch.object(bridge,'ask',return_value={'bindings':[]}) as ask:
            result=bridge.generate({'outline':'匹配原始表单步骤','binding_only':True,'document':self.document(),'strict_excel':True,'_excel_fast':True})
        self.assertEqual(len(result['cases']),4)
        self.assertEqual(ask.call_count,2)
    def test_real_binding_pipeline_publishes_each_small_batch(self):
        streamed=[]
        with patch.object(bridge,'ask',return_value={'bindings':[]}):
            bridge.generate({'outline':'匹配原始步骤','binding_only':True,'document':self.document(),'strict_excel':True,'_excel_fast':True,'_excel_on_candidate':lambda rows:streamed.append([r['title'] for r in rows])})
        self.assertEqual(streamed,[['表单0','表单1'],['表单2','表单3']])
    def test_batch_timeout_falls_back_to_single_cases(self):
        def respond(*a,**kw):
            respond.count+=1
            if respond.count==1:raise ValueError('AI 请求超时')
            return {'bindings':[]}
        respond.count=0
        with patch.object(bridge,'ask',side_effect=respond):
            result=bridge.generate({'outline':'匹配原始表单步骤','binding_only':True,'document':self.document(),'strict_excel':True,'_excel_fast':True})
        self.assertEqual(len(result['cases']),4)
        self.assertEqual(respond.count,5)


if __name__=='__main__':unittest.main()
