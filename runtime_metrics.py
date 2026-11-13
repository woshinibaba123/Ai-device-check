"""Per-run timing context shared by every execution channel."""
from contextvars import ContextVar
import functools

recorder = ContextVar('devicecheck_recorder', default=None)


def timed(operation):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            current = recorder.get()
            if current is None:
                return fn(*args, **kwargs)
            return current.call(operation, lambda: fn(*args, **kwargs))
        return wrapped
    return decorate
