import host_runtime
"""Verified source-backed screen profiles and isolated Android AVD provisioning."""
import json, os, platform, re, shutil, subprocess, time
from pathlib import Path

BASE = host_runtime.root()
API_BY_ANDROID = {'8.1':27, '9':28, '10':29, '11':30, '12':31, '12L':32, '13':33, '14':34, '15':35, '16':36}

def catalog():
    return json.loads((BASE/'catalog.json').read_text())

def sdk_root():
    return host_runtime.sdk_root()

def images():
    sdk = sdk_root()
    abi = 'arm64-v8a' if platform.machine() == 'arm64' else 'x86_64'
    result = []
    for props in (sdk/'system-images').glob('*/*/*/source.properties'):
        values = {}
        for line in props.read_text().splitlines():
            if '=' in line:
                k,v = line.split('=',1); values[k.strip()] = v.strip()
        if values.get('SystemImage.Abi') != abi: continue
        package = ';'.join(props.parent.relative_to(sdk).parts)
        api = values.get('AndroidVersion.ApiLevel','?')
        result.append({'package':package, 'api':api, 'abi':abi, 'label':values.get('Pkg.Desc',package), 'path':str(props.parent)})
    return sorted(result, key=lambda v:v['package'])

def resolve_profile(selection):
    profile = next((p for p in catalog() if p['id']==selection.get('id')),None)
    if not profile: raise ValueError('未知机型')
    profile = dict(profile)
    density = int(selection.get('density', profile['density']))
    if not 120 <= density <= 800: raise ValueError('逻辑 DPI 必须在 120～800 之间')
    profile['density'] = density
    runtime = selection.get('image','baseline')
    installed = images()
    if runtime == 'baseline':
        api = API_BY_ANDROID.get(profile['android'])
        if api is None: raise ValueError(profile['name']+' 的 Android 基线待核验，请明确选择测试镜像；不能自动猜测版本。')
        candidates = [i for i in installed if i['api']==str(api) and re.fullmatch(r'android-\d+', i['package'].split(';')[1])]
        if not candidates: raise ValueError(f"{profile['name']} 需要 Android {profile['android']} / API {api} 镜像，本机未安装兼容架构镜像。请先到 Android Studio → SDK Manager 安装；不会替换为其他版本。")
        image = candidates[0]
    else:
        image = next((i for i in installed if i['package']==runtime),None)
        if not image: raise ValueError('所选系统镜像未安装或与 Mac 架构不兼容')
    profile['image'] = image
    profile['coverage'] = '屏幕参数近似模拟；通用 Android 镜像；不覆盖厂商 ROM、芯片、性能和屏幕挖孔。逻辑 DPI 为可调整测试值。'
    return profile

def prepare(profile, folder, log, runner=subprocess.run):
    sdk = sdk_root()
    tools = sorted((sdk/'cmdline-tools').glob('*/bin/'+host_runtime.batch_name('avdmanager')))
    manager = shutil.which(host_runtime.batch_name('avdmanager')) or (str(tools[-1]) if tools else None)
    if not manager: raise ValueError('未找到 avdmanager，请在 Android Studio SDK Manager 安装 Android SDK Command-line Tools。')
    name = 'DeviceCheck_' + profile['id'] + '_' + str(time.time_ns())
    home = Path(os.environ.get('ANDROID_AVD_HOME') or Path.home()/'.android/avd')
    home.mkdir(parents=True,exist_ok=True)
    target = home/(name+'.avd')
    log('创建独立模拟器：'+profile['name']+' · API '+profile['image']['api'])
    try:
        result = runner([manager,'create','avd','-n',name,'-k',profile['image']['package'],'-p',str(target)],input='no\n',text=True,capture_output=True,timeout=90)
    except Exception:
        cleanup(name, target)
        raise
    if result.returncode:
        cleanup(name, target)
    if result.returncode: raise RuntimeError('创建模拟器失败：'+result.stdout+result.stderr)
    config = target/'config.ini'
    values = dict(line.split('=',1) for line in config.read_text().splitlines() if '=' in line)
    values.update({'hw.lcd.width':str(profile['width']),'hw.lcd.height':str(profile['height']),'hw.lcd.density':str(profile['density']),'hw.ramSize':'4096','hw.keyboard':'yes','showDeviceFrame':'no','skin.dynamic':'yes','skin.name':f"{profile['width']}x{profile['height']}",'hw.gpu.enabled':'yes','hw.gpu.mode':'swiftshader','hw.cpu.ncore':'4'})
    config.write_text('\n'.join(k+'='+v for k,v in values.items())+'\n')
    return name, target

def cleanup(name, target):
    # Only tool-created directories are eligible for deletion.
    if not name.startswith('DeviceCheck_') or target.name != name+'.avd': return
    shutil.rmtree(target,ignore_errors=True)
    (target.parent/(name+'.ini')).unlink(missing_ok=True)
