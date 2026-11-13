"""Versioned, reviewable App/H5 flow recipes, separate from confirmed scripts."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def catalog():
    flows=[]
    for path in sorted((ROOT/'presets').glob('*.json')):
        document=json.loads(path.read_text())
        for flow in document['flows']:
            if not flow.get('id') or not flow.get('steps'):raise ValueError('预设流程格式无效')
            flows.append(dict(flow,module=document['module']))
    return flows
