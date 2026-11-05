"""Per-device PDF report; executed by the isolated PDF runtime."""
import json, re, sys
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor

ERROR_LOG=re.compile(r'异常|错误|失败|受阻|中断|超时|卡住|crash|error|exception|服务报错|HTTP 5|网络错误',re.I)


def build(job, root, output):
    font=Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    if font.is_file():pdfmetrics.registerFont(TTFont('ReportFont',str(font)))
    else:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    font_name='ReportFont' if font.is_file() else 'STSong-Light'
    style=ParagraphStyle('body',fontName=font_name,fontSize=11,leading=18,spaceAfter=9,wordWrap='CJK')
    error_style=ParagraphStyle('error_log',parent=style,textColor=HexColor('#d64541'))
    title=ParagraphStyle('title',parent=style,fontSize=21,leading=29,spaceAfter=20)
    story=[]
    def text(value, heading=False, error=False):story.append(Paragraph(escape(str(value)).replace('\n','<br/>'),title if heading else error_style if error else style))
    text('DeviceCheck 机型测试报告',True)
    text('机型 / 设备：'+str(job.get('label') or job.get('device','未知')))
    text('平台：'+job.get('platform','未知')+'    任务：'+job.get('id',''))
    text('状态：'+{'passed':'已完成配置范围','review':'待复核','failed':'失败','blocked':'受阻','stopped':'已停止'}.get(job.get('status'),job.get('status','未知')))
    text('开始：'+job.get('started','')+'    结束：'+job.get('finished',''))
    if job.get('language'):text('语言：'+json.dumps(job['language'],ensure_ascii=False))
    for key,label in [('profile','模拟配置'),('actual_environment','实际环境')]:
        if job.get(key):text(label+'：'+json.dumps(job[key],ensure_ascii=False))
    x=job.get('exploration',{})
    reasons={'return_mismatch':'返回后页面状态不一致（旧版在此停止）','reachable_controls_exhausted':'当前可达控件探索完毕','unreachable_pending_branches':'仍有入口未探索，返回路径恢复失败','action_limit':'达到操作次数上限','time_limit':'达到时间上限','no_accessible_controls':'未识别到交互控件','outside_app':'离开被测 App','page_tree_unavailable':'被测页面控件持续不可用，覆盖不完整','webview_context_failed':'无法恢复原生操作上下文，已停止探索','depth_limit':'达到深度上限','stopped':'用户停止','login_or_secure_form':'遇到登录或密码页','root_snapshot_unavailable':'首页路由已返回，但页面控件持续未就绪','startup_not_ready':'启动画面等待超时，首页未就绪','back_failed':'返回失败','popup_blocked':'弹窗未能关闭，需复核'}
    if x:
        text('探索结果',True)
        text(f"页面状态 {len(x.get('pages',[]))} 个；操作 {x.get('actions',0)} 次；结束原因：{reasons.get(x.get('termination'),x.get('termination',''))}")
        text(x.get('coverage_note',''))
        if job.get('device','').startswith('emulator-') and not job.get('profile'):text('本次记录仅包含本机模拟器编号，未记录品牌机型，不能归为具体品牌机型测试。')
        coverage=x.get('source_coverage',{})
        if coverage.get('route_count'):
            text('源码页面覆盖',True)
            text('源码路由 '+str(coverage['route_count'])+' 个；观察到跳转 '+str(len(coverage.get('visited_routes',[])))+' 个。路由记录和页面展示均不代表业务测试通过。')
            if coverage.get('route_details'):
                names={'displayed':'已采集页面','observed':'仅观察到跳转','protected':'敏感输入已跳过','excluded':'按规则跳过','startup_unobserved':'启动流程未记录','not_observed':'本次未观察到'}
                for route in coverage['route_details']:
                    text(names.get(route['status'],route['status'])+'：'+route['path']+' · '+route.get('page','')+' · '+route['reason'])
                text(coverage.get('h5_note',''))
            else:
                for route in coverage.get('visited_routes',[]):text('观察到：'+route)
                for route in coverage.get('unvisited_routes',[]):text('本次未记录：'+route['path']+' · '+route.get('page','')+'（具体原因未逐项验证）')
        for popup in x.get('popup_dismissals',[]):text('弹窗处理：'+json.dumps(popup,ensure_ascii=False))
        for note in x.get('observations',[]):text('页面观察及所需条件：'+json.dumps(note,ensure_ascii=False))
        for form in x.get('forms',[]):text('表单填写与提交：'+json.dumps(form,ensure_ascii=False))
        for issue in x.get('issues',[]):
            kind=issue.get('type',issue.get('action',''))
            category='测试数据或表单适配' if kind=='auto_form' else '返回及恢复记录' if kind in ('back','popup_recovered','foreground_recovered') else '执行待复核'
            text(category+'：'+json.dumps(issue,ensure_ascii=False))
        skipped=x.get('skipped',[])
        missing_labels={}
        for skip in skipped:
            if str(skip.get('reason','')).startswith('缺少可读标识'):
                missing_labels.setdefault(str(skip.get('page','')),[]).append(str(skip.get('label','')))
        reported_missing=set()
        for skip in skipped:
            page=str(skip.get('page',''))
            if str(skip.get('reason','')).startswith('缺少可读标识'):
                if page in reported_missing:continue
                reported_missing.add(page)
                labels=missing_labels[page]
                detail='、'.join(labels[:5])+(' 等' if len(labels)>5 else '')
                text('未覆盖：'+page+' 共 '+str(len(labels))+' 个控件缺少可读标识，需补充可访问性标识（'+detail+'）')
            else:
                text('未覆盖：'+json.dumps(skip,ensure_ascii=False))
        for edge in x.get('transitions',[]):text('路径：'+json.dumps(edge,ensure_ascii=False))
    text('执行日志',True)
    for line in job.get('logs',[]):text(line,error=bool(ERROR_LOG.search(str(line))))
    seen=set()
    for url in job.get('screenshots',[]):
        if url in seen:continue
        seen.add(url)
        path=(root/url.lstrip('/')).resolve()
        if root.resolve() not in path.parents or not path.is_file():continue
        story.append(PageBreak());text('页面截图 · '+path.stem,True)
        image=Image(str(path));scale=min(475/image.imageWidth,650/image.imageHeight)
        image.drawWidth=image.imageWidth*scale;image.drawHeight=image.imageHeight*scale
        story.append(image)
    def footer(c,doc):
        c.setFont(font_name,9);c.drawString(42,25,'DeviceCheck · '+job.get('id',''));c.drawRightString(550,25,str(doc.page))
    SimpleDocTemplate(str(output),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=45).build(story,onFirstPage=footer,onLaterPages=footer)

if __name__=='__main__':
    report=Path(sys.argv[1]);build(json.loads(report.read_text()),report.parents[2],report.with_suffix('.pdf'))
