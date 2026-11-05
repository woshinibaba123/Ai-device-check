import host_runtime
"""Scoped WebView operations through the app's Appium session."""
import re
import os
import shutil
import subprocess
from pathlib import Path
import automation

WEB_ACTIONS={'web_tap','web_assert','web_input','web_assert_input','web_back','web_save'}


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


class WebView:
    def __init__(self,explorer):self.e=explorer
    def __enter__(self):
        e=self.e
        contexts=e.call('GET',e.base+'/contexts')
        package=getattr(e,'app_package','') or getattr(e,'app_bundle','')
        choices=[c for c in contexts if c.startswith('WEBVIEW') and package and (c=='WEBVIEW_'+package or c.startswith('WEBVIEW_'+package+':'))]
        if len(choices)!=1:raise RuntimeError('未发现唯一的被测 App WebView，请先打开 H5 页面并启用调试')
        try:e.call('POST',e.base+'/context',{'name':choices[0]})
        except Exception:
            try:e.call('POST',e.base+'/context',{'name':'NATIVE_APP'})
            except Exception:pass
            raise
        return self
    def __exit__(self,*args):self.e.call('POST',self.e.base+'/context',{'name':'NATIVE_APP'})
    def js(self,script,args=None,*,read_only=False):
        try:return self.e.call('POST',self.e.base+'/execute/sync',{'script':script,'args':args or []})
        except RuntimeError as error:
            # Rebind a closed browser window only for a read-only discovery call.
            # Mutations are never replayed after an uncertain driver response.
            if not read_only or not re.search(r'no such window|web view not found|target window already closed',str(error),re.I):raise
            e=self.e
            handles=e.call('GET',e.base+'/window/handles')
            if not isinstance(handles,list) or len(handles)!=1:raise RuntimeError('H5 窗口已失效，未找到唯一的新窗口；未重复填写') from error
            e.call('POST',e.base+'/window',{'handle':handles[0]})
            return e.call('POST',e.base+'/execute/sync',{'script':script,'args':args or []})
    def snapshot(self):
        return self.js('''const visible=e=>!!(e.getClientRects().length)&&getComputedStyle(e).visibility!=='hidden';
if([...document.querySelectorAll('input[type=password]')].some(visible))throw Error('secure form');
const clean=(s,limit=160)=>String(s||'').replace(/\\b\\d{7,}\\b/g,'[hidden]').replace(/[^\\s]+@[^\\s]+/g,'[hidden]').slice(0,limit);
const controls=[...document.querySelectorAll('a,button,input,select,textarea,[role=button]')].filter(visible).slice(0,60).map(e=>({tag:e.tagName.toLowerCase(),text:clean(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')),id:e.id||'',type:e.getAttribute('type')||''}));
return {title:clean(document.title),path:location.pathname+location.hash.split('?')[0],text:clean(document.body.innerText,1200),controls};''')
    def perform(self,step):
        action=step['action']
        if action=='web_back':
            self.e.call('POST',self.e.base+'/back',{})
            return {'action':action}
        info=self.js('''const [by,value,clickable]=arguments;const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
const text=e=>(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').trim().replace(/\\s+/g,' ');
let found=[];
if(by==='css')found=[...document.querySelectorAll(value)];
else if(by==='xpath'){const r=document.evaluate(value,document,null,XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null);for(let i=0;i<r.snapshotLength;i++)found.push(r.snapshotItem(i));}
else found=[...document.querySelectorAll(clickable?'a,button,[role=button],label,li,input,select,textarea':'body *')].filter(e=>text(e)===value.trim().replace(/\\s+/g,' '));
found=found.filter(visible);if(!clickable)found=found.filter(e=>!found.some(c=>c!==e&&e.contains(c)));
if(found.length!==1)return {count:found.length};const e=found[0];return {count:1,element:e,secure:e.type==='password',label:text(e),editable:['INPUT','TEXTAREA'].includes(e.tagName),value:['INPUT','TEXTAREA'].includes(e.tagName)?e.value:null};''',[step.get('by','text'),step['value'],action in ('web_tap','web_input','web_save')])
        if info.get('count')!=1:raise AssertionError('H5 控件未唯一匹配：'+step['value']+'（'+str(info.get('count',0))+' 个）')
        if info.get('secure'):raise RuntimeError('H5 密码字段由专用登录流程处理')
        element=info['element'];eid=element.get(automation.ELEMENT) or element.get('ELEMENT')
        if action in ('web_tap','web_input'):
            label=(info.get('label','')+' '+step['value']).casefold()
            if any(word.casefold() in label for word in (automation.DEFAULT_SKIP+',save,保存,儲存,确认提交,confirm submission').split(',') if word):
                raise RuntimeError('该 H5 操作需专用提交或设备控制流程，未执行')
        if action=='web_save':
            import web_save
            return web_save.perform(self,step,eid)
        if action=='web_tap':self.e.call('POST',self.e.base+'/element/'+eid+'/click',{})
        elif action=='web_assert' and step.get('text') and step['text'] not in info.get('label',''):
            raise AssertionError('H5 页面未出现预期文字：'+step['text'])
        elif action=='web_input':
            if not info.get('editable'):raise RuntimeError('目标不是 H5 输入框')
            self.e.call('POST',self.e.base+'/element/'+eid+'/clear',{})
            self.e.call('POST',self.e.base+'/element/'+eid+'/value',{'text':step['text']})
        elif action=='web_assert_input':
            if info.get('value')!=step['text']:raise AssertionError('H5 输入内容与预期不一致')
        return {'action':action,'selector':step['value'],'matched':True}
