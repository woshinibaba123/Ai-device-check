"""Bounded diagnostic metadata; no credentials, headers or arbitrary request bodies."""
import re
from urllib.parse import urlsplit
import automation

PARAM_KEYS={'_type','robotSn','storeId','robotId','sceneCode','targetPointId','page','pageNo','pageSize','limit','offset','type','status','language','lang','sort','order','category','issueType','problemType'}
SENSITIVE=re.compile(r'password|passwd|token|secret|authorization|cookie|phone|mobile|email|account|user.?name|session|jwt|api.?key|credential|联系人|密码|账号|电话|姓名|地址|address',re.I)


def clean(value,secrets=(),limit=160):
    return automation.redact(str(value or ''),secrets)[:limit]


def url(value):
    try:
        u=urlsplit(str(value));path=u.path
        path=re.sub(r'(?<=/)(?:[0-9]{7,}|[a-fA-F0-9-]{32,})(?=/|$)','[id]',path)
        path=clean(path)
        host=u.hostname or ''
        if u.port:host+=':'+str(u.port)
        return (u.scheme+'://'+host if u.scheme in ('http','https') and host else '')+path
    except (ValueError,TypeError):return '[redacted-url]'


def params(value,secrets=()):
    if not isinstance(value,dict):return {'_type':type(value).__name__}
    result={}
    for key,item in list(value.items())[:30]:
        key=str(key)
        if not re.fullmatch(r'[\w.-]{1,64}',key):continue
        if key not in PARAM_KEYS or SENSITIVE.search(key):result[key]='[redacted]';continue
        if item is None or isinstance(item,(int,float,bool)):result[key]='[redacted]' if item is not None and str(item) in [str(s) for s in secrets if s] else item
        elif isinstance(item,str) and len(item)<=80 and clean(item,secrets,100)==item and not re.search(r'password|token|secret|bearer',item,re.I):result[key]=item
        else:result[key]='[redacted]'
    return result


def route(value):
    raw=str(value or '')
    fragment=raw.split('#',1)[1].split('?',1)[0] if '#' in raw else ''
    if '=' in fragment:fragment='[redacted-route]'
    return url(raw)+(('#'+clean(fragment)) if fragment else '')


def api_event(event,secrets=()):
    return {**event, 'url':event.get('url') or event.get('path',''),
            'method':str(event.get('method','GET')).upper(),
            'http_status':event.get('http_status',event.get('status')),
            'error':event.get('error'), 'params':event.get('params') or {},
            'route':event.get('route',''), 'response_body':event.get('response_body'),
            'response_summary':event.get('response_summary',{})}



def trace(data,secrets=()):
    events=[]
    for event in data.get('events',[]):
        row=api_event(event,secrets)
        row['path']=urlsplit(row['url']).path
        row.update({key:event[key] for key in ('request_seq','request_shape','data_type') if key in event})
        fields=event.get('response_fields') if isinstance(event.get('response_fields'),dict) else {}
        row['response_fields']={key:clean(value,secrets) if isinstance(value,str) else value for key,value in fields.items()}
        events.append(row)
    return {'run':data.get('run'),'counter':data.get('counter'),'events':events}
