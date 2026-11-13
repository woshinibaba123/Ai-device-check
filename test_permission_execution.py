import unittest
from unittest.mock import Mock
import ai_operator,automation
class PermissionTests(unittest.TestCase):
 def test_system_permission_bypasses_business_denylist(self):
  e=Mock();e.base='/session/test';e.call.side_effect=[{automation.ELEMENT:'permission'},None]
  node={'package':'com.android.permissioncontroller','id':'com.android.permissioncontroller:id/permission_allow_foreground_only_button','label':'允许','editable':False}
  ai_operator.execute(e,{'action':'tap','target':'n0'},{'n0':('native',node)},{})
  self.assertEqual(e.call.call_count,2)
  self.assertTrue(e.call.call_args.args[1].endswith('/permission/click'))
