"""Source-derived navigation inventory. Static candidates are not coverage proof."""
import json
import re
from pathlib import Path


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
        routes.update(re.findall(r"static\s+const\s+(\w+)\s*=\s*['\"]([^'\"]+)['\"]",text))
        pages.update(re.findall(r'GetPage\(\s*name:\s*(\w+)\s*,\s*page:\s*\(\)\s*=>\s*(?:const\s+)?(\w+)\(',text))
    for file in dart:
        text=file.read_text()
        # Only a nearby UI label is a candidate. Runtime route observation confirms navigation.
        for match in re.finditer(r'Get\.(?:toNamed|offNamed|offAllNamed)\(\s*Routers\.(\w+)',text):
            name=match.group(1)
            prefix=text[max(0,match.start()-1600):match.start()]
            keys=re.findall(r"(?:text|title|label):\s*['\"]([^'\"]+)['\"]\.tr",prefix)
            values=sorted(translations.get(keys[-1],set())) if keys else []
            labels.update(values)
            entries.append({'route':routes.get(name,name),'source':str(file.relative_to(project)),'line':text.count('\n',0,match.start())+1,'labels':values,'mapping':'static_candidate'})
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
  void save(Route<dynamic>? route) {
    final name = route?.settings.name;
    if (name == null || !allowed.contains(name)) return;
    try {
      observed.add(name);
      File('${Directory.systemTemp.path}/devicecheck-route.json').writeAsStringSync(jsonEncode({'route': name, 'observed': observed.toList()}));
    } catch (_) {}
  }
  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) { save(route); }
  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) { save(previousRoute); }
  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) { save(newRoute); }
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
                result=self.command([self.adb,'-s',self.device,'shell','run-as',self.bundle,'cat',base+'/code_cache/devicecheck-route.json'])
                text=result['output'] if result['ok'] else '{}'
            else:
                result=self.command(['xcrun','simctl','get_app_container',self.device,self.bundle,'data'])
                text=(Path(result['output'])/'tmp/devicecheck-route.json').read_text() if result['ok'] else '{}'
            data=json.loads(text);route=data.get('route','')
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
