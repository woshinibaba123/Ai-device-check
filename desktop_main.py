"""Native desktop window with a private local backend and user-writable data."""
import html
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import host_runtime


def data_directory():
    if os.environ.get('DEVICECHECK_DATA_DIR'):return Path(os.environ['DEVICECHECK_DATA_DIR']).expanduser().resolve()
    if sys.platform=='win32':return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'DeviceCheck'
    return Path.home()/'Library/Application Support/DeviceCheck'


def prepare():
    root=data_directory();root.mkdir(parents=True,exist_ok=True)
    resources=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    for name in ('index.html','catalog.json','model_credit_reference.json'):
        source=resources/name
        if source.resolve()!=(root/name).resolve():shutil.copy2(source,root/name)
    os.environ['DEVICECHECK_DATA_DIR']=str(root)
    os.environ['DEVICECHECK_DESKTOP']='1'
    os.environ.setdefault('DEVICECHECK_APPIUM_PORT','14723')
    host_runtime.setup_environment(root)
    return root


def main():
    root=prepare()
    # Capture backend output in a stable place; windowed executables have no console.
    log=(root/'desktop.log').open('a',encoding='utf-8',buffering=1)
    sys.stdout=log;sys.stderr=log
    import webview
    webview.settings['ALLOW_DOWNLOADS']=True
    if '--setup-runtime' in sys.argv:
        from desktop.setup_runtime import configure
        window=webview.create_window('巡测 · 配置自动化环境',html='<h2>正在配置自动化环境</h2><p>请等待 Appium 和平台驱动安装完成。详细进度记录在数据目录 desktop.log。</p>',width=700,height=350)
        def setup():
            try:
                configure(root)
                window.load_html('<h2>自动化环境配置完成</h2><p>请关闭并重新打开巡测桌面版。设备测试仍需本机的 SDK、Java；源码构建另需 Flutter。</p>')
            except Exception as error:
                window.load_html('<h2>环境尚未配置完成</h2><p>'+html.escape(str(error))+'</p><p>详细进度记录在数据目录 desktop.log。</p>')
        webview.start(setup);return
    import app,runtime_health
    port=int(os.environ.get('DEVICECHECK_DESKTOP_PORT','18765'))
    try:server=app.ThreadingHTTPServer(('127.0.0.1',port),app.Handler)
    except OSError:
        webview.create_window('巡测 · 无法启动',html='<h2>桌面端已经运行，或本机端口被占用</h2><p>请检查已打开的巡测窗口后重试。</p>',width=640,height=300)
        webview.start();return
    app.restore_history()
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    # Missing SDKs do not prevent opening the configuration and diagnostics UI.
    if (root/'.runtime/node_modules/appium/build/lib/main.js').is_file():
        def start_appium():
            try:runtime_health.desktop_restart(root,print)
            except Exception as error:print('自动化服务：'+str(error))
        threading.Thread(target=start_appium,daemon=True).start()
    window=webview.create_window('巡测 · 桌面工作台','http://127.0.0.1:'+str(port),width=1280,height=900,min_size=(900,640))
    def closing():
        # Keep the process alive while test resource cleanup is still running.
        if app.BATCH_RUNNING.is_set() or app.language_pipeline.active() or app.codebuddy_bridge.status().get('busy'):
            window.create_confirmation_dialog('测试仍在执行','请先在工作台停止任务并等待资源清理完成，再关闭桌面窗口。')
            return False
    window.events.closing+=closing
    try:webview.start(private_mode=False,storage_path=str(root/'webview'))
    finally:
        server.shutdown();server.server_close();runtime_health.desktop_stop()


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
