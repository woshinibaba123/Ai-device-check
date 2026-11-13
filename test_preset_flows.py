import unittest
import preset_flows
import ai_fastpath
class PresetTests(unittest.TestCase):
    def test_ids_and_source_evidence(self):
        flows=preset_flows.catalog();self.assertGreaterEqual(len(flows),8)
        self.assertEqual(len({f['id'] for f in flows}),len(flows))
        for flow in flows:
            self.assertTrue(flow['sources']);self.assertTrue(flow['steps']);self.assertIn(flow['status'],('source_candidate','existing_candidate'))
    def test_store_recipe_compiles(self):
        flow=next(f for f in preset_flows.catalog() if f['id']=='clean-robot')
        goal=flow['steps'][0].replace('{{store}}','塘人｜创意本帮菜(奥特莱斯店)')
        plan=ai_fastpath.compile_goal(goal)
        self.assertEqual(plan['query'],'塘人｜创意本帮菜(奥特莱斯店)')
