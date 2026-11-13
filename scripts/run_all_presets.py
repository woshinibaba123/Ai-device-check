"""Sequential, resumable real-device suite. The agent reviews and repairs results."""
import sys,json,time,re,urllib.request,urllib.error,subprocess,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'output/full-device-suite';OUT.mkdir(parents=True,exist_ok=True)
STATE=OUT/'progress.json';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
DEVICE='3163925638000P3';ADB=str(Path.home()/'Library/Android/sdk/platform-tools/adb')
def api(path,body=None):
 req=urllib.request.Request('http://127.0.0.1:8765'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
 with opener.open(req,timeout=30) as r:return json.load(r)
def write(state):
 temp=STATE.with_suffix('.tmp');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2));temp.replace(STATE)
def stalled(item,job,now):
 count=len(job.get('ai_operator',{}).get('steps',[]))
 if count!=item.get('progress_step_count'):
  item.update(progress_step_count=count,last_progress_at=now)
 return now-item.get('last_progress_at',item.get('launched',now))>1500
def flows():
 all_flows=api('/api/preset-flows')
 selected=[f for f in all_flows if f.get('scope')=='business' or f['id']=='call-cancel']
 clean=next(f for f in all_flows if f['id']=='clean-robot');clean=dict(clean)
 html=(ROOT/'index.html').read_text();m=re.search(r'<textarea id="cleanRobotDraft"[^>]*>(.*?)</textarea>',html,re.S)
 if m:
  clean['steps']=[m.group(1)]
  clean['readonly']=False  # Extended workflow includes rename and saved forms.
 return [clean]+selected

def payload(flow,fresh=False):
 stamp=time.strftime('%Y-%m-%d %H:%M');suffix=time.strftime('%m%d%H%M%S')
 values={p['key']:p.get('default','') for p in flow.get('parameters',[])}
 defaults={'robot':'当前门店实际设备列表中的第一台可用测试设备','occurred_at':stamp,'problem_type':'当前设备第一个可用类型','contact_method':'13800138000','description':'自动化测试报修_'+suffix,'contact':'测试人员','attachment':'无'}
 for k in values:
  if not values[k]:values[k]=defaults.get(k,'测试_'+suffix)
 values.update({'test_name':'巡测_'+suffix,'description':values.get('description') or '自动化测试数据_'+suffix,
                'contact':values.get('contact') or '测试人员','contact_method':values.get('contact_method') or '13800138000',
                'test_phone':'13800138000','test_email':'devicecheck'+suffix+'@example.com','test_address':'上海市浦东新区测试地址',
                'test_number':'1','test_note':'自动化回归_'+suffix,'test_time':stamp})
 stable_path=OUT/flow['id']/'generated-data.json';stable_path.parent.mkdir(parents=True,exist_ok=True)
 if stable_path.exists() and not fresh:values.update(json.loads(stable_path.read_text()))
 else:
  import ai_operator
  values=ai_operator.goal_input_data('\n'.join(flow['steps']),values)
  stable_path.write_text(json.dumps(values,ensure_ascii=False,indent=2))
 goal='\n'.join(flow['steps']) if any(re.search(r'(?m)^\d+[.、]',step) for step in flow['steps']) else '\n'.join(str(i+1)+'. '+step for i,step in enumerate(flow['steps']))
 if flow['id']=='repair-full':
  goal=re.sub(r'选择编码为 \{\{robot\}\} 的测试设备并核对门店归属；不存在则记录受阻，不替换为其他设备。',
              '打开机器人下拉，从当前门店实际返回的设备中选择第一台可用测试设备，记录实际编码并核对门店归属；无设备时记录本项及依赖项受阻，继续独立字段。',goal)
 goal=re.sub(r'\{\{(\w+)\}\}',lambda m:values.get(m[1],'自动识别实际可用值'),goal)
 goal+='\n从当前实际页面继续，若已在本模块无需重走入口；遇到其他模块未提交表单先返回放弃草稿，不代为补交。结束返回App首页。每个分支分别记录证据；缺权限、测试账号、数据时记录受阻并继续独立项，不能虚构通过。当前为用户授权的测试环境，表单数据自动生成并填写保存、完成或提交，记录接口参数和返回结果。设备、订单、点位等引用对象必须从实际页面选择，不虚构存在。账号改密/换绑使用测试数据，必须保存原账号恢复方式和当前登录状态；无法恢复时记录前置受阻，不锁死整套测试。退款仅对测试环境中本次可明确识别的测试订单执行，不猜测订单。'
 review_notes=OUT/flow['id']/'review-notes.txt'
 if review_notes.exists():goal+='\n复测说明：'+review_notes.read_text()
 if flow.get('readonly'):goal+='\n本模块只读检查；不执行本模块未描述的业务修改。'
 cfg={'goal':goal,'preset_id':flow['id'],'form_submit':not flow.get('readonly',False),'data':{k:v for k,v in values.items() if k not in ('robot','problem_type','attachment')},'remember':True,'fast_mode':True,'visual_only':True,'recover_start':True,'midscene_first':True,'share_page':True,'midscene_model':'glm-5.3-flash','model':'glm-5.3-flash'}
 resume=OUT/flow['id']/'resume.json'
 if resume.exists():
  previous=json.loads(resume.read_text());cfg['_resume_history']=previous.get('steps',[]);cfg['_resume_coverage']=previous.get('coverage',[])
 return {'targets':[{'platform':'Android','device':DEVICE,'name':flow['name']}],'test_mode':'ai_live','execution_mode':'installed','bundle':'com.keenon.mobile','login':{'enabled':False},'screenshot_policy':'anomalies_only','midscene_model':'glm-5.3-flash','ai_live':cfg}

def main():
 state=json.loads(STATE.read_text()) if STATE.exists() else {'created':time.strftime('%Y-%m-%d %H:%M:%S'),'items':[{'id':f['id'],'name':f['name'],'state':'pending'} for f in flows()]}
 write(state);catalog={f['id']:f for f in flows()}
 subprocess.run([ADB,'-s',DEVICE,'shell','svc','power','stayon','true'],capture_output=True,timeout=15)
 last_wake=0
 while True:
  if (OUT/'pause').exists():state['status']='paused_for_review';write(state);return
  item=next((i for i in state['items'] if i['state'] in ('pending','running','quota_wait')),None)
  if item is None:state['status']='all_attempted_needs_review';write(state);return
  if time.time()-last_wake>300:
   subprocess.run([ADB,'-s',DEVICE,'shell','input','keyevent','KEYCODE_WAKEUP'],capture_output=True,timeout=15);last_wake=time.time()
  try:
   jobs=api('/api/batches/'+item['batch'])['jobs'] if item['state']=='running' and item.get('batch') else api('/api/jobs')
   active=[j for j in jobs if j['status'] in ('running','queued')]
   if item['state']=='quota_wait':
    if time.time()<item.get('retry_at',0):time.sleep(20);continue
    item['state']='pending'
   if item['state']=='pending':
    if active:time.sleep(10);continue
    response=api('/api/batch',payload(catalog[item['id']],fresh=not item.get('launched') and not item.get('attempts')))
    for field in ('termination','reason','last_step','last_log','progress_step_count','last_progress_at','timeout_requested'):item.pop(field,None)
    item.update(state='running',batch=response['id'],launched=time.time());state['status']='running';write(state)
    print('START',item['id'],response['id'],flush=True)
   jobs=api('/api/batches/'+item['batch'])['jobs'];job=next((j for j in jobs if j.get('batch')==item.get('batch')),None)
   if job:
    if job['status']=='running' and stalled(item,job,time.time()) and not item.get('timeout_requested'):
     api('/api/stop',{'id':job['id']});item['timeout_requested']=True;state['status']='module_stalled_needs_review'
    item['job']=job['id'];a=job.get('ai_operator',{});item['last_step']=a.get('steps',[])[-1:] ;item['last_log']=job.get('logs',[])[-1:];write(state)
    if job['status'] not in ('running','queued'):
     report=ROOT/'reports'/job['id']/'report.json'
     if not report.exists():time.sleep(3);continue
     saved=OUT/item['id'];saved.mkdir(exist_ok=True)
     (saved/(job['id']+'.json')).write_text(json.dumps(job,ensure_ascii=False,indent=2))
     reason=a.get('termination_detail','');logs='\n'.join(job.get('logs',[])[-12:])
     quota=bool(re.search(r'quota|额度|余额不足|credit.*exhaust|rate.limit|429',reason+'\n'+logs,re.I))
     if quota:
      (saved/'resume.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
      item.update(state='quota_wait',retry_at=time.time()+900,reason=reason)
      state['status']='waiting_for_quota'

     else:
      complete=a.get('termination')=='goal_complete' and all(r['status']=='observed' for r in a.get('coverage',[]))
      concluded=a.get('termination')=='needs_review' and a.get('coverage') and all(r['status'] in ('observed','blocked') for r in a['coverage'])
      item.update(state='passed' if complete else 'blocked' if concluded else 'needs_review',termination=a.get('termination'),reason=reason)
      item['blocked_checks']=[{'id':r['id'],'requirement':r['requirement'],'evidence':r.get('evidence','')} for r in a.get('coverage',[]) if r['status']=='blocked']

     write(state);print('END',item['id'],item['state'],reason[:180],flush=True)
     # Stop for agent review before proceeding after an executor/script failure.
     if item['state']=='needs_review':state['status']='needs_agent_review';write(state);return
   time.sleep(5)
  except urllib.error.HTTPError as error:
   try:detail=json.load(error).get('error','HTTP '+str(error.code))
   except Exception:detail='HTTP '+str(error.code)
   if error.code==409:
    state['last_log']='等待上一批次资源清理完成';write(state);time.sleep(5);continue
   state.update(status='needs_agent_review',request_error=detail);write(state)
   print('REQUEST_FAILED',detail[:400],flush=True);return
  except (OSError,ValueError,urllib.error.URLError) as error:
   state['connection_error']=type(error).__name__;write(state);time.sleep(15)
if __name__=='__main__':main()
