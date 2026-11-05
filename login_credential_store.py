"""Account-scoped test credentials kept in the macOS login keychain."""
import hashlib
import json
import credential_store

SERVICE='com.devicecheck.test-login'


def identity(account):
    if not isinstance(account,str) or not account.strip() or len(account)>1024:
        raise ValueError('请填写测试账号')
    return account.strip(),hashlib.sha256(account.strip().encode()).hexdigest()


def read(account):
    account,key=identity(account)
    result=credential_store._run(['find-generic-password','-s',SERVICE,'-a',key,'-w'])
    if result.returncode==44:return ''
    if result.returncode:raise ValueError('无法读取测试密码，请解锁 系统凭据存储后重试')
    try:payload=json.loads(result.stdout)
    except (ValueError,TypeError):raise ValueError('已保存的登录信息无效，请重新保存') from None
    if not isinstance(payload,dict) or payload.get('account')!=account or not isinstance(payload.get('password'),str):
        raise ValueError('已保存的登录信息与当前账号不匹配，请重新保存')
    return payload['password']


def saved(account):
    _,key=identity(account)
    result=credential_store._run(['find-generic-password','-s',SERVICE,'-a',key])
    if result.returncode==44:return False
    if result.returncode:raise ValueError('无法访问测试密码，请解锁 系统凭据存储后重试')
    return True


def save(account,password):
    account,key=identity(account)
    if not isinstance(password,str) or not 1<=len(password)<=1024:raise ValueError('请填写有效测试密码')
    encoded=json.dumps({'account':account,'password':password},ensure_ascii=False).encode().hex()
    result=credential_store._run(['-i'],'add-generic-password -U -s '+SERVICE+' -a '+key+' -X '+encoded+'\n')
    if result.returncode or read(account)!=password:raise ValueError('账号密码未保存成功，请检查 系统凭据存储')


def delete(account):
    _,key=identity(account)
    result=credential_store._run(['delete-generic-password','-s',SERVICE,'-a',key])
    if result.returncode not in (0,44):raise ValueError('无法清除测试密码，请解锁 系统凭据存储后重试')


def resolve(login):
    if login.get('enabled') and login.get('use_saved_password') and not login.get('password'):
        password=read(login.get('account',''))
        if not password:raise ValueError('当前账号尚未保存密码，请输入密码后保存')
        login['password']=password
    login.pop('use_saved_password',None)
    return login
