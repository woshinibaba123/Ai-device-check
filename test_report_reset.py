import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
import app

class ReportResetTests(unittest.TestCase):
    def run_case(self, offline=False, busy=False, pipeline=False):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'ROOT',Path(tmp)), patch.object(app,'JOBS',{'old':{'id':'old','status':'passed'}}), patch.object(app,'BATCH_RUNNING',threading.Event()):
            folder=Path(tmp)/'reports/old';folder.mkdir(parents=True)
            (folder/'report.json').write_text('{}');(folder/'screen.png').write_bytes(b'test')
            unrelated=Path(tmp)/'keep.txt';unrelated.write_text('keep')
            server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            if busy: app.BATCH_RUNNING.set()
            def remote(*args):
                if offline:raise RuntimeError('offline')
                return {}
            try:
                data={'targets':[{'platform':'Android','device':'mock'}],'bundle':'example.app','steps':[],**({'pipeline_id':'test-pipeline'} if pipeline else {})}
                req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/batch',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with patch.object(app,'request',side_effect=remote), patch.object(app,'run_batch'),patch.object(app.language_pipeline,'owns',return_value=pipeline),patch.object(app.language_pipeline,'active',return_value=pipeline):
                    if offline or busy:
                        with self.assertRaises(urllib.error.HTTPError) as caught:opener.open(req)
                        self.assertEqual(caught.exception.code,400 if offline else 409)
                        self.assertTrue(folder.exists());self.assertIn('old',app.JOBS)
                    else:
                        with opener.open(req) as r:self.assertEqual(r.status,200)
                        self.assertTrue(folder.exists());self.assertIn('old',app.JOBS)
                        self.assertEqual(len(app.JOBS),2)
                self.assertEqual(unrelated.read_text(),'keep')
            finally:server.shutdown();server.server_close()
    def test_language_pipeline_appends_and_preserves_previous_reports(self):self.run_case(pipeline=True)
    def test_successful_start_preserves_old_reports(self):self.run_case()
    def test_invalid_start_preserves_old_reports(self):self.run_case(offline=True)
    def test_cleanup_in_progress_preserves_old_reports(self):self.run_case(busy=True)

class EncodedReportDownloadTests(unittest.TestCase):
    def test_chinese_report_filename_is_served_without_path_escape(self):
        import urllib.parse
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'ROOT',Path(tmp).resolve()):
            folder=Path(tmp)/'reports/group';folder.mkdir(parents=True);(folder/'测试结果.xlsx').write_bytes(b'xlsx-report')
            (Path(tmp)/'secret.txt').write_text('private')
            server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
            op=urllib.request.build_opener(urllib.request.ProxyHandler({}));url='http://127.0.0.1:'+str(server.server_port)
            try:
                with op.open(url+'/reports/group/'+urllib.parse.quote('测试结果.xlsx')) as r:self.assertEqual(r.read(),b'xlsx-report')
                with self.assertRaises(urllib.error.HTTPError):op.open(url+'/reports/group/%2e%2e/%2e%2e/secret.txt')
            finally:server.shutdown();server.server_close()
