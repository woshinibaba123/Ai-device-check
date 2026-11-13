"""Run one authored module against the real local device service, preserving reports."""
import json,time,urllib.request,urllib.error,shutil,argparse,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/source-test-suite/auto-run';OUT.mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser();parser.add_argument('--module',required=True);parser.add_argument('--language',default='ja-JP');parser.add_argument('--reuse-build',action='store_true');parser.add_argument('--gpu',choices=['host','swiftshader'],default='host');parser.add_argument('--run-tag',default='');args=parser.parse_args()
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def api(path,body=None):
 req=urllib.request.Request('http://127.0.0.1:8765'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
 try:
  with opener.open(req,timeout=90) as r:return json.load(r)
 except urllib.error.HTTPError as e:
  detail=json.loads(e.read());raise RuntimeError(detail.get('error','HTTP '+str(e.code))) from None
def save(value):
 (OUT/'progress.tmp').write_text(json.dumps(value,ensure_ascii=False,indent=2));(OUT/'progress.tmp').replace(OUT/'progress.json')
 (OUT/'progress.md').write_text('# 五模块实际运行进度\n\n'+ '\n'.join(f'- {k}: {v}' for k,v in value.items() if k!='logs')+'\n\n'+'\n'.join(value.get('logs',[])))
existing=api('/api/jobs');existing=list(existing.values()) if isinstance(existing,dict) else existing
if any(x.get('status') in ('running','queued') for x in existing):raise SystemExit('现有任务仍在执行，未覆盖或中断')
cfg=json.loads((ROOT/'.runtime/overnight-20261104/pilot-config.json').read_text())['execution']
cfg.update(emulator_gpu=args.gpu,test_mode='manual',step_format='chinese',targets=[{'profile':{'id':'mi17','density':460,'image':'baseline'}}],source='/Users/apple/Documents/app-phone/app_phone',h5_source=str(ROOT/'.runtime/source-snapshots/portal-tele-270-5eedcbfaa10c'),entrypoint='lib/main_eng.dart')
if args.reuse_build:
 build=OUT/'verified-build'
 if not (build/'app-debug.apk').is_file():raise SystemExit('本轮测试构建不存在')
 metadata=json.loads((build/'build-metadata.json').read_text())
 with zipfile.ZipFile(build/'app-debug.apk') as z:
  if metadata['login_probe'].encode() not in z.read('assets/flutter_assets/kernel_blob.bin'):
   raise SystemExit('缓存APK与登录观察器不一致；需要重新构建')
 cache=ROOT/'.runtime/flow-replay'
 backup=OUT/'previous-flow-replay'
 if cache.exists() and not backup.exists():shutil.copytree(cache,backup)
 cache.mkdir(exist_ok=True)
 shutil.copyfile(build/'app-debug.apk',cache/'app-debug.apk')
 shutil.copyfile(build/'build-metadata.json',cache/'build-metadata.json')
 cfg.update(reuse_test_build=True,business_source=cfg['source'])
login=cfg['login'];login.pop('password',None);login['use_saved_password']=True
if not api('/api/login/credentials',{'operation':'status','account':login['account']})['saved']:raise SystemExit('测试账号未保存密码，未开始任务')
selected=[x for x in cfg['languages']['selected'] if x['code']==args.language]
if not selected:raise SystemExit('未找到目标语言')
cfg['languages']={'enabled':True,'selected':selected}
if args.module=='05' and not args.run_tag:
 for report in OUT.glob('05-*/*/report.json'):
  prior=json.loads(report.read_text())
  if any(r.get('api',{}).get('path')=='/api/devops/aftersale/work/order' and r.get('api',{}).get('code')==610000 for r in prior.get('custom_step_results',[])):
   raise SystemExit('已有报修提交成功证据；需提供明确run-tag才能进行新的提交复测')
textfile=next((ROOT/'output/source-test-suite/可粘贴步骤').glob(args.module+'-*.txt'))
cfg['business_text']=textfile.read_text();cfg['steps']=[]
if args.run_tag and args.module=='05':cfg['business_text']=cfg['business_text'].replace('自动化测试报修，请忽略，无真实设备故障','自动化测试报修，请忽略，无真实设备故障；'+args.run_tag)
# /api/batch clears reports: preserve old reports first.
backup=OUT/('preserved-'+time.strftime('%Y%m%d-%H%M%S'))
if (ROOT/'reports').exists():shutil.copytree(ROOT/'reports',backup)
state={'module':textfile.stem,'language':args.language,'phase':'submitting','status':'running','started':time.strftime('%Y-%m-%d %H:%M:%S'),'logs':[]};save(state)
for attempt in range(20):
 try:
  result=api('/api/batch',cfg);break
 except RuntimeError as error:
  if '上一批次正在收尾清理' not in str(error):raise
  if attempt==19:raise
  time.sleep(2)
state.update(batch=result['id'],phase='device_execution');save(state);print('STARTED '+json.dumps({k:state[k] for k in ('module','language','batch')},ensure_ascii=False),flush=True)
last=None
cached=False
while True:
 batch=api('/api/batches/'+result['id']);jobs=batch['jobs']
 if not cached:
  for j in jobs:
   if not j.get('artifact'):continue
   artifact=Path(j['artifact'])
   staged=ROOT/'.runtime'/('login-source-'+j['id'])
   if artifact.is_file() and staged.is_dir():
    probe=[]
    for dart in (staged/'lib').rglob('*.dart'):
     probe+=re.findall(r'devicecheck-login-[a-f0-9]{32}\.json',dart.read_text(errors='replace'))
    if probe:
     with zipfile.ZipFile(artifact) as archive:
      if probe[0].encode() not in archive.read('assets/flutter_assets/kernel_blob.bin'):continue
     build=OUT/'verified-build';build.mkdir(exist_ok=True)
     shutil.copyfile(artifact,build/'app-debug.apk')
     (build/'build-metadata.json').write_text(json.dumps({'entrypoint':cfg['entrypoint'],'login_probe':probe[0],'source_plan':{},'source':cfg['source'],'captured_from':j['id']}))
     cached=True
 state['jobs']=[{'id':j['id'],'status':j['status'],'label':j.get('label')} for j in jobs]
 state['logs']=[line for j in jobs for line in j.get('logs',[])[-5:]];state['updated']=time.strftime('%Y-%m-%d %H:%M:%S');save(state)
 current=[(j['id'],j['status'],j.get('logs',[])[-1:]) for j in jobs]
 if current!=last:print(json.dumps(current,ensure_ascii=False),flush=True);last=current
 if all(j['status'] not in ('queued','running') for j in jobs):
  # Wait for the report and resource cleanup, not just the in-memory status flag.
  if all((ROOT/'reports'/j['id']/'report.json').exists() for j in jobs):break
 time.sleep(3)
folder=OUT/(textfile.stem+'-'+args.language+'-'+time.strftime('%Y%m%d-%H%M%S'));folder.mkdir()
for j in jobs:shutil.copytree(ROOT/'reports'/j['id'],folder/j['id'])
state.update(status='passed' if all(j['status']=='passed' for j in jobs) else 'needs_repair',phase='finished',report=str(folder));save(state)
(folder/'summary.json').write_text(json.dumps(state,ensure_ascii=False,indent=2));print('FINISHED '+json.dumps({k:state[k] for k in ('module','language','status','report')},ensure_ascii=False),flush=True)
