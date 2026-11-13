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

class CheckedDOMSubmitTests(unittest.TestCase):
    def test_checked_dom_submit_has_one_click_and_requires_api_success(self):
        web=Mock();web.e.base='/session/test';web.e.stopped.return_value=False
        web.js.side_effect=[True,True,[{'status':200,'code':610000,'fields':{}}],True]
        step={'action':'web_save','by':'css','value':'#repair button.btn-submit','click_mode':'dom_checked','api':{'method':'POST','path':'/api/devops/aftersale/work/order','codes':[610000]}}
        result=web_save.perform(web,step,'submit')
        self.assertTrue(result['clicked_once']);self.assertEqual(result['click_mode'],'dom_checked')
        web.e.call.assert_not_called()
        self.assertEqual(sum(c.args[0]==web_save.CHECKED_DOM_CLICK for c in web.js.call_args_list),1)

    def test_checked_dom_submit_refuses_disabled_and_obscured_controls(self):
        import subprocess,json,shutil
        node=shutil.which('node')
        if not node:self.skipTest('Node required')
        script='const click=new Function('+json.dumps(web_save.CHECKED_DOM_CLICK)+''');
let count=0;const e={isConnected:true,disabled:false,getAttribute:()=>null,getClientRects:()=>[{}],scrollIntoView:()=>{},getBoundingClientRect:()=>({left:0,top:0,width:20,height:20}),contains:()=>false,click:()=>count++};
global.getComputedStyle=()=>({visibility:'visible',display:'block'});global.innerWidth=400;global.innerHeight=800;
global.document={elementFromPoint:()=>e};
const ok=click(e);e.disabled=true;let disabled=false,obscured=false;
try{click(e)}catch{disabled=true}e.disabled=false;document.elementFromPoint=()=>({});try{click(e)}catch{obscured=true}
console.log(JSON.stringify({ok,count,disabled,obscured}));'''
        self.assertEqual(json.loads(subprocess.check_output([node,'-e',script],text=True)),{'ok':True,'count':1,'disabled':True,'obscured':True})

class NestedButtonTests(unittest.TestCase):
    def test_text_span_resolves_to_hit_button(self):
        import subprocess,json,shutil
        node=shutil.which('node')
        if not node:self.skipTest('Node required')
        script = 'const click=new Function('+json.dumps(web_save.CHECKED_DOM_CLICK)+');'+r"""
let count=0;
const button={isConnected:true,disabled:false,getAttribute:()=>null,getClientRects:()=>[{}],scrollIntoView:()=>{},getBoundingClientRect:()=>({left:10,top:10,width:80,height:30}),contains:()=>false,click:()=>count++};
const span={closest:()=>button};
global.getComputedStyle=()=>({visibility:'visible',display:'block'});global.innerWidth=400;global.innerHeight=800;
global.document={elementFromPoint:()=>button};
if(click(span)!==true||count!==1)throw Error('nested button failed');
"""
        subprocess.run([node,'-e',script],check=True,capture_output=True,timeout=10)
