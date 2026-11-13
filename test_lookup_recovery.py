import unittest
from unittest.mock import patch
import ai_operator as op
from test_ai_operator import Device,node

class LookupRecoveryTests(unittest.TestCase):
    def test_lookup_timeout_has_distinct_pre_action_error(self):
        e=Device();e.find=lambda *_: (_ for _ in ()).throw(TimeoutError('timeout'))
        with self.assertRaises(op.ElementLookupTimeout):op.execute(e,{'action':'tap','target':'n0'},{'n0':('native',node('我的'))},{})
        self.assertEqual(e.calls,[])
    def test_click_timeout_is_not_lookup_timeout(self):
        e=Device();e.call=lambda *_: (_ for _ in ()).throw(TimeoutError('click timeout'))
        with self.assertRaises(TimeoutError):op.execute(e,{'action':'tap','target':'n0'},{'n0':('native',node('我的'))},{})
    def test_live_lookup_timeout_uses_visual_once(self):
        e=Device();e.nodes=[node('我的\nTab 4 of 4')]
        e.find=lambda *_: (_ for _ in ()).throw(TimeoutError('timeout'))
        with patch.object(op.automation,'parse_ui',side_effect=lambda _:e.nodes),patch.object(op.cancellation.Control,'sleep'),patch.object(op.visual_navigation,'tap',return_value={'model_calls':1}) as tap:
            r=op.run(e,{'goal':'进入我的','share_page':True,'seconds':90,'max_actions':1})
        tap.assert_called_once()
        self.assertEqual(len(r['steps']),1)
        self.assertEqual(r['recoveries'][0]['action'],'lookup_timeout_visual_tap')

    def test_fresh_android_bounds_bypass_element_lookup(self):
        from vision_probe import test_image
        e=Device();e.device_id='serial'
        target=node('门店',bounds='[100,200][200,250]')
        with patch('android_visual.AndroidVisual') as cls:
            cls.return_value.screenshot.return_value=test_image()
            op.execute(e,{'action':'tap','target':'n0'},{'n0':('native',target)},{})
        cls.return_value.tap.assert_called_once_with(150,225)
        self.assertEqual(e.calls,[])
    def test_out_of_screen_bounds_never_click(self):
        from vision_probe import test_image
        e=Device();e.device_id='serial'
        with patch('android_visual.AndroidVisual') as cls:
            cls.return_value.screenshot.return_value=test_image()
            with self.assertRaises(ValueError):op.execute(e,{'action':'tap','target':'n0'},{'n0':('native',node('门店',bounds='[300,200][500,250]'))},{})
        cls.return_value.tap.assert_not_called()

    def test_store_precondition_is_not_visual_navigation(self):
        e=Device()
        goal='进入门店列表，搜索并进入「塘人｜创意本帮菜(奥特莱斯店)」。前置条件：已登录，从首页开始。查看清洁机器人地图'
        with patch.object(op,'observe',side_effect=TimeoutError('timeout')),patch.object(op.visual_navigation,'tap',side_effect=ValueError('not found')) as tap:
            result=op.run(e,{'goal':goal,'share_page':True,'seconds':90,'max_actions':3})
        self.assertEqual([call.args[1] for call in tap.call_args_list],['门店'])
        self.assertEqual(result['steps'],[])
        self.assertEqual(result['termination'],'visual_store_entry_blocked')

class StoreTransitionTests(unittest.TestCase):
    def test_store_click_skips_post_tree_and_checks_search_visually(self):
        e=Device();e.device_id='serial'
        page=({'text':'门店','route':'','controls':[{'id':'n0','text':'门店','editable':False}]},
              {'n0':('native',node('门店'))},'<hierarchy/>','page1')
        cfg={'goal':'进入门店列表，搜索上海擎朗研发部','share_page':True,'seconds':90,'max_actions':2}
        decision={'action':'tap','target':'n0','origin':'local_path','path_index':0}
        with patch.object(op,'observe',return_value=page) as observe, \
             patch.object(op,'execute') as execute, \
             patch.object(op.ai_fastpath,'next_step',return_value=decision), \
             patch.object(op.cancellation.Control,'sleep'), \
             patch.object(op.visual_navigation,'tap',side_effect=ValueError('Search page not confirmed')) as visual:
            result=op.run(e,cfg,ask=lambda *a,**kw:self.fail('Unexpected model request'))
        self.assertEqual(observe.call_count,1)
        execute.assert_called_once()
        self.assertEqual(visual.call_args.args[1],'门店搜索输入框')
        self.assertEqual(result['termination'],'visual_store_search_blocked')
        self.assertEqual(len(result['steps']),1)
        self.assertIn('execute_ms',result['steps'][0]['timings'])

class CooldownRecoveryTests(unittest.TestCase):
    def test_cooldown_without_timeout_words_uses_recovery(self):
        e=Device()
        cfg={'goal':'进入门店列表，搜索测试门店','share_page':True,'seconds':60,'max_actions':2}
        with patch.object(op,'observe',side_effect=TimeoutError('原生控件树通道冷却中')), \
             patch.object(op.visual_navigation,'tap',side_effect=ValueError('not matched')):
            result=op.run(e,cfg,ask=lambda *a,**kw:self.fail('Unexpected model'))
        self.assertEqual(result['termination'],'visual_store_entry_blocked')

    def test_nonrecoverable_error_is_not_swallowed(self):
        e=Device()
        with patch.object(op,'observe',side_effect=RuntimeError('invalid session id')):
            with self.assertRaisesRegex(RuntimeError,'invalid session'):
                op.run(e,{'goal':'查看页面','share_page':True,'seconds':60,'max_actions':1})

    def test_start_recovery_uses_verified_cache_before_tree(self):
        e=Device();e.device_id='serial'
        cfg={'goal':'进入门店列表，搜索测试门店','share_page':True,'seconds':60,'max_actions':1,'recover_start':True,'midscene_first':True}
        with patch.object(op,'observe') as observe, \
             patch.object(op.visual_navigation,'tap',side_effect=[{'model_calls':0},ValueError('search not ready')]) as tap, \
             patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,cfg,ask=lambda *a,**kw:self.fail('Unexpected model'))
        observe.assert_not_called()
        self.assertEqual(tap.call_args_list[0].args[1],'门店')
        self.assertTrue(tap.call_args_list[0].args[2]['_cached_navigation_only'])
        self.assertEqual(result['steps'][0]['origin'],'verified_visual_cache')

    def test_start_cache_miss_preserves_original_start_validation(self):
        e=Device();e.device_id='serial'
        cfg={'goal':'进入门店列表，搜索测试门店','share_page':True,'seconds':60,'max_actions':1,'recover_start':True,'midscene_first':True}
        with patch.object(op.visual_navigation,'tap',side_effect=ValueError('not matched')), \
             patch.object(op,'observe',side_effect=TimeoutError('timeout')) as observe, \
             patch.object(op,'observe_webview',side_effect=RuntimeError('no WebView')), \
             patch.object(op.cancellation.Control,'sleep'):
            result=op.run(e,cfg)
        observe.assert_called_once()
        self.assertEqual(result['termination'],'start_page_unreadable')
        self.assertEqual(result['steps'],[])
