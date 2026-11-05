import json,unittest
from unittest.mock import patch
from automation import Explorer
import case_runner,excel_ai

PATH='/api/merchant/mobile/miniprogram/v2/call/task'
class DispatchTests(unittest.TestCase):
    def execute(self,enabled=True,success=True):
        clicks=[];e=Explorer(lambda *args:None,'s','Android',lambda _:None,lambda *args:None);e.app_package='com.test'
        source='<hierarchy><node class="android.widget.Button" package="com.test" text="首页" clickable="true"/><node class="android.widget.Button" package="com.test" text="呼叫" clickable="true"/></hierarchy>'
        class Probe:
            manifest={'paths':[PATH],'response_fields':[]};last_event=None
            def mark(self):return {'counter':0}
            def check(self,*args):
                if not success:raise AssertionError('业务码失败')
                return {'http_status':200,'code':610000,'request_shape':{'storeId':True,'sceneCode':True,'targetPointId':True,'multiPointCount':0}}
        e.http_probe=Probe()
        plan={'steps':[{'action':'dispatch','value':'呼叫','api':{'method':'POST','path':PATH,'codes':[610000]}}]}
        case={'id':'S:2','sheet':'S','row':2,'title':'呼叫下发','group':'test','priority':'P0','mobile':True,'steps':'点击呼叫','expected':'后台下发成功','precondition':'','plan_text':json.dumps(plan)}
        with patch.object(e,'settled_source',return_value=source),patch.object(e,'tap',side_effect=lambda node:clicks.append(node['label'])):
            result=case_runner.run(e,{'cases':[case]},{'call_acceptance':'backend_only' if enabled else 'full'},lambda _:None,lambda *args:'/proof.png',lambda _:None,lambda:False,lambda _:None)[0]
        return result,clicks
    def test_accepts_one_successful_dispatch_without_motion_assertion(self):
        row,clicks=self.execute();self.assertEqual(row['result'],'pass');self.assertEqual(clicks.count('呼叫'),1)
        self.assertFalse(row['steps'][-1]['robot_motion_verified'])
        self.assertEqual(row['steps'][-1]['acceptance'],'backend_task_accepted_only')
    def test_disabled_acceptance_never_clicks_call(self):
        row,clicks=self.execute(enabled=False);self.assertEqual(row['result'],'fail');self.assertNotIn('呼叫',clicks)
    def test_http_business_failure_never_passes(self):
        self.assertEqual(self.execute(success=False)[0]['result'],'fail')
    def test_only_explicit_call_post_endpoint_is_allowed(self):
        for method,path in [('DELETE',PATH),('POST','/api/robot/cancel'),('POST','/api/auth/login')]:
            with self.assertRaises(ValueError):case_runner.validate_plan({'steps':[{'action':'dispatch','value':'呼叫','api':{'method':method,'path':path,'codes':[0]}}]})
    def test_user_acceptance_override_does_not_edit_original_case(self):
        c={'title':'普通点位与多点任务下发','steps':'1. 下发呼叫任务\n2. 检查App任务、接口结果及机器人接收/执行；在隔离场地结束任务','expected':'仅一次下发；机器人实际接收执行才可算通过；离线给出失败','priority':'P0'}
        d=excel_ai.business_case(c,'backend_only')
        self.assertIn('不验证机器人实际移动',d['expected']);self.assertIn('机器人实际接收执行才可算通过',c['expected'])
        self.assertIn('不发送额外取消',d['business_steps'][1]['action'])

class SelectedLanguageParentTests(unittest.TestCase):
    def test_selected_instrumented_language_parent_proves_child_label_selection(self):
        nodes=[{'label':'devicecheck-language-zh-CN','selected':True,'path':'/root/row[1]','clickable':False,'id':''},{'label':'中文简体','selected':False,'path':'/root/row[1]/text[1]','clickable':True,'id':''},{'label':'English','selected':False,'path':'/root/row[2]/text[1]','clickable':True,'id':''}]
        self.assertTrue(case_runner.find_node(nodes,{'action':'assert_selected','value':'中文简体'})['selected'])
        self.assertIsNone(case_runner.find_node(nodes,{'action':'assert_selected','value':'English'}))
        nodes[0]['label']='普通选中容器'
        self.assertIsNone(case_runner.find_node(nodes,{'action':'assert_selected','value':'中文简体'}))
