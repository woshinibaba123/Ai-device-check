"""Restart only this project's idle local HTTP service."""
import os,signal,subprocess,time,json,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('http://127.0.0.1:8765/api/jobs',timeout=5) as r:jobs=json.load(r)
if any(j['status'] in ('queued','running') for j in jobs):raise SystemExit('Active jobs: refusing restart')
try:
 with opener.open('http://127.0.0.1:8765/api/ai/status',timeout=20) as r:ai=json.load(r)
 if ai.get('busy'):raise SystemExit('AI generation active: refusing restart')
except urllib.error.HTTPError:pass
pids=subprocess.check_output(['/usr/sbin/lsof','-t','-iTCP:8765','-sTCP:LISTEN'],text=True).split()
for value in pids:
 pid=int(value)
 cwd=subprocess.check_output(['/usr/sbin/lsof','-a','-p',value,'-d','cwd','-Fn'],text=True)
 if 'n'+str(root) not in cwd.splitlines():raise SystemExit('Unexpected process cwd')
 os.kill(pid,signal.SIGTERM)
for _ in range(40):
 if subprocess.run(['/usr/sbin/lsof','-t','-iTCP:8765','-sTCP:LISTEN'],capture_output=True).returncode:break
 time.sleep(.25)
with (root/'server.log').open('ab') as log:
 p=subprocess.Popen(['/bin/zsh',str(root/'启动工具.command')],cwd=root,stdout=log,stderr=log,start_new_session=True)
print('Started wrapper',p.pid)
