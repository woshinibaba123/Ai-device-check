"""Read case libraries and patch result cells without rebuilding the source XLSX."""
import json
import io
import math
import unicodedata
import posixpath
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
MAX_SIZE=30*1024*1024

def column(number):
    text=''
    while number:
        number,remainder=divmod(number-1,26);text=chr(65+remainder)+text
    return text

def column_number(address):
    value=0
    for ch in re.match(r'[A-Z]+',address)[0]:value=value*26+ord(ch)-64
    return value

def checked_path(value):
    path=Path(value).expanduser().resolve()
    if path.suffix.lower()!='.xlsx' or not path.is_file():raise ValueError('请选择存在的 .xlsx 用例文件')
    if path.stat().st_size>MAX_SIZE:raise ValueError('用例文件不能超过 30 MB')
    return path

def mobile_scope(case):
    title=case['title'];group=case.get('group','');text=title+' '+case.get('steps','')
    if re.search(r'压测|压力测试|埋点按照|接口性能',title):return False,'接口/埋点专项，不属于手机页面自动化'
    if group.startswith('云平台'):return False,'云平台用例'
    if group.startswith(('小程序','小程序端')) and not re.search(r'手机\s*APP|手机端|移动端',title,re.I):return False,'小程序用例'
    if re.search(r'验证小程序|小程序隐藏',title) and not re.search(r'手机\s*APP',title,re.I):return False,'小程序用例'
    if '小程序' in text and not re.search(r'手机|\bapp\b|安卓|Android|iOS',text,re.I):return False,'仅涉及小程序的步骤'
    if re.search(r'手机|APP|app|安卓|Android|iOS|IOS',text+group):return True,'手机 App 或手机联动用例'
    return True,'手机用例表中的页面/业务用例，执行前仍需核对条件'

def read(path):
    path=checked_path(path)
    content=path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if sum(i.file_size for i in archive.infolist())>120*1024*1024:raise ValueError('解压内容过大')
        strings=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings=[''.join(n.itertext()) for n in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si',NS)]
        rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets=[];cases=[]
        for sheet in ET.fromstring(archive.read('xl/workbook.xml')).findall('m:sheets/m:sheet',NS):
            target=rels[sheet.attrib['{'+REL+'}id']]
            target=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            xml=ET.fromstring(archive.read(target));rows=[]
            for row in xml.findall('m:sheetData/m:row',NS):
                values={}
                for cell in row.findall('m:c',NS):
                    value=cell.find('m:v',NS);value=value.text if value is not None else ''
                    if cell.get('t')=='s':value=strings[int(value)]
                    elif cell.get('t')=='inlineStr':value=''.join(t.text or '' for t in cell.findall('.//m:t',NS))
                    values[column_number(cell.get('r'))]=value or ''
                rows.append((int(row.get('r')),values))
            header=next(((n,v) for n,v in rows if '标题' in v.values() and ('步骤描述' in v.values() or '操作步骤' in v.values())),None)
            if not header:continue
            hn,hv=header;headers={str(v).strip():k for k,v in hv.items() if v}
            info={'name':sheet.get('name'),'xml':target,'header_row':hn,'last_column':max(headers.values()),'result_column':headers.get('执行结果'),'evidence_column':headers.get('实际结果与证据')};sheets.append(info)
            modules=['','','','']
            for nr,values in rows:
                if nr<=hn:continue
                def get(*names):return next((str(values.get(headers[k],'')) for k in names if k in headers),'')
                if not get('标题').strip():continue
                for index,key in enumerate(('一级模块','二级模块','三级模块','四级模块')):
                    if get(key):modules[index]=get(key);modules[index+1:]=['']*(3-index)
                case={'id':sheet.get('name')+':'+str(nr),'sheet':sheet.get('name'),'row':nr,'module':' / '.join(x for x in modules if x and x!='\\'),'title':get('标题'),'group':get('所属分组'),'priority':get('用例等级') or ('P0' if 'P0' in sheet.get('name','') else '未标注'),'precondition':get('前置条件'),'steps':get('步骤描述','操作步骤'),'expected':get('预期结果'),'plan_text':get('自动化步骤','自动化脚本'),'test_data':get('测试数据','输入数据')}
                case['mobile'],case['scope_reason']=mobile_scope(case)
                cases.append(case)
                if len(cases)>10000:raise ValueError('最多导入 10000 条用例')
    if not cases:raise ValueError('未找到包含“标题、步骤描述/操作步骤、预期结果”的用例表')
    return {'path':str(path),'content':content,'sheets':sheets,'cases':cases}

def summary(book):
    return {'total':len(book['cases']),'mobile':sum(c['mobile'] for c in book['cases']),'excluded':sum(not c['mobile'] for c in book['cases']),'priorities':dict(Counter(c['priority'] for c in book['cases'] if c['mobile'])),'sheets':[{'name':s['name'],'count':sum(c['sheet']==s['name'] for c in book['cases'])} for s in book['sheets']]}

def annotate(book,results,destination):
    """Only add automation columns; all other ZIP entries and original cells survive."""
    by_id={r['id']:r for r in results}
    with zipfile.ZipFile(io.BytesIO(book['content'])) as source,zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as output:
        changes={}
        workbook_xml=source.read('xl/workbook.xml').decode('utf-8')
        if '<calcPr' in workbook_xml:
            workbook_xml=re.sub(r'<calcPr\b[^>]*/>', '<calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1" calcMode="auto"/>',workbook_xml)
        else:workbook_xml=workbook_xml.replace('</workbook>','<calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1" calcMode="auto"/></workbook>')
        changes['xl/workbook.xml']=workbook_xml.encode('utf-8')
        wrapped_style=None
        if 'xl/styles.xml' in source.namelist():
            styles=source.read('xl/styles.xml').decode('utf-8')
            match=re.search(r'(<cellXfs\b[^>]*>)(.*?)(</cellXfs>)',styles,re.S)
            if match:
                wrapped_style=len(ET.fromstring('<x>'+match[2]+'</x>'))
                opening=re.sub(r'count="\d+"','count="'+str(wrapped_style+1)+'"',match[1])
                extra='<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
                changes['xl/styles.xml']=(styles[:match.start()]+opening+match[2]+extra+match[3]+styles[match.end():]).encode('utf-8')
        for sheet in book['sheets']:
            entries={sheet['header_row']:['自动化备注','自动化执行状态','自动化原因','自动化证据']}
            actual={}
            for case in book['cases']:
                if case['sheet']!=sheet['name']:continue
                result=by_id.get(case['id'],{})
                if result:actual[case['row']]=result
                entries[case['row']]=[result.get('result',''),result.get('status','未执行' if case['mobile'] else '排除非手机'),result.get('reason',case['scope_reason'] if not case['mobile'] else '尚未执行'),'; '.join(result.get('screenshots',[]))]
            raw=source.read(sheet['xml']).decode('utf-8')
            def patch_row(match):
                start,content,end=match.groups();nr=int(re.search(r'\br="(\d+)"',start)[1])
                if nr not in entries:return match[0]
                if nr in actual:
                    result=actual[nr]
                    status=result.get('status','未执行')
                    visible='pass' if result.get('result')=='pass' else 'blocked' if result.get('result')=='skip' or status in ('待转换','执行受阻','前置条件不满足','前序阶段未通过','已跳过') else '未执行' if status in ('未执行','已停止') else 'fail'
                    for field,value in (('result_column',visible),('evidence_column',result.get('reason','')+'\n'+'; '.join(result.get('screenshots',[])))):
                        if not sheet.get(field):continue
                        addr=column(sheet[field])+str(nr)
                        pattern=r'<c\b(?=[^>]*\br="'+addr+r'")[^>]*?(?:/>|>.*?</c>)'
                        old=re.search(pattern,content,re.S)
                        style=re.search(r'\bs="(\d+)"',old[0]) if old else None
                        clean=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))[:32000]
                        cell='<c r="'+addr+'"'+(' s="'+style[1]+'"' if style else '')+' t="inlineStr"><is><t xml:space="preserve">'+escape(clean)+'</t></is></c>'
                        content=re.sub(pattern,lambda _:cell,content,flags=re.S) if old else content+cell
                for offset,value in enumerate(entries[nr],1):
                    addr=column(sheet['last_column']+offset)+str(nr)
                    content=re.sub(r'<c\b(?=[^>]*\br="'+addr+r'")[^>]*?(?:/>|>.*?</c>)','',content,flags=re.S)
                    clean=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))[:32000]
                    content+='<c r="'+addr+'"'+(' s="'+str(wrapped_style)+'"' if wrapped_style is not None else '')+' t="inlineStr"><is><t xml:space="preserve">'+escape(clean)+'</t></is></c>'
                if nr!=sheet['header_row']:
                    widths=[16,22,80,80]
                    needed=max(math.ceil(sum(2 if unicodedata.east_asian_width(ch) in ('W','F') else 1 for ch in str(value))/width) for value,width in zip(entries[nr],widths))
                    height=max(float((re.search(r'\bht="([\d.]+)"',start) or [None,'15'])[1]),min(max(needed,2)*15,400))
                    start=re.sub(r'\s(?:ht|customHeight)="[^"]*"','',start)[:-1]+' ht="'+str(height)+'" customHeight="1">'
                return start+content+end
            raw=re.sub(r'(<row\b[^>]*>)(.*?)(</row>)',patch_row,raw,flags=re.S)
            # Used-range metadata must include the appended columns.
            dimension=re.search(r'<dimension\b[^>]*\bref="([^"]+)"',raw)
            last=max(entries);last_col=sheet['last_column']+4
            if dimension:
                end=dimension[1].split(':')[-1]
                last=max(last,int(re.search(r'\d+',end)[0]));last_col=max(last_col,column_number(end))
            raw=re.sub(r'<dimension\b[^>]*/>',lambda m:'<dimension ref="A1:'+column(last_col)+str(last)+'"/>',raw,count=1)
            # Split inherited column ranges so only the new result columns widen.
            cols=re.search(r'<cols>(.*?)</cols>',raw,re.S)
            definitions=[]
            if cols:
                for item in re.findall(r'<col\b[^>]*/>',cols[1]):
                    attrs=dict(ET.fromstring(item).attrib);low=int(attrs['min']);high=int(attrs['max'])
                    for left,right in ((low,min(high,sheet['last_column'])),(max(low,sheet['last_column']+5),high)):
                        if left<=right:definitions.append({**attrs,'min':str(left),'max':str(right)})
            for offset,width in enumerate((16,22,80,80),1):
                index=str(sheet['last_column']+offset)
                definitions.append({'min':index,'max':index,'width':str(width),'customWidth':'1'})
            definitions.sort(key=lambda d:int(d['min']))
            newcols='<cols>'+''.join('<col '+' '.join(k+'="'+escape(v)+'"' for k,v in d.items())+'/>' for d in definitions)+'</cols>'
            raw=raw[:cols.start()]+newcols+raw[cols.end():] if cols else raw.replace('<sheetData>',newcols+'<sheetData>',1)
            changes[sheet['xml']]=raw.encode('utf-8')
        for item in source.infolist():output.writestr(item,changes.get(item.filename,source.read(item.filename)))
