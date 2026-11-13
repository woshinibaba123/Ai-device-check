"""Observed navigation timings, API failures and anomaly-only capture decisions."""
import json
import re
import time
from pathlib import Path
import automation
import diagnostic_privacy as privacy
import hybrid_webview

ERROR_TEXT=re.compile(r'页面加载失败|加载出错|服务异常|服务器错误|网络异常|请求失败|无法访问|ERR_(?:CONNECTION|NAME|TIMED)|Internal Server Error|Application error|Something went wrong|ページを読み込め',re.I)

class ContextRestoreError(RuntimeError):pass


class Monitor:
    def __init__(self,explorer,job,folder,active,log,clock=time.monotonic):
        self.e=explorer;self.job=job;self.folder=Path(folder);self.active=active;self.log=log;self.clock=clock
        self.busy=False;self.context='NATIVE_APP';self.pending=None;self.last=None;self.blank_since=None
        self.sensitive=False;self.recent_errors=[];self.action_starts=[];self.webview_creations={}
        self.last_collect=-100;self.seen=set();self.issue_keys=set();self.current_issues=[];self.rect=None;self.geometry_since={}
        self.result={'webview_transitions':[],'navigation':[],'native_route_frames':[],'webview_loads':[],'api_events':[],'api_errors':[],'issues':[],
                     'coverage':{'native':'source_observer_required','h5':'xhr_fetch_and_visible_dom','timings':'observed_action_to_content_upper_bound','visual':'blank_error_and_geometry_heuristics_not_full_visual_validation'},'dropped_events':0}
        job['diagnostics']=self.result

    def enabled(self):
        return not self.busy and self.active() and not self.e.stopped()

    def native_page(self,label):
        """Explicit visual evidence for a native page, even without a UIA tree."""
        reader=getattr(self.e,'route_reader',None)
        route=reader.read() if reader else ''
        self.last={'identity':(route,(),False),'route':route,'webview':False,
                   'signature':label,'page_label':label,'identity_source':'native_route_observer' if route else 'visual_native_page'}

    def before(self,method,path,data):
        if not self.enabled() or method!='POST':return
        script=(data or {}).get('script','') if isinstance(data,dict) else ''
        action=path.endswith('/click') or path.endswith('/back') or path.endswith('/actions') or path.endswith('/execute/sync') and (script in ('mobile: clickGesture','mobile: tap') or re.search(r'\be\.click\(',script))
        if action:
            if self.pending:self.finish_pending('readiness_not_observed_before_next_action')
            calibration=None
            probe=getattr(self.e,'web_probe',None) or getattr(self.e,'diagnostic_clock',None)
            if probe and hasattr(probe,'device_clock'):
                try:calibration=probe.device_clock()
                except Exception:pass
            started=self.clock()
            if calibration:
                # Convert the action boundary to device time; never subtract unsynchronised clocks.
                epoch=calibration['epoch_ms']+(time.monotonic()-calibration['monotonic'])*1000
                self.action_starts.append({'epoch_ms':epoch,'from':(self.last or {}).get('route') or (self.last or {}).get('page_label',''),
                                           'native':bool(self.last and not self.last.get('webview')),
                                           'clock_uncertainty_ms':calibration['uncertainty_ms']})
                self.action_starts=self.action_starts[-1000:]
            self.pending={'start':started,'native_entry':bool(self.last and not self.last.get('webview')),'before':self.last,'webview_seen':None,'action':'back' if path.endswith('/back') else 'gesture' if path.endswith('/actions') else 'tap'}

    def after(self,method,path,data,value):
        if self.busy:return
        if method=='POST' and path.endswith('/context') and isinstance(data,dict):self.context=data.get('name','NATIVE_APP')
        if self.pending and self.context.startswith('WEBVIEW') and self.pending['webview_seen'] is None:self.pending['webview_seen']=self.clock()
        script=(data or {}).get('script','') if isinstance(data,dict) else ''
        action=method=='POST' and (path.endswith(('/click','/actions','/back')) or path.endswith('/execute/sync') and script in ('mobile: clickGesture','mobile: tap'))
        if action and self.enabled() and self.pending and not self.pending.get('early_frame_sampled') and getattr(self.e,'platform','')=='Android' and isinstance(getattr(self.e,'device_id',None),str) and self.e.device_id:
            self.pending['early_frame_sampled']=True
            try:
                from android_visual import AndroidVisual
                AndroidVisual(self.e).screenshot()
            except (OSError,ValueError,RuntimeError):self.log('页面跳转早期采样失败，后续观察继续。')
        if self.enabled() and self.context=='NATIVE_APP' and method=='GET' and path.endswith('/source') and isinstance(value,str):
            self.observe(value)

    def observe_h5(self, data):
        if not isinstance(data,dict):return
        self.result['coverage']['h5']='observed'
        if isinstance(self.job.get('capabilities'),dict):
            self.job['capabilities']['network_observer']='h5_runtime_observed'
        self.collect()
        for event in data.get('events',[]):self.event(event,'h5','runtime')
        route=privacy.route(data.get('route',''))
        sample=data.get('sample') or {}
        current={'identity':(route,(),True),'route':route,'webview':True,'signature':route}
        if self.pending:
            if self.pending['webview_seen'] is None:self.pending['webview_seen']=self.clock()
            self.pending['observed']=current
            before=self.pending['before']
            if data.get('ready') and sample.get('content') and not sample.get('loading') and not sample.get('secure'):
                changed=before and (before.get('route')!=route or not before.get('webview'))
                self.finish_pending('content_ready' if changed else 'same_page_ready',current)
        self.last=current
        self.persist()

    def observe_frame(self,png):
        """Capture an observed blank transition immediately, without a UIA read."""
        if not self.enabled() or self.sensitive or not self.pending:return
        import io
        from PIL import Image
        with Image.open(io.BytesIO(png)) as image:
            w,h=image.size
            content=image.convert('RGB').crop((0,int(h*.08),w,int(h*.94)))
            sample=content.resize((96,160))
            white=sum(min(pixel)>=245 for pixel in sample.getdata())/15360
            if white<.995:return
            token=self.pending['start']
            if getattr(self,'_blank_frame_token',None)==token:return
            self._blank_frame_token=token
            route=(self.last or {}).get('route','')
            name='blank-transition-'+str(len(self.result['issues']))+'.jpg'
            self.folder.mkdir(parents=True,exist_ok=True)
            if content.width>1080:content=content.resize((1080,round(content.height*1080/content.width)))
            content.save(self.folder/name,'JPEG',quality=80)
        url='/reports/'+self.job['id']+'/'+name
        issue={'type':'transition_blank_frame','route':route,'evidence':'操作后采样到内容区域超过99.5%为白色；单帧不能证明持续时长或加载失败',
               'severity':'suspected','screenshot':url,'screenshot_status':'captured',
               'action_to_sample_ms':round((self.clock()-token)*1000,1),'measurement':'sampled_blank_frame_not_duration',
               'page_context':'跳转前最后观察页面；目标路由尚未确认'}
        self.result['issues'].append(issue)
        self.job.setdefault('screenshots',[]).append(url)
        self.job.setdefault('screenshot_records',[]).append({'url':url,'route':route,'abnormal':True,'issues':['transition_blank_frame']})
        self.log('页面跳转白屏已截图：'+url+'（单帧观察，持续时间未确认）')
        self.persist()

    def capture_feedback_frame(self,png,evidence,kind='action_error_feedback',source='post_action_screenshot_ocr',severity='error'):
        if not self.enabled() or self.sensitive:return
        import io
        from PIL import Image
        name='action-error-'+str(len(self.result['issues']))+'.jpg'
        self.folder.mkdir(parents=True,exist_ok=True)
        with Image.open(io.BytesIO(png)) as image:
            image=image.convert('RGB')
            if image.width>1080:image=image.resize((1080,round(image.height*1080/image.width)))
            image.save(self.folder/name,'JPEG',quality=80)
        url='/reports/'+self.job['id']+'/'+name
        route=(self.last or {}).get('route','')
        self.result['issues'].append({'type':kind,'route':route,'evidence':evidence[:500],'source':source,'screenshot':url,'screenshot_status':'captured','severity':severity})
        self.job.setdefault('screenshots',[]).append(url)
        self.job.setdefault('screenshot_records',[]).append({'url':url,'route':route,'abnormal':True,'issues':[kind]})
        self.persist()

    def capture_blocked_observation(self,png,observation):
        key=('workflow_check_blocked',observation.get('id'))
        if key in self.issue_keys:return
        if not self.enabled() or self.sensitive:return
        evidence=observation.get('evidence','')
        if not isinstance(evidence,str) or len(evidence.strip())<8:return
        self.capture_feedback_frame(png,privacy.clean(evidence,self.e.secrets),
                                    kind='workflow_check_blocked',source='visual_model_observation',severity='suspected')
        self.issue_keys.add(key)

    def capture_recent_api_error_frame(self,png):
        if not self.enabled() or self.sensitive:return
        route=(self.last or {}).get('route','')
        for event in self.result['api_errors'][-10:]:
            epoch=event.get('epoch_ms')
            if not isinstance(epoch,(int,float)) or not 0<=time.time()*1000-epoch<=10000:continue
            if not route or event.get('route')!=route:continue
            key=('api_error_frame',event.get('url'),epoch)
            if key in self.issue_keys:continue
            evidence='%s %s HTTP=%s code=%s'%(event.get('method'),event.get('url'),event.get('http_status'),event.get('code'))
            self.capture_feedback_frame(png,evidence,kind='api_error_page',source='recent_api_error_current_route')
            self.issue_keys.add(key)

    def issue(self,kind,evidence,route='',current=True):
        key=(kind,route)
        if current:self.current_issues.append(kind)
        if key in self.issue_keys:return
        self.issue_keys.add(key)
        event={'type':kind,'route':privacy.clean(route,self.e.secrets),'evidence':evidence,'screenshot_status':'pending_capture' if current else 'awaiting_current_page_observation','severity':'suspected' if kind in ('blank_screen_suspected','loading_stalled','horizontal_overflow','control_clipped','text_clipped') else 'error'}
        self.result['issues'].append(event);self.log('页面异常'+('疑点' if event['severity']=='suspected' else '')+'：'+kind+' '+event['route'])

    def collect_native_routes(self):
        reader=getattr(self.e,'route_reader',None)
        if not reader:return
        reader.read()
        latest=getattr(reader,'latest',{})
        for event in latest.get('events',[]):
            key=('native_route',latest.get('run'),event.get('route'),event.get('route_started_us'))
            if key in self.seen:continue
            self.seen.add(key)
            row={'from':privacy.route(event.get('from','')),'route':privacy.route(event.get('route','')),
                 'route_to_first_frame_ms':event.get('route_to_first_frame_ms'),
                 'measurement':'flutter_navigator_callback_to_next_frame'}
            self.result['native_route_frames'].append(row)
            self.result['coverage']['native_routes']='observed'

    def collect(self,force=False):
        now=self.clock()
        if not force and now-self.last_collect<1:return
        self.last_collect=now
        self.collect_native_routes()
        for attr,source in (('http_probe','native'),('web_probe','h5')):
            probe=getattr(self.e,attr,None)
            if not probe:continue
            try:
                data=probe.read();self.result['coverage'][source]='observed' if source!='native' or probe.manifest.get('diagnostics_version') else 'legacy_observer_without_latency_or_parameters'
                for event in data.get('events',[]):self.event(event,source,str(data.get('run','')))
            except Exception:
                self.result['coverage'][source]='observer_present_no_readable_events'

    def event(self,event,source,run=''):
        if not isinstance(event,dict):return
        key=(source,run,event.get('request_seq'),event.get('id'),event.get('epoch_ms'),event.get('kind','api'),event.get('url',event.get('path')),event.get('issue'))
        if key in self.seen:return
        self.seen.add(key)
        kind=event.get('kind','api')
        if kind=='api':
            record=privacy.api_event(event,self.e.secrets);record['source']=source
            record['observed_at']=time.strftime('%Y-%m-%d %H:%M:%S')
            status=record.get('http_status');code=record.get('code')
            success={str(c) for c in getattr(getattr(self.e,'http_probe',None),'manifest',{}).get('success_codes',[0,610000])}
            if source=='h5':success.add('200')
            failed=bool(record['error']) or isinstance(status,int) and (status==0 or status>=400) or code is not None and str(code) not in success
            record['failed']=failed;self.result['api_events'].append(record)
            if failed:
                self.log('接口调用原文：'+json.dumps(record,ensure_ascii=False,default=str))
                self.result['api_errors'].append(record)
                if isinstance(event.get('epoch_ms'),(int,float)):self.recent_errors.append((event['epoch_ms'],record['route'],'api_error'))
                self.log('接口异常：'+record['method']+' '+record['url']+' HTTP='+str(status)+' code='+str(code)+' 参数='+json.dumps(record['params'],ensure_ascii=False)+' 响应摘要='+json.dumps(record.get('response_summary',{}),ensure_ascii=False)+' 耗时='+str(record.get('elapsed_ms'))+'ms 页面='+record['route'])
        elif kind=='webview_created':
            self.webview_creations[(run,event.get('id'))]=dict(event)
        elif kind=='h5_ready':
            fields=('webview_created_to_h5_ready_ms','route_to_content_ms','dom_content_loaded_ms','document_load_ms')
            row={k:event[k] for k in fields if isinstance(event.get(k),(float,int)) and 0<=event[k]<=1800000}
            row.update(route=privacy.route(event.get('route','')),late_attach=event.get('late_attach') is True,readiness='visible_content_stable_300ms',source='native_webview_js_bridge')
            self.result['webview_loads'].append(row)
            created=self.webview_creations.pop((run,event.get('id')),None)
            if created and isinstance(created.get('epoch_ms'),(int,float)) and isinstance(event.get('epoch_ms'),(int,float)):
                creation=created['epoch_ms'];ready_at=event['epoch_ms']
                candidates=[a for a in self.action_starts if a['epoch_ms']<=creation]
                action=candidates[-1] if candidates else None
                if action and action['native'] and 0<=ready_at-creation<=1800000 and creation-action['epoch_ms']<=1800000:
                    jump=creation-action['epoch_ms'];load=ready_at-creation
                    self.result['webview_transitions'].append({'from':action['from'],'to':row['route'],
                        'action_to_webview_ms':round(jump,1),'webview_to_h5_content_ms':round(load,1),
                        'total_ms':round(jump+load,1),'clock_uncertainty_ms':action['clock_uncertainty_ms'],
                        'webview_id':event.get('id'),'late_attach':row['late_attach'],
                        'measurement':'action_start_to_webview_creation_to_visible_content_stable_300ms'})
            timings='，'.join(label+'='+str(row[key])+' ms' for key,label in (
                ('webview_created_to_h5_ready_ms','创建至内容就绪'),('route_to_content_ms','路由至内容就绪'),
                ('dom_content_loaded_ms','DOMContentLoaded'),('document_load_ms','load')) if key in row)
            self.log('WebView 打开耗时：'+row['route']+' '+(timings or '未取得有效计时')+
                     ('（监控晚接入，非完整打开耗时）' if row['late_attach'] else '（内容稳定 300ms）'))
        elif kind in ('javascript_error','ui_issue'):
            name=event.get('issue') if kind=='ui_issue' else 'javascript_error'
            if name in ('visible_error_message','horizontal_overflow','control_clipped','text_clipped','blank_screen_suspected','javascript_error'):
                self.issue(name,'h5_observer',privacy.route(event.get('route','')),current=False)
                if name=='javascript_error' and isinstance(event.get('epoch_ms'),(int,float)):self.recent_errors.append((event['epoch_ms'],privacy.route(event.get('route','')),name))
        for name in ('api_events','api_errors','issues','webview_loads'):
            if len(self.result[name])>3000:self.result[name]=self.result[name][-3000:];self.result['dropped_events']+=1

    def observe(self,source):
        if self.busy or not self.active():return
        self.busy=True
        try:
            nodes=automation.parse_ui(source)
            self.sensitive=any(n['secure'] for n in nodes)
            if self.sensitive:return
            self.current_issues=[]
            reader=getattr(self.e,'route_reader',None)
            route=reader.read() if reader else ''
            selected=tuple(n['label'] for n in nodes if n['selected'])
            is_web=any('WebView' in n['kind'] for n in nodes)
            self.collect()
            h5=None
            if is_web:
                if self.pending and self.pending['webview_seen'] is None:self.pending['webview_seen']=self.clock()
                try:
                    with hybrid_webview.WebView(self.e) as web:
                        # Fallback also supports installed debug builds lacking the native bridge.
                        web.js((Path(__file__).parent/'h5_diagnostics.js').read_text())
                        h5=web.js("const s=window.__devicecheckDiagnosticsV1;return {route:location.origin+location.pathname+location.hash.split('?')[0],ready:!!s?.ready,sample:s?.sample?.(),events:s?.events||[]}",read_only=True)
                    if h5:
                        route=privacy.route(h5.get('route',''))
                        self.sensitive=bool((h5.get('sample') or {}).get('secure'))
                        if self.last and self.last['route']!=route:self.geometry_since.clear()
                        kinds=(h5.get('sample') or {}).get('issues',[])
                        for key in list(self.geometry_since):
                            if key[0]==route and key[1] in ('horizontal_overflow','control_clipped','text_clipped') and key[1] not in kinds:self.geometry_since.pop(key,None)
                        for name in kinds:
                            if name in ('horizontal_overflow','control_clipped','text_clipped'):
                                started=self.geometry_since.setdefault((route,name),self.clock())
                                if self.clock()-started<1:continue
                            self.issue(name,'current_dom',route)
                        if not getattr(self.e,'web_probe',None):
                            for event in h5.get('events',[]):self.event(event,'h5','runtime')
                except Exception:
                    try:self.e.call('POST',self.e.base+'/context',{'name':'NATIVE_APP'})
                    except Exception as error:raise ContextRestoreError('监控读取 H5 后无法恢复原生上下文，已停止避免误操作') from error
                    self.result['coverage']['h5']='webview_driver_unavailable_or_context_unreadable'
            labels=[n['label'] for n in nodes if n['label'] and not n['editable'] and n.get('package')!='com.android.systemui']
            if ERROR_TEXT.search('\n'.join(labels)):self.issue('visible_error_message','native_error_text_pattern',route)
            content=bool(labels) if not is_web else bool(h5 and (h5.get('sample') or {}).get('content'))
            if not content and (not is_web or h5 is not None):
                if self.blank_since is None:self.blank_since=self.clock()
                loading=bool(h5 and (h5.get('sample') or {}).get('loading')) or any('ProgressBar' in n['kind'] for n in nodes)
                if self.clock()-self.blank_since>=(30 if loading else 10):self.issue('loading_stalled' if loading else 'blank_screen_suspected','no_visible_content_after_wait',route)
            else:self.blank_since=None
            if not is_web:
                if self.last and self.last['route']!=route:self.geometry_since.clear()
                if self.rect is None:
                    try:self.rect=self.e.call('GET',self.e.base+'/window/rect')
                    except Exception:self.rect={}
                width=(self.rect or {}).get('width',0);height=(self.rect or {}).get('height',0)
                clipped=False
                for n in nodes:
                    b=re.fullmatch(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]',n.get('bounds',''))
                    if b and n['clickable'] and width and int(b[2])<height and int(b[4])>0 and int(b[1])<width and int(b[3])>0 and (int(b[1]) < -4 or int(b[3])>width+4):clipped=True
                key=(route,'native_control_clipped')
                if clipped:
                    started=self.geometry_since.setdefault(key,self.clock())
                    if self.clock()-started>=1:self.issue('control_clipped','native_control_outside_horizontal_viewport',route)
                else:self.geometry_since.pop(key,None)
            self.recent_errors=self.recent_errors[-100:]
            for epoch,error_route,name in self.recent_errors:
                if error_route and error_route==privacy.route(route) and 0<=time.time()*1000-epoch<=5000:self.issue(name,'recent_error_on_current_route',route)
            ready=content and (not is_web or h5 and h5.get('ready'))
            identity=(route,selected,is_web)
            current={'identity':identity,'route':privacy.clean(route,self.e.secrets),'selected':selected,'webview':is_web,'signature':automation.signature(nodes)}
            if self.pending:self.pending['observed']=current
            if self.pending and ready:
                before=self.pending['before']
                changed=before and (identity!=before['identity'] or current['signature']!=before['signature'])
                self.finish_pending('content_ready' if changed else 'same_page_ready',current)
            self.last=current
            self.persist()
        finally:self.busy=False

    def finish_pending(self,status,current=None):
        p=self.pending
        if not p:return
        self.pending=None
        if current is None:current=p.get('observed')
        if p['before'] is None:return
        row={'from':p['before']['route'],'to':current['route'] if current else None,'action':p['action'],'status':status,
             'action_to_content_ms':round((self.clock()-p['start'])*1000,1) if status=='content_ready' else None,
             'observed_elapsed_ms':round((self.clock()-p['start'])*1000,1),'measurement':'observed_upper_bound_including_driver_wait'}
        if current and current['webview']:
            row['type']='webview_navigation';row['observed_webview_to_content_ms']=round((self.clock()-p['webview_seen'])*1000,1) if p['webview_seen'] is not None else None
        else:row['type']='native_navigation' if current and current['identity']!=p['before']['identity'] else 'ui_state_change'
        self.result['navigation'].append(row)
        if p.get('native_entry') and current and current.get('webview') and status=='content_ready':
            self.result.setdefault('webview_observations',[]).append({'from':p['before'].get('route') or p['before'].get('page_label') or '原生页面（路由未采集）',
                'to':current['route'],'total_ms':row['action_to_content_ms'],
                'first_webview_observed_ms':round((p['webview_seen']-p['start'])*1000,1) if p.get('webview_seen') is not None else None,
                'measurement':'action_to_observed_h5_ready_upper_bound_including_driver_wait',
                'split_status':'requires_webview_creation_event_and_device_clock'})
        if status=='content_ready':
            self.log('页面切换耗时：'+row['from']+' → '+str(row['to'])+' '+str(row['action_to_content_ms'])+' ms（动作至观察到内容就绪，含驱动等待）')
            if row['type']=='webview_navigation':
                self.log('WebView 打开耗时（自动化观察）：'+str(row['to'])+' 动作至内容就绪='+str(row['action_to_content_ms'])+' ms，首次观察到 WebView 至内容就绪='+str(row['observed_webview_to_content_ms'])+' ms')
        elif status=='same_page_ready':
            self.log('已观察到当前页面内容就绪，未观察到页面切换：'+str(row['to']))
        else:
            self.log('页面切换计时未完成：'+row['from']+' 已等待 '+str(row['observed_elapsed_ms'])+' ms，未观察到新页面就绪（'+status+'）')

    def should_capture(self,name):
        if self.sensitive:return False
        forced=name==999 or bool(re.search(r'failure|failed|error|blocked',str(name),re.I))
        return forced or bool(self.current_issues)

    def persist(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/'diagnostics.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2))
        self.job['diagnostics_report']='/reports/'+self.job['id']+'/diagnostics.json'

    def note_capture(self,url):
        route=(self.last or {}).get('route','')
        if not self.current_issues:self.issue('execution_failure','failed_step_or_automation',route)
        for issue in self.result['issues']:
            if issue['type'] in self.current_issues and issue['route']==route:
                issue.update(screenshot=url,screenshot_status='captured')
        self.persist()

    def finalize(self):
        self.busy=True
        try:
            self.collect(force=True);self.finish_pending('readiness_not_observed_at_end')
            for issue in self.result['issues']:
                if not issue.get('screenshot'):issue['screenshot_status']='metadata_only_no_current_frame'
            self.persist()
        finally:self.busy=False
