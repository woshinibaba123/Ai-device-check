import unittest
import tempfile
import json
from pathlib import Path
import excel_ai
import codebuddy_bridge as bridge
import h5_source


class StepExpectationTests(unittest.TestCase):
    def case(self,expected):
        return {'title':'地址更新','steps':'【1】保存地址\n【2】返回列表','expected':expected,'priority':'P1'}

    def test_numbered_expectations_stay_with_their_actions(self):
        expected='【1】立即提示修改成功\n【2】列表地址已更新'
        row=excel_ai.business_case(self.case(expected))
        self.assertEqual([s['expected'] for s in row['business_steps']],['立即提示修改成功','列表地址已更新'])
        self.assertEqual(row['expected'],expected)

    def test_mismatched_numbers_preserve_overall_expected_without_guessing(self):
        expected='【1】成功\n【3】地址更新'
        row=excel_ai.business_case(self.case(expected))
        self.assertEqual(row['business_steps'][-1]['expected'],expected)

    def test_partial_step_is_not_executable_prefix(self):
        row={'business_steps':[
            {'automation_status':'candidate','automation_steps':[{'action':'tap','value':'我的'}]},
            {'automation_status':'partial','automation_steps':[{'action':'assert','value':'修改成功'}]}]}
        self.assertEqual(excel_ai.partial_candidate(row)['steps'],[{'action':'tap','value':'我的'}])


class BindingDependencyTests(unittest.TestCase):
    def test_search_without_input_and_save_without_submission_are_incomplete(self):
        ops=[{'action':'web_assert','by':'text','value':'修改成功'}]
        self.assertTrue(bridge.binding_coverage_issues({'action':'搜索框输入 洲际 点击搜索'},ops))
        self.assertTrue(bridge.binding_coverage_issues({'action':'选点后点保存地址'},ops))

    def test_missing_search_button_is_not_required_for_input_driven_search(self):
        ops=[{'action':'web_input','by':'css','value':'input[type=search]','text':'洲际'},
             {'action':'web_assert','by':'text','value':'浦东洲际酒店'}]
        self.assertEqual(bridge.binding_coverage_issues({'action':'搜索框输入 洲际'},ops),[])

    def test_specific_account_requires_identity_assertion(self):
        from test_codebuddy_bridge import business_sample,bindings_sample
        business=business_sample();business['cases'][0]['precondition']='账号 app_direct01 已登录'
        row=bridge.apply_bindings(bridge.business_document(business),bindings_sample())['cases'][0]
        self.assertIsNone(row['plan'])
        self.assertIn('账号核验',row['blocked_reason'])
        self.assertIsNone(excel_ai.partial_candidate(row))
        bindings=bindings_sample()
        bindings['bindings'][0]['requires']=[{'action':'assert','value':'app_direct01'}]
        row=bridge.apply_bindings(bridge.business_document(business),bindings)['cases'][0]
        self.assertIsNotNone(row['plan'])

    def test_failed_binding_blocks_dependent_success_assertion(self):
        doc=bridge.business_document({'cases':[{'title':'保存地址','precondition':'已登录','expected':'保存成功并返回列表',
            'business_steps':[{'action':'点保存地址','expected':'修改成功'},{'action':'返回列表核对','expected':'地址已更新'}]}]})
        binding={'bindings':[{'case_id':1,'steps':[
            {'business_step':1,'operations':[],'blocked_reason':'缺少提交接口'},
            {'business_step':2,'operations':[{'action':'web_assert','by':'text','value':'修改成功'}]}]}]}
        row=bridge.apply_bindings(doc,binding)['cases'][0]
        self.assertIsNone(row['plan'])
        self.assertEqual(row['business_steps'][1]['automation_status'],'partial')
        self.assertIn('依赖的第 1 步',row['business_steps'][1]['automation_reason'])
        self.assertIsNone(excel_ai.partial_candidate(row))


class H5BindingEvidenceTests(unittest.TestCase):
    def test_literal_selector_and_request_are_exposed_without_success_code_guess(self):
        evidence=h5_source.binding_evidence('''<form class="search" @submit.prevent="loadAddress(true)"><input class="keyword" v-model="keyword" @input="searchStores"></form>
<article v-for="item in items" class="store-card"></article>
export function save(data) {return request({url:'/merchant/address',method:'put',data})}''')
        self.assertEqual(evidence['requests'],[{'method':'PUT','path':'/merchant/address'}])
        self.assertTrue(any(c.get('model')=='keyword' for c in evidence['dom_controls']))
        self.assertTrue(any(c.get('scope_required') for c in evidence['dom_controls']))
        self.assertNotIn('codes',json.dumps(evidence))

    def test_translation_namespace_keeps_target_page_and_api_over_generic_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'package.json').write_text('{}')
            for folder in ('src/lang/storeAddressManage','src/pages/storeAddressManage','src/api'):(root/folder).mkdir(parents=True)
            (root/'src/lang/storeAddressManage/index.js').write_text("export default {title:'门店地址管理'}")
            (root/'src/pages/storeAddressManage/index.vue').write_text('''<div>{{$t('storeAddressManage.title')}}</div><input class="search-input" v-model="keyword">\nimport {save} from '@/api/storeAddressManage' ''')
            (root/'src/api/storeAddressManage.js').write_text("export function save(data) {return request({url:'/merchant/address',method:'put',data})}")
            for i in range(20):(root/f'src/noise{i}.vue').write_text('<button>门店 搜索 地址 保存</button>\n'*20)
            data=h5_source.summary(tmp,'门店地址管理 搜索 地址 保存',max_chars=4000)
            self.assertEqual(data['files'][0]['file'],'src/pages/storeAddressManage/index.vue')
            self.assertTrue(any(r.get('requests') for r in data['files']))


if __name__=='__main__':unittest.main()
