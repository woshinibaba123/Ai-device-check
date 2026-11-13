import unittest
from unittest.mock import patch
import ai_fastpath as fast
import ai_operator
from test_ai_operator import Device, node


class FastPathTests(unittest.TestCase):
    def test_french_goal(self):
        plan=fast.compile_goal('进入通用设置，将语言切换成法语，并确认切换生效。')
        self.assertEqual(plan['labels'],['我的','通用设置','语言','Français'])
    def test_store_prefix_handles_original_goal_without_completing_business(self):
        plan=fast.compile_goal('进入门店列表进入 上海擎朗研发部 然后进入这个门店，下发一个呼叫任务')
        self.assertEqual(plan['query'],'上海擎朗研发部')
        tab={'id':'tab','text':'Store\nTab 2 of 4','editable':False,'selected':False}
        self.assertEqual(fast.next_step(plan,{'controls':[tab]})['target'],'tab')
        plan['cursor']=1
        search={'id':'search','text':'Please enter the store name','editable':True}
        self.assertEqual(fast.next_step(plan,{'controls':[search]})['action'],'input')
        plan['cursor']=2
        card={'id':'card','text':'[已隐藏]\nS123','editable':False}
        self.assertEqual(fast.next_step(plan,{'controls':[card]},raw_labels={'card':'上海擎朗研发部\nS123'})['target'],'card')
        self.assertEqual(fast.next_step(plan,{'controls':[card,dict(card,id='duplicate')]},raw_labels={'card':'上海擎朗研发部','duplicate':'上海擎朗研发部'})['action'],'blocked')
        plan['cursor']=3
        self.assertIsNone(fast.next_step(plan,{'controls':[card]}))

    def test_common_store_goal_wordings(self):
        for goal in ('请帮我进入门店列表，找到上海擎朗研发部，然后查看详情',
                     '打开门店页面，搜索“上海擎朗研发部”，查看详情',
                     '前往门店列表并找到名为上海擎朗研发部，门店编号 S00031759',
                     '门店列表里搜索上海擎朗研发部，进入详情'):
            with self.subTest(goal=goal):
                self.assertEqual(fast.compile_goal(goal)['query'],'上海擎朗研发部')
        for goal in ('不要进入门店列表，搜索上海擎朗研发部', '去门店报修', '进入门店列表，搜索下发呼叫任务'):
            self.assertIsNone(fast.compile_goal(goal))

    def test_store_navigation_prefix_does_not_invent_search_data(self):
        plan=fast.compile_goal('查看门店列表，然后下发呼叫任务')
        self.assertEqual(plan['query'],'')
        self.assertEqual(fast.next_step(plan,{'controls':[{'id':'tab','text':'Store'}]})['target'],'tab')
        plan['cursor']=1
        self.assertIsNone(fast.next_step(plan,{'controls':[{'id':'search','text':'Please enter the store name','editable':True}]}))

    def test_store_tab_prefers_navigation_over_count_heading_and_rejects_duplicates(self):
        heading={'id':'heading','text':'Store (757)'}
        tab={'id':'tab','text':'Store\nTab 2 of 5'}
        self.assertEqual(fast.store_tab({'controls':[heading,tab]}),'tab')
        self.assertIsNone(fast.store_tab({'controls':[heading]}))
        self.assertIsNone(fast.store_tab({'controls':[tab,dict(tab,id='duplicate')]}))
        self.assertIsNone(fast.store_tab({'controls':[dict(tab,selected=True)]}))

    def test_store_code_disambiguates_same_name(self):
        plan=fast.compile_goal('进入门店列表，搜索并进入上海擎朗研发部，门店编号 S00031759，查看详情')
        plan['cursor']=2
        page={'controls':[{'id':'a','text':'[已隐藏]'}, {'id':'b','text':'[已隐藏]'}]}
        labels={'a':'上海擎朗研发部\nSXBB00000315','b':'上海擎朗研发部\nS00031759'}
        self.assertEqual(fast.next_step(plan,page,raw_labels=labels)['target'],'b')
        plan['store_code']='S99999999'
        self.assertIsNone(fast.next_step(plan,page,raw_labels=labels))

    def test_store_prefix_never_guesses_missing_or_partial_result(self):
        plan=fast.compile_goal('进入门店列表，搜索并进入上海擎朗研发部，查看门店详情')
        plan['cursor']=2
        self.assertIsNone(fast.next_step(plan,{'controls':[{'id':'c','text':'上海擎朗研发部二店'}]}))
        self.assertIsNone(fast.next_step(plan,{'controls':[{'id':'c','text':'上海擎朗研发部','blocked':True}]}))

    def test_unknown_or_extra_goal_uses_ai(self):
        for text in ('去门店报修','进入通用设置，切换法语然后删除账号','切换法语和英语'):
            self.assertIsNone(fast.compile_goal(text))
    def test_resume_on_settings_page(self):
        plan=fast.compile_goal('切换成法语')
        step=fast.next_step(plan,{'controls':[{'id':'real','text':'Language','editable':False}]})
        self.assertEqual(step['path_index'],2)
        self.assertEqual(step['target'],'real')
    def test_ambiguous_target_falls_back(self):
        self.assertIsNone(fast.resolve('我的',{'controls':[{'id':'1','text':'Mine'},{'id':'2','text':'我的'}]}))
    def test_batch_resolves_live_id_not_model_locator(self):
        self.assertEqual(fast.queued_step({'action':'tap','label':'Settings','target':'made-up'},{'controls':[{'id':'actual','text':'Settings'}]})['target'],'actual')
    def test_batch_does_not_match_absent_or_blocked(self):
        self.assertIsNone(fast.queued_step({'action':'tap','label':'Save'},{'controls':[{'id':'x','text':'Save','blocked':True}]}))
        self.assertIsNone(fast.queued_step({'action':'tap','label':'Missing'},{'controls':[]}))


class FastLoopTests(unittest.TestCase):
    def setUp(self):
        self.e=Device()
        self.cfg={'goal':'进入通用设置，将语言切换成法语，并确认切换生效','share_page':True,'max_actions':8,'seconds':60}
        self.parser=patch.object(ai_operator.automation,'parse_ui',side_effect=lambda _:self.e.nodes)
        self.parser.start()
        self.sleep=patch.object(ai_operator.cancellation.Control,'sleep');self.sleep.start()
    def tearDown(self):self.parser.stop();self.sleep.stop()
    def test_four_local_clicks_only_one_final_model_request(self):
        pages=['Mine','General Settings','Language','Français','Paramètres généraux']
        self.e.nodes=[node(pages[0])]
        clicks=[]
        def call(*args):
            clicks.append(args)
            self.e.nodes=[node(pages[len(clicks)])]
        self.e.call=call
        prompts=[]
        def ask(prompt,*args,**kw):
            prompts.append(prompt)
            return {'satisfied':True,'evidence':['Paramètres généraux']}
        result=ai_operator.run(self.e,self.cfg,ask=ask)
        self.assertEqual(len(clicks),4)
        self.assertEqual(len(prompts),1)
        self.assertEqual(result['model_calls'],1)
        self.assertEqual(result['termination'],'ai_goal_supported')
        self.assertTrue(all(s['origin']=='local_path' for s in result['steps']))
    def test_fast_mode_reuses_post_action_page_and_short_wait(self):
        self.cfg.update(goal='查看页面', max_actions=2, checkpoints=['Second'])
        self.e.nodes=[node('First')]
        self.e.call=lambda *a:setattr(self.e,'nodes',[node('Second')])
        answers=iter([{'action':'tap','target':'n0'},{'action':'done'}])
        with patch.object(ai_operator, 'observe', wraps=ai_operator.observe) as observe, patch.object(ai_operator.cancellation.Control, 'sleep') as sleep:
            result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:next(answers))
        # Initial, pre-click revalidation, post-click, completion revalidation.
        self.assertEqual(observe.call_count,4)
        sleep.assert_called_once_with(.2)
        self.assertEqual(len(self.e.captures),0)
        self.assertIn('decision_ms',result['steps'][0]['timings'])

    def test_unchanged_page_gets_grace_period_without_reclick(self):
        self.cfg.update(goal='查看页面', max_actions=1)
        self.e.nodes=[node('First')]
        with patch.object(ai_operator.cancellation.Control, 'sleep') as sleep:
            result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:{'action':'tap','target':'n0'})
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[.2,.6])
        self.assertEqual(sum(c[0]=='POST' for c in self.e.calls),1)
        self.assertFalse(result['steps'][0]['page_changed'])

    def test_slow_capture_invalidates_cached_page(self):
        self.cfg['full_evidence']=True
        self.cfg.update(goal='查看页面', max_actions=2, checkpoints=['Second'])
        self.e.nodes=[node('First')]
        now=[0.0]
        self.e.call=lambda *a:setattr(self.e,'nodes',[node('Second')])
        self.e.capture=lambda *a:now.__setitem__(0, now[0]+1)
        answers=iter([{'action':'tap','target':'n0'},{'action':'done'}])
        with patch.object(ai_operator.time,'monotonic',side_effect=lambda:now[0]), patch.object(ai_operator,'observe',wraps=ai_operator.observe) as observe:
            ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:next(answers),clock=lambda:0)
        self.assertEqual(observe.call_count,5)

    def test_store_search_and_open_run_locally_with_values_kept_out_of_prompt(self):
        self.cfg.update(goal='进入门店列表，搜索并进入上海擎朗研发部，查看门店详情',max_actions=4,checkpoints=['详情'])
        self.e.nodes=[node('Store\nTab 2 of 4')]
        writes=[]
        def call(*a):
            if self.e.nodes[0]['label'].startswith('Store'):
                self.e.nodes=[node('',editable=True,hint='Please enter the store name')]
            else:self.e.nodes=[node('详情')]
        def type_value(eid,value,n):
            writes.append(value)
            self.e.nodes=[node('上海擎朗研发部\nS123')]
        self.e.call=call;self.e.type=type_value
        def ask(prompt,*a,**kw):
            self.assertNotIn('上海擎朗研发部',prompt)
            return {'action':'done'}
        result=ai_operator.run(self.e,self.cfg,ask=ask)
        self.assertEqual(writes,['上海擎朗研发部'])
        self.assertEqual(result['model_calls'],1)
        self.assertEqual([s['action'] for s in result['steps']],['tap','input','tap'])
        self.assertTrue(all(s['origin']=='local_path' for s in result['steps']))

    def test_debounced_search_waits_locally_instead_of_calling_model(self):
        self.cfg.update(goal='进入门店列表，搜索并进入上海擎朗研发部，门店编号 S00031759',max_actions=3)
        self.e.nodes=[node('Store\nTab 2 of 4')]
        waiting=[0]
        def source():
            if waiting[0]:
                waiting[0]+=1
                if waiting[0]>=4:
                    self.e.nodes=[node('上海擎朗研发部\nS00031759')]
                    waiting[0]=0
            return '<root/>'
        def call(*a):
            self.e.nodes=[node('',editable=True,hint='Please enter the store name')] if self.e.nodes[0]['label'].startswith('Store') else [node('门店详情')]
        def type_value(*a):
            self.e.nodes=[node('加载中')];waiting[0]=1
        self.e.source=source;self.e.call=call;self.e.type=type_value
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:self.fail('Search readiness must not ask the model'))
        self.assertEqual(result['model_calls'],0)
        self.assertEqual([s['action'] for s in result['steps']],['tap','input','tap'])
        self.assertIn('search_ready_ms',result['steps'][1]['timings'])

    def test_fast_model_timeout_is_bounded_review_without_action(self):
        self.cfg.update(goal='查看未知页面',max_actions=1)
        def ask(*a,**kw):
            self.assertLessEqual(kw['timeout'],30)
            raise ValueError('AI 请求超时，请缩短目标或更换模型')
        result=ai_operator.run(self.e,self.cfg,ask=ask)
        self.assertEqual(result['termination'],'decision_timeout')
        self.assertEqual(self.e.calls,[])

    def test_fast_verification_timeout_preserves_review(self):
        self.cfg.update(goal='查看未知页面',max_actions=1)
        answers=iter([{'action':'done'},ValueError('AI 请求超时')])
        def ask(*a,**kw):
            answer=next(answers)
            if isinstance(answer,Exception):raise answer
            return answer
        result=ai_operator.run(self.e,self.cfg,ask=ask)
        self.assertEqual(result['termination'],'verification_timeout')
        self.assertEqual(result['status'],'review')

    def test_blocked_reason_is_saved_redacted_and_logged(self):
        self.cfg.update(goal='查看页面',max_actions=2,data={'搜索':'local-query'})
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:{'action':'blocked','reason':'缺少配置 local-query credential-secret'})
        self.assertEqual(result['termination'],'needs_review')
        self.assertIn('缺少配置',result['termination_detail'])
        self.assertEqual(result['decisions'][0]['action'],'blocked')
        self.assertNotIn('local-query',str(result))
        self.assertNotIn('credential-secret',str(result))
        self.assertTrue(any('自主操作停止原因' in line for line in self.e.logs))

    def test_missing_blocked_reason_gets_explicit_explanation(self):
        self.cfg.update(goal='查看页面',max_actions=1)
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:{'action':'blocked'})
        self.assertIn('未提供具体停止原因',result['termination_detail'])

    def test_unmatched_batch_refreshes_then_uses_single_real_target(self):
        self.cfg.update(goal='查看页面',max_actions=2)
        self.e.nodes=[node('Real')]
        prompts=[]
        answers=iter([{'steps':[{'action':'tap','label':'Invented'}]},{'action':'tap','target':'n0'}])
        def ask(prompt,*a,**kw):prompts.append(prompt);return next(answers)
        result=ai_operator.run(self.e,self.cfg,ask=ask)
        self.assertEqual(sum(c[0]=='POST' for c in self.e.calls),1)
        self.assertEqual(result['recoveries'][0]['action'],'refresh_and_request_single_step')
        self.assertEqual(result['decisions'][0]['result'],'plan_unmatched_not_executed')
        self.assertIn('本轮最新 controls',prompts[1])
        self.assertEqual(result['steps'][0]['round'],2)

    def test_repeated_unmatched_plan_stops_without_exception_or_click(self):
        self.cfg.update(goal='查看页面',max_actions=5)
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:{'steps':[{'action':'tap','label':'Invented'}]})
        self.assertEqual(result['model_calls'],2)
        self.assertEqual(result['termination'],'plan_unmatched')
        self.assertEqual(len(result['recoveries']),1)
        self.assertEqual(self.e.calls,[])

    def test_premature_blocked_replans_available_store_navigation_once(self):
        self.cfg.update(goal='我需要查看门店列表，然后下发呼叫任务',max_actions=2)
        self.e.nodes=[node('Store\nTab 2 of 4')]
        answers=iter([{'action':'blocked','reason':'任务下发不支持'},{'action':'tap','target':'n0'}])
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:next(answers))
        self.assertEqual(len(result['steps']),1)
        self.assertEqual(result['steps'][0]['action'],'tap')
        self.assertEqual(result['recoveries'][0]['action'],'recheck_available_navigation')
        self.assertNotIn('termination_detail',result)

    def test_repeated_blocked_is_bounded_and_last_reason_is_saved(self):
        self.cfg.update(goal='我需要查看门店列表，然后下发呼叫任务',max_actions=5)
        self.e.nodes=[node('Store\nTab 2 of 4')]
        answers=iter([{'action':'blocked','reason':'第一次原因'},{'action':'blocked','reason':'无法确认门店入口'}])
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:next(answers))
        self.assertEqual(result['model_calls'],2)
        self.assertEqual(result['termination_detail'],'无法确认门店入口')
        self.assertEqual(len(result['decisions']),2)
        self.assertEqual(self.e.calls,[])

    def test_local_ambiguous_store_never_replans_to_guess(self):
        self.cfg.update(goal='进入门店列表，搜索上海擎朗研发部',max_actions=3)
        self.e.nodes=[node('',editable=True,hint='Please enter the store name')]
        self.e.type=lambda *a:setattr(self.e,'nodes',[node('上海擎朗研发部\nS00000001'),node('上海擎朗研发部\nS00000002',path='/root/button[2]')])
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:self.fail('Must not ask AI to pick an ambiguous store'))
        self.assertIn('多个同名门店',result['termination_detail'])
        self.assertEqual(result['model_calls'],0)
        self.assertEqual(len(result['steps']),1)

    def test_missing_local_entry_uses_ai(self):
        self.e.nodes=[node('其他入口')]
        self.cfg['max_actions']=1
        prompts=[]
        def ask(prompt,*args,**kw):prompts.append(prompt);return {'action':'blocked'}
        result=ai_operator.run(self.e,self.cfg,ask=ask)
        self.assertEqual(len(prompts),1)
        self.assertEqual(result['termination'],'needs_review')
    def test_batch_performs_two_pages_with_single_planning_request(self):
        self.cfg.update(goal='查看指定两个页面',max_actions=3,checkpoints=['Second'])
        self.e.nodes=[node('First')]
        self.e.call=lambda *a:setattr(self.e,'nodes',[node('Second')])
        answers=iter([{'steps':[{'action':'tap','label':'First'},{'action':'assert','label':'Second'}]},{'action':'done'}])
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:next(answers))
        self.assertEqual(result['model_calls'],2)
        self.assertEqual([s['origin'] for s in result['steps']],['ai_batch','ai_batch'])
    def test_changed_batch_page_falls_back_to_model(self):
        self.cfg.update(goal='查看页面',max_actions=2)
        self.e.nodes=[node('First')]
        self.e.call=lambda *a:setattr(self.e,'nodes',[node('Unexpected')])
        answers=iter([{'steps':[{'action':'tap','label':'First'},{'action':'tap','label':'Missing'}]},{'action':'blocked'}])
        result=ai_operator.run(self.e,self.cfg,ask=lambda *a,**kw:next(answers))
        self.assertEqual(result['model_calls'],2)
        self.assertEqual(len(result['steps']),1)


if __name__=='__main__':unittest.main()
