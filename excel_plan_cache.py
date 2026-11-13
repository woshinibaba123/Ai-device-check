"""Content-addressed complete candidates, never execution/pass results."""
import hashlib
import json
import time
from pathlib import Path

VERSION = 'excel-fast-v11-core-evidence-and-list-observation'
EXCLUDED = {'node_modules', '.git', '.runtime', '.fvm', 'build', 'dist', '.dart_tool'}


def stamp(config):
    """Cheap mutation guard between full content fingerprints."""
    rows=[]
    for key,folders in (('source',('lib','assets/i18n')),('h5_source',('src',))):
        if not config.get(key):continue
        root=Path(config[key]).expanduser()
        files=[root/name for name in ('pubspec.yaml','package.json')]
        for folder in folders:
            base=root/folder
            if base.is_dir():files.extend(p for p in base.rglob('*') if p.suffix in ('.dart','.json','.vue','.js','.ts') and not any(x in EXCLUDED for x in p.relative_to(root).parts))
        for path in sorted(set(files)):
            if path.is_symlink() or not path.is_file():continue
            try:
                stat=path.stat();rows.append((key,str(path),stat.st_size,stat.st_mtime_ns))
            except OSError:rows.append((key,str(path),'unreadable'))
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def scope(config, *, legacy=False):
    digest = hashlib.sha256()
    settings = {k: config.get(k, '') for k in ('source', 'h5_source', 'include_source', 'model', 'region', 'target_language', 'call_acceptance','execution_mode','adapter_id','reference_flow','excel_observation_mode')}
    settings['excel_observation_mode']=config.get('excel_observation_mode',True) is not False
    if not settings.get('reference_flow'):settings.pop('reference_flow',None)
    if config.get('adapter_id'):
        import app_adapter
        settings['adapter_fingerprint']=app_adapter.signature(config['adapter_id'])
    # The generator model is not a dependency of an already validated plan.
    if not legacy:settings.pop('model')
    digest.update(json.dumps([VERSION, settings], sort_keys=True).encode())
    for key, folders in (('source', ('lib', 'assets/i18n')), ('h5_source', ('src',))):
        root = Path(config.get(key, '')).expanduser()
        if not config.get(key):
            continue
        files = [root / name for name in ('pubspec.yaml', 'package.json')]
        for folder in folders:
            base = root / folder
            if base.is_dir():
                files.extend(p for p in base.rglob('*') if p.suffix in ('.dart', '.json', '.vue', '.js', '.ts') and not any(x in EXCLUDED for x in p.relative_to(root).parts))
        for path in sorted(set(files)):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                digest.update(str(path.relative_to(root)).encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
            except OSError:
                # Unreadable source must not share a cache scope with readable source.
                digest.update(str(path).encode() + b':unreadable')
    return digest.hexdigest()


def cache_key(scope_key, case_key):
    return hashlib.sha256((scope_key + ':' + case_key).encode()).hexdigest()


def save_blocked(folder, scope_key, case_key, entry):
    """Keep semantic blockers until retry or expiry, never provider failures."""
    import excel_ai
    reason=entry.get('blocked_reason','')
    if not reusable_blocker(entry):
        return
    text=json.dumps(entry,ensure_ascii=False,sort_keys=True)
    if excel_ai.safe_text(text)!=text:return
    root=Path(folder)/'blocked';path=root/(cache_key(scope_key,case_key)+'.json')
    try:
        root.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version':VERSION,'scope':scope_key,'case':case_key,'expires':time.time()+30*86400,'entry':entry},ensure_ascii=False))
        temporary.replace(path)
    except OSError:pass


def load_blocked(folder,scope_key,case_key):
    path=Path(folder)/'blocked'/(cache_key(scope_key,case_key)+'.json')
    try:
        data=json.loads(path.read_text())
        if data.get('version')==VERSION and data.get('scope')==scope_key and data.get('case')==case_key and data.get('expires',0)>time.time() and isinstance(data.get('entry'),dict):
            return data['entry'] if reusable_blocker(data['entry']) else None
    except (OSError,ValueError,TypeError,AttributeError):pass
    return None


def reusable_blocker(entry):
    """Reject tool/transport failures on both write and legacy cache reads."""
    reason=entry.get('blocked_reason','')
    failures=('超时','调用失败','请求失败','服务异常','连接失败','额度','返回格式','适配服务异常','AI 改写','AI 返回','AI 未返回','无法解析','JSON 校验',
              '摘要大小','摘要处理失败','证据超过','传输上限','事件流超过','请求过大')
    return not entry.get('plan') and isinstance(reason,str) and bool(reason) and not any(word in reason for word in failures)


def load(folder, scope_key, case_key):
    path = Path(folder) / 'reusable' / (cache_key(scope_key, case_key) + '.json')
    try:
        data = json.loads(path.read_text())
        if data.get('version') == VERSION and data.get('scope') == scope_key and data.get('case') == case_key:
            entry=data.get('entry')
            return entry if isinstance(entry,dict) else None
    except (OSError, ValueError, AttributeError):
        pass
    return None


def save(folder, scope_key, case_key, entry):
    # Only complete candidates. Credentials are not eligible for persistent reuse.
    import excel_ai
    if not isinstance(entry.get('plan'),dict):return
    text = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    import re
    operations=entry.get('plan',{}).get('requires',[])+entry.get('plan',{}).get('steps',[])
    if any(s.get('action')=='input_local' for s in operations):
        import case_runner
        try:case_runner.validate_plan(entry['plan'])
        except (ValueError,TypeError,KeyError):return
    if not entry.get('plan') or any(s.get('action') in ('input_secret', 'workflow_case') or (s.get('action')!='input_local' and re.search(r'password|密码|密碼|账号|帐号|account|token|secret|验证码',s.get('value',''),re.I)) for s in operations) or excel_ai.safe_text(text) != text:
        return
    root = Path(folder) / 'reusable'
    path = root / (cache_key(scope_key, case_key) + '.json')
    temporary = path.with_suffix('.tmp')
    try:
        root.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({'version': VERSION, 'scope': scope_key, 'case': case_key, 'entry': entry}, ensure_ascii=False))
        temporary.replace(path)
    except OSError:
        # Cache write failures must not discard a valid generated plan.
        try:temporary.unlink(missing_ok=True)
        except OSError:pass
