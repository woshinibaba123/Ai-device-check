import host_runtime
"""Avoid embedding optional Swift Testing libraries absent from the installed Xcode."""
from pathlib import Path
import subprocess

ROOT = host_runtime.root()

def apply():
    project=ROOT/'.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj/project.pbxproj'
    if not project.is_file(): return
    developer=Path(subprocess.check_output(['xcode-select','-p'],text=True).strip())
    lib=developer/'Platforms/iPhoneSimulator.platform/Developer/usr/lib/lib_TestingInterop.dylib'
    if lib.exists(): return
    old=project.read_text()
    lines=[]
    for line in old.splitlines(keepends=True):
        if 'WDA_XCTEST_EXCLUDED_2600 = ' in line and 'lib_TestingInterop.dylib' not in line:
            line=line.replace('libXCTestSwiftSupport.dylib"','libXCTestSwiftSupport.dylib lib_TestingInterop.dylib"')
        lines.append(line)
    new=''.join(lines)
    if new != old:
        backup=project.with_suffix('.pbxproj.devicecheck-backup')
        if not backup.exists(): backup.write_text(old)
        project.write_text(new)
        print('已适配本机 Xcode：跳过不存在的可选 Swift Testing 库。')

if __name__=='__main__': apply()
