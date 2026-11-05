import unittest
from unittest.mock import Mock,patch
import web_save,case_runner

class WebSaveTests(unittest.TestCase):
    def step(self):return {'action':'web_save','by':'css','value':'#submit','api':{'method':'POST','path':'/api/repair/save','codes':[0],'equals':{'data.saved':True}}}
    def web(self,events):
        web=Mock();web.e.base='/session/test';web.e.stopped.return_value=False
        web.js.side_effect=[True,events,True]
        return web
    def test_single_click_requires_http_and_business_success_and_field_evidence(self):
        web=self.web([{'status':200,'code':0,'fields':{'data.saved':True}}])
        result=web_save.perform(web,self.step(),'button')
        self.assertTrue(result['clicked_once']);self.assertEqual(result['api']['code'],0)
        web.e.call.assert_called_once_with('POST','/session/test/element/button/click',{})
        self.assertIn('restore',web.js.call_args.args[0])
    def test_business_failure_and_field_mismatch_cannot_pass(self):
        for event in [{'status':500,'code':0},{'status':200,'code':1},{'status':200,'code':0,'fields':{'data.saved':False}}]:
            with self.assertRaises(AssertionError):web_save.perform(self.web([event]),self.step(),'button')
    def test_missing_binding_and_sensitive_response_fields_prevent_click(self):
        for api in [{},{'method':'POST','path':'/api/repair/save','equals':{'data.token':'secret'}}]:
            web=self.web([])
            with self.assertRaises(ValueError):web_save.perform(web,dict(self.step(),api=api),'button')
            web.e.call.assert_not_called()
    def test_uncertain_click_is_not_retried_and_observer_is_removed(self):
        web=self.web([]);web.e.call.side_effect=RuntimeError('window closed')
        with self.assertRaises(RuntimeError):web_save.perform(web,self.step(),'button')
        self.assertEqual(web.e.call.call_count,1)
        self.assertIn('restore',web.js.call_args.args[0])
    def test_secure_or_device_interfaces_still_require_dedicated_flow(self):
        for path in ['/api/auth/login','/api/robot/task/start','/api/user/delete']:
            with self.assertRaises(ValueError):case_runner.validate_plan({'steps':[dict(self.step(),api={'method':'POST','path':path,'codes':[0]})]})

class WebObserverScriptTests(unittest.TestCase):
    def test_fetch_and_xhr_observe_only_bound_responses_and_restore_hooks(self):
        import subprocess,json,shutil
        from pathlib import Path
        node=shutil.which('node') or '/Users/apple/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
        if not Path(node).is_file():self.skipTest('Node unavailable')
        script=r'''
const assert=require('node:assert/strict');global.window=global;global.location={href:'https://qa.example/form'};
class XHR {open(method,url){this.method=method;this.url=url}addEventListener(name,fn){this.listener=fn}send(){this.status=200;this.responseType='json';this.response={code:0,data:{saved:true,token:'secret-token'}};if(this.listener)this.listener()}}
global.XMLHttpRequest=XHR;global.fetch=async()=>({status:200,clone:()=>({text:async()=>JSON.stringify({code:0,data:{saved:true,password:'secret-password'}})})});
const oldFetch=fetch,oldOpen=XHR.prototype.open,oldSend=XHR.prototype.send;
const before=new XHR();before.open('POST','/api/repair/save');
new Function(INSTALL)('proof','POST','/api/repair/save',['data.saved']);
before.send();assert.equal(proof.events.length,0);
let other=new XHR();other.open('POST','/api/other');other.send();assert.equal(proof.events.length,0);
let matching=new XHR();matching.open('POST','/api/repair/save');matching.send('private-request');assert.equal(proof.events.length,1);
(async()=>{await fetch('/api/repair/save',{method:'POST',body:'private-request'});await new Promise(r=>setImmediate(r));assert.equal(proof.events.length,2);assert.deepEqual(proof.events[0],{status:200,code:0,fields:{'data.saved':true}});assert(!JSON.stringify(proof.events).includes('secret'));assert(!JSON.stringify(proof.events).includes('private-request'));proof.restore();assert.equal(fetch,oldFetch);assert.equal(XHR.prototype.open,oldOpen);assert.equal(XHR.prototype.send,oldSend);assert.equal(global.proof,undefined)})().catch(e=>{console.error(e);process.exitCode=1});
'''.replace('new Function(INSTALL)','new Function('+json.dumps(web_save.INSTALL)+')')
        result=subprocess.run([node,'-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
