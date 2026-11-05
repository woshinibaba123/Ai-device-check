#!/usr/bin/env python3
import host_runtime
import json, os, re, shutil, subprocess, threading, time, uuid, urllib.request, urllib.error, urllib.parse
import cancellation
import runtime_health
import importlib
import popup_handler
import source_navigation
import build_config
import login_probe
import login_flow
import ios_models
import matrix
import automation
import language_tests
import excel_ai
import language_pipeline
import case_workbook
import case_runner
import flow_planner
import form_runner
import http_probe
import codebuddy_bridge
import hybrid_webview
import manual_steps
import semantic_steps
import language_workflow
import login_credential_store
import runtime_inventory
import hashlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = host_runtime.root()
JOBS = {}
LOCK = threading.Lock()
CONTEXT = threading.local()
BATCH_RUNNING = threading.Event()


class PipelineAPI:
    def __init__(self,port):self.url='http://127.0.0.1:'+str(port)
    def call(self,path,body=None):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        try:
            with opener.open(req,timeout=180) as response:return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code==409:raise language_pipeline.QueueBusy() from None
            raise ValueError(json.load(error).get('error','语言任务提交失败')) from None
    def post(self,path,body):return self.call(path,body)
    def get(self,path):return self.call(path)


def pipeline_source_signature(project):
    project=Path(project);digest=hashlib.sha256()
    files=list((project/'lib').rglob('*.dart'))+list((project/'assets/i18n').glob('*.json'))
    files += [project/name for name in ('pubspec.yaml','pubspec.lock','android/app/src/main/AndroidManifest.xml','android/app/build.gradle','android/app/build.gradle.kts') if (project/name).is_file()]
    for file in sorted(files):
        digest.update(str(file.relative_to(project)).encode());digest.update(file.read_bytes())
    return digest.hexdigest()


def cache_pipeline_build(cfg,artifact,probe_name):
    identifier=cfg.get('pipeline_id','')
    if cfg.get('platform')!='Android' or not re.fullmatch(r'[a-f0-9]{32}',identifier):return str(artifact)
    folder=ROOT/'.runtime/pipeline-builds'/identifier;folder.mkdir(parents=True,exist_ok=True)
    target=folder/'app-debug.apk';shutil.copyfile(artifact,target)
    metadata={k:cfg.get(k) for k in ('source','entrypoint','source_plan','route_tracking','http_manifest','flow_index')}
    metadata['source_fingerprint']=cfg.get('_pipeline_source_fingerprint');metadata['login_probe']=probe_name
    if metadata.get('flow_index'):metadata['flow_index']=dict(metadata['flow_index'],project=cfg['source'])
    (folder/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False))
    return str(target)


def apply_pipeline_build(cfg):
    identifier=cfg.get('pipeline_id','')
    if not re.fullmatch(r'[a-f0-9]{32}',identifier) or not cfg.get('source') or language_workflow.applies(cfg.get('case_book',{})):return False
    if cfg.get('platform')=='iOS' or any(t.get('ios_model') or t.get('platform')=='iOS' for t in cfg.get('targets',[])):return False
    folder=ROOT/'.runtime/pipeline-builds'/identifier;file=folder/'metadata.json';artifact=folder/'app-debug.apk'
    if not file.is_file() or not artifact.is_file():return False
    try:metadata=json.loads(file.read_text())
    except (OSError,ValueError):return False
    if not isinstance(metadata,dict):return False
    if metadata.get('source')!=cfg['source'] or metadata.get('entrypoint')!=cfg.get('entrypoint'):return False
    if metadata.get('source_fingerprint')!=pipeline_source_signature(cfg['source']):return False
    required={field for c in case_runner.selected_cases(cfg.get('case_book',{}),cfg.get('cases',{})) if c.get('plan_text') for s in json.loads(c['plan_text']).get('steps',[]) if s['action'] in ('save','dispatch') for field in s['api'].get('equals',{})}
    dispatch=any(s['action']=='dispatch' for c in case_runner.selected_cases(cfg.get('case_book',{}),cfg.get('cases',{})) if c.get('plan_text') for s in json.loads(c['plan_text']).get('steps',[]))
    if dispatch and (metadata.get('http_manifest') or {}).get('request_shape_version')!='call_task_fields_v1':return False
    if required-set((metadata.get('http_manifest') or {}).get('response_fields',[])):return False
    cfg.update(source='',app=str(artifact),login_probe=metadata.get('login_probe'),source_plan=metadata.get('source_plan'),route_tracking=metadata.get('route_tracking'),http_manifest=metadata.get('http_manifest'),flow_index=metadata.get('flow_index'),pipeline_build_reused=True)
    return True
# 任务日志只保留主要事件；逐次点击等过程噪音在日志出口统一过滤。
NOISE_LOG_PATTERN = re.compile(r'^(点击方式|隐私确认原生点击坐标|等待中页面|先让账号框失焦|收起键盘|当前登录页|准备输入密码框|已到达登录页|已确认测试账号填入|点击账号密码登录|点击登录按钮|勾选登录协议|关闭引导弹层)')

def local_emulator_proxy():
    """Reuse the Mac's local HTTP proxy for tool-owned emulator TCP traffic."""
    from urllib.parse import urlsplit
    proxies=urllib.request.getproxies()
    for key in ('https','http'):
        value=proxies.get(key,'')
        try:
            parsed=urlsplit(value)
            if parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost') and parsed.port and not parsed.username and not parsed.password:
                return value
        except ValueError:continue
    return ''

def command(args):
    try:
        p = getattr(CONTEXT, 'control', cancellation.Control()).run(args, capture_output=True, text=True, timeout=25)
        return {'ok': p.returncode == 0, 'output': (p.stdout + p.stderr).strip()}
    except cancellation.Cancelled: raise
    except Exception as e:
        return {'ok': False, 'output': str(e)}

def android_tools():
    sdk = host_runtime.sdk_root()
    return (shutil.which('adb') or str(sdk / ('platform-tools/'+host_runtime.executable('adb'))), shutil.which('emulator') or str(sdk / ('emulator/'+host_runtime.executable('emulator'))))

def devices():
    adb, emulator = android_tools()
    android = command([adb, 'devices', '-l'])
    ios = command(['xcrun', 'simctl', 'list', 'devices', '--json'])
    hdc = shutil.which('hdc')
    found = []
    if android['ok']:
        for line in android['output'].splitlines()[1:]:
            fields = line.split()
            if len(fields) > 1 and fields[1] == 'device':
                found.append({'platform': 'Android', 'id': fields[0], 'name': line})
    avds = command([emulator, '-list-avds'])
    running_avds = set()
    for d in found:
        if d['id'].startswith('emulator-'):
            name = command([adb, '-s', d['id'], 'emu', 'avd', 'name'])
            if name['ok']: running_avds.add(name['output'].splitlines()[0])
    if avds['ok']:
        for name in avds['output'].splitlines():
            if name.strip() and name.strip() not in running_avds:
                found.append({'platform': 'Android', 'id': 'avd:' + name.strip(), 'name': name.strip() + ' · 未启动（测试时自动启动）'})
    android['output'] = ('已连接设备：\n' + android['output'] + '\n本机模拟器：\n' + avds['output'])
    if not avds['ok']: android['output'] += '\n请安装 Android Studio 并创建模拟器。'
    elif not avds['output'].strip(): android['output'] += '\n尚未创建 Android 模拟器，请在 Android Studio 的 Device Manager 创建。'
    if ios['ok']:
        try:
            for runtime, entries in json.loads(ios['output'])['devices'].items():
                for d in entries:
                    if d.get('isAvailable'):
                        found.append({'platform': 'iOS', 'id': d['udid'], 'device_type':d.get('deviceTypeIdentifier',''), 'name': d['name'] + ' · ' + runtime.split('.')[-1] + ' · ' + d['state']})
        except (ValueError, KeyError): pass
    harmony = command([hdc, 'list', 'targets']) if hdc else {'ok': False, 'output': '未找到 hdc；请安装 DevEco Studio 并配置 PATH。鸿蒙自动操作尚未接入。'}
    types_result=command(['xcrun','simctl','list','devicetypes','--json'])
    try: types=json.loads(types_result['output']).get('devicetypes',[]) if types_result['ok'] else []
    except (ValueError,TypeError): types=[]
    references=ios_models.references(types,found)
    return {'reference_profiles':references, 'devices': found, 'diagnostics': {'Android': android, 'iOS': ios, 'HarmonyOS': harmony}, 'adb': adb}

def raw_request(method, path, data=None, timeout=None):
    req = urllib.request.Request(host_runtime.appium_url() + path, data=json.dumps(data).encode() if data is not None else None, headers={'Content-Type': 'application/json'}, method=method)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout or (300 if method == 'POST' and path == '/session' else 90)) as r: value = json.load(r).get('value')
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode()[:3000]) from e
    if isinstance(value, dict) and value.get('error'): raise RuntimeError(value.get('message', str(value)))
    return value

def request(method, path, data=None):
    control = getattr(CONTEXT, 'control', cancellation.Control())
    def late_session(value):
        if method == 'POST' and path == '/session' and isinstance(value, dict) and value.get('sessionId'):
            try: raw_request('DELETE', '/session/'+value['sessionId'], timeout=10)
            except Exception: pass
    return control.call(lambda: raw_request(method, path, data), late_session)


def run_job(jid, cfg):
    if cfg.get('live_updates'):
        importlib.reload(popup_handler);importlib.reload(login_flow);importlib.reload(automation)
    import base64
    job = JOBS[jid]
    job['screenshot_policy']='raw_screenshots_v1'
    control = cancellation.Control(lambda: job.get('stop_requested', False))
    CONTEXT.control = control
    folder = ROOT / 'reports' / jid
    folder.mkdir(parents=True)
    if cfg.get('test_mode')=='cases':
        import hashlib
        job['case_source']={'path':cfg['case_book']['path'],'sha256':hashlib.sha256(cfg['case_book']['content']).hexdigest(),'sheet':cfg.get('cases',{}).get('sheet',''),'priority':cfg.get('cases',{}).get('priority','')}
    sid = None
    login_cfg = cfg.get('login', {})
    secrets = [login_cfg.get('account',''), login_cfg.get('password','')]+form_runner.values(cfg.get('explore',{}).get('form',{}))
    capture_allowed = not login_cfg.get('enabled',False)
    staged_project = None
    probe_name = cfg.get('login_probe')
    owned_avd = None
    owned_process = None
    device = cfg.get("device", "")
    noise_pattern = NOISE_LOG_PATTERN
    last_progress=[time.monotonic()]
    def log(message):
        last_progress[0]=time.monotonic()
        text = automation.redact(message,secrets)
        # 只保留主要日志：阶段、页面跳转、断言、弹窗与异常；过滤逐次点击等过程噪音。
        if noise_pattern.match(text.strip()):return
        with LOCK: job['logs'].append(text)
    explorer=None
    captured_pages = set()
    route_reader = None
    def shot(index, source=None):
        if not capture_allowed or getattr(explorer,'auth_case_active',False):return
        source = source or request('GET', f'/session/{sid}/source')
        nodes = automation.parse_ui(source)
        if any(n['secure'] for n in nodes) or popup_handler.has_popup(nodes):return
        route = route_reader.read() if route_reader else ''
        if route and re.match(r'^/(?:login|staffLogin)(?:/|$)',route):return
        selected = tuple(n['label'] for n in nodes if n.get('selected'))
        page_key = (route, selected, automation.signature(nodes),index if cfg.get('test_mode')=='cases' else '')
        if page_key in captured_pages:return
        data = base64.b64decode(request('GET', f'/session/{sid}/screenshot'))
        stem = (f'{index:03d}' if isinstance(index,int) else str(index))
        try:
            # 压缩报告截图：整页截图缩到 1080 宽、JPEG 保存，明显缩小报告体积。
            from PIL import Image
            import io as _io
            image=Image.open(_io.BytesIO(data))
            if image.width>1080:
                image=image.resize((1080,max(1,round(image.height*1080/image.width))))
            name=stem+'.jpg'
            image.convert('RGB').save(folder/name,format='JPEG',quality=72,optimize=True)
        except Exception:
            name=stem+'.png'
            (folder/name).write_bytes(data)
        captured_pages.add(page_key)
        with LOCK: job['screenshots'].append('/reports/' + jid + '/' + name)
    try:
        control.check()
        if cfg.get('pipeline_build_reused'):
            log('复用本轮已验证源码版本的测试包，跳过重复编译。')
            job['build_entrypoint']=cfg.get('entrypoint')
        if cfg.get('test_mode')=='cases':
            if not cfg.get('flow_index') and cfg.get('source','').strip():cfg['flow_index']=flow_planner.source_index(cfg['source'])
            document=flow_planner.build({'cases':case_runner.selected_cases(cfg['case_book'],cfg.get('cases',{}))},cfg.get('flow_index'))
            (folder/'case-flows.json').write_text(json.dumps(document,ensure_ascii=False,indent=2))
            (folder/'case-flows.md').write_text(flow_planner.markdown(document))
            job['case_flows']='/reports/'+jid+'/case-flows.json'
            if cfg['case_book'].get('ai'):
                (folder/'ai-plan.json').write_bytes(cfg['case_book']['content'])
                job['ai_plan']='/reports/'+jid+'/ai-plan.json'
            elif cfg['case_book'].get('excel_ai_document'):
                (folder/'excel-ai-plan.json').write_text(json.dumps(cfg['case_book']['excel_ai_document'],ensure_ascii=False,indent=2))
                job['ai_plan']='/reports/'+jid+'/excel-ai-plan.json'
        if cfg.get('ios_reference'):
            job['ios_reference']=cfg['ios_reference']
            log(cfg['ios_reference']['coverage'])
        platform = cfg['platform']
        device = cfg.get('device', '')
        profile = None
        if cfg.get('profile'):
            profile = matrix.resolve_profile(cfg['profile'])
            job['profile'] = profile
            log(profile['coverage'])
            owned_avd = matrix.prepare(profile, folder, log, runner=control.run)
            device = 'avd:' + owned_avd[0]
        if platform=='iOS' and os.name=='nt':raise ValueError('Windows 桌面端仅支持 Android；iOS 自动化需要 Mac 和 Xcode。')
        if platform not in ('Android', 'iOS'): raise ValueError('当前版本只执行 Android / iOS；鸿蒙仅提供环境诊断。')
        steps = cfg.get('steps', [])
        if not isinstance(steps, list) or len(steps) > 200: raise ValueError('步骤必须是数组，最多 200 步。')
        app = cfg.get('app', '').strip()
        project_text = cfg.get('source', '').strip()
        if project_text:
            project = Path(project_text).expanduser().resolve()
            if cfg.get('pipeline_id'):cfg['_pipeline_source_fingerprint']=pipeline_source_signature(project)
            target_entry=build_config.entrypoint(project,cfg.get('entrypoint','lib/main.dart'))
            job['build_entrypoint']=target_entry
            if not (project / 'pubspec.yaml').is_file(): raise ValueError('源码目录内未找到 pubspec.yaml，请选择 Flutter 项目根目录。')
            flutter = shutil.which(host_runtime.batch_name('flutter'))
            for candidate in (project / '.fvm/flutter_sdk/bin/flutter', Path.home() / 'fvm/default/bin/flutter'):
                if candidate.is_file():
                    flutter = str(candidate)
                    break
            if not flutter: raise ValueError('未找到 Flutter SDK，请先安装 Flutter 并配置 PATH。')
            if cfg.get('test_mode') in ('explore','cases'):
                cfg['source_plan']=source_navigation.analyze(project)
                job['source_navigation']=cfg['source_plan']
                log('源码分析：识别 '+str(len(cfg['source_plan']['routes']))+' 个路由，'+str(len(cfg['source_plan']['entries']))+' 个跳转入口候选。')
            if (login_cfg.get('enabled') and login_cfg.get('flow')=='keenon_china') or cfg.get('test_mode') in ('explore','cases'):
                if login_cfg.get('enabled') and login_cfg.get('flow')=='keenon_china':login_probe.validate(project)
                staged_project=ROOT/'.runtime'/('login-source-'+jid)
                staged_project.parent.mkdir(parents=True,exist_ok=True)
                log('创建独立源码副本，添加登录结果或页面路由观察器。')
                host_runtime.copy_source(project,staged_project,control.run)
                project=staged_project
                if login_cfg.get('enabled') and login_cfg.get('flow')=='keenon_china':probe_name=login_probe.instrument(project)
                if cfg.get('test_mode') in ('explore','cases'):
                    source_navigation.instrument(project)
                    cfg['route_tracking']=True
                if cfg.get('test_mode')=='cases' and (cfg.get('pipeline_id') or language_workflow.applies(cfg['case_book'])):language_workflow.instrument(project)
                if cfg.get('test_mode')=='cases':
                    cfg['flow_index']=flow_planner.source_index(project)
                    plans=case_runner.preview(cfg['case_book'],cfg.get('cases',{}),cfg.get('flow_index'))['cases']
                    fields=sorted({key for case in plans if case['plan'] for step in case['plan']['steps'] if step['action'] in ('save','dispatch') for key in step['api'].get('equals',{})})
                    cfg['http_manifest']=http_probe.instrument(project,cfg['flow_index'],fields)
                    log('已为测试副本添加 Dio 接口观察器；不记录请求参数、Header 或凭据。')
            args = ([flutter, 'build', 'apk'] if platform == 'Android' else [flutter, 'build', 'ios', '--simulator']) + ['-t',target_entry,'--debug']
            log('正在编译 Flutter 源码，启动入口：'+target_entry+'（debug 测试包）…')
            with (folder / 'build.log').open('w') as build_log:
                try:
                    result = control.run(args, cwd=str(project), stdout=build_log, stderr=subprocess.STDOUT, timeout=1800)
                except subprocess.TimeoutExpired: raise RuntimeError('编译超过 30 分钟，已停止。请查看 build.log。')
            if result.returncode:
                tail = (folder / 'build.log').read_text(errors='replace')[-5000:]
                raise RuntimeError('Flutter 编译失败：\n' + tail)
            if platform == 'Android':
                artifact = project / 'build/app/outputs/flutter-apk/app-debug.apk'
            else:
                outputs = list((project / 'build/ios/iphonesimulator').glob('*.app'))
                if len(outputs) != 1: raise RuntimeError('未找到唯一的 iOS 模拟器 .app，请改用安装包路径。')
                artifact = outputs[0]
            if not artifact.exists(): raise RuntimeError('未找到编译产物，请查看 build.log。')
            app = str(artifact)
            log('编译完成：' + app)
            if cfg.get('pipeline_id'):
                app=cache_pipeline_build(cfg,artifact,probe_name)
                if app!=str(artifact):log('已缓存本轮测试包；后续语言在源码及接口断言一致时直接复用。')
        if platform == 'Android' and device.startswith('avd:'):
            adb, emulator = android_tools()
            avd = device[4:]
            available = command([emulator, '-list-avds'])
            if not available['ok'] or avd not in available['output'].splitlines(): raise ValueError('Android 模拟器不存在，请刷新设备。')
            log('正在启动 Android 模拟器：' + avd)
            control.check()
            proxy=local_emulator_proxy() if owned_avd else ''
            if proxy:log('Android 模拟器沿用 Mac 本机 HTTP 代理，转发网络连接。')
            gpu_mode=cfg.get('emulator_gpu','swiftshader')
            if gpu_mode not in ('swiftshader','host'):raise ValueError('不支持的模拟器 GPU 模式')
            if owned_avd:log('Android 模拟器渲染模式：'+gpu_mode)
            with (folder / 'emulator.log').open('w') as emulator_log:
                process = subprocess.Popen([emulator, '-avd', avd, '-no-snapshot'] + (['-gpu',gpu_mode,'-feature','-Vulkan'] if owned_avd else []) + (['-http-proxy',proxy] if proxy else []), stdout=emulator_log, stderr=subprocess.STDOUT, start_new_session=True)
                owned_process = process
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                control.check()
                listing = command([adb, 'devices'])
                for line in listing['output'].splitlines()[1:]:
                    fields = line.split()
                    if len(fields) != 2 or fields[1] != 'device' or not fields[0].startswith('emulator-'): continue
                    name = command([adb, '-s', fields[0], 'emu', 'avd', 'name'])
                    boot = command([adb, '-s', fields[0], 'shell', 'getprop', 'sys.boot_completed'])
                    if name['ok'] and name['output'].splitlines()[0] == avd and boot['output'].strip() == '1':
                        device = fields[0]
                        break
                if not device.startswith('avd:'): break
                control.sleep(2)
            if device.startswith('avd:'): raise RuntimeError('Android 模拟器启动超时，请查看 emulator.log 或在 Android Studio 手动启动。')
            log('Android 模拟器已就绪。')
        if app and not (Path(app).is_file() or (platform == 'iOS' and Path(app).is_dir() and Path(app).suffix == '.app')): raise ValueError('App 路径不存在。请提供本机绝对路径。')
        caps = {'platformName': platform, 'appium:automationName': 'UiAutomator2' if platform == 'Android' else 'XCUITest', 'appium:udid': device, 'appium:noReset': True, 'appium:newCommandTimeout': 1200}
        if platform == 'Android':
            try:driver=hybrid_webview.ensure_driver(ROOT,device,log)
            except Exception as error:
                driver=None;log('H5 驱动未就绪，将限制为原生控件识别：'+automation.redact(error,secrets)[:300])
            job['h5_driver_ready']=bool(driver)
            if driver:
                caps['appium:chromedriverExecutable']=driver
                caps['appium:recreateChromeDriverSessions']=True
            # Flutter 页面有光标闪烁等持续动画，UiAutomator2 默认等待 UI 空闲会拖死页面树抓取。
            caps.update({'appium:adbExecTimeout':60000,'appium:uiautomator2ServerLaunchTimeout':120000,'appium:appWaitForLaunch':True,'appium:enforceAppInstall':True,'appium:settings':{'waitForIdleTimeout':0,'actionAcknowledgmentTimeout':3000}})
            if cfg.get('pipeline_id'):caps['appium:settings']['enableMultiWindows']=True
        if cfg.get('test_mode')=='cases' and language_workflow.applies(cfg.get('case_book',{})):
            caps['appium:appWaitForLaunch']=False
            caps['appium:autoGrantPermissions']=True
            caps['appium:newCommandTimeout']=0
            caps['appium:hideKeyboard']=True
            caps['appium:settings']['enableMultiWindows']=True
        if cfg.get('cases',{}).get('start_from_current'):caps['appium:autoLaunch']=False
        if cfg.get('language'):
            caps['appium:language']='en'
            caps['appium:locale']='US' if platform=='Android' else 'en_US'
        if app: caps['appium:app'] = app
        if cfg.get('bundle'): caps['appium:appPackage' if platform == 'Android' else 'appium:bundleId'] = cfg['bundle']
        if not app and not cfg.get('bundle'): raise ValueError('请填写安装包路径或已安装 App 的包名。')
        if platform == 'iOS':
            caps.update({'appium:isHeadless':True,'appium:wdaLaunchTimeout':180000})
            log('正在启动 iOS 模拟器…')
            command(['xcrun', 'simctl', 'boot', device])
        if profile:
            adb, _ = android_tools()
            actual = {}
            for key, args in {'android':['getprop','ro.build.version.release'], 'api':['getprop','ro.build.version.sdk'], 'size':['wm','size'], 'density':['wm','density'], 'model':['getprop','ro.product.model']}.items():
                value = command([adb,'-s',device,'shell'] + args)
                if not value['ok']: raise RuntimeError('读取实际设备参数失败：'+value['output'])
                actual[key] = value['output']
            job['actual_environment'] = actual
            if actual['api'].strip().split('.')[0] != profile['image']['api'].split('.')[0]: raise RuntimeError('实际系统 API 与所选镜像不一致，停止测试。')
            sizes = re.findall(r'(\d+)x(\d+)',actual['size'])
            densities = re.findall(r'(\d+)',actual['density'])
            if not sizes or tuple(map(int,sizes[-1])) != (profile['width'],profile['height']): raise RuntimeError('实际屏幕分辨率与目标配置不一致，停止测试。')
            if not densities or int(densities[-1]) != profile['density']: raise RuntimeError('实际逻辑 DPI 与目标配置不一致，停止测试。')
            log('已核对实际 Android API 主版本、分辨率和逻辑 DPI。')
        if platform == 'Android' and app:
            # Flutter debug 包 versionCode 恒定，Appium 可能跳过安装导致探针不匹配；
            # 用 aapt2 解析包名后强制卸载旧包，确保安装的是本次构建。
            sdk = host_runtime.sdk_root()
            aapts = sorted(sdk.glob('build-tools/*/'+host_runtime.executable('aapt2')))
            if aapts:
                info = command([str(aapts[-1]),'dump','badging',app])
                m = re.search(r"package: name='([^']+)'", info['output']) if info['ok'] else None
                if m:
                    adb,_ = android_tools()
                    command([adb,'-s',device,'uninstall',m.group(1)])
                    log('已卸载旧版本，将安装本次构建的测试包。')
        if cfg.get('live_updates'):runtime_health.restart(ROOT,log)
        if platform == 'Android' and device.startswith('emulator-'):
            adb, _ = android_tools()
            stylus = command([adb, '-s', device, 'shell', 'settings', 'put', 'secure', 'stylus_handwriting_enabled', '0'])
            if stylus['ok']: log('已关闭模拟器触控笔手写输入，避免 "Try out your stylus" 引导弹窗打断测试。')
        log('连接本机 Appium，创建测试会话…')
        session = request('POST', '/session', {'capabilities': {'alwaysMatch': caps, 'firstMatch': [{}]}})
        sid = session['sessionId']
        if app: job['artifact'] = app
        job['build_entrypoint']=cfg.get('entrypoint',job.get('build_entrypoint','lib/main.dart'))
        if probe_name:job['login_probe']=probe_name
        def capture_state(name, source):
            nodes=automation.parse_ui(source)
            if any(n['secure'] for n in nodes) or popup_handler.debug_panel_open(nodes):return
            shot(name, source)
            if not any(n['editable'] for n in nodes):
                (folder / (str(name)+'.xml')).write_text(automation.scrub_xml(source,explorer.secrets),encoding='utf-8')
        capabilities=session.get('capabilities',{})
        key='appPackage' if platform=='Android' else 'bundleId'
        bundle=capabilities.get(key) or capabilities.get('appium:'+key) or cfg.get('bundle')
        if cfg.get('source_plan'):job['source_navigation']=cfg['source_plan']
        if cfg.get('route_tracking'):
            route_reader=source_navigation.RouteReader(platform,device,bundle,command,android_tools()[0])
        def tracked_call(method,path,data=None):
            last_progress[0]=time.monotonic()
            return request(method,path,data)
        explorer = automation.Explorer(tracked_call,sid,platform,log,capture_state,lambda:job.get('stop_requested',False),secrets,
            shell=(lambda args,d=device: command([android_tools()[0],'-s',d,'shell']+args)) if platform=='Android' else None)
        def watchdog():
            # Appium 驱动在个别 WebView 上可能死锁，指令只能靠 socket 超时逐个失败。
            # 连续 7 分钟既无指令返回也无日志，就自动停止任务，避免无限卡住。
            while job.get('status')=='running' and not job.get('stop_requested'):
                time.sleep(20)
                if time.monotonic()-last_progress[0]>420:
                    job['stop_requested']=True
                    log('看门狗：连续 7 分钟无任何指令进展，自动停止任务以便复核。')
                    break
        threading.Thread(target=watchdog,daemon=True).start()
        explorer.app_bundle = bundle if platform=='iOS' and bundle else ''
        explorer.route_reader = route_reader
        explorer.app_package = bundle if platform=='Android' and bundle else ''
        explorer.device_id = device
        if platform=='Android':
            def cleanup_shell(args,d=device):
                value=subprocess.run([android_tools()[0],'-s',d,'shell']+args,capture_output=True,text=True,timeout=10)
                return {'ok':value.returncode==0,'output':value.stdout}
            explorer.cleanup_shell=cleanup_shell
        if cfg.get('flow_index'):
            explorer.flow_index=cfg['flow_index']
            explorer.page_policies={p['path']:p['return'] for p in cfg['flow_index']['pages']}
            explorer.control_aliases={label:item for item in cfg['flow_index']['translations'].values() for label in item}
            for item in cfg['flow_index']['translations'].values():
                for label in item:
                    plain=re.sub(r'^(?:请输入|请填写|输入)','',label)
                    if plain!=label:explorer.control_aliases.setdefault(plain,item)
        if cfg.get('http_manifest'):
            explorer.http_probe=http_probe.Probe(platform,device,bundle,cfg['http_manifest'],command,android_tools()[0])
            job['http_manifest']=cfg['http_manifest']
        if login_cfg.get('enabled') and login_cfg.get('flow')=='keenon_china':
            capabilities=session.get('capabilities',{})
            key='appPackage' if platform=='Android' else 'bundleId'
            bundle=capabilities.get(key) or capabilities.get('appium:'+key) or cfg.get('bundle')
            explorer.login_probe=login_probe.Probe(platform,device,bundle,probe_name or '',command,android_tools()[0])
        if cfg.get('test_mode')=='cases' and language_workflow.applies(cfg['case_book']):
            if platform!='Android' or not login_cfg.get('enabled') or login_cfg.get('flow')!='keenon_china':raise ValueError('语言完整回归需 Android 测试副本并启用内置账号密码登录')
            capture_allowed=True
            def suite_capture(name,source):
                before=len(job['screenshots']);capture_state(name,source)
                return job['screenshots'][-1] if len(job['screenshots'])>before else None
            def suite_progress(results):
                with LOCK:job['case_results']=json.loads(json.dumps(results))
                (folder/'case-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
            results=language_workflow.run(explorer,cfg['case_book'],login_cfg,cfg['flow_index']['project'],log,suite_capture,suite_progress,control.sleep)
            job['login']=getattr(explorer,'login_result',{'status':'not_confirmed'})
            job['status']='stopped' if job.get('stop_requested') else 'failed' if any(r['result']=='fail' for r in results) else 'passed'
            return
        if cfg.get('language',{}).get('phase')=='before_login':job['language']=explorer.switch_language(cfg['language'])
        auth_planned=cfg.get('test_mode')=='cases' and any(c.get('plan',{}).get('start_state','home')!='home' for c in case_runner.preview(cfg['case_book'],cfg.get('cases',{}),cfg.get('flow_index'))['cases'] if c.get('plan'))
        if auth_planned:
            if platform!='Android' or not (cfg.get('source') or cfg.get('pipeline_build_reused') or cfg.get('reuse_test_build')) or not getattr(explorer,'app_package',''):
                raise ValueError('独立登录测试需使用 Android 源码测试副本，不能重置外部安装包')
            import auth_case_setup
            def reset_login_test_app():
                package=explorer.app_package
                explorer.call('POST',explorer.base+'/appium/device/terminate_app',{'appId':package})
                outcome=command([android_tools()[0],'-s',device,'shell','pm','clear',package])
                if not outcome['ok'] or 'Success' not in outcome['output']:raise automation.LoginBlocked('无法初始化当前源码测试副本，未继续执行')
                explorer.call('POST',explorer.base+'/appium/device/activate_app',{'appId':package})
            auth_case_setup.install(explorer,login_cfg,reset_login_test_app,log,control.sleep,cfg.get('language'))
        try:
            job['login'] = {'status':'deferred','reason':'按用例分别准备登录前或登录后状态'} if auth_planned else explorer.login(login_cfg)
        except automation.LoginBlocked:raise
        except Exception as e:
            raise automation.LoginBlocked('登录未完成，请检查登录控件或账号配置：'+automation.redact(e,secrets)) from e
        explorer.allow_source_recovery=job.get('login',{}).get('status')=='confirmed'
        explorer.recovery_events=[]
        if job.get('login',{}).get('confirmation')=='login_api_success_callback':
            log('登录接口已成功，等待页面完成跳转。')
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if not any(n['secure'] for n in automation.parse_ui(explorer.source())):break
                control.sleep(.5)
        capture_allowed = True
        if job.get('login',{}).get('status')=='confirmed':
            log('等待登录后的业务页面就绪，最长 90 秒。')
            login_flow.wait_post_login(explorer,control.sleep)
        control.sleep(3)
        if not auth_planned and not cfg.get('cases',{}).get('start_from_current'):
            try:
                login_flow.dismiss_onboarding(explorer)
            except Exception as e:
                log('引导弹窗清理中断：'+automation.redact(e,secrets)[:120])
        if cfg.get('pipeline_id') and platform=='Android':
            catalog=language_tests.load_runtime_aliases(explorer)
            if catalog:job['runtime_language_catalog']=catalog
        if not auth_planned and cfg.get('language') and cfg['language'].get('phase','after_login')=='after_login':job['language']=explorer.switch_language(cfg['language'])
        if cfg.get('language') and cfg.get('pipeline_id') and platform=='Android':
            job['language']=language_tests.verify_persisted_language(explorer,cfg['language'])
        if cfg.get('language') and not auth_planned:
            capture_state('language-switched',explorer.source())
        if cfg.get('test_mode')=='cases':
            def case_capture(name,source):
                before=len(job['screenshots'])
                capture_state(name,source)
                return job['screenshots'][-1] if len(job['screenshots'])>before else None
            def case_progress(results):
                with LOCK:job['case_results']=json.loads(json.dumps(results))
                (folder/'case-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
            generation=cfg.get('ai_generation')
            if generation:
                results=stream_case_run(explorer,generation,cfg,log,case_capture,case_progress,lambda:job.get('stop_requested',False),control.sleep)
                case_progress(results)
                log('边生成边执行结束：共记录 '+str(len(results))+' 条用例结果')
            else:
                results=case_runner.run(explorer,cfg['case_book'],cfg.get('cases',{}),log,case_capture,case_progress,lambda:job.get('stop_requested',False),control.sleep)
            job['case_results']=results
            if auth_planned:job['login']=getattr(explorer,'login_result',job['login'])
            job['status']='stopped' if job.get('stop_requested') else 'failed' if any(r['result']=='fail' for r in results) else 'passed'
            return
        if cfg.get('test_mode','manual') == 'explore':
            job['exploration'] = explorer.explore(dict(cfg.get('explore',{}),source_plan=cfg.get('source_plan',{})))
            result = job['exploration']
            log('探索结束：'+str(len(result['pages']))+' 个页面状态，'+str(result['actions'])+' 次操作；结束原因：'+result['termination'])
            job['status'] = automation.exploration_status(result)
            return
        explorer.business_groups=semantic_steps.load_groups(cfg.get('business_source') or cfg.get('source',''),cfg.get('h5_source','')) if any(s.get('action')=='business' for s in steps) else []
        shot(0)
        for i, step in enumerate(steps, 1):
            if job.get('stop_requested'):job['status']='stopped';return
            action = step['action']
            log(f'步骤 {i}: {action}')
            if action=='business':
                log('业务步骤：'+automation.redact(step['instruction'],secrets))
                evidence=semantic_steps.perform(explorer,step,control.sleep,job.get('login',{}))
                job.setdefault('custom_step_results',[]).append({'step':i,**evidence})
            elif action in manual_steps.ACTIONS:
                evidence=manual_steps.perform(explorer,step,control.sleep)
                job.setdefault('custom_step_results',[]).append({'step':i,**evidence})
            elif action in ('tap', 'input', 'assert'):
                selector = step.get('by', 'accessibility id')
                if selector not in ('accessibility id', 'id', 'xpath', '-android uiautomator', '-ios predicate string'): raise ValueError('不支持的定位方式')
                element = request('POST', f'/session/{sid}/element', {'using': selector, 'value': step['value']})
                eid = element.get('element-6066-11e4-a52e-4f735466cecf') or element.get('ELEMENT')
                if action == 'tap': request('POST', f'/session/{sid}/element/{eid}/click', {})
                if action == 'input': request('POST', f'/session/{sid}/element/{eid}/value', {'text': step['text']})
            elif action == 'wait': control.sleep(min(max(float(step.get('seconds', 1)), 0), 30))
            elif action == 'back': request('POST', f'/session/{sid}/back', {})
            elif action == 'swipe':
                points = [int(step[k]) for k in ('x1', 'y1', 'x2', 'y2')]
                request('POST', f'/session/{sid}/actions', {'actions': [{'type': 'pointer', 'id': 'finger', 'parameters': {'pointerType': 'touch'}, 'actions': [{'type': 'pointerMove', 'duration': 0, 'x': points[0], 'y': points[1]}, {'type': 'pointerDown', 'button': 0}, {'type': 'pointerMove', 'duration': 600, 'x': points[2], 'y': points[3]}, {'type': 'pointerUp', 'button': 0}]}]})
            elif action != 'screenshot': raise ValueError('未知操作: ' + action)
            shot(i)
            source = request('GET', f'/session/{sid}/source')
            if not popup_handler.debug_panel_open(automation.parse_ui(source)):
                (folder / f'{i:03d}.xml').write_text(automation.scrub_xml(source,secrets), encoding='utf-8')
        log('步骤执行完成。截图需人工复核；本版不自动判断视觉缺陷或采集网络请求。')
        job['status'] = 'passed'
    except Exception as e:
        job['status'] = 'stopped' if job.get('stop_requested') else 'blocked' if isinstance(e,automation.LoginBlocked) or not sid else 'failed'
        log(str(e))
        if sid and capture_allowed and not job.get('stop_requested'):
            try: shot(999)
            except Exception: pass
    finally:
        CONTEXT.control = cancellation.Control()
        if 'explorer' in locals() and getattr(explorer,'http_probe',None):
            try:
                trace=explorer.http_probe.read()
                (folder/'http-events.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
                job['http_events']='/reports/'+jid+'/http-events.json'
            except Exception as error:log('接口观察数据读取失败：'+str(error))
        if cfg.get('test_mode')=='cases':
            results=job.get('case_results',[])
            seen={r['id'] for r in results}
            for case in case_runner.selected_cases(cfg['case_book'],cfg.get('cases',{})):
                if case['id'] not in seen:results.append({'id':case['id'],'sheet':case['sheet'],'row':case['row'],'title':case['title'],'result':'fail','status':'已停止' if job.get('stop_requested') else '未执行','reason':'测试中断或登录/环境未就绪，未完成此用例','screenshots':[]})
            job['case_results']=results
            (folder/'case-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
            if not cfg['case_book'].get('ai'):
                try:
                    case_workbook.annotate(cfg['case_book'],results,folder/'case-results.xlsx')
                    job['case_workbook']='/reports/'+jid+'/case-results.xlsx'
                except Exception as error:log('用例 Excel 写回失败：'+str(error))
        if job.get('stop_requested'):
            job['status'] = 'stopped'
        if sid:
            try: raw_request('DELETE', f'/session/{sid}', timeout=90)
            except Exception as e: log('会话清理失败: ' + str(e))
        if owned_process and (owned_avd or job.get('stop_requested')):
            owned_process.terminate()
            try: owned_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                owned_process.kill()
                owned_process.wait(timeout=2)
        if owned_avd:
            try: matrix.cleanup(*owned_avd)
            except Exception as e: log('模拟器文件清理失败：'+str(e))
        job['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
        # 汇总缺少可访问性标识的控件清单，供 App 侧补充 Semantics/contentDescription。
        missing={}
        for skip in (job.get('exploration') or {}).get('skipped',[]):
            if str(skip.get('reason','')).startswith('缺少可读标识'):
                missing.setdefault(str(skip.get('page','')),[]).append({'label':skip.get('label',''),'kind':skip.get('kind','')})
        if missing:
            (folder/'missing-labels.json').write_text(json.dumps(missing,ensure_ascii=False,indent=2),encoding='utf-8')
            job['missing_labels']='/reports/'+jid+'/missing-labels.json'
        (folder / 'report.json').write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        # PDF 在下载接口按需实时生成，不再逐任务同步生成，避免阻塞批次锁数分钟。


def finalize_batch(jids):
    """批次结束后给每个任务补明确的结束标记，避免“正在中断”成为最后一行。"""
    with LOCK:
        for jid in jids:
            job=JOBS.get(jid)
            if not job:continue
            job.pop('stop_requested',None)
            if job.get('status')=='stopped' and not any('批次已全部结束' in line for line in job.get('logs',[])):
                job['logs'].append('批次已全部结束，测试资源清理完成。')

def stream_case_run(explorer, generation, cfg, log, capture, progress, stopped, sleep):
    """边生成边执行：先跑已生成用例，生成任务每追加一批就继续执行，直到生成结束且全部执行完。"""
    seen=set();results=[]
    while not stopped():
        snapshot=codebuddy_bridge.generation_snapshot(generation)
        document=snapshot['document']
        full=None;pending=[]
        if document and document.get('cases'):
            full=codebuddy_bridge.book(document)
            pending=[c for c in full['cases'] if c['id'] not in seen]
        if pending:
            if seen:log('生成任务已追加 '+str(len(pending))+' 条用例，继续执行')
            round_book={**full,'cases':pending}
            def round_progress(rows,_results=results):
                progress(_results+rows)
            results.extend(case_runner.run(explorer,round_book,cfg.get('cases',{}),log,capture,round_progress,stopped,sleep))
            seen.update(r['id'] for r in results)
            cfg['case_book']=full
        if snapshot['status'] in ('done','failed'):
            if snapshot['status']=='failed':log('生成任务提前结束：'+str(snapshot.get('error',''))[:200]+'；已生成的用例仍按以上结果为准')
            break
        if not pending:sleep(3)
    return results


def run_batch(entries):
    try:
        _run_batch(entries)
    finally:
        try:
            for jid, _ in entries:
                shutil.rmtree(ROOT/'.runtime'/('login-source-'+jid),ignore_errors=True)
            finalize_batch([jid for jid,_ in entries])
        finally:
            BATCH_RUNNING.clear()

def _run_batch(entries):
    artifacts = {}
    for jid, cfg in entries:
        if JOBS[jid].get('stop_requested'):
            with LOCK:
                JOBS[jid]['status']='stopped'
                JOBS[jid]['logs'].append('本批次已停止，未执行此目标。')
                JOBS[jid]['finished']=time.strftime('%Y-%m-%d %H:%M:%S')
            folder=ROOT/'reports'/jid;folder.mkdir(parents=True,exist_ok=True)
            (folder/'report.json').write_text(json.dumps(JOBS[jid],ensure_ascii=False,indent=2))
            continue
        with LOCK: JOBS[jid]['status'] = 'running'
        platform = cfg['platform']
        if cfg.get('source') and platform in artifacts:
            cfg = dict(cfg, business_source=cfg.get('source',''), source='', app=artifacts[platform]['app'],login_probe=artifacts[platform].get('login_probe'), source_plan=artifacts[platform].get('source_plan'),route_tracking=artifacts[platform].get('route_tracking'),http_manifest=artifacts[platform].get('http_manifest'),flow_index=artifacts[platform].get('flow_index'))
        try:
            run_job(jid,cfg)
        except Exception as e:
            with LOCK:
                JOBS[jid]['status'] = 'failed'
                JOBS[jid]['logs'].append('任务异常：'+automation.redact(e,[cfg.get('login',{}).get('account',''),cfg.get('login',{}).get('password','')]))
                JOBS[jid]['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
        if JOBS[jid].get('artifact'): artifacts[platform] = {'app':JOBS[jid]['artifact'],'login_probe':JOBS[jid].get('login_probe'),'source_plan':cfg.get('source_plan'),'route_tracking':cfg.get('route_tracking'),'http_manifest':cfg.get('http_manifest'),'flow_index':cfg.get('flow_index')}
    for _, cfg in entries:
        login = cfg.get('login',{})
        login.pop('account',None); login.pop('password',None)

class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Cache-Control','no-store'); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path=='/api/language-pipelines':
            with language_pipeline.LOCK:identifiers=list(language_pipeline.TASKS)
            return self.send_json([language_pipeline.snapshot(i) for i in identifiers])
        if self.path.startswith('/api/language-pipelines/'):
            try:return self.send_json(language_pipeline.snapshot(self.path.rsplit('/',1)[-1]))
            except ValueError as error:return self.send_json({'error':str(error)},404)
        if self.path.startswith('/api/pdf/'):
            jid=self.path.rsplit('/',1)[-1]
            with LOCK: job=json.loads(json.dumps(JOBS.get(jid)))
            if not job or not job.get('finished'):return self.send_json({'error':'报告尚未完成'},404)
            report=ROOT/'reports'/jid/'report.json'
            runtime=ROOT/'.runtime/pdf-venv/bin/python'
            if getattr(__import__('sys'),'frozen',False) or not runtime.is_file():
                import pdf_report
                pdf_report.build(job,ROOT,report.with_suffix('.pdf'))
            else:
                result=subprocess.run([str(runtime),str(ROOT/'pdf_report.py'),str(report)],capture_output=True,timeout=60)
                if result.returncode:return self.send_json({'error':'PDF 生成失败，请检查 PDF 运行环境'},500)
            body=report.with_suffix('.pdf').read_bytes()
            self.send_response(200);self.send_header('Content-Type','application/pdf');self.send_header('Content-Disposition','attachment; filename="device-'+jid+'.pdf"');self.end_headers();self.wfile.write(body);return
        if self.path.startswith('/api/batches/'):

            bid = self.path.rsplit('/',1)[-1]
            with LOCK: items = json.loads(json.dumps([j for j in JOBS.values() if j.get('batch')==bid]))
            if not items: return self.send_json({'error':'批次不存在'},404)
            return self.send_json({'batch':bid,'total':len(items),'counts':{s:sum(j['status']==s for j in items) for s in ('queued','running','passed','failed','blocked','stopped','review')},'jobs':items})
        if self.path == '/api/languages':return self.send_json({'languages':language_tests.LANGUAGES,'source':'App 源码 DataCache.getLanguageList；实际可用语言由云端配置决定'})
        if self.path == '/api/catalog': return self.send_json({'profiles':matrix.catalog(), 'images':matrix.images()})
        if self.path == '/api/devices': return self.send_json(devices())
        if self.path == '/api/jobs':
            with LOCK: snapshot = json.loads(json.dumps(list(JOBS.values())))
            return self.send_json(snapshot)
        if self.path == '/api/ai/status': return self.send_json(codebuddy_bridge.status())
        if self.path.startswith('/api/ai/generations/'):
            try:return self.send_json(codebuddy_bridge.generation_status(self.path.rsplit('/',1)[-1]))
            except ValueError as error:return self.send_json({'error':str(error)},404)
        file_path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        target = ROOT / ('index.html' if file_path == '/' else file_path.lstrip('/'))
        target = target.resolve()
        if (target != ROOT / 'index.html' and ROOT / 'reports' not in target.parents) or not target.is_file(): return self.send_error(404)
        self.send_response(200); self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if target.suffix == '.xlsx' else 'image/png' if target.suffix == '.png' else 'application/json' if target.suffix == '.json' else 'text/plain; charset=utf-8' if target.suffix in ('.log', '.xml', '.md') else 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(target.read_bytes())
    def do_POST(self):
        if self.headers.get('Origin') not in (None, 'http://127.0.0.1:'+str(self.server.server_port)): return self.send_json({'error': '来源不允许'}, 403)
        if self.path not in ('/api/run', '/api/batch','/api/steps/preview','/api/stop','/api/cases/preview','/api/ai/config','/api/ai/models/refresh','/api/ai/test','/api/ai/generate','/api/ai/generations','/api/ai/runtime','/api/login/credentials','/api/language-pipelines','/api/language-pipelines/stop'): return self.send_error(404)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length > 2000000: raise ValueError('请求过大')
            cfg = json.loads(self.rfile.read(length))
            if not isinstance(cfg,dict):raise ValueError('请求必须是对象')
            if self.path=='/api/language-pipelines/stop':return self.send_json(language_pipeline.stop(cfg.get('id')))
            if self.path=='/api/language-pipelines':
                with LOCK:
                    if BATCH_RUNNING.is_set() or any(j['status'] in ('running','queued') for j in JOBS.values()):raise ValueError('请先等待当前设备测试完成')
                return self.send_json(language_pipeline.start(cfg,PipelineAPI(self.server.server_port)),202)
            if self.path == '/api/steps/preview':
                plan=semantic_steps.compile_text(cfg.get('text',''))
                return self.send_json({'steps':plan,'note':'输入内容保持原文；运行时根据源码翻译映射和页面控件定位。提交仅适配报修表单。'})
            if self.path == '/api/login/credentials':
                account=cfg.get('account','')
                operation=cfg.get('operation','status')
                if operation=='save':login_credential_store.save(account,cfg.get('password'))
                elif operation=='delete':login_credential_store.delete(account)
                elif operation!='status':raise ValueError('未知登录信息操作')
                return self.send_json({'saved':False if operation=='delete' else login_credential_store.saved(account)})
            if self.path == '/api/ai/runtime':
                with LOCK:
                    if BATCH_RUNNING.is_set() or any(j['status'] in ('running','queued') for j in JOBS.values()):raise ValueError('测试队列正在使用设备，请完成后再采集')
                    return self.send_json(runtime_inventory.collect(request,cfg,ROOT))
            if self.path == '/api/ai/models/refresh':return self.send_json(codebuddy_bridge.refresh_models())
            if self.path == '/api/ai/config':return self.send_json(codebuddy_bridge.configure(cfg))
            if self.path == '/api/ai/test':return self.send_json(codebuddy_bridge.connection(cfg))
            if self.path == '/api/ai/generate':return self.send_json(codebuddy_bridge.generate(cfg))
            if self.path == '/api/ai/generations':return self.send_json(codebuddy_bridge.start_generation(cfg),202)
            if self.path=='/api/cases/preview':
                book=excel_ai.apply(case_workbook.read(cfg.get('path','')),cfg)
                import hashlib
                index=flow_planner.source_index(cfg['source']) if cfg.get('source','').strip() else None
                flows=flow_planner.build({'cases':case_runner.selected_cases(book,cfg)},index)
                return self.send_json({**case_workbook.summary(book),**case_runner.preview(book,cfg,index),'flow_summary':{'source_pages':len(index['pages']) if index else 0,'located':sum(bool(f['page_candidates']) for f in flows['flows']),'total':len(flows['flows']),'note':flows['note']},'flow_examples':flows['flows'][:3],'fingerprint':hashlib.sha256(book['content']).hexdigest()})
            if self.path == '/api/stop':
                with LOCK:
                    job=JOBS.get(cfg.get('id',''))
                    if not job:return self.send_json({'error':'任务不存在'},404)
                    for item in JOBS.values():
                        if (item.get('batch') == job.get('batch') if job.get('batch') else item['id'] == job['id']) and item['status'] in ('running','queued'):
                            item['stop_requested']=True
                            if item['status']=='queued':item['status']='stopped'
                            item['logs'].append('收到停止请求，正在中断操作并清理测试资源。')
                return self.send_json({'ok':True})
            if cfg.get('test_mode')=='explore':
                cfg.setdefault('explore',{})['form']=form_runner.validate(cfg.get('explore',{}).get('form'))
            if cfg.get('test_mode','manual') not in ('manual','explore','cases','ai'):raise ValueError('未知测试模式')
            if cfg.get('test_mode')=='ai':
                generation=cfg.pop('ai_generation',None)
                document=cfg.pop('ai_plan',None)
                if generation and document is None:
                    # 边生成边执行：从进行中的生成任务读取当前草稿，执行任务后续自动追加新用例。
                    snapshot=codebuddy_bridge.generation_snapshot(generation)
                    document=snapshot['document']
                    if not document or not document.get('cases'):raise ValueError('生成任务尚未产出任何用例，请稍候再开始')
                    cfg['ai_generation']=generation
                cfg['case_book']=codebuddy_bridge.book(document)
                cfg['cases']={'start_from_current':cfg.pop('ai_start_from_current',False) is True}
                if not any(c['plan_text'] for c in cfg['case_book']['cases']):raise ValueError('业务计划已生成，但尚无完整可执行用例；请查看各步骤的自动化适配说明')
                cfg['test_mode']='cases'
            elif cfg.get('test_mode')=='cases':
                options=cfg.get('cases',{})
                if not isinstance(options,dict):raise ValueError('用例配置无效')
                book=case_workbook.read(options.get('path',''))
                import hashlib
                if not options.get('fingerprint') or options['fingerprint']!=hashlib.sha256(book['content']).hexdigest():raise ValueError('用例文件已变化或尚未预览，请重新读取用例')
                book=excel_ai.apply(book,options)
                preview=case_runner.preview(book,options)
                if not preview['selected']:raise ValueError('当前筛选没有手机用例')
                if not preview['ready']:raise ValueError('当前没有可执行用例，请先完成 AI 步骤生成并确认有可执行结果；测试未启动')
                cfg['case_book']=book
                if options.get('source','').strip():cfg['flow_index']=flow_planner.source_index(options['source'])
            cached_build = False
            if cfg.get('pipeline_id'):cached_build=apply_pipeline_build(cfg)
            if cfg.get('reuse_test_build'):
                cache=ROOT/'.runtime/flow-replay'
                metadata=json.loads((cache/'build-metadata.json').read_text())
                artifact=cache/'app-debug.apk'
                if metadata.get('entrypoint','lib/main.dart')!=cfg.get('entrypoint','lib/main.dart'):raise ValueError('缓存测试包的启动入口不一致，请重新从源码构建')
                if not artifact.is_file() or not re.fullmatch(r'devicecheck-login-[a-f0-9]{32}\.json',metadata.get('login_probe','')):raise ValueError('可重测的测试包不存在，请先从源码构建')
                cfg.update(source='',app=str(artifact),login_probe=metadata['login_probe'],source_plan=metadata['source_plan'],route_tracking=True)
                cfg['http_manifest']=metadata.get('http_manifest')
                cfg['flow_index']=metadata.get('flow_index',cfg.get('flow_index'))
                cached_build=True
            if cfg.get('cases',{}).get('start_from_current'):
                if cfg.get('source','').strip() or cfg.get('app','').strip() or (isinstance(cfg.get('login'),dict) and cfg['login'].get('enabled')) or (isinstance(cfg.get('languages'),dict) and cfg['languages'].get('enabled')):
                    raise ValueError('从当前页面开始时，请只填写已安装 App 的包名，清空源码和安装包，关闭自动登录及语言切换')
            login=cfg.get('login',{})
            if not isinstance(login,dict):raise ValueError('登录配置无效')
            login_credential_store.resolve(login)
            if login.get('enabled'):
                if not all(isinstance(login.get(k),str) and 0<len(login[k])<=1024 for k in ('account','password')):raise ValueError('请填写有效的测试账号和密码')
                if login.get('flow') not in (None,'custom','keenon_china'):raise ValueError('未知登录流程')
                if login.get('flow')=='keenon_china':
                    if not cached_build and not cfg.get('source','').strip():raise ValueError('内置流程需要 Flutter 源码来验证登录接口成功；安装包请选自定义页面标识验证。')
                    if not cached_build:login_probe.validate(Path(cfg['source']).expanduser().resolve())
                if login.get('flow')!='keenon_china' and (not isinstance(login.get('success'),dict) or not login['success'].get('value','').strip()):raise ValueError('请填写登录成功标识')
                if not isinstance(login.get('prepare',[]),list) or len(login.get('prepare',[]))>10 or not all(isinstance(x,str) and 0<len(x)<=512 for x in login.get('prepare',[])):raise ValueError('登录前操作需为最多 10 项按钮文字')
            if language_workflow.applies(cfg.get('case_book',{})):
                if not login.get('enabled') or login.get('flow')!='keenon_china' or not cfg.get('source','').strip():raise ValueError('完整登录/语言回归需要填写 Flutter 源码，并启用内置账号密码自动登录；保存的密码可留空自动使用')
            if cfg.get('source','').strip():
                cfg['entrypoint']=build_config.entrypoint(Path(cfg['source']).expanduser(),cfg.get('entrypoint','lib/main.dart'))
            if cfg.get('test_mode','manual')=='manual' and cfg.get('step_format')=='chinese':
                cfg['steps']=semantic_steps.compile_text(cfg.get('business_text',''))
                if any(x['op']=='login' for x in cfg['steps']) and not login.get('enabled'):raise ValueError('中文步骤包含自动登录，请先启用并配置自动登录')
            cfg['live_updates']=True
            selections = cfg.get('targets') if self.path == '/api/batch' else [{'platform':cfg.get('platform'), 'device':cfg.get('device')}]
            if not isinstance(selections,list) or not 1 <= len(selections) <= 60: raise ValueError('请选择 1～60 个测试目标')
            if not cfg.get('source','').strip() and not cfg.get('app','').strip() and not cfg.get('bundle','').strip(): raise ValueError('请填写源码、安装包或已安装 App 包名')
            steps = cfg.get('steps',[])
            if not isinstance(steps,list) or len(steps)>200: raise ValueError('步骤必须是数组，最多 200 步')
            for step in steps:
                if not isinstance(step,dict):raise ValueError('每个步骤必须为 JSON 对象')
                manual_steps.validate(step)
            entries = []
            batch = uuid.uuid4().hex[:12]
            known = {p['id']:p for p in matrix.catalog()}
            for selection in selections:
                target = dict(cfg)
                target.pop('targets',None)
                if selection.get('ios_model'):
                    model, simulator = ios_models.resolve(selection['ios_model'], devices()['reference_profiles'])
                    target.pop('profile',None)
                    target.update(platform='iOS',device=simulator['id'],ios_reference=model)
                    label='苹果 '+model['name']+' · '+simulator['name']
                elif selection.get('profile'):
                    profile = selection['profile']
                    if profile.get('id') not in known: raise ValueError('未知机型')
                    if not cfg.get('source','').strip() and not cfg.get('app','').strip(): raise ValueError('机型模拟需要源码或安装包')
                    target.update(platform='Android', device='', profile=profile)
                    label = known[profile['id']]['brand']+' '+known[profile['id']]['name']
                else:
                    if selection.get('platform') not in ('Android','iOS') or not selection.get('device'): raise ValueError('请选择有效设备')
                    target.update(platform=selection['platform'],device=selection['device'])
                    label = selection.get('name',selection['device'])
                jid = uuid.uuid4().hex[:12]
                entries.append((jid,target, label))
            entries=language_tests.expand(entries,cfg.get('languages',{}))
            problems = []
            for jid,target,label in entries:
                if target.get('profile'):
                    try: matrix.resolve_profile(target['profile'])
                    except (ValueError,TypeError) as e: problems.append(label+'：'+str(e))
            try: request('GET','/status')
            except Exception: problems.append('Appium 未就绪：请先配置 Appium 与平台驱动（桌面版运行自动化环境配置）。')
            if problems: return self.send_json({'error':'测试未开始，启动前检查发现：\n'+'\n'.join(problems)},400)
            with LOCK:
                pipeline_id=cfg.get('pipeline_id')
                if pipeline_id and not language_pipeline.owns(pipeline_id):raise ValueError('语言接力标识已失效')
                if language_pipeline.active() and not pipeline_id:return self.send_json({'error':'语言接力正在使用测试队列，请等待完成或停止接力任务'},409)
                if BATCH_RUNNING.is_set() or any(j['status'] in ('running','queued') for j in JOBS.values()):
                    busy=[j for j in JOBS.values() if j['status'] in ('running','queued')]
                    if not busy:message='上一批次正在收尾清理，请几秒后重试。'
                    else:message='请等待当前批量队列和资源清理完成（执行中 %d 个，排队 %d 个）'%(sum(j['status']=='running' for j in busy),sum(j['status']=='queued' for j in busy))
                    return self.send_json({'error':message},409)
                reports = ROOT / 'reports'
                if not pipeline_id:
                    if reports.exists(): shutil.rmtree(reports)
                    JOBS.clear()
                for jid,target,label in entries:
                    JOBS[jid] = {'language':({k:target['language'][k] for k in ('code','name')} if target.get('language') else None),'id':jid,'batch':batch,'label':label,'status':'queued','device':target['device'],'platform':target['platform'],'logs':[],'screenshots':[],'started':time.strftime('%Y-%m-%d %H:%M:%S')}
                BATCH_RUNNING.set()
            threading.Thread(target=run_batch,args=([(jid,target) for jid,target,label in entries],),daemon=True).start()
            self.send_json({'id':batch,'count':len(entries)})
        except Exception as e: self.send_json({'error': str(e)}, 400)

def restore_history():
    language_pipeline.restore_history()
    for saved in (ROOT / 'reports').glob('*/report.json'):
        try:
            item = json.loads(saved.read_text())
            if item.get('status') in ('running','queued'): item['status'] = 'failed'; item.setdefault('logs',[]).append('工具重启，任务已中断。')
            if item.get('status')=='failed' and any(any(t in line for t in ('基线待核验','镜像，本机未安装','App 路径不存在')) for line in item.get('logs',[])):
                item['status']='blocked'
                saved.write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8')
            JOBS[item['id']] = item
        except (ValueError, KeyError): pass


if __name__ == '__main__':
    restore_history()
    print('DeviceCheck 已启动：http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
