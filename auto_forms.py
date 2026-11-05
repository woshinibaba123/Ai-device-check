"""Local form discovery and conservative data binding. Exploration never submits."""
import hashlib
import json
import re
import automation
import form_runner


def validate(config):
    data=config.get('data',{})
    if not isinstance(data,dict) or len(data)>80:raise ValueError('自动填表测试数据需为最多 80 项的对象')
    clean={}
    for key,value in data.items():
        if not isinstance(key,str) or not key.strip() or len(key)>160 or not (type(value) is bool or isinstance(value,str) and 0<len(value)<=2000):raise ValueError('自动填表数据格式无效，请按字段名填写文本或勾选值')
        clean[key.strip()]=value
    return {'enabled':True,'mode':'auto','data':clean,'submit_policy':'never'}


def norm(text):
    text=re.sub(r'^(?:please\s+(?:enter|input|select|type\s+in|fill\s+in)|请输入|请填写|请选择)\s*','',str(text or '').strip(),flags=re.I)
    text=re.sub(r"^(?:the|your|a|an)\s+",'',text,flags=re.I).replace("'s",'').replace('’s','')
    text=re.sub(r'^corresponding\s+','',text,flags=re.I)
    return re.sub(r'[\W_]+','',text.casefold())


ALIASES={
    'contact_name':['联系人','姓名','联系姓名','联系人姓名','contact','contact name','contact person','name'],
    'description':['问题描述','故障描述','备注','描述','problem description','description','remarks','remark','details'],
    'phone':['联系电话','手机号','手机号码','电话','phone','phone number','contact phone number','telephone','mobile'],
    'contact_info':['联系方式','联系信息','contact information','phone number or email address'],
    'email':['邮箱','电子邮箱','email','email address'],
    'store':['门店','门店名称','store','store name'],
    'robot':['机器人编号','机器编号','设备编号','robot number','robot sn','serial number','device id'],
    'problem_type':['问题类型','故障类型','question type','problem type','issue type'],
}
SEARCH=re.compile(r'搜索|搜尋|筛选|search|filter',re.I)
SECURE=re.compile(r'密码|验证码|password|passcode|verification.?code|sms.?code|\botp\b|token|secret',re.I)
CONSENT=re.compile(r'协议|条款|隐私|agreement|terms|privacy|consent',re.I)
SUBMIT=re.compile(r'^(提交|保存|submit|save|send|确认提交|立即提交|submit report)$',re.I)
GENERATED={'contact_name':'自动化测试','description':'自动化回归测试数据，请忽略。'}


def category(label):
    if re.search(r'please describe (?:the |your )?(?:issue|problem)|请描述.{0,4}(?:问题|故障)',label,re.I):return 'description'
    name=norm(label)
    return next((kind for kind,names in ALIASES.items() if name in {norm(v) for v in names}),None)


def choose(field,data):
    """Explicit data first. Only ordinary name/description fields get generated text."""
    label=field['label'];kind=field['kind']
    if SECURE.search(label) or field.get('secure'):return None,None,'登录或敏感字段使用专用流程'
    if CONSENT.search(label):return None,None,'协议或隐私勾选项不自动处理'
    names=[label,*field.get('aliases',[])]
    matches=[(key,value) for key,value in data.items() if norm(key) in {norm(n) for n in names if n}]
    semantic=category(label)
    if not matches and semantic:matches=[(k,v) for k,v in data.items() if category(k)==semantic]
    if not matches and semantic=='contact_info':matches=[(k,v) for k,v in data.items() if category(k) in ('phone','email')]
    if len(matches)>1:return None,None,'测试数据存在多个匹配值，请保留唯一配置'
    if matches:
        value=matches[0][1]
        if kind=='checkbox' and type(value) is not bool:return None,None,'勾选项需要 true 或 false'
        if kind!='checkbox' and not isinstance(value,str):return None,None,'该字段需要文本测试数据'
        if kind=='select' and field.get('options_known',True) and value not in field.get('options',[]):return None,None,'配置的选项不在当前可用列表中'
        maximum=field.get('max_length')
        if isinstance(maximum,int) and maximum>0 and isinstance(value,str) and len(value)>maximum:return None,None,'测试数据超过字段长度限制'
        return value,'configured',''
    if kind=='text' and label.strip().casefold()!='name' and semantic in GENERATED and field.get('input_type','text') in ('text','textarea',''):
        value=GENERATED[semantic];maximum=field.get('max_length')
        if re.search(r'[A-Za-z]',label) and not re.search(r'[\u4e00-\u9fff]',label):
            value='Automation Test' if semantic=='contact_name' else 'Automation test report. This is synthetic regression test data for form validation only. Please ignore.'
        if isinstance(maximum,int) and maximum>0 and len(value)>maximum:return None,None,'字段长度不足，需提供符合限制的测试数据'
        return value,'generated',''
    # 常见输入类型直接生成确定性测试数据，减少"待配置"。
    input_type=field.get('input_type','text')
    typed={'email':'automation@test.example','tel':'13800000000','number':'1',
           'date':'2026-01-01','time':'10:00','datetime-local':'2026-01-01T10:00',
           'month':'2026-01','week':'2026-W01','url':'https://example.com','search':'自动化测试'}
    if kind=='text' and input_type in typed:
        value=typed[input_type];maximum=field.get('max_length')
        if isinstance(maximum,int) and maximum>0 and len(value)>maximum:return None,None,'字段长度不足，需提供符合限制的测试数据'
        return value,'generated',''
    return None,None,'缺少有效测试数据，未猜测业务值或默认选项'


DISCOVER=r'''const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
const candidates=[...document.querySelectorAll('input:not([type=hidden]),textarea,select')].filter(e=>visible(e)&&!e.disabled&&!e.readOnly);
if(candidates.some(e=>e.type==='password'))return {ignored:'secure'};
const forms=[...new Set(candidates.map(e=>e.form).filter(Boolean))];
if(forms.length>1)return {ambiguous:true,fields:[],buttons:[]};
const root=forms[0]||document;
const controls=candidates.filter(e=>!forms.length||e.form===forms[0]);
const label=e=>{const labels=[...(e.labels||[])].map(n=>n.innerText.trim()).filter(Boolean);const near=e.parentElement;
return e.getAttribute('aria-label')||labels.join(' ')||e.getAttribute('placeholder')||
(near&&near.children.length<5?(near.querySelector('label')?.innerText||''):'')||e.name||e.id||'';};
const fields=controls.slice(0,31).map((e,i)=>({label:label(e).replace(/^[*\s]+|[*\s]+$/g,''),aliases:[e.name,e.id,e.getAttribute('placeholder')].filter(Boolean),
kind:e.tagName==='SELECT'?'select':e.type==='checkbox'?'checkbox':['file','radio','range','color','button','submit','reset'].includes(e.type)?'unsupported':'text',
input_type:e.tagName==='TEXTAREA'?'textarea':e.type||'text',required:e.required||e.getAttribute('aria-required')==='true',filled:e.type==='checkbox'?e.checked:!!String(e.value||'').trim(),
max_length:e.maxLength>0?e.maxLength:null,options:e.tagName==='SELECT'?[...e.options].filter(o=>!o.disabled&&o.value!=='').map(o=>o.text.trim()):[],element:e}));
const buttons=[...root.querySelectorAll('button,input[type=submit],[role=button]')].filter(visible).map(e=>(e.innerText||e.value||e.getAttribute('aria-label')||'').trim());
return {path:location.origin+location.pathname,fields,buttons};'''


def native_snapshot(nodes):
    fields=[]
    for node in nodes:
        if not (node['editable'] or any(v in node['kind'] for v in ('CheckBox','Spinner','RadioButton'))):continue
        if node['secure']:return {'ignored':'secure'}
        label=node.get('hint') or node.get('id') or node.get('label','')
        # A value in an unnamed input must not be mistaken for the field name.
        if node['editable'] and not node.get('hint') and not node.get('id') and not (category(label) or re.search(r'请输入|please (?:enter|input|select)',label,re.I)):
            label=''
            box=re.findall(r'\d+',node.get('bounds',''))
            if len(box)==4:
                left,top,right,bottom=map(int,box)
                nearby=[]
                for other in nodes:
                    b=re.findall(r'\d+',other.get('bounds',''))
                    if other['editable'] or other['clickable'] or not other['label'] or len(b)!=4:continue
                    x,y,r,t=map(int,b)
                    if 0<=top-t<140 and abs(left-x)<160:nearby.append((top-t,other['label']))
                nearby.sort()
                if len(nearby)==1 or len(nearby)>1 and nearby[0][0]<nearby[1][0]:label=nearby[0][1]
        kind='checkbox' if 'CheckBox' in node['kind'] else 'select' if 'Spinner' in node['kind'] else 'unsupported' if 'RadioButton' in node['kind'] else 'text'
        fields.append({'label':label,'kind':kind,'input_type':'text','required':True,'filled':bool(node.get('hint') and node.get('label','').strip() not in ('',node['hint'].strip(),'[已隐藏]') and not re.search(r'^please (?:enter|select|type)|^请输入',node.get('label',''),re.I)),'aliases':[node.get('hint',''),node.get('id','')],'path':node['path'],'options':[],'options_known':False})
    return {'fields':fields,'buttons':[n['label'].strip() for n in nodes if n['clickable']]}


class NativeDriver(form_runner.Native):
    def __init__(self,e,fields):super().__init__(e);self.fields={f['label']:f for f in fields}
    def resolve(self,label,kind):
        binding=self.fields.get(label)
        if binding:
            nodes=self.nodes();aliases={v for v in binding.get('aliases',[]) if v}
            eligible=[n for n in nodes if not n['secure'] and (n['editable'] if kind=='text' else any(v in n['kind'] for v in ('CheckBox','Spinner')))]
            if aliases:found=[n for n in eligible if aliases & {n.get('hint',''),n.get('id','')}]
            else:
                # Re-identify the field after layout changes; never trust an old row index alone.
                current=native_snapshot(nodes).get('fields',[])
                paths=[f['path'] for f in current if f['label']==label and f['kind']==kind]
                found=[n for n in eligible if n['path'] in paths]
            if len(found)!=1:raise form_runner.FormError('自动识别的控件已变化')
            return found[0]
        return super().resolve(label,kind)
    def fill(self,f):
        if f['kind']!='select':return super().fill(f)
        self.e.tap(self.resolve(f['label'],'select'))
        option=super().resolve(f['value'],'select');self.e.tap(option)
        selected=self.resolve(f['label'],'select')
        if f['value'] not in (selected['label'],selected.get('value','')) and not any(n['path'].startswith(selected['path']+'/') and n['label']==f['value'] for n in self.nodes()):
            raise form_runner.FormError('选择项未在原字段中回显')


class WebDriver(form_runner.Web):
    def __init__(self,w,fields):super().__init__(w);self.fields={f['label']:f for f in fields}
    def resolve(self,label,kind):
        field=self.fields.get(label)
        if field:
            el=field['element']
            if not self.w.js('const e=arguments[0];return e.isConnected&&!e.disabled&&!!e.getClientRects().length&&e.type!=="password";',[el]):raise form_runner.FormError('自动识别的 H5 控件已变化')
            return el
        return super().resolve(label,kind)


def candidate(snapshot):
    fields=snapshot.get('fields',[])
    if snapshot.get('ignored') or any(SECURE.search(f.get('label','')) for f in fields):return False
    if snapshot.get('ambiguous'):return True
    if not fields:return False
    if all(SEARCH.search(f.get('label','')) for f in fields):return False
    # One unlabelled search/address bar is not a business form.
    return len([f for f in fields if f['kind'] in ('text','select')])>=2 or any(SUBMIT.fullmatch(b) for b in snapshot.get('buttons',[])) or any(category(f.get('label',''))=='description' for f in fields)


def protected(snapshot):
    return snapshot.get('ignored')=='secure' or any(SECURE.search(f.get('label','')) for f in snapshot.get('fields',[]))


def protected_result():
    return {'page':'受保护的输入页面','automatic':True,'status':'blocked','submitted':False,'fields':[],
            'reason':'登录、密码或验证码页面使用专用流程；未填写，也不点击验证或提交按钮'}


def fill(e,snapshot,config):
    fields=snapshot.get('fields',[])
    result={'page':'自动识别表单','automatic':True,'status':'blocked','submitted':False,'fields':[],'verification':'field_readback_only'}
    if snapshot.get('ambiguous') or len(fields)>30:
        result['reason']='存在多张表单或字段过多，需明确测试范围；未填写';return result
    names=[f.get('label','') for f in fields]
    if len([n for n in names if n])!=len(set(n for n in names if n)):
        result['reason']='存在同名字段，无法唯一绑定；未填写';return result
    count=0;missing=0
    driver=snapshot['_driver']
    for field in fields:
        label=field.get('label') or '未识别字段'
        item={'label':automation.redact(label,e.secrets),'kind':field['kind']}
        if e.stopped():item.update(status='blocked',reason='用户停止');result['fields'].append(item);missing+=1;break
        if field['kind']=='unsupported':item.update(status='blocked',reason='该控件需要附件、日期选择或专用操作支持');missing+=1
        elif field.get('filled') and choose(field,config.get('data',{}))[1]!='configured':
            item.update(status='existing',reason='保留页面已有值，未替换');count+=1
        else:
            value,source,reason=choose(field,config.get('data',{}))
            if reason:item.update(status='missing_data',reason=reason);missing+=1
            else:
                e.secrets=list(e.secrets)+([value] if isinstance(value,str) else [])
                e.form_data_active=True
                try:
                    driver.fill({'label':field['label'],'kind':field['kind'],'value':value})
                    item.update(status='filled',source=source,verified=True);count+=1
                except Exception:
                    item.update(status='blocked',reason='输入或回读校验失败；未提交');missing+=1
        result['fields'].append(item)
    result['status']='partial' if count and missing else 'filled' if count else 'blocked'
    result['filled_count']=sum(v['status']=='filled' for v in result['fields'])
    result['existing_count']=sum(v['status']=='existing' for v in result['fields'])
    result['missing_count']=missing
    result['required_data']=[v['label'] for v in result['fields'] if v['status']=='missing_data' and not re.search(r'协议|隐私',v.get('reason',''))]
    result['consent_required']=[v['label'] for v in result['fields'] if v['status']=='missing_data' and re.search(r'协议|隐私',v.get('reason',''))]
    result['adaptation_required']=[v['label'] for v in result['fields'] if v['status']=='blocked']
    result['reason']='已填写 '+str(result['filled_count'])+' 项、保留 '+str(result['existing_count'])+' 项；'+str(missing)+' 项待配置或待适配；未提交'
    return result


def visit(e,nodes,route,config,cache):
    """Return (is_form, new_result). Cache layout identities, never current values."""
    fields=native_snapshot(nodes)
    layout=[(n['kind'],n.get('id',''),n.get('hint',''),n['path']) for n in nodes if n['editable'] or any(v in n['kind'] for v in ('CheckBox','Spinner','RadioButton'))]
    titles=[n['label'] for n in nodes if 'WebView' in n['kind']]
    key=str(getattr(e,'auto_form_epoch',0))+':'+hashlib.sha256(json.dumps((route,layout,titles),ensure_ascii=False).encode()).hexdigest()
    if key in cache:return cache[key],None
    native_key='native:'+hashlib.sha256(json.dumps((route,titles,[(f.get('label',''),f.get('kind','')) for f in fields.get('fields',[])]),ensure_ascii=False).encode()).hexdigest()
    if cache.get(native_key):cache[key]=True;return True,None
    if protected(fields):cache[key]=True;return True,protected_result()
    web=any('WebView' in n['kind'] for n in nodes)
    if not web and not candidate(fields):cache[key]=False;return False,None
    started=False;result=None
    try:
        if web:
            from hybrid_webview import WebView
            with WebView(e) as w:
                snapshot=w.js(DISCOVER,read_only=True)
                if protected(snapshot):cache[key]=True;return True,protected_result()
                if not candidate(snapshot):cache[key]=False;return False,None
                full='full:'+hashlib.sha256(json.dumps((snapshot.get('path',''),[(f.get('label',''),f['kind'],f.get('aliases',[])) for f in snapshot.get('fields',[])]),ensure_ascii=False).encode()).hexdigest()
                cache[key]=True
                if full in cache:return True,None
                cache[full]=True
                snapshot['_driver']=WebDriver(w,snapshot.get('fields',[]))
                started=True;result=fill(e,snapshot,config)
            return True,result
        cache[key]=True;fields['_driver']=NativeDriver(e,fields['fields'])
        return True,fill(e,fields,config)
    except Exception as error:
        if started:
            # Restoration failure must never trigger a second fill through another driver.
            result=result or {'page':'自动识别表单','automatic':True,'status':'blocked','submitted':False,'fields':[],'reason':'填写过程受阻，未重复填写或提交'}
            try:e.call('POST',e.base+'/context',{'name':'NATIVE_APP'})
            except Exception:
                result.update(status='blocked',stop_exploration=True,reason='无法恢复原生操作上下文，停止探索；未重复填写或提交')
            return True,result
        if candidate(fields):
            cache[key]=True
            cache[native_key]=True
            fields['_driver']=NativeDriver(e,fields.get('fields',[]))
            result=fill(e,fields,config)
            result['discovery']='native_accessibility'
            result['coverage_note']='H5 页面结构未能读取，仅处理当前原生可访问字段；不代表识别了全部必填项'
            result['discovery_reason']=automation.redact(str(error),e.secrets)[:250]
            return True,result
        cache[key]=False;return False,None
