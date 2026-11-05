import json
"""Bounded, read-only H5 page excerpts for AI planning."""
import os
import re
import posixpath
from pathlib import Path

SKIP={'node_modules','dist','build','coverage','vendor','public','.git','.next','.nuxt'}
EXT={'.vue','.tsx','.jsx','.html','.ts','.js'}


def source_index(directory):
    if not isinstance(directory,str) or not directory.strip():raise ValueError('请填写 H5 项目本地目录')
    if directory.startswith(('http://','https://','git@')):raise ValueError('H5 源码请填写下载到本机的项目目录，不是网页或 Git 地址')
    root=Path(directory).expanduser().resolve()
    if not root.is_dir():raise ValueError('H5 源码目录不存在，请填写本机文件夹路径')
    if not any((root/name).is_file() for name in ('package.json','index.html')):
        raise ValueError('请选择包含 package.json 或 index.html 的 H5 项目根目录')
    documents=[];seen=0;size=0
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
            relevant=[(n,line) for n,line in enumerate(text.splitlines(),1) if re.search(r'route|path|title|label|placeholder|input|form|button|submit|axios|fetch|router|\b(?:url|method|code|baseURL)\s*:|export\s+function|\.(?:post|get|put)\(|[\u4e00-\u9fff]',line,re.I)]
            if relevant:documents.append({'file':str(path.relative_to(root)),'text':text,'lines':relevant})
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
    candidates=[]
    for document in index['documents']:
        text=document['text'];rel=document['file']
        score=sum(min(text.count(term),5) for term in terms)+sum(4 for term in terms if term.lower() in rel.lower())
        relevant=sorted(document['lines'],key=lambda item:-sum(term in item[1] for term in terms))
        chosen=sorted(relevant[:20])
        excerpt='\n'.join(str(n)+': '+line[:280] for n,line in chosen)[:1600]
        if excerpt:candidates.append((score,{'file':rel,'excerpt':excerpt}))
    candidates.sort(key=lambda row:(-row[0],row[1]['file']))
    by_file={d['file']:d for d in index['documents']};excerpts={d['file']:d for _,d in candidates}
    selected=[row[1] for row in candidates[:12]];dependencies=[]
    for row in selected[:6]:
        document=by_file[row['file']]
        for link in re.findall(r"from\s*['\"]([^'\"]+)['\"]",document['text']):
            target='src/'+link[2:] if link.startswith('@/') else posixpath.normpath(posixpath.join(posixpath.dirname(row['file']),link)) if link.startswith('.') else ''
            if not target or not re.search(r'(?:^|/)(?:api|router)(?:/|$)',target):continue
            found=next((name for name in (target,target+'.js',target+'.ts',target+'/index.js') if name in excerpts),None)
            if found and found not in {d['file'] for d in selected+dependencies}:dependencies.append(excerpts[found])
    chosen=(selected+dependencies[:4]+[row[1] for row in candidates[12:] if row[1]['file'] not in {d['file'] for d in dependencies[:4]}])[:16]
    while chosen and len(json.dumps(chosen,ensure_ascii=False))>max_chars:chosen.pop()
    return {'kind':'h5_source_excerpts','files':chosen,
            'note':'仅为按大纲筛选的部分源码片段，非完整代码或运行证据。H5 页面仍需 WebView/DOM 能力确认；缺少 DOM 操作支持时应标记待适配，不能将网页路由当作 Flutter 路由。'}
