import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import app
from cancellation import Control, Cancelled

class CancellationTests(unittest.TestCase):
    def test_large_input_survives_delayed_child_read(self):
        payload='x'*1_000_000
        result=Control().run([sys.executable,'-c','import sys,time;time.sleep(.5);print(len(sys.stdin.read()))'],input=payload,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.stdout.strip(),str(len(payload)))

    def test_stdout_is_observed_before_process_finishes(self):
        observations=[];start=time.monotonic()
        result=Control().run([sys.executable,'-u','-c','import time;print("first",flush=True);time.sleep(.4);print("last",flush=True)'],capture_output=True,text=True,
                             on_stdout=lambda text:observations.append((time.monotonic()-start,text)))
        self.assertEqual(result.stdout,'first\nlast\n')
        self.assertEqual(observations[0][1],'first\n')
        self.assertLess(observations[0][0],.35)
        self.assertEqual(observations[-1][1],result.stdout)
    def test_child_process_is_interrupted(self):
        stop = threading.Event()
        timer = threading.Timer(.2, stop.set); timer.start()
        start = time.monotonic()
        with self.assertRaises(Cancelled):
            Control(stop.is_set).run([sys.executable, '-c', 'import time;time.sleep(60)'], capture_output=True, text=True)
        self.assertLess(time.monotonic()-start, 3)

    def test_wait_interrupts(self):
        stop = threading.Event()
        threading.Timer(.1, stop.set).start()
        start = time.monotonic()
        with self.assertRaises(Cancelled): Control(stop.is_set).sleep(30)
        self.assertLess(time.monotonic()-start, 1)

    def test_pending_session_cleans_up_once(self):
        stop = threading.Event(); release = threading.Event(); cleaned = threading.Event(); values=[]
        def remote():
            release.wait(3)
            return {'sessionId':'late'}
        def cleanup(value): values.append(value); cleaned.set()
        threading.Timer(.1, stop.set).start()
        with self.assertRaises(Cancelled): Control(stop.is_set).call(remote, cleanup)
        release.set()
        self.assertTrue(cleaned.wait(2))
        self.assertEqual(values,[{'sessionId':'late'}])

    def test_stop_before_job_prevents_session(self):
        job={'status':'running','stop_requested':True,'logs':[],'screenshots':[]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'ROOT',Path(tmp)), patch.dict(app.JOBS,{'cancel-test':job}), patch.object(app,'request') as request:
            app.run_job('cancel-test',{'platform':'Android','device':'mock','bundle':'test'})
            request.assert_not_called()
            self.assertEqual(job['status'],'stopped')
            self.assertTrue((Path(tmp)/'reports/cancel-test/report.json').exists())

    def test_stop_during_emulator_boot_never_creates_session(self):
        import subprocess
        job={'status':'running','logs':[],'screenshots':[]}
        process=unittest.mock.Mock()
        def command(args):
            if args[-1]=='-list-avds': return {'ok':True,'output':'test-avd'}
            job['stop_requested']=True
            return {'ok':True,'output':'List of devices attached\n'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app,'ROOT',Path(tmp)), patch.dict(app.JOBS,{'boot-stop':job}), patch.object(app,'command',side_effect=command), patch.object(app.subprocess,'Popen',return_value=process), patch.object(app,'request') as request:
            app.run_job('boot-stop',{'platform':'Android','device':'avd:test-avd','bundle':'test'})
            request.assert_not_called()
            process.terminate.assert_called_once()
            self.assertEqual(job['status'],'stopped')
