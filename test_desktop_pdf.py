import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

class PortablePDFTests(unittest.TestCase):
    def test_report_exports_without_macos_font(self):
        import pdf_report
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'report.pdf'
            with patch.object(Path,'is_file',return_value=False):
                pdf_report.build({'id':'desktop-test','status':'passed','label':'中文机型','logs':['中文步骤执行完成'],'screenshots':[]},root,out)
            self.assertTrue(out.read_bytes().startswith(b'%PDF'))
            self.assertGreater(out.stat().st_size,1000)
