"""Store one DeviceCheck CodeBuddy credential in the macOS login keychain."""
import subprocess
import sys

SERVICE = 'com.devicecheck.codebuddy'
ACCOUNT = 'codebuddy-api-key'


def _run(args, data=None):
    if sys.platform=='win32':
        import windows_credentials
        return windows_credentials.run(args,data)
    if sys.platform != 'darwin':
        raise ValueError('记住密钥需要 系统凭据存储；仍可使用本次会话密钥')
    try:
        return subprocess.run(['/usr/bin/security', *args], input=data, text=True,
                              capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('无法访问 系统凭据存储，请解锁登录钥匙串后重试') from None


def exists():
    result = _run(['find-generic-password', '-s', SERVICE, '-a', ACCOUNT])
    if result.returncode == 44:
        return False
    if result.returncode:
        raise ValueError('无法访问 系统凭据存储，请解锁后重试')
    return True


def read():
    result = _run(['find-generic-password', '-s', SERVICE, '-a', ACCOUNT, '-w'])
    if result.returncode == 44:
        return ''
    if result.returncode:
        raise ValueError('无法读取已保存密钥，请解锁 系统凭据存储后重试')
    return result.stdout.rstrip('\n')


def save(key):
    if not key or not key.isascii() or any(ord(c)<33 or ord(c)>126 for c in key):
        raise ValueError('密钥格式无效，请粘贴完整访问密钥')
    # security's interactive command accepts hex data. Keep secrets out of argv,
    # shell expansion, configuration files and logs. No broad access (-A) grant.
    encoded = key.encode('utf-8').hex()
    result = _run(['-i'], 'add-generic-password -U -s '+SERVICE+' -a '+ACCOUNT+' -X '+encoded+'\n')
    if result.returncode or read() != key:
        raise ValueError('密钥未保存成功，请确认 系统凭据存储可用')


def delete():
    result = _run(['delete-generic-password', '-s', SERVICE, '-a', ACCOUNT])
    if result.returncode not in (0, 44):
        raise ValueError('无法清除已保存密钥，请解锁 系统凭据存储后重试')
