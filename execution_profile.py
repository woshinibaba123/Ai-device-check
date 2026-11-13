"""Explicit app-under-test modes; installed mode never inherits source instrumentation."""
import re

MODES={'installed','package','source'}
OBSERVERS=('source_plan','route_tracking','flow_index','login_probe','http_manifest','web_manifest','reuse_test_build','pipeline_build_reused','business_source')


def normalize(config, *, runtime=False):
    cfg=dict(config)
    if not isinstance(cfg.get('login',{}),dict):raise ValueError('登录配置无效')
    cfg['login']=dict(cfg.get('login',{}))
    for field in ('source','app','bundle'):
        if not isinstance(cfg.get(field,''),str):raise ValueError('应用路径和包名必须是文本')
    mode=cfg.get('execution_mode') or ('source' if cfg.get('source','').strip() or runtime and cfg.get('business_source') else 'package' if cfg.get('app','').strip() else 'installed')
    if mode not in MODES:raise ValueError('请选择已安装应用、安装包或源码测试构建')
    cfg['execution_mode']=mode
    targets=cfg.get('targets',[])
    if not isinstance(targets,list) or any(not isinstance(t,dict) for t in targets):raise ValueError('测试设备列表无效')
    if mode=='installed':
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{1,250}',cfg.get('bundle','').strip()):raise ValueError('已安装应用模式需要填写有效包名或 Bundle ID')
        cfg.update(source='',app='')
        for field in OBSERVERS:cfg.pop(field,None)
        if cfg.get('profile') or any(t.get('profile') or t.get('ios_model') for t in cfg.get('targets',[])):
            raise ValueError('已安装应用模式请选择已有设备；新建机型模拟器中没有指定旧包')
        if config.get('execution_mode')=='installed' and cfg.get('pipeline_id'):raise ValueError('语言完整回归当前需要源码测试构建；旧包请使用普通用例回归')
    elif mode=='package':
        if not cfg.get('app','').strip():raise ValueError('安装包模式需要填写本机安装包路径')
        cfg['source']=''
        if len({t.get('platform','Android') for t in targets})>1:raise ValueError('原始安装包请按 Android 和 iOS 分开运行')
        # A request cannot attach arbitrary source probes to an original package.
        if not runtime or not cfg.get('reuse_test_build'):
            for field in OBSERVERS:cfg.pop(field,None)
    elif not cfg.get('source','').strip() and not (runtime and cfg.get('app') and cfg.get('business_source')):
        raise ValueError('源码测试构建模式需要填写 Flutter 源码目录')
    return cfg


def login_policy(login,mode):
    if not login.get('enabled'):return 'not_requested'
    proof=login.get('verification','auto')
    if proof not in ('auto','ui','observer'):raise ValueError('未知登录验证方式')
    if proof=='auto':proof='observer' if mode=='source' and login.get('flow')=='keenon_china' else 'ui'
    if proof=='observer' and mode!='source':raise ValueError('登录接口观察仅用于源码测试构建；旧包请使用页面状态验证')
    success=login.get('success',{})
    if not isinstance(success,dict) or not isinstance(success.get('value',''),str):raise ValueError('登录成功标识无效')
    if proof=='ui' and not success.get('value','').strip():raise ValueError('页面验证需要填写登录后唯一标识，不能使用登录页也存在的文字')
    if proof=='ui' and success['value'] in (login.get('account'),login.get('password')):raise ValueError('账号或密码不能作为登录成功标识')
    login['verification']=proof
    return proof


def preview(config):
    cfg=normalize(config)
    proof=login_policy(cfg.setdefault('login',{}),cfg['execution_mode'])
    source=cfg['execution_mode']=='source'
    return {'execution_mode':cfg['execution_mode'],'bundle':cfg.get('bundle',''),
            'preserves_installed_data':cfg['execution_mode']=='installed',
            'login_verification':proof,'capabilities':{
                'native_tree':'需连接设备验证','webview_dom':'需确认当前包已开放调试',
                'route_observer':'测试构建后验证' if source else '不可用',
                'network_observer':'测试构建后验证' if source else '不可用',
                'visual':'本版未新增视觉驱动'},
            'note':'页面验证只确认 UI 登录状态，不代表接口业务码或后台数据已验证。'}
