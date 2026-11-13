"""Read explicit source control identities without evaluating project code."""
import json
import re
from pathlib import Path


def native_id(attributes):
    identity=attributes.get('resource-id') or attributes.get('identifier')
    if identity:return identity
    name=attributes.get('name','')
    return name if name.startswith('flutter.') else ''


def registry(project):
    path=Path(project)/'automation-identifiers.json'
    if not path.is_file() or path.stat().st_size>5_000_000:return {}
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):return {}
    result={}
    for site in data.get('sites',[]) if isinstance(data,dict) else []:
        if not isinstance(site,dict):continue
        identity=site.get('id');source=site.get('source')
        if not isinstance(identity,str) or not re.fullmatch(r'(?:flutter|h5)\.[a-z0-9_.]+',identity):continue
        if not isinstance(source,str) or '..' in Path(source).parts or Path(source).is_absolute():continue
        result.setdefault(source,[]).append(site)
    return result


def flutter_targets(source,sites,class_sources):
    targets=[]
    def add(site,prefix='',scope_required=False,seen=()):
        if len(targets)>=128:return
        identity=prefix+site['id']
        required=scope_required or bool(site.get('requiresInstanceScope'))
        if site.get('component'):
            if site.get('repeatedOrCallback') and str(site.get('widget','')).endswith(('Page','Screen')):return
            child_source=class_sources.get(site.get('widget'))
            if child_source and child_source not in seen and len(seen)<3:
                for child in sites.get(child_source,[]):add(child,identity+'/',required,seen+(child_source,))
            return
        targets.append({'by':'id','value':identity,'widget':site.get('widget'),
                        'scope_required':required})
    for site in sites.get(source,[]):add(site,seen=(source,))
    unique={t['value']:t for t in targets}
    return sorted(unique.values(),key=lambda t:(bool(t['scope_required']),0 if t['widget'] in ('TextField','TextFormField','EditableText') else 1,t['value']))
