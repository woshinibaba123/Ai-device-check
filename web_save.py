"""One-click H5 writes verified against that click's XHR/fetch response.
No request headers/bodies, full response bodies or credentials leave the WebView.
"""
import time
import uuid
import http_probe

INSTALL=r'''
const [key,method,path,fields]=arguments;
const original={fetch:window.fetch,open:XMLHttpRequest.prototype.open,send:XMLHttpRequest.prototype.send};
const state={events:[],restore:null};window[key]=state;
const match=(m,u)=>{try{return String(m).toUpperCase()===method&&new URL(u,location.href).pathname===path}catch{return false}};
const primitive=v=>v===null||typeof v==='number'||typeof v==='boolean'||(typeof v==='string'&&v.length<=128&&!/@|\d{7}/.test(v));
const record=(status,body)=>{try{
 if(typeof body==='string'){if(body.length>1000000)return;body=JSON.parse(body)}
 const values={};for(const field of fields){let v=body;for(const part of field.split('.'))v=v&&typeof v==='object'&&Object.prototype.hasOwnProperty.call(v,part)?v[part]:undefined;values[field]=primitive(v)?v:'[missing or redacted]'}
 state.events.push({status,code:body&&Number.isInteger(body.code)?body.code:null,fields:values});
 if(state.events.length>10)state.events.shift();
}catch{state.events.push({status,code:null,fields:{}})}};
const requestMeta=new WeakMap();
const open=function(m,u,...rest){requestMeta.set(this,{match:match(m,u)});return original.open.call(this,m,u,...rest)};
const send=function(...args){if(requestMeta.get(this)?.match)this.addEventListener('load',()=>{try{record(this.status,this.responseType==='json'?this.response:this.responseText)}catch{record(this.status,null)}},{once:true});return original.send.apply(this,args)};
const fetchWrapper=async function(input,init){const m=init?.method||input?.method||'GET';const u=input?.url||input;const response=await original.fetch.apply(this,arguments);if(match(m,u))response.clone().text().then(body=>record(response.status,body)).catch(()=>record(response.status,null));return response};
XMLHttpRequest.prototype.open=open;XMLHttpRequest.prototype.send=send;if(original.fetch)window.fetch=fetchWrapper;
state.restore=()=>{if(XMLHttpRequest.prototype.open===open)XMLHttpRequest.prototype.open=original.open;if(XMLHttpRequest.prototype.send===send)XMLHttpRequest.prototype.send=original.send;if(window.fetch===fetchWrapper)window.fetch=original.fetch;delete window[key]};
return true;
'''


def perform(web,step,element_id):
    # Repeat validation at the mutation boundary even when called outside case_runner.
    import case_runner
    case_runner.validate_plan({'steps':[step]})
    api=step['api'];fields=http_probe.safe_fields(list(api.get('equals',{})))
    key='__devicecheck_save_'+uuid.uuid4().hex
    installed=web.js(INSTALL,[key,api['method'],api['path'],fields])
    if installed is not True:raise RuntimeError('H5 接口观察器未就绪，未点击保存')
    try:
        if web.e.stopped():raise RuntimeError('用户停止，未点击保存')
        # Exactly once: never retry an uncertain save click.
        web.e.call('POST',web.e.base+'/element/'+element_id+'/click',{})
        deadline=time.monotonic()+float(api.get('timeout',20))
        while time.monotonic()<deadline:
            if web.e.stopped():raise RuntimeError('保存已点击但测试停止；需核对记录，不能自动重提')
            events=web.js('return window[arguments[0]]?.events||[]',[key],read_only=True)
            if events:
                event=events[0]
                if not 200<=event.get('status',0)<300:raise AssertionError('H5 保存接口 HTTP 失败：'+str(event.get('status')))
                if event.get('code') not in api.get('codes',[610000,0]):raise AssertionError('H5 保存接口业务失败或缺少成功码：'+str(event.get('code')))
                for field,value in api.get('equals',{}).items():
                    if event.get('fields',{}).get(field)!=value:raise AssertionError('H5 保存响应字段与预期不一致：'+field)
                return {'action':'web_save','selector':step['value'],'api':{'method':api['method'],'path':api['path'],'http_status':event['status'],'code':event['code'],'fields':event.get('fields',{})},'clicked_once':True}
            time.sleep(.25)
        raise RuntimeError('H5 保存已点击但接口结果未确认；不能自动重提，需核对后台记录')
    finally:
        try:web.js('window[arguments[0]]?.restore();return true',[key])
        except Exception:pass
