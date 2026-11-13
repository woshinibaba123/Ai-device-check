import unittest
from ai_operator import parse_verification, unvisited_goal_entries

class CompletionReviewTests(unittest.TestCase):
    def test_fenced_review(self):
        self.assertFalse(parse_verification('```json\n{"satisfied":false,"evidence":[]}\n```')['satisfied'])

    def test_invalid_review(self):
        for value in ('{"satisfied":', {'satisfied':'true','evidence':[]}):
            with self.assertRaises(ValueError): parse_verification(value)

    def test_only_executed_entries_count(self):
        controls=[{'text':'排班列表'},{'text':'清洁模式'},{'text':'清洁记录','blocked':True}]
        history=[{'label':'排班列表','action':'tap','result':'page_changed_not_executed'}]
        self.assertEqual(unvisited_goal_entries('排班列表、清洁模式、清洁记录',controls,history),['排班列表','清洁模式'])
        history.append({'label':'排班列表','action':'tap','result':'executed'})
        self.assertEqual(unvisited_goal_entries('排班列表、清洁模式',controls,history),['清洁模式'])

class StatisticsFastPathTests(unittest.TestCase):
    def test_sequence_and_completion(self):
        from ai_operator import local_statistics_step
        page={'controls':[{'id':'w'+str(i),'text':s} for i,s in enumerate(['今日','昨日','七日','机器人名称','清洁记录'])]}
        history=[]
        for label in ['今日','昨日','七日','今日']:
            decision=local_statistics_step('检查今日昨日七日',page,history)
            self.assertEqual(next(c['text'] for c in page['controls'] if c['id']==decision['target']),label)
            history.append(dict(decision,label=label,result='executed'))
        self.assertIsNone(local_statistics_step('检查今日昨日七日',page,history))
        self.assertIsNone(local_statistics_step('仅查看今日',page,[]))

class ScheduleIconTests(unittest.TestCase):
    def test_header_icon_not_month_arrow(self):
        from ai_operator import local_schedule_icon_step
        page={'viewport_width':360,'controls':[{'id':'w0','text':'无文字图标 内嵌图片，位置301,-1'},{'id':'w3','text':'无文字图标 内嵌图片，位置223,57'}]}
        history=[{'action':'tap','label':'排班列表','result':'executed'}]
        step=local_schedule_icon_step('进入排班列表点击右上角图标',page,history)
        self.assertEqual(step['target'],'w0')
        history.append(dict(step,result='executed'))
        self.assertIsNone(local_schedule_icon_step('排班列表右上角',page,history))

class FinalExitTests(unittest.TestCase):
    def test_requires_actual_module_visits(self):
        from ai_operator import final_h5_exit_ready
        goal='排班列表、清洁记录、清洁模式、任务报告设置、详情；最后返回当前门店机器人列表'
        steps=[{'action':'tap','label':s,'result':'executed'} for s in ['排班列表','清洁记录','清洁模式','任务报告设置','详情']]
        self.assertTrue(final_h5_exit_ready(goal,steps))
        self.assertFalse(final_h5_exit_ready(goal,steps[:-1]))
        self.assertFalse(final_h5_exit_ready('查看排班列表',steps))
