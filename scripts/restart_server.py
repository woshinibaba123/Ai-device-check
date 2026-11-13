"""Restart only this project's idle local HTTP service."""
import os,signal,subprocess,time,json,urllib.request,argparse
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--replace-generation');args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('http://127.0.0.1:8765/api/jobs',timeout=5) as r:jobs=json.load(r)
if any(j['status'] in ('queued','running') for j in jobs):raise SystemExit('Active jobs: refusing restart')
try:
 with opener.open('http://127.0.0.1:8765/api/ai/status',timeout=20) as r:ai=json.load(r)
 if ai.get('busy'):
  if not args.replace_generation or ai.get('active_generation')!=args.replace_generation:raise SystemExit('AI generation active: refusing restart')
  with opener.open('http://127.0.0.1:8765/api/ai/generations/'+args.replace_generation,timeout=10) as r:snapshot=json.load(r)
  folder=root/'.runtime/restart-backups';folder.mkdir(parents=True,exist_ok=True)
  (folder/('generation-'+args.replace_generation+'.json')).write_text(json.dumps({k:snapshot.get(k) for k in ('id','status','stage','label','elapsed')},ensure_ascii=False,indent=2))
except urllib.error.HTTPError:pass
pids=subprocess.check_output(['/usr/sbin/lsof','-t','-iTCP:8765','-sTCP:LISTEN'],text=True).split()
for value in pids:
 pid=int(value)
 cwd=subprocess.check_output(['/usr/sbin/lsof','-a','-p',value,'-d','cwd','-Fn'],text=True)
 if 'n'+str(root) not in cwd.splitlines():raise SystemExit('Unexpected process cwd')
 children=set()
 if args.replace_generation:
  table=subprocess.check_output(['/bin/ps','-axo','pid=,ppid='],text=True)
  pairs=[tuple(map(int,line.split())) for line in table.splitlines() if len(line.split())==2]
  parents={pid}
  while True:
   added={child for child,parent in pairs if parent in parents}-parents
   if not added:break
   children.update(added);parents.update(added)
 os.kill(pid,signal.SIGTERM)
 for child in sorted(children,reverse=True):
  try:os.kill(child,signal.SIGTERM)
  except ProcessLookupError:pass
for _ in range(40):
 if subprocess.run(['/usr/sbin/lsof','-t','-iTCP:8765','-sTCP:LISTEN'],capture_output=True).returncode:break
 time.sleep(.25)
with (root/'server.log').open('ab') as log:
 p=subprocess.Popen(['/bin/zsh',str(root/'启动工具.command')],cwd=root,stdout=log,stderr=log,start_new_session=True)
print('Started wrapper',p.pid)
