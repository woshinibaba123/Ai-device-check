"""Build-only instrumentation; reads a credential-free success event in the app sandbox."""
import json
import re
import uuid
from pathlib import Path

REPOSITORY=Path('lib/http/repository/login_repository.dart')

def validate(project):
    file=project/REPOSITORY
    if not file.is_file():raise ValueError('内置接口登录验证需要该 App 的 Flutter 源码，未找到 login_repository.dart。安装包模式请使用自定义页面标识验证。')
    text=file.read_text()
    section=text.split('  /// 医疗账号登录后校验',1)[0]
    if section.count('success?.call(ResultBean.event(true));')!=2:
        raise ValueError('登录源码结构已变化，无法安全添加接口结果验证，请更新适配。')

def instrument(project):
    validate(project)
    name='devicecheck-login-'+uuid.uuid4().hex+'.json'
    file=project/REPOSITORY;text=file.read_text()
    head,tail=text.split('  /// 医疗账号登录后校验',1)
    event="try { File('${Directory.systemTemp.path}/"+name+"').writeAsStringSync('{\"success\":true}'); } catch (_) {}\n"
    head=head.replace('success?.call(ResultBean.event(true));',event+'      success?.call(ResultBean.event(true));')
    # Preserve business results while recording only numeric failure codes.
    # No request parameters, response bodies, tokens or error messages are saved.
    if 'class LoginRepository extends BaseRepository {' in head:
        helper = """
  ResultBean _deviceCheckFailure(int code) {
    try { File('${Directory.systemTemp.path}/NAME').writeAsStringSync(jsonEncode({'success': false, 'code': code})); } catch (_) {}
    return ResultBean.newBean(false, code);
  }
""".replace('NAME', name)
        head = re.sub(r'ResultBean\.newBean\(false,\s*(code|-1)\)', r'_deviceCheckFailure(\1)', head)
        head = head.replace('class LoginRepository extends BaseRepository {', 'class LoginRepository extends BaseRepository {' + helper, 1)
    file.write_text("import 'dart:io';\n"+head+'  /// 医疗账号登录后校验'+tail)
    return name

class Probe:
    def __init__(self, platform, device, bundle, name, command, adb=None):
        if not re.fullmatch(r'devicecheck-login-[a-f0-9]{32}\.json',name):raise ValueError('无效登录验证文件')
        if not bundle or not re.fullmatch(r'[\w.\-]+',bundle):raise ValueError('未能确定 App 包名，不能读取接口验证结果')
        self.platform=platform;self.device=device;self.bundle=bundle;self.name=name;self.command=command;self.adb=adb
    def ios_file(self):
        r=self.command(['xcrun','simctl','get_app_container',self.device,self.bundle,'data'])
        if not r['ok']:raise RuntimeError('无法访问 iOS 模拟器 App 数据目录')
        return Path(r['output'])/'tmp'/self.name
    def reset(self):
        if self.platform=='Android':
            # Dart 的 Directory.systemTemp 在 Android 上指向 code_cache，而非 cache。
            base='/data/user/0/'+self.bundle
            r=self.command([self.adb,'-s',self.device,'shell','run-as',self.bundle,'rm','-f',base+'/code_cache/'+self.name,base+'/cache/'+self.name])
            if not r['ok']:raise RuntimeError('无法访问 App 测试目录，请使用源码构建的 debug 包')
        else:self.ios_file().unlink(missing_ok=True)
    def read(self):
        if self.platform=='Android':
            # adb 会把参数拼给设备 shell 解析，这里用绝对路径逐个尝试，避免引号/glob 问题。
            base='/data/user/0/'+self.bundle
            text=''
            for path in (base+'/code_cache/'+self.name,base+'/cache/'+self.name):
                r=self.command([self.adb,'-s',self.device,'shell','run-as',self.bundle,'cat',path])
                if r['ok'] and r['output'].strip():text=r['output'];break
        else:
            file=self.ios_file();text=file.read_text() if file.is_file() else ''
        try: result=json.loads(text)
        except (ValueError,TypeError):return False
        if not isinstance(result,dict):return False
        if result.get('success') is False and isinstance(result.get('code'),int):
            from automation import LoginBlocked
            raise LoginBlocked('登录接口明确返回失败，错误码：'+str(result['code'])+'；未继续探索。')
        return result.get('success') is True
