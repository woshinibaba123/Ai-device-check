import unittest
from unittest.mock import Mock,patch
import workflow_coverage as coverage
import uia_health
from automation import Explorer


class CoverageTests(unittest.TestCase):
    def test_report_periods_do_not_substitute_for_date_control(self):
        rows=coverage.requirements('1. /reportRecord 日期、报告类型或设备筛选\n2. 逐一切换当前页面实际提供的日报、周报、月报、年报\n3. 返回首页')
        coverage.record(rows,[{'id':'report_'+k,'status':'observed','evidence':'实际核对当前周期选中状态与统计内容'} for k in ('week','month','year')],1)
        self.assertEqual(rows[1]['status'],'observed')
        self.assertEqual(rows[0]['status'],'pending')
        coverage.record(rows,[{'id':'report_business','status':'observed','evidence':'实际选择送餐报告并恢复全部'}],2)
        self.assertEqual(rows[0]['status'],'pending')
        coverage.record(rows,[{'id':'report_date','status':'observed','evidence':'实际选择上一周并核对后恢复原日期'}],3)
        self.assertEqual(rows[0]['status'],'observed')
        self.assertEqual(rows[-1]['id'],'step_3')

    def test_each_nearby_filter_needs_separate_evidence(self):
        rows=coverage.requirements('1. 检查距离、机型、区域、任务数筛选\n2. 返回首页')
        coverage.record(rows,[{'id':'step_1','status':'observed','evidence':'距离与行政区选择并恢复原条件均成功'}],1)
        self.assertEqual([r['id'] for r in coverage.pending(rows)],['step_1','filter_distance','filter_model','filter_region','filter_task','step_2'])
        self.assertEqual(rows[-1]['id'],'step_2')
        coverage.record(rows,[{'id':'filter_'+key,'status':'observed','evidence':'实际选择、确认结果并恢复原筛选条件'} for key in ('distance','model','region','task')],2)
        self.assertEqual(rows[0]['status'],'observed')
        self.assertEqual(rows[0]['provenance'],'aggregated_explicit_filter_observations')

    def test_provisional_evidence_does_not_pass(self):
        rows=coverage.requirements('1. 核对设备归属')
        coverage.record(rows,[{'id':'step_1','status':'observed','evidence':'设备编号非空，门店归属待后续核对'}],1)
        self.assertEqual(rows[0]['status'],'pending')
        coverage.record(rows,[{'id':'step_1','status':'blocked','evidence':'缺少可用设备，无法核对门店归属'}],2)
        self.assertEqual(rows[0]['status'],'blocked')

    def test_text_timeout_falls_back_without_replaying_action(self):
        import ai_operator
        import visual_flow
        from test_ai_operator import Device
        config={'goal':'检查呼叫任务页面','checkpoints':[],'share_page':True,'max_actions':3,'seconds':90,'data':{}}
        page=({'text':'测试页面','controls':[]},{},'<root/>','fingerprint')
        with patch.object(ai_operator,'observe',return_value=page),patch.object(visual_flow,'step',return_value={'action':'blocked','reason':'无可用机器人'}):
            result=ai_operator.run(Device(),config,ask=Mock(side_effect=ValueError('AI 请求超时')))
        self.assertTrue(any(r['action']=='decision_timeout_to_visual' for r in result['recoveries']))
        self.assertEqual(result['steps'],[])

    def test_repeated_done_claim_cannot_complete_unobserved_workflow(self):
        import ai_operator
        import visual_flow
        from test_ai_operator import Device
        cfg={'goal':'1. 每种源码语言切换\n2. H5检查日、韩、法、泰、繁体','checkpoints':[],'share_page':True,'max_actions':5,'seconds':90,'data':{}}
        with patch.object(ai_operator,'observe',side_effect=TimeoutError('source timeout')),patch.object(visual_flow,'step',return_value={'action':'done','reason':'日语已核对','observations':[{'id':'step_1','status':'observed','evidence':'模型在done时自报通过不能作为证据'}]}),patch.object(ai_operator.cancellation.Control,'sleep'):
            result=ai_operator.run(Device(),cfg)
        self.assertEqual(result['termination'],'incomplete_workflow')
        self.assertTrue(all(r['status']=='pending' for r in result['coverage']))

    def test_japanese_does_not_complete_other_languages_or_h5(self):
        rows=coverage.requirements('1. 每种源码语言切换并检查\n2. H5检查日、韩、法、泰、繁体')
        coverage.record(rows,[{'id':'language_日语','status':'observed','evidence':'日本語已选中并核对根导航和功能入口'}],2)
        self.assertEqual(len(coverage.pending(rows)),6)
        self.assertEqual(rows[2]['provenance'],'visual_model_observation')

    def test_no_evidence_does_not_count(self):
        rows=coverage.requirements('1. 检查登录\n2. 检查H5')
        coverage.record(rows,[{'id':'step_1','status':'observed','evidence':''}],1)
        self.assertEqual(len(coverage.pending(rows)),2)

class HealthTests(unittest.TestCase):
    def test_persistent_d_state_detected_without_appium(self):
        with patch.object(uia_health.subprocess,'run',return_value=Mock(returncode=0,stdout='STAT NAME\nD io.appium.uiautomator2.server\n')) as run,patch.object(uia_health.time,'sleep'):
            self.assertTrue(uia_health.blocked('adb','device'))
            self.assertEqual(run.call_count,2)

    def test_transient_d_state_not_treated_as_blocked(self):
        with patch.object(uia_health.subprocess,'run',side_effect=[Mock(returncode=0,stdout='D io.appium.uiautomator2.server'),Mock(returncode=0,stdout='S io.appium.uiautomator2.server')]),patch.object(uia_health.time,'sleep'):
            self.assertFalse(uia_health.blocked('adb','device'))

    def test_blocked_server_never_receives_source_request(self):
        call=Mock();e=Explorer(call,'sid','Android',Mock(),Mock())
        e.visual_source_fallback=True;e.native_health_probe=lambda:True
        with self.assertRaises(TimeoutError):e.source()
        call.assert_not_called()
