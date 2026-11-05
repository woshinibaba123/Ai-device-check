"""Read local test progress without credential or request-body logging."""
import json, urllib.request
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('http://127.0.0.1:8765/api/jobs', timeout=10) as r: jobs=json.load(r)
print(json.dumps({'counts':{s:sum(j['status']==s for j in jobs) for s in ('running','queued','passed','review','blocked','failed','stopped')},'jobs':[{'id':j['id'],'label':j.get('label'),'status':j['status'],'logs':j.get('logs',[])[-5:] if j['status']=='running' else j.get('logs',[])[-1:],'screenshots':j.get('screenshots',[])[-3:],'exploration':{k:j.get('exploration',{}).get(k) for k in ('actions','termination')}} for j in jobs if j['status']!='queued']},ensure_ascii=False,indent=2))
