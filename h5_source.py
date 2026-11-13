import json
"""Bounded, read-only H5 page excerpts for AI planning."""
import os
import re
import posixpath
import stable_identifiers
from pathlib import Path

SKIP={'node_modules','dist','build','coverage','vendor','public','.git','.next','.nuxt'}
EXT={'.vue','.tsx','.jsx','.html','.ts','.js'}


def binding_evidence(text):
    """Literal DOM and request evidence; never infer runtime uniqueness or success codes."""
    controls=[]
    for match in re.finditer(r'<(input|textarea|button|article|form|div|span|li|ul|ol)\b([^>]*)>',text):
        tag,attrs=match.groups()
        cls=re.search(r'(?<![:\w-])class=[\'"]([\w -]+)[\'"]',attrs)
        if cls and re.search(r'input|textarea|button|article|form|card|empty|store-name|address|meta',tag+' '+cls[1]):
            classes=cls[1].split()
            if not classes:continue
            selector=tag+'.'+'.'.join(classes)
        elif not cls and tag in ('input','textarea'):
            kind=re.search(r'(?<![:\w-])type=[\'\"]([\w-]+)[\'\"]',attrs)
            selector=tag+('[type="'+kind[1]+'"]' if kind else '')
        elif not cls and (tag=='li' and 'v-for' in attrs or tag=='button' and '@click' in attrs):
            before=text[:match.start()]
            parents=list(re.finditer(r'<(ul|ol)\b[^>]*\bclass=[\'"]([\w -]+)[\'"][^>]*>',before))
            parent=parents[-1] if parents else None
            if parent and before.rfind('</'+parent[1]+'>')<parent.start():selector=parent[1]+'.'+'.'.join(parent[2].split())+' '+tag
            else:continue
        else:continue
        row={'selector':selector,'requires_runtime_unique_match':True}
        model=re.search(r'v-model(?:\.\w+)*=[\'"]([^\'"]+)',attrs)
        if model:row['model']=model[1]
        events=re.findall(r'@(\w+)(?:\.\w+)*=[\'"]([^\'"]+)',attrs)
        if events:row['events']=dict(events)
        if 'v-for' in attrs or tag=='article':row['scope_required']=True
        controls.append(row)
    requests=[]
    for match in re.finditer(r'\brequest\(\{([\s\S]{0,1200}?)\}\)',text):
        body=match[1]
        path=re.search(r'\burl:\s*[\'"]([^\'"]+)',body)
        method=re.search(r'\bmethod:\s*[\'"]([^\'"]+)',body)
        if path and method:requests.append({'method':method[1].upper(),'path':path[1]})
    fields=sorted(set(re.findall(r'\b(?:item|row|form)\.([A-Za-z_]\w*)',text)))[:35]
    return {'dom_controls':controls[:12],'requests':requests[:8],'data_fields':fields}


def source_index(directory):
    if not isinstance(directory,str) or not directory.strip():raise ValueError('请填写 H5 项目本地目录')
    if directory.startswith(('http://','https://','git@')):raise ValueError('H5 源码请填写下载到本机的项目目录，不是网页或 Git 地址')
    root=Path(directory).expanduser().resolve()
    if not root.is_dir():raise ValueError('H5 源码目录不存在，请填写本机文件夹路径')
    if not any((root/name).is_file() for name in ('package.json','index.html')):
        raise ValueError('请选择包含 package.json 或 index.html 的 H5 项目根目录')
    documents=[];seen=0;size=0;identifiers=stable_identifiers.registry(root)
    for folder,dirs,files in os.walk(root):
        dirs[:]=sorted(d for d in dirs if d not in SKIP and not d.startswith('.') and not Path(folder,d).is_symlink())
        for name in sorted(files):
            seen+=1
            if seen>5000:break
            path=Path(folder,name)
            if path.is_symlink() or path.suffix not in EXT or name.endswith(('.min.js','.d.ts')) or path.stat().st_size>150000:continue
            if re.search(r'(^|[._-])(config|secret|credential|token|lock|test|spec)([._-]|$)',name,re.I):continue
            text=path.read_text(errors='replace');size+=len(text)
            if size>8_000_000:break
            # Omit credential-looking assignments even inside page files.
            text=re.sub(r'(?im)^.*(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=].*$', '[credential assignment omitted]',text)
            relevant=[(n,line) for n,line in enumerate(text.splitlines(),1) if re.search(r'data-testid|data-test-key|@click|v-model|route|path|title|label|placeholder|input|form|button|submit|axios|fetch|router|\b(?:url|method|code|baseURL)\s*:|export\s+function|\.(?:post|get|put)\(|[\u4e00-\u9fff]',line,re.I)]
            if relevant:documents.append({'file':str(path.relative_to(root)),'text':text,'lines':relevant,'automation_targets':identifiers.get(str(path.relative_to(root)),[])})
        if seen>5000 or size>8_000_000:break
    if not documents:raise ValueError('H5 项目中未找到可分析的页面或路由代码')
    return {'project':str(root),'documents':documents}


def summary(directory,outline,*,index=None,max_chars=30000):
    if index is None:index=source_index(directory)
    elif index['project']!=str(Path(directory).expanduser().resolve()):
        raise ValueError('H5 索引与源码目录不一致')
    terms=set(re.findall(r'[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}',outline))
    for word in list(terms):
        if re.search(r'[\u4e00-\u9fff]',word):terms.update(word[i:i+2] for i in range(len(word)-1))
    terms=sorted(terms,key=lambda term:(-len(term),term))[:80]
    # Translation namespaces connect Chinese requirement text to pages whose
    # templates contain only i18n keys. Generic words must not outrank that link.
    module_strength={}
    for document in index['documents']:
        module=re.search(r'/(?:lang|locales|i18n)/([^/]+)/',document['file'])
        matches=[len(term) for term in terms if len(term)>=4 and re.search(r'[\u4e00-\u9fff]',term) and term in document['text']]
        if module:matches.extend(len(value) for value in re.findall(r'''['"]([\u4e00-\u9fff]{4,40})['"]''',document['text']) if value in outline)
        if module and matches:module_strength[module[1].lower()]=max(matches)
    strongest=max(module_strength.values(),default=0)
    modules={name for name,strength in module_strength.items() if strength==strongest}
    candidates=[]
    for document in index['documents']:
        text=document['text'];rel=document['file']
        score=sum(min(text.count(term),5) for term in terms)+sum(4 for term in terms if term.lower() in rel.lower())
        if any(module in rel.lower() for module in modules):score+=180 if rel.endswith('.vue') else 100
        relevant=sorted(document['lines'],key=lambda item:-sum(term in item[1] for term in terms))
        chosen=sorted(relevant[:20])
        excerpt='\n'.join(str(n)+': '+line[:280] for n,line in chosen)[:1600]
        if excerpt:
            row={'file':rel,'excerpt':excerpt}
            evidence=binding_evidence(text)
            row.update({k:v for k,v in evidence.items() if v})
            if re.search(r'/(?:lang|locales|i18n)/',rel):
                labels={}
                for key,value in re.findall(r'''\b(\w+):\s*['"]([^'"\n]{1,250})['"]''',text):
                    labels.setdefault(key,value)
                    if len(labels)>=35:break
                if labels:row['translation_labels']=labels;row['excerpt']=row['excerpt'][:300]
            if row.get('dom_controls') or row.get('requests'):row['excerpt']=row['excerpt'][:1000]
            targets=sorted(document.get('automation_targets',[]),key=lambda s: -sum(term.lower() in (s.get('id','')+' '+str(s.get('model',''))).lower() for term in terms))[:3]
            if targets:row['automation_targets']=[{'by':'css','value':t['selector'],'input_selector':t.get('inputSelector'),'scope_required':t.get('requiresInstanceScope',False),'repeat_keys':t.get('repeatKeys',[])} for t in targets]
            candidates.append((score,row))
    candidates.sort(key=lambda row:(-row[0],row[1]['file']))
    by_file={d['file']:d for d in index['documents']};excerpts={d['file']:d for _,d in candidates}
    selected=[row[1] for row in candidates[:12]];bundles=[]
    def dependencies(row,depth=0,visited=None):
        visited=set() if visited is None else visited
        if row['file'] in visited or depth>2:return []
        visited.add(row['file'])
        document=by_file[row['file']]
        linked=[]
        for link in re.findall(r"from\s*['\"]([^'\"]+)['\"]",document['text']):
            target='src/'+link[2:] if link.startswith('@/') else posixpath.normpath(posixpath.join(posixpath.dirname(row['file']),link)) if link.startswith('.') else ''
            if not target:continue
            found=next((name for name in (target,target+'.js',target+'.ts',target+'.vue',target+'/index.js',target+'/index.vue') if name in excerpts),None)
            if found and found!=row['file'] and found not in {d['file'] for d in linked}:
                child=excerpts[found]
                if found.endswith(('/index.js','/index.ts')):
                    linked.extend(dependencies(child,depth+1,visited))
                linked.append(child)
        linked.sort(key=lambda d:(not bool(d.get('requests')),not d['file'].endswith('/index.vue'),not d['file'].endswith('.vue'),not bool(d.get('dom_controls')),d['file']))
        return linked
    for row in selected:
        linked=dependencies(row)
        bundles.extend([row]+linked[:4])
    # Keep imported APIs beside their page before lower-ranked page snippets.
    # Previously dependencies went last and were the first evidence cut by budget.
    # Reserve the module's list page and API before editor/map dependencies.
    # Shared component snippets must never evict the page that owns search.
    core=[]
    for _,row in candidates:
        rel=row['file'];module_match=any(module in rel.lower() for module in modules)
        if module_match and (re.search(r'/(?:index|list)\.vue$',rel,re.I) and '/lang/' not in rel or row.get('requests') or row.get('translation_labels')):
            core.append(row)
    core.sort(key=lambda row:(not row['file'].endswith('.vue'),row['file']))
    chosen=[];seen=set()
    for row in core+bundles+[row[1] for row in candidates[12:]]:
        if row['file'] in seen:continue
        seen.add(row['file'])
        if len(json.dumps(chosen+[row],ensure_ascii=False))<=max_chars:chosen.append(row)
        if len(chosen)>=16:break
    return {'kind':'h5_source_excerpts','files':chosen,
            'note':'仅为按大纲筛选的部分源码片段，非完整代码或运行证据。H5 页面仍需 WebView/DOM 能力确认；缺少 DOM 操作支持时应标记待适配，不能将网页路由当作 Flutter 路由。'}
