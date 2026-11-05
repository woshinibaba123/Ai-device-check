import copy,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import excel_ai,codebuddy_bridge,case_workbook,case_runner
from test_case_workbook import fixture

class ExcelAITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'cases.xlsx';fixture(self.path)
        self.book=case_workbook.read(self.path)
        self.options={'path':str(self.path),'fingerprint':excel_ai.fingerprint(self.book),'sheet':'手机全量','priority':'P1','plans':{}}
        self.cache=patch.object(excel_ai,'CACHE',Path(self.tmp.name)/'plans');self.cache.start();self.addCleanup(self.cache.stop)
    def generate(self,responder=None):
        def response(cfg,progress):
            doc=copy.deepcopy(cfg['document'])
            for row in doc['cases']:
                row['plan']={'requires':[],'steps':[{'action':'tap','value':'我的'},{'action':'assert','value':'通用设置'}]};row['blocked_reason']=''
            return doc
        with patch.object(codebuddy_bridge,'generate',side_effect=responder or response):
            return excel_ai.generate({'excel':self.options,'include_source':False},lambda *a:None)
    def test_duplicate_titles_map_to_original_excel_rows_and_original_is_unchanged(self):
        original=self.path.read_bytes();result=self.generate()
        self.assertEqual(result['ready'],2);self.assertEqual([r['id'] for r in result['cases']],['手机全量:6','手机全量:7'])
        merged=excel_ai.apply(self.book,dict(self.options,ai_plan_id=result['excel_plan_id']))
        self.assertEqual(case_runner.preview(merged,self.options)['ready'],2)
        self.assertEqual(self.path.read_bytes(),original);self.assertEqual(merged['content'],original)
        self.assertFalse(merged.get('ai'));self.assertEqual([c['expected'] for c in merged['cases']],[c['expected'] for c in self.book['cases']])
        out=Path(self.tmp.name)/'results.xlsx'
        case_workbook.annotate(merged,[{'id':'手机全量:6','result':'pass','status':'已执行','reason':'断言通过','screenshots':[]}],out)
        with zipfile.ZipFile(out) as z:
            xml=z.read('xl/worksheets/sheet1.xml').decode();self.assertIn('pass',xml);self.assertIn('尚未执行',xml)
            self.assertEqual(z.read('native-part.bin'),b'keep native metadata')
    def test_generated_plan_executes_and_results_map_back_to_excel(self):
        from automation import Explorer
        from test_automation import FakeDriver
        class Driver(FakeDriver):
            def source(self):
                return '<hierarchy><node package="com.example" class="android.widget.Button" text="首页" clickable="true" selected="'+str(self.state=='A').lower()+'"/><node package="com.example" class="android.widget.Button" text="我的" clickable="true" selected="'+str(self.state=='M').lower()+'"/>'+('<node package="com.example" class="android.widget.TextView" text="通用设置"/>' if self.state=='M' else '')+'</hierarchy>'
            def __call__(self,method,path,data=None):
                if path.endswith('/click'):
                    label=self.elements[path.split('/')[-2]]['label'];self.state='M' if label=='我的' else 'A';return
                return super().__call__(method,path,data)
        r=self.generate();options=dict(self.options,ai_plan_id=r['excel_plan_id'])
        book=excel_ai.apply(self.book,options);driver=Driver();e=Explorer(driver,'s','Android',lambda _:None,lambda *a:None)
        e.app_package='com.example';e.settled_source=driver.source
        results=case_runner.run(e,book,options,lambda _:None,lambda *a:'unit-test-evidence',lambda *a:None,lambda:False,lambda *a:None)
        self.assertEqual([r['result'] for r in results],['pass','pass'])
        self.assertEqual([r['id'] for r in results],['手机全量:6','手机全量:7'])
        target=Path(self.tmp.name)/'executed.xlsx';case_workbook.annotate(book,results,target)
        with zipfile.ZipFile(target) as z:self.assertEqual(z.read('xl/worksheets/sheet1.xml').decode().count('>pass<'),2)

    def test_workbook_or_filter_change_rejects_stale_plan(self):
        r=self.generate();options=dict(self.options,ai_plan_id=r['excel_plan_id'])
        with self.assertRaises(ValueError):excel_ai.apply(dict(self.book,content=b'changed'),options)
        with self.assertRaises(ValueError):excel_ai.apply(self.book,dict(options,priority='P0'))
        with self.assertRaises(ValueError):excel_ai.apply(self.book,dict(options,source='/another/source'))
    def test_ai_may_not_change_original_expected_or_steps(self):
        def changed(cfg,progress):
            d=copy.deepcopy(cfg['document']);d['cases'][0]['expected']='弱化的预期';return d
        r=self.generate(changed);self.assertEqual(r['ready'],0)
        merged=excel_ai.apply(self.book,dict(self.options,ai_plan_id=r['excel_plan_id']))
        preview=case_runner.preview(merged,self.options);self.assertEqual(preview['ready'],0)
        self.assertTrue(all('改写' in x['reason'] for x in preview['cases']))
    def test_missing_data_is_pending_instead_of_falling_back_to_automatic_compile(self):
        def pending(cfg,progress):return copy.deepcopy(cfg['document'])
        r=self.generate(pending);merged=excel_ai.apply(self.book,dict(self.options,ai_plan_id=r['excel_plan_id']))
        self.assertEqual(case_runner.preview(merged,self.options)['ready'],0)
    def test_literal_credentials_are_not_sent_to_model_or_stored_in_artifact(self):
        b=copy.deepcopy(self.book)
        for c in b['cases']:c['precondition']='账号: demo@example.test 密码: SuperSecret123';c['test_data']='密码=AnotherSecret'
        seen=[]
        def inspect(cfg,progress):seen.append(json.dumps({k:v for k,v in cfg.items() if not k.startswith('_')},ensure_ascii=False));return copy.deepcopy(cfg['document'])
        with patch.object(case_workbook,'read',return_value=b):r=self.generate(inspect)
        data=''.join(seen)+(excel_ai.CACHE/(r['excel_plan_id']+'.json')).read_text()
        for secret in ('demo@example.test','SuperSecret123','AnotherSecret'):self.assertNotIn(secret,data)
    def test_redacted_placeholder_is_never_typed(self):
        def placeholder(cfg,progress):
            d=copy.deepcopy(cfg['document'])
            for c in d['cases']:c.update(plan={'steps':[{'action':'input','value':'账号','text':'[本机数据]'},{'action':'assert','value':'首页'}]},blocked_reason='')
            return d
        self.assertEqual(self.generate(placeholder)['ready'],0)
    def test_invalid_file_and_stale_preview_are_rejected_before_model(self):
        with self.assertRaises(ValueError):excel_ai.read_selected(dict(self.options,fingerprint='stale'))
        with self.assertRaises(ValueError):excel_ai.apply(self.book,dict(self.options,ai_plan_id='../secret'))
    def test_failure_in_one_batch_does_not_lose_other_rows(self):
        b=copy.deepcopy(self.book);template=next(c for c in b['cases'] if c['mobile'])
        b['cases']=[dict(template,id='手机全量:'+str(n),row=n,priority='P1') for n in range(10,16)]
        calls=[]
        def response(cfg,progress):
            calls.append(cfg)
            if len(calls)==1:raise ValueError('AI 返回 JSON 不完整')
            d=copy.deepcopy(cfg['document'])
            for c in d['cases']:c.update(plan={'steps':[{'action':'assert','value':'首页'}]},blocked_reason='')
            return d
        with patch.object(excel_ai,'BATCH_SIZE',5),patch.object(case_workbook,'read',return_value=b):r=self.generate(response)
        self.assertEqual(len(calls),2);self.assertEqual(r['selected'],6);self.assertEqual(r['ready'],1)
    def test_excel_changed_during_generation_cannot_publish_plan(self):
        def changed(cfg,progress):
            self.path.write_bytes(self.path.read_bytes()+b'changed')
            return copy.deepcopy(cfg['document'])
        with self.assertRaisesRegex(ValueError,'生成期间'):self.generate(changed)
    def test_more_than_300_cases_are_batched_without_losing_row_mapping(self):
        b=copy.deepcopy(self.book);template=next(c for c in b['cases'] if c['mobile'])
        b['cases']=[dict(template,id='手机全量:'+str(n),row=n,priority='P1') for n in range(10,367)]
        sizes=[];events=[]
        def response(cfg,progress):
            document=copy.deepcopy(cfg['document']);sizes.append(len(document['cases']))
            for row in document['cases']:
                row.update(plan={'steps':[{'action':'assert','value':'首页'}]},blocked_reason='')
            return document
        with patch.object(case_workbook,'read',return_value=b),patch.object(codebuddy_bridge,'generate',side_effect=response):
            result=excel_ai.generate({'excel':self.options,'include_source':False},lambda *event:events.append(event))
        self.assertEqual(sizes,[10]*35+[7])
        self.assertEqual(result['ready'],357)
        self.assertEqual([r['id'] for r in result['cases']],[c['id'] for c in b['cases']])
        self.assertTrue(any('第 36/36 批' in label for _,label in events))
        merged=excel_ai.apply(b,dict(self.options,ai_plan_id=result['excel_plan_id']))
        self.assertEqual(case_runner.preview(merged,self.options)['ready'],357)
    def test_complex_cases_use_smaller_batches(self):
        rows=[{'steps':'\n'.join(['操作']*30),'title':'表单'} for _ in range(7)]
        self.assertEqual([len(c) for c in excel_ai.batches(rows)],[2,2,2,1])
        rows=[{'steps':'操作','test_data':'x'*10000} for _ in range(3)]
        self.assertEqual([len(c) for c in excel_ai.batches(rows)],[1,1,1])
    def test_source_index_reused_with_batch_specific_evidence(self):
        context=codebuddy_bridge.ExcelSourceContext()
        document=codebuddy_bridge.business_document({'cases':[excel_ai.business_case(self.book['cases'][0])]})
        cfg={'outline':'门店报修表单','binding_only':True,'strict_excel':True,'include_source':True,'source':'/test/source','document':document,'_excel_source_context':context}
        with patch('flow_planner.source_index',return_value={'pages':[]}) as index,patch('flow_planner.ai_summary',return_value={}) as summary,patch.object(codebuddy_bridge,'ask',return_value={'bindings':[]}):
            codebuddy_bridge.generate(cfg)
            other=json.loads(json.dumps(document));other['cases'][0]['title']='机器人详情'
            codebuddy_bridge.generate(dict(cfg,outline='机器人详情',document=other))
        self.assertEqual(index.call_count,1)
        self.assertIn('切换消息',summary.call_args_list[0].args[1])
        self.assertIn('机器人详情',summary.call_args_list[1].args[1])
        self.assertNotIn('门店报修表单',summary.call_args_list[0].args[1])
    def test_manual_overrides_cannot_silently_replace_ai_plan(self):
        r=self.generate()
        with self.assertRaises(ValueError):excel_ai.apply(self.book,dict(self.options,ai_plan_id=r['excel_plan_id'],plans={'手机全量:6':{'steps':[]}}))

class ExcelAIHTTPTests(unittest.TestCase):
    setUp=ExcelAITests.setUp
    generate=ExcelAITests.generate
    def test_zero_executable_cases_rejected_before_device_start(self):
        import app,threading,urllib.request,urllib.error
        book=copy.deepcopy(self.book)
        for case in book['cases']:case['precondition']='需要尚未配置的业务数据'
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/batch',data=json.dumps({'test_mode':'cases','cases':self.options,'bundle':'test.app','targets':[{'platform':'Android','device':'mock'}]}).encode(),headers={'Content-Type':'application/json'})
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with patch.object(case_workbook,'read',return_value=book),patch.object(app,'request') as device:
                with self.assertRaises(urllib.error.HTTPError) as caught:opener.open(req)
                self.assertEqual(caught.exception.code,400)
                self.assertIn('没有可执行用例',json.load(caught.exception)['error'])
                device.assert_not_called()
        finally:server.shutdown();server.server_close()
    def test_http_preview_and_queue_use_the_same_original_workbook_rows(self):
        import app,threading,urllib.request
        from unittest.mock import MagicMock
        from types import SimpleNamespace
        result=self.generate();options=dict(self.options,ai_plan_id=result['excel_plan_id'])
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def post(path,body):return json.load(opener.open(urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})))
        try:
            preview=post('/api/cases/preview',options);self.assertEqual(preview['ready'],2)
            worker=MagicMock()
            with patch.object(app,'ROOT',Path(self.tmp.name)/'server'),patch.object(app,'JOBS',{}),patch.object(app,'BATCH_RUNNING',threading.Event()),patch.object(app,'request',return_value={}),patch.object(app,'threading',SimpleNamespace(Thread=worker)):
                queued=post('/api/batch',{'test_mode':'cases','cases':options,'bundle':'test.app','targets':[{'platform':'Android','device':'mock-device'}]})
                self.assertEqual(queued['count'],1)
                cfg=worker.call_args.kwargs['args'][0][0][1];book=cfg['case_book']
                self.assertEqual(book['content'],self.book['content']);self.assertFalse(book.get('ai'))
                self.assertEqual([c['id'] for c in case_runner.selected_cases(book,options)],['手机全量:6','手机全量:7'])
                self.assertEqual(case_runner.preview(book,options)['ready'],2)
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()

class LanguageCandidateReuseTests(unittest.TestCase):
    def test_identical_case_localizes_only_source_backed_native_labels(self):
        cache=codebuddy_bridge.ExcelSourceContext()
        cache.flutter={'locale_packs':{'zh':{'mine':'我的','settings':'通用设置'},'en':{'mine':'Mine','settings':'Settings'},'ja':{'mine':'私','settings':'設定'}}}
        row={'id':'zh:6','plan':{'requires':[],'steps':[{'action':'tap','value':'我的'},{'action':'assert','value':'通用设置'}]},'business_steps':[{'automation_steps':[{'action':'tap','value':'我的'},{'action':'assert','value':'通用设置'}]}]}
        localized=excel_ai.localize_candidate(row,cache,'ja')
        self.assertEqual([s['value'] for s in localized['plan']['steps']],['私','設定'])
        self.assertEqual(row['plan']['steps'][0]['value'],'我的')
        self.assertIsNone(excel_ai.localize_candidate(row,cache,'th'))
        row['plan']['steps'][0]['value']='未定义控件'
        self.assertIsNone(excel_ai.localize_candidate(row,cache,'en'))
    def test_only_locale_precondition_prefix_is_normalized(self):
        case={'title':'保存','steps':'输入10，保存','expected':'回读10','precondition':'当前为中文简体（zh）；已登录','test_data':'10','module':'App / 设置'}
        other=dict(case,precondition='当前为English（en）；已登录')
        self.assertEqual(excel_ai.reusable_key(case),excel_ai.reusable_key(other))
        self.assertNotEqual(excel_ai.reusable_key(case),excel_ai.reusable_key(dict(other,test_data='11')))
        self.assertNotEqual(excel_ai.reusable_key(case),excel_ai.reusable_key(dict(other,expected='回读11')))
    def test_known_format_samples_remain_but_real_lookalikes_are_redacted(self):
        self.assertIn('13800000000',excel_ai.safe_text('联系方式：13800000000'))
        self.assertIn('qa@example.com',excel_ai.safe_text('联系邮箱：qa@example.com'))
        self.assertNotIn('138000000001',excel_ai.safe_text('联系方式：138000000001'))
        self.assertNotIn('otherqa@example.com',excel_ai.safe_text('邮箱：otherqa@example.com'))

class PartialCandidateTests(unittest.TestCase):
    setUp=ExcelAITests.setUp
    def test_contiguous_prefix_executes_but_entire_case_never_passes(self):
        from automation import Explorer
        b=copy.deepcopy(self.book)
        for c in b['cases']:c['steps']='点击我的入口\n提交表单'
        options=dict(self.options,allow_partial=True)
        def response(cfg,progress):
            d=copy.deepcopy(cfg['document'])
            for row in d['cases']:
                row['plan']=None;row['blocked_reason']='第二步提交接口未适配'
                row['business_steps'][0].update(automation_status='candidate',automation_steps=[{'action':'tap','value':'我的'},{'action':'assert','value':'通用设置'}])
                row['business_steps'][1].update(automation_status='unbound',automation_reason='提交接口未适配')
            return d
        with patch.object(case_workbook,'read',return_value=b),patch.object(codebuddy_bridge,'generate',side_effect=response):
            result=excel_ai.generate({'excel':options},lambda *args:None)
        self.assertEqual(result['complete_ready'],0);self.assertEqual(result['partial_ready'],2)
        merged=excel_ai.apply(b,dict(options,ai_plan_id=result['excel_plan_id']))
        e=Explorer(lambda *args:None,'s','Android',lambda _:None,lambda *args:None);e.app_package='com.test';clicks=[]
        source='<hierarchy><node class="android.widget.Button" package="com.test" text="首页" clickable="true"/><node class="android.widget.Button" package="com.test" text="我的" clickable="true"/><node class="android.widget.TextView" package="com.test" text="通用设置"/></hierarchy>'
        with patch.object(e,'settled_source',return_value=source),patch.object(e,'tap',side_effect=lambda node:clicks.append(node['label'])):
            rows=case_runner.run(e,merged,options,lambda _:None,lambda *args:'/proof.png',lambda _:None,lambda:False,lambda _:None)
        self.assertTrue(all(r['result']=='fail' and r['status']=='执行受阻' for r in rows));self.assertEqual(clicks.count('我的'),2)
    def test_prefix_never_crosses_a_gap_or_types_redacted_placeholders(self):
        row={'business_steps':[{'automation_status':'candidate','automation_steps':[{'action':'tap','value':'我的'}]},{'automation_status':'unbound','automation_steps':[]},{'automation_status':'candidate','automation_steps':[{'action':'tap','value':'提交'}]}]}
        self.assertEqual(excel_ai.partial_candidate(row)['steps'],[{'action':'tap','value':'我的'}])
        row['business_steps'][0]['automation_steps']=[{'action':'input','value':'联系方式','text':'[已隐藏]'}]
        self.assertIsNone(excel_ai.partial_candidate(row))
