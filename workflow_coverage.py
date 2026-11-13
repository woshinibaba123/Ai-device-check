"""Explicit coverage ledger; an action or terminal model claim is not proof."""
import re


def requirements(goal):
    rows=[{'id':'step_'+number,'requirement':text.strip(),'status':'pending'}
          for number,text in re.findall(r'(?m)^\s*(\d+)[.、]\s*(.+)$',goal)]
    if '距离、机型、区域、任务数筛选' in goal:
        filters=[{'id':'filter_'+key,'requirement':name+'筛选：实际选择可用条件，确认结果变化，再恢复原条件；不可只检查其他筛选后概括通过。','status':'pending'}
                 for key,name in [('distance','距离'),('model','机型'),('region','行政区'),('task','任务数')]]
        # Keep the final navigation check last for resume verification.
        rows[max(0,len(rows)-1):max(0,len(rows)-1)]=filters
    if '/reportRecord' in goal and '周报、月报、年报' in goal:
        checks=[('date','日期控件：实际前后切换或选择不同日期，核对结果后恢复原日期；周期Tab切换不能代替日期控件测试。'),
                ('business','报告类型：选择实际业务类型，核对并恢复原条件；不要把报告类型称为设备编号。'),
                ('week','周报：核对周报选中状态、范围和统计内容。'),
                ('month','月报：实际切换月报并核对范围和统计内容。'),
                ('year','年报：实际切换年报并核对范围和统计内容。')]
        rows[max(0,len(rows)-1):max(0,len(rows)-1)]=[{'id':'report_'+key,'requirement':text,'status':'pending'} for key,text in checks]
    if re.search(r'每种.*语言|逐.*语言|多语言',goal):
        for name,pattern in [('日语',r'日语|日、'),('韩语',r'韩语|韩、'),('法语',r'法语|法、'),('泰语',r'泰语|泰、'),('繁体',r'繁体')]:
            if re.search(pattern,goal):
                rows.append({'id':'language_'+name,'requirement':name+'：切换后核对选中项、根导航和功能入口；点击成功不算通过','status':'pending'})
    return rows


def record(rows,updates,round_number):
    if not isinstance(updates,list):return
    for update in updates:
        if not isinstance(update,dict):continue
        row=next((r for r in rows if r['id']==update.get('id')),None)
        evidence=update.get('evidence')
        # Done itself cannot certify a workflow. Require separate observations
        # from earlier rounds and preserve their provenance in the report.
        if row is None or update.get('status') not in ('observed','blocked') or not isinstance(evidence,str) or len(evidence.strip())<8:continue
        if update['status']=='observed' and re.search(r'待(?:后续|核对|确认|验证)|尚未(?:核对|确认|验证)|归属.*待',evidence):
            continue
        row.update(status=update['status'],evidence=evidence[:1500],round=round_number,provenance='visual_model_observation')
    reconcile(rows)


def reconcile(rows):
    """Summaries follow their individual evidence, never override it."""
    groups=[('距离、机型、区域、任务数筛选',['filter_'+k for k in ('distance','model','region','task')],'filter'),
            ('日期、报告类型或设备筛选',['report_date','report_business'],'report'),
            ('逐一切换当前页面实际提供的日报、周报、月报、年报',['report_week','report_month','report_year'],'report')]
    for marker,identifiers,kind in groups:
        group=next((r for r in rows if marker in r.get('requirement','')),None)
        parts=[next((r for r in rows if r['id']==key),None) for key in identifiers]
        if group is None or not all(parts):continue
        if any(r['status']=='pending' for r in parts):
            group['status']='pending'
            for field in ('evidence','round','provenance'):group.pop(field,None)
            continue
        group.update(status='observed' if all(r['status']=='observed' for r in parts) else 'blocked',
                     evidence='；'.join(r['requirement'].split('：')[0]+'：'+r.get('evidence','') for r in parts)[:1500],
                     provenance='aggregated_explicit_'+kind+'_observations')


def pending(rows):
    return [r for r in rows if r['status']=='pending']
