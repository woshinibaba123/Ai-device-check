import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app

class PipelineBuildCacheTests(unittest.TestCase):
    def test_same_source_reuses_binary_but_changes_or_extra_fields_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'ROOT',Path(tmp)):
            root=Path(tmp);source=root/'source';(source/'lib').mkdir(parents=True)
            (source/'lib/main.dart').write_text('void main(){}');(source/'pubspec.yaml').write_text('name: test')
            artifact=root/'original.apk';artifact.write_bytes(b'compiled-test-binary')
            cfg={'platform':'Android','pipeline_id':'a'*32,'source':str(source),'entrypoint':'lib/main.dart','route_tracking':True,'source_plan':{},'http_manifest':{'response_fields':['data.saved']},'flow_index':{'project':str(root/'temporary-clone')},'login':{'password':'TOP_SECRET_PWD'}}
            cfg['_pipeline_source_fingerprint']=app.pipeline_source_signature(source)
            cached=app.cache_pipeline_build(cfg,artifact,'devicecheck-login-'+('b'*32)+'.json')
            artifact.unlink();self.assertEqual(Path(cached).read_bytes(),b'compiled-test-binary')
            metadata=(root/'.runtime/pipeline-builds'/('a'*32)/'metadata.json').read_text()
            self.assertNotIn('TOP_SECRET_PWD',metadata)
            self.assertEqual(json.loads(metadata)['flow_index']['project'],str(source))
            target=dict(cfg,case_book={'cases':[]},cases={})
            self.assertTrue(app.apply_pipeline_build(target));self.assertEqual(target['source'],'');self.assertEqual(target['app'],cached)
            extra={'cases':[{'id':'a:1','mobile':True,'sheet':'a','priority':'P1','plan_text':json.dumps({'steps':[{'action':'save','value':'保存','api':{'equals':{'data.other':True}}}]})}]}
            self.assertFalse(app.apply_pipeline_build(dict(cfg,case_book=extra,cases={})))
            (source/'lib/main.dart').write_text('void main(){print("changed");}')
            self.assertFalse(app.apply_pipeline_build(dict(cfg,case_book={'cases':[]},cases={})))
    def test_android_cache_is_never_reused_for_ios(self):
        self.assertFalse(app.apply_pipeline_build({'pipeline_id':'a'*32,'source':'/source','targets':[{'platform':'iOS'}]}))
