import base64
import json
import subprocess
import unittest
from unittest.mock import patch
import cancellation
import codebuddy_bridge as bridge
from vision_probe import test_image

class VisionInputTests(unittest.TestCase):
    def test_image_is_transported_without_changing_text_prompt(self):
        response = subprocess.CompletedProcess([], 0, json.dumps({'type':'result','result':'{"x":300,"y":200}'})+'\n', '')
        image = test_image()
        with patch.object(bridge, '_KEY', 'unit-test-secret'), patch.object(bridge, 'executable', return_value='/mock/cli'), patch.object(cancellation.Control, 'run', return_value=response) as run:
            bridge.ask('locate', images=[image], model='hy4std')
        args, kwargs = run.call_args
        self.assertIn('--input-format', args[0])
        payload = json.loads(kwargs['input'])
        self.assertEqual(payload['message']['content'][0]['text'], 'locate')
        self.assertEqual(base64.b64decode(payload['message']['content'][1]['source']['data']), image)
        self.assertNotIn('unit-test-secret', kwargs['input'])

    def test_invalid_image_does_not_launch_cli(self):
        with patch.object(bridge, 'executable', return_value='/mock/cli'), patch.object(cancellation.Control, 'run') as run:
            with self.assertRaises(ValueError): bridge.ask('locate', images=[b'not an image'])
        run.assert_not_called()
