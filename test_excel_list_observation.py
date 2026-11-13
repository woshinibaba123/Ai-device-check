import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import codebuddy_bridge as bridge
import excel_execution_policy as policy
import h5_source
import hybrid_webview


class ObservationReasonTests(unittest.TestCase):
    def test_count_and_baseline_requirements_are_notes(self):
        reason='原始预期列表长度=0需要H5列表计数/缺席断言能力（无web_assert_count），本轮按实际结果观察记录；与后台数据一致缺少后台基准数据；yyyy-MM-dd HH:mm格式无运行时格式断言能力，均按观察记录'
        blocking,notes=policy.observation_reason(reason)
        self.assertEqual(blocking,'');self.assertEqual(len(notes),3)
    def test_missing_real_selector_and_submission_remain_blockers(self):
        reason='缺少搜索框CSS定位；缺少提交接口method/path/codes；缺少后台基准数据'
        blocking,notes=policy.observation_reason(reason)
        self.assertIn('搜索框',blocking);self.assertIn('提交接口',blocking);self.assertEqual(len(notes),1)
    def test_observation_notes_do_not_hide_missing_input(self):
        document=bridge.business_document({'cases':[{'title':'搜索','expected':'记录搜索结果','business_steps':[{'action':'搜索框输入 洲际','expected':'记录有无结果'}]}]})
        response={'bindings':[{'case_id':1,'steps':[{'business_step':1,'blocked_reason':'原始预期列表长度=0需要计数断言，本轮按实际结果观察记录','operations':[{'action':'web_observe','by':'css','value':'.card'}]}]}]}
        row=bridge.apply_bindings(document,response,observation_mode=True)['cases'][0]
        self.assertIsNone(row['plan']);self.assertIn('未生成输入',row['blocked_reason'])
        self.assertTrue(row['business_steps'][0]['automation_observation_notes'])


class CoreEvidenceTests(unittest.TestCase):
    def test_long_title_preserves_list_page_and_api_before_map_components(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'package.json').write_text('{}')
            for folder in ('src/lang/storeAddressManage','src/views/storeAddressManage','src/api','src/components'):(root/folder).mkdir(parents=True)
            (root/'src/lang/storeAddressManage/index.js').write_text("export default {title:'门店地址管理'}")
            (root/'src/views/storeAddressManage/index.vue').write_text('<input class="search" v-model="keyword" @input="searchStores"><article class="card" v-for="item in rows">{{item.storeName}} {{item.adminCount}}</article>')
            (root/'src/api/storeAddressManage.js').write_text("export function save() {return request({url:'/address',method:'put'})}")
            (root/'src/views/storeAddressManage/edit.vue').write_text("import Map from '@/components/map';\n"+'<button>搜索地址保存修改地图</button>\n'*30)
            (root/'src/components/map.js').write_text('export const title="搜索地址保存修改地图";\n'*30)
            result=h5_source.summary(temp,'验证门店地址管理仅支持按门店名称模糊搜索且地址关键字不命中',max_chars=4000)
            self.assertEqual(result['files'][0]['file'],'src/views/storeAddressManage/index.vue')
            self.assertTrue(any(r.get('requests') for r in result['files']))
            self.assertIn('adminCount',result['files'][0]['data_fields'])


class NestedComponentEvidenceTests(unittest.TestCase):
    def test_default_reexport_reaches_actual_map_controls_and_dialog_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'package.json').write_text('{}')
            for folder in ('src/lang/storeAddressManage','src/views/storeAddressManage','src/components/Picker','src/api'):(root/folder).mkdir(parents=True)
            (root/'src/lang/storeAddressManage/index.js').write_text("const zh={title:'门店地址管理',confirmUpdate:'确认更新'}")
            (root/'src/views/storeAddressManage/index.vue').write_text('<input class="search" v-model="keyword">')
            (root/'src/views/storeAddressManage/edit.vue').write_text("import Picker from '@/components/Picker';\nimport {save} from '@/api/storeAddressManage';\n<button>保存地址</button>")
            (root/'src/api/storeAddressManage.js').write_text("export function save() {return request({url:'/address',method:'put'})}")
            (root/'src/components/Picker/index.js').write_text("export {default} from './index.vue'")
            (root/'src/components/Picker/index.vue').write_text('<form class="lp-search"><input v-model="keyword" @input="search"></form><ul class="lp-results"><li v-for="item in results"><button @click="pick(item)">选点</button></li></ul>')
            result=h5_source.summary(temp,'验证门店地址管理修改地址地图选点保存与确认更新',max_chars=6500)
            picker=next(r for r in result['files'] if r['file']=='src/components/Picker/index.vue')
            self.assertTrue(any(c['selector']=='ul.lp-results button' for c in picker['dom_controls']))
            self.assertTrue(any(r.get('translation_labels',{}).get('confirmUpdate')=='确认更新' for r in result['files']))


class FlutterBusinessEvidenceTests(unittest.TestCase):
    def test_logged_in_account_preconditions_do_not_evict_main_page(self):
        import flow_planner
        with tempfile.TemporaryDirectory() as temp:
            index={'project':temp,'navigation':{'routes':[],'entries':[]},'translations':{},'pages':[
                {'name':'main','path':'/main','source':'main.dart','labels':[{'key':'mine','labels':['我的']}],'inputs':[]},
                {'name':'login','path':'/login','source':'login.dart','labels':[{'key':'account','labels':['账号']},{'key':'login','labels':['登录']}],'inputs':[]}]}
            result=flow_planner.ai_summary(index,'验证管理员账号已登录后进入我的页面查看门店地址管理入口',max_chars=5000)
            self.assertEqual(result['pages'][0]['path'],'/main')


class ListObservationTests(unittest.TestCase):
    def web(self):
        e=Mock();e.excel_observation_mode=True;e.secrets=['private-token']
        web=hybrid_webview.WebView(e);web.collect_diagnostics=Mock();return web
    def test_records_selector_count_and_names_and_distinguishes_unavailable(self):
        web=self.web();web.js=Mock(return_value={'messages':[],'total_dom_count':2,'match_count':2,'has_data':True,'texts':['门店A','门店B private-token'],'truncated':False})
        result=web.perform({'action':'web_observe','by':'css','value':'.store-name','text':'实际名称'})
        self.assertEqual(result['match_count'],2);self.assertEqual(result['texts'][0],'门店A')
        self.assertNotIn('private-token',str(result));self.assertEqual(web.js.call_args.args[1],['css','.store-name'])
        web.js.return_value={'selector_error':'invalid_selector'}
        result=web.perform({'action':'web_observe','by':'css','value':'['})
        self.assertIsNone(result['has_data']);self.assertIsNone(result['match_count'])
    def test_actual_javascript_counts_zero_and_multiple_rendered_elements(self):
        if not shutil.which('node'):self.skipTest('Node unavailable')
        web=self.web();web.js=Mock(return_value={'messages':[]})
        web.perform({'action':'web_observe','by':'css','value':'.card'})
        script=web.js.call_args.args[0]
        for count in (0,2,55):
            code="const nodes=Array.from({length:"+str(count)+"},(_,i)=>({innerText:'店'+i,textContent:'店'+i,getBoundingClientRect:()=>({width:100,height:50}),querySelector:()=>null,matches:()=>false}));const document={querySelectorAll:s=>s==='.card'?nodes:[]};const getComputedStyle=()=>({display:'block',visibility:'visible'});const fn=new Function('document','getComputedStyle',"+json.dumps('return function(){'+script+'}')+");process.stdout.write(JSON.stringify(fn(document,getComputedStyle).apply(null,['css','.card'])));"
            result=json.loads(subprocess.check_output(['node','-e',code],text=True))
            self.assertEqual(result['match_count'],count);self.assertEqual(result['has_data'],count>0)
            self.assertEqual(len(result['texts']),min(50,count));self.assertEqual(result['truncated'],count>50)


if __name__=='__main__':unittest.main()
