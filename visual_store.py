"""Exact store search-result verification and read-only card navigation."""
import io
import math
import time
import unicodedata
from PIL import Image
from android_visual import AndroidVisual
import cancellation
import midscene_bridge
from visual_navigation import frame_matches


def canonical(value):
    if not isinstance(value,str):return ''
    return ''.join(unicodedata.normalize('NFKC',value).split()).replace('｜','|')


def validate_search(value,name,first_result=False):
    if not isinstance(value,dict) or value.get('page')!='store_search':raise ValueError('视觉未确认门店搜索结果页')
    if not first_result and canonical(value.get('search_text'))!=canonical(name):raise ValueError('搜索框内容与指定完整门店名不一致，未点击')
    cards=value.get('store_names')
    if not isinstance(cards,list) or any(not isinstance(v,str) for v in cards):raise ValueError('视觉门店结果格式无效')
    if first_result:
        if not cards or not cards[0].strip():raise ValueError('没有可点击的门店搜索结果')
        return cards[0]
    if sum(canonical(v)==canonical(name) for v in cards)!=1:raise ValueError('指定完整门店名未唯一匹配，未选择近似分店')


def verified_first_result(page,name):
    # First-result selection still requires confirming the entered query.
    selected=validate_search(page,name,first_result=True)
    if canonical(page.get('search_text'))!=canonical(name):
        raise ValueError('搜索框内容尚未确认与目标门店一致，未点击结果')
    return selected


def wait_identity(transport, query, selected, control, deadline, log):
    """Re-observe a transitioning page without replaying the card click."""
    last={}
    for attempt in range(4):
        control.check()
        if time.monotonic()>=deadline-1:break
        transport.foreground()
        last=query(transport.screenshot(),{'page':'Return store_detail only for a store equipment/device-list page; store_search if search results still shown; otherwise other.', 'store_name':'Exact full store title on the current detail page. Empty if absent or obscured.'})
        if isinstance(last,dict) and last.get('page')=='store_detail' and canonical(last.get('store_name'))==canonical(selected):return last
        if attempt<3 and deadline-time.monotonic()>2:
            log('门店身份尚未确认，等待页面加载后重新核对（%s/3）；不会重复点击。'%(attempt+1))
            control.sleep(min(1, max(0,deadline-time.monotonic()-1)))
    page=last.get('page','unknown') if isinstance(last,dict) else 'invalid'
    actual=last.get('store_name','') if isinstance(last,dict) else ''
    raise ValueError('已点击门店卡片，但进入后的完整门店身份尚未确认，停止后续设备操作；预期门店=%s；识别页面=%s；实际门店=%s'%(selected,page,actual or '[未识别]'))


def enter(explorer,name,config,timeout=120,on_query=None):
    deadline=time.monotonic()+timeout
    transport=AndroidVisual(explorer);control=cancellation.Control(explorer.stopped)
    calls=0
    def query(image,prompt,operation='query'):
        nonlocal calls
        control.check()
        remaining=deadline-time.monotonic()
        if remaining<=1:raise ValueError('门店视觉核对超时')
        calls+=1
        if on_query:on_query()
        return midscene_bridge.query(image,prompt,config,operation=operation,stopped=explorer.stopped,timeout=min(120,remaining))['value']
    for attempt in range(3):
        transport.foreground();image=transport.screenshot()
        page=query(image,{'page':'Return store_search for a store list page with a search input and deployment tabs, including when result cards are visible; otherwise other.', 'search_text':'Exact current value inside the store search input, not a result card.', 'store_names':'Read full store names from visible white result cards BELOW the 全部/已部署/未部署 tabs, ordered top to bottom. A card can contain province, robot count, store code, address and a right arrow. Include the bold store title; exclude the search input and tabs.'})
        try:
            selected=verified_first_result(page,name)
            break
        except ValueError as error:
            explorer.log('门店结果核对未通过：'+str(error))
            if attempt==2:raise
            explorer.log('搜索结果尚未核实，等待后重新截图核对（'+str(attempt+1)+'/2）；尚未点击门店。')
            control.sleep(2)
    explorer.log('已核对搜索内容，按用户要求选择第一张结果卡片：'+__import__('automation').redact(selected,explorer.secrets))
    point=query(image,'Locate the FIRST/TOPMOST store RESULT CARD below the search input, named '+selected+'. Select the first card even if other cards have the same name. Do not locate input, suggestions, history or toolbar.','locate')
    center=point.get('center') if isinstance(point,dict) else None
    with Image.open(io.BytesIO(image)) as im:w,h=im.size
    if not isinstance(center,list) or len(center)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in center):raise ValueError('门店卡片定位坐标无效')
    x,y=center
    if not(0<=x<w and h*.15<y<h*.9):raise ValueError('门店卡片定位落在搜索栏或导航区域，未点击')
    transport.foreground();latest=transport.screenshot()
    if not frame_matches(image,latest,center):raise ValueError('门店结果页发生变化，未点击旧坐标')
    control.check();transport.tap(int(x),int(y));explorer.log('已通过 ADB 点击第一张门店结果卡片，继续执行后续指令。');control.sleep(2)
    return {'model_calls':calls,'entry_clicked':True,'selected_store':selected,'selection_policy':'first_result'}
