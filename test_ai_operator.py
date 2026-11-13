import json
import unittest
from unittest.mock import patch
import ai_operator as op
import cancellation


def node(label='消息', path='/root/button[1]', **kwargs):
    return dict(dict(path=path, enabled=True, kind='Button', label=label, hint='', id='', editable=False, secure=False, clickable=True, scrollable=False, package='app.test', bounds='', value='', checked=False, selected=False), **kwargs)


class Device:
    platform='Android'
    app_package='app.test'
    base='/session/test'
    secrets=['credential-secret']
    def __init__(self):
        self.calls=[]
        self.captures=[]
        self.logs=[]
        self.nodes=[node()]
        self.stop=False
    def source(self):return '<root/>'
    def stopped(self):return self.stop
    def capture(self,*args):self.captures.append(args)
    def log(self,text):self.logs.append(text)
    def find(self,selector):self.calls.append(('find',selector));return 'element'
    def call(self,*args):self.calls.append(args)
    def back(self,nodes):self.calls.append(('back',))
    def scroll(self):self.calls.append(('scroll',))


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.e=Device()
        self.cfg=dict(goal='进入消息',checkpoints=['消息'],share_page=True,max_actions=5,seconds=30,data={'搜索':'local-only-value'},fast_mode=False)
        self.parser=patch.object(op.automation,'parse_ui',side_effect=lambda s:self.e.nodes)
        self.parser.start()
        self.sleeper=patch.object(op.cancellation.Control,'sleep')
        self.sleeper.start()
    def tearDown(self):self.parser.stop();self.sleeper.stop()
    def run_with(self,decisions):
        responses=iter(decisions)
        return op.run(self.e,self.cfg,ask=lambda *a,**kw:next(responses))
    def test_real_target_click_then_completion_is_review(self):
        result=self.run_with([{'action':'tap','target':'n0'},{'action':'done'}])
        self.assertEqual(result['status'],'review')
        self.assertEqual(result['termination'],'goal_checked')
        self.assertEqual(sum(c[0]=='POST' for c in self.e.calls),1)
    def test_missing_checkpoint_cannot_complete(self):
        self.cfg['checkpoints']=['不存在的页面']
        self.assertEqual(self.run_with([{'action':'done'}])['termination'],'needs_review')
    def test_last_allowed_action_still_observed(self):
        self.cfg.update(max_actions=1,checkpoints=['目标页面'])
        def call(*args):
            self.e.calls.append(args)
            self.e.nodes=[node('目标页面')]
        self.e.call=call
        result=self.run_with([{'action':'tap','target':'n0'}])
        self.assertTrue(result['checkpoints'][0]['observed'])
        self.assertTrue(result['steps'][0]['page_changed'])
    def test_invalid_target_never_clicks(self):
        with self.assertRaises(ValueError):self.run_with([{'action':'tap','target':'guessed'}])
        self.assertEqual(self.e.calls,[])
    def test_destructive_target_blocked(self):
        self.e.nodes=[node('删除')]
        with self.assertRaises(ValueError):self.run_with([{'action':'tap','target':'n0'}])
        self.assertEqual(self.e.calls,[])
    def test_no_arbitrary_model_input(self):
        with self.assertRaises(ValueError):self.run_with([{'action':'input','target':'n0','text':'invented','data_key':'unknown'}])
        self.assertEqual(self.e.calls,[])
    def test_page_changes_during_decision_no_click(self):
        self.cfg['max_actions']=1
        def ask(*a,**kw):
            self.e.nodes=[node('另一页')]
            return {'action':'tap','target':'n0'}
        result=op.run(self.e,self.cfg,ask=ask)
        self.assertEqual(self.e.calls,[])
        self.assertEqual(result['steps'][0]['result'],'page_changed_not_executed')
    def test_path_change_invalidates_decision(self):
        self.cfg['max_actions']=1
        def ask(*a,**kw):
            self.e.nodes=[node(path='/root/button[2]')]
            return {'action':'tap','target':'n0'}
        op.run(self.e,self.cfg,ask=ask)
        self.assertEqual(self.e.calls,[])
    def test_repeat_limit(self):
        result=self.run_with([{'action':'tap','target':'n0'}]*3)
        self.assertEqual(result['termination'],'repeated_action')
        self.assertEqual(len(result['steps']),2)
    def test_secure_page_not_sent(self):
        self.e.nodes[0]['secure']=True
        with self.assertRaises(RuntimeError):self.run_with([])
        self.assertEqual(self.e.captures,[])
    def test_outside_app_not_sent(self):
        self.e.nodes[0]['package']='another.app'
        with self.assertRaises(RuntimeError):self.run_with([])
    def test_credentials_and_data_values_not_in_prompt(self):
        self.e.nodes=[node('credential-secret local-only-value')]
        def ask(prompt,*a,**kw):
            self.assertNotIn('credential-secret',prompt)
            self.assertNotIn('local-only-value',prompt)
            self.assertIn('搜索',prompt)
            return {'action':'done'}
        op.run(self.e,self.cfg,ask=ask)
    def test_stop_after_model_prevents_action(self):
        def ask(*a,**kw):
            self.e.stop=True
            return {'action':'tap','target':'n0'}
        with self.assertRaises(cancellation.Cancelled):op.run(self.e,self.cfg,ask=ask)
        self.assertEqual(self.e.calls,[])
    def test_time_limit_after_model_prevents_action(self):
        now=[0]
        def ask(*a,**kw):now[0]=31;return {'action':'tap','target':'n0'}
        result=op.run(self.e,self.cfg,ask=ask,clock=lambda:now[0])
        self.assertEqual(result['termination'],'time_limit')
        self.assertEqual(self.e.calls,[])
    def test_h5_driver_failure_never_native_fallback(self):
        self.e.nodes=[node('web',kind='WebView')]
        with patch.object(op.hybrid_webview,'WebView',side_effect=RuntimeError('driver missing')):
            with self.assertRaises(RuntimeError):self.run_with([])
    def test_consent_and_limits_required(self):
        for updates in ({'share_page':False},{'max_actions':0},{'seconds':0},{'checkpoints':['']}):
            with self.assertRaises(ValueError):op.validate(dict(self.cfg,**updates))

    def test_no_manual_checks_uses_grounded_verification(self):
        self.cfg.pop('checkpoints')
        result=self.run_with([{'action':'done'},{'satisfied':True,'evidence':['消息']}])
        self.assertEqual(result['termination'],'ai_goal_supported')
        self.assertEqual(result['status'],'review')
        self.assertTrue(result['automatic_verification']['supported'])

    def test_invented_completion_evidence_rejected(self):
        self.cfg['checkpoints']=[]
        result=self.run_with([{'action':'done'},{'satisfied':True,'evidence':['不存在的法语页面']}])
        self.assertEqual(result['termination'],'needs_review')

    def test_verifier_uncertainty_not_completed(self):
        self.cfg['checkpoints']=[]
        result=self.run_with([{'action':'done'},{'satisfied':False,'evidence':['消息']}])
        self.assertEqual(result['termination'],'needs_review')


if __name__=='__main__':unittest.main()
