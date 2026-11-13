import tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
import h5_source
import codebuddy_bridge
from test_codebuddy_bridge import business_sample, bindings_sample

class H5SourceTests(unittest.TestCase):
    def test_imported_api_survives_small_excerpt_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'package.json').write_text('{}');(root/'src/api').mkdir(parents=True)
            (root/'src/repair.vue').write_text("import {save} from '@/api/repair';\n<button>报修提交</button>\n"+'\n'.join('<label>报修字段</label>' for _ in range(18)))
            (root/'src/api/repair.js').write_text("export function save() { return request.post('/api/repair/save'); }")
            for n in range(15):(root/f'src/noise{n}.vue').write_text('\n'.join('<label>报修字段</label>' for _ in range(18)))
            result=h5_source.summary(tmp,'报修提交',max_chars=1700)
            self.assertEqual(result['files'][0]['file'],'src/repair.vue')
            self.assertIn('/api/repair/save',json.dumps(result))

    def test_collects_page_evidence_without_env_dependencies_or_linked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'package.json').write_text('{}');(root/'src').mkdir()
            (root/'src/repair.vue').write_text('<button>提交保修</button>\nconst path="/repair"\nconst apiKey="private-value"')
            (root/'.env').write_text('secret=hidden');(root/'node_modules').mkdir();(root/'node_modules/hidden.js').write_text('title="private dependency"')
            result=str(h5_source.summary(tmp,'保修'))
            self.assertIn('repair.vue',result);self.assertIn('提交保修',result)
            self.assertNotIn('private-value',result);self.assertNotIn('private dependency',result)
    def test_rejects_url_and_missing_project(self):
        for value in ('https://example.com/repo','/missing/h5/source'):
            with self.assertRaises(ValueError):h5_source.summary(value,'test')
    def test_reused_index_selects_different_evidence_without_reading_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'package.json').write_text('{}')
            for n in range(18):(root/f'page{n:02}.vue').write_text('<button>普通入口</button>')
            (root/'repair.vue').write_text('<button>报修提交</button>')
            (root/'survey.vue').write_text('<input placeholder="勘察地址">')
            index=h5_source.source_index(tmp)
            with patch.object(Path,'read_text',side_effect=AssertionError('重复读取源码')):
                repair=h5_source.summary(tmp,'报修提交',index=index)
                survey=h5_source.summary(tmp,'勘察地址',index=index)
            self.assertEqual(repair['files'][0]['file'],'repair.vue')
            self.assertEqual(survey['files'][0]['file'],'survey.vue')
            with self.assertRaises(ValueError):h5_source.summary('/another/project','报修',index=index)
    def test_excel_h5_cache_is_per_generation_and_rescans_on_new_task(self):
        context=codebuddy_bridge.ExcelSourceContext()
        cfg={'outline':'保修','include_source':True,'h5_source':'/project','binding_only':True,'strict_excel':True,'document':business_sample(),'_excel_source_context':context}
        with patch.object(h5_source,'source_index',side_effect=[{'version':1},{'version':2}]) as scan,patch.object(h5_source,'summary',return_value={'files':[]}) as summary,patch.object(codebuddy_bridge,'ask',side_effect=[bindings_sample(),bindings_sample(),bindings_sample()]):
            codebuddy_bridge.generate(cfg)
            codebuddy_bridge.generate(dict(cfg,outline='勘察'))
            codebuddy_bridge.generate(dict(cfg,_excel_source_context=codebuddy_bridge.ExcelSourceContext()))
        self.assertEqual(scan.call_count,2)
        self.assertEqual([c.kwargs['index']['version'] for c in summary.call_args_list],[1,1,2])
        self.assertTrue(all('点击我的' in c.args[1] for c in summary.call_args_list))
        self.assertTrue(all(c.kwargs['max_chars']==12000 for c in summary.call_args_list))
    def test_h5_only_generation_sends_evidence_only_when_opted_in(self):
        doc={'cases':[{'title':'保修','expected':'显示表单','blocked_reason':'需 WebView 支持','plan':None}]}
        with patch.object(h5_source,'source_index',return_value={'project':'/project'}),patch.object(h5_source,'summary',return_value={'files':[{'file':'repair.vue','excerpt':'保修表单'}]}) as scan,patch.object(codebuddy_bridge,'ask',side_effect=[business_sample(),bindings_sample(),business_sample(),bindings_sample()]) as ask:
            codebuddy_bridge.generate({'outline':'保修','include_source':True,'h5_source':'/project'})
            scan.assert_called_once_with('/project','保修',index={'project':'/project'},max_chars=30000);self.assertIn('repair.vue',ask.call_args.args[0])
            scan.reset_mock();codebuddy_bridge.generate({'outline':'保修','h5_source':'/project'})
            scan.assert_not_called()

if __name__=='__main__':unittest.main()
