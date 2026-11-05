"""Install project-private automation dependencies, using the official npm registry."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import host_runtime


def configure(root=None):
    root=Path(root or host_runtime.root());root.mkdir(parents=True,exist_ok=True)
    host_runtime.setup_environment(root)
    npm=shutil.which('npm.cmd' if sys.platform=='win32' else 'npm')
    if not npm:raise RuntimeError('请先安装 Node.js（包含 npm），再配置自动化环境。')
    # Project versions already used by the web tool. SDKs/licenses are user-managed.
    commands=[
        [npm,'install','--prefix',str(root/'.runtime'),'appium@3.8.0','--registry=https://registry.npmjs.org'],
        [shutil.which('node'),str(root/'.runtime/node_modules/appium/build/lib/main.js'),'driver','install','uiautomator2@8.7.0'],
    ]
    if sys.platform=='darwin':commands.append([shutil.which('node'),str(root/'.runtime/node_modules/appium/build/lib/main.js'),'driver','install','xcuitest@12.19.0'])
    for args in commands:
        driver=args[-1]
        if driver.startswith(('uiautomator2@','xcuitest@')) and (root/'.appium/node_modules'/('appium-'+driver.split('@')[0]+'-driver')).is_dir():continue
        result=subprocess.run(args,cwd=root,stdout=sys.stdout,stderr=sys.stderr)
        if result.returncode:raise RuntimeError('环境安装未完成，请检查安装日志和网络后重试。')
    print('Appium 环境已安装。Android SDK、Java、Flutter 和模拟器请按测试需求安装；iOS 仅支持 Mac + Xcode。')


if __name__=='__main__':configure()
