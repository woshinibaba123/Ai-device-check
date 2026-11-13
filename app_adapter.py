"""Tool-side logical identities, resolved against each fresh native observation."""
import json
import re
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'adapters'


def load(identity):
    if not identity:return None
    if not isinstance(identity,str) or not re.fullmatch(r'[a-z0-9_-]{1,64}',identity):raise ValueError('适配包名称无效')
    path=ROOT/identity/'adapter.json'
    if not path.is_file():raise ValueError('适配包不存在')
    data=json.loads(path.read_text())
    if data.get('schema_version')!=1 or data.get('id')!=identity or not isinstance(data.get('targets'),dict):raise ValueError('适配包格式无效')
    return data


def catalog():
    return [{k:d.get(k) for k in ('id','name','version','status','note')} for p in sorted(ROOT.glob('*/adapter.json')) for d in [load(p.parent.name)]]


def signature(identity):
    data=load(identity)
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest() if data else ''


def normalized(text):return re.sub(r'\s+',' ',text.strip()).casefold()


def matches(node,labels):
    values=[node.get('label',''),node.get('hint','')]
    for value in list(values):values.extend(part.strip() for part in value.split('·'))
    wanted={normalized(label) for label in labels}
    return any(normalized(value) in wanted for value in values if value)


def resolve(nodes,identity,adapter,first_match=False):
    from case_runner import CaseBlocked
    if not adapter or identity not in adapter['targets']:raise CaseBlocked('逻辑目标未配置：'+identity)
    target=adapter['targets'][identity]
    page=adapter.get('pages',{}).get(target.get('page'))
    if not page or not page.get('anchors') or not all(any(matches(n,group) for n in nodes) for group in page['anchors']):
        raise CaseBlocked('当前页面不满足逻辑目标的页面条件：'+identity)
    ids=target.get('ids',[])
    found=[n for n in nodes if n.get('id') in ids] if ids else []
    if not found:found=[n for n in nodes if matches(n,target.get('labels',[]))]
    if target.get('role')=='input':
        found=[n for n in found if n.get('editable') and n.get('secure')==target.get('secure',False)]
    elif target.get('role')=='tap':
        # Promote a label-only child only to its nearest actionable ancestor.
        promoted=[]
        for n in found:
            choices=[p for p in nodes if p.get('clickable') and (n is p or n.get('path','').startswith(p.get('path','')+'/'))]
            if choices:promoted.append(max(choices,key=lambda p:len(p.get('path',''))))
        found=promoted
    unique={n['path']:n for n in found}
    if not unique or len(unique)!=1 and not first_match:raise CaseBlocked('逻辑目标未唯一匹配：'+identity+'（'+str(len(unique))+' 个）')
    return next(iter(unique.values()))
