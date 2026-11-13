"""Privacy-safe progress and bounded loop checks shared by UI runners."""
import re


def field_state(node):
    """Expose presence, never the entered value (including credentials/PII)."""
    if node.get('secure') or node.get('type') == 'password':
        return {}
    value = node.get('value')
    if value is None:
        return {}
    return {'filled': bool(str(value).strip())}


def cycle_length(history, candidate):
    """Detect a third traversal of a 2..12 action cycle, scoped to route.

    IDs, clocks and page fingerprints are deliberately excluded: map animations
    and dynamically assigned IDs must not defeat the loop bound.
    """
    def identity(s):
        return (s.get('route', ''), s.get('action'), s.get('label', ''), s.get('data_key', ''))
    steps = [s for s in history if s.get('result') == 'executed' and s.get('action') != 'assert'][-24:]
    for size in range(2, min(12, len(steps)//2)+1):
        a, b = steps[-2*size:-size], steps[-size:]
        if (list(map(identity,a)) == list(map(identity,b)) and identity(candidate) == identity(a[0])
                and any(s.get('action') in ('tap','input') for s in a)):
            return size
    return 0


def save_label(label):
    return bool(re.fullmatch(r'保存|提交|完成|保存并提交|save|submit|done|finish', str(label).strip(), re.I))


def pending_save(history, route):
    """A submit remains unresolved while still on its form; never replay it."""
    for s in reversed(history):
        if s.get('result') != 'executed':
            continue
        if s.get('route', '') != route or s.get('action') == 'back':
            return None
        if s.get('action') == 'tap' and save_label(s.get('label', '')):
            # Region save is navigation back to the parent form, not submission.
            if s.get('origin') == 'local_region_save':
                return None
            return s
    return None
