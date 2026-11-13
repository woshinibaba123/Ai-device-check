"""Private request metadata only; never request bodies, responses or error text."""
import json
import re
import threading
import time
import uuid

class Trace:
    def __init__(self, folder):
        self.path = folder / 'backend-diagnostics.jsonl'
        self.lock = threading.Lock()

    def emit(self, **fields):
        try:
            with self.lock, self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(timestamp=time.time(), **fields)) + '\n')
        except OSError:
            pass

    def call(self, method, path, callback):
        endpoint = re.sub(r'/session/[^/]+', '/session/[session]', path.split('?')[0])
        endpoint = re.sub(r'/element/[^/]+', '/element/[element]', endpoint)
        ident = uuid.uuid4().hex[:12]
        started = time.monotonic()
        done = threading.Event()
        def record(phase, **extra):
            self.emit(request=ident, method=method, endpoint=endpoint, phase=phase,
                      elapsed_ms=round((time.monotonic()-started)*1000, 1), **extra)
        def watch():
            while not done.wait(15):
                record('still_waiting')
        record('start')
        threading.Thread(target=watch, daemon=True).start()
        try:
            value = callback()
            record('complete')
            return value
        except BaseException as error:
            record('error', error_type=type(error).__name__)
            raise
        finally:
            done.set()
