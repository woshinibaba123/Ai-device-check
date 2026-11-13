"""Small, strict local navigation plans; every step resolves against the live page."""
import re
import unicodedata
import semantic_steps
import navigation_intents

LANGUAGES = {
    '法语': ['Français', 'French'], '英语': ['English'], '日语': ['日本語'],
    '韩语': ['한국어'], '德语': ['Deutsch'], '西班牙语': ['Español'],
    '意大利语': ['Italiano'], '俄语': ['Русский'], '葡萄牙语': ['Português'],
    '泰语': ['ไทย'], '越南语': ['Tiếng Việt'], '阿拉伯语': ['العربية'],
    '简体中文': ['中文简体', '简体中文'], '繁体中文': ['中文繁體', '繁體中文'],
}


def _compile_legacy(goal):
    text = re.sub(r'[\s，,。；;“”「」\"→>-]', '', goal)
    languages = '|'.join(LANGUAGES)
    switch = re.fullmatch(r'(?:请)?(?:进入|打开)?(?:我的)?(?:通用设置)?(?:将|把)?(?:语言)?(?:切换为|切换成|切换到|切换|改成|设置为)(' + languages + r')(?:并(?:确认|检查|验证)(?:切换)?(?:成功|生效))?', text)
    if switch:
        return {'labels': ['我的', '通用设置', '语言', LANGUAGES[switch[1]][0]], 'cursor': 0, 'kind': 'language', 'target_language': switch[1]}
    navigation = re.fullmatch(r'(?:请)?(?:进入|打开)(首页|消息|我的|通用设置)(?:页面)?', text)
    if navigation:
        target = navigation[1]
        return {'labels': ['我的', '通用设置'] if target == '通用设置' else [target], 'cursor': 0, 'kind': 'navigation'}
    return None


def compile_goal(goal):
    # Only extract an explicitly named destination, never a name invented by AI.
    text = re.sub(r'^(?:(?:请帮我|帮我|请|先)\s*)+', '', goal.strip())
    # Numbered recipes can start with prerequisites; use only a unique explicit store destination.
    destinations = re.findall(r'(?m)^\s*(?:\d+[.、]\s*)?进入门店列表[，,]\s*搜索并进入「([^」]+)」', text)
    if len(set(destinations)) == 1:
        text = '进入门店列表，搜索并进入「' + destinations[0] + '」'
    match = re.match(r'^(?:进入|打开|前往|去到|去|到)(?:门店列表|门店)(?:页面)?[，,\s]*(?:(?:然后|接着|再|并)[，,\s]*)?(?:搜索并进入|搜索并打开|搜索|查找|找到|进入|打开)\s*(?:名称为|名为)?([^，,。；;\n]{1,80})', text)
    if not match:
        match = re.match(r'^(?:在)?门店列表(?:中|里)?[，,\s]*(?:搜索并进入|搜索并打开|搜索|查找|找到)\s*([^，,。；;\n]{1,80})', text)
    if match:
        query = re.split(r'然后|之后|再进入|并进入|并打开', match[1], maxsplit=1)[0].strip().strip('「」“”"')
        if query and len(query) <= 60 and not re.search(r'下发|呼叫|取消任务|删除|提交|支付', query):
            codes = set(re.findall(r'(?<![A-Za-z0-9])S[A-Z0-9]{5,20}(?![A-Za-z0-9])', goal))
            if len(codes) <= 1:
                return {'kind': 'store_lookup', 'query': query, 'store_code': next(iter(codes), ''), 'cursor': 0}
    if not match and re.match(r'^(?:进入|打开|前往|去到|去|到|查看)(?:门店列表|门店页面|门店)(?=$|[，,。；;\s]|然后|并)', text):
        return {'kind': 'store_lookup', 'query': '', 'store_code': '', 'cursor': 0}
    return _compile_legacy(navigation_intents.normalize_goal(goal))


def store_tab(evidence):
    # Prefer the actual bottom navigation tab, never the homepage Store(count)
    # heading. Support semantics trees that omit tab-number accessibility text.
    matches = [c for c in evidence['controls'] if not c.get('blocked') and not c.get('editable') and not c.get('selected') and
               re.fullmatch(r'(?:Store|门店)(?:\s*\nTab \d+ of \d+)?', c['text'].strip(), re.I)]
    return matches[0]['id'] if len(matches) == 1 else None


def store_searches(evidence):
    return [c for c in evidence['controls'] if c.get('editable') and not c.get('blocked') and
            semantic_steps.norm(c['text']) in ('please enter the store name', '请输入门店名称', '请输入门店名', '搜索门店')]


def store_name_matches(query, label):
    def canonical(value):
        value = unicodedata.normalize('NFKC', value).strip()
        return re.sub(r'\s*\|\s*', '|', value)
    wanted, actual = canonical(query), canonical(label)
    # A branch suffix is allowed only after the complete requested name.
    # store_step still requires exactly one card across all matching branches.
    return actual == wanted or (actual.startswith(wanted + '(') and actual.endswith(')'))


def store_step(plan, evidence, raw_labels):
    controls = evidence['controls']
    searches = store_searches(evidence)
    if plan['cursor'] == 0 and not searches:
        tab = store_tab(evidence)
        if tab:
            return {'action': 'tap', 'target': tab, 'origin': 'local_path', 'path_index': 0}
    if plan['cursor'] <= 1 and plan['query'] and len(searches) == 1:
        return {'action': 'input', 'target': searches[0]['id'], 'data_key': '__goal_store_name', 'origin': 'local_path', 'path_index': 1}
    if plan['cursor'] == 2:
        # Input values are redacted in model evidence. Match original labels
        # locally, never by the redaction placeholder or a partial name.
        matches = [c for c in controls if not c.get('blocked') and not c.get('editable') and
                   any(store_name_matches(plan['query'], line) for line in raw_labels.get(c['id'], c['text']).splitlines())]
        if plan.get('store_code'):
            matches = [c for c in matches if plan['store_code'] in [line.strip() for line in raw_labels.get(c['id'], c['text']).splitlines()]]
        if matches and plan.get('first_result'):
            return {'action':'tap','target':matches[0]['id'],'origin':'local_path','path_index':2}
        if len(matches) == 1:
            return {'action': 'tap', 'target': matches[0]['id'], 'origin': 'local_path', 'path_index': 2}
        if len(matches) > 1:
            return {'action': 'blocked', 'origin': 'local_path', 'reason': '找到多个同名门店，请在目标中补充唯一门店编号，避免进入错误门店。'}
    return None


def resolve(label, evidence, groups=()):
    candidates = set(semantic_steps.terms(label, list(semantic_steps.GROUPS) + list(groups)))
    for values in LANGUAGES.values():
        if label in values:
            candidates.update(semantic_steps.norm(v) for v in values)
    matches = [c for c in evidence['controls'] if not c.get('blocked') and not c.get('editable') and any(semantic_steps.norm(line) in candidates for line in c['text'].splitlines())]
    return matches[0]['id'] if len(matches) == 1 else None


def next_step(plan, evidence, groups=(), raw_labels=None):
    if not plan:
        return None
    if plan.get('kind') == 'store_lookup':
        return store_step(plan, evidence, raw_labels or {})
    if plan['cursor'] >= len(plan['labels']):
        return {'action': 'done', 'origin': 'local_path'}
    # Start in settings/language pages too, without going back through the home tab.
    # The final language option is only chosen when the language-page label is present.
    cursor = plan['cursor']
    for i in range(cursor, min(3, len(plan['labels']))):
        ident = resolve(plan['labels'][i], evidence, groups)
        if ident:
            cursor = i
    ident = resolve(plan['labels'][cursor], evidence, groups)
    if not ident:
        return None
    return {'action': 'tap', 'target': ident, 'origin': 'local_path', 'path_index': cursor}


def queued_step(step, evidence):
    if not isinstance(step, dict) or step.get('action') not in ('tap', 'assert') or not isinstance(step.get('label'), str):
        return None
    # A model plan is a suggestion, never a locator. Re-resolve exact visible labels.
    matches = [c for c in evidence['controls'] if re.sub(r'\s*Tab \d+ of \d+\s*$', '', c['text']).strip() == step['label'].strip() and not c.get('blocked') and not c.get('editable')]
    if len(matches) != 1:
        return None
    return {'action': step['action'], 'target': matches[0]['id'], 'origin': 'ai_batch'}
