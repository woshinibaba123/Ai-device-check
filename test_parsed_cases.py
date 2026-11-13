import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import parsed_cases
import excel_plan_cache
import case_runner
import codebuddy_bridge as bridge
from excel_execution_policy import POLICY


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=parsed_cases.Store(self.root/'.runtime/parsed-case-library')
        self.plan={'execution_policy':POLICY,'requires':[],'steps':[{'action':'tap','value':'我的'},{'action':'assert','value':'设置'}]}
        self.source={'path':'/deleted/cases.xlsx','cases':[{'id':'Sheet:2','title':'打开设置','steps':'点击我的','expected':'设置入口存在','priority':'P1','precondition':'当前账号已登录','test_data':'测试值'}]}
        self.result={'excel_plan_id':'a'*32,'binding_schema':excel_plan_cache.VERSION,'cases':[{'id':'Sheet:2','sheet':'Sheet','row':2,'title':'打开设置','plan':self.plan,'business_steps':[{'action':'点击我的','expected':'设置入口存在'}]}]}
        self.suite=self.store.save_generation(self.result,self.source,{'model':'test-model','source':'/project','login':{'password':'SECRET'},'key':'API_SECRET','excel_observation_mode':True})
    def test_persists_and_runs_without_original_excel(self):
        store=parsed_cases.Store(self.store.directory);book=store.book(self.suite['id'],self.suite['revision'])
        self.assertEqual(case_runner.preview(book,{})['ready'],1)
        self.assertEqual(json.loads(book['cases'][0]['plan_text'])['execution_policy'],POLICY)
        self.assertTrue(book['ai'])
        saved=self.store.path(self.suite['id']).read_text()
        self.assertNotIn('SECRET',saved);self.assertNotIn('API_SECRET',saved)
    def test_text_edits_autosave_and_invalidate_only_business_changes(self):
        saved=self.store.update_case(self.suite['id'],self.suite['revision'],'Sheet:2',{'title':'新标题'})
        self.assertEqual(saved['cases'][0]['plan'],self.plan)
        saved=self.store.update_case(saved['id'],saved['revision'],'Sheet:2',{'steps':'点击消息'})
        self.assertTrue(saved['cases'][0]['needs_reanalysis']);self.assertIsNone(saved['cases'][0]['plan'])
        self.assertEqual(self.store.get(saved['id'])['cases'][0]['steps'],'点击消息')
        self.assertEqual(case_runner.preview(self.store.book(saved['id']),{})['ready'],0)
        saved=self.store.update_case(saved['id'],saved['revision'],'Sheet:2',{'plan':self.plan})
        self.assertFalse(saved['cases'][0]['needs_reanalysis'])
    def test_group_uses_excel_filename_and_logs_metadata_without_input_values(self):
        self.assertEqual(self.suite['name'],'cases.xlsx')
        self.assertEqual(self.suite['source_filename'],'cases.xlsx')
        saved=self.store.update_case(self.suite['id'],self.suite['revision'],'Sheet:2',{'test_data':'PRIVATE_INPUT_VALUE'})
        logs=self.store.logs(saved['id'])
        self.assertEqual(logs[-1]['action'],'case_updated')
        self.assertEqual(logs[-1]['fields'],['test_data'])
        self.assertNotIn('PRIVATE_INPUT_VALUE',json.dumps(logs))
        self.assertEqual(logs[-1]['excel_name'],'cases.xlsx')

    def test_history_filename_recovered_by_fingerprint_only(self):
        import hashlib
        path=self.root/'真正的Excel名称.xlsx';path.write_bytes(b'original workbook bytes')
        data=copy.deepcopy(self.result);data['excel_plan_id']='c'*32;data['fingerprint']=hashlib.sha256(path.read_bytes()).hexdigest()
        suite=self.store.save_generation(data,{'path':'历史Excel解析-cccccccc'}, {})
        self.assertEqual(self.store.recover_sources([path]),[suite['id']])
        saved=self.store.get(suite['id']);self.assertEqual(saved['name'],path.name)
        self.assertEqual(saved['source_filename'],path.name)
        self.assertEqual(self.store.logs(suite['id'])[-1]['action'],'source_recovered')
        path.write_bytes(b'different workbook')
        self.assertEqual(self.store.recover_sources([path]),[])

    def test_deleted_group_retains_operation_log(self):
        self.store.delete(self.suite['id'],self.suite['revision'])
        logs=parsed_cases.Store(self.store.directory).logs(self.suite['id'])
        self.assertEqual(logs[-1]['action'],'suite_deleted')

    def test_invalid_plan_does_not_overwrite_saved_revision(self):
        with self.assertRaises(ValueError):self.store.update_case(self.suite['id'],self.suite['revision'],'Sheet:2',{'plan':{'steps':[{'action':'invented'}]}})
        self.assertEqual(self.store.get(self.suite['id'])['revision'],self.suite['revision'])
    def test_stale_revision_does_not_overwrite_edits(self):
        self.store.rename(self.suite['id'],self.suite['revision'],'已修改名称')
        with self.assertRaises(parsed_cases.Conflict):self.store.update_case(self.suite['id'],self.suite['revision'],'Sheet:2',{'title':'旧窗口'})
        self.assertEqual(self.store.get(self.suite['id'])['name'],'已修改名称')
    def test_background_generation_preserves_manual_edits_and_deletions(self):
        current=self.store.update_case(self.suite['id'],self.suite['revision'],'Sheet:2',{'title':'人工编辑'})
        saved=self.store.save_generation(self.result,self.source,{})
        self.assertEqual(saved['cases'][0]['title'],'人工编辑')
        self.store.delete(saved['id'],saved['revision'],'Sheet:2')
        saved=self.store.save_generation(self.result,self.source,{})
        self.assertEqual(saved['cases'],[])
    def test_deleted_suite_is_not_reimported(self):
        self.store.delete(self.suite['id'],self.suite['revision'])
        self.assertIsNone(self.store.save_generation(self.result,self.source,{}))
        with self.assertRaises(ValueError):self.store.get(self.suite['id'])
    def test_selected_cases_and_path_validation(self):
        with self.assertRaises(ValueError):self.store.get('../secret')
        with self.assertRaises(ValueError):self.store.book(self.suite['id'],case_ids=['missing'])
        self.assertEqual(len(self.store.book(self.suite['id'],case_ids=['Sheet:2'])['cases']),1)
    def test_import_old_result_is_editable_but_requires_reanalysis(self):
        cache=self.root/'old';cache.mkdir();data=copy.deepcopy(self.result);data['excel_plan_id']='b'*32;data.pop('binding_schema')
        (cache/('b'*32+'.json')).write_text(json.dumps(data));self.store.import_existing(cache)
        old=next(row for row in self.store.listing() if row['source_plan_id']=='b'*32)
        self.assertEqual(old['ready'],0)
        self.store.import_existing(cache);self.assertEqual(len(self.store.listing()),2)
    def test_reanalysis_updates_selected_case_and_preserves_original_description(self):
        settings={'parsed_library_id':self.suite['id'],'parsed_revision':self.suite['revision'],'parsed_case_ids':['Sheet:2'],'_parsed_store':str(self.store.directory)}
        def generated(cfg,progress):
            row=copy.deepcopy(cfg['document']['cases'][0]);row.update(plan=self.plan,blocked_reason='');return {'cases':[row]}
        with patch.object(bridge,'generate',side_effect=generated):result=parsed_cases.reanalyze(settings,lambda *args:None)
        saved=self.store.get(result['library_id']);self.assertEqual(saved['cases'][0]['steps'],'点击我的')
        self.assertEqual(saved['cases'][0]['plan'],self.plan)
        actions=[event['action'] for event in self.store.logs(saved['id'])]
        self.assertIn('analysis_started',actions);self.assertIn('analysis_completed',actions)
    def test_analysis_cannot_overwrite_concurrent_edit(self):
        def generated(cfg,progress):
            self.store.update_case(self.suite['id'],self.suite['revision'],'Sheet:2',{'title':'分析期间修改'})
            row=copy.deepcopy(cfg['document']['cases'][0]);row.update(plan=self.plan,blocked_reason='');return {'cases':[row]}
        with patch.object(bridge,'generate',side_effect=generated),self.assertRaises(parsed_cases.Conflict):
            parsed_cases.reanalyze({'parsed_library_id':self.suite['id'],'parsed_revision':self.suite['revision'],'_parsed_store':str(self.store.directory)},lambda *args:None)
        self.assertEqual(self.store.get(self.suite['id'])['cases'][0]['title'],'分析期间修改')
        self.assertEqual(self.store.logs(self.suite['id'])[-1]['action'],'analysis_failed')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        import app,threading,urllib.request
        from http.server import ThreadingHTTPServer
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.patch=patch.object(app,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.store=parsed_cases.Store(self.root/'.runtime/parsed-case-library')
        self.suite=self.store.save_generation({'excel_plan_id':'a'*32,'binding_schema':excel_plan_cache.VERSION,'cases':[{'id':'Sheet:2','title':'查看设置','plan':{'steps':[{'action':'assert','value':'设置'}]}}]},
            {'path':'cases.xlsx','cases':[{'id':'Sheet:2','steps':'查看设置','expected':'有设置入口','priority':'P1'}]}, {})
    def request(self,path,data=None,origin=None):
        import urllib.request
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**({'Origin':origin} if origin else {})})
        with self.opener.open(req,timeout=5) as r:return json.load(r)
    def test_listing_update_preview_and_delete(self):
        self.assertEqual(len(self.request('/api/parsed-cases')),1)
        saved=self.request('/api/parsed-cases/update',{'id':self.suite['id'],'revision':self.suite['revision'],'case_id':'Sheet:2','changes':{'title':'自动保存'}})
        preview=self.request('/api/cases/preview',{'library_id':saved['id'],'library_revision':saved['revision']})
        self.assertEqual(preview['ready'],1);self.assertEqual(preview['cases'][0]['title'],'自动保存')
        logs=self.request('/api/parsed-cases/logs/'+saved['id'])
        self.assertEqual(logs['events'][-1]['action'],'case_updated')
        self.request('/api/parsed-cases/delete',{'id':saved['id'],'revision':saved['revision']})
        self.assertEqual(self.request('/api/parsed-cases'),[])
    def test_conflict_and_foreign_origin_are_rejected(self):
        import urllib.error
        data={'id':self.suite['id'],'revision':0,'name':'旧版本'}
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/parsed-cases/update',data)
        self.assertEqual(caught.exception.code,409)
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/parsed-cases/delete',data,'https://example.com')
        self.assertEqual(caught.exception.code,403)
    def test_reanalysis_uses_snapshot_and_filters_settings(self):
        with patch.object(bridge,'start_generation',return_value={'id':'job'}) as generate:
            self.request('/api/parsed-cases/reanalyze',{'id':self.suite['id'],'revision':self.suite['revision'],'case_ids':['Sheet:2'],'password':'MUST_NOT_PERSIST','model':'test'})
        cfg=generate.call_args.args[0];self.assertNotIn('password',cfg);self.assertEqual(cfg['parsed_case_ids'],['Sheet:2'])


if __name__=='__main__':unittest.main()
