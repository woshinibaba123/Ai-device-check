import tempfile, unittest, shutil
from pathlib import Path
from unittest.mock import patch
import app

class ToolTests(unittest.TestCase):
    def test_only_local_credential_free_http_proxy_is_inherited(self):
        for value,expected in [('http://127.0.0.1:7890','http://127.0.0.1:7890'),('http://localhost:7890','http://localhost:7890'),('http://user:secret@localhost:7890',''),('http://external.example:7890',''),('socks5://localhost:7890',''),('http://localhost:invalid','')]:
            with patch('app.urllib.request.getproxies',return_value={'https':value}):
                self.assertEqual(app.local_emulator_proxy(),expected)

    def test_offline_android_is_listed(self):
        def command(args):
            if args[-1] == '-list-avds': return {'ok': True, 'output': 'Medium_Phone'}
            if 'simctl' in args: return {'ok': True, 'output': '{"devices":{}}'}
            return {'ok': True, 'output': 'List of devices attached\n'}
        with patch.object(app, 'command', command):
            self.assertIn('avd:Medium_Phone', [d['id'] for d in app.devices()['devices']])

    def test_source_build_and_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); project = root/'project'; project.mkdir()
            (project/'lib').mkdir();(project/'lib/main.dart').write_text('void main() {}');(project/'lib/main_eng.dart').write_text('void main() {}')
            (project/'pubspec.yaml').write_text('name: example')
            artifact = project/'build/app/outputs/flutter-apk/app-debug.apk'
            artifact.parent.mkdir(parents=True); artifact.write_bytes(b'test')
            app.JOBS['test'] = {'logs': [], 'screenshots': [], 'status': 'running'}
            def request(method, path, data=None):
                if path == '/session':
                    session_apk=Path(data['capabilities']['alwaysMatch']['appium:app'])
                    self.assertTrue(session_apk.is_relative_to(root/'.runtime'))
                    self.assertEqual(session_apk.read_bytes(),b'test')
                    return {'sessionId': 'mock'}
                if path.endswith('/screenshot'): return 'aGVsbG8='
                if path.endswith('/source'):return '<hierarchy><node class="android.widget.Button" text="Home" clickable="true"/></hierarchy>'
            with patch.object(app, 'ROOT', root), patch.object(app.shutil, 'which', return_value='/mock/flutter'), patch.object(app.cancellation.Control, 'run') as run, patch.object(app, 'request', request), patch.object(app.host_runtime,'copy_source',side_effect=lambda src,dst,_:shutil.copytree(src,dst)), patch.object(app.source_navigation,'instrument',side_effect=ValueError('unsupported fixture')):
                run.return_value.returncode = 0
                run.return_value.stdout = run.return_value.stderr = ""
                app.run_job('test', {'platform':'Android', 'device':'mock', 'source':str(project), 'entrypoint':'lib/main_eng.dart', 'steps':[]})
                build_calls=[call for call in run.call_args_list if call.kwargs.get('cwd')==str(root/'.runtime/login-source-test')]
                self.assertEqual(len(build_calls),1)
                self.assertIn('build',build_calls[0].args[0])
                self.assertEqual((project/'lib/main_eng.dart').read_text(),'void main() {}')
            self.assertEqual(app.JOBS['test']['status'], 'passed')

    def test_invalid_source_fails_before_build(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'ROOT',Path(tmp)), patch.object(app.subprocess,'run') as run:
            app.JOBS['invalid']={'logs':[], 'screenshots':[], 'status':'running'}
            app.run_job('invalid',{'platform':'Android','device':'mock','source':tmp})
            run.assert_not_called()
            self.assertEqual(app.JOBS['invalid']['status'],'blocked')

if __name__ == '__main__': unittest.main()

class MatrixTests(unittest.TestCase):
    def test_missing_baseline_never_substitutes(self):
        import matrix
        with patch.object(matrix,'images',return_value=[{'api':'35','package':'system-images;android-35;google_apis;arm64-v8a'}]):
            with self.assertRaisesRegex(ValueError,'未安装'): matrix.resolve_profile({'id':'mi10'})

    def test_explicit_image_is_recorded(self):
        import matrix
        image={'api':'35','package':'system-images;android-35;google_apis;arm64-v8a'}
        with patch.object(matrix,'images',return_value=[image]):
            profile=matrix.resolve_profile({'id':'mi10','image':image['package'],'density':440})
            self.assertEqual(profile['android'],'10')
            self.assertEqual(profile['image']['api'],'35')
            self.assertEqual(profile['density'],440)

    def test_unknown_baseline_requires_explicit_choice(self):
        import matrix
        with self.assertRaisesRegex(ValueError,'待核验'): matrix.resolve_profile({'id':'mi8'})

    def test_batch_continues_after_unexpected_failure(self):
        seen=[]
        def run(jid,cfg):
            seen.append(jid)
            if jid=='first': raise RuntimeError('test failure')
            app.JOBS[jid]['status']='passed'
        for jid in ('first','second'): app.JOBS[jid]={'status':'queued','logs':[]}
        with patch.object(app,'run_job',side_effect=run):
            app.run_batch([(j,{'platform':'Android'}) for j in ('first','second')])
        self.assertEqual(seen,['first','second'])
        self.assertEqual(app.JOBS['first']['status'],'failed')
        self.assertEqual(app.JOBS['second']['status'],'passed')

class BatchAPITests(unittest.TestCase):
    def test_batch_reports_each_missing_environment(self):
        import json,threading,time,urllib.request,matrix
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'ROOT',Path(tmp)), patch.object(app,'JOBS',{}), patch.object(matrix,'images',return_value=[]):
            server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            url='http://127.0.0.1:'+str(server.server_port)
            try:
                data={'targets':[{'profile':{'id':'mi10'}},{'profile':{'id':'mi8'}}], 'app':'/not-installed.apk','steps':[]}
                req=urllib.request.Request(url+'/api/batch',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
                import urllib.error
                with patch.object(app,'request',side_effect=RuntimeError('offline')):
                    with self.assertRaises(urllib.error.HTTPError) as caught: op.open(req)
                self.assertEqual(caught.exception.code,400)
                error=json.load(caught.exception)['error']
                self.assertIn('Appium',error)
                self.assertIn('未安装',error)
                self.assertEqual(app.JOBS,{})
            finally:server.shutdown();server.server_close()

class StreamingRunTests(unittest.TestCase):
    def doc(self,titles):
        return {'cases':[{'title':t,'priority':'P1','precondition':'','description':'点击入口','expected':'出现入口','blocked_reason':'',
                          'plan':{'requires':[],'steps':[{'action':'assert','value':'首页'}]}} for t in titles]}
    def test_stream_case_run_executes_appended_cases_in_order(self):
        import time
        import codebuddy_bridge as bridge
        with patch.object(bridge,'GENERATIONS',{}):
            task={'id':'g1','status':'running','started':time.monotonic(),'changed':time.monotonic(),'history':[],
                  'draft':self.doc(['用例A'])}
            bridge.GENERATIONS['g1']=task
            rounds=[]
            def fake_run(explorer,book,cfg,log,capture,progress,stopped,sleep):
                rounds.append([c['id'] for c in book['cases']])
                if rounds[-1]==['AI:1']:
                    task['draft']=self.doc(['用例A','用例B'])
                    return [{'id':'AI:1','result':'pass','status':'已执行'}]
                task['status']='done'
                return [{'id':'AI:2','result':'skip','status':'已跳过'}]
            cfg={'cases':{},'case_book':None}
            with patch.object(app.case_runner,'run',side_effect=fake_run):
                results=app.stream_case_run(object(),'g1',cfg,lambda x:None,lambda *a:None,lambda r:None,lambda:False,lambda s:None)
            self.assertEqual(rounds,[['AI:1'],['AI:2']])
            self.assertEqual([r['id'] for r in results],['AI:1','AI:2'])
            self.assertEqual([c['id'] for c in cfg['case_book']['cases']],['AI:1','AI:2'])
    def test_stream_case_run_stops_when_generation_fails_without_new_cases(self):
        import time
        import codebuddy_bridge as bridge
        with patch.object(bridge,'GENERATIONS',{}):
            task={'id':'g2','status':'failed','started':time.monotonic(),'changed':time.monotonic(),'history':[],
                  'error':'模型超时','draft':self.doc(['用例A'])}
            bridge.GENERATIONS['g2']=task
            with patch.object(app.case_runner,'run',return_value=[{'id':'AI:1','result':'pass','status':'已执行'}]) as run:
                logs=[]
                results=app.stream_case_run(object(),'g2',{'cases':{},'case_book':None},logs.append,lambda *a:None,lambda r:None,lambda:False,lambda s:None)
            self.assertEqual(run.call_count,1)
            self.assertEqual([r['id'] for r in results],['AI:1'])
            self.assertTrue(any('提前结束' in line for line in logs))

class StreamingBatchAPITests(unittest.TestCase):
    def post(self,url,op,data):
        import json,urllib.request,urllib.error
        req=urllib.request.Request(url+'/api/batch',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        try:
            op.open(req);return None
        except urllib.error.HTTPError as error:
            return error.code,json.load(error)['error']
    def test_ai_generation_submission_validates_task(self):
        import json,threading,time,urllib.request,tempfile
        import codebuddy_bridge as bridge
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'ROOT',Path(tmp)), patch.object(app,'JOBS',{}), patch.object(bridge,'GENERATIONS',{}):
            server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            url='http://127.0.0.1:'+str(server.server_port)
            try:
                body={'test_mode':'ai','ai_generation':'missing','targets':[{'platform':'Android','device':'x'}]}
                code,error=self.post(url,op,body)
                self.assertEqual(code,400);self.assertIn('生成任务不存在',error)
                now=time.monotonic()
                bridge.GENERATIONS['g1']={'id':'g1','status':'running','started':now,'changed':now,'history':[],'draft':{'cases':[]}}
                code,error=self.post(url,op,body|{'ai_generation':'g1'})
                self.assertEqual(code,400);self.assertIn('尚未产出任何用例',error)
            finally:server.shutdown();server.server_close()
