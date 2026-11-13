import unittest
from unittest.mock import patch
import ai_operator as op
from test_ai_operator import Device,node

class CleanRobotIdentityTests(unittest.TestCase):
    def test_rejects_observed_nonclean_card(self):
        self.assertTrue(op.nonclean_card_for_goal('查看清洁机器人详情','Not callable\n0 m\nMission Mileage\n0 times\nNumber of Tasks'))
        self.assertTrue(op.nonclean_card_for_goal('进入清洁机器人','132m 任务里程 17次 任务次数'))

    def test_cleaning_card_and_other_goals_remain_available(self):
        for goal,label in [('查看机器人详情','0 m Mission Mileage Number of Tasks'),('查看清洁机器人','138㎡ 清洁面积 17次 任务次数'),('View cleaning robot','138 m² Cleaning Area 17 Number of Tasks')]:
            self.assertFalse(op.nonclean_card_for_goal(goal,label))

    def test_ai_cannot_click_known_nonclean_card_for_clean_goal(self):
        e=Device();e.nodes=[node('0 m\nMission Mileage\n0 times\nNumber of Tasks')]
        cfg={'goal':'查看清洁机器人','share_page':True,'fast_mode':False,'seconds':30,'max_actions':2}
        def ask(prompt,*a,**kw):
            self.assertIn('"blocked": true',prompt)
            return {'action':'tap','target':'n0'}
        with patch.object(op.automation,'parse_ui',side_effect=lambda s:e.nodes),patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,cfg,ask=ask)
        self.assertEqual(result['termination'],'robot_type_mismatch')
        self.assertEqual(e.calls,[])
        self.assertEqual(result['steps'],[])

class NamedStoreTests(unittest.TestCase):
    def test_exact_store_name_preserves_separator(self):
        import ai_fastpath
        plan=ai_fastpath.compile_goal('进入门店列表，搜索并进入「塘人 | 创意本帮菜」，然后查看清洁机器人')
        self.assertEqual(plan['query'],'塘人 | 创意本帮菜')
        self.assertEqual(plan['kind'],'store_lookup')

    def test_local_store_option_requires_boolean(self):
        with self.assertRaises(ValueError):op.validate({'goal':'进入门店列表','share_page':True,'local_store_navigation':'true'})

class StoreNameVariantTests(unittest.TestCase):
    def test_observed_fullwidth_separator_and_branch_suffix(self):
        import ai_fastpath as fast
        self.assertTrue(fast.store_name_matches('塘人 | 创意本帮菜','塘人｜创意本帮菜(奥特莱斯店)'))
        self.assertFalse(fast.store_name_matches('塘人 | 创意本帮菜','塘人｜创意本帮菜配送中心'))
        self.assertFalse(fast.store_name_matches('塘人','塘人｜创意本帮菜'))

    def test_matching_multiple_branches_still_blocks(self):
        import ai_fastpath as fast
        controls=[{'id':str(i),'text':'塘人｜创意本帮菜('+branch+')'} for i,branch in enumerate(['一店','二店'])]
        plan={'cursor':2,'kind':'store_lookup','query':'塘人 | 创意本帮菜'}
        result=fast.store_step(plan,{'controls':controls},{})
        self.assertEqual(result['action'],'blocked')

class LocalStoreRunTests(unittest.TestCase):
    def test_standard_ai_mode_uses_local_navigation_for_observed_name_variant(self):
        class StoreDevice(Device):
            def __init__(self):
                super().__init__();self.state=0
            @property
            def nodes(self):
                if self.state==0:return [node('Store\nTab 2 of 4')]
                if self.state==1:return [node('Please enter the store name',editable=True,hint='Please enter the store name')]
                if self.state==2:return [node('Please enter the store name',editable=True,hint='Please enter the store name'),node('塘人｜创意本帮菜(奥特莱斯店)\nS00018012',path='/root/card')]
                return [node('Cleaning Area 138㎡')]
            @nodes.setter
            def nodes(self,value):pass
            def call(self,*args):
                self.calls.append(args)
                if args[0]=='POST' and args[1].endswith('/click'):self.state=1 if self.state==0 else 3
            def type(self,*args):self.state=2
        e=StoreDevice()
        cfg={'goal':'进入门店列表，搜索并进入「塘人 | 创意本帮菜」，然后查看门店信息','share_page':True,'fast_mode':False,'local_store_navigation':True,'seconds':60,'max_actions':5}
        with patch.object(op.automation,'parse_ui',side_effect=lambda s:e.nodes),patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,cfg,ask=lambda *a,**kw:{'action':'blocked','reason':'test stops after store entry'})
        self.assertEqual([s['action'] for s in result['steps']],['tap','input','tap'])
        self.assertTrue(all(s['origin']=='local_path' for s in result['steps']))
        self.assertEqual(e.state,3)
        self.assertEqual(result['model_calls'],1)

class LocalGuideAndScanTests(unittest.TestCase):
    def page(self,controls,text='Equipment（43）',route=''):
        return {'controls':controls,'text':text,'route':route}

    def test_screenshot_guide_uses_skip_without_ai(self):
        page=self.page([{'id':'skip','text':'skip'},{'id':'next','text':'Next'}],'Click to return to the store page')
        self.assertEqual(op.local_guide_step(page)['target'],'skip')
        self.assertIsNone(op.local_guide_step(self.page(page['controls'],'Normal business wizard')))

    def test_guide_without_clickable_next(self):
        page=self.page([{'id':'skip','text':'skip'}],'Click to return to the store page')
        self.assertEqual(op.local_guide_step(page)['target'],'skip')

    def test_store_list_without_card_controls_scrolls(self):
        self.assertEqual(op.local_clean_list_step(self.page([],route='/store/main'))['action'],'scroll')

    def test_no_clean_visible_scrolls_down(self):
        page=self.page([{'id':'other','text':'0 m Mission Mileage 0 times Number of Tasks','blocked':True}])
        self.assertEqual(op.local_clean_list_step(page)['action'],'scroll')

    def test_clean_card_unique_and_multiple_are_distinguished(self):
        card={'id':'clean','text':'138 m² Cleaning Area 17 Number of Tasks'}
        self.assertEqual(op.local_clean_list_step(self.page([card]))['target'],'clean')
        self.assertEqual(op.local_clean_list_step(self.page([card,dict(card,id='second')]))['action'],'blocked')
        self.assertIsNone(op.local_clean_list_step(self.page([card],route='/map/cleanRecord')))

    def test_onboarding_does_not_wait_for_model(self):
        e=Device();e.nodes=[node('Click to return to the store page',clickable=False),node('skip',path='/skip'),node('Next',path='/next')]
        def call(*args):
            e.calls.append(args)
            if args[0]=='POST':e.nodes=[node('消息')]
        e.call=call
        with patch.object(op.automation,'parse_ui',side_effect=lambda s:e.nodes),patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,{'goal':'进入消息','share_page':True,'fast_mode':False,'max_actions':3,'seconds':30,'checkpoints':['消息']},ask=lambda *a,**kw:{'action':'done'})
        self.assertEqual(result['steps'][0]['origin'],'guide_dismiss')
        self.assertEqual(result['steps'][0]['label'],'skip')
        self.assertEqual(result['model_calls'],1)

class NativeStoreRouteTests(unittest.TestCase):
    def test_native_store_route_allows_local_scroll(self):
        evidence={'route':'/store/main','text':'Equipment（43）','controls':[{'id':'robot','text':'0 m Mission Mileage 0 times Number of Tasks','blocked':True}]}
        self.assertEqual(op.local_clean_list_step(evidence)['action'],'scroll')
        evidence['route']='/robot/info'
        self.assertIsNone(op.local_clean_list_step(evidence))

class StoreLoadingTests(unittest.TestCase):
    def test_after_store_click_waits_locally_for_guide_then_skips_without_ai(self):
        class D(Device):
            def __init__(self):
                super().__init__();self.state=0;self.reads=0
            @property
            def nodes(self):
                if self.state==0:return [node('Store\nTab 2 of 4')]
                if self.state==1:return [node('Please enter the store name',editable=True,hint='Please enter the store name')]
                if self.state==2:return [node('塘人｜创意本帮菜(奥特莱斯店)',path='/store')]
                if self.state==3:
                    self.reads+=1
                    if self.reads<8:return [node('Loading',clickable=False)]
                    return [node('Click to return to the store page',clickable=False),node('skip',path='/skip'),node('Next',path='/next')]
                return [node('Equipment',clickable=False),node('138㎡ Cleaning Area 1 Number of Tasks')]
            @nodes.setter
            def nodes(self,value):pass
            def call(self,*args):
                self.calls.append(args)
                if args[0]=='POST' and args[1].endswith('/click'):self.state={0:1,2:3,3:4,4:5}.get(self.state,self.state)
            def type(self,*args):self.state=2
        e=D()
        cfg={'goal':'进入门店列表，搜索并进入「塘人 | 创意本帮菜」，然后查看清洁机器人','share_page':True,'fast_mode':False,'local_store_navigation':True,'max_actions':10,'seconds':60}
        with patch.object(op.automation,'parse_ui',side_effect=lambda s:e.nodes),patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,cfg,ask=lambda *a,**kw:{'action':'blocked','reason':'stop'})
        origins=[s.get('origin') for s in result['steps']]
        self.assertIn('local_store_loading',origins)
        self.assertIn('guide_dismiss',origins)
        self.assertIn('local_clean_card',origins)

class FirstVisibleCleanTests(unittest.TestCase):
    def test_explicit_readonly_selection_uses_first_confirmed_clean_card(self):
        page={'route':'/store/main','text':'Equipment','controls':[{'id':'delivery','text':'Mission Mileage Number of Tasks','blocked':True},{'id':'clean1','text':'138㎡ Cleaning Area Number of Tasks'},{'id':'clean2','text':'132㎡ Cleaning Area Number of Tasks'}]}
        self.assertEqual(op.local_clean_list_step(page,'first_visible')['target'],'clean1')
        self.assertEqual(op.local_clean_list_step(page)['action'],'blocked')

class ResumeCurrentStoreTests(unittest.TestCase):
    def test_resume_requires_matching_store_identity(self):
        e=Device();e.nodes=[node('Other Store'),node('Equipment')]
        cfg={'goal':'进入门店列表，搜索并进入「塘人｜创意本帮菜(奥特莱斯店)」，然后查看清洁机器人','share_page':True,'fast_mode':False,'local_store_navigation':True,'resume_current_store':True,'max_actions':3,'seconds':30}
        with patch.object(op.automation,'parse_ui',side_effect=lambda s:e.nodes):
            r=op.run(e,cfg,ask=lambda *a,**kw:self.fail('wrong store must not request AI'))
        self.assertEqual(r['termination'],'store_context_mismatch')
        self.assertFalse(e.calls)

    def test_store_list_card_clicks_through_without_search(self):
        # 门店列表页已显示目标门店卡片（无设备列表）：直接点卡片，不终止也不请求 AI 搜索。
        e=Device();e.nodes=[node('全部\n已部署\n未部署\n浙江省 43 台\n塘人｜创意本帮菜(奥特莱斯店)\nS00018012\n已部署\n浙江省宁波市海曙区',path='/store-card')]
        def call(*args):
            e.calls.append(args)
            if args[0]=='POST' and args[1].endswith('/click'):e.nodes=[node('Equipment',clickable=False)]
        e.call=call
        cfg={'goal':'进入门店列表，搜索并进入「塘人｜创意本帮菜(奥特莱斯店)」，然后查看清洁机器人','share_page':True,'fast_mode':False,'local_store_navigation':True,'resume_current_store':True,'max_actions':5,'seconds':30}
        with patch.object(op.automation,'parse_ui',side_effect=lambda s:e.nodes),patch.object(op.cancellation.Control,'sleep'):
            r=op.run(e,cfg,ask=lambda *a,**kw:{'action':'blocked','reason':'stop'})
        self.assertEqual([s.get('origin') for s in r['steps']][0],'local_path')
        self.assertNotEqual(r.get('termination'),'store_context_mismatch')

class ExactRobotMacTests(unittest.TestCase):
    def test_only_requested_mac_is_selected(self):
        page={'route':'/store/main','text':'Equipment','controls':[{'id':'other','text':'88:49:2D:A0:4B:EF Cleaning Area Number of Tasks'},{'id':'wanted','text':'c4:3c:b0:aa:f9:cf Cleaning Area Number of Tasks'}]}
        self.assertEqual(op.local_clean_list_step(page,'first_visible','C4:3C:B0:AA:F9:CF')['target'],'wanted')
        page['controls']=page['controls'][:1]
        self.assertEqual(op.local_clean_list_step(page,'first_visible','C4:3C:B0:AA:F9:CF')['action'],'scroll')

class LocalListScanRegressionTests(unittest.TestCase):
    def test_equipment_header_without_clickable_cards_scans(self):
        page={'route':'', 'text':'Equipment（43）', 'controls':[]}
        self.assertEqual(op.local_clean_list_step(page)['action'], 'scroll')

    def test_agent_route_list_scans_without_model(self):
        page={'route':'/main/agent', 'text':'Equipment (43)', 'controls':[]}
        self.assertEqual(op.local_clean_list_step(page)['action'], 'scroll')

    def test_report_equipment_count_does_not_scan(self):
        page={'route':'/map/cleanRecord', 'text':'Equipment (43)', 'controls':[]}
        self.assertIsNone(op.local_clean_list_step(page))

    def test_unchanged_list_stops_after_two_scrolls_without_ai(self):
        device=Device()
        device.nodes=[node('Equipment（43）',clickable=False)]
        with patch.object(op.automation,'parse_ui',side_effect=lambda _:device.nodes), patch.object(op.cancellation.Control,'sleep'):
            result=op.run(device,{'goal':'查找清洁机器人','share_page':True,'max_actions':10,'seconds':30},ask=lambda *a,**kw:self.fail('should not call model'))
        self.assertEqual(device.calls.count(('scroll',)),2)
        self.assertEqual(result['model_calls'],0)
        self.assertIn('两次',result['termination_detail'])
