import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from unittest.mock import patch
from xml.sax.saxutils import escape
import case_workbook as workbook
import case_runner as runner
from automation import Explorer
from test_automation import FakeDriver

def fixture(path):
    headers=['一级模块','标题','所属分组','前置条件','步骤描述','预期结果','用例等级','备注']
    rows=[headers,
        ['首页','切换消息','首页','已登录','点击消息入口','进入消息页面','P0','原备注'],
        ['', '平台审核','云平台|审核','已登录','点击通过','审核通过','P0',''],
        ['', '小程序登录','小程序端|登录','已登录','点击登录','成功','P1',''],
        ['工业','原点呼叫','工业|原点呼叫','已连接机器人','呼叫机器人','机器人返航','P0',''],
        ['', '同名','首页','已登录','点击我的入口','进入我的页面','P1',''],
        ['', '同名','首页','已登录','点击我的入口','进入我的页面','P1','']]
    xml='<worksheet xmlns="'+workbook.NS['m']+'"><dimension ref="A1:H7"/><sheetData>'
    for i,row in enumerate(rows,1):
        xml+='<row r="'+str(i)+'">'
        for j,v in enumerate(row,1):xml+='<c r="'+workbook.column(j)+str(i)+'" t="inlineStr" s="0"><is><t>'+escape(v)+'</t></is></c>'
        xml+='</row>'
    xml+='</sheetData><mergeCells count="1"><mergeCell ref="A2:A4"/></mergeCells></worksheet>'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="'+workbook.NS['m']+'" xmlns:r="'+workbook.REL+'"><sheets><sheet name="手机全量" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',xml)
        z.writestr('native-part.bin',b'keep native metadata')

class WorkbookTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'cases.xlsx';fixture(self.path)
        self.book=workbook.read(self.path)
    def test_scope_priority_inheritance_and_duplicate_titles(self):
        self.assertEqual(workbook.summary(self.book)['mobile'],4)
        self.assertEqual([c['id'] for c in self.book['cases'] if c['title']=='同名'],['手机全量:6','手机全量:7'])
        self.assertEqual(self.book['cases'][1]['module'],'首页')
        self.assertEqual(runner.preview(self.book,{'priority':'P0'})['selected'],2)
    def test_results_preserve_original_cells_and_native_parts(self):
        before=self.path.read_bytes();out=Path(self.tmp.name)/'result.xlsx'
        workbook.annotate(self.book,[{'id':'手机全量:2','result':'pass','status':'已执行','reason':'a < b & c','screenshots':['/reports/proof.png']}],out)
        self.assertEqual(self.path.read_bytes(),before)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(z.read('native-part.bin'),b'keep native metadata')
            source=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            cells={c.get('r'):''.join(c.itertext()) for c in source.findall('.//m:c',workbook.NS)}
            self.assertEqual(cells['H2'],'原备注');self.assertEqual(cells['I2'],'pass')
            self.assertEqual(cells['K2'],'a < b & c');self.assertEqual(cells['J3'],'排除非手机')
            self.assertIsNotNone(source.find('m:mergeCells',workbook.NS))
    def test_input_snapshot_survives_original_replacement(self):
        self.path.write_bytes(b'replaced after import')
        out=Path(self.tmp.name)/'result.xlsx';workbook.annotate(self.book,[],out)
        self.assertTrue(zipfile.is_zipfile(out))
    def test_styled_empty_cells_do_not_consume_appended_results(self):
        import io
        temp=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.book['content'])) as original,zipfile.ZipFile(temp,'w') as changed:
            for entry in original.infolist():
                content=original.read(entry.filename)
                if entry.filename=='xl/worksheets/sheet1.xml':
                    import re
                    content=re.sub(rb'(<row r="2">.*?)(</row>)',lambda m:m[1]+b'<c r="I2" s="0"/><c r="J2" s="0"/><c r="K2" s="0"/><c r="L2" s="0"/>'+m[2],content)
                changed.writestr(entry,content)
        self.book['content']=temp.getvalue()
        out=Path(self.tmp.name)/'styled.xlsx'
        workbook.annotate(self.book,[{'id':'手机全量:2','result':'pass','status':'已执行','reason':'done','screenshots':[]}],out)
        with zipfile.ZipFile(out) as z:
            tree=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(''.join(tree.find('.//m:c[@r="I2"]',workbook.NS).itertext()),'pass')
    def test_empty_and_unsafe_paths_rejected(self):
        with self.assertRaises(ValueError):workbook.read(Path(self.tmp.name)/'missing.xlsx')
    def test_unsupported_case_never_becomes_pass(self):
        progress=[]
        result=runner.run(None,self.book,{'priority':'P0','plans':{'手机全量:2':{'steps':[]}}},lambda x:None,lambda *x:None,lambda x:progress.append(x[:]),lambda:False,lambda x:None)
        self.assertEqual([r['result'] for r in result],['skip','skip'])
        self.assertTrue(all(r['status']=='已跳过' for r in result))

class RunnerTests(unittest.TestCase):
    def test_natural_language_multi_step_requires_every_expected_result(self):
        plan=runner.compile_linear('【1】点击“消息”入口\n【2】点击“消息设置”按钮','【1】进入消息页面\n【2】显示“消息通知”')
        self.assertEqual([s['action'] for s in plan['steps']],['tap','assert_selected','tap','assert'])
        self.assertIsNone(runner.compile_linear('点击“消息”入口','显示“消息”，数据必须与云平台一致'))
    def test_screenshot_failure_cannot_be_pass(self):
        result=self.execute({'action':'assert','value':'Ready'},capture_ok=False)
        self.assertEqual(result['result'],'fail')
        self.assertIn('截图',result['reason'])
    def test_requires_are_assertions_and_final_assertion_is_mandatory(self):
        for plan in ({'steps':[{'action':'tap','value':'消息'}]}, {'requires':[{'action':'tap','value':'消息'}],'steps':[{'action':'assert','value':'消息'}]}):
            with self.assertRaises(ValueError):runner.validate_plan(plan)
    def test_simple_case_compiles_without_guessing_business_rules(self):
        case={'mobile':True,'precondition':'已登录','steps':'点击消息入口','expected':'进入消息页面'}
        plan,reason=runner.compile_case(case);self.assertFalse(reason)
        self.assertEqual(plan['steps'][-1]['action'],'assert_selected')
        case['expected']='显示10条消息，排序正确'
        self.assertIsNone(runner.compile_case(case)[0])
    def test_mobile_entry_in_miniprogram_group_is_kept(self):
        yes,_=workbook.mobile_scope({'title':'验证手机APP首页增加入口','group':'小程序端|入口','steps':'在首页查看'})
        self.assertTrue(yes)
    def test_selected_assertion_does_not_accept_unselected_tab(self):
        from automation import parse_ui
        nodes=parse_ui('<hierarchy><node text="Message&#10;Tab 3 of 4" clickable="true" selected="false"/></hierarchy>')
        self.assertIsNone(runner.find_node(nodes,{'action':'assert_selected','value':'消息'}))
    def execute(self,assertion,requires=None,stopped=False,capture_ok=True):
        driver=FakeDriver();captures=[];exp=Explorer(driver,'s','Android',lambda x:None,lambda *x:None)
        exp.app_package='com.example'
        xml='<hierarchy><node class="android.widget.Button" package="com.example" text="Home&#10;Tab 1 of 4" clickable="true" selected="true"/><node class="android.widget.Button" text="Ready" package="com.example" clickable="true"/></hierarchy>'
        case={'id':'S:2','sheet':'S','row':2,'title':'A','group':'首页','priority':'P0','precondition':'已登录','mobile':True,'steps':'explicit','expected':'explicit','plan_text':json.dumps({'requires':requires or [],'steps':[assertion]})}
        with patch.object(exp,'settled_source',return_value=xml),patch.object(exp,'tap'):
            return runner.run(exp,{'cases':[case]}, {},lambda x:None,lambda name,source:('/reports/'+name+'.png') if capture_ok else None,lambda x:None,lambda:stopped,lambda x:None)[0]
    def test_pass_requires_successful_assertion_and_evidence(self):
        result=self.execute({'action':'assert','value':'Ready'})
        self.assertEqual(result['result'],'pass');self.assertTrue(result['screenshots'])
    def test_default_case_run_has_no_total_time_limit(self):
        import itertools
        with patch('case_runner.time.monotonic',side_effect=itertools.count(0,10000)):
            result=self.execute({'action':'assert','value':'Ready'})
        self.assertEqual(result['result'],'pass')
    def test_failed_assertion_is_fail_with_evidence(self):
        result=self.execute({'action':'assert','value':'Missing'})
        self.assertEqual(result['result'],'fail');self.assertEqual(result['status'],'断言失败');self.assertTrue(result['screenshots'])
    def test_precondition_failure_is_distinguished(self):
        result=self.execute({'action':'assert','value':'Ready'},[{'action':'assert','value':'Missing'}])
        self.assertEqual(result['status'],'前置条件不满足');self.assertEqual(result['result'],'fail')
    def test_stop_does_not_pass_or_touch_app(self):
        result=self.execute({'action':'assert','value':'Ready'},stopped=True)
        self.assertEqual(result['status'],'已停止');self.assertEqual(result['result'],'fail')

if __name__=='__main__':unittest.main()

class ExistingResultColumnsTests(unittest.TestCase):
    def test_result_template_and_overview_recalculation_are_updated_in_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'input.xlsx';fixture(p)
            with zipfile.ZipFile(p) as z:parts={n:z.read(n) for n in z.namelist()}
            xml=parts['xl/worksheets/sheet1.xml'].decode().replace('<t>备注</t>','<t>执行结果</t>')
            xml=xml.replace('</row>','<c r="I1" t="inlineStr"><is><t>实际结果与证据</t></is></c></row>',1)
            parts['xl/worksheets/sheet1.xml']=xml.encode()
            with zipfile.ZipFile(p,'w') as z:
                for n,data in parts.items():z.writestr(n,data)
            book=workbook.read(p);original=p.read_bytes();out=Path(tmp)/'output.xlsx'
            workbook.annotate(book,[{'id':'手机全量:2','result':'pass','status':'已执行','reason':'断言通过','screenshots':['/reports/proof.png']},{'id':'手机全量:6','result':'fail','status':'待转换','reason':'缺少定位','screenshots':[]}],out)
            self.assertEqual(p.read_bytes(),original)
            with zipfile.ZipFile(out) as z:
                root=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
                values={c.get('r'):''.join(c.itertext()) for c in root.findall('.//m:c',workbook.NS)}
                self.assertEqual(values['H2'],'pass');self.assertEqual(values['H6'],'blocked')
                self.assertIn('/reports/proof.png',values['I2']);self.assertEqual(values['B2'],'切换消息')
                self.assertEqual(ET.fromstring(z.read('xl/workbook.xml')).find('m:calcPr',workbook.NS).get('fullCalcOnLoad'),'1')
