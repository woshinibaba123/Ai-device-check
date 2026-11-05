"""Exercise the real HTTP/Excel/queue plumbing without devices or provider calls."""
import copy,json,tempfile,threading,time,unittest,urllib.request,zipfile
from pathlib import Path
from unittest.mock import patch
import app,case_workbook,excel_ai,language_pipeline
from test_case_workbook import fixture

class LanguagePipelineHTTPTests(unittest.TestCase):
    def test_two_language_plans_reach_queue_with_original_rows_and_keep_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'cases.xlsx';fixture(path)
            with zipfile.ZipFile(path) as z:parts={name:z.read(name) for name in z.namelist()}
            parts['xl/workbook.xml']=parts['xl/workbook.xml'].decode().replace('手机全量','01_中文简体').replace('</sheets>','<sheet name="02_English" sheetId="2" r:id="rId2"/></sheets>').encode()
            parts['xl/_rels/workbook.xml.rels']=parts['xl/_rels/workbook.xml.rels'].decode().replace('</Relationships>','<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>').encode()
            parts['xl/worksheets/sheet2.xml']=parts['xl/worksheets/sheet1.xml']
            with zipfile.ZipFile(path,'w') as z:
                for name,data in parts.items():z.writestr(name,data)
            book=case_workbook.read(path);seen=[]
            old=root/'reports/old/report.json';old.parent.mkdir(parents=True);old.write_text('{}')
            def generated(cfg,progress):
                doc=copy.deepcopy(cfg['document'])
                for row in doc['cases']:row.update(plan={'steps':[{'action':'assert','value':'首页'}]},blocked_reason='')
                return doc
            def run(entries):
                try:
                    for jid,cfg in entries:
                        seen.append((cfg['cases']['sheet'],cfg['language']['code'],[c['id'] for c in app.case_runner.selected_cases(cfg['case_book'],cfg['cases'])]))
                        with app.LOCK:app.JOBS[jid].update(status='passed',finished='done')
                finally:app.BATCH_RUNNING.clear()
            with patch.object(app,'ROOT',root),patch.object(app,'JOBS',{}),patch.object(app,'BATCH_RUNNING',threading.Event()),patch.object(app,'run_batch',side_effect=run),patch.object(app,'request',return_value={}),patch.object(excel_ai,'CACHE',root/'plans'),patch.object(language_pipeline,'ROOT',root),patch.object(language_pipeline,'TASKS',{}),patch.object(language_pipeline,'CONTROLS',{}),patch.object(app.codebuddy_bridge,'generate',side_effect=generated),patch.object(app.codebuddy_bridge,'status',return_value={'busy':False}):
                server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
                threading.Thread(target=server.serve_forever,daemon=True).start()
                api=app.PipelineAPI(server.server_port)
                try:
                    cfg={'excel':{'path':str(path),'fingerprint':excel_ai.fingerprint(book),'priority':'P1'},'execution':{'targets':[{'platform':'Android','device':'mock'}],'bundle':'test.app','languages':{'enabled':True,'selected':[{'code':'zh-CN','choice':'中文简体'},{'code':'en-US','choice':'English'}]}}}
                    result=api.post('/api/language-pipelines',cfg)
                    end=time.monotonic()+5
                    while time.monotonic()<end:
                        task=api.get('/api/language-pipelines/'+result['id'])
                        if task['status'] not in ('running','stopping'):break
                        time.sleep(.02)
                    self.assertEqual(task['status'],'done',task)
                    self.assertEqual(seen,[('01_中文简体','zh-CN',['01_中文简体:6','01_中文简体:7']),('02_English','en-US',['02_English:6','02_English:7'])])
                    self.assertTrue(old.exists());self.assertEqual(len(app.JOBS),2)
                    self.assertEqual(len(list((root/'plans').glob('*.json'))),2)
                    self.assertIn('report',task)
                    report=json.loads((root/task['json_report'].lstrip('/')).read_text())
                    self.assertEqual(report['selected'],4)
                    self.assertEqual(report['passed'],0)  # Mock jobs lack per-case execution evidence.
                    self.assertEqual(len(report['results']),4)
                    self.assertTrue((root/task['workbook'].lstrip('/')).is_file())
                finally:server.shutdown();server.server_close()
