"""Collect a current App page as evidence; do not explore or submit data."""
import re
import automation
import hybrid_webview


def collect(call,cfg,root):
    device=cfg.get('device','');bundle=cfg.get('bundle','')
    if not isinstance(device,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',device):raise ValueError('请在本机设备模式选择一台已启动的 Android 设备')
    if not isinstance(bundle,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]{2,180}',bundle):raise ValueError('请填写要采集的 App 包名，例如 com.example.app')
    caps={'platformName':'Android','appium:automationName':'UiAutomator2','appium:udid':device,
          'appium:appPackage':bundle,'appium:autoLaunch':False,'appium:noReset':True,'appium:newCommandTimeout':90,'appium:uiautomator2ServerLaunchTimeout':120000,'appium:adbExecTimeout':60000,
          'appium:settings':{'waitForIdleTimeout':0}}
    driver=hybrid_webview.driver_path(root,device)
    if driver:caps['appium:chromedriverExecutable']=driver
    sid=call('POST','/session',{'capabilities':{'alwaysMatch':caps,'firstMatch':[{}]}})['sessionId']
    try:
        e=automation.Explorer(call,sid,'Android',lambda _:None,lambda *a:None);e.app_package=bundle
        nodes=automation.parse_ui(e.source())
        if not any(n['package']==bundle for n in nodes):raise ValueError('当前前台不是指定 App，请先在设备上打开待测页面')
        def clean(s):return re.sub(r'\S+@\S+|\b\d{7,}\b','[hidden]',s)[:180]
        controls=[{'label':clean(n['label']) if not n['editable'] else '', 'id':n['id'], 'xpath':n['path'],
                   'clickable':n['clickable'],'editable':n['editable'],'secure':n['secure'],'selected':n['selected']}
                  for n in nodes if n['label'] or n['id'] or n['editable']][:100]
        result={'platform':'Android','device':device,'bundle':bundle,'native_controls':controls,
                'note':'仅此刻页面的运行证据，不代表其他页面已读取或测试通过'}
        if any(n['secure'] for n in nodes):
            result['web_note']='当前为密码页面，未采集 H5 或输入内容'
        else:
            contexts=call('GET',e.base+'/contexts')
            if any(c.startswith('WEBVIEW') and bundle in c for c in contexts):
                try:
                    with hybrid_webview.WebView(e) as web:result['web']=web.snapshot()
                except Exception:result['web_note']='WebView 无法读取，请检查调试开关和匹配的 ChromeDriver'
        return result
    finally:call('DELETE','/session/'+sid)
