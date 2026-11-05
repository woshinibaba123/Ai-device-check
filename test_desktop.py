import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import host_runtime,desktop_main,windows_credentials,runtime_health


class DesktopPathsTests(unittest.TestCase):
    def test_windows_sdk_and_binary_names_without_mac_paths(self):
        with patch.object(host_runtime.sys,'platform','win32'),patch.dict(os.environ,{'LOCALAPPDATA':'C:/Users/Test/AppData/Local'},clear=True):
            self.assertEqual(str(host_runtime.sdk_root()),'C:/Users/Test/AppData/Local/Android/Sdk')
            self.assertEqual(host_runtime.executable('adb'),'adb.exe')
            self.assertEqual(host_runtime.batch_name('avdmanager'),'avdmanager.bat')

    def test_desktop_assets_go_into_data_directory_not_bundle(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'DEVICECHECK_DATA_DIR':tmp}),patch.object(host_runtime,'setup_environment'):
            root=desktop_main.prepare()
            self.assertTrue((root/'index.html').is_file())
            self.assertTrue((root/'catalog.json').is_file())
            self.assertFalse((root/'reports').exists())
            self.assertFalse((root/'.appium').exists())

    def test_source_copy_on_windows_does_not_use_mac_cp(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(host_runtime.sys,'platform','win32'):
            source=Path(tmp)/'source';source.mkdir();(source/'pubspec.yaml').write_text('name: app')
            (source/'build').mkdir();(source/'build/old').write_text('cache')
            run=Mock();target=Path(tmp)/'copy'
            host_runtime.copy_source(source,target,run)
            self.assertTrue((target/'pubspec.yaml').exists());self.assertFalse((target/'build').exists());run.assert_not_called()

    def test_windows_process_cleanup_uses_tree(self):
        process=Mock();process.pid=123;process.poll.return_value=None
        with patch.object(host_runtime.sys,'platform','win32'),patch.object(host_runtime.subprocess,'run') as run:
            host_runtime.stop_process(process,True)
            self.assertEqual(run.call_args.args[0],['taskkill','/PID','123','/T','/F'])


class WindowsCredentialAdapterTests(unittest.TestCase):
    def test_unicode_secret_is_passed_directly_to_store_not_process(self):
        secret='密码\n$()';encoded=secret.encode().hex()
        with patch.object(windows_credentials,'write') as write:
            result=windows_credentials.run(['-i'],'add-generic-password -U -s com.devicecheck -a account -X '+encoded+'\n')
            self.assertEqual(result.returncode,0);write.assert_called_once_with('com.devicecheck/account','account',secret)

    def test_missing_entry_matches_existing_store_contract(self):
        with patch.object(windows_credentials,'read',return_value=None):
            self.assertEqual(windows_credentials.run(['find-generic-password','-s','service','-a','account','-w']).returncode,44)


class DesktopServiceOwnershipTests(unittest.TestCase):
    def test_busy_port_is_not_stopped_or_adopted(self):
        with patch.object(runtime_health,'_owned_desktop',None),patch('socket.socket') as socket,patch.object(runtime_health.subprocess,'Popen') as popen:
            socket.return_value.__enter__.return_value.connect_ex.return_value=0
            with self.assertRaisesRegex(RuntimeError,'其他进程'):runtime_health.desktop_restart('/mock/root',lambda _:None)
            popen.assert_not_called()
