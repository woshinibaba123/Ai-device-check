import json,unittest
import case_runner
import automation

def node(text,kind='android.widget.TextView',resource_id='',clickable=False,bounds='[0,0][100,100]'):
    return ('<node index="0" text="{text}" resource-id="{rid}" class="{kind}" package="test.app" '
            'clickable="{click}" bounds="{bounds}"/>').format(text=text,rid=resource_id,kind=kind,click='true' if clickable else 'false',bounds=bounds)

def page(children):
    return '<hierarchy>'+children+'</hierarchy>'

DIALOG=page(node('即将前往微信打开此文章，使用完整服务。')
            +node('Cancel','android.widget.Button','test.app:id/cancel',True,'[0,300][400,420]')
            +node('Proceed','android.widget.Button','',True,'[400,300][800,420]'))
CLEAN=page(node('首页','android.widget.Button','test.app:id/home',True,'[0,2200][270,2340]')
           +node('OK'))
PERMISSION_DIALOG=page(node('允许 应用获取位置信息？')
    +node('拒绝','android.widget.Button','',True,'[0,300][360,420]')
    +node('仅在使用中允许','android.widget.Button','',True,'[360,300][720,420]')
    +node('允许','android.widget.Button','',True,'[720,300][1080,420]'))

class FakeExplorer:
    def __init__(self,sources):
        self.sources=list(sources);self.app_package='test.app';self.base='http://mock';self.secrets=[]
        self.taps=[];self.backs=[]
    def settled_source(self):
        if len(self.sources)>1:return self.sources.pop(0)
        return self.sources[0]
    def source(self):return self.sources[0]
    def tap(self,node):self.taps.append(node['label'])
    def back(self,nodes):self.backs.append(len(self.backs))

class PopupBackRecoveryTests(unittest.TestCase):
    def test_external_app_dialog_falls_back_to_back_after_two_taps(self):
        explorer=FakeExplorer([DIALOG,DIALOG,DIALOG,CLEAN])
        logs=[]
        book={'cases':[{'id':'AI:1','sheet':'AI','row':1,'module':'M','group':'手机 App','title':'打开外部程序弹窗恢复',
                        'priority':'P1','precondition':'','steps':'查看页面','expected':'出现OK',
                        'plan_text':json.dumps({'requires':[],'steps':[{'action':'assert','value':'OK'}]}),
                        'ai_pending':'','mobile':True,'scope_reason':''}]}
        results=case_runner.run(explorer,book,{},logs.append,lambda name,source:'shot.png',lambda results:None,lambda:False,lambda s:None)
        self.assertEqual(results[0]['result'],'pass')
        # 同一弹窗只点两次 Cancel，随后按返回键离开，不再反复点击。
        self.assertEqual(explorer.taps.count('Cancel'),2)
        self.assertEqual(len(explorer.backs),1)
        self.assertTrue(any('两次点击未关闭' in line for line in logs))
    def test_dialog_dismissed_on_first_tap_never_triggers_back(self):
        explorer=FakeExplorer([DIALOG,CLEAN])
        logs=[]
        book={'cases':[{'id':'AI:1','sheet':'AI','row':1,'module':'M','group':'手机 App','title':'弹窗一次关闭',
                        'priority':'P1','precondition':'','steps':'查看页面','expected':'出现OK',
                        'plan_text':json.dumps({'requires':[],'steps':[{'action':'assert','value':'OK'}]}),
                        'ai_pending':'','mobile':True,'scope_reason':''}]}
        results=case_runner.run(explorer,book,{},logs.append,lambda name,source:'shot.png',lambda results:None,lambda:False,lambda s:None)
        self.assertEqual(results[0]['result'],'pass')
        self.assertEqual(explorer.taps[0],'Cancel');self.assertNotIn('Cancel',explorer.taps[1:]);self.assertEqual(explorer.backs,[])
    def test_stubborn_dialog_after_backs_reports_blocked_without_endless_taps(self):
        explorer=FakeExplorer([DIALOG])
        logs=[]
        book={'cases':[{'id':'AI:1','sheet':'AI','row':1,'module':'M','group':'手机 App','title':'弹窗无法关闭',
                        'priority':'P1','precondition':'','steps':'查看页面','expected':'出现OK',
                        'plan_text':json.dumps({'requires':[{'action':'assert','value':'即将前往微信打开此文章'}],
                                                'steps':[{'action':'assert','value':'OK'}]}),
                        'ai_pending':'','mobile':True,'scope_reason':''}]}
        results=case_runner.run(explorer,book,{'start_from_current':True},logs.append,lambda name,source:'shot.png',lambda results:None,lambda:False,lambda s:None)
        self.assertEqual(results[0]['result'],'fail')
        self.assertIn('弹窗多次关闭后仍存在',results[0]['reason'])
        # 执行与失败留图各调用一次 stable_source：每轮只点 2 次 Cancel 再返回，共 4 次。
        self.assertEqual(explorer.taps.count('Cancel'),4);self.assertEqual(len(explorer.backs),4)

class PermissionDialogTests(unittest.TestCase):
    def book_case(self,title,plan_requires=()):
        return {'cases':[{'id':'AI:1','sheet':'AI','row':1,'module':'M','group':'手机 App','title':title,
                          'priority':'P1','precondition':'','steps':'查看页面','expected':'出现OK',
                          'plan_text':json.dumps({'requires':[{'action':'assert','value':v} for v in plan_requires] or [],
                                                  'steps':[{'action':'assert','value':'OK'}]}),
                          'ai_pending':'','mobile':True,'scope_reason':''}]}
    def test_permission_dialog_defaults_to_allow(self):
        explorer=FakeExplorer([PERMISSION_DIALOG,PERMISSION_DIALOG,CLEAN])
        logs=[]
        results=case_runner.run(explorer,self.book_case('普通用例'),{},logs.append,lambda n,s:'p.png',lambda r:None,lambda:False,lambda s:None)
        self.assertEqual(results[0]['result'],'pass')
        self.assertEqual(explorer.taps[0],'允许')
        self.assertTrue(any('权限弹窗默认允许' in line for line in logs))
    def test_case_demanding_denial_taps_deny(self):
        explorer=FakeExplorer([PERMISSION_DIALOG,PERMISSION_DIALOG,CLEAN])
        logs=[]
        results=case_runner.run(explorer,self.book_case('拒绝位置权限后继续操作'),{},logs.append,lambda n,s:'p.png',lambda r:None,lambda:False,lambda s:None)
        self.assertEqual(results[0]['result'],'pass')
        self.assertEqual(explorer.taps[0],'拒绝')

if __name__=='__main__':unittest.main()
