"""Dio observer in the cloned test source; no request bodies, headers or credentials."""
import json
import re
import uuid
from pathlib import Path

SENSITIVE=re.compile(r'password|passwd|token|secret|authorization|cookie|phone|email|account|user.?name|session|jwt|api.?key|credential',re.I)
def safe_fields(fields):
    if not isinstance(fields,list) or len(fields)>32:raise ValueError('最多选择 32 个响应字段')
    if any(not isinstance(f,str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',f) or SENSITIVE.search(f) for f in fields):raise ValueError('响应字段无效或包含凭据/账号信息')
    return fields

def instrument(project,index,fields=None,monitor=False):
    project=Path(project);file=project/'lib/http/dio_client.dart';text=file.read_text()
    marker='dio = Dio(options);'
    if text.count(marker)!=1:raise ValueError('Dio 初始化结构已变化，无法添加接口观察器')
    fields=safe_fields(fields or [])
    paths=sorted({call['path'] for call in index['api_calls'] if call['path'] and not SENSITIVE.search(call['path']) and not re.search(r'/auth/|/oauth/|/login|/code(?:/|$)',call['path'])})
    name='devicecheck-http-'+uuid.uuid4().hex+'.json'
    dart=r'''import 'dart:io';
import 'dart:convert';
import 'package:dio/dio.dart';
class DeviceCheckHttpObserver extends Interceptor {
  static int counter = 0;
  static final List<Map<String, dynamic>> events = [];
  static const allowed = PATHS;
  static const fields = FIELDS;
  static final run = DateTime.now().microsecondsSinceEpoch.toString();
  void persist() {
    try { File('${Directory.systemTemp.path}/FILE').writeAsStringSync(jsonEncode({'run':run,'counter':counter,'events':events})); } catch (_) {}
  }
  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    options.extra['devicecheck_seq'] = ++counter;
    persist();
    handler.next(options);
  }
  dynamic field(dynamic data, String path) {
    dynamic value = data;
    for (final key in path.split('.')) {
      if (value is! Map || !value.containsKey(key)) return '[missing]';
      value = value[key];
    }
    if (value is num || value is bool || value == null) return value;
    if (value is String) {
      if (value.length > 128 || value.contains('@') || RegExp(r'\b\d{11,}\b').hasMatch(value)) return '[redacted]';
      return value;
    }
    return {'type':value is List ? 'list' : 'object','length':value is List ? value.length : value is Map ? value.length : null};
  }
  Map<String, dynamic> requestShape(dynamic data) {
    if (data is String) { try { data=jsonDecode(data); } catch (_) { return {}; } }
    if (data is! Map) return {};
    bool present(String key) => data.containsKey(key) && data[key] != null && data[key].toString().trim().isNotEmpty;
    final task=data['taskRequest'];
    return {'storeId':present('storeId'),'sceneCode':present('sceneCode'),'targetPointId':present('targetPointId'),
      'multiPointCount':task is Map && task['points'] is List ? (task['points'] as List).length : 0};
  }
  void record(RequestOptions options, Response? response, String? error) {
    try {
      final path=options.uri.path;
      if (!allowed.contains(path)) return;
      dynamic body=response?.data;
      if (body is String) { try { body=jsonDecode(body); } catch (_) { body=null; } }
      final code=body is Map ? body['code'] : null;
      events.add({'request_seq':options.extra['devicecheck_seq'],'path':path,'method':options.method,'http_status':response?.statusCode,'code':code is num ? code : null,'error':error,'response_fields':{for(final key in fields) key:field(body,key)},'request_shape':path == '/api/merchant/mobile/miniprogram/v2/call/task' ? requestShape(options.data) : {},'data_type':body is Map ? 'object' : body is List ? 'list' : 'other'});
      if(events.length>300) events.removeAt(0);
      persist();
    } catch (_) {}
  }
  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    record(response.requestOptions,response,null);handler.next(response);
  }
  @override
  void onError(DioError error, ErrorInterceptorHandler handler) {
    record(error.requestOptions,error.response,error.type.toString());handler.next(error);
  }
}
'''.replace('PATHS',json.dumps(paths,ensure_ascii=False)).replace('FIELDS',json.dumps(fields)).replace('FILE',name)
    if '/api/merchant/mobile/miniprogram/v2/call/task' not in paths:dart=dart.replace('requestShape(options.data)','<String, dynamic>{}')
    if monitor:
        helpers=r'''
  Map<String,dynamic> safeParams(dynamic value) {
    const keys=['storeId','robotId','sceneCode','targetPointId','page','pageNo','pageSize','limit','offset','type','status','language','lang','sort','order','category','issueType','problemType'];
    if(value is String){try{value=jsonDecode(value);}catch(_){return {'_type':'string'};}}
    if(value is! Map)return {};
    final result=<String,dynamic>{};
    for(final entry in value.entries.take(30)) {
      final key=entry.key.toString(),v=entry.value;
      if(!RegExp(r'^[\w.-]{1,64}$').hasMatch(key))continue;
      result[key]=keys.contains(key)&&(v==null||v is num||v is bool||v is String&&v.length<=80&&!RegExp(r'@|\b\d{7,}\b|password|token|secret|bearer',caseSensitive:false).hasMatch(v))?v:'[redacted]';
    }
    return result;
  }
  Map<String,dynamic> diagnostic(RequestOptions options,Response? response,String? error,dynamic body) {
    final code=body is Map?body['code']:null;
    final failed=error!=null||(response?.statusCode!=null&&(response!.statusCode!<200||response.statusCode!>=400))||(code!=null&&!SUCCESS_CODES.contains(code.toString()));
    final path=options.uri.path.replaceAll(RegExp(r'/(?:\d{7,}|[a-fA-F0-9-]{32,})(?=/|$)'),'/[id]');
    final auth=RegExp(r'/(auth|oauth|login|token|password|captcha|sms)(/|$)',caseSensitive:false).hasMatch(path);
    final start=options.extra['devicecheck_start_us'];
    return {'url':options.uri.toString(),'failed':failed,'epoch_ms':DateTime.now().millisecondsSinceEpoch,'elapsed_ms':start is int?(DateTime.now().microsecondsSinceEpoch-start)/1000:null,'route':options.extra['devicecheck_route'],'params':{'query':options.queryParameters,'body':options.data?.toString()},'request_headers':options.headers,'response_body':response?.data,'response_headers':response?.headers.map};
  }
'''.replace('SUCCESS_CODES',json.dumps([str(c) for c in index['business_success_codes']]))
        dart=dart.replace('  void record(RequestOptions options,',helpers+'\n  void record(RequestOptions options,')
        dart=dart.replace('      if (!allowed.contains(path)) return;','')
        dart=dart.replace("    options.extra['devicecheck_seq'] = ++counter;", "    options.extra['devicecheck_seq'] = ++counter;\n    options.extra['devicecheck_start_us'] = DateTime.now().microsecondsSinceEpoch;\n    try { options.extra['devicecheck_route'] = jsonDecode(File('${Directory.systemTemp.path}/devicecheck-route.json').readAsStringSync())['route']; } catch (_) {}")
        start=dart.index("      events.add({'request_seq':")
        end=dart.index(');\n      if(events.length',start)
        expression=dart[start+len('      events.add('):end]
        dart=dart[:start]+"      final event=<String,dynamic>"+expression+";\n      event.addAll(diagnostic(options,response,error,body));\n      events.add(event"+dart[end:]
        dart=dart.replace("'code':code is num ? code : null", "'code':code is num || code is String && RegExp(r'^[A-Za-z0-9_-]{1,64}$').hasMatch(code) ? code : null")
    (project/'lib/devicecheck_http_observer.dart').write_text(dart)
    file.write_text("import 'package:app_phone/devicecheck_http_observer.dart';\n"+text.replace(marker,marker+'\n    dio.interceptors.add(DeviceCheckHttpObserver());'))
    return {'file':name,'paths':paths,'response_fields':fields,'success_codes':index['business_success_codes'],'field_encoding':'missing_sentinel_v1','scope':'native_dio_only','request_shape_version':'call_task_fields_v1','diagnostics_version':'native_diagnostics_v1' if monitor else None}

class Probe:
    def __init__(self,platform,device,bundle,manifest,command,adb):
        if not re.fullmatch(r'devicecheck-http-[a-f0-9]{32}\.json',manifest.get('file','')):raise ValueError('缺少本次构建的接口观察器，请重新从源码构建')
        if not re.fullmatch(r'[\w.\-]+',bundle or ''):raise ValueError('未确认 App 包名')
        self.platform=platform;self.device=device;self.bundle=bundle;self.manifest=manifest;self.command=command;self.adb=adb
    def read(self):
        name=self.manifest['file'];text=''
        if self.platform=='Android':
            for directory in ('code_cache','cache'):
                path='/data/user/0/'+self.bundle+'/'+directory+'/'+name
                result=self.command([self.adb,'-s',self.device,'shell','run-as',self.bundle,'cat',path])
                if result['ok']:text=result['output'];break
        else:
            result=self.command(['xcrun','simctl','get_app_container',self.device,self.bundle,'data'])
            if result['ok']:
                file=Path(result['output'])/'tmp'/name
                if file.exists():text=file.read_text()
        try:data=json.loads(text)
        except (ValueError,TypeError):raise RuntimeError('无法读取接口观察器，不能判定保存成功')
        if not isinstance(data,dict) or not isinstance(data.get('counter'),int) or not isinstance(data.get('events'),list):raise RuntimeError('接口观察器数据无效')
        return data
    def mark(self):
        data=self.read();return {'run':data.get('run'),'counter':data['counter']}
    def check(self,marker,expect):
        if expect['path'] not in self.manifest['paths']:raise RuntimeError('接口未在本次源码观察范围中')
        data=self.read()
        if data.get('run')!=marker['run']:raise RuntimeError('保存期间 App 已重启，接口结果无法归属于原操作')
        events=[e for e in data['events'] if isinstance(e.get('request_seq'),int) and e['request_seq']>marker['counter'] and e['path']==expect['path'] and e['method'].upper()==expect['method'].upper()]
        if not events:return None
        # Multiple matching calls cannot be silently attributed to one button.
        if len(events)>1:raise RuntimeError('同一操作后出现多个匹配接口，需进一步明确请求关联')
        event=events[0]
        self.last_event=event
        status=event.get('http_status')
        if event.get('error') or not isinstance(status,int) or not 200<=status<300:raise AssertionError('保存接口 HTTP/网络失败：'+str(status))
        if event.get('code') not in expect.get('codes',self.manifest['success_codes']):raise AssertionError('保存接口业务失败或缺少业务码：'+str(event.get('code')))
        for field,value in expect.get('equals',{}).items():
            if field not in self.manifest['response_fields']:raise RuntimeError('响应字段未在构建时配置：'+field)
            if field not in event.get('response_fields',{}):raise RuntimeError('接口观察记录缺少字段：'+field)
            if value is None and self.manifest.get('field_encoding')!='missing_sentinel_v1':raise RuntimeError('当前观察器无法区分空值与缺失字段，请重新构建')
            if event.get('response_fields',{}).get(field) in ('[missing]','[redacted]'):raise RuntimeError('响应字段缺失或已脱敏，不能验证：'+field)
            if event.get('response_fields',{}).get(field)!=value:raise AssertionError('接口返回字段不符合预期：'+field)
        return event
