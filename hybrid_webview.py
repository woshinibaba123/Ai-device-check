import host_runtime
"""Scoped WebView operations through the app's Appium session."""
import re
import os
import shutil
import subprocess
from pathlib import Path
import automation

class H5InputMismatch(AssertionError):
    """Input was attempted, but its actual value did not match locally."""
    pass


class H5BackUnavailable(RuntimeError):
    pass

WEB_ACTIONS={'web_tap','web_assert','web_input','web_assert_input','web_back','web_save','web_observe'}


def driver_path(root,device=None):
    path=Path(root)/('.runtime/chromedriver/'+host_runtime.executable('chromedriver'))
    candidates=[path]+sorted((Path(root)/'.runtime/chromedriver').glob('*/'+host_runtime.executable('chromedriver')))
    if not any(p.is_file() for p in candidates):return None
    if device:
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',device):return None
        adb=shutil.which('adb') or str(host_runtime.sdk_root()/'platform-tools'/host_runtime.executable('adb'))
        try:
            actual=subprocess.run([adb,'-s',device,'shell','dumpsys','webviewupdate'],capture_output=True,text=True,timeout=15,check=True).stdout
            match=re.search(r'Current WebView package.*?,\s*(\d+)\.',actual)
            if not match:return None
            for candidate in candidates:
                if not candidate.is_file():continue
                version=subprocess.run([str(candidate),'--version'],capture_output=True,text=True,timeout=5,check=True).stdout
                installed=re.search(r'ChromeDriver (\d+)\.',version)
                if installed and match[1]==installed[1]:return str(candidate)
            return None
        except (OSError,subprocess.SubprocessError):return None
    return str(path)


def ensure_driver(root,device,log):
    """Install only the official driver matching this emulator's WebView build."""
    existing=driver_path(root,device)
    if existing:
        log('H5 驱动已匹配当前设备 WebView')
        return existing
    import json,urllib.request,zipfile,io,platform
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',device):raise ValueError('设备编号无效')
    adb=shutil.which('adb') or str(host_runtime.sdk_root()/'platform-tools'/host_runtime.executable('adb'))
    actual=subprocess.run([adb,'-s',device,'shell','dumpsys','webviewupdate'],capture_output=True,text=True,timeout=15,check=True).stdout
    match=re.search(r'Current WebView package.*?,\s*(\d+\.\d+\.\d+)\.',actual)
    if not match:raise RuntimeError('无法识别 WebView 版本，未下载驱动')
    build=match[1];target='win64' if os.name=='nt' else ('mac-arm64' if platform.machine()=='arm64' else 'mac-x64')
    log('正在匹配 H5 驱动：WebView '+build)
    if int(build.split('.')[0])<115:
        # Chrome <=114 uses the legacy official storage, not Chrome for Testing.
        with urllib.request.urlopen('https://chromedriver.storage.googleapis.com/LATEST_RELEASE_'+build,timeout=25) as response:
            version=response.read(128).decode().strip()
        if not re.fullmatch(re.escape(build)+r'\.\d+',version):raise RuntimeError('旧版驱动版本信息无效')
        archive_name='chromedriver_win32.zip' if os.name=='nt' else ('chromedriver_mac_arm64.zip' if platform.machine()=='arm64' else 'chromedriver_mac64.zip')
        url='https://chromedriver.storage.googleapis.com/'+version+'/'+archive_name
        member=host_runtime.executable('chromedriver')
    else:
        with urllib.request.urlopen('https://googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build-with-downloads.json',timeout=25) as response:
            info=json.load(response)['builds'].get(build)
        if not info:raise RuntimeError('官方没有对应 WebView 构建的驱动：'+build)
        url=next((x['url'] for x in info['downloads'].get('chromedriver',[]) if x['platform']==target),'')
        if not url.startswith('https://storage.googleapis.com/chrome-for-testing-public/'):raise RuntimeError('官方驱动下载地址不可用')
        version=info['version'];member='chromedriver-'+target+'/'+host_runtime.executable('chromedriver')
    with urllib.request.urlopen(url,timeout=45) as response:data=response.read(50*1024*1024+1)
    if len(data)>50*1024*1024:raise RuntimeError('驱动包超出大小限制')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:binary=archive.read(member)
    folder=Path(root)/'.runtime/chromedriver'/build;folder.mkdir(parents=True,exist_ok=True)
    temporary=folder/host_runtime.executable('chromedriver.download');temporary.write_bytes(binary);temporary.chmod(0o755)
    try:
        binary_version=subprocess.run([str(temporary),'--version'],capture_output=True,text=True,timeout=10,check=True).stdout
        if not binary_version.startswith('ChromeDriver '+version+' '):raise RuntimeError('驱动版本验证失败')
        path=folder/host_runtime.executable('chromedriver');temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    log('H5 驱动已就绪：'+version)
    return str(path)


# The known test-environment vConsole launcher can cover fixed business buttons.
# Only its own launcher is hidden; no business overlay or console data is touched.
DEBUG_OVERLAY_SETUP=r'''
let hiddenDebugSwitches=0;
const debugRoot=document.getElementById('__vconsole');
if(debugRoot)for(const e of debugRoot.querySelectorAll('.vc-switch')){
 if(e.style.visibility!=='hidden')hiddenDebugSwitches++;
 e.style.setProperty('visibility','hidden','important');
 e.style.setProperty('pointer-events','none','important');
}
let style=document.getElementById('devicecheck-hide-vconsole');
if(!style && typeof document.createElement==='function'){style=document.createElement('style');style.id='devicecheck-hide-vconsole';
style.textContent='#__vconsole, .vc-switch, .vc-mask {display:none !important;pointer-events:none !important}';
(document.head||document.documentElement).appendChild(style);}
'''


# Shared discovery for snapshots and text actions: include real Vue/DOM handlers,
# but exclude the embedded debug console from test targets.
DOM_TARGETS = r"""
const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('#__vconsole');
const text=e=>(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.getAttribute('title')||e.getAttribute('alt')||'').trim().replace(/\s+/g,' ');
const vueTargets=new Set(),seenVNodes=new Set();
const visitVNode=v=>{if(!v||seenVNodes.has(v))return;seenVNodes.add(v);if(v.elm&&v.data&&v.data.on&&Object.keys(v.data.on).some(k=>/click/i.test(k)))vueTargets.add(v.elm);for(const c of v.children||[])visitVNode(c);if(v.componentInstance)visitVNode(v.componentInstance._vnode);};
for(const e of document.querySelectorAll('body *'))if(e.__vue__)visitVNode(e.__vue__._vnode);
const actionable=e=>vueTargets.has(e)||e.matches('a,button,input,select,textarea,[role=button],label,li,[onclick],[tabindex]')||typeof e.onclick==='function'||!!(e._vei&&Object.keys(e._vei).some(k=>/click/i.test(k)))||!!(e.__vue__&&e.__vue__.$listeners&&e.__vue__.$listeners.click)||getComputedStyle(e).cursor==='pointer';
const dialogs=[...document.querySelectorAll('.van-dialog,[role=dialog],.van-popup')].filter(visible);
dialogs.sort((a,b)=>(Number(getComputedStyle(b).zIndex)||0)-(Number(getComputedStyle(a).zIndex)||0));
const activeDialog=dialogs[0];
const targets=()=>[...document.querySelectorAll('body *')].filter(e=>visible(e)&&actionable(e)&&(!activeDialog||activeDialog.contains(e)));
"""


class DOMTargetMissing(AssertionError):
    """No DOM target exists; no mutation was sent."""


class WebView:
    def __init__(self,explorer):self.e=explorer
    @__import__('runtime_metrics').timed('webview_connect')
    def __enter__(self):
        e=self.e
        active=getattr(e,'_active_webview_context',None)
        if isinstance(active,tuple) and active[0]==e.base:return self
        contexts=e.call('GET',e.base+'/contexts')
        if not isinstance(contexts,list):raise RuntimeError('WebView上下文列表不可用')
        package=getattr(e,'app_package','') or getattr(e,'app_bundle','')
        choices=[c for c in contexts if c.startswith('WEBVIEW') and package and (c=='WEBVIEW_'+package or c.startswith('WEBVIEW_'+package+':'))]
        if len(choices)!=1:raise RuntimeError('未发现唯一的被测 App WebView，请先打开 H5 页面并启用调试')
        try:e.call('POST',e.base+'/context',{'name':choices[0]})
        except Exception:
            try:e.call('POST',e.base+'/context',{'name':'NATIVE_APP'})
            except Exception:pass
            raise
        if isinstance(getattr(e,'capability_record',None),dict):e.capability_record['webview_dom']='context_connected'
        e._active_webview_context=(e.base,choices[0])
        return self
    def __exit__(self,*args):
        if getattr(self.e,'prefer_webview',False) is True and not args[0]:return
        try:self.e.call('POST',self.e.base+'/context',{'name':'NATIVE_APP'})
        finally:self.e._active_webview_context=None
    def js(self,script,args=None,*,read_only=False):
        try:
            result=self.e.call('POST',self.e.base+'/execute/sync',{'script':script,'args':args or []})
            if isinstance(getattr(self.e,'capability_record',None),dict):self.e.capability_record['webview_dom']='observed'
            return result
        except RuntimeError as error:
            # Rebind a closed browser window only for a read-only discovery call.
            # Mutations are never replayed after an uncertain driver response.
            if not read_only or not re.search(r'no such window|web view not found|target window already closed',str(error),re.I):raise
            e=self.e
            handles=e.call('GET',e.base+'/window/handles')
            if not isinstance(handles,list) or len(handles)!=1:raise RuntimeError('H5 窗口已失效，未找到唯一的新窗口；未重复填写') from error
            e.call('POST',e.base+'/window',{'handle':handles[0]})
            return e.call('POST',e.base+'/execute/sync',{'script':script,'args':args or []})
    def collect_diagnostics(self):
        monitor=getattr(self.e,'diagnostics_monitor',None)
        if monitor is None or monitor.busy or not monitor.enabled():return
        monitor.busy=True
        try:
            from pathlib import Path
            self.js((Path(__file__).parent/'h5_diagnostics.js').read_text())
            data=self.js("const s=window.__devicecheckDiagnosticsV1;return {route:location.origin+location.pathname+location.hash.split('?')[0],ready:!!s?.ready,sample:s?.sample?.(),events:s?.events||[]}",read_only=True)
            monitor.observe_h5(data)
        finally:
            monitor.busy=False

    @__import__('runtime_metrics').timed('h5_dom_observe')
    def snapshot(self):
        self.collect_diagnostics()
        return self.js(DEBUG_OVERLAY_SETUP+DOM_TARGETS+'''
if([...document.querySelectorAll('input[type=password]')].some(visible))throw Error('secure form');
const clean=(s,limit=160)=>String(s||'').replace(/\\b\\d{7,}\\b/g,'[hidden]').replace(/[^\\s]+@[^\\s]+/g,'[hidden]').slice(0,limit);
const targetsList=targets();
const cssPath=e=>{const parts=[];while(e&&e.nodeType===1){const tag=e.tagName.toLowerCase();const peers=e.parentElement?[...e.parentElement.children].filter(c=>c.tagName===e.tagName):[e];parts.unshift(tag+':nth-of-type('+(peers.indexOf(e)+1)+')');e=e.parentElement;}return parts.join(' > ');};
const iconLabel=e=>{if(e.matches('.van-nav-bar__left,.van-icon-arrow-left')||e.closest('.van-nav-bar__left')||e.querySelector('.van-icon-arrow-left'))return '';const img=e.matches('img,svg,i')?e:e.querySelector('img,svg,i');if(!img)return '';const r=e.getBoundingClientRect();return '无文字图标 '+(img.getAttribute('alt')||img.getAttribute('title')||((img.getAttribute('src')||'').startsWith('data:')?'内嵌图片':(img.getAttribute('src')||'').split('?')[0].split('/').pop())||String(img.className?.baseVal||img.className||img.tagName))+'，位置'+Math.round(r.left)+','+Math.round(r.top);};
const controls=targetsList.filter(e=>!targetsList.some(c=>c!==e&&e.contains(c)&&text(c)===text(e))).slice(0,100).map(e=>({filled:['INPUT','TEXTAREA'].includes(e.tagName)?!!String(e.value||'').trim():undefined,selected:e.getAttribute('aria-selected')==='true'||e.classList.contains('van-picker-column__item--selected')||e.classList.contains('van-picker-column__item--active'),field:clean((e.closest('.van-field,.van-cell')?.querySelector('.van-field__label,.van-cell__title')?.innerText||'').trim(),80),tag:e.tagName.toLowerCase(),text:clean(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.getAttribute('title')||e.getAttribute('alt')||iconLabel(e)),selector:cssPath(e.closest('button,[role=button],a')||e),id:e.id||'',type:e.getAttribute('type')||''}));
return {viewport_width:innerWidth,viewport_height:innerHeight,title:clean(document.title),path:location.pathname+location.hash.split('?')[0],visual_regions:[...document.querySelectorAll('canvas')].filter(visible).map(e=>({kind:'canvas',label:clean(e.getAttribute('aria-label')||e.title||'地图或自绘画布')})),text:clean([...document.body.children].filter(e=>e.id!=='__vconsole'&&!e.matches('script,style,noscript')).map(e=>e.innerText||'').join('\\n'),4000),controls};''',read_only=True)
    @__import__('runtime_metrics').timed('h5_operation')
    def perform(self,step):
        self.collect_diagnostics()
        action=step['action']
        if action=='web_observe':
            if getattr(self.e,'excel_observation_mode',False) is not True:raise RuntimeError('页面观察仅用于Excel观察记录模式')
            data=self.js("""const [by,value]=arguments;
const visible=e=>{if(!e||typeof e.getBoundingClientRect!=='function'||e.closest?.('#__vconsole'))return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};
const out={messages:[...document.querySelectorAll('[role=alert],.van-toast,.van-field__error-message,.van-empty__description,.el-form-item__error,[class*=empty]')].filter(visible).filter(e=>!e.querySelector('input,textarea')).map(e=>(e.innerText||'').trim().slice(0,160)).filter(Boolean).slice(0,12)};
if(!by)return out;
let nodes=[];
try {
 if(by==='css')nodes=[...document.querySelectorAll(value)];
 else if(by==='xpath'){const result=document.evaluate(value,document,null,XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null);for(let i=0;i<result.snapshotLength;i++)nodes.push(result.snapshotItem(i));}
 else if(by==='text')nodes=[...document.querySelectorAll('body *')].filter(e=>(e.innerText||'').trim()===value);
 else return {...out,selector_error:'unsupported_locator'};
}catch(_){return {...out,selector_error:'invalid_selector'};}
nodes=[...new Set(nodes)];const shown=nodes.filter(visible);
return {...out,total_dom_count:nodes.length,match_count:shown.length,has_data:shown.length>0,
 texts:shown.slice(0,50).filter(e=>!e.matches?.('input,textarea')&&!e.querySelector('input[type=password]')).map(e=>(e.innerText||e.textContent||'').trim().slice(0,500)),truncated:shown.length>50};""",[step.get('by'),step.get('value','')],read_only=True)
            data=data or {}
            result={'action':action,'status':'unavailable' if data.get('selector_error') else 'observed',
                    'messages':[automation.redact(m,self.e.secrets) for m in data.get('messages',[])],
                    'note':automation.redact(step.get('text') or (step.get('value','') if not step.get('by') else ''),self.e.secrets)}
            if step.get('by'):
                result.update(by=step['by'],selector=step.get('value'),measurement='rendered_dom_matches_not_backend_total')
                if data.get('selector_error'):result.update(selector_error=data['selector_error'],match_count=None,has_data=None)
                else:result.update({k:data.get(k) for k in ('total_dom_count','match_count','has_data','truncated')},texts=[automation.redact(t,self.e.secrets) for t in data.get('texts',[])])
            return result
        if action=='web_scroll':
            return self.js("""const nodes=[document.scrollingElement,...document.querySelectorAll('body *')].filter(e=>e&&e.getClientRects().length&&!e.closest('#__vconsole')&&e.scrollHeight>e.clientHeight+4&&(e===document.scrollingElement||/auto|scroll/.test(getComputedStyle(e).overflowY)));nodes.sort((a,b)=>b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight);const e=nodes[0];if(!e)return {scrolled:false};const before=e.scrollTop;e.scrollTop=Math.min(e.scrollHeight-e.clientHeight,before+e.clientHeight*.65);return {scrolled:e.scrollTop!==before,before,after:e.scrollTop};""")
        if action=='web_back':
            result=self.js("""const all=[...document.querySelectorAll('.van-nav-bar__left,i.van-icon-arrow-left,[aria-label="返回"],[aria-label="Back"]')];
const visible=all.filter(e=>{if(e.closest('#__vconsole'))return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);if(r.width<=0||r.height<=0||s.visibility==='hidden'||s.display==='none'||Number(s.opacity)===0)return false;const x=r.left+r.width/2,y=r.top+r.height/2;if(x<0||y<0||x>=innerWidth||y>=innerHeight)return false;const hit=document.elementFromPoint(x,y);return hit&&(hit===e||e.contains(hit));});
const popups=[...new Set([...document.querySelectorAll('.van-calendar')].map(e=>e.closest('.van-popup')||e))].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).display!=='none';});
if(popups.length){const close=[...new Set(popups.flatMap(p=>[...p.querySelectorAll('.van-popup__close-icon')]))].filter(e=>{const r=e.getBoundingClientRect();const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return r.width>0&&r.height>0&&hit&&(hit===e||e.contains(hit));});if(close.length===1){close[0].click();return 'calendar_close';}return {blocked:true,count:close.length,candidates:[]};}
const headers=visible.filter(e=>e.matches('.van-nav-bar__left'));const candidates=headers.length?headers:visible;
const groups=[];for(const e of candidates){const r=e.getBoundingClientRect();if(!groups.some(g=>g.e.contains(e)||e.contains(g.e)||(Math.abs(g.x-r.left-r.width/2)<4&&Math.abs(g.y-r.top-r.height/2)<4)))groups.push({e,x:r.left+r.width/2,y:r.top+r.height/2});}
if(groups.length!==1)return {blocked:true,count:groups.length,candidates:groups.map(g=>({tag:g.e.tagName,cls:g.e.className,x:Math.round(g.x),y:Math.round(g.y)}))};
groups[0].e.click();return 'header';""")
            if isinstance(result,dict) and result.get('blocked'):
                raise H5BackUnavailable('H5 返回未执行：可交互候选数='+str(result.get('count'))+'，候选='+__import__('json').dumps(result.get('candidates',[]),ensure_ascii=False))
            return {'action':action,'strategy':result}
        info=self.js(DEBUG_OVERLAY_SETUP+DOM_TARGETS+'''const [by,value,clickable,firstMatch]=arguments;
let found=[];
if(by==='css')found=[...document.querySelectorAll(value)];
else if(by==='xpath'){const r=document.evaluate(value,document,null,XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null);for(let i=0;i<r.snapshotLength;i++)found.push(r.snapshotItem(i));}
else found=(clickable?targets():[...document.querySelectorAll('body *')]).filter(e=>text(e)===value.trim().replace(/\\s+/g,' '));
found=found.filter(visible);found=found.filter(e=>!found.some(c=>c!==e&&e.contains(c)));
if(!found.length||found.length!==1&&!firstMatch)return {count:found.length};const e=found[0];return {count:found.length,element:e,debug_switch_hidden:hiddenDebugSwitches>0,secure:e.type==='password',label:text(e),editable:['INPUT','TEXTAREA'].includes(e.tagName),maxlength:e.maxLength,value:['INPUT','TEXTAREA'].includes(e.tagName)?e.value:null};''',[step.get('by','text'),step['value'],action in ('web_tap','web_input','web_save'),getattr(self.e,'excel_observation_mode',False) is True])
        observing=getattr(self.e,'excel_observation_mode',False) is True
        if info.get('secure'):raise RuntimeError('H5 密码字段由专用登录流程处理')
        if observing and action in ('web_assert','web_assert_input'):
            return {'action':action,'selector':step['value'],'present':bool(info.get('count')),'match_count':info.get('count',0),'actual_text':info.get('label',''),'actual_value':info.get('value'),'expected_text':step.get('text'),'selection_policy':'first_match'}
        if info.get('count')==0:raise DOMTargetMissing('H5 DOM 未找到目标：'+step['value'])
        if info.get('count')!=1 and not observing:raise AssertionError('H5 控件未唯一匹配：'+step['value']+'（'+str(info.get('count',0))+' 个）')
        if info.get('secure'):raise RuntimeError('H5 密码字段由专用登录流程处理')
        element=info['element'];eid=element.get(automation.ELEMENT) or element.get('ELEMENT')
        if action in ('web_tap','web_input'):
            label=(info.get('label','')+' '+step['value']).casefold()
            import ai_operator
            authorized_save = action == 'web_tap' and ai_operator.save_allowed(self.e, info.get('label', '')) and (step.get('by')=='css' or ai_operator.save_allowed(self.e, step['value']))
            if not authorized_save and any(word.casefold() in label for word in (automation.DEFAULT_SKIP+',save,保存,儲存,确认提交,confirm submission').split(',') if word):
                raise RuntimeError('该 H5 操作需专用提交或设备控制流程，未执行')
        if action=='web_save':
            import web_save
            return __import__('save_outcomes').nonblocking(web_save.perform)(self,step,eid)
        if action=='web_tap':
            try:
                self.e.call('POST',self.e.base+'/element/'+eid+'/click',{})
            except RuntimeError as error:
                if 'element not interactable' not in str(error).lower():
                    raise
                # The driver explicitly rejected interaction; no click was sent.
                # Bring this exact, previously resolved element into view once.
                self.js("arguments[0].scrollIntoView({block:'center',inline:'nearest'});",[element])
                self.e.call('POST',self.e.base+'/element/'+eid+'/click',{})
        elif action=='web_assert' and step.get('text') and step['text'] not in info.get('label',''):
            raise AssertionError('H5 页面未出现预期文字：'+step['text'])
        elif action=='web_input':
            if not info.get('editable'):raise RuntimeError('目标不是 H5 输入框')
            if info.get('value') == step['text']:
                return {'action':action,'selector':step['value'],'matched':True,'input_unchanged':True}
            self.e.call('POST',self.e.base+'/element/'+eid+'/clear',{})
            # Notify controlled H5 inputs of the empty value before typing.
            self.js('''const e=arguments[0];const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
const setter=Object.getOwnPropertyDescriptor(proto,'value').set;
setter.call(e,'');e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));''',[element])
            self.e.call('POST',self.e.base+'/element/'+eid+'/value',{'text':step['text']})
        elif action=='web_assert_input':
            if info.get('value')!=step['text']:
                limit=info.get('maxlength')
                expected=step['text'].encode('utf-16-le',errors='surrogatepass')
                if (step.get('allow_maxlength_truncation') is True and type(limit) is int and limit>0
                        and len(expected)>limit*2
                        and info.get('value')==expected[:limit*2].decode('utf-16-le',errors='surrogatepass')):
                    return {'action':action,'matched':True,'input_truncated':True,'maxlength':limit}
                raise H5InputMismatch('H5 输入内容与预期不一致')
        return {'action':action,'selector':step['value'],'matched':True}
