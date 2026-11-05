import io
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import codebuddy_bridge as bridge
import case_runner
import app


def sample():
    return {'cases':[{'title':'打开我的页面','priority':'P1','precondition':'已登录，位于首页',
                      'description':'点击我的，检查设置入口','expected':'出现设置入口','blocked_reason':'',
                      'plan':{'requires':[{'action':'assert','value':'首页'}],
                              'steps':[{'action':'tap','value':'我的'},{'action':'assert','value':'设置'}]}}]}


def business_sample():
    return {'cases':[{'title':'打开我的页面','priority':'P1','precondition':'已登录，位于首页','expected':'出现设置入口',
                      'business_steps':[{'action':'点击我的，查看设置入口','expected':'出现设置入口'}]}]}


def bindings_sample():
    return {'bindings':[{'case_id':1,'requires':[{'action':'assert','value':'首页'}],
                         'steps':[{'business_step':1,'operations':[{'action':'tap','value':'我的'},{'action':'assert','value':'设置'}],'blocked_reason':''}]}]}


class GenerationSnapshotTests(unittest.TestCase):
    def tearDown(self):
        bridge.GENERATIONS.clear()
    def test_snapshot_returns_draft_result_and_status(self):
        import time
        now=time.monotonic()
        bridge.GENERATIONS['g1']={'id':'g1','status':'running','stage':'binding_batch','label':'x','started':now,'changed':now,'history':[],
                                  'draft':{'cases':[{'title':'A','priority':'P1','precondition':'','description':'步骤','expected':'结果','blocked_reason':'','plan':{'requires':[],'steps':[{'action':'assert','value':'首页'}]}}]}}
        snapshot=bridge.generation_snapshot('g1')
        self.assertEqual(snapshot['status'],'running')
        self.assertEqual(snapshot['document']['cases'][0]['title'],'A')
        bridge.GENERATIONS['g1']['status']='done';bridge.GENERATIONS['g1']['result']={'cases':[]}
        snapshot=bridge.generation_snapshot('g1')
        self.assertEqual(snapshot['status'],'done');self.assertEqual(snapshot['document'],{'cases':[]})
        with self.assertRaises(ValueError):bridge.generation_snapshot('missing')


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.saved_key=''
        def save(key):self.saved_key=key
        def delete():self.saved_key=''
        self.store=SimpleNamespace(exists=MagicMock(side_effect=lambda:bool(self.saved_key)),
                                   read=MagicMock(side_effect=lambda:self.saved_key),
                                   save=MagicMock(side_effect=save),delete=MagicMock(side_effect=delete))
        self.storage_patch=patch.object(bridge,'credential_store',self.store)
        self.storage_patch.start()

    def tearDown(self):
        bridge.configure({'clear':True})
        self.storage_patch.stop()

    def test_remembered_key_is_reused_after_memory_reset_without_returning_secret(self):
        state=bridge.configure({'key':'persisted-test-key','remember':True})
        self.assertTrue(state['saved'])
        bridge._KEY=''
        self.assertTrue(bridge.status()['configured'])
        process=MagicMock(returncode=0);process.communicate.return_value=(json.dumps({'result':'OK'}),'')
        with patch.object(bridge,'executable',return_value='/mock/codebuddy'),patch.object(bridge.subprocess,'Popen',return_value=process) as start:
            bridge.ask('ping')
            self.assertEqual(start.call_args.kwargs['env']['CODEBUDDY_API_KEY'],'persisted-test-key')
        self.assertNotIn('persisted-test-key',json.dumps(state))

    def test_forgetting_key_removes_saved_and_session_values(self):
        bridge.configure({'key':'test-key','remember':True})
        state=bridge.configure({'clear':True,'forget':True})
        self.assertFalse(state['saved']);self.assertEqual(bridge._KEY,'')
        self.store.delete.assert_called_once()

    def test_unchecking_remember_keeps_session_only(self):
        bridge.configure({'key':'test-key','remember':True})
        state=bridge.configure({'remember':False})
        self.assertFalse(state['saved']);self.assertEqual(bridge._KEY,'test-key')

    def test_storage_failure_does_not_claim_success_or_replace_session_key(self):
        bridge._KEY='old-session-key'
        self.store.save.side_effect=ValueError('钥匙串不可用')
        with self.assertRaisesRegex(ValueError,'钥匙串'):bridge.configure({'key':'new-key','remember':True})
        self.assertEqual(bridge._KEY,'old-session-key')

    def test_explicit_assertions_compile_and_missing_data_stays_pending(self):
        document=sample()
        document['cases'].append({'title':'验证码登录','expected':'进入首页','blocked_reason':'需人工提供验证码','plan':None})
        book=bridge.book(document)
        preview=case_runner.preview(book,{})
        self.assertEqual(preview['ready'],1)
        self.assertEqual(preview['pending'],1)
        self.assertIn('验证码',preview['cases'][1]['reason'])

    def test_no_assertion_unknown_operation_and_nonfinite_wait_rejected(self):
        for steps in ([{'action':'tap','value':'我的'}], [{'action':'shell','value':'ls'}],
                      [{'action':'wait','seconds':float('nan')},{'action':'assert','value':'设置'}]):
            document=sample();document['cases'][0]['plan']['steps']=steps
            with self.assertRaises(ValueError):bridge.book(document)

    def test_pending_case_cannot_smuggle_plan(self):
        document=sample();document['cases'][0]['blocked_reason']='缺少数据'
        with self.assertRaises(ValueError):bridge.book(document)

    def test_key_never_in_arguments_response_or_public_status(self):
        bridge.configure({'key':'test-private-key'})
        process=MagicMock(returncode=0)
        process.communicate.return_value=(json.dumps({'result':'DEVICECHECK_OK test-private-key'}),'')
        with patch.object(bridge,'executable',return_value='/mock/codebuddy'),patch.object(bridge.subprocess,'Popen',return_value=process) as start,patch.object(bridge,'cli_models',return_value=[]):
            response=bridge.ask('只检查连接','some-model','cn')
            args=start.call_args.args[0];options=start.call_args.kwargs
            self.assertNotIn('test-private-key',' '.join(args))
            self.assertNotIn('test-private-key',response)
            self.assertEqual(options['env']['CODEBUDDY_API_KEY'],'test-private-key')
            self.assertEqual(args[args.index('--tools')+1],'')
            self.assertIn('--no-session-persistence',args)
            self.assertNotIn('test-private-key',json.dumps(bridge.status()))
            self.assertFalse(Path(options['cwd']).exists())

    def test_vendor_error_output_never_echoed(self):
        bridge.configure({'key':'test-secret'})
        process=MagicMock(returncode=1);process.communicate.return_value=('','failed with test-secret')
        with patch.object(bridge,'executable',return_value='/mock/codebuddy'),patch.object(bridge.subprocess,'Popen',return_value=process):
            with self.assertRaises(ValueError) as caught:bridge.ask('ping')
            self.assertNotIn('test-secret',str(caught.exception))

    def test_timeout_kills_process_group(self):
        bridge.configure({'key':'test-secret'})
        process=MagicMock(pid=1234);process.communicate.side_effect=[bridge.subprocess.TimeoutExpired('codebuddy',180),('','')]
        with patch.object(bridge,'executable',return_value='/mock/codebuddy'),patch.object(bridge.subprocess,'Popen',return_value=process),patch.object(bridge.os,'killpg') as kill:
            with self.assertRaisesRegex(ValueError,'180'):bridge.ask('ping')
            kill.assert_called_once_with(1234,bridge.signal.SIGKILL)
            self.assertFalse(bridge.BUSY.locked())

    def test_generation_does_not_read_source_without_opt_in(self):
        with patch.object(bridge,'ask',side_effect=[business_sample(),bindings_sample()]) as ask,patch('flow_planner.source_index') as source:
            self.assertEqual(len(bridge.generate({'outline':'检查我的页面','source':'/private/source'})['cases']),1)
            source.assert_not_called()
            self.assertNotIn('/private/source',ask.call_args.args[0])

    def test_json_code_fence_and_oversized_case_count(self):
        self.assertEqual(bridge.parse_json('```json\n'+json.dumps(sample())+'\n```'),sample())
        with self.assertRaises(ValueError):bridge.book({'cases':sample()['cases']*31})

    def test_ai_plan_executes_with_step_evidence_in_existing_runner(self):
        class Explorer:
            secrets=[]
            def __init__(self):self.opened=False
            def settled_source(self):
                return '<hierarchy><node text="首页" clickable="true"/><node text="我的" clickable="true"/>'+('<node text="设置"/>' if self.opened else '')+'</hierarchy>'
            def tap(self,node):self.opened=node['label']=='我的'
        results=case_runner.run(Explorer(),bridge.book(sample()),{},lambda _:None,
                                lambda name,source:'/reports/test/'+name+'.png',lambda _:None,lambda:False,lambda _:None)
        self.assertEqual(results[0]['result'],'pass')
        self.assertEqual(len(results[0]['steps']),3)
        self.assertEqual(len(results[0]['screenshots']),3)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def tearDown(self):
        self.server.shutdown();self.server.server_close()
    def post(self,path,data,origin=None):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        return self.opener.open(urllib.request.Request(self.url+path,data=json.dumps(data).encode(),headers=headers))
    def test_ai_batch_uses_validated_case_executor_without_workbook(self):
        cfg={'test_mode':'ai','ai_plan':sample(),'app':'/test.apk','targets':[]}
        with patch.object(bridge,'book',wraps=bridge.book) as build,patch('case_workbook.read') as read:
            with self.assertRaises(urllib.error.HTTPError) as error:self.post('/api/batch',cfg)
            self.assertIn('测试目标',json.load(error.exception)['error'])
            build.assert_called_once();read.assert_not_called()
    def test_all_pending_plan_does_not_start_batch(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.post('/api/batch',{'test_mode':'ai','ai_plan':{'cases':[{'title':'登录','expected':'成功','blocked_reason':'缺数据','plan':None}]}})
        self.assertIn('尚无完整可执行',json.load(error.exception)['error'])
    def test_valid_ai_batch_queues_normalized_plan_without_ai_credentials(self):
        worker=MagicMock()
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'ROOT',Path(folder)),patch.object(app,'JOBS',{}),patch.object(app,'BATCH_RUNNING',threading.Event()),patch.object(app,'request',return_value={}),patch.object(app,'threading',SimpleNamespace(Thread=worker)):
            response=json.load(self.post('/api/batch',{'test_mode':'ai','ai_plan':sample(),'bundle':'com.example.app',
                                'targets':[{'platform':'Android','device':'mock-device'}]}))
            self.assertEqual(response['count'],1)
            cfg=worker.call_args.kwargs['args'][0][0][1]
            self.assertEqual(cfg['test_mode'],'cases')
            self.assertTrue(cfg['case_book']['ai'])
            self.assertNotIn('ai_plan',cfg)
            self.assertEqual(case_runner.preview(cfg['case_book'],{})['ready'],1)
    def test_foreign_origin_rejected_before_using_credentials(self):
        with patch.object(bridge,'configure') as configure:
            with self.assertRaises(urllib.error.HTTPError) as error:self.post('/api/ai/config',{'key':'secret'},'https://example.com')
            self.assertEqual(error.exception.code,403);configure.assert_not_called()


if __name__=='__main__':unittest.main()

class ResponseFormatTests(unittest.TestCase):
    def test_cli_message_array_uses_terminal_result(self):
        result=json.dumps(sample())
        self.assertEqual(bridge.parse_json(bridge.extract_response([{'type':'system'},{'type':'result','result':result}])),sample())
    def test_empty_terminal_falls_back_to_assistant_text_blocks(self):
        response=[{'type':'assistant','message':{'role':'assistant','content':[{'type':'text','text':json.dumps(sample())}]}},{'type':'result','result':None}]
        self.assertEqual(bridge.parse_json(bridge.extract_response(response)),sample())
    def test_structured_result_and_provider_errors(self):
        self.assertEqual(bridge.extract_response({'result':None,'structured_output':sample()}),sample())
        with self.assertRaises(ValueError):bridge.extract_response([{'type':'result','is_error':True,'result':'private vendor error'}])
    def test_empty_response_explains_failure(self):
        with self.assertRaisesRegex(ValueError,'空结果'):bridge.extract_response({'result':None})

class GenerationProgressTests(unittest.TestCase):
    def test_real_stage_updates_and_completion(self):
        entered=threading.Event();release=threading.Event()
        def generate(cfg,progress):
            progress('source','读取页面结构')
            draft=sample();progress.publish_draft(draft);draft['cases'][0]['title']='changed after publish'
            entered.set();release.wait(2)
            progress('validate','校验步骤');return sample()
        with patch.object(bridge,'generate',side_effect=generate):
            task=bridge.start_generation({'outline':'test'})
            self.assertTrue(entered.wait(2))
            state=bridge.generation_status(task['id'])
            self.assertEqual(state['stage'],'source');self.assertEqual(state['status'],'running')
            self.assertEqual(state['draft']['cases'][0]['title'],sample()['cases'][0]['title'])
            self.assertEqual(bridge.start_generation({}),{'id':task['id'],'existing':True})
            release.set()
            import time
            for _ in range(100):
                state=bridge.generation_status(task['id'])
                if state['status']!='running':break
                time.sleep(.01)
            self.assertEqual(state['status'],'done');self.assertEqual(state['result'],sample())
            self.assertEqual([h['stage'] for h in state['history']],['source','validate','done'])
            self.assertNotIn('started',state)
    def test_failure_records_stage_without_raw_subprocess_exception(self):
        with patch.object(bridge,'generate',side_effect=RuntimeError('secret vendor data')):
            task=bridge.start_generation({})
            import time
            for _ in range(100):
                state=bridge.generation_status(task['id'])
                if state['status']!='running':break
                time.sleep(.01)
            self.assertEqual(state['status'],'failed');self.assertNotIn('secret',json.dumps(state))

class BusinessPlanningTests(unittest.TestCase):
    def test_complete_business_case_survives_partial_binding(self):
        business=business_sample()
        business['cases'][0]['business_steps'].append({'action':'返回首页','expected':'显示首页导航'})
        document=bridge.business_document(business)
        binding=bindings_sample()
        binding['bindings'][0]['steps'].append({'business_step':2,'operations':[],'blocked_reason':'返回按钮定位待确认'})
        result=bridge.apply_bindings(document,binding)['cases'][0]
        self.assertEqual(len(result['business_steps']),2)
        self.assertEqual(result['business_steps'][0]['automation_status'],'candidate')
        self.assertEqual(result['business_steps'][1]['automation_status'],'unbound')
        self.assertEqual(result['business_steps'][1]['expected'],'显示首页导航')
        self.assertIn('第 2 步',result['blocked_reason'])
        self.assertIsNone(result['plan'])
        # 部分匹配用例可携带候选步骤部分执行（ai_incomplete），但执行受阻不会记为通过。
        preview=case_runner.preview(bridge.book({'cases':[result]}),{})
        self.assertEqual(preview['ready'],1)
        self.assertTrue(preview['cases'][0]['partial_reason'])
    def test_full_binding_reuses_existing_executor_and_preserves_business(self):
        result=bridge.apply_bindings(bridge.business_document(business_sample()),bindings_sample())
        self.assertEqual(case_runner.preview(bridge.book(result),{})['ready'],1)
        self.assertEqual(result['cases'][0]['business_steps'][0]['expected'],'出现设置入口')
    def test_binding_failure_does_not_discard_business_plan(self):
        with patch.object(bridge,'ask',side_effect=[business_sample(),ValueError('quota')]):
            result=bridge.generate({'outline':'进入我的页面'})
        self.assertEqual(len(result['cases'][0]['business_steps']),1)
        self.assertIn('匹配未完成',result['cases'][0]['blocked_reason'])
        self.assertIsNone(result['cases'][0]['plan'])
    def test_invalid_binding_is_local_to_step(self):
        response=bindings_sample();response['bindings'][0]['steps'][0]['operations']=[{'action':'shell','value':'arbitrary'}]
        result=bridge.apply_bindings(bridge.business_document(business_sample()),response)
        self.assertEqual(result['cases'][0]['business_steps'][0]['automation_status'],'unbound')
        self.assertIsNone(result['cases'][0]['plan'])
    def test_requires_depending_on_other_case_state_is_rejected_with_navigation_guidance(self):
        document=bridge.business_document({'cases':[
            {'title':'进入语言设置页','priority':'P1','precondition':'已登录，位于首页','expected':'语言设置页展示可切换语言',
             'business_steps':[{'action':'在主页底部点击我的，进入通用设置后点击语言','expected':'进入语言设置页'}]},
            {'title':'将语言切换回中文','priority':'P1','precondition':'已登录且当前语言为非中文','expected':'界面恢复中文',
             'business_steps':[{'action':'在语言设置页点击中文','expected':'界面恢复中文'}]}]})
        bindings={'bindings':[
            {'case_id':1,'requires':[],'steps':[{'business_step':1,'operations':[
                {'action':'tap','value':'我的'},{'action':'tap','value':'语言'},
                {'action':'assert','value':'您可以切换当前应用语言'}],'blocked_reason':''}]},
            {'case_id':2,'requires':[{'action':'assert','value':'您可以切换当前应用语言'}],
             'steps':[{'business_step':1,'operations':[
                 {'action':'tap','value':'中文'},{'action':'assert','value':'中文'}],'blocked_reason':''}]}]}
        result=bridge.apply_bindings(document,bindings)
        first,second=result['cases']
        self.assertIsNotNone(first['plan'])
        self.assertIsNone(second['plan'])
        self.assertIn('恢复首页',second['blocked_reason'])
        self.assertIn('导航',second['blocked_reason'])
        self.assertIn('第 1 条',second['blocked_reason'])
    def test_home_anchor_requires_and_own_step_state_are_not_flagged(self):
        document=bridge.business_document(business_sample())
        bindings={'bindings':[{'case_id':1,'requires':[{'action':'assert','value':'首页'}],
                               'steps':[{'business_step':1,'operations':[
                                   {'action':'tap','value':'我的'},{'action':'assert','value':'设置'}],'blocked_reason':''}]}]}
        result=bridge.apply_bindings(document,bindings)
        self.assertIsNotNone(result['cases'][0]['plan'])
        self.assertEqual(result['cases'][0]['blocked_reason'],'')
    def test_destructive_business_scenario_retained_without_execution(self):
        document=business_sample();document['cases'][0]['title']='退出账号';document['cases'][0]['business_steps']=[{'action':'在测试账号设置页点击退出并确认','expected':'回到登录页'}]
        result=bridge.apply_bindings(bridge.business_document(document),{'bindings':[]})
        self.assertEqual(result['cases'][0]['title'],'退出账号')
        self.assertEqual(len(result['cases'][0]['business_steps']),1)
        self.assertIsNone(result['cases'][0]['plan'])

class SeparatePlanningStagesTests(unittest.TestCase):
    def test_business_button_uses_one_model_request(self):
        with patch.object(bridge,'ask',return_value=business_sample()) as ask:
            doc=bridge.generate({'outline':'检查附近门店','auto_bind':False})
            self.assertEqual(ask.call_count,1)
            self.assertEqual(len(doc['cases'][0]['business_steps']),1)
            self.assertIsNone(doc['cases'][0]['plan'])
    def test_binding_button_preserves_business_and_uses_one_request(self):
        document=bridge.business_document(business_sample())
        with patch.object(bridge,'ask',return_value=bindings_sample()) as ask:
            doc=bridge.generate({'outline':'检查我的页面','auto_bind':False,'binding_only':True,'document':document})
            self.assertEqual(ask.call_count,1)
            self.assertIsNotNone(doc['cases'][0]['plan'])
            self.assertEqual(doc['cases'][0]['business_steps'][0]['action'],document['cases'][0]['business_steps'][0]['action'])

class BindingDiagnosticsTests(unittest.TestCase):
    def test_structured_binding_response_is_supported(self):
        payload=bindings_sample()
        self.assertEqual(bridge.extract_response({'structured_output':payload}),payload)
        self.assertEqual(bridge.extract_response({'type':'result','result':payload}),payload)

    def test_failed_binding_replaces_every_placeholder_reason(self):
        doc=bridge.business_document(business_sample())
        with patch.object(bridge,'ask',side_effect=ValueError('AI 未返回有效 JSON')):
            result=bridge.generate({'outline':'打开我的','binding_only':True,'document':doc})
        step=result['cases'][0]['business_steps'][0]
        self.assertIn('AI 未返回有效 JSON',step['automation_reason'])
        self.assertNotIn('尚未匹配',step['automation_reason'])
        self.assertIsNone(result['cases'][0]['plan'])

    def test_wrong_schema_is_reported_as_binding_failure(self):
        doc=bridge.business_document(business_sample())
        with patch.object(bridge,'ask',return_value=business_sample()):
            result=bridge.generate({'outline':'打开我的','binding_only':True,'document':doc})
        self.assertIn('缺少 bindings',result['cases'][0]['business_steps'][0]['automation_reason'])

    def test_missing_case_has_specific_model_response_diagnostic(self):
        result=bridge.apply_bindings(bridge.business_document(business_sample()),{'bindings':[]})
        self.assertIn('未返回第 1 条用例',result['cases'][0]['business_steps'][0]['automation_reason'])

class JSONRecoveryTests(unittest.TestCase):
    def test_complete_object_inside_explanation_is_extracted(self):
        payload=bindings_sample()
        self.assertEqual(bridge.parse_json('下面是匹配结果：\n```JSON\n'+json.dumps(payload)+'\n```\n以上为完整结果。'),payload)

    def test_braces_and_escaped_quotes_inside_text_are_preserved(self):
        payload=bindings_sample();payload['bindings'][0]['steps'][0]['operations'][0]['value']='按钮 {name} "详情"'
        self.assertEqual(bridge.parse_json('结果：'+json.dumps(payload,ensure_ascii=False)+' 完毕'),payload)

    def test_truncated_json_is_rejected_without_fabricating_steps(self):
        with self.assertRaisesRegex(ValueError,'不完整'):bridge.parse_json(json.dumps(bindings_sample())[:-5])

    def test_multiple_plans_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'多份'):bridge.parse_json(json.dumps(bindings_sample())+'\n'+json.dumps(bindings_sample()))

    def test_invalid_response_retries_once_and_keeps_original_business(self):
        document=bridge.business_document(business_sample())
        with patch.object(bridge,'ask',side_effect=['not JSON',bindings_sample()]) as ask:
            result=bridge.generate({'outline':'检查我的页面','binding_only':True,'document':document})
        self.assertEqual(ask.call_count,2)
        self.assertIsNotNone(result['cases'][0]['plan'])
        self.assertEqual(result['cases'][0]['business_steps'][0]['action'],document['cases'][0]['business_steps'][0]['action'])

    def test_two_invalid_responses_stop_without_more_retries(self):
        with patch.object(bridge,'ask',return_value='not JSON') as ask:
            result=bridge.generate({'outline':'检查我的页面','binding_only':True,'document':bridge.business_document(business_sample())})
        self.assertEqual(ask.call_count,2)
        self.assertIsNone(result['cases'][0]['plan'])
        self.assertIn('JSON',result['cases'][0]['business_steps'][0]['automation_reason'])

class ContradictoryPlanTests(unittest.TestCase):
    def test_initial_route_assertions_must_be_consistent_before_navigation(self):
        with self.assertRaisesRegex(ValueError,'矛盾'):
            bridge.checked_plan({'requires':[{'action':'assert_route','value':'/main'}],'steps':[{'action':'assert_route','value':'/login'},{'action':'tap','value':'登录'},{'action':'assert_route','value':'/main'}]})
        self.assertTrue(bridge.checked_plan({'requires':[{'action':'assert_route','value':'/main'}],'steps':[{'action':'tap','value':'我的'},{'action':'assert_route','value':'/my'}]}))
    def test_business_data_placeholders_cannot_be_typed_literally(self):
        with self.assertRaisesRegex(ValueError,'尚未绑定'):
            bridge.checked_plan({'steps':[{'action':'input','value':'门店','text':'${TEST_STORE}'},{'action':'assert','value':'成功'}]})

class BindingBatchTests(unittest.TestCase):
    def test_timeout_isolated_and_completed_batches_published_in_original_order(self):
        import copy
        document={'cases':[]}
        for n in range(12):
            row=copy.deepcopy(business_sample()['cases'][0]);row['title']='页面'+str(n);document['cases'].append(row)
        calls=[];drafts=[]
        def ask(prompt,*args,**kwargs):
            calls.append(prompt)
            if len(calls) in (2,5):raise ValueError('AI 请求超过 180 秒')
            size=5 if len(calls)==1 else 1
            return json.dumps({'bindings':[{'case_id':n+1,'requires':[],'steps':[{'business_step':1,'operations':[{'action':'assert','value':'首页'}],'blocked_reason':''}]} for n in range(size)]})
        def progress(*args):pass
        progress.publish_draft=lambda d:drafts.append(copy.deepcopy(d))
        with patch.object(bridge,'ask',side_effect=ask):
            result=bridge.generate({'outline':'逐页检查','binding_only':True,'document':document},progress)
        self.assertEqual(len(calls),9)
        self.assertEqual([r['title'] for r in result['cases']],[r['title'] for r in document['cases']])
        self.assertTrue(all(r['plan'] for n,r in enumerate(result['cases']) if n!=7))
        self.assertIn('180',result['cases'][7]['blocked_reason'])
        self.assertTrue(any(d['cases'][0]['plan'] for d in drafts))

class AdaptiveBindingTests(unittest.TestCase):
    def test_complex_cases_start_as_single_requests(self):
        import copy
        row=copy.deepcopy(business_sample()['cases'][0]);row['business_steps']*=4
        doc={'cases':[copy.deepcopy(row),copy.deepcopy(row)]};prompts=[]
        def ask(prompt,*args,**kwargs):
            start=prompt.index('业务计划：\n')+len('业务计划：\n');data,_=json.JSONDecoder().raw_decode(prompt[start:]);prompts.append(len(data['cases']));return {'bindings':[]}
        with patch.object(bridge,'ask',side_effect=ask):result=bridge.generate({'outline':'保留原步骤','binding_only':True,'document':doc})
        self.assertEqual(prompts,[1,1]);self.assertEqual(len(result['cases']),2)
    def test_bulk_timeout_changes_all_future_batches_to_single_requests(self):
        import copy
        doc={'cases':[copy.deepcopy(business_sample()['cases'][0]) for _ in range(12)]};sizes=[]
        def ask(prompt,*args,**kwargs):
            start=prompt.index('业务计划：\n')+len('业务计划：\n');data,_=json.JSONDecoder().raw_decode(prompt[start:]);sizes.append(len(data['cases']))
            if len(sizes)==1:raise ValueError('AI 请求超过 180 秒')
            return {'bindings':[]}
        with patch.object(bridge,'ask',side_effect=ask):result=bridge.generate({'outline':'保留原步骤','binding_only':True,'document':doc})
        self.assertEqual(sizes,[5]+[1]*12);self.assertEqual(len(result['cases']),12)
