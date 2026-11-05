import time,unittest
from unittest.mock import Mock,patch
import automation,case_runner,app

class NavigationLogTests(unittest.TestCase):
    def explorer(self,routes):
        e=automation.Explorer.__new__(automation.Explorer)
        e.route_reader=Mock();e.route_reader.read.side_effect=routes
        e.logs=[];e.log=e.logs.append
        return e
    def test_route_transition_logged_with_duration(self):
        e=self.explorer(['/language'])
        e._route_track=('/main',time.monotonic()-2.4)
        self.assertEqual(e._note_route('source'),'source')
        self.assertEqual(len(e.logs),1)
        self.assertIn('页面跳转：/main → /language',e.logs[0])
        self.assertIn('页面打开耗时',e.logs[0])
    def test_same_route_and_first_observation_are_silent(self):
        e=self.explorer(['/main','/main',''])
        e._note_route('a');e._note_route('b');e._note_route('c')
        self.assertEqual(e.logs,[])
    def test_settled_timeout_reports_possible_stall(self):
        e=automation.Explorer.__new__(automation.Explorer)
        e.route_reader=None;e.logs=[];e.log=e.logs.append;e.stopped=lambda:False
        source='<hierarchy><node class="android.widget.ProgressBar" package="test.app"/><node text="加载中" package="test.app"/></hierarchy>'
        e.source=lambda:source
        with patch.object(automation.time,'sleep'):
            e.settled_source(timeout=0)
        self.assertTrue(any('可能卡住或加载异常' in line for line in e.logs))

class ApiNoteTests(unittest.TestCase):
    def test_failure_reason_includes_observed_api(self):
        note=case_runner.api_note({'method':'POST','path':'/robot/call','http_status':500,'code':610001})
        self.assertIn('最近接口：POST /robot/call',note)
        self.assertIn('HTTP 500',note);self.assertIn('业务码 610001',note)
    def test_network_error_is_included_and_empty_event_is_silent(self):
        self.assertIn('网络错误 timeout',case_runner.api_note({'method':'GET','path':'/x','error':'timeout'}))
        self.assertEqual(case_runner.api_note(None),'')

class BatchFinalizeTests(unittest.TestCase):
    def test_stopped_job_gets_explicit_batch_end_marker(self):
        app.JOBS['t1']={'id':'t1','status':'stopped','stop_requested':True,'logs':['收到停止请求，正在中断操作并清理测试资源。']}
        try:
            app.finalize_batch(['t1'])
            self.assertEqual(app.JOBS['t1']['logs'][-1],'批次已全部结束，测试资源清理完成。')
            self.assertNotIn('stop_requested',app.JOBS['t1'])
            app.finalize_batch(['t1'])
            self.assertEqual(sum('批次已全部结束' in l for l in app.JOBS['t1']['logs']),1)
        finally:app.JOBS.pop('t1',None)
    def test_running_and_missing_jobs_are_left_alone(self):
        app.JOBS['t2']={'id':'t2','status':'running','logs':[]}
        try:
            app.finalize_batch(['t2','missing'])
            self.assertEqual(app.JOBS['t2']['logs'],[]);self.assertNotIn('批次已全部结束',app.JOBS['t2']['logs'])
        finally:app.JOBS.pop('t2',None)

class NoiseFilterTests(unittest.TestCase):
    def test_click_level_noise_is_filtered_but_stage_logs_kept(self):
        for line in ('点击方式 native-gesture-v2：登录 @540,1295','隐私确认原生点击坐标：1,2','等待中页面：输入框[]','关闭引导弹层：下一步','收起键盘，等待账号输入。'):
            self.assertTrue(app.NOISE_LOG_PATTERN.match(line),line)
        for line in ('页面跳转：/login → /main（页面打开耗时 2.1 秒）','执行用例 AI:1：登录','断言通过：登录成功','用例结果 AI:1：fail / 断言失败 · 未出现预期文案','任务异常：连接中断','系统权限弹窗默认允许：允许'):
            self.assertFalse(app.NOISE_LOG_PATTERN.match(line),line)
    def test_error_lines_match_frontend_red_pattern(self):
        red=app.re.compile(r'异常|错误|失败|受阻|中断|超时|卡住|crash|error|exception|服务报错|HTTP 5|网络错误',app.re.I)
        for line in ('任务异常：连接中断','用例结果 AI:2：fail / 断言失败 · 未出现预期文案','当前页面不属于被测 App 或自动化连接已中断','页面等待超过 15 秒仍未稳定，可能卡住或加载异常。','最近接口：POST /robot/call，HTTP 500','保存接口网络失败：timeout（网络错误 timeout）'):
            self.assertRegex(line,red)

if __name__=='__main__':unittest.main()
