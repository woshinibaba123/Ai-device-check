"""Add WebView lifecycle/JS telemetry only to the isolated Flutter test copy."""
import json
import re
import time
import uuid
from pathlib import Path


def instrument(project):
    project=Path(project)
    param=project/'lib/widgets/webview/web_param.dart'
    original=param.read_text()
    markers=['  final WebViewController controller = WebViewController.fromPlatformCreationParams(params);','onPageStarted: (String url) {},','onPageFinished: (String url) {','    ..setJavaScriptMode(JavaScriptMode.unrestricted)']
    if any(original.count(m)!=1 for m in markers):raise ValueError('WebView 源码结构变化，未添加加载观察器')
    filename='devicecheck-web-'+uuid.uuid4().hex+'.json'
    script=(Path(__file__).parent/'h5_diagnostics.js').read_text()
    dart=r'''import 'dart:io';
import 'dart:convert';
class DeviceCheckWebObserver {
  static final events=<Map<String,dynamic>>[];
  static final createdAt=<String,int>{};
  static final readySeen=<String>{};
  static final run=DateTime.now().microsecondsSinceEpoch.toString();
  static String clean(dynamic input) {
    var value=(input??'').toString();
    value=value.replaceAll(RegExp(r'[^\s]+@[^\s]+'),'[redacted]').replaceAll(RegExp(r'\b\d{7,}\b'),'[redacted]');
    return value.length>180?value.substring(0,180):value;
  }
  static String safeUrl(dynamic input) {
    try { final u=Uri.parse(input.toString());return clean((u.hasAuthority?'${u.scheme}://${u.host}${u.hasPort?':${u.port}':''}':'')+u.path+(u.fragment.isNotEmpty?'#'+u.fragment.split('?').first:'')); } catch (_) { return '[invalid-url]'; }
  }
  static dynamic params(dynamic value) {
    const keys=['storeId','robotId','sceneCode','targetPointId','page','pageNo','pageSize','limit','offset','type','status','language','lang','sort','order','category','issueType','problemType'];
    if(value is! Map)return <String,dynamic>{};
    return {for(final entry in value.entries.take(30)) if(RegExp(r'^[\w.-]{1,64}$').hasMatch(entry.key.toString())) entry.key.toString():keys.contains(entry.key)&&((entry.value is num)||(entry.value is bool)||entry.value==null||(entry.value is String&&entry.value.length<=80&&clean(entry.value)==entry.value&&!RegExp(r'password|token|secret|bearer',caseSensitive:false).hasMatch(entry.value)))?entry.value:'[redacted]'};
  }
  static void persist() {
    try { if(events.length>600)events.removeRange(0,events.length-600);File('${Directory.systemTemp.path}/FILENAME').writeAsStringSync(jsonEncode({'run':run,'events':events})); } catch (_) {}
  }
  static String created(String page,String url) {
    final id=DateTime.now().microsecondsSinceEpoch.toString();createdAt[id]=DateTime.now().millisecondsSinceEpoch;
    events.add({'kind':'webview_created','id':id,'epoch_ms':createdAt[id],'url':safeUrl(url)});persist();return id;
  }
  static void mark(String id,String kind) {events.add({'kind':kind,'id':id,'epoch_ms':DateTime.now().millisecondsSinceEpoch});persist();}
  static void message(String id,String raw) {

    try {
      final data=jsonDecode(raw);if(data is! Map)return;
      final kind=data['kind'];if(!['api','h5_ready','javascript_error','ui_issue','route_start'].contains(kind))return;
      final e=<String,dynamic>{'id':id,'kind':kind,'epoch_ms':data['epoch_ms'] is num?data['epoch_ms']:DateTime.now().millisecondsSinceEpoch,'route':safeUrl(data['route']??'')};
      for(final field in ['http_status','elapsed_ms','route_to_content_ms','dom_content_loaded_ms','document_load_ms']) {if(data[field] is num)e[field]=data[field];}
      for(final field in ['late_attach','failed']) {if(data[field] is bool)e[field]=data[field];}
      if(kind=='api') {
        e['url']=data['url'];e['method']=RegExp(r'^[A-Z]{1,10}$').hasMatch((data['method']??'').toString())?data['method']:'UNKNOWN';
        e['code']=data['code'] is num?data['code']:data['code'] is String?clean(data['code']):null;
        e['error']=data['error']!=null?'transport_error':null;
        e['params']=data['params'];e['response_body']=data['response_body'];e['response_summary']=data['response_summary'];
      }
      if(kind=='ui_issue'&&['visible_error_message','horizontal_overflow','control_clipped','text_clipped','blank_screen_suspected'].contains(data['issue']))e['issue']=data['issue'];
      if(kind=='javascript_error')e['message']=RegExp(r'password|token|secret|authorization|账号|密码',caseSensitive:false).hasMatch((data['message']??'').toString())?'[redacted]':clean(data['message']);
      if(kind=='h5_ready') {
        e['readiness']='visible_content_stable_300ms';
        if(!readySeen.contains(id)&&createdAt.containsKey(id)){e['webview_created_to_h5_ready_ms']=(e['epoch_ms'] as num)-createdAt[id]!;readySeen.add(id);}
      }
      events.add(e);persist();
    } catch (_) {}
  }
  static const script=r'JS_LITERAL';
}
'''.replace('FILENAME',filename)
    # Use a Dart raw triple string, with no interpolation of business source or credentials.
    dart=dart.replace("r'JS_LITERAL'","r'''"+script+"'''")
    (project/'lib/devicecheck_web_observer.dart').write_text(dart)
    text="import 'package:app_phone/devicecheck_web_observer.dart';\n"+original
    text=text.replace(markers[0],"  final dcSession = DeviceCheckWebObserver.created(pageName, url);\n"+markers[0])
    text=text.replace(markers[1],"onPageStarted: (String url) { DeviceCheckWebObserver.mark(dcSession, 'load_start'); controller.runJavaScript(DeviceCheckWebObserver.script).catchError((Object _) {}); },")
    text=text.replace(markers[2],markers[2]+"\n          DeviceCheckWebObserver.mark(dcSession, 'document_load_finished');\n          controller.runJavaScript(DeviceCheckWebObserver.script).catchError((Object _) {});")
    text=text.replace(markers[3],"    ..addJavaScriptChannel('DeviceCheckDiagnostics', onMessageReceived: (m) => DeviceCheckWebObserver.message(dcSession, m.message))\n"+markers[3])
    param.write_text(text)
    map_file=project/'lib/widgets/webview/webview_map_controller.dart'
    map_supported=False
    if map_file.is_file():
        text=map_file.read_text()
        marker='final scripts = <UserScript>['
        if text.count(marker)==1 and text.count('      onWebViewCreated: (c) {')==1 and text.count('    final settings = InAppWebViewSettings(')==1:
            text="import 'package:app_phone/devicecheck_web_observer.dart';\n"+text
            text=text.replace(marker,"final dcSession = DeviceCheckWebObserver.created(pageName, url);\n    "+marker)
            text=text.replace('    final settings = InAppWebViewSettings(',"    scripts.add(UserScript(source: DeviceCheckWebObserver.script, injectionTime: UserScriptInjectionTime.AT_DOCUMENT_START));\n    final settings = InAppWebViewSettings(")
            text=text.replace('      onWebViewCreated: (c) {',"      onWebViewCreated: (c) {\n        c.addJavaScriptHandler(handlerName: 'DeviceCheckDiagnostics', callback: (args) { if(args.isNotEmpty)DeviceCheckWebObserver.message(dcSession, jsonEncode(args.first)); return null; });")
            map_file.write_text(text);map_supported=True
    return {'file':filename,'version':'web_diagnostics_v1','map_document_start':map_supported,'standard_webview_initial_requests_may_be_missing':True,'scope':'xhr_fetch_and_visible_dom'}


class Probe:
    def __init__(self,platform,device,bundle,manifest,command,adb):
        if not re.fullmatch(r'devicecheck-web-[a-f0-9]{32}\.json',manifest.get('file','')) or not re.fullmatch(r'[\w.-]+',bundle or ''):raise ValueError('H5 观察器标识无效')
        self.platform=platform;self.device=device;self.bundle=bundle;self.manifest=manifest;self.command=command;self.adb=adb
    def device_clock(self):
        """Device epoch at the midpoint of the clock read, with uncertainty."""
        started=time.monotonic()
        if self.platform=='Android':
            result=self.command([self.adb,'-s',self.device,'shell','date','+%s%3N'])
            value=str(result.get('output','')).strip()
            if not result.get('ok') or not re.fullmatch(r'\d{13}',value):return None
            epoch=float(value)
        else:
            # iOS simulator and the host share the system clock.
            epoch=time.time()*1000
        finished=time.monotonic()
        return {'epoch_ms':epoch,'monotonic':(started+finished)/2,'uncertainty_ms':(finished-started)*500}

    def read(self):
        name=self.manifest['file'];text=''
        if self.platform=='Android':
            for directory in ('code_cache','cache'):
                r=self.command([self.adb,'-s',self.device,'shell','run-as',self.bundle,'cat','/data/user/0/'+self.bundle+'/'+directory+'/'+name])
                if r['ok']:text=r['output'];break
        else:
            r=self.command(['xcrun','simctl','get_app_container',self.device,self.bundle,'data'])
            if r['ok']:text=(Path(r['output'])/'tmp'/name).read_text()
        data=json.loads(text)
        if not isinstance(data.get('events'),list):raise ValueError('H5 观察数据无效')
        return data


class DeviceClock(Probe):
    """Clock calibration is usable even when an installed app has no source probe."""
    def __init__(self,platform,device,command,adb):
        self.platform=platform;self.device=device;self.command=command;self.adb=adb


def discover(platform,device,bundle,command,adb):
    if not re.fullmatch(r'[\w.-]+',bundle or ''):return None
    names=set()
    if platform=='Android':
        for directory in ('code_cache','cache'):
            result=command([adb,'-s',device,'shell','run-as',bundle,'ls',directory])
            if result.get('ok'):names.update(str(result.get('output','')).split())
    else:
        result=command(['xcrun','simctl','get_app_container',device,bundle,'data'])
        if result.get('ok'):names.update(p.name for p in (Path(result['output'].strip())/'tmp').glob('devicecheck-web-*.json'))
    names={n for n in names if re.fullmatch(r'devicecheck-web-[a-f0-9]{32}\.json',n)}
    if len(names)!=1:return None
    probe=Probe(platform,device,bundle,{'file':next(iter(names))},command,adb)
    probe.read()  # Confirm readable telemetry rather than promising unavailable monitoring.
    return probe
