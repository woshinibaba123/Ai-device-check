"""Compile all observers in an isolated APFS source clone, never the user's checkout."""
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
import flow_planner,http_probe,source_navigation,login_probe
source=Path('/Users/apple/Documents/app-phone/app_phone')
stage=root/'.runtime'/('http-verify-'+uuid.uuid4().hex[:12])
log=root/'.runtime/http-observer-build.log'
try:
    subprocess.run(['/bin/cp','-cR',str(source),str(stage)],check=True)
    index=flow_planner.source_index(stage)
    login_name=login_probe.instrument(stage)
    source_navigation.instrument(stage)
    manifest=http_probe.instrument(stage,index,['data.count','data.total','data.status'])
    env=os.environ.copy();env['ANDROID_HOME']=str(Path.home()/'Library/Android/sdk')
    env['JAVA_HOME']=subprocess.check_output(['/usr/libexec/java_home','-v','17'],text=True).strip()
    with log.open('w') as output:
        result=subprocess.run([str(Path.home()/'fvm/default/bin/flutter'),'build','apk','-t','lib/main_eng.dart','--debug'],cwd=stage,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=1800)
    if result.returncode:
        print(log.read_text(errors='replace')[-4000:]);raise SystemExit(result.returncode)
    cache=root/'.runtime/flow-replay';cache.mkdir(exist_ok=True)
    shutil.copy2(stage/'build/app/outputs/flutter-apk/app-debug.apk',cache/'app-debug.apk.new')
    (cache/'app-debug.apk.new').replace(cache/'app-debug.apk')
    index['project']=str(source)
    (cache/'build-metadata.json').write_text(json.dumps({'entrypoint':'lib/main_eng.dart','login_probe':login_name,'source_plan':index['navigation'],'route_tracking':True,'http_manifest':manifest,'flow_index':index},ensure_ascii=False))
    print('eng 测试包编译成功：登录、路由和 Dio 接口观察器已一起验证。')
finally:
    if stage.exists():shutil.rmtree(stage)
