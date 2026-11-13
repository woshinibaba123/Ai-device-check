import unittest
from unittest.mock import Mock,patch
import app

class TimeoutDiagnosticTests(unittest.TestCase):
    def test_timeout_identifies_endpoint_without_payload_or_session(self):
        opener=Mock();opener.open.side_effect=TimeoutError('timed out')
        with patch.object(app.urllib.request,'build_opener',return_value=opener):
            with self.assertRaisesRegex(RuntimeError,r'POST /session/\[session\]/element/\[element\]/click') as result:
                app.raw_request('POST','/session/private-session/element/private-element/click',{'password':'secret'})
        self.assertNotIn('secret',str(result.exception));self.assertNotIn('private-',str(result.exception))
        opener.open.assert_called_once()
