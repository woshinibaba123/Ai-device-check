import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
import module_scripts as modules


RUN_ID = 'a123456789ab'


def write_success(root, document, **overrides):
    folder = Path(root) / 'reports' / RUN_ID
    folder.mkdir(parents=True, exist_ok=True)
    report = {'id':RUN_ID, 'status':'passed', 'finished':'2026-11-09 10:00:00',
              'module_candidate':modules.validate(document),
              'custom_step_results':[{'step':i,'status':'passed'} for i in range(1,len(document['steps'])+1)]}
    report.update(overrides)
    (folder / 'report.json').write_text(json.dumps(report),encoding='utf-8')


def confirmed_save(root, document):
    write_success(root, document)
    return modules.save(root, document, RUN_ID, True)


class ModuleScriptsTests(unittest.TestCase):
    def document(self):
        return {'name':'导航', 'steps':[{'action':'tap','value':'tab'}, {'action':'assert','value':'page'}]}

    def test_content_versions_and_server_side_steps(self):
        with tempfile.TemporaryDirectory() as root:
            d=confirmed_save(root,self.document())
            self.assertEqual(d['id'],confirmed_save(root,self.document())['id'])
            cfg={'module_id':d['id'],'steps':[{'action':'back'}]}
            modules.prepare(root,cfg)
            self.assertEqual(cfg['steps'],d['steps'])
            changed=self.document();changed['steps'][0]['value']='other'
            self.assertNotEqual(d['id'],confirmed_save(root,changed)['id'])
            self.assertEqual(len(modules.listing(root)),2)

    def test_requires_assertion_and_parameter_input(self):
        for steps in ([{'action':'tap','value':'x'}], [{'action':'input','value':'x','text':'secret'},{'action':'assert','value':'y'}]):
            with self.assertRaises(ValueError):modules.validate({'name':'bad','steps':steps})
        with tempfile.TemporaryDirectory() as root:
            doc=confirmed_save(root,{'name':'input','steps':[{'action':'input','value':'field','parameter':'account'},{'action':'assert','value':'done'}]})
            with self.assertRaises(ValueError):modules.prepare(root,{'module_id':doc['id']})
            with self.assertRaises(ValueError):modules.load(root,'../../other')

    def test_waits_then_clicks_without_source(self):
        call=Mock(side_effect=[[],[{'ELEMENT':'new'}],True,True,None]);sleep=Mock()
        result=modules.perform(call,'/session/a',{'action':'tap','value':'tab'}, {},sleep,lambda:False)
        self.assertEqual(result['status'],'passed')
        sleep.assert_called_once_with(.2)
        self.assertEqual(call.call_args.args[1],'/session/a/element/new/click')
        self.assertFalse(any('/source' in c.args[1] for c in call.call_args_list))

    def test_ambiguous_or_transport_failure_never_clicks(self):
        for response in ([{'ELEMENT':'1'},{'ELEMENT':'2'}],RuntimeError('connection lost')):
            call=Mock(side_effect=response if isinstance(response,Exception) else [response])
            with self.assertRaises((AssertionError,RuntimeError)):
                modules.perform(call,'/s',{'action':'tap','value':'x'}, {},Mock(),lambda:False)
            self.assertEqual(call.call_count,1)

    def test_failed_write_is_not_retried(self):
        call=Mock(side_effect=[[{'ELEMENT':'1'}],True,True,RuntimeError('unknown click result')])
        with self.assertRaises(RuntimeError):modules.perform(call,'/s',{'action':'tap','value':'x'}, {},Mock(),lambda:False)
        self.assertEqual(call.call_count,4)

    def test_stop_prevents_any_driver_call(self):
        call=Mock()
        with self.assertRaises(RuntimeError):modules.perform(call,'/s',{'action':'back'}, {},Mock(),lambda:True)
        call.assert_not_called()

class ModuleApiTests(unittest.TestCase):
    def handler(self, path, body=None):
        import app
        import io
        import json
        handler=object.__new__(app.Handler)
        handler.path=path
        handler.server=Mock(server_port=8765)
        raw=json.dumps(body or {}).encode()
        handler.headers={'Content-Length':str(len(raw))}
        handler.rfile=io.BytesIO(raw)
        handler.send_json=Mock()
        handler.send_error=Mock()
        return handler

    def test_save_and_list_via_handler(self):
        import app
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root, patch.object(app,'ROOT',root):
            document={'name':'page','steps':[{'action':'assert','value':'home'}]}
            write_success(root,document)
            h=self.handler('/api/module-scripts',dict(document,run_id=RUN_ID,confirmed=True))
            h.do_POST()
            saved=h.send_json.call_args.args[0]
            self.assertEqual(h.send_json.call_args.args[1],201)
            h=self.handler('/api/module-scripts');h.do_GET()
            self.assertEqual(h.send_json.call_args.args[0][0]['id'],saved['id'])

    def test_rejects_invalid_script_at_api_boundary(self):
        h=self.handler('/api/module-scripts',{'name':'invalid','steps':[{'action':'tap','value':'x'}]})
        h.do_POST()
        self.assertIn('error',h.send_json.call_args.args[0])

    def test_module_load_failure_precedes_device_dispatch(self):
        h=self.handler('/api/batch',{'module_id':'../../bad'})
        h.do_POST()
        self.assertIn('error',h.send_json.call_args.args[0])

class ManualConfirmationTests(unittest.TestCase):
    def document(self):
        return {'name':'导航','steps':[{'action':'assert','value':'home'}]}

    def test_needs_explicit_manual_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            write_success(root,self.document())
            for value in (False,None,'true',1):
                with self.assertRaises(ValueError):modules.save(root,self.document(),RUN_ID,value)
            self.assertEqual(modules.listing(root),[])

    def test_rejects_failed_stopped_review_unfinished_and_partial_runs(self):
        for overrides in ({'status':'failed'},{'status':'stopped'},{'status':'review'},
                          {'finished':None},{'stop_requested':True},{'custom_step_results':[]}):
            with self.subTest(overrides=overrides),tempfile.TemporaryDirectory() as root:
                write_success(root,self.document(),**overrides)
                with self.assertRaises(ValueError):modules.save(root,self.document(),RUN_ID,True)
                self.assertEqual(modules.listing(root),[])

    def test_editing_json_requires_another_run(self):
        with tempfile.TemporaryDirectory() as root:
            write_success(root,self.document())
            changed=self.document();changed['steps'][0]['value']='other'
            with self.assertRaisesRegex(ValueError,'JSON 已变化'):modules.save(root,changed,RUN_ID,True)

    def test_draft_preparation_does_not_save(self):
        with tempfile.TemporaryDirectory() as root:
            cfg={'module_draft':self.document()}
            modules.prepare(root,cfg)
            self.assertEqual(cfg['module_script']['status'],'trial')
            self.assertEqual(modules.listing(root),[])
            self.assertFalse((Path(root)/'.runtime/module-scripts').exists())

    def test_legacy_unconfirmed_modules_are_not_runnable_or_listed(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'.runtime/module-scripts';folder.mkdir(parents=True)
            identifier='a'*24
            (folder/(identifier+'.json')).write_text(json.dumps(self.document()))
            self.assertEqual(modules.listing(root),[])
            with self.assertRaisesRegex(ValueError,'尚未手动确认'):modules.load(root,identifier)

    def test_confirmed_library_persists_run_reference_without_parameters(self):
        with tempfile.TemporaryDirectory() as root:
            saved=confirmed_save(root,self.document())
            loaded=modules.load(root,saved['id'])
            self.assertEqual(loaded['status'],'manually_confirmed')
            self.assertEqual(loaded['confirmation']['run_id'],RUN_ID)
            self.assertEqual(modules.listing(root),[loaded])

    def test_missing_and_path_traversal_run_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            for run_id in (None,'../../report','f'*12):
                with self.assertRaises(ValueError):modules.save(root,self.document(),run_id,True)
