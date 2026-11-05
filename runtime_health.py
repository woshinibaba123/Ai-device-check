"""Lifecycle isolation for this repository's private Appium server."""
import json,os,signal,subprocess,time,urllib.request
from pathlib import Path


def restart(root, log):
    import sys
    if sys.platform=='win32' or os.environ.get('DEVICECHECK_DESKTOP')=='1':return desktop_restart(root,log)
    root=Path(root);expected=str(root/'.runtime/node_modules/.bin/appium')
    result=subprocess.run(['/usr/sbin/lsof','-t','-iTCP:4723','-sTCP:LISTEN'],capture_output=True,text=True,timeout=5)
    pids={int(p) for p in result.stdout.split() if p.isdigit()}
    for pid in pids:
        process=subprocess.run(['/bin/ps','-p',str(pid),'-o','command='],capture_output=True,text=True,timeout=5)
        if expected not in process.stdout:raise RuntimeError('4723 端口不是本工具专用服务，未重启外部服务。')
    for pid in pids:
        try:os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:pass
    deadline=time.monotonic()+10
    for pid in pids:
        while time.monotonic()<deadline:
            try:os.kill(pid,0)
            except ProcessLookupError:break
            time.sleep(.2)
        else:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
    with (root/'appium-console.log').open('ab') as stream:
        child=subprocess.Popen([str(root/'启动自动操作服务.command')],cwd=str(root),stdout=stream,stderr=stream,start_new_session=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(60):
        if child.poll() is not None:raise RuntimeError('专用自动化服务启动失败，请查看 appium-console.log。')
        try:
            with opener.open('http://127.0.0.1:4723/status',timeout=1) as response:
                if json.load(response).get('value',{}).get('ready'):
                    log('已隔离上一台设备会话，专用自动化服务重新就绪。');return
        except (OSError,ValueError):pass
        time.sleep(.3)
    raise RuntimeError('专用自动化服务启动等待超时。')


_owned_desktop = None


def desktop_restart(root,log):
    """Restart only the child created by this process; never stop another listener."""
    import host_runtime,shutil,socket
    global _owned_desktop
    root=Path(root);port=host_runtime.appium_port()
    if _owned_desktop is not None:
        host_runtime.stop_process(_owned_desktop)
        try:_owned_desktop.wait(timeout=5)
        except subprocess.TimeoutExpired:
            host_runtime.stop_process(_owned_desktop,force=True);_owned_desktop.wait(timeout=5)
        _owned_desktop=None
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('桌面端 Appium 端口已被其他进程占用，未停止该进程。')
    node=shutil.which('node');entry=root/'.runtime/node_modules/appium/build/lib/main.js'
    if not node or not entry.is_file():raise RuntimeError('尚未配置桌面自动化环境，请先运行桌面环境配置脚本（需要 Node.js、Android SDK；iOS 另需 Mac 和 Xcode）。')
    env=os.environ.copy();env['APPIUM_HOME']=str(root/'.appium')
    with (root/'appium-console.log').open('ab') as stream:
        child=subprocess.Popen([node,str(entry),'--address','127.0.0.1','--port',str(port),'--log',str(root/'appium.log'),'--log-no-colors','--log-level','warn'],env=env,cwd=root,stdout=stream,stderr=stream,start_new_session=True)
    _owned_desktop=child
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(60):
        if child.poll() is not None:raise RuntimeError('桌面自动化服务启动失败，请查看数据目录下的 appium-console.log。')
        try:
            with opener.open(host_runtime.appium_url()+'/status',timeout=1) as response:
                if json.load(response).get('value',{}).get('ready'):
                    log('桌面端专用自动化服务已就绪。');return
        except (OSError,ValueError):pass
        time.sleep(.3)
    raise RuntimeError('桌面自动化服务启动等待超时。')


def desktop_stop():
    global _owned_desktop
    if _owned_desktop is not None:
        import host_runtime
        host_runtime.stop_process(_owned_desktop)
        try:_owned_desktop.wait(timeout=5)
        except subprocess.TimeoutExpired:host_runtime.stop_process(_owned_desktop,force=True)
        _owned_desktop=None
