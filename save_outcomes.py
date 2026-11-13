"""Record save failures without blocking subsequent test steps."""
import functools
import automation
import cancellation


def record(explorer, error):
    reason=automation.redact(str(error),explorer.secrets)
    row={'status':'failed_or_unconfirmed','reason':reason,'retried':False}
    failures=getattr(explorer,'save_failures',None)
    if not isinstance(failures,list):explorer.save_failures=[]
    explorer.save_failures.append(row)
    monitor=getattr(explorer,'diagnostics_monitor',None)
    if monitor is not None:
        monitor.job['save_failures']=explorer.save_failures
        monitor.result['save_failures']=explorer.save_failures
        monitor.persist()
    explorer.log('保存失败或结果未确认，已记录并继续后续流程；不重复提交：'+reason)
    return row


def nonblocking(fn):
    @functools.wraps(fn)
    def wrapped(web,*args,**kwargs):
        try:return fn(web,*args,**kwargs)
        except cancellation.Cancelled:raise
        except Exception as error:
            if web.e.stopped():raise
            return record(web.e,error)
    return wrapped
