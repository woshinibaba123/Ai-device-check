"""ADB transport independent of Appium/UiAutomator2 for visual recovery."""
import io
import os
from pathlib import Path
import re
import shutil
from PIL import Image
import cancellation

class AndroidVisual:
    def __init__(self, explorer):
        self.explorer=explorer
        self.control=cancellation.Control(explorer.stopped)
        self.serial=getattr(explorer,'device_id','')
        if not self.serial:raise ValueError('视觉恢复缺少目标设备序列号')
        sdk=Path(os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or Path.home()/'Library/Android/sdk')
        self.adb=shutil.which('adb') or str(sdk/'platform-tools/adb')
    def run(self,args,binary=False):
        tick=getattr(self.explorer,'progress_tick',None)
        if callable(tick):tick()
        try:
            result=self.control.run([self.adb,'-s',self.serial,*args],capture_output=True,text=not binary,timeout=12)
        except (OSError,TimeoutError,__import__('subprocess').TimeoutExpired):
            raise ValueError('ADB 视觉操作失败或超时，未重复执行') from None
        if result.returncode:raise ValueError('ADB 视觉操作失败，未重复执行')
        if callable(tick):tick()
        return result.stdout
    @__import__('runtime_metrics').timed('visual_foreground')
    def foreground(self):
        expected=getattr(self.explorer,'app_package','')
        if not expected:raise ValueError('无法确认被测 App 身份')
        text=self.run(['shell','dumpsys','window','windows'])
        lines=[s for s in text.splitlines() if 'mCurrentFocus=' in s]
        if not lines:
            text=self.run(['shell','dumpsys','activity','activities'])
            lines=[s for s in text.splitlines() if 'topResumedActivity=' in s or 'mResumedActivity:' in s]
        if not any(re.search(r'(?<![\w.])'+re.escape(expected)+r'/',s) for s in lines):
            raise ValueError('ADB 未确认前台为被测 App，未点击')
    @__import__('runtime_metrics').timed('visual_capture')
    def screenshot(self):
        data=self.run(['exec-out','screencap','-p'],binary=True)
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except Exception:raise ValueError('ADB 截图无效') from None
        monitor=getattr(self.explorer,'diagnostics_monitor',None)
        if monitor:
            try:monitor.observe_frame(data)
            except Exception:self.explorer.log('白屏采样记录失败，保留当前截图和操作结果。')
        return data

    def restore_from_launcher(self):
        """Recover only the OS launcher; never steal focus from another app."""
        expected=getattr(self.explorer,'app_package','')
        if not expected:return False
        resolved=self.run(['shell','cmd','package','resolve-activity','--brief','-a','android.intent.action.MAIN','-c','android.intent.category.HOME'])
        homes=[line.strip().split('/')[0] for line in resolved.splitlines() if '/' in line and ' ' not in line.strip()]
        activities=self.run(['shell','dumpsys','activity','activities'])
        resumed=[line for line in activities.splitlines() if 'ResumedActivity' in line or 'topResumedActivity=' in line]
        if not homes or not any(re.search(r'(?<![\w.])'+re.escape(home)+r'/',line) for home in homes for line in resumed):return False
        self.run(['shell','monkey','-p',expected,'-c','android.intent.category.LAUNCHER','1'])
        self.foreground()
        self.explorer.log('检测到退回系统桌面，已重新打开被测 App；重新观察当前页面，不重放业务操作。')
        return True
    @__import__('runtime_metrics').timed('visual_tap')
    def tap(self,x,y):
        monitor=getattr(self.explorer,'diagnostics_monitor',None)
        if monitor:monitor.before('POST','/visual/actions',{})
        self.explorer.log('视觉点击坐标：(%d,%d)'%(x,y))
        self.run(['shell','input','tap',str(x),str(y)])
        if monitor and monitor.enabled():
            self.control.sleep(.15)
            try:self.explorer._last_action_frame=(self.screenshot(),__import__('time').monotonic())
            except (OSError,ValueError):self.explorer.log('跳转早期截图失败，后续观察继续。')
    def scroll(self,width,height):
        self.run(['shell','input','swipe',str(width//2),str(int(height*.75)),str(width//2),str(int(height*.3)),'600'])

    @__import__('runtime_metrics').timed('keyboard_check')
    def hide_keyboard_if_visible(self):
        """Use IME state, never guess from the screenshot or send BACK blindly."""
        state=self.run(['shell','dumpsys','input_method'])
        if not re.search(r'\b(?:mInputShown|mIsInputViewShown|isInputViewShown)=true\b',state):return False
        self.foreground()
        self.run(['shell','input','keyevent','4'])
        after=self.run(['shell','dumpsys','input_method'])
        hidden=bool(re.search(r'\b(?:mInputShown|mIsInputViewShown|isInputViewShown)=false\b',after)) and not re.search(r'\b(?:mInputShown|mIsInputViewShown|isInputViewShown)=true\b',after)
        self.explorer.log('本地键盘处理：已确认键盘显示，收起结果=%s；后续重新截图。'%hidden)
        return hidden

    def input_search(self,text):
        """Unicode input through the explicit test IME; restore user's keyboard."""
        import base64
        ime='com.devicecheck.input/.TestIME'
        installed=self.run(['shell','ime','list','-a','-s'])
        if ime not in installed:
            apk=Path(__file__).resolve().parent/'.runtime/devicecheck-input/input.apk'
            if not apk.is_file():raise ValueError('缺少中文测试输入法，请运行 python3 android-input/build.py')
            self.run(['install','-r',str(apk)])
        previous=self.run(['shell','settings','get','secure','default_input_method']).strip()
        if not previous or previous=='null':raise ValueError('无法读取原输入法，未修改输入法')
        try:
            self.run(['shell','ime','enable',ime])
            self.run(['shell','ime','set',ime])
            self.control.sleep(.5)
            self.foreground()
            # Clear only the already focused, visually located store search field.
            self.run(['shell','am','broadcast','-p','com.devicecheck.input','-a','com.devicecheck.input.CLEAR'])
            payload=base64.b64encode(text.encode('utf-8')).decode('ascii')
            output=self.run(['shell','am','broadcast','-p','com.devicecheck.input','-a','com.devicecheck.input.TEXT','--es','msg',payload])
            if 'result=1' not in output:raise ValueError('测试输入法未确认输入成功，未继续选择门店')
        finally:
            # Cleanup must run even when the job was cancelled.
            saved_control=self.control
            self.control=cancellation.Control()
            try:self.run(['shell','ime','set',previous])
            finally:self.control=saved_control
