# Build on the target OS; do not bundle SDKs, credentials, source clones or reports.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files
base=Path(SPECPATH).parent
assets=[(str(base/name),'.') for name in ('index.html','parsed_cases.js','catalog.json','model_credit_reference.json')]
assets+=collect_data_files('webview')
a=Analysis([str(base/'desktop_main.py')],pathex=[str(base)],datas=assets,
    hiddenimports=['webview','pdf_report','windows_credentials','desktop.setup_runtime'],
    excludes=['PyQt5','PyQt6','PySide2','PySide6','gi','webview.platforms.gtk','webview.platforms.qt'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='DeviceCheck',debug=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='DeviceCheck')
if sys.platform=='darwin':
    app=BUNDLE(coll,name='巡测.app',bundle_identifier='com.devicecheck.desktop',
      info_plist={'CFBundleName':'巡测','CFBundleDisplayName':'巡测','CFBundleShortVersionString':'1.1.0','CFBundleVersion':'110',
        'NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},
        'NSHumanReadableCopyright':'DeviceCheck desktop'})
