"""Recover only non-secret setup fields from an existing local run configuration."""
import json
from pathlib import Path


def read(root):
    path = Path(root) / '.runtime/overnight-20261104/pilot-config.json'
    try:
        config = json.loads(path.read_text())
        execution = config.get('execution', {})
        if not isinstance(execution, dict):
            return {}
    except (OSError, ValueError, AttributeError):
        return {}
    result = {}
    for key in ('source', 'h5_source', 'app'):
        value = execution.get(key, '')
        if isinstance(value, str) and value and Path(value).exists():
            result[key] = value
    for key in ('entrypoint', 'bundle'):
        value = execution.get(key)
        if isinstance(value, str) and len(value) <= 1024:
            result[key] = value
    login = execution.get('login', {})
    if isinstance(login, dict):
        result['login'] = {key: login[key] for key in ('account', 'flow') if isinstance(login.get(key), str)}
        result['login']['enabled'] = login.get('enabled') is True
    return result
