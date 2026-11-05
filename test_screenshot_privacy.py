import io,unittest
from PIL import Image
from automation import parse_ui
from screenshot_privacy import mask
class ScreenshotPrivacyTests(unittest.TestCase):
 def png(self):
  b=io.BytesIO();Image.new('RGB',(120,240),'white').save(b,format='PNG');return b.getvalue()
 def nodes(self,s):return parse_ui('<hierarchy>'+s+'</hierarchy>')
 def test_h5_map_keeps_screenshot_and_masks_search(self):
  nodes=self.nodes('<node class="android.webkit.WebView"/><node class="android.widget.EditText" text="search" bounds="[10,10][100,30]"/>')
  result=Image.open(io.BytesIO(mask(self.png(),nodes,['previous-form-data'])))
  self.assertEqual(result.getpixel((20,20)),(40,52,72));self.assertEqual(result.getpixel((60,150)),(255,255,255))
 def test_previously_filled_h5_page_still_has_masked_evidence(self):
  nodes=self.nodes('<node class="android.webkit.WebView"/><node class="android.widget.EditText" text="synthetic-contact" bounds="[10,40][100,60]"/>')
  image=Image.open(io.BytesIO(mask(self.png(),nodes,['synthetic-contact'])))
  self.assertEqual(image.getpixel((20,50)),(40,52,72));self.assertEqual(image.getpixel((20,100)),(255,255,255))
 def test_secret_rendered_outside_input_is_masked(self):
  nodes=self.nodes('<node class="android.widget.TextView" text="synthetic-contact" bounds="[0,0][100,40]"/>')
  image=Image.open(io.BytesIO(mask(self.png(),nodes,['synthetic-contact'])))
  self.assertEqual(image.getpixel((20,20)),(40,52,72))
 def test_unknown_sensitive_position_does_not_save_raw_image(self):
  with self.assertRaises(ValueError):mask(self.png(),self.nodes('<node class="android.widget.EditText"/>'),[])
 def test_nonform_h5_is_preserved(self):
  original=self.png();self.assertEqual(mask(original,self.nodes('<node class="android.webkit.WebView"/>'),[]),original)
if __name__=='__main__':unittest.main()
