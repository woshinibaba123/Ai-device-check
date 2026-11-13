import subprocess
import unittest
from unittest.mock import patch
from android_visual import AndroidVisual
from test_ai_operator import Device
from vision_probe import test_image
import visual_navigation

class ADBTests(unittest.TestCase):
    def test_launcher_recovery_reopens_only_expected_app(self):
        e=Device();e.device_id='serial'
        with patch.object(AndroidVisual,'run',side_effect=['com.bbk.launcher2/.Launcher','topResumedActivity=ActivityRecord{ com.bbk.launcher2/.Launcher }','']) as run,patch.object(AndroidVisual,'foreground'):
            self.assertTrue(AndroidVisual(e).restore_from_launcher())
            self.assertEqual(run.call_args_list[-1].args[0],['shell','monkey','-p','app.test','-c','android.intent.category.LAUNCHER','1'])

    def test_other_foreground_app_is_not_replaced(self):
        e=Device();e.device_id='serial'
        with patch.object(AndroidVisual,'run',side_effect=['com.bbk.launcher2/.Launcher','topResumedActivity=ActivityRecord{ other.app/.Main }']) as run:
            self.assertFalse(AndroidVisual(e).restore_from_launcher())
            self.assertEqual(run.call_count,2)

    def test_visible_keyboard_is_hidden_locally(self):
        e=Device();e.device_id='serial'
        with patch.object(AndroidVisual,'run',side_effect=['mInputShown=true','','mInputShown=false']) as run,patch.object(AndroidVisual,'foreground'):
            self.assertTrue(AndroidVisual(e).hide_keyboard_if_visible())
            self.assertEqual(run.call_args_list[1].args[0],['shell','input','keyevent','4'])

    def test_hidden_or_unknown_keyboard_never_sends_back(self):
        e=Device();e.device_id='serial'
        for state in ('mInputShown=false','unsupported output'):
            with patch.object(AndroidVisual,'run',return_value=state) as run:
                self.assertFalse(AndroidVisual(e).hide_keyboard_if_visible())
                run.assert_called_once()

    def test_android_click_never_calls_appium(self):
        e=Device();e.device_id='test-serial'
        def run(args,**kwargs):
            self.assertEqual(args[1:3],['-s','test-serial'])
            if 'screencap' in args:out=test_image()
            elif 'dumpsys' in args:out='mCurrentFocus=Window{abc u0 app.test/.Main}'
            else:out=''
            return subprocess.CompletedProcess(args,0,out,'' if kwargs.get('text') else b'')
        with patch('cancellation.Control.run',side_effect=run), patch.object(visual_navigation.midscene_bridge,'query',return_value={'value':{'center':[300,200]},'model_calls':1}):
            result=visual_navigation.tap(e,'我的',{})
        self.assertEqual(result['center'],[300,200])
        self.assertEqual(e.calls,[])
    def test_missing_serial_fails_closed(self):
        with self.assertRaises(ValueError):AndroidVisual(Device())
    def test_wrong_foreground_fails_closed(self):
        e=Device();e.device_id='serial'
        with patch.object(AndroidVisual,'run',return_value='mCurrentFocus=Window{abc other.app/.Main}'):
            with self.assertRaises(ValueError):AndroidVisual(e).foreground()

    def test_unicode_search_restores_original_keyboard(self):
        e=Device();e.device_id='serial';e.app_package='app.test'
        commands=[]
        def run(args,binary=False):
            commands.append(args)
            if args[:4]==['shell','ime','list','-a']:return 'com.devicecheck.input/.TestIME'
            if args[:3]==['shell','settings','get']:return 'original.keyboard/.IME'
            return 'Broadcast completed: result=1'
        with patch.object(AndroidVisual,'run',side_effect=run),patch.object(AndroidVisual,'foreground'),patch('cancellation.Control.sleep'):
            AndroidVisual(e).input_search('塘人｜创意本帮菜(奥特莱斯店)')
        self.assertEqual(commands[-1],['shell','ime','set','original.keyboard/.IME'])
        self.assertTrue(any('com.devicecheck.input.TEXT' in c for c in commands))
