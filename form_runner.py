"""Opt-in form transactions. One submission per configured page per run."""
import re
import time
import automation


class FormError(RuntimeError):pass


def validate(config):
    if config is None:config={'mode':'auto'}
    if not isinstance(config,dict):raise ValueError('表单配置必须为对象')
    if config.get('mode') not in (None,'auto','manual','off'):raise ValueError('未知表单处理方式')
    if config.get('mode')=='auto' and config.get('enabled') is not False:
        import auto_forms
        return auto_forms.validate(config)
    if config.get('enabled') is not True:return {'enabled':False,'mode':'off'}
    result={'enabled':True}
    for key,name in [('page','页面识别文字'),('submit','提交按钮'),('success','提交成功标识')]:
        value=config.get(key)
        if not isinstance(value,str) or not value.strip() or len(value)>160:raise ValueError('请填写有效的'+name)
        result[key]=value.strip()
    if result['success']==result['page']:raise ValueError('成功标识不能与表单页面识别文字相同')
    fields=config.get('fields',[])
    if not isinstance(fields,list) or not 1<=len(fields)<=30:raise ValueError('请配置 1 至 30 个表单字段')
    result['fields']=[];seen=set()
    for f in fields:
        if not isinstance(f,dict):raise ValueError('字段配置无效')
        label=f.get('label','');kind=f.get('kind','text');value=f.get('value')
        if not isinstance(label,str) or not label.strip() or len(label)>120 or label in seen:raise ValueError('字段名称为空、过长或重复')
        if re.search(r'password|密码|验证码|otp|token|secret',label,re.I):raise ValueError('密码或验证码请使用专用登录流程')
        if kind not in ('text','select','checkbox'):raise ValueError('表单字段仅支持文本、选择项和勾选项')
        if kind=='checkbox':
            if type(value) is not bool:raise ValueError('勾选值必须为 true 或 false')
        elif not isinstance(value,str) or not value.strip() or len(value)>2000:raise ValueError('请填写字段测试数据')
        seen.add(label);result['fields'].append({'label':label.strip(),'kind':kind,'value':value})
    return result


def values(config):return [f['value'] for f in config.get('fields',[]) if isinstance(f['value'],str)]+[v for v in config.get('data',{}).values() if isinstance(v,str)]


def labels(nodes):return {n['label'].strip() for n in nodes if n['label']}


class Native:
    def __init__(self,e):self.e=e
    def nodes(self):return automation.parse_ui(self.e.source())
    def text(self):return '\n'.join(labels(self.nodes()))
    def resolve(self,label,kind):
        nodes=self.nodes();matches=[n for n in nodes if label in (n['label'].strip(),n['hint'].strip(),n['id'])]
        if kind=='text':
            fields=[n for n in matches if n['editable'] and not n['secure']]
            # Accessibility label on a wrapping control or its adjacent label.
            if not fields and len(matches)==1:
                anchor=matches[0];fields=[n for n in nodes if n['editable'] and not n['secure'] and n['path'].startswith(anchor['path']+'/')]
            matches=fields
        else:matches=[n for n in matches if n['clickable'] or 'CheckBox' in n['kind'] or 'Switch' in n['kind']]
        if len(matches)!=1:raise FormError('字段未唯一匹配：'+label+'；请填写实际占位文字或控件 ID')
        return matches[0]
    def preflight(self,c):
        if any(n['secure'] for n in self.nodes()):raise FormError('密码表单不使用通用填写流程')
        for f in c['fields']:self.resolve(f['label'],f['kind'])
        self.resolve(c['submit'],'select')
    def fill(self,f):
        n=self.resolve(f['label'],f['kind'])
        if f['kind']=='text':
            eid=self.e.find({'by':'xpath','value':n['path']})
            self.e.call('POST',self.e.base+'/element/'+eid+'/clear',{})
            self.e.call('POST',self.e.base+'/element/'+eid+'/value',{'text':f['value']})
            current=[v for v in self.nodes() if v['path']==n['path'] and v['editable'] and not v['secure']]
            if len(current)!=1:raise FormError('填写后输入框结构变化：'+f['label'])
            n=current[0]
            if f['value'] not in (n['label'],n.get('value','')):raise FormError('字段输入未通过回读验证：'+f['label'])
        elif f['kind']=='checkbox':
            if n['checked']!=f['value']:self.e.tap(n)
            if self.resolve(f['label'],'checkbox')['checked']!=f['value']:raise FormError('勾选状态未生效：'+f['label'])
        else:
            self.e.tap(n);time.sleep(.4);option=self.resolve(f['value'],'select');self.e.tap(option);time.sleep(.4)
            if f['value'] not in self.text():raise FormError('选择项未回显：'+f['label'])
    def prepare_submit(self,c):self.resolve(c['submit'],'select')
    def submit(self,c):self.e.tap(self.resolve(c['submit'],'select'))


# Run inside the App's own debuggable WebView, never an external browser.
FIND=r'''const [label,kind]=arguments;
const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
const norm=s=>String(s||'').trim();
const text=e=>norm(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder'));
const tags=kind==='button'?'button,input[type=submit],[role=button]':'input:not([type=hidden]),textarea,select,[role=combobox]';
const found=[...document.querySelectorAll(tags)].filter(visible).filter(e=>[text(e),e.id,e.name,norm(e.getAttribute('aria-label')),norm(e.getAttribute('placeholder')),...[...(e.labels||[])].map(l=>norm(l.innerText))].includes(label));
if(found.length!==1)throw Error('field not unique');
const e=found[0];if(e.type==='password')throw Error('secure field');
return e;'''


class Web:
    def __init__(self,w):self.w=w;self.e=w.e
    def text(self):return self.w.js("return [...document.querySelectorAll('body *')].filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&e.children.length===0).map(e=>e.innerText||'').join('\\n');")
    def resolve(self,label,kind):return self.w.js(FIND,[label,kind])
    def preflight(self,c):
        if self.w.js("return [...document.querySelectorAll('input[type=password]')].some(e=>e.getClientRects().length);"):raise FormError('密码表单不使用通用填写流程')
        for f in c['fields']:
            el=self.resolve(f['label'],f['kind'])
            if f['kind']=='select' and not self.w.js("const e=arguments[0];return e.tagName==='SELECT'&&[...e.options].filter(o=>o.text.trim()===arguments[1]&&!o.disabled).length===1;",[el,f['value']]):raise FormError('H5 选择项未唯一匹配：'+f['label'])
            if f['kind']=='text' and not self.w.js("return ['INPUT','TEXTAREA'].includes(arguments[0].tagName)&&!['file','checkbox','radio','submit','button','password'].includes(arguments[0].type);",[el]):raise FormError('字段不是文本输入框：'+f['label'])
            if f['kind']=='checkbox' and not self.w.js("return arguments[0].type==='checkbox';",[el]):raise FormError('字段不是勾选项：'+f['label'])
        self.resolve(c['submit'],'button')
    def fill(self,f):
        el=self.resolve(f['label'],f['kind']);eid=el.get(automation.ELEMENT) or el.get('ELEMENT')
        if f['kind']=='text':
            self.e.call('POST',self.e.base+'/element/'+eid+'/clear',{})
            self.e.call('POST',self.e.base+'/element/'+eid+'/value',{'text':f['value']})
            good=self.w.js('return arguments[0].value===arguments[1];',[self.resolve(f['label'],'text'),f['value']])
        elif f['kind']=='select':
            good=self.w.js("const [e,v]=arguments,o=[...e.options].find(o=>o.text.trim()===v&&!o.disabled);e.value=o.value;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return e.selectedOptions[0].text.trim()===v;",[el,f['value']])
        else:
            if self.w.js('return arguments[0].checked;',[el])!=f['value']:self.e.call('POST',self.e.base+'/element/'+eid+'/click',{})
            good=self.w.js('return arguments[0].checked===arguments[1];',[self.resolve(f['label'],'checkbox'),f['value']])
        if not good:raise FormError('字段状态未通过回读验证：'+f['label'])
    def prepare_submit(self,c):
        el=self.resolve(c['submit'],'button')
        if not self.w.js("const e=arguments[0],root=e.form||document;return !e.disabled&&[...root.querySelectorAll('input,textarea,select')].filter(n=>!n.disabled&&n.getClientRects().length).every(n=>(!n.checkValidity||n.checkValidity())&&(n.getAttribute('aria-required')!=='true'||String(n.value||'').trim()));",[el]):raise FormError('表单存在未满足的必填项、格式错误或提交按钮不可用')
    def submit(self,c):
        el=self.resolve(c['submit'],'button')
        eid=el.get(automation.ELEMENT) or el.get('ELEMENT');self.e.call('POST',self.e.base+'/element/'+eid+'/click',{})


def execute(e,c,web=False):
    """Return metadata only. Mark the attempt before entering; never retry submit."""
    result={'page':c['page'],'status':'blocked','submitted':False,'fields':[],'verification':'visible_success_marker'}
    def run(driver):
        if c['success'] in driver.text():raise FormError('提交前已存在成功标识，无法验证本次提交')
        driver.preflight(c)
        for f in c['fields']:
            if e.stopped():raise FormError('用户已停止')
            driver.fill(f);result['fields'].append({'label':f['label'],'kind':f['kind'],'verified':True})
        if e.stopped():raise FormError('用户已停止')
        driver.prepare_submit(c)
        # Mark before sending: a transport error may follow a successful server-side write.
        result['submitted']=True;result['status']='unconfirmed'
        driver.submit(c)
        deadline=time.monotonic()+15
        while True:
            if e.stopped():raise FormError('用户已停止，提交结果尚未确认')
            text=driver.text()
            if c['success'] in text:
                result.update(status='passed',reason='填写已回读验证，提交后出现指定成功标识');return
            if re.search(r'必填|不能为空|格式错误|提交失败|提交失敗|required|invalid|submission failed',text,re.I):
                result.update(status='failed',reason='提交后页面出现校验或失败提示');return
            if time.monotonic()>=deadline:raise FormError('提交后未出现指定成功标识；未自动重试，请复核是否已创建记录')
            time.sleep(.5)
    try:
        if web:
            from hybrid_webview import WebView
            with WebView(e) as w:run(Web(w))
        else:run(Native(e))
    except FormError as error:
        result['reason']=automation.redact(error,e.secrets)
    except Exception:
        # Driver exceptions may contain request bodies/field values. Never expose them.
        result['reason']='已尝试提交但结果未确认，请复核记录；本次不重试' if result['submitted'] else '填写或定位未完成，未提交；请检查页面识别、字段名称、选项及测试数据'
    return result
