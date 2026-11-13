"""Source-derived navigation inventory. Static candidates are not coverage proof."""
import json
import re
from pathlib import Path


def control_labels(text, position):
    """Find labels on the enclosing control, never a preceding sibling."""
    masked=re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//[^\n]*|/\*.*?\*/''',
                  lambda m:' '*len(m[0]),text,flags=re.S)
    stack=[];ranges=[]
    for i,ch in enumerate(masked):
        if ch=='(':stack.append(i)
        elif ch==')' and stack:
            start=stack.pop()
            if start<position<i:ranges.append((start,i))
    for start,end in sorted(ranges,key=lambda pair:pair[1]-pair[0]):
        # Strip nested calls so another child's label cannot become this control's label.
        body=text[start+1:end];mask=masked[start+1:end];depth=0;direct=[]
        for ch,raw in zip(mask,body):
            if ch in '([{':depth+=1
            direct.append(raw if depth==0 else ' ')
            if ch in ')]}':depth-=1
        keys=re.findall(r'''\b(?:text|title|label):\s*['"]([^'"\n]+)['"]\.tr''',''.join(direct))
        if keys:return list(dict.fromkeys(keys))
        # A callback argument can be nested inside the control; do not cross a
        # complete list of sibling controls looking for an unrelated title.
        if re.search(r'\b(?:children|items)\s*:', ''.join(direct)):break
    return []


def navigation_label_keys(text, position):
    keys=control_labels(text,position)
    if keys:return keys
    # A control often delegates navigation to a local callback method.
    methods=list(re.finditer(r'^\s*(?:void|Future(?:<[^>]+>)?)\s+(\w+)\s*\([^\n]*\)\s*(?:async\s*)?\{',text,re.M))
    method=next((m for i,m in enumerate(methods) if m.end()<=position<(methods[i+1].start() if i+1<len(methods) else len(text))),None)
    if not method:return []
    candidates=[]
    for reference in re.finditer(r'\b'+re.escape(method[1])+r'\b',text):
        if reference.start()==method.start(1):continue
        found=control_labels(text,reference.start())
        if found:candidates.append(tuple(found))
    unique=set(candidates)
    return list(next(iter(unique))) if len(unique)==1 else []


def analyze(project):
    project=Path(project)
    routes={};pages={};entries=[];labels=set();translations={}
    for file in (project/'assets/i18n').glob('*.json'):
        try:
            data=json.loads(file.read_text())
            for key,value in data.items():
                if isinstance(value,str):translations.setdefault(key,set()).add(value)
        except (ValueError,OSError):continue
    dart=list((project/'lib').rglob('*.dart'))
    for file in dart:
        if file.name not in ('routers.dart','routes.dart'):continue
        text=file.read_text()
        routes.update(re.findall(r"static\s+const\s+(?:String\s+)?(\w+)\s*=\s*['\"]([^'\"]+)['\"]",text))
        for entry in re.finditer(r'GetPage\(\s*name:\s*(\w+)\s*,\s*page:\s*\(\)\s*=>\s*',text):
            expression=text[entry.end():]
            for _ in range(8):
                constructor=re.match(r'(?:const\s+)?(\w+)\(',expression)
                if not constructor:break
                if constructor[1] not in ('AutomationTarget','AutomationInstance'):
                    pages[entry[1]]=constructor[1];break
                child=re.search(r'\bchild:\s*',expression[constructor.end():])
                if not child:break
                expression=expression[constructor.end()+child.end():]
    for file in dart:
        text=file.read_text()
        # Only a nearby UI label is a candidate. Runtime route observation confirms navigation.
        for match in re.finditer(r'Get\.(?:toNamed|offNamed|offAllNamed)\(\s*Routers\.(\w+)',text):
            name=match.group(1)
            keys=navigation_label_keys(text,match.start())
            values=sorted({value for key in keys for value in translations.get(key,set())})
            labels.update(values)
            entries.append({'route':routes.get(name,name),'source':str(file.relative_to(project)),'line':text.count('\n',0,match.start())+1,'labels':values,'label_keys':keys,'mapping':'static_candidate'})
    # Root tabs do not push routes; recognize their source-defined localized labels.
    tabs=[]
    for file in dart:
        text=file.read_text()
        for key in re.findall(r"_clickMenuItem\(\s*\d+\s*,\s*['\"]([^'\"]+)['\"]\.tr",text):
            tabs.extend(translations.get(key,set()))
    reverse={}
    for key,values in translations.items():
        for value in values:reverse.setdefault(value.strip().casefold(),set()).add(key)
    label_keys={label:next(iter(keys)) for label,keys in reverse.items() if len(keys)==1}
    return {'routes':[{'name':name,'path':path,'page':pages.get(name,'')} for name,path in routes.items()], 'entries':entries,'entry_labels':sorted(labels),'tab_labels':sorted(set(tabs)), 'label_keys':label_keys,'method':'static_candidates_with_runtime_route_confirmation'}


def instrument(project):
    project=Path(project);file=project/'lib/main_config.dart';text=file.read_text()
    marker='navigatorObservers: [AppRouteObserver().routeObserver]'
    if text.count(marker)!=1:raise ValueError('源码导航结构已变化，无法添加路由观察器。')
    routes=analyze(project)['routes']
    allowed=json.dumps([r['path'] for r in routes],ensure_ascii=False)
    code="""import 'dart:io';
import 'dart:convert';
import 'package:flutter/widgets.dart';
class DeviceCheckRouteObserver extends NavigatorObserver {
  static const allowed = ALLOWED;
  static final observed = <String>{};
  static final events = <Map<String,dynamic>>[];
  static final run = DateTime.now().microsecondsSinceEpoch.toString();
  void save(Route<dynamic>? route, Route<dynamic>? previous) {
    final name = route?.settings.name;
    if (name == null || !allowed.contains(name)) return;
    try {
      observed.add(name);
      final started=DateTime.now().microsecondsSinceEpoch;
      File('${Directory.systemTemp.path}/devicecheck-route.json').writeAsStringSync(jsonEncode({'run':run,'route': name, 'observed': observed.toList(),'events':events}));
      WidgetsBinding.instance.addPostFrameCallback((_) {
        try {
          events.add({'from':allowed.contains(previous?.settings.name)?previous?.settings.name:null,'route':name,'route_started_us':started,'route_to_first_frame_ms':(DateTime.now().microsecondsSinceEpoch-started)/1000});
          if(events.length>300)events.removeAt(0);
          final file=File('${Directory.systemTemp.path}/devicecheck-route.json');
          final current=jsonDecode(file.readAsStringSync());current['events']=events;file.writeAsStringSync(jsonEncode(current));
        } catch (_) {}
      });
    } catch (_) {}
  }
  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) { save(route, previousRoute); }
  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) { save(previousRoute, route); }
  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) { save(newRoute, oldRoute); }
}
""".replace('ALLOWED',allowed)
    (project/'lib/devicecheck_route_observer.dart').write_text(code)
    file.write_text("import 'devicecheck_route_observer.dart';\n"+text.replace(marker,'navigatorObservers: [AppRouteObserver().routeObserver, DeviceCheckRouteObserver()]'))


class RouteReader:
    def __init__(self,platform,device,bundle,command,adb):
        if not re.fullmatch(r'[\w.\-]+',bundle or ''):raise ValueError('无法确定路由观察器的 App 包名')
        self.platform=platform;self.device=device;self.bundle=bundle;self.command=command;self.adb=adb;self.observed=set()
    def read(self):
        try:
            if self.platform=='Android':
                base='/data/user/0/'+self.bundle
                text='{}'
                for directory in ('code_cache','cache'):
                    result=self.command([self.adb,'-s',self.device,'shell','run-as',self.bundle,'cat',base+'/'+directory+'/devicecheck-route.json'])
                    if result['ok']:
                        text=result['output'];break
            else:
                result=self.command(['xcrun','simctl','get_app_container',self.device,self.bundle,'data'])
                text=(Path(result['output'])/'tmp/devicecheck-route.json').read_text() if result['ok'] else '{}'
            data=json.loads(text);route=data.get('route','')
            self.latest=data
            history=data.get('observed',[])
            if isinstance(history,list):self.observed.update(r for r in history if isinstance(r,str) and r.startswith('/'))
            if route:self.observed.add(route)
            return route
        except (OSError,ValueError):return ''


def coverage(plan,ready,reader,skipped,termination):
    history=getattr(reader,'observed',set())
    observed=set(ready)|(set(history) if isinstance(history,(list,tuple,set)) else set())
    protected={s['route'] for s in skipped if s.get('label')=='业务密码页' and s.get('route')}
    rows=[]
    startup={'/splash','/agreement','/loginConfig','/login','/login/staff','/fallback'}
    for route in plan.get('routes',[]):
        path=route['path']
        if path in protected:status='protected';reason='已到达，敏感输入未执行'
        elif path in ready:status='displayed';reason='已展示并采集页面；不代表业务测试通过'
        elif path in observed:status='observed';reason='已记录路由跳转；未完成页面控件核验'
        elif path=='/user/modifyPass' and any(s.get('semantic')=='modify_pass' for s in skipped):status='excluded';reason='修改密码入口已按敏感操作规则跳过，未执行密码修改'
        elif path in startup:status='startup_unobserved';reason='启动或登录前流程；本次未取得该路由记录'
        else:status='not_observed';reason='本次未观察到；入口、账号权限及测试数据条件尚未逐项验证'
        rows.append({**route,'status':status,'reason':reason})
    return {'route_count':len(rows),'visited_routes':sorted(observed),'displayed_routes':sorted(set(ready)-protected),
            'observed_only_routes':sorted(observed-set(ready)), 'route_details':rows,
            'unvisited_routes':[r for r in rows if r['status'] in ('not_observed','startup_unobserved')],
            'h5_note':'多个 H5 功能共用 /webview，不能用该路由数量衡量 H5 功能覆盖率',
            'termination':termination}
