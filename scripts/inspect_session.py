"""Read only sanitized labels and geometry from the tool's active Appium session."""
import sys,json,re,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import automation
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path):
 with opener.open('http://127.0.0.1:8200'+path,timeout=15) as r:return json.load(r)['value']
sessions=get('/sessions')
if not sessions:print('No active session');sys.exit()
sid=sessions[0]['id']
for n in automation.parse_ui(get('/session/'+sid+'/source')):
 if n['label'] or n['editable']:
  label='[输入内容已隐藏]' if n['editable'] or n['secure'] else re.sub(r'\S+@\S+','[账号已隐藏]',n['label'])
  print(json.dumps({'label':label,'editable':n['editable'],'secure':n['secure'],'clickable':n['clickable'],'bounds':n['bounds'],'kind':n['kind']},ensure_ascii=False))
