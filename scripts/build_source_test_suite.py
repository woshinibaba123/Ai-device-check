"""Build a source-evidenced modular test catalogue; never claims runtime coverage."""
import json,re,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import flow_planner,semantic_steps,source_navigation
ROOT=Path(__file__).resolve().parents[1]
APP=Path('/Users/apple/Documents/app-phone/app_phone')
H5=ROOT/'.runtime/source-snapshots/portal-tele-270-5eedcbfaa10c'
OUT=ROOT/'output/source-test-suite'
OUT.mkdir(parents=True,exist_ok=True)
h5=json.loads((OUT/'h5-source-index.json').read_text())
index=flow_planner.source_index(str(APP));zh=json.loads((APP/'assets/i18n/zh.json').read_text())
modules={
 'activation':'机器人激活','appPermission':'应用权限说明','cleanTaskReport':'清洁任务报告','createStore':'创建门店',
 'datav':'数据可视化','downloadAPP':'App下载','follow':'我的关注','guideSteps':'部署引导',
 'mapPreview':'地图预览','medical-vending':'医疗售货机器人','ossUploader':'文件上传桥接',
 'personalInformation':'个人信息清单','pocCamera':'相机取景','privacyAgreement':'隐私协议',
 'privacySummary':'隐私摘要','report':'运行报告与门店业务','serviceAgreement':'用户协议',
 'study':'旧版学习中心','studyVideo':'学习视频','survey':'勘察工具','thirdPartyInformation':'第三方信息清单',
 'warranty':'保修与延保','weekReport':'周报','workOrder':'工单入口'}
casebook=[]
def safe(s):return str(s).replace('|','\\|').replace('\n',' ').replace('\r',' ')[:350]
def link(path,line=1):return f'[{Path(path).name}:{line}]({path}:{line})'
def add_case(module,title,steps,expected,source,status='需运行确认',data='有权限的测试账号、测试门店和有效机器人'):
 c={'id':f'TC-{len(casebook)+1:05d}','module':module,'title':title,'precondition':data,'steps':steps,'expected':expected,'source':source,'status':status,'runtime_verified':False}
 casebook.append(c);return c
# Native pages and every UI callback are separately indexed, including non-route widgets.
native=[]
for file in sorted((APP/'lib/widgets').rglob('*.dart')):
 text=flow_planner.without_comments(file.read_text(errors='replace'))
 callbacks=[]
 for m in re.finditer(r'\b(onTap|onPressed|onChanged|onSubmitted|onLongPress|onWillPop|onPopInvokedWithResult)\s*:',text):
  prefix=text[max(0,m.start()-700):m.start()]
  keys=list(dict.fromkeys(re.findall(r"['\"]([^'\"\n]+)['\"]\.tr",prefix)))[-5:]
  callbacks.append({'event':m[1],'line':text.count('\n',0,m.start())+1,'nearby_labels':[{'key':key,'zh':zh.get(key,'')} for key in keys], 'binding':text[m.end():m.end()+240].strip().split('\n\n')[0]})
 native.append({'source':str(file.relative_to(APP)),'module':file.relative_to(APP/'lib/widgets').parts[0], 'callbacks':callbacks,'routes':[p['path'] for p in index['pages'] if p['source']==str(file.relative_to(APP)) and p.get('kind')!='h5_entry']})
(OUT/'flutter-source-index.json').write_text(json.dumps({'project':str(APP),'navigation':index['navigation'],'pages':index['pages'],'widgets':native},ensure_ascii=False,indent=2))
# Source-based manual cases per native route, not executable locator promises.
for page in index['pages']:
 if page.get('kind')=='h5_entry':continue
 name='Flutter/'+page['source'].split('/')[2]
 title=' / '.join(page.get('title_labels',[])[:2]) or page['page']
 entry=page.get('entry_path') or []
 steps=([f'按源码候选入口依次打开：{" → ".join(entry)}。'] if entry else [f'准备对应角色及业务数据，从 App 正常界面进入 {title}；入口尚需运行确认，禁止通过绕过登录或权限的直达方式替代。'])
 steps += [f'确认实际路由为 {page["path"]}，检查标题、加载状态和空数据/无权限分支。','检查当前语言下的字段、按钮、长文本换行及键盘遮挡；返回并检查前一页状态。']
 expected=['目标页面与源码路由一致；有数据/空数据/权限不足分别记录，不能把入口不可见判为通过。','返回行为与源码拦截一致；若源码会在返回时保存，核对保存接口及结果；否则不得额外写入、退出账号或触发设备任务。']
 add_case(name,title,steps,expected,[{'path':str(APP/page['source']),'line':1}],data='角色与权限匹配；涉及硬件时使用专用测试设备；登录/凭据模块需专用测试账号')
# H5 controls: one case for each discovered control. Component forwarding is explicitly marked.
for page in h5['pages']:
 module='H5/'+page['module'];source=str(H5/page['source'])
 if not page['controls']:
  add_case(module,Path(source).stem+' 页面展示',[f'通过所属模块的正常入口打开 {page["source"]}。','检查内容、语言、加载、空态及返回。'],['静态内容与源码一致；只有实际展示后才能记录通过。'],[{'path':source,'line':1}])
 for control in page['controls']:
  labels=[x['zh'] or x['key'] for x in control['labels']]
  title=' / '.join(labels[:3]) or control['text'] or ','.join(control['models']) or control['tag']
  events=control['events'];bindings=[x['handler'] for x in events]
  entry=f'通过正常页面入口打开所属模块；目标路由候选：{", ".join(page["routes"]) or "该文件为子组件，先打开引用它的父页面"}。'
  preconditions=[f'{x["kind"]}: {x["expression"]}' for x in control['conditions']]
  steps=[entry]
  if preconditions:steps.append('满足源码控件显示条件：'+'；'.join(preconditions)+'。')
  if control['models']:
   if re.search(r'popup|sheet|dialog|checkbox|switch',control['tag'],re.I):
    steps.append('打开、关闭或切换该控件，分别检查初始状态和操作后状态。')
   else:steps.append('分别输入/选择有效测试值、清空值及边界值；检查显示、回读、校验提示和关联字段。')
  if events:steps.append('逐一通过界面触发事件：'+'；'.join(x['event']+' → '+x['handler'] for x in events)+'。生命周期/父子组件事件由正常界面动作间接触发，不直接调用方法。')
  matched=[m for m in page['handlers'] if any(re.match(r'^'+re.escape(m['name'])+r'(?:\b|\()',b) for b in bindings)]
  effects=[effect['expression'] for m in matched for effect in m['effects']]
  expected=['事件或字段模型与源码绑定一致；数据为空、权限不足或异步失败时有明确结果，不凭截图判业务成功。']
  if effects:expected.append('核对源码处理分支（表达式为静态证据，非已执行结果）：'+'；'.join(effects[:5]))
  if control['models']:expected.append('字段模型：'+', '.join(control['models'])+'；输入后回读实际值，选择后核对选项和关联字段。')
  if any(re.search(r'submit|save|delete|remove|dispatch|start|pay|bind|send',b,re.I) for b in bindings):
   status='需测试数据、写接口断言及运行适配；未执行'
   steps.append('写操作前核对测试对象；提交后核对本次接口业务码及服务端结果；清理测试数据并保留证据。')
  else:status='源码候选；需运行定位确认'
  add_case(module,title,steps,expected,[{'path':source,'line':control['line']}],status=status)
# Native callback ledger covers direct-push / embedded / non-registered screens.
for widget in native:
 for c in widget['callbacks']:
  labels=[v['zh'] or v['key'] for v in c['nearby_labels']]
  add_case('Flutter/'+widget['module'],'控件：'+(' / '.join(labels[-2:]) or c['event']),
   [f'通过 {widget["source"]} 的父页面正常进入；核对候选路由 {", ".join(widget["routes"]) or "嵌入组件/直接构造页面，无独立命名路由"}。',
    '运行时用控件树确认目标；附近文案只是候选，存在多个同名控件时停止。',f'触发 {c["event"]}，核对绑定处理分支和返回行为；有保存、解绑、设备动作时单独准备数据和结果断言。'],
   ['实际目标与源码绑定一致；相关回调应通过界面触发，不能用直接调用回调替代测试。'],[{'path':str(APP/widget['source']),'line':c['line']}],status='源码候选；需运行定位确认')
# All discovered condition branches retained as audit targets, rather than fabricated assertions.
branches=[{'source':str(H5/p['source']),'module':p['module'],**c,'status':'待设计业务数据并运行覆盖'} for p in h5['pages'] for c in p['conditions']]
(OUT/'cases.json').write_text(json.dumps(casebook,ensure_ascii=False,indent=2))
(OUT/'branch-checklist.json').write_text(json.dumps(branches,ensure_ascii=False,indent=2))
# Module files contain concrete per-control cases and line-specific source evidence.
for module in sorted({c['module'] for c in casebook}):
 platform,group=module.split('/',1);folder=OUT/platform;folder.mkdir(exist_ok=True)
 name=modules.get(group,group) if platform=='H5' else group
 lines=[f'# {module} · {name}','', '本文件是源码驱动的测试设计，未执行项不代表通过。控件、数据和权限必须运行确认。','']
 if platform=='H5':
  routes=[r for r in h5['routes'] if r['source'].startswith('src/pages/'+group+'/')]
  lines+=['## 路由清单','', '| 路由 | 页面文件 / 重定向 | 来源 |','|---|---|---|']
  for r in routes:lines.append(f'| {safe(r["path"])} | {safe(r["component"] or r["redirect"] or "需运行确认")} | {link(H5/r["source"],r["line"])} |')
  lines+=['']
 for c in [c for c in casebook if c['module']==module]:
  lines += [f'## {c["id"]} {safe(c["title"])}','',f'状态：{c["status"]}。',f'前置：{c["precondition"]}。','']
  lines += [f'{i}. {step}' for i,step in enumerate(c['steps'],1)]
  lines += ['', '预期：']+['- '+e for e in c['expected']]+['','源码：'+'，'.join(link(s['path'],s['line']) for s in c['source']),'']
 (folder/(group+'.md')).write_text('\n'.join(lines))
# Independently runnable business-step blocks; all compile through the real parser.
runnable={
 '01-基础导航':'自动登录，进入首页\n截图\n点击底部“消息”\n确认消息页面打开\n截图\n回到首页\n点击底部“我的”\n确认我的页面打开\n截图\n回到首页\n确认首页\n',
 '02-附近门店':'自动登录，进入首页\n点击“附近门店”\n确认附近门店页面打开\n截图\n点击“列表”\n确认附近门店列表页面打开\n截图\n点击“地图”\n确认附近门店地图页面打开\n截图\n返回\n确认首页\n',
 '03-学习中心':'自动登录，进入首页\n点击“学习中心”\n确认学习中心页面打开\n截图\n返回\n确认首页\n',
 '04-通用设置与关于':'自动登录，进入首页\n点击底部“我的”\n确认我的页面打开\n点击“通用设置”\n确认通用设置页面打开\n截图\n返回\n点击“关于”\n确认关于页面打开\n截图\n返回\n回到首页\n确认首页\n',
 '05-报修填写及真实提交':'自动登录，进入首页\n点击“报修”\n等待报修表单加载完成\n截图\n门店选择“乘梯测试门店---cy”\n机器人选择第一台\n问题类型选择第一个可用选项\n问题描述填写“自动化测试报修，请忽略，无真实设备故障”\n联系人填写“自动化测试人员”\n联系方式填写“devicecheck@example.com”\n勾选用户协议\n截图\n点击“提交”\n检查是否提交成功\n确认回到首页\n截图\n'}
folder=OUT/'可粘贴步骤';folder.mkdir(exist_ok=True)
for name,text in runnable.items():
 steps=semantic_steps.compile_text(text)
 (folder/(name+'.txt')).write_text(text)
 (folder/(name+'.json')).write_text(json.dumps({'name':name,'status':'语法校验通过，尚未完成当前版本端到端运行','source':str(APP),'h5_source':str(H5),'requires':'账号权限、有效测试业务数据；报修模块会真实创建工单','steps':steps},ensure_ascii=False,indent=2))
# Integrity includes every widget, H5 page, route and interaction, without a completeness claim for business behavior.
manifest={'app_source':str(APP),'h5_source':str(H5),'h5_revision':(H5/'SOURCE-REVISION.txt').read_text().strip(),'counts':{'flutter_widget_files':len(native),'flutter_registered_routes':len(index['navigation']['routes']),'flutter_page_records':len(index['pages']),'h5_modules':len(modules),'h5_vue_files':len(h5['pages']),'h5_route_declarations':len(h5['routes']),'h5_routes':len({(r['source'].split('/')[2],r['path']) for r in h5['routes']}),'h5_interactive_controls':sum(len(p['controls']) for p in h5['pages']),'h5_condition_branches':len(branches),'source_designed_cases':len(casebook),'compiled_business_modules':len(runnable)},'parse_errors':h5['errors'],'runtime_coverage':'未执行；这些计数是静态清单，不是全部业务已覆盖或通过的证明'}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps(manifest,ensure_ascii=False,indent=2))
