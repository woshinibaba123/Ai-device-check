import host_runtime
"""Cooperative job cancellation for waits, child processes and HTTP calls."""
import os
import signal
import subprocess
import threading
import time

class Cancelled(Exception):
    pass

class Control:
    def __init__(self, stopped=lambda: False):
        self.stopped = stopped

    def check(self):
        if self.stopped():
            raise Cancelled('用户已停止本批次。')

    def sleep(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check()
            time.sleep(min(.1, max(0, deadline-time.monotonic())))
        self.check()

    def run(self, args, timeout=25, **kwargs):
        self.check()
        input_text = kwargs.pop('input', None)
        capture = kwargs.pop('capture_output', False)
        if capture:
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if input_text is not None:
            kwargs['stdin'] = subprocess.PIPE
        process = subprocess.Popen(args, start_new_session=True, **kwargs)
        deadline = time.monotonic() + timeout
        first = True
        try:
            while True:
                self.check()
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(args, timeout)
                try:
                    out, err = process.communicate(input=input_text if first else None, timeout=.1)
                    self.check()
                    return subprocess.CompletedProcess(args, process.returncode, out, err)
                except subprocess.TimeoutExpired:
                    first = False
        finally:
            if process.poll() is None:
                host_runtime.stop_process(process)
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    host_runtime.stop_process(process,force=True)
                    process.wait(timeout=2)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None: pipe.close()

    def call(self, fn, late_result=None):
        self.check()
        done = threading.Event()
        result = []
        abandoned = threading.Event()
        cleanup_lock = threading.Lock()
        cleaned = [False]
        def cleanup():
            with cleanup_lock:
                if cleaned[0] or not result or not result[0][0]: return
                cleaned[0] = True
            if late_result: late_result(result[0][1])
        def worker():
            try: result.append((True, fn()))
            except Exception as exc: result.append((False, exc))
            finally: done.set()
            if abandoned.is_set(): cleanup()
        threading.Thread(target=worker, daemon=True).start()
        try:
            while not done.wait(.1): self.check()
            self.check()
        except Cancelled:
            abandoned.set()
            if done.is_set():
                threading.Thread(target=cleanup, daemon=True).start()
            raise
        ok, value = result[0]
        if not ok: raise value
        return value
