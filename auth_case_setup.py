"""Prepare isolated Android source-test login boundaries without exporting credentials."""
import time
import automation,login_flow


def install(explorer,login_cfg,reset_test_app,log,sleep,language=None):
    dirty={'value':True}
    explorer.test_credentials={k:login_cfg.get(k,'') for k in ('account','password')}
    def prepare(state):
        explorer.auth_case_active=state!='home'
        if state=='home':
            if dirty['value']:
                result=explorer.login(login_cfg)
                explorer.login_result=result
                if result.get('status')!='confirmed':raise automation.LoginBlocked('登录后用例需要已配置的有效测试账号密码')
                login_flow.wait_post_login(explorer,sleep)
                login_flow.dismiss_onboarding(explorer)
                if language:explorer.switch_language(language)
                dirty['value']=False
            return
        reset_test_app();dirty['value']=True
        log('准备独立登录测试起点：'+state+'；重置当前源码测试副本的本地数据，不提交业务数据')
        if state=='login':
            login_flow.prepare(explorer)
            # Switch to password login after entering an account only when the case requests it.
            return
        reader=getattr(explorer,'route_reader',None)
        if not reader:raise automation.LoginBlocked('登录配置测试需要源码路由观察器')
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if explorer.stopped():raise automation.LoginBlocked('用户停止')
            if reader.read()=='/loginConfig':return
            nodes=automation.parse_ui(explorer.source())
            agree=login_flow.matching(nodes,login_flow.AGREE)
            if len(agree)==1:explorer.tap(agree[0])
            sleep(.5)
        raise automation.LoginBlocked('未到达独立登录前配置页，未执行当前用例')
    explorer.prepare_test_case=prepare
