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
    diagnostics=job.get('diagnostics') or {}
    operator=job.get('ai_operator') or {}
    text('异常记录',True)
    issues=list(diagnostics.get('issues',[]))
    issues+=list((job.get('exploration') or {}).get('issues',[]))
    issues+=list(diagnostics.get('api_errors',[]))
    screenshots={}
    for issue in issues:
        text('页面：'+str(issue.get('route') or issue.get('page') or '未取得页面标识'),error=True)
        text(json.dumps(issue,ensure_ascii=False),error=True)
        if issue.get('screenshot'):screenshots[issue['screenshot']]=issue.get('route') or issue.get('page') or '异常页面'
    for record in job.get('screenshot_records',[]):
        if record.get('abnormal'):screenshots[record['url']]=record.get('route') or record.get('page') or '异常页面'
    # Legacy runs have no screenshot metadata; retain only explicitly named failures.
    for url in job.get('screenshots',[]):
        if re.search(r'failure|failed|error|blocked|/999[.]',url,re.I):screenshots.setdefault(url,'异常现场（历史记录未提供页面标识）')
    abnormal_logs=[str(line) for line in job.get('logs',[]) if ERROR_LOG.search(str(line)) and not re.search(r'无异常|无错误|未发现异常|仅.*异常|异常.*截图|响应上限|未命中|无需',str(line))]
    for line in dict.fromkeys(abnormal_logs):text(line,error=True)
    if not issues and not abnormal_logs:text('未记录到异常；不代表所有业务检查均已通过。')
    if operator.get('termination_detail'):text('执行结束原因：'+str(operator['termination_detail']),error=True)
    text('页面耗时',True)
    text('自动化观察值包含驱动等待；未观察到就绪的记录不代表加载成功。')
    for group,label in [('navigation','页面切换'),('native_route_frames','原生首帧'),('webview_loads','WebView 加载')]:
        for row in diagnostics.get(group,[]):text(label+'：'+json.dumps(row,ensure_ascii=False))
    if not any(diagnostics.get(k) for k in ('navigation','native_route_frames','webview_loads')):text('本次未采集到页面耗时。')
    text('操作耗时',True)
    timed_steps=[step for step in operator.get('steps',[]) if step.get('timings')]
    for step in timed_steps:
        text('步骤 '+str(step.get('round',''))+' · 页面 '+str(step.get('route') or '未记录')+' · '+str(step.get('action',''))+' '+str(step.get('label') or '')+'：'+json.dumps(step['timings'],ensure_ascii=False))
    if not timed_steps:
        for line in job.get('logs',[]):
            if str(line).startswith('操作耗时：'):text(line)
    for url,page in screenshots.items():
        path=(root/url.lstrip('/')).resolve()
        if root.resolve() not in path.parents or not path.is_file():continue
        story.append(PageBreak());text('异常页面 · '+str(page),True)
        image=Image(str(path));scale=min(475/image.imageWidth,620/image.imageHeight)
        image.drawWidth=image.imageWidth*scale;image.drawHeight=image.imageHeight*scale
        story.append(image)
    def footer(c,doc):
        c.setFont(font_name,9);c.drawString(42,25,'DeviceCheck · '+job.get('id',''));c.drawRightString(550,25,str(doc.page))
    SimpleDocTemplate(str(output),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=45).build(story,onFirstPage=footer,onLaterPages=footer)

if __name__=='__main__':
    report=Path(sys.argv[1]);build(json.loads(report.read_text()),report.parents[2],report.with_suffix('.pdf'))
