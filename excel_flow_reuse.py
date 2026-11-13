"""Cross-module, structurally matched parameter reuse; never infer execution success."""
import copy
import re

FIELDS=('steps','expected','precondition','test_data')
QUOTED=re.compile(r'[“「\"]([^”」\"\n]*)[”」\"]')

def shape(case):
    return tuple(QUOTED.sub('"{}"',str(case.get(k,''))) for k in FIELDS)

def reuse(original,current,plan):
    if not plan or original.get('module')!=current.get('module'):return None
    if original.get('precondition','')!=current.get('precondition','') or shape(original)!=shape(current):return None
    replacements={};kinds={}
    for field in FIELDS:
        old=list(QUOTED.finditer(str(original.get(field,''))));new=list(QUOTED.finditer(str(current.get(field,''))))
        if len(old)!=len(new):return None
        for a,b in zip(old,new):
            av,bv=a[1],b[1]
            if av==bv:continue
            if not av or any(x in bv for x in ('[已隐藏]','[本机数据]')):return None
            if av in replacements and replacements[av]!=bv:return None
            replacements[av]=bv
            if field in ('steps','test_data'):
                prefix=str(original.get(field,''))[max(0,a.start()-12):a.start()]
                if re.search(r'选择|选中|切换为|切换到|勾选',prefix):kinds[av]='option'
                elif re.search(r'输入|填写|填入|设为|改为|内容[为是:=：]',prefix):kinds[av]='input'
    if not replacements or set(kinds)!=set(replacements):return None
    result=copy.deepcopy(plan);used=set()
    for step in result.get('requires',[])+result.get('steps',[]):
        for key,value in list(step.items()):
            if not isinstance(value,str):continue
            if value not in replacements:
                if any(a in value for a in replacements):return None
                continue
            action=step.get('action');kind=kinds[value]
            allowed=(kind=='input' and action in ('input','web_input','assert_input','web_assert_input') and key=='text') or (kind=='option' and action in ('tap','web_tap','assert_selected','assert') and key=='value' and step.get('by','text') in ('text','label'))
            if not allowed:return None
            step[key]=replacements[value];used.add(value)
    if used!=set(replacements):return None
    return result
