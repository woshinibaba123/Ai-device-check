"""Chinese business instructions resolved against runtime UI and translation keys.
Unrecognized instructions and ambiguous targets stop; writes use explicit adapters.
"""
import json
import re
import time
from pathlib import Path
import automation
import hybrid_webview

# Baseline adapter vocabulary; source translation keys extend every group.
GROUPS = [
 ['首页','主页','Home','ホーム'], ['消息','消息中心','Message','Messages','メッセージ'],
 ['我的','个人中心','Mine','マイページ'], ['报修','报修表单','Repair','Problem Reporting','工单报修'],
 ['门店','门店名称','Store Name','店舗名'], ['机器人','机器人编号','Robot Number','ロボット番号'],
 ['问题类型','故障类型','question type','Problem Type'], ['问题描述','故障描述','Problem Description'],
 ['联系人','Contact','連絡先氏名'], ['联系方式','Contact information','連絡先'],
 ['提交','Submit','送信'], ['用户协议','隐私协议','用户隐私协议','ユーザー契約'],
 ['语言','Language','言語'], ['通用设置','Common setting','General Settings'], ['消息设置','Message Settings'],
 ['提交成功','Submitted successfully','Submission successful'],
]


def norm(value):
    return re.sub(r'\s+', ' ', str(value).strip().lstrip('*＊')).strip().casefold()


def load_groups(source='', h5_source=''):
    groups=[list(g) for g in GROUPS]
    if source:
        by_key={}
        for path in sorted((Path(source).expanduser()/'assets/i18n').glob('*.json')):
            try:data=json.loads(path.read_text())
            except (OSError,ValueError):continue
            for key,value in data.items():
                if isinstance(value,str):by_key.setdefault(key,[]).append(value)
        groups.extend(by_key.values())
    if h5_source:
        # Read translation files only. Never execute project JavaScript.
        for root in ('src/lang','src/locales','src/i18n'):
            by_key={}
            for path in sorted((Path(h5_source).expanduser()/root).rglob('*')):
                if not path.is_file() or path.suffix not in ('.js','.ts','.json') or path.stat().st_size>500000:continue
                if path.suffix=='.json':
                    def flatten(obj,prefix=''):
                        for k,v in obj.items():
                            if isinstance(v,dict):yield from flatten(v,prefix+k+'.')
                            elif isinstance(v,str):yield prefix+k,v
                    try:pairs=list(flatten(json.loads(path.read_text())))
                    except (OSError,ValueError):continue
                else:
                    # Namespace by translation module to avoid merging unrelated keys.
                    pairs=[(m[1] or m[2],m[4]) for m in re.finditer(r'''^\s*(?:([\w]+)|['"]([^'"\n]+)['"])\s*:\s*(['"])((?:\\.|(?!\3)[^\\\n])*)\3\s*[,}]''',path.read_text(errors='replace'),re.M)]
                relative=path.relative_to(Path(h5_source).expanduser()/root)
                parts=[part for part in relative.parts if not re.fullmatch(r'(?:zh|en|ja|ko|fr|de|es|it|pt|ru|ar|th|vi|id)(?:[-_][A-Za-z]+)?(?:\.json|\.js|\.ts)?',part,re.I)]
                namespace='/'.join(parts) or 'root'
                for key,value in pairs:by_key.setdefault((namespace,key),[]).append(value)
            groups.extend(by_key.values())
    return groups


def terms(target,groups):
    result={norm(target)}
    # Expand by key, then baseline synonyms (e.g. 机器人 -> 机器人编号 -> other locales).
    for _ in range(4):
        previous=set(result)
        for group in groups:
            values={norm(v) for v in group if isinstance(v,str) and v.strip()}
            if result & values:result.update(values)
        if result==previous:break
    return sorted(result)


def unquote(value):
    return value.strip().strip('“”「」"\'')


def split_result_clause(line):
    closing=None
    pairs={'“':'”','「':'」','"':'"',"'":"'"}
    for i,char in enumerate(line):
        if closing:
            if char==closing:closing=None
        elif char in pairs:closing=pairs[char]
        elif char in '，,' and re.match(r'\s*(?:确认|检查)',line[i+1:]):
            return [line[:i],line[i+1:].strip()]
    return [line]


def compile_text(text):
    if not isinstance(text,str) or not text.strip() or len(text)>20000:raise ValueError('请填写中文业务步骤（最多 20000 字）')
    result=[]
    def add(op,line,**kw):result.append(dict(action='business',op=op,instruction=line,**kw))
    for number,raw in enumerate(text.splitlines(),1):
        line=re.sub(r'^\s*(?:第\s*\d+\s*步[：:、.]?|\d+[.、．)）])\s*','',raw).strip().rstrip('。；;')
        if not line:continue
        if line in ('自动登录','自动登录，进入首页','自动登录,进入首页'):
            add('login',line)
            if '首页' in line:add('click',line,target='首页')
            continue
        m=re.fullmatch(r'(?:回到|返回|进入)(首页|我的|消息)(?:页面)?',line)
        if m:add('click',line,target=m[1]);continue
        if line in ('返回','返回上一页'):add('back',line);continue
        if line in ('截图','保存截图'):add('screenshot',line);continue
        m=re.fullmatch(r'等待\s*(\d+)\s*秒',line)
        if m:
            if not 0<int(m[1])<=30:raise ValueError('第 %d 行：等待需为 1～30 秒'%number)
            add('wait',line,seconds=int(m[1]));continue
        # Explicit result wording becomes a separate assertion, never silently dropped.
        parts=split_result_clause(line)
        if len(parts)==2:
            nested=compile_text('\n'.join(parts))
            result.extend(nested);continue
        m=re.fullmatch(r'(?:点击|打开)(?:底部)?[“"「]?(.+?)[”"」]?',line)
        if m:
            target=unquote(m[1]).removesuffix('按钮')
            if target in ('提交','保存'):add('submit',line,target=target)
            else:add('click',line,target=target,tab='底部' in line)
            continue
        m=re.fullmatch(r'(?:确认|检查)(?:已经|已)?(?:回到|进入)?(.+?)(?:页面打开|页面已打开|已打开|页面出现|出现|是否提交成功|是否成功)?',line)
        if m:
            target=unquote(m[1])
            if line in ('检查是否提交成功','确认提交成功','检查提交成功'):add('submission_result',line)
            else:add('assert',line,target=target.removesuffix('页面'))
            continue
        m=re.fullmatch(r'等待(.+?)(?:加载完成|出现)',line)
        if m:add('assert',line,target=unquote(m[1]).removesuffix('表单') if m[1]!='报修表单' else '报修表单');continue
        m=re.fullmatch(r'(.+?)(?:填写|输入)(?:为)?[：:]?\s*(.+)',line)
        if m:add('input',line,target=unquote(m[1]).removeprefix('在').removesuffix('输入框').strip(),text=unquote(m[2]));continue
        m=re.fullmatch(r'(?:在)?[“"「]?(.+?)[”"」]?(?:输入框|中)(?:填写|输入)[：:]?\s*(.+)',line)
        if m:add('input',line,target=unquote(m[1]).removeprefix('在').removesuffix('输入框').strip(),text=unquote(m[2]));continue
        m=re.fullmatch(r'(.+?)选择(?:列表中)?(?:的)?(?:第一(?:个|台|项)(?:可用)?(?:选项)?|[“"「](.+)[”"」])',line)
        if m:add('select',line,target=unquote(m[1]),choice=m[2] or '',first=not bool(m[2]));continue
        m=re.fullmatch(r'勾选(?:用户协议|隐私协议|用户隐私协议)',line)
        if m:add('check',line,target='用户协议');continue
        raise ValueError('第 %d 行暂不能识别：%s。请写成“点击我的”“门店选择「名称」”“联系人填写「内容」”“确认首页”等步骤。'%(number,line))
    if not result or len(result)>200:raise ValueError('需有 1～200 个业务操作')
    return result


# Discover rendered labels and associated DOM controls, without reading credentials or page URL.
DISCOVER=r'''
const [words,mode]=arguments;
const normalize=s=>String(s||'').trim().replace(/^[*＊]+/,'').replace(/\s+/g,' ').trim().toLowerCase();
const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&getComputedStyle(e).display!=='none';
const matches=s=>words.includes(normalize(s));
const xpath=e=>{const parts=[];while(e&&e.nodeType===1){let i=1;for(let p=e.previousElementSibling;p;p=p.previousElementSibling)if(p.tagName===e.tagName)i++;parts.unshift(e.tagName.toLowerCase()+'['+i+']');e=e.parentElement}return '/'+parts.join('/')};
let found=[];
if(mode==='field'){
 for(const wrap of document.querySelectorAll('.el-form-item,.van-field,[role=group]')){
  const label=wrap.querySelector('.el-form-item__label,.van-field__label,label');
  if(label&&matches(label.innerText))found.push(...wrap.querySelectorAll('input:not([type=hidden]),textarea,select'));
 }
 for(const label of document.querySelectorAll('label[for]'))if(matches(label.innerText)){const e=document.getElementById(label.htmlFor);if(e)found.push(e)}
 for(const e of document.querySelectorAll('input,textarea,select'))if(matches(e.getAttribute('aria-label'))||matches(e.placeholder))found.push(e);
}else if(mode==='option'){
 found=[...document.querySelectorAll('.el-select-dropdown__item,[role=option],option')].filter(e=>!e.classList.contains('is-disabled')&&!e.disabled&&(words.length===0||matches(e.innerText)));
}else{
 found=[...document.querySelectorAll('button,a,[role=button],label,li,span,div')].filter(e=>visible(e)&&(matches(e.innerText)||matches(e.getAttribute('aria-label'))));
 found=found.filter(e=>!found.some(c=>c!==e&&e.contains(c)));
}
return [...new Set(found)].filter(visible).map(e=>({xpath:xpath(e),editable:['INPUT','TEXTAREA'].includes(e.tagName),label:(e.innerText||e.getAttribute('aria-label')||'').slice(0,160)}));
'''


# Read the loaded Vue i18n dictionaries; never switch locale or execute source files.
RUNTIME_TRANSLATIONS=r'''
const [words,target]=arguments;
const norm=s=>String(s||'').trim().replace(/^[*＊]+/,'').replace(/\s+/g,' ').trim().toLowerCase();
const dictionaries=new Set();
for(const el of document.querySelectorAll('*')){
 const vm=el.__vue__;
 if(vm&&vm.$i18n&&vm.$i18n.messages)dictionaries.add(vm.$i18n);
}
const groups=[];
for(const i18n of dictionaries){
 const messages=i18n.messages;
 const byKey=new Map();
 const walk=(obj,prefix,depth)=>{
  if(!obj||typeof obj!=='object'||depth>20)return;
  for(const [key,value] of Object.entries(obj)){
   const path=prefix?prefix+'.'+key:key;
   if(typeof value==='string'){
    if(!byKey.has(path))byKey.set(path,[]);
    byKey.get(path).push(value);
   }else walk(value,path,depth+1);
  }
 };
 const chinese=Object.entries(messages).filter(([locale])=>/^zh(?:[-_]|$)/i.test(locale));
 for(const [,locale] of chinese)walk(locale,'',0);
 const exact=[...byKey.entries()].filter(([,values])=>values.some(v=>norm(v)===norm(target)));
 if(exact.length){
  const current=messages[i18n.locale];
  const values=exact.map(([key])=>key.split('.').reduce((obj,k)=>obj&&obj[k],current)).filter(v=>typeof v==='string');
  if(values.length)return [...new Set(values.map(norm))];
 }
 byKey.clear();
 for(const locale of Object.values(messages))walk(locale,'',0);
 groups.push(...byKey.values());
}
const result=new Set(words.map(norm));
for(let i=0;i<4;i++)for(const group of groups){
 const values=group.map(norm);
 if(values.some(v=>result.has(v)))for(const v of values)result.add(v);
}
return [...result];
'''


def _web_find(web,target,groups,mode='text',first=False):
    words=[] if first else terms(target,groups)
    if not first:
        translated=web.js(RUNTIME_TRANSLATIONS,[words,target],read_only=True)
        if isinstance(translated,list) and all(isinstance(v,str) for v in translated):
            words=sorted(set(translated))
    found=web.js(DISCOVER,[words,mode],read_only=True)
    if not isinstance(found,list):raise RuntimeError('无法读取 H5 控件')
    if len(found)==1 or first and found:return found[0]
    if len(found)>1:raise ValueError('“%s”匹配多个控件，请补充具体名称；未点击'%target)
    return None


def _native(e,target,groups,tab=False):
    words=set(terms(target,groups));nodes=automation.parse_ui(e.source())
    package=getattr(e,'app_package','')
    matches=[n for n in nodes if (not package or n['package']==package) and (norm(n['label'].split('\n')[0]) in words or n['editable'] and norm(n.get('hint','')) in words) and (not tab or re.search(r'\nTab \d+ of \d+',n['label']))]
    clickable=[n for n in matches if n['clickable']]
    matches=clickable or matches
    if len(matches)>1:raise ValueError('“%s”匹配多个原生控件，请补充具体名称；未点击'%target)
    return (matches[0] if matches else None),nodes


def navigate_tab(e,target,groups,sleep):
    """Unwind only recognized native settings screens, never root/system Back."""
    settings=set(terms('语言',groups)+terms('通用设置',groups))
    for attempt in range(4):
        if e.stopped():raise RuntimeError('测试已停止')
        node,nodes=_native(e,target,groups,True)
        if node:
            e.tap(node)
            return {'operation':'click','target':target,'navigation_returns':attempt}
        package=getattr(e,'app_package','')
        app_nodes=[n for n in nodes if not package or n['package']==package]
        if not app_nodes or any('WebView' in n['kind'] or n.get('secure') for n in app_nodes):return None
        # If any root tab is already present, do not press Back and exit the App.
        if any(re.search(r'\nTab \d+ of \d+',n['label']) for n in app_nodes):return None
        if not any(norm(n['label'].split('\n')[0]) in settings for n in app_nodes):return None
        if attempt==3:break
        explicit=[n for n in app_nodes if n['clickable'] and re.fullmatch(r'返回|后退|back|navigate up',n['label'],re.I)]
        if len(explicit)==1:header=explicit[0]
        elif getattr(e,'platform','')=='Android':
            headers=[]
            for n in app_nodes:
                bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.get('bounds',''))
                if n['clickable'] and 'ImageView' in n['kind'] and bounds and int(bounds[1])<180 and int(bounds[2])<=200 and int(bounds[3])-int(bounds[1])<=180 and int(bounds[4])-int(bounds[2])<=180:
                    headers.append(n)
            if len(headers)!=1:return None
            header=headers[0]
        else:return None
        e.log('导航恢复：当前在语言或通用设置页，点击页面返回后前往“%s”。'%target)
        e.tap(header)
        e.settled_source()
    raise AssertionError('设置页返回后仍未出现“%s”页签，已停止恢复，未继续返回'%target)


def perform(e,step,sleep,login=None):
    op=step['op'];target=step.get('target','');groups=getattr(e,'business_groups',GROUPS)
    if op not in ('login','wait','screenshot','back','submission_result','submit','click','assert','input','select','check'):raise ValueError('未知业务操作')
    if op=='login':
        if (login or {}).get('status')!='confirmed':raise RuntimeError('请启用并配置自动登录；本次登录尚未确认')
        return {'operation':op,'confirmed':True}
    if op=='click' and any(norm(target) in terms(tab,groups) for tab in ('首页','我的','消息')):
        navigation=navigate_tab(e,target,groups,sleep)
        if navigation:return navigation
    if op=='wait':sleep(step['seconds']);return {'operation':op}
    if op=='screenshot':return {'operation':op}
    if op=='back':
        node,nodes=_native(e,'首页',groups,True)
        if node:e.tap(node)
        else:e.back(nodes)
        return {'operation':op}
    if op=='submission_result':
        if not getattr(e,'business_submission',None):raise RuntimeError('尚无本次提交的接口成功证据')
        return {'operation':op,'api':e.business_submission['api']}
    if op=='submit':
        with hybrid_webview.WebView(e) as web:
            # Application-specific binding, checked against live form before mutation.
            found=web.js("return !!document.querySelector('#repair button.btn-submit') && location.hash.split('?')[0]==='#/repairForm'",read_only=True)
            if not found:raise RuntimeError('当前页面没有已适配的提交接口，未点击；首版支持报修表单提交')
            result=web.perform({'action':'web_save','by':'css','value':'#repair button.btn-submit','api':{'method':'POST','path':'/api/devops/aftersale/work/order','codes':[610000],'timeout':60}})
            e.business_submission=result
            return result
    # Resolve known page assertions using unique content rather than persistent tab labels.
    page_marks={'首页':'报修','我的':'通用设置','消息':'消息设置','报修表单':'门店名称'}
    looking=page_marks.get(target,target) if op=='assert' else target
    deadline=time.monotonic()+30
    while True:
        if e.stopped():raise RuntimeError('测试已停止')
        node,nodes=_native(e,looking,groups,step.get('tab',False))
        is_web=any('WebView' in n['kind'] for n in nodes)
        if op in ('click','assert') and node and not (is_web and op=='click'):
            if op=='click':
                if not node['clickable']:raise RuntimeError('“%s”已找到，但未暴露可点击标识'%target)
                e.tap(node)
            return {'operation':op,'target':target,'matched_label':automation.redact(node['label'],getattr(e,'secrets',[]))}
        if op=='input' and node and node['editable'] and not is_web:
            if node.get('secure'):raise RuntimeError('密码字段请使用自动登录配置')
            eid=e.find({'by':'xpath','value':node['path']})
            e.type(eid,step['text'],node)
            attribute='value' if e.platform=='iOS' else 'text'
            actual=e.call('GET',e.base+'/element/'+eid+'/attribute/'+attribute)
            if actual!=step['text']:raise AssertionError('“%s”输入回读不一致'%target)
            return {'operation':op,'target':target,'matched':True}
        if is_web:
            with hybrid_webview.WebView(e) as web:
                if op=='check':
                    # Explicit agreement instruction; idempotently check only this form checkbox.
                    state=web.js("const e=document.querySelector('#repair .argument .van-checkbox');return e?{checked:e.getAttribute('aria-checked')==='true'||!!e.querySelector('.van-checkbox__icon--checked')}:null",read_only=True)
                    if state:
                        if not state['checked']:web.perform({'action':'web_tap','by':'css','value':'#repair .argument .van-checkbox__icon'})
                        after=web.js("return !!document.querySelector('#repair .argument .van-checkbox__icon--checked')",read_only=True)
                        if after is not True:raise AssertionError('用户协议未确认勾选')
                        return {'operation':op,'checked':True}
                else:
                    mode='field' if op in ('input','select') else 'text'
                    match=_web_find(web,looking,groups,mode)
                    if match:
                        locator={'by':'xpath','value':match['xpath']}
                        if op=='input':
                            web.perform(dict(locator,action='web_input',text=step['text']))
                            web.perform(dict(locator,action='web_assert_input',text=step['text']))
                        elif op=='click':web.perform(dict(locator,action='web_tap'))
                        elif op=='select':
                            if step.get('choice'):
                                web.perform(dict(locator,action='web_input',text=step['choice']))
                            else:web.perform(dict(locator,action='web_tap'))
                            option=None;end=time.monotonic()+30
                            while time.monotonic()<end:
                                if e.stopped():raise RuntimeError('测试已停止')
                                option=_web_find(web,step.get('choice',''),groups,'option',step.get('first',False))
                                if option:break
                                sleep(.5)
                            if not option:raise AssertionError('“%s”没有可选择的%s；请检查业务数据、列表接口或下拉框状态'%(target,'候选项' if step.get('first') else '“'+step.get('choice','')+'”'))
                            web.perform({'action':'web_tap','by':'xpath','value':option['xpath']})
                            if step.get('choice'):web.perform(dict(locator,action='web_assert_input',text=step['choice']))
                        return {'operation':op,'target':target,'matched':True}
        if time.monotonic()>=deadline:raise AssertionError('当前页面未找到“%s”的对应控件（已检查已配置的多语言文案）；未继续操作'%looking)
        sleep(.5)
