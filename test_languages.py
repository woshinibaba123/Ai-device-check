import unittest,itertools
from unittest.mock import patch
from language_tests import LANGUAGES,expand,validate,text_findings
from automation import Explorer,ELEMENT,LoginBlocked,parse_ui

class LanguageTests(unittest.TestCase):
    def config(self,codes):return {'enabled':True,'selected':[{'code':c,'path':[],'choice':next(v['name'] for v in LANGUAGES if v['code']==c),'marker':'verified-'+c} for c in codes]}
    def test_matrix_expands_device_and_language(self):
        entries=[('a',{'platform':'Android','device':'1'},'设备一'),('b',{'platform':'Android','device':'2'},'设备二')]
        results=expand(entries,self.config(['zh-CN','en-US','ja-JP']))
        self.assertEqual(len(results),6);self.assertEqual(len(set(i for i,_,_ in results)),6)
        self.assertEqual({cfg['language']['code'] for _,cfg,_ in results},{'zh-CN','en-US','ja-JP'})
    def test_no_language_configuration_keeps_existing_jobs(self):
        entries=[('a',{},'a')];self.assertEqual(expand(entries,{'enabled':False}),entries)
    def test_missing_marker_is_allowed(self):
        c=self.config(['ja-JP']);c['selected'][0]['marker']=''
        self.assertEqual(validate(c)[0]['code'],'ja-JP')
    def test_legacy_marker_is_ignored(self):
        c=self.config(['ja-JP']);c['selected'][0]['marker']='日本語'
        self.assertEqual(validate(c)[0]['code'],'ja-JP')
    def test_duplicate_language_rejected(self):
        with self.assertRaises(ValueError):validate(self.config(['ja-JP','ja-JP']))
    def test_text_findings_are_only_hints(self):
        findings=text_findings([{'label':'login_title'},{'label':'Hello {{name}}'},{'label':'broken\ufffd'},{'label':'KEENON'},{'label':'password_key','secure':True}])
        self.assertEqual(len(findings),3)
    def test_switch_continues_without_content_verification(self):
        class Driver:
            state='menu'
            index=0
            def __call__(self,method,path,data=None):
                if path.endswith('/source'):
                    label=['我的','通用设置','语言','日本語','ホーム'][self.index]
                    return '<hierarchy><node class="android.widget.Button" text="'+label+'" clickable="true"/></hierarchy>'
                if path.endswith('/element'):return {ELEMENT:'option'}
                if path.endswith('/click'):
                    self.index+=1
                    if self.index==4:self.state='jp'
        d=Driver();exp=Explorer(d,'s','Android',lambda x:None,lambda *x:None)
        with patch('automation.time.sleep'):result=exp.switch_language({'code':'ja-JP','name':'日本語','choice':'日本語',})
        self.assertEqual(result['status'],'switched');self.assertNotIn('marker',result);self.assertEqual(d.state,'jp')
    def test_missing_language_option_blocks_execution(self):
        exp=Explorer(lambda *x:'<hierarchy><node class="android.widget.Button" text="English" clickable="true"/></hierarchy>','s','Android',lambda x:None,lambda *x:None)
        with self.assertRaises(LoginBlocked):exp.switch_language({'code':'ja-JP','name':'日本語','choice':'日本語','marker':'ホーム'})

class LanguagePreferenceTests(unittest.TestCase):
    def test_persisted_locale_is_checked_without_returning_other_preferences(self):
        from unittest.mock import Mock
        from language_tests import verify_persisted_language
        e=Mock();e.app_package='com.example'
        e.shell.return_value={'ok':True,'output':'<map><string name="flutter.selected_locale">ja_JP</string><string name="flutter.token">secret-token</string></map>'}
        config=next(x for x in LANGUAGES if x['code']=='ja-JP')
        result=verify_persisted_language(e,config)
        self.assertEqual(result['status'],'confirmed');self.assertNotIn('secret-token',str(result))
        with self.assertRaises(AssertionError):verify_persisted_language(e,next(x for x in LANGUAGES if x['code']=='en-US'))

class RuntimeLanguageAliasTests(unittest.TestCase):
    def test_verified_cloud_labels_are_local_only_and_checksum_required(self):
        import json,hashlib
        from unittest.mock import Mock
        from language_tests import load_runtime_aliases
        scope='eng|https://qa.example|CALLPHONE';name=hashlib.sha256(scope.encode()).hexdigest()+'.json'
        raw=json.dumps({'mine':'حسابي'},ensure_ascii=False)
        data={'schema':1,'scope':scope,'raw':{'ar':raw},'hashes':{'ar':hashlib.md5(raw.encode()).hexdigest()}}
        e=Mock();e.app_package='com.example';e.flow_index={'locale_packs':{'en':{'mine':'Mine'}},'translations':{'mine':['我的','Mine']}};e.control_aliases={}
        e.shell.side_effect=[{'ok':True,'output':name},{'ok':True,'output':json.dumps(data)}]
        result=load_runtime_aliases(e)
        self.assertEqual(result['languages'],['ar']);self.assertIn('حسابي',e.control_aliases['我的']);self.assertNotIn('raw',result)
        data['hashes']['ar']='wrong';e.control_aliases={};e.shell.side_effect=[{'ok':True,'output':name},{'ok':True,'output':json.dumps(data)}]
        self.assertIsNone(load_runtime_aliases(e));self.assertFalse(e.control_aliases)
