"""Versioned native module scripts. No model calls or replayed element IDs."""
import hashlib
import json
import re
import time
import os
import tempfile
from pathlib import Path

BY = ('accessibility id', 'id', '-android uiautomator', '-ios predicate string')


def validate(document):
    if not isinstance(document, dict):
        raise ValueError('模块必须是 JSON 对象')
    if not isinstance(document.get('name'), str) or not document['name'].strip():
        raise ValueError('请填写模块名称')
    steps = document.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 200:
        raise ValueError('模块需要 1～200 个步骤')
    for step in steps:
        if not isinstance(step, dict) or step.get('action') not in ('tap', 'assert', 'input', 'back'):
            raise ValueError('模块首版支持 tap、assert、input、back')
        if set(step) - {'action', 'by', 'value', 'parameter', 'timeout'}:
            raise ValueError('模块步骤包含不支持的字段；输入请使用 parameter')
        timeout = step.get('timeout', 8)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise ValueError('步骤 timeout 需大于 0 且不超过 60 秒')
        if step['action'] != 'back':
            if step.get('by', 'accessibility id') not in BY or not isinstance(step.get('value'), str) or not step['value'].strip():
                raise ValueError('请指定稳定控件定位方式和 value')
        if step['action'] == 'input' and (not isinstance(step.get('parameter'), str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}', step['parameter'])):
            raise ValueError('输入步骤需要 parameter 参数名')
    if steps[-1]['action'] != 'assert':
        raise ValueError('模块最后一步必须为 assert，确认结束状态')
    return {'name': document['name'].strip()[:100], 'steps': steps}


def save(root, document, run_id=None, confirmed=False):
    document = validate(document)
    if confirmed is not True:
        raise ValueError('请手动确认运行稳定后再存入脚本库')
    if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{12}', run_id):
        raise ValueError('请选择本模块的成功运行记录')
    try:
        report = json.loads((Path(root) / 'reports' / run_id / 'report.json').read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        raise ValueError('运行报告不存在或尚未完成') from None
    if report.get('status') != 'passed' or not report.get('finished') or report.get('stop_requested'):
        raise ValueError('仅完整成功的运行可手动确认存入')
    if report.get('module_candidate') != document:
        raise ValueError('JSON 已变化，请重新运行后确认')
    results = report.get('custom_step_results', [])
    if len(results) != len(document['steps']) or any(r.get('step') != i or r.get('status') != 'passed' for i, r in enumerate(results, 1)):
        raise ValueError('运行步骤未全部成功，不能存入')
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True)
    identifier = hashlib.sha256(raw.encode()).hexdigest()[:24]
    folder = Path(root) / '.runtime/module-scripts'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (identifier + '.json')
    # Identical content is immutable and safe for concurrent saves.
    if not target.exists() or not json.loads(target.read_text(encoding='utf-8')).get('confirmation'):
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder, delete=False) as stream:
            temp = stream.name
            stream.write(json.dumps(dict(document, confirmation={'run_id':run_id,'confirmed_at':time.strftime('%Y-%m-%d %H:%M:%S')}),ensure_ascii=False,sort_keys=True))
        try:
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return load(root, identifier)


def load(root, identifier):
    if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{24}', identifier):
        raise ValueError('无效模块标识')
    try:
        stored = json.loads((Path(root) / '.runtime/module-scripts' / (identifier + '.json')).read_text(encoding='utf-8'))
        document = validate(stored)
    except FileNotFoundError:
        raise ValueError('模块不存在') from None
    if not isinstance(stored.get('confirmation'), dict) or not stored['confirmation'].get('run_id'):
        raise ValueError('旧模块尚未手动确认，请重新试运行后存入')
    return dict(document, id=identifier, status='manually_confirmed', confirmation=stored['confirmation'])


def listing(root):
    folder = Path(root) / '.runtime/module-scripts'
    documents = []
    for path in sorted(folder.glob('*.json')):
        try:documents.append(load(root, path.stem))
        except (ValueError, OSError):continue
    return documents


def prepare(root, cfg):
    if cfg.get('module_id') and cfg.get('module_draft') is not None:
        raise ValueError('请选择已保存模块或新 JSON 试运行')
    document = validate(cfg['module_draft']) if cfg.get('module_draft') is not None else load(root, cfg.get('module_id'))
    document = dict(document, id=document.get('id','trial'), status=document.get('status','trial'))
    params = cfg.get('module_parameters', {})
    if not isinstance(params, dict):
        raise ValueError('模块参数必须是对象')
    for step in document['steps']:
        if step['action'] == 'input':
            value = params.get(step['parameter'])
            if not isinstance(value, str) or not value:
                raise ValueError('缺少模块参数：' + step['parameter'])
    cfg.update(test_mode='manual', step_format='json', steps=document['steps'], module_script=document)


def perform(call, base, step, parameters, sleep, stopped):
    started = time.monotonic()
    action = step['action']
    if stopped():
        raise RuntimeError('测试已停止')
    if action == 'back':
        call('POST', base + '/back', {})
    else:
        deadline = started + step.get('timeout', 8)
        while True:
            if stopped():
                raise RuntimeError('测试已停止')
            # Only read-only absence is retried. Transport errors propagate.
            elements = call('POST', base + '/elements', {'using': step.get('by', 'accessibility id'), 'value': step['value']})
            if len(elements) > 1:
                raise AssertionError('模块控件定位不唯一')
            if elements:
                element = elements[0]
                eid = element.get('element-6066-11e4-a52e-4f735466cecf') or element.get('ELEMENT')
                if not eid:
                    raise RuntimeError('驱动未返回控件标识')
                visible = call('GET', base + '/element/' + eid + '/displayed')
                enabled = action == 'assert' or call('GET', base + '/element/' + eid + '/enabled')
                if visible and enabled:
                    break
            if time.monotonic() >= deadline:
                raise AssertionError('等待模块控件就绪超时')
            sleep(.2)
        if stopped():
            raise RuntimeError('测试已停止')
        if action == 'tap':
            call('POST', base + '/element/' + eid + '/click', {})
        elif action == 'input':
            call('POST', base + '/element/' + eid + '/clear', {})
            call('POST', base + '/element/' + eid + '/value', {'text': parameters[step['parameter']]})
    return {'action': action, 'elapsed_ms': round((time.monotonic() - started) * 1000), 'status': 'passed'}
