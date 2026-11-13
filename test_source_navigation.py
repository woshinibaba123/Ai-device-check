import tempfile, unittest
from pathlib import Path
import source_navigation

class SourceNavigationTests(unittest.TestCase):
    def test_routes_entries_translations_and_tabs_are_discovered(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'lib').mkdir();(root/'assets/i18n').mkdir(parents=True)
            (root/'assets/i18n/en.json').write_text('{"settings":"Settings","mine":"Mine"}')
            (root/'lib/routers.dart').write_text("static const settings = '/settings'; GetPage(name: settings, page: () => const SettingsPage())")
            (root/'lib/screen.dart').write_text("Item(text: 'settings'.tr, onTap: () { Get.toNamed(Routers.settings); }); _clickMenuItem(2, 'mine'.tr)")
            plan=source_navigation.analyze(root)
            self.assertEqual(plan['routes'][0]['page'],'SettingsPage')
            self.assertEqual(plan['entries'][0]['route'],'/settings')
            self.assertEqual(plan['entry_labels'],['Settings']);self.assertEqual(plan['tab_labels'],['Mine'])
    def test_instrumentation_keeps_existing_observer_and_whitelists_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'lib').mkdir()
            (root/'lib/routers.dart').write_text("static const main = '/main';")
            target=root/'lib/main_config.dart';target.write_text('navigatorObservers: [AppRouteObserver().routeObserver],')
            source_navigation.instrument(root)
            self.assertIn('AppRouteObserver().routeObserver, DeviceCheckRouteObserver()',target.read_text())
            probe=(root/'lib/devicecheck_route_observer.dart').read_text()
            self.assertIn('allowed.contains(name)',probe);self.assertNotIn('arguments',probe)

    def test_explicit_string_routes_are_discovered(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'lib').mkdir()
            (root/'lib/routers.dart').write_text("static const String permissionManagement = '/permission/management'; GetPage(name: permissionManagement, page: () => const PermissionPage())")
            routes=source_navigation.analyze(root)['routes']
            self.assertEqual(routes,[{'name':'permissionManagement','path':'/permission/management','page':'PermissionPage'}])


class RouteReaderTests(unittest.TestCase):
    def test_android_reads_cache_when_code_cache_missing(self):
        import json
        calls=[]
        def command(args):
            calls.append(args)
            return {'ok':'/cache/' in args[-1],'output':json.dumps({'route':'/settings','run':'a','events':[]})}
        reader=source_navigation.RouteReader('Android','serial','com.example',command,'adb')
        self.assertEqual(reader.read(),'/settings')
        self.assertEqual(len(calls),2)
