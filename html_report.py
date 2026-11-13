"""Standalone printable run report with original API evidence."""
import json
from datetime import datetime
from html import escape


def render(job):
    def e(value):return escape(str(value if value is not None else '—'))
    def dump(value):return e(json.dumps(value,ensure_ascii=False,indent=2,default=str))
    def badge(status):return '<span class="badge '+e(status)+'">'+e(status).upper()+'</span>'
    steps=[step for step in (job.get('ai_operator') or {}).get('steps',[])
           if str(step.get('action','')).strip().lower()!='wait']
    events=(job.get('diagnostics') or {}).get('api_events',[])
    passed=sum(s.get('status') in ('passed','success') or s.get('success') is True for s in steps)
    failed=sum(s.get('status') in ('failed','error') or s.get('success') is False for s in steps)
    duration='未记录'
    try:
        started=datetime.fromisoformat(str(job.get('started','')).replace('Z','+00:00'))
        finished=datetime.fromisoformat(str(job.get('finished','')).replace('Z','+00:00')) if job.get('finished') else datetime.now(started.tzinfo)
        seconds=max(0,int((finished-started).total_seconds()))
        hours,remainder=divmod(seconds,3600)
        minutes,seconds=divmod(remainder,60)
        duration=(f'{hours}小时' if hours else '')+(f'{minutes}分' if minutes or hours else '')+f'{seconds}秒'
        if not job.get('finished'):duration+='（进行中）'
    except (ValueError,TypeError):pass
    coverage=(job.get('diagnostics') or {}).get('coverage',{})
    monitoring=[]
    labels={'native':'App 原生接口','h5':'内嵌网页接口与页面状态'}
    for key,label in labels.items():
        value=coverage.get(key)
        if value=='observed':description='已采集'
        elif value in ('source_observer_required','legacy_observer_without_latency_or_parameters'):description='当前测试包未提供完整监控数据，需重新构建测试包'
        elif value=='observer_present_no_readable_events':description='已配置监控，但本次未能读取数据'
        elif value:description='已配置监控，尚未确认采集到数据'
        else:description='本次未记录监控情况'
        monitoring.append(f'<li>{label}：{description}。</li>')
    if coverage.get('timings'):monitoring.append('<li>页面耗时：从操作开始，到观察到页面内容出现的时间，包含自动化等待时间。</li>')
    if coverage.get('visual'):monitoring.append('<li>页面异常检查：检查白屏、错误提示和部分显示异常；不代表所有页面与功能均已验证。</li>')
    monitoring_html='<div><b>监控情况</b><ul>'+''.join(monitoring)+'</ul></div>' if coverage else ''
    rows=[]
    for i,s in enumerate(steps,1):
        action={'tap':'点击','click':'点击','input':'输入','scroll':'滑动','back':'返回','select':'选择'}.get(s.get('action'),s.get('action','操作'))
        elapsed=s.get('elapsed_ms')
        timing=f'{elapsed/1000:.2f}秒' if isinstance(elapsed,(int,float)) else '未采集'
        rows.append(f'<tr><td>#{i}</td><td><b>{e(action)} · {e(s.get("label") or s.get("instruction") or s.get("target") or "页面")}</b></td><td>{timing}</td></tr>')
    navigation=[]
    other_observations=[]
    for row in (job.get('diagnostics') or {}).get('navigation',[]):
        elapsed=row.get('observed_elapsed_ms',row.get('action_to_content_ms'))
        timing=f'{elapsed/1000:.2f}秒' if isinstance(elapsed,(int,float)) else '未采集'
        status=row.get('status')
        outcome='已观察到页面就绪' if status=='content_ready' else '当前页面内容就绪，未观察到页面切换' if status=='same_page_ready' else '下一次操作前未观察到就绪' if status=='readiness_not_observed_before_next_action' else '结束前未观察到就绪'
        if status!='content_ready':timing+='（观察时长）'
        is_transition=bool(row.get('from') and row.get('to') and row['from']!=row['to'] and status!='same_page_ready')
        target_rows=navigation if is_transition else other_observations
        target_rows.append(f'<tr><td>{e(row.get("from"))}</td><td>{e(row.get("to") or "未确认目标页面")}</td><td>{timing}</td><td>{outcome}</td></tr>')
    navigation_html='<section><h2>页面切换时长</h2><p>包含自动化等待时间；未确认就绪的记录不代表加载完成。</p><table><tr><th>原页面</th><th>目标页面</th><th>时长</th><th>结果</th></tr>'+''.join(navigation)+'</table>'+('' if navigation else '<p>本次未采集页面切换计时。</p>')+'</section>'
    if other_observations:
        navigation_html+='<details><summary>同页操作与未确认跳转的观察记录（不计入页面切换） · '+str(len(other_observations))+' 条</summary><table><tr><th>操作前页面</th><th>观察到的页面</th><th>观察时长</th><th>结果</th></tr>'+''.join(other_observations)+'</table></details>'
    transitions=[]
    for row in (job.get('diagnostics') or {}).get('webview_transitions',[]):
        values=[row.get(k) for k in ('total_ms','action_to_webview_ms','webview_to_h5_content_ms')]
        if not all(isinstance(v,(int,float)) and v>=0 for v in values):continue
        total,jump,load=[f'{v/1000:.2f}'.rstrip('0').rstrip('.') for v in values]
        note='监控晚接入，展示就绪时间为上界' if row.get('late_attach') else 'H5 内容可见并稳定 300ms'
        uncertainty=row.get('clock_uncertainty_ms')
        if isinstance(uncertainty,(int,float)):note+=f'；设备时钟对齐误差约 ±{uncertainty:.0f}ms'
        transitions.append(f'<tr><td>{e(row.get("from"))}</td><td>{e(row.get("to"))}</td><td><b>{total}s（{jump}+{load}）</b></td><td>{e(note)}</td></tr>')
    navigation_html+='<section><h2>原生页面 → WebView → H5 展示</h2><p>总时长（原生点击至 WebView 创建 + WebView 创建至 H5 内容展示稳定），单位：秒。包含内容稳定确认所需的 300ms。</p>'
    if transitions:
        navigation_html+='<table><tr><th>原生页面</th><th>H5 目标页面</th><th>总时长（跳转+H5加载）</th><th>采集说明</th></tr>'+''.join(transitions)+'</table>'
    else:
        navigation_html+='<p>未采集完整分段计时：需要原生操作起点、WebView 创建事件、H5 就绪事件及设备时钟对齐。历史记录无法补算。</p>'
    observations=(job.get('diagnostics') or {}).get('webview_observations',[])
    if observations:
        navigation_html+='<h3>原生点击 → H5 就绪（自动化观察）</h3><p>以下为含采样与驱动等待的观察上界，未取得 WebView 创建事件时无法拆成跳转与 H5 加载两段。</p><table><tr><th>原生页面</th><th>H5 页面</th><th>点击至观察到就绪</th></tr>'
        for row in observations:
            elapsed=row.get('total_ms')
            if isinstance(elapsed,(int,float)):
                navigation_html+=f'<tr><td>{e(row.get("from"))}</td><td>{e(row.get("to"))}</td><td>{elapsed/1000:.2f}s（观察上界；分段未采集）</td></tr>'
        navigation_html+='</table>'
    navigation_html+='</section>'
    native_frames=(job.get('diagnostics') or {}).get('native_route_frames',[])
    navigation_html+='<section><h2>App 原生路由切换时长</h2><p>由 Flutter 路由回调至下一帧；不是业务数据全部加载完成的时间。</p>'
    if native_frames:
        navigation_html+='<table><tr><th>原路由</th><th>目标路由</th><th>路由至首帧</th></tr>'
        for row in native_frames:
            elapsed=row.get('route_to_first_frame_ms')
            timing=f'{elapsed:.1f}ms' if isinstance(elapsed,(int,float)) else '未采集'
            navigation_html+=f'<tr><td>{e(row.get("from") or "启动或原路由未采集")}</td><td>{e(row.get("route"))}</td><td>{timing}</td></tr>'
        navigation_html+='</table>'
    else:navigation_html+='<p>未采集到原生路由事件；当前包需包含原生路由观察器。同路由的 Tab 切换不计为路由切换。</p>'
    navigation_html+='</section>'
    measured=[]
    for row in (job.get('diagnostics') or {}).get('webview_loads',[]):
        def ms(key):
            value=row.get(key)
            return f'{value} ms' if isinstance(value,(int,float)) else '未采集'
        measured.append(f'<tr><td>{e(row.get("route"))}</td><td>{ms("route_to_content_ms")}</td><td>{ms("webview_created_to_h5_ready_ms")}</td><td>{"监控晚接入，非完整打开耗时" if row.get("late_attach") else "页面内容稳定 300ms"}</td></tr>')
    if measured:
        navigation_html+='<section><h2>网页内部实测计时</h2><p>由网页监控采集。晚接入时首条路由计时从监控接入开始；不等于完整加载耗时。</p><table><tr><th>实际页面地址</th><th>路由观察至内容稳定</th><th>WebView 创建至就绪</th><th>采集说明</th></tr>'+''.join(measured)+'</table></section>'
    calls=[]
    for i,r in enumerate(events,1):
        calls.append(f'<details><summary>#{i} {badge("failed" if r.get("failed") else "success")} <b>{e(r.get("method"))} {e(r.get("url"))}</b> · HTTP {e(r.get("http_status"))} · {e(r.get("elapsed_ms"))} ms</summary><details><summary>请求参数</summary><pre>{dump(r.get("params") or "未采集参数或请求无参数（历史记录无法区分）")}</pre></details><details><summary>返回结果</summary><pre>{dump(r.get("response_body") if r.get("response_body") is not None else "未采集到返回正文（不代表接口返回 null）")}</pre></details></details>')
    screenshots=''.join(f'<a href="{e(u)}" target="_blank"><img loading="lazy" src="{e(u)}"></a>' for u in job.get('screenshots',[]))
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>测试报告</title><style>
*{box-sizing:border-box}body{margin:0;background:#f1f5f9;color:#1e293b;font:15px/1.65 -apple-system,BlinkMacSystemFont,"Microsoft YaHei",sans-serif}main{max-width:1260px;margin:48px auto;padding:0 24px}section{background:white;border-radius:22px;padding:32px 40px;margin-bottom:24px;box-shadow:0 2px 5px #10203009}h1{font-size:27px;margin:0 0 22px}h2{font-size:21px;border-left:5px solid #4083ff;padding-left:14px}header{display:flex;justify-content:space-between;align-items:start}.badge{display:inline-block;border-radius:24px;background:#64748b;color:white;padding:3px 15px;font-weight:700;white-space:nowrap}.success,.passed{background:#12a64e}.failed,.error{background:#e52329}.meta,code{background:#f1f5f9;border-radius:8px;padding:5px 12px}code{color:#2865ed}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin:26px 0}.stat{border:1px solid #dce5ef;background:#f8fafc;border-radius:15px;text-align:center;padding:18px}.stat strong{display:block;font-size:29px}.stat span{color:#718198}table{width:100%;border-collapse:collapse}th{text-align:left;background:#f8fafc;color:#718198}td,th{padding:18px 12px;border-bottom:1px solid #edf2f7;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f8fafc;border:1px solid #e0e7ef;border-radius:8px;padding:12px;font:13px/1.6 monospace}details{border-bottom:1px solid #e2e8f0;padding:18px 0}summary{cursor:pointer;overflow-wrap:anywhere}img{max-width:230px;max-height:450px;margin:8px}p{overflow-wrap:anywhere}@media(max-width:700px){section{padding:20px}.stats{grid-template-columns:repeat(2,1fr)}main{padding:0 10px}table{display:block;overflow:auto}}@media print{body{background:white}main{margin:0;max-width:none}section{box-shadow:none;border:1px solid #eee}details,pre{break-inside:auto}.stats{break-inside:avoid}}
</style><main>'''+f'''<section><button type="button" id="downloadReport" data-job="{e(job.get('id','report'))}">下载完整报告（HTML）</button><header><h1>{e(job.get('label') or 'DeviceCheck 测试报告')}</h1>{badge(job.get('status','unknown'))}</header><span class="meta">任务：{e(job.get('id'))}</span> <span class="meta">平台：{e(job.get('platform'))}</span><p>开始：{e(job.get('started'))}　结束：{e(job.get('finished'))}　<strong>总时长：{e(duration)}</strong></p><div class="stats"><div class="stat"><strong>{len(steps)}</strong><span>已记录步骤</span></div><div class="stat"><strong style="color:#12a64e">{passed}</strong><span>通过</span></div><div class="stat"><strong style="color:#e52329">{failed}</strong><span>失败</span></div><div class="stat"><strong>{len(events)}</strong><span>接口调用</span></div></div>{monitoring_html}</section><section><h2>执行步骤 · {len(steps)} 项</h2><p>步骤耗时包含识别、定位和执行时间；历史记录未采集的耗时无法补回。</p><table><thead><tr><th>#</th><th>步骤与执行说明</th><th>步骤耗时</th></tr></thead><tbody>{''.join(rows)}</tbody></table>{'<p>本次没有结构化步骤记录，执行过程见下方日志。</p>' if not steps else ''}</section>{navigation_html}<section><h2>接口调用 · {len(events)} 项</h2><p>成功与失败请求均展示原始采集参数和返回结果；历史记录未采集的正文显示“—”。</p>{''.join(calls)}</section><section><h2>执行日志</h2><pre>{e(chr(10).join(job.get('logs',[])))}</pre></section><section><h2>截图</h2>{screenshots}</section></main>'''+DOWNLOAD_SCRIPT+'</html>' 


DOWNLOAD_SCRIPT = r"""<script>
document.getElementById('downloadReport').addEventListener('click',async function(){
 const button=this,original=button.textContent;button.disabled=true;button.textContent='正在打包报告与截图…';
 try{
  const clone=document.documentElement.cloneNode(true);
  const sourceImages=[...document.images],images=[...clone.querySelectorAll('img')];
  await Promise.all(sourceImages.map(async (img,index)=>{
   let data=img.src;
   if(!data.startsWith('data:')){
    const response=await fetch(data);if(!response.ok)throw Error('截图读取失败');
    const blob=await response.blob();data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob)});
   }
   images[index].src=data;images[index].removeAttribute('loading');
   if(images[index].parentElement.tagName==='A')images[index].parentElement.href=data;
  }));
  clone.querySelector('#downloadReport').disabled=false;clone.querySelector('#downloadReport').textContent=original;
  const blob=new Blob(['<!doctype html>\n'+clone.outerHTML],{type:'text/html;charset=utf-8'});
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='DeviceCheck-'+button.dataset.job+'.html';link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
 }catch(error){alert('下载失败：'+error.message)}finally{button.disabled=false;button.textContent=original}
});
</script>"""
