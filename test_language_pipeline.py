import copy,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import language_pipeline as pipeline
import language_tests

class LanguagePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name,value in [('ROOT',self.root),('TASKS',{}),('CONTROLS',{})]:
            p=patch.object(pipeline,name,value);p.start();self.addCleanup(p.stop)
        self.book={'cases':[{'id':'zh:6','sheet':'01_中文简体','mobile':True,'priority':'P0'},{'id':'en:6','sheet':'02_English','mobile':True,'priority':'P0'}]}
        self.languages={'enabled':True,'selected':[dict(l,choice=l['name'],path=['我的','通用设置','语言']) for l in language_tests.LANGUAGES[:2]]}
        self.cfg={'excel':{'path':'test.xlsx','fingerprint':'hash','priority':'P0'},'source':'/app','h5_source':'/h5','execution':{'targets':[{'platform':'Android','device':'test'}],'source':'/app','h5_source':'/h5','languages':self.languages,'login':{'account':'secret-account','password':'secret-password'}}}
    def wait(self,predicate):
        end=time.monotonic()+4
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.01)
        self.fail('任务未在预期时间内完成')
    def test_group_order_and_explicit_language_mapping(self):
        rows=pipeline.group_selection(self.book,{},self.languages)
        self.assertEqual([r['language']['code'] for r in rows],['zh-CN','en-US'])
        with self.assertRaisesRegex(ValueError,'无法唯一对应'):
            pipeline.group_selection({'cases':[dict(self.book['cases'][0],sheet='未知语言')]},{},self.languages)
    def test_first_language_runs_while_second_generates_and_reports_append(self):
        started=threading.Event();second=threading.Event();release=threading.Event();calls=[];contexts=[]
        class API:
            def post(self,path,body):
                calls.append(copy.deepcopy(body));started.set()
                return {'id':'batch'+str(len(calls))}
            def get(self,path):return {'jobs':[{'status':'passed'}],'counts':{'passed':1}}
        def generate(cfg,progress):
            contexts.append(cfg['_excel_source_context'])
            if len(contexts)==2:
                second.set();release.wait(3)
            return {'ready':1,'selected':1,'excel_plan_id':str(len(contexts))}
        with patch.object(pipeline.excel_ai,'read_selected',return_value=(self.book,self.book['cases'])),patch.object(pipeline.codebuddy_bridge,'status',return_value={'busy':False}),patch.object(pipeline.excel_ai,'generate',side_effect=generate):
            result=pipeline.start(copy.deepcopy(self.cfg),API())
            try:
                self.assertTrue(started.wait(2));self.assertTrue(second.wait(2))
                self.assertEqual(pipeline.snapshot(result['id'])['status'],'running')
            finally:release.set()
            self.wait(lambda:pipeline.snapshot(result['id'])['status']=='done')
        self.assertIs(contexts[0],contexts[1])
        self.assertEqual([c['cases']['sheet'] for c in calls],['01_中文简体','02_English'])
        self.assertEqual([c['languages']['selected'][0]['code'] for c in calls],['zh-CN','en-US'])
        self.assertTrue(all(c['pipeline_id']==result['id'] for c in calls))
        saved=(self.root/'.runtime/language-pipelines'/(result['id']+'.json')).read_text()
        self.assertNotIn('secret-account',saved);self.assertNotIn('secret-password',saved)
    def test_zero_ready_group_skipped_and_next_language_still_runs(self):
        sent=[]
        class API:
            def post(self,path,body):sent.append(body['cases']['sheet']);return {'id':'batch'}
            def get(self,path):return {'jobs':[{'status':'passed'}],'counts':{'passed':1}}
        def generate(cfg,progress):
            return {'ready':0 if cfg['excel']['sheet'].startswith('01') else 1,'excel_plan_id':'plan'}
        with patch.object(pipeline.excel_ai,'read_selected',return_value=(self.book,self.book['cases'])),patch.object(pipeline.codebuddy_bridge,'status',return_value={'busy':False}),patch.object(pipeline.excel_ai,'generate',side_effect=generate):
            result=pipeline.start(copy.deepcopy(self.cfg),API())
            self.wait(lambda:pipeline.snapshot(result['id'])['status']=='review')
        self.assertEqual(sent,['02_English'])
        self.assertEqual(pipeline.snapshot(result['id'])['groups'][0]['state'],'blocked')
    def test_stop_keeps_finished_plans_and_never_submits_later_languages(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def generate(cfg,progress):
            entered.set();release.wait(3);progress('prepare','检查停止状态')
        class API:
            def post(self,*a):calls.append(a)
        with patch.object(pipeline.excel_ai,'read_selected',return_value=(self.book,self.book['cases'])),patch.object(pipeline.codebuddy_bridge,'status',return_value={'busy':False}),patch.object(pipeline.excel_ai,'generate',side_effect=generate):
            result=pipeline.start(copy.deepcopy(self.cfg),API());self.assertTrue(entered.wait(2))
            pipeline.stop(result['id']);release.set()
            self.wait(lambda:pipeline.snapshot(result['id'])['status']=='stopped')
        self.assertFalse(calls)
        self.assertFalse(pipeline.active())
    def test_ready_languages_wait_for_previous_test_and_cleanup(self):
        first=threading.Event();release=threading.Event();calls=[]
        class API:
            attempts=0
            def post(self,path,body):
                if not calls:
                    self.attempts+=1
                    if self.attempts==1:raise pipeline.QueueBusy()
                calls.append(body['cases']['sheet']);first.set();return {'id':'batch'+str(len(calls))}
            def get(self,path):
                running=path.endswith('batch1') and not release.is_set()
                return {'jobs':[{'status':'running' if running else 'passed'}],'counts':{'passed':0 if running else 1}}
        with patch.object(pipeline.excel_ai,'read_selected',return_value=(self.book,self.book['cases'])),patch.object(pipeline.codebuddy_bridge,'status',return_value={'busy':False}),patch.object(pipeline.excel_ai,'generate',return_value={'ready':1,'excel_plan_id':'plan'}):
            result=pipeline.start(copy.deepcopy(self.cfg),API())
            try:
                self.assertTrue(first.wait(2));self.assertEqual(len(calls),1)
            finally:release.set()
            self.wait(lambda:pipeline.snapshot(result['id'])['status']=='done')
        self.assertEqual(calls,['01_中文简体','02_English'])
