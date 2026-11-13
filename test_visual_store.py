import unittest
from visual_store import validate_search,canonical

class StoreIdentityTests(unittest.TestCase):
    def page(self,names,text='塘人｜创意本帮菜(奥特莱斯店)'):
        return {'page':'store_search','search_text':text,'store_names':names}
    def test_exact_branch_accepts_typographic_variants(self):
        validate_search(self.page(['塘人|创意本帮菜（奥特莱斯店）']),'塘人｜创意本帮菜(奥特莱斯店)')
    def test_wrong_branch_rejected(self):
        with self.assertRaises(ValueError):validate_search(self.page(['塘人｜创意本帮菜(其他店)']),'塘人｜创意本帮菜(奥特莱斯店)')
    def test_duplicate_rejected(self):
        name='塘人｜创意本帮菜(奥特莱斯店)'
        with self.assertRaises(ValueError):validate_search(self.page([name,name]),name)
    def test_input_not_confirmed_rejected(self):
        with self.assertRaises(ValueError):validate_search(self.page(['塘人'],text=''),'塘人')

    def test_first_result_policy_accepts_multiple_cards(self):
        name='塘人｜创意本帮菜(奥特莱斯店)'
        self.assertEqual(validate_search(self.page(['第一张门店','第二张门店']),name,first_result=True),'第一张门店')
    def test_first_result_requires_nonempty_list(self):
        with self.assertRaises(ValueError):validate_search(self.page([]),'塘人｜创意本帮菜(奥特莱斯店)',first_result=True)

class VerifiedFirstResultTests(unittest.TestCase):
    def test_visible_card_requires_correct_search_text(self):
        from visual_store import verified_first_result
        with self.assertRaises(ValueError):
            verified_first_result({'page':'store_search','search_text':'其他门店','store_names':['第一张门店']},'目标门店')
    def test_matching_input_accepts_visible_card(self):
        from visual_store import verified_first_result
        self.assertEqual(verified_first_result({'page':'store_search','search_text':'目标门店','store_names':['目标门店']},'目标门店'),'目标门店')

class IdentityWaitTests(unittest.TestCase):
    def test_transition_retries_without_clicking_again(self):
        import time
        from unittest.mock import Mock
        from visual_store import wait_identity
        transport=Mock();control=Mock()
        query=Mock(side_effect=[{'page':'other','store_name':''},{'page':'store_detail','store_name':'目标门店'}])
        identity=wait_identity(transport,query,'目标门店',control,time.monotonic()+30,Mock())
        self.assertEqual(identity['store_name'],'目标门店')
        self.assertEqual(query.call_count,2)
        transport.tap.assert_not_called()
        control.sleep.assert_called_once()

    def test_wrong_identity_is_bounded_and_reports_actual_name(self):
        import time
        from unittest.mock import Mock
        from visual_store import wait_identity
        transport=Mock();query=Mock(return_value={'page':'store_detail','store_name':'其他门店'})
        with self.assertRaisesRegex(ValueError,'实际门店=其他门店'):
            wait_identity(transport,query,'目标门店',Mock(),time.monotonic()+30,Mock())
        self.assertEqual(query.call_count,4)
        transport.tap.assert_not_called()

class QueryAccountingTests(unittest.TestCase):
    def test_failed_query_is_counted_immediately(self):
        from unittest.mock import Mock,patch
        import visual_store
        e=Mock();e.stopped=lambda:False
        callback=Mock()
        with patch.object(visual_store,'AndroidVisual'),patch.object(visual_store.midscene_bridge,'query',side_effect=ValueError('model failed')):
            with self.assertRaisesRegex(ValueError,'model failed'):
                visual_store.enter(e,'目标门店',{},on_query=callback)
        callback.assert_called_once()
