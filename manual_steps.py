"""Additional custom-step actions using the existing H5 execution boundary."""
import time
import automation
import hybrid_webview
import case_runner

ACTIONS = hybrid_webview.WEB_ACTIONS | {'wait_for', 'app_back', 'web_wait_for'}


def validate(step):
    if step.get('action') == 'web_wait_for':
        case_runner.validate_plan({'steps':[dict(step,action='web_assert')]},require_assertion=False)
        if not 1 <= float(step.get('timeout',30)) <= 60:
            raise ValueError('H5 等待时间需为 1～60 秒')
    elif step.get('action') in hybrid_webview.WEB_ACTIONS:
        case_runner.validate_plan({'steps': [step]}, require_assertion=False)
    elif step.get('action') == 'wait_for':
        if step.get('by', 'accessibility id') not in ('accessibility id', 'id', 'xpath', '-android uiautomator', '-ios predicate string'):
            raise ValueError('不支持的等待定位方式')
        if not isinstance(step.get('value'), str) or not step['value'].strip():
            raise ValueError('等待步骤需指定 value')
        if not 1 <= float(step.get('timeout', 20)) <= 60:
            raise ValueError('控件等待时间需为 1～60 秒')


def perform(explorer, step, sleep):
    validate(step)
    if step['action'] == 'app_back':
        explorer.back(automation.parse_ui(explorer.source()))
        return {'action':'app_back'}
    if step['action'] == 'web_wait_for':
        deadline=time.monotonic()+float(step.get('timeout',30))
        with hybrid_webview.WebView(explorer) as web:
            while True:
                if explorer.stopped():raise RuntimeError('测试已停止')
                try:
                    result=web.perform(dict(step,action='web_assert'))
                    return dict(result,action='web_wait_for')
                except AssertionError:
                    if time.monotonic()>=deadline:raise
                    sleep(.5)
    if step['action'] in hybrid_webview.WEB_ACTIONS:
        with hybrid_webview.WebView(explorer) as web:
            return web.perform(step)
    deadline = time.monotonic() + float(step.get('timeout', 20))
    while True:
        if explorer.stopped():
            raise RuntimeError('测试已停止')
        # Transport/session failures must propagate rather than look like absence.
        found = explorer.call('POST', explorer.base + '/elements', {
            'using': step.get('by', 'accessibility id'), 'value': step['value']})
        if found:
            return {'action': 'wait_for', 'matched': True}
        if time.monotonic() >= deadline:
            raise AssertionError('等待控件超时：' + step['value'])
        sleep(.5)
