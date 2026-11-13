"""User-selected Excel observation policy, separate from strict acceptance testing."""
import re
import uuid

POLICY='current_account_observe_first_match_v1'
RULES='''本轮按用户指定的观察规则执行，优先于原Excel中的账号角色和固定结果要求：
1. 使用工具已配置或当前已登录账号，不切换账号，不要求原用例指定账号或角色，不因权限身份未知阻塞。
2. 同一目标匹配多个相同元素时，按页面顺序选第一个；不为重复匹配标记受阻。
3. 搜索原文提供具体内容则使用原文；没有提供时生成普通随机搜索词。按实际源码触发搜索，不虚构搜索按钮。清空搜索框仍使用空字符串。
4. 搜索有结果或无结果均只记录实际结果；权限相关只到指定页面记录按钮/入口存在或不存在。不存在时不强行点击，结束本条并继续下一用例。
5. 不要求固定卡片数量或指定账号绑定关系才能继续。保留原始预期供对照，结果标为观察记录，不能声称原始账号权限或预期通过。
6. 页面定位、输入和提交动作仍须有依据；提交、保存不能凭成功提示推断已执行。'''


def search_operations(step,operations):
    """Bind missing search data locally; do not invent values for other fields."""
    action=step.get('action','')
    if not re.search(r'搜索|查询',action):return operations
    match=re.search(r'(?:输入|填写)\s*[：:“「\"\']*\s*(.+?)(?=点击搜索|点搜索|点击查询|后(?:点|点击)|[；。\n]|$)',action)
    literal=match[1].strip(' \t，,：“”「」\"\'') if match else None
    if len([op for op in operations if isinstance(op,dict) and op.get('action') in ('input','web_input')])>1 and re.search(r'、|依次|分别',action):literal=None
    clear=bool(re.search(r'清空|清除',action)) and not re.search(r'输入|填写',action)
    out=[]
    for op in operations:
        item=dict(op) if isinstance(op,dict) else op
        if isinstance(item,dict) and item.get('action') in ('input','web_input'):
            if literal is not None:item['text']=literal
            elif clear:item['text']=''
            elif not item.get('text'):item['text']='qa_search_'+uuid.uuid4().hex[:8]
        out.append(item)
    return out


def observation_operations(step,operations,reason='',history=()):
    """Normalize observation-only branches without inventing a product outcome."""
    action=step.get('action','')
    conditional_list=bool(re.search(r'页面有列表时|有列表时|有记录时|若有列表|如有列表',action))
    no_list=bool(re.search(r'无列表|无.{0,12}列表记录|无.{0,12}记录控件|条件分支不适用',reason))
    if conditional_list and no_list and not re.search(r'输入|填写|保存|提交|删除',action):
        return [{'action':'record','value':'列表详情条件不适用：'+reason[:300]}],''
    result=[]
    previous=next((s.get('action') for s in reversed(history) if s.get('action') in ('back','web_back','tap','web_tap','input','web_input')),None)
    for op in operations:
        item=dict(op) if isinstance(op,dict) else op
        if not isinstance(item,dict):result.append(item);continue
        # A second back needs a fresh page decision, not a blind replay.
        if item.get('action') in ('back','web_back') and previous in ('back','web_back'):
            result.append({'action':'record','value':'跳过连续返回：需重新观察页面后再决定，避免退出App'})
            continue
        result.append(item)
        if item.get('action') in ('back','web_back','tap','web_tap','input','web_input'):previous=item['action']
        if item.get('action') not in ('input','web_input'):continue
        if item.get('by')=='field' and item.get('value') in ('account','password'):continue
        by=item.get('by','text' if item['action']=='web_input' else 'label')
        result.append({'action':'web_assert_input' if item['action']=='web_input' else 'assert_input',
                       'by':by,'value':item['value'],'text':item['text']})
        result.append({'action':'web_observe' if item['action']=='web_input' else 'record',
                       'value':'记录本次输入后的提示与空态；不推定样例合法，不额外提交'})
    return result,reason


RULES+='''
7. 条件步骤（如“页面有列表时进入详情”）不适用于当前源码页面时，生成record说明不适用并继续；不要把条件不满足当成定位缺失。record仅记录观察，不代表预期通过。不能用record代替必需的输入或提交。
8. back/web_back最多连续一次；返回后重新观察再决定。登录配置根页/loginConfig不执行系统返回，以免退出App。
9. 多个输入样例必须逐个输入、核对回显、记录提示后再输入下一值，不得只检查最后一个。普通input后可跟assert_input和record；web_input后可跟web_assert_input和web_observe。登录凭据禁止使用record记录明文。
10. 国家/地区搜索框按搜索处理；abc、空格和QATest01只作测试输入，不能称为有效国家或可保存的表单。搜索随输入自动触发时，不虚构保存、失焦提交或不存在的按钮。
'''


def observation_reason(reason):
    """Separate waived acceptance conditions from missing executable evidence."""
    notes=[];blocking=[]
    for part in re.split(r'[；;\n]+',reason):
        part=part.strip()
        if not part:continue
        # Missing real locators, inputs and write evidence remain blockers.
        missing_target=bool(re.search(r'(?:缺少|未提供|无|无法).{0,35}(?:搜索框|输入框|定位|选择器|CSS|XPath|DOM|控件|method|path|codes|提交接口|写接口|验证码|密码)',part,re.I))
        missing_target=missing_target and not re.search(r'无web_assert_count|无.{0,12}格式断言',part)
        waived=bool(re.search(r'列表长度|卡片总数|精确数量|固定数量|计数|绑定关系|指定账号|账号身份|角色身份|权限身份|后台基准|后台记录|与后台数据一致|格式断言',part))
        note_only=bool(re.fullmatch(r'(?:本轮)?按(?:实际结果|实际页面|当前账号).{0,15}(?:观察|记录).*|输入随@input自动触发.*|源码无搜索按钮，不虚构点击',part))
        if not missing_target and (waived or note_only):notes.append(part)
        else:blocking.append(part)
    return '；'.join(blocking),notes


RULES+='\n11. web_observe支持by=css/xpath/text与value=真实定位，采集实际渲染匹配数、名称/文字列表和有无数据；无by时只采集反馈提示。不能仅用web_observe的文字说明代替真实采集。\n12. 固定数量、列表长度必须为0、指定角色/绑定门店、缺少后台比较基准等在本轮只作原始预期对照，不写入blocked_reason。保留实际列表、字段和提示观察；准确定位、必需输入或提交证据确实缺失时才受阻。\n'

RULES+='\n13. 已登录是业务前置状态，不是重新登录的操作要求。对于云端下发的动态菜单，用户步骤明确给出准确入口文字时，可按该文字生成观察/点击候选；静态源码未包含菜单文案不等于运行时没有入口。运行时不存在则记录并继续，不为此预先阻塞。'
