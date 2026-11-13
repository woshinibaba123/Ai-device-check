import unittest
from ai_operator import goal_input_data
class GoalInputTests(unittest.TestCase):
 def test_store_search_name_is_available_to_input(self):
  goal='进入门店列表，优先通过门店名称搜索“华住三期测试酒店”，点击该门店。'
  self.assertEqual(goal_input_data(goal,{})['store'],'华住三期测试酒店')
  self.assertEqual(goal_input_data(goal,{'store':'指定门店'})['store'],'指定门店')
 def test_ambiguous_store_search_is_not_inferred(self):
  self.assertNotIn('store',goal_input_data('搜索“门店甲”；搜索“门店乙”',{}))
 def test_explicit_rename_becomes_input_key(self):
  self.assertEqual(goal_input_data('点击机器人名称，记录原名称，清空并输入 test1，点击保存。',{})['robot_name'],'test1')
 def test_user_data_wins_and_is_not_mutated(self):
  original={'robot_name':'custom'}
  self.assertEqual(goal_input_data('机器人名称改为 test1',original)['robot_name'],'custom')
  self.assertEqual(original,{'robot_name':'custom'})
 def test_conflicts_and_negative_instruction_not_inferred(self):
  for goal in ('机器人名称改为 first；机器人名称改为 second','机器人名称不要改为 test1','输入 password123','查看机器人名称'):
   self.assertNotIn('robot_name',goal_input_data(goal,{}))
 def test_unique_names_are_distinct_and_supplied_stable(self):
  goal='任务名称使用 test1_排班_本次唯一后缀；新增 test1_模式_本次唯一后缀'
  first=goal_input_data(goal,{})
  self.assertTrue(first['schedule_name'].startswith('test1_排班_'))
  self.assertTrue(first['clean_mode_name'].startswith('test1_模式_'))
  self.assertNotEqual(first['schedule_name'],goal_input_data(goal,{})['schedule_name'])
  self.assertEqual(first,goal_input_data(goal,first))

class BlockedContinuationTests(unittest.TestCase):
 def test_blocked_dialog_is_cancelled_before_continuing(self):
  from unittest.mock import patch
  from test_ai_operator import Device
  import ai_operator as op
  e=Device();e.prefer_webview=True
  page=({'text':'名称 取消','controls':[{'id':'w0','text':'取消','editable':False}],'route':'/'},{'w0':('web',{'text':'取消','tag':'button'})},'<hierarchy/>','same')
  cfg={'goal':'单项受阻后继续其他独立步骤','share_page':True,'max_actions':1,'seconds':60}
  with patch.object(op,'observe',return_value=page),patch.object(op,'execute') as execute,patch.object(op.cancellation.Control,'sleep'):
   result=op.run(e,cfg,ask=lambda *a,**kw:{'action':'blocked','reason':'当前无新增入口'})
  self.assertEqual(result['blocked_items'][0]['reason'],'当前无新增入口')
  self.assertEqual(execute.call_args.args[1],{'action':'tap','target':'w0'})
  self.assertNotIn(result['termination'],('goal_checked','ai_goal_supported'))
