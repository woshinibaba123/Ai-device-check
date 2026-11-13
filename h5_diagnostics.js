(()=>{
 if(window.__devicecheckDiagnosticsV1?.version===3)return;
 const state={version:3,events:[],queue:[],started:performance.now(),lastMutation:performance.now(),routeStarted:performance.now(),route:'',ready:false,late:document.readyState==='complete'};
 window.__devicecheckDiagnosticsV1=state;
 const sensitive=/password|passwd|token|secret|authorization|cookie|phone|mobile|email|account|user.?name|session|jwt|api.?key|credential|密码|账号|电话|姓名|地址/i;
 const keys=new Set(['_type','robotSn','storeId','robotId','sceneCode','targetPointId','page','pageNo','pageSize','limit','offset','type','status','language','lang','sort','order','category','issueType','problemType']);
 const text=v=>String(v??'').replace(/[^\s]+@[^\s]+/g,'[redacted]').replace(/\b\d{7,}\b/g,'[redacted]').slice(0,160);
 const safeUrl=v=>{try{const u=new URL(String(v),location.href);return u.origin+u.pathname.replace(/\/(?:\d{7,}|[a-f0-9-]{32,})(?=\/|$)/gi,'/[id]')}catch{return '[invalid-url]'}};
 const route=()=>safeUrl(location.href)+(location.hash.split('?')[0].includes('=')?'#[redacted-route]':text(location.hash.split('?')[0]));
 const parameters=v=>{if(typeof v==='string'){try{return JSON.parse(v)}catch{return v}}if(v instanceof URLSearchParams)return v.toString();if(v instanceof FormData)return [...v.entries()].map(([k,v])=>[k,typeof v==='string'?v:{name:v.name,size:v.size,type:v.type}]);return v??null};
 const flush=()=>{while(state.queue.length){const e=state.queue[0];try{if(window.DeviceCheckDiagnostics?.postMessage)window.DeviceCheckDiagnostics.postMessage(JSON.stringify(e));else if(window.flutter_inappwebview?.callHandler)window.flutter_inappwebview.callHandler('DeviceCheckDiagnostics',e).catch(()=>{});else break;state.queue.shift()}catch{break}}};
 const emit=e=>{e.epoch_ms=Date.now();e.route=route();state.events.push(e);state.queue.push(e);if(state.events.length>300)state.events.shift();if(state.queue.length>300)state.queue.shift();flush()};
 const visible=e=>{if(!e||e.closest('#__vconsole'))return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity)!==0};
 const sample=()=>{
  const root=document.querySelector('main,.view-container,#app')||document.body;
  if(!root)return {content:false,loading:true,issues:[]};
  const loading=[...document.querySelectorAll('.el-loading-mask,.van-loading__mask,[aria-busy=true]')].some(visible);
  const labels=[...root.querySelectorAll('body *,button,a,input,textarea,select')].filter(e=>visible(e)&&!e.closest('nav,header,#__vconsole')).slice(0,800);
  const words=String(root.innerText||'').trim();
  const media=labels.some(e=>['CANVAS','VIDEO','IFRAME'].includes(e.tagName)||e.tagName==='IMG'&&e.complete&&e.naturalWidth>0);
  const content=words.length>=10||media||labels.some(e=>['BUTTON','INPUT','TEXTAREA','SELECT','A'].includes(e.tagName));
  const issues=[];
  if(/页面加载失败|无法访问|服务异常|网络异常|ERR_CONNECTION|Application error|Internal Server Error|ページを読み込め|加载出错/i.test(words))issues.push('visible_error_message');
  if(document.documentElement.scrollWidth>innerWidth+8)issues.push('horizontal_overflow');
  const controls=labels.filter(e=>['BUTTON','INPUT','TEXTAREA','SELECT'].includes(e.tagName)||e.getAttribute('role')==='button').slice(0,100);
  for(const e of controls){const r=e.getBoundingClientRect();if(r.top>=innerHeight||r.bottom<=0||r.left>=innerWidth||r.right<=0)continue;if(r.left < -4||r.right>innerWidth+4)issues.push('control_clipped');if((e.scrollWidth>e.clientWidth+8)&&getComputedStyle(e).overflowX==='hidden'&&getComputedStyle(e).textOverflow!=='ellipsis')issues.push('text_clipped');}
  if(!loading&&performance.now()-state.routeStarted>10000&&!content)issues.push('blank_screen_suspected');
  return {content,loading,secure:[...document.querySelectorAll('input[type=password]')].some(visible),issues:[...new Set(issues)],ready_state:document.readyState};
 };
 state.sample=sample;
 const tick=()=>{const r=route();if(r!==state.route){state.route=r;state.routeStarted=performance.now();state.ready=false;state.lastMutation=performance.now();state.issueTimes={};emit({kind:'route_start'})}const s=sample();if(!state.ready&&s.content&&!s.loading&&!s.secure&&document.readyState!=='loading'&&performance.now()-state.lastMutation>=300){state.ready=true;const n=performance.getEntriesByType('navigation')[0];emit({kind:'h5_ready',route_to_content_ms:Math.round(performance.now()-state.routeStarted),late_attach:state.late,readiness:'visible_content_stable_300ms',dom_content_loaded_ms:n?Math.round(n.domContentLoadedEventEnd):null,document_load_ms:n?Math.round(n.loadEventEnd):null})}if(!state.issueTimes)state.issueTimes={};for(const key of Object.keys(state.issueTimes))if(!s.issues.includes(key))delete state.issueTimes[key];for(const issue of s.issues){if(['horizontal_overflow','control_clipped','text_clipped'].includes(issue)){if(state.issueTimes[issue]===undefined)state.issueTimes[issue]=performance.now();if(performance.now()-state.issueTimes[issue]<1000)continue}if(!state.reported)state.reported=new Set();const k=r+issue;if(!state.reported.has(k)){state.reported.add(k);emit({kind:'ui_issue',issue})}}flush()};
 const attach=()=>{if(document.documentElement)new MutationObserver(()=>{state.lastMutation=performance.now()}).observe(document.documentElement,{subtree:true,childList:true,characterData:true})};if(document.documentElement)attach();else addEventListener('DOMContentLoaded',attach,{once:true});
 const record=(method,u,start,status,body,error,data)=>{
  let response=body;if(typeof response==='string'){try{response=response.length<=1000000?JSON.parse(response):null}catch{response=null}}
  const code=response&&typeof response==='object'&&['string','number'].includes(typeof response.code)?response.code:null;
  const failed=!!error||status===0||status>=400||(code!==null&&!['0','610000','200'].includes(String(code)));
  let query={};try{query=Object.fromEntries(new URL(String(u),location.href).searchParams.entries())}catch{}
  const auth=/\/(auth|oauth|login|token|password|captcha|sms)(\/|$)/i.test(safeUrl(u));
  emit({kind:'api',url:String(u),method:String(method).toUpperCase(),http_status:status,code:typeof code==='string'?text(code):code,elapsed_ms:Math.round(performance.now()-start),error:error?'transport_error':null,failed,response_summary:!auth?{code,message:text(response?.message||response?.msg||''),success:typeof response?.success==='boolean'?response.success:null,data_type:Array.isArray(response?.data)?'array':typeof response?.data,data_count:Array.isArray(response?.data)?response.data.length:null}:{},response_body:response??body,response_capture:body===null?"unavailable":"captured",params:{query,body:parameters(data)}});
 };
 const originalFetch=window.fetch;
 if(originalFetch)window.fetch=async function(input,init){const method=init?.method||input?.method||'GET',u=input?.url||input,start=performance.now();try{const requestBody=init?.body??(typeof Request!=='undefined'&&input instanceof Request?await input.clone().text().catch(()=>null):null);const response=await originalFetch.apply(this,arguments);if(true)response.clone().text().then(body=>record(method,u,start,response.status,body,null,requestBody)).catch(()=>record(method,u,start,response.status,null,null,requestBody));else record(method,u,start,response.status,null,null,requestBody);return response}catch(e){record(method,u,start,0,null,true,init?.body);throw e}};
 const originalOpen=XMLHttpRequest.prototype.open,originalSend=XMLHttpRequest.prototype.send,meta=new WeakMap();
 XMLHttpRequest.prototype.open=function(method,u){meta.set(this,{method,u});return originalOpen.apply(this,arguments)};
 XMLHttpRequest.prototype.send=function(data){const m=meta.get(this);if(m){m.start=performance.now();this.addEventListener('loadend',()=>{let body=null;try{body=this.responseType==='json'?this.response:this.responseText}catch{}record(m.method,m.u,m.start,this.status,body,this.status===0,data)},{once:true})}return originalSend.apply(this,arguments)};
 addEventListener('error',e=>{const message=String(e.message||'resource_load_error');emit({kind:'javascript_error',message:sensitive.test(message)?'[redacted]':text(message)})});
 addEventListener('unhandledrejection',()=>emit({kind:'javascript_error',message:'unhandled_promise_rejection'}));
 addEventListener('flutterInAppWebViewPlatformReady',flush);
 setInterval(tick,500);tick();
})();
