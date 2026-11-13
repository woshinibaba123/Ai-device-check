"""Conservative local synonyms for navigation, not unrestricted fuzzy similarity."""
import itertools
import re

ALIASES={
    '首页':('首页','主页','主页面'), '我的':('我的','个人中心','我的个人中心'),
    '消息':('消息','消息中心'), '通用设置':('通用设置','常规设置'),
    '附近门店':('附近门店','附近的门店'), '学习中心':('学习中心',),
}
VERBS=('进入','打开','跳转到','跳到','前往','访问','去到','到达','跳转至','转到','到','去')
UNSAFE=re.compile(r'不|禁止|拒绝|失败|删除|提交|支付|购买|发送|注销|密码|账号|验证码|权限|如果|否则|等待|输入|填写|保存|退出')


def target(value):
    value=value.strip().strip('“”「」\"\'')
    for key,values in ALIASES.items():
        if value in values:return key
    value=re.sub(r'(?:的)?(?:页面|页|入口|界面)$','',value).strip().strip('“”「」\"\'')
    for key,values in ALIASES.items():
        if value in values:return key
    if re.fullmatch(r'[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 _-]{1,29}',value) and not UNSAFE.search(value):return value
    return None


def parse_clause(text):
    text=text.strip().rstrip('。；;')
    text=re.sub(r'^(?:请帮我|帮我|我想要|我想|带我|请|先|再|然后|接着|随后)','',text).strip()
    if UNSAFE.search(text):return None
    match=re.fullmatch(r'(?:(?:从|在|由)(.+?)(?:中)?)?('+'|'.join(VERBS)+r')(.+)',text)
    if match:
        raw=match[3];dest=target(raw);source=target(match[1]) if match[1] else None
        known=dest in ALIASES
        explicit=bool(re.search(r'页面|界面|入口|页$|[“”「」\"\']',raw))
        if dest and (known or explicit) and (not match[1] or source):return ('navigate',source,dest)
    match=re.fullmatch(r'点击(?:底部|顶部)?(.+?)(?:按钮)?',text)
    if match:
        raw=match[1];dest=target(raw)
        if dest and (dest in ALIASES or re.search(r'页面|入口',raw)):return ('navigate',None,dest)
    return None


def parse(text):
    if not isinstance(text,str) or not text.strip():return None
    parts=re.split(r'[，,；;。\n]+|(?:然后|接着|随后)|并(?=进入|打开|跳转到|前往)',text)
    parsed=[parse_clause(p) for p in parts if p.strip()]
    return parsed if parsed and all(parsed) else None


def normalize_goal(text):
    intent=parse(text)
    if intent and len(intent)==1 and intent[0][1] is None:return '进入'+intent[0][2]
    return text


def canonical_text(text, expected=False):
    original=text
    if expected:text=re.sub(r'^(?:确认|检查|验证)(?:已)?','',text.strip())
    parsed=parse(text)
    return {'navigation':parsed} if parsed else original


def variants(text,limit=16):
    parsed=parse(text)
    if not parsed or len(parsed)!=1:return [text]
    _,source,dest=parsed[0]
    names=ALIASES.get(dest,(dest,));sources=ALIASES.get(source,(source,)) if source else (None,)
    values=[text]
    combinations=list(itertools.product(VERBS,('', '页面','页'),(dest,),(source,),('',)))
    combinations+=list(itertools.product(VERBS,('', '页面','页'),names,sources,('', '页面')))
    for verb,suffix,name,src,source_suffix in combinations:
        value=('从'+src+source_suffix if src else '')+verb+name+suffix
        if value not in values:values.append(value)
        if len(values)>=limit:break
    return values


def case_variants(case,limit=128):
    fields=('steps','title','expected')
    choices=[variants(case.get(k,''),16) for k in fields]
    count=0
    for changes in range(4):
        for positions in itertools.combinations(range(3),changes):
            ranges=[range(1,len(choices[i])) if i in positions else (0,) for i in range(3)]
            for indexes in itertools.product(*ranges):
                yield dict(case,**{k:choices[i][indexes[i]] for i,k in enumerate(fields)})
                count+=1
                if count>=limit:return
