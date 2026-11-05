"""Host paths and process primitives shared by source and desktop builds."""
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def root():
    return Path(os.environ.get('DEVICECHECK_DATA_DIR') or Path(__file__).resolve().parent)


def sdk_root():
    default=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'Android/Sdk' if sys.platform=='win32' else Path.home()/'Library/Android/sdk'
    return Path(os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or default)


def executable(name):
    return name+('.exe' if sys.platform=='win32' else '')


def batch_name(name):
    return name+('.bat' if sys.platform=='win32' else '')


def appium_port():return int(os.environ.get('DEVICECHECK_APPIUM_PORT','4723'))
def appium_url():return 'http://127.0.0.1:'+str(appium_port())


def stop_process(process,force=False):
    if process.poll() is not None:return
    if sys.platform=='win32':
        # /T includes descendants started by npm, adb and build wrappers.
        args=['taskkill','/PID',str(process.pid),'/T']
        if force:args.append('/F')
        subprocess.run(args,capture_output=True,timeout=10)
    else:
        try:os.killpg(process.pid,signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:pass


def copy_source(source,target,run):
    if sys.platform=='darwin':
        result=run(['/bin/cp','-cR',str(source),str(target)],capture_output=True,text=True,timeout=180)
        if result.returncode:raise RuntimeError('创建测试源码副本失败：'+result.stderr)
    else:
        shutil.copytree(source,target,ignore=shutil.ignore_patterns('.git','build','.dart_tool','.fvm','node_modules'))


def setup_environment(data_root):
    """Finder-launched apps do not inherit shell startup files."""
    data_root=Path(data_root)
    sdk=sdk_root();os.environ.setdefault('ANDROID_HOME',str(sdk));os.environ.setdefault('ANDROID_SDK_ROOT',str(sdk))
    os.environ['APPIUM_HOME']=str(data_root/'.appium')
    bins=[data_root/'.runtime/node_modules/.bin',data_root/'.runtime/codebuddy/node_modules/.bin',sdk/'platform-tools',sdk/'emulator',sdk/'cmdline-tools/latest/bin',Path('/opt/homebrew/bin'),Path('/usr/local/bin')]
    bins+=sorted((Path.home()/'.nvm/versions/node').glob('*/bin'),reverse=True)
    if sys.platform=='win32':bins+=[Path(os.environ.get('ProgramFiles','C:/Program Files'))/'nodejs',Path(os.environ.get('APPDATA',''))/'npm']
    os.environ['PATH']=os.pathsep.join(map(str,bins))+os.pathsep+os.environ.get('PATH','')
    if sys.platform=='darwin' and not os.environ.get('JAVA_HOME'):
        result=subprocess.run(['/usr/libexec/java_home'],capture_output=True,text=True,timeout=5)
        if result.returncode==0:os.environ['JAVA_HOME']=result.stdout.strip()
