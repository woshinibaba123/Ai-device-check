"""App-language test matrix; selection clicks are recorded without content verification."""
import re
from pathlib import Path

LANGUAGES=[
 {'code':'zh-CN','name':'中文简体','system_language':'zh','system_country':'CN'},
 {'code':'en-US','name':'English','system_language':'en','system_country':'US'},
 {'code':'ja-JP','name':'日本語','system_language':'ja','system_country':'JP'},
 {'code':'ko-KR','name':'한국어','system_language':'ko','system_country':'KR'},
 {'code':'fr-FR','name':'Français','system_language':'fr','system_country':'FR'},
 {'code':'es-ES','name':'Español','system_language':'es','system_country':'ES'},
 {'code':'de-DE','name':'Deutsch','system_language':'de','system_country':'DE'},
 {'code':'vi-VN','name':'Tiếng Việt','system_language':'vi','system_country':'VN'},
 {'code':'it-IT','name':'Italiano','system_language':'it','system_country':'IT'},
 {'code':'zh-TW','name':'中文繁體','system_language':'zh','system_country':'TW'},
 {'code':'th-TH','name':'ไทย','system_language':'th','system_country':'TH'},
 {'code':'pt-PT','name':'Português','system_language':'pt','system_country':'PT'},
 {'code':'ru-RU','name':'Русский','system_language':'ru','system_country':'RU'},
 {'code':'ar-SA','name':'العربية','system_language':'ar','system_country':'SA'},
]

def validate(config):
    if not config or not config.get('enabled'):return []
    selected=config.get('selected',[])
    if not isinstance(selected,list) or not 1<=len(selected)<=len(LANGUAGES):raise ValueError('请选择 1～'+str(len(LANGUAGES))+' 种语言')
    known={v['code']:v for v in LANGUAGES};seen=set();result=[]
    for row in selected:
        code=row.get('code')
        if code not in known or code in seen:raise ValueError('未知或重复的语言配置')
        seen.add(code)
        path=row.get('path',[])
        if not isinstance(path,list) or len(path)>15 or not all(isinstance(v,str) and 0<len(v)<=512 for v in path):raise ValueError('语言切换路径最多 15 项按钮文字')
        if not isinstance(row.get('choice'),str):raise ValueError('语言选项需为文本')
        return_path=row.get('return_path',[])
        if not isinstance(return_path,list) or len(return_path)>15 or not all(isinstance(v,str) and 0<len(v)<=512 for v in return_path):raise ValueError('语言切换后路径最多 15 项按钮文字')
        choice=row.get('choice','').strip()
        if not choice:raise ValueError(known[code]['name']+'：请填写语言选项文字')
        if row.get('phase','after_login') not in ('before_login','after_login'):raise ValueError('语言切换阶段无效')
        result.append({**known[code],'choice':choice,'path':path,'return_path':return_path,'phase':row.get('phase','after_login')})
    return result


def expand(entries,config):
    languages=validate(config)
    if not languages:return entries
    import uuid
    if len(entries)*len(languages)>300:raise ValueError('每批最多 300 个机型与语言组合，请分批运行')
    result=[]
    for jid,cfg,label in entries:
        for language in languages:
            result.append((uuid.uuid4().hex[:12],dict(cfg,language=dict(language)),label+' · '+language['name']))
    return result


def text_findings(nodes,secrets=()):
    from automation import redact
    findings=[]
    for n in nodes:
        if n.get('editable') or n.get('secure'):continue
        label=n.get('label','').strip()
        reason=None
        if '\ufffd' in label:reason='出现替换字符，可能存在编码或字体问题'
        elif re.search(r'\{\{[^}]+\}\}|\$\{[^}]+\}',label):reason='疑似未替换的文案变量'
        elif re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+){1,8}',label):reason='疑似翻译键直接显示，需人工复核'
        if reason:findings.append({'text':redact(label,secrets)[:250],'reason':reason})
    return findings


def verify_persisted_language(explorer,config):
    """Verify the debug App's persisted locale without exporting preferences/credentials."""
    from xml.etree import ElementTree as ET
    package=getattr(explorer,'app_package','')
    if not re.fullmatch(r'[\w.]+',package):raise RuntimeError('无法确认被测 App 包名，未验证语言生效')
    response=explorer.shell(['run-as',package,'cat','/data/user/0/'+package+'/shared_prefs/FlutterSharedPreferences.xml'])
    if not response.get('ok'):raise RuntimeError('无法读取测试包的语言配置证据，不能确认切换生效')
    try:
        root=ET.fromstring(response['output'])
        actual=next((n.text or '' for n in root if n.get('name')=='flutter.selected_locale'),'')
    except (ValueError,TypeError):raise RuntimeError('语言配置证据无效') from None
    lang='zht' if config['code']=='zh-TW' else config['system_language']
    expected=lang+'_'+config['system_country']
    if actual!=expected:raise AssertionError('语言选项点击后配置未生效：预期 '+expected+'，实际 '+(actual or '未设置'))
    explorer.log('已验证 App 语言配置保存为 '+expected)
    return {'code':config['code'],'name':config['name'],'status':'confirmed','confirmation':'persisted_locale','locale':actual}


def load_runtime_aliases(explorer):
    """Merge this debug install's verified UI-language cache into local locators only."""
    import json,hashlib
    package=getattr(explorer,'app_package','')
    index=getattr(explorer,'flow_index',{})
    if not callable(getattr(explorer,'shell',None)) or not re.fullmatch(r'[\w.]+',package) or not index:return None
    folder='/data/user/0/'+package+'/files/cloud_languages_v1'
    listing=explorer.shell(['run-as',package,'ls',folder])
    if not listing.get('ok'):return None
    names=[name for name in listing['output'].splitlines() if re.fullmatch(r'[a-f0-9]{64}\.json',name)]
    if len(names)!=1:return None
    response=explorer.shell(['run-as',package,'cat',folder+'/'+names[0]])
    if not response.get('ok') or len(response['output'].encode())>8*1024*1024:return None
    try:
        data=json.loads(response['output']);scope=data.get('scope','')
        if data.get('schema')!=1 or not isinstance(scope,str) or hashlib.sha256(scope.encode()).hexdigest()+'.json'!=names[0]:return None
        raw=data['raw'];hashes=data['hashes']
        if not raw or set(raw)!=set(hashes) or len(raw)>len(LANGUAGES):return None
        packs=index.get('locale_packs',{});baseline=packs.get('en',{})
        known={'zht' if l['code']=='zh-TW' else l['system_language'] for l in LANGUAGES};extra={}
        tokens=lambda s:sorted(re.findall(r'\{[^{}]+\}',s))
        for lang,content in raw.items():
            if lang not in known or not isinstance(content,str) or len(content.encode())>512*1024 or hashlib.md5(content.encode()).hexdigest()!=hashes[lang]:return None
            values=json.loads(content)
            if not isinstance(values,dict) or len(values)>10000:return None
            for key,value in values.items():
                reference=packs.get(lang,baseline).get(key,baseline.get(key))
                if isinstance(reference,str) and isinstance(value,str) and value.strip() and len(value)<=16384 and tokens(value)==tokens(reference):extra.setdefault(key,[]).append(value)
        aliases=getattr(explorer,'control_aliases',{})
        for key,values in extra.items():
            all_values=list(dict.fromkeys(index.get('translations',{}).get(key,[])+values))
            for value in all_values:aliases[value]=all_values
        explorer.control_aliases=aliases
        # Path navigation uses source-key alias groups too, including cloud-only locales.
        explorer.runtime_translation_aliases=extra
        return {'languages':sorted(raw),'alias_keys':len(extra),'scope':'verified_local_ui_language_cache'}
    except (ValueError,TypeError,KeyError):return None
