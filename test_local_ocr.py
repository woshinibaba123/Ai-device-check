import unittest,json,subprocess
from unittest.mock import patch
from vision_probe import test_image
import local_ocr
class Tests(unittest.TestCase):
 def run_rows(self,rows):
  with patch.object(local_ocr.Path,'is_file',return_value=True),patch.object(local_ocr.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(rows),'')):
   return local_ocr.locate_mac(test_image(),'C4:3C:B0:AA:F9:CF')
 def test_unique_mac(self):
  r={'text':'C4:3C:BO:AA:F9:CF','confidence':1,'x':.1,'y':.2,'width':.5,'height':.1}
  self.assertEqual(self.run_rows([r])['center'],[140,75])
  self.assertIsNone(self.run_rows([r,r]))
 def test_wrong_or_low_confidence(self):
  self.assertIsNone(self.run_rows([{'text':'C4:3C:B0:AA:F9:00','confidence':1}]))
  self.assertIsNone(self.run_rows([{'text':'C4:3C:B0:AA:F9:CF','confidence':.3}]))

class HeaderTests(unittest.TestCase):
 def test_full_title_and_device_anchors_required(self):
  from unittest.mock import patch
  rows=[{'text':'门店A','confidence':1,'y':.05},{'text':'设备','confidence':1,'y':.95},{'text':'清洁面积','confidence':1,'y':.6}]
  with patch.object(local_ocr.Path,'is_file',return_value=True),patch.object(local_ocr.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(rows),'')):
   self.assertTrue(local_ocr.verified_store_header(test_image(),'门店A'))
   self.assertFalse(local_ocr.verified_store_header(test_image(),'门店B'))
  rows.pop()
  with patch.object(local_ocr.Path,'is_file',return_value=True),patch.object(local_ocr.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(rows),'')):
   self.assertFalse(local_ocr.verified_store_header(test_image(),'门店A'))

class FooterTests(unittest.TestCase):
 def test_unique_complete_footer_required(self):
  rows=[{'text':t,'confidence':1,'x':i*.25+.02,'y':.82,'width':.1,'height':.13} for i,t in enumerate(('首页','门店','消息','我的'))]
  with patch.object(local_ocr.Path,'is_file',return_value=True),patch.object(local_ocr.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(rows),'')):
   point=local_ocr.locate_bottom_tab(test_image(),'门店')['center']
   self.assertAlmostEqual(point[0],128);self.assertAlmostEqual(point[1],288.75)
  rows.pop()
  with patch.object(local_ocr.Path,'is_file',return_value=True),patch.object(local_ocr.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(rows),'')):
   self.assertIsNone(local_ocr.locate_bottom_tab(test_image(),'门店'))
 def test_duplicate_footer_label_is_ambiguous(self):
  rows=[{'text':t,'confidence':1,'x':i*.25+.02,'y':.82,'width':.1,'height':.13} for i,t in enumerate(('首页','门店','消息','我的'))]
  rows.append(dict(rows[1]))
  with patch.object(local_ocr.Path,'is_file',return_value=True),patch.object(local_ocr.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(rows),'')):
   self.assertIsNone(local_ocr.locate_bottom_tab(test_image(),'门店'))
