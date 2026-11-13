"""Midscene navigation-only coordinate fallback with current-frame validation."""
import base64
import hashlib
import io
import math
import json
from pathlib import Path
from PIL import Image, ImageChops
import automation
import cancellation
import midscene_bridge
import screenshot_privacy
from android_visual import AndroidVisual

ALLOWED = {'我的','通用设置','语言','语言设置','法语','Français','French','首页','门店','消息','设置','地图','清洁记录','日语','日本語','英语','English','门店搜索输入框'}

def remember_store_entry(explorer,png,center):
    """Seed a screenshot-validated cache from an actual native store tab."""
    if not getattr(explorer,'app_package',''):return
    with Image.open(io.BytesIO(png)) as im:
        footer=im.convert('RGB').crop((0,int(im.height*.93),im.width,im.height))
        key=hashlib.sha256(('门店'+str(im.size)+explorer.app_package).encode()+footer.tobytes()).hexdigest()
    path=Path(__file__).resolve().parent/'.runtime/search-locate-cache.json'
    try:cache=json.loads(path.read_text())
    except (OSError,ValueError):cache={}
    cache[key]=list(center)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(dict(list(cache.items())[-20:])))


def frame_matches(before, after, center):
    try:return _frame_matches(before, after, center)
    except (OSError, ValueError):return False


def _frame_matches(before, after, center):
    """Ignore status-bar updates and tiny rendering noise; reject changed targets/scenes."""
    with Image.open(io.BytesIO(before)) as a, Image.open(io.BytesIO(after)) as b:
        if a.size != b.size:return False
        a=a.convert('RGB');b=b.convert('RGB');w,h=a.size
        x,y=center
        if y < h*.06:return False
        def changed(box):
            left=a.crop(box);right=b.crop(box)
            diff=ImageChops.difference(left,right)
            return sum(max(pixel)>35 for pixel in diff.getdata()) / max(1,diff.width*diff.height)
        radius=max(16,int(min(w,h)*.04))
        target=(max(0,int(x)-radius),max(int(h*.06),int(y)-radius),min(w,int(x)+radius),min(h,int(y)+radius))
        return changed(target) <= .01 and changed((0,int(h*.06),w,h)) <= .02


def _tap_once(explorer, label, config, source=None, timeout=60):
    if label not in ALLOWED:
        raise ValueError('该目标未开放视觉导航点击，请使用专用流程')
    control=cancellation.Control(explorer.stopped);control.check()
    nodes=automation.parse_ui(source) if source else []
    if any(n.get('secure') or n.get('editable') for n in nodes):raise ValueError('输入页面不执行视觉导航')
    transport = AndroidVisual(explorer) if explorer.platform == 'Android' else None
    if transport:
        transport.foreground()
        raw=transport.screenshot()
        with Image.open(io.BytesIO(raw)) as image: width,height=image.size
        rect={'width':width,'height':height}
    else:
        rect=explorer.call('GET',explorer.base+'/window/rect')
        raw=base64.b64decode(explorer.call('GET',explorer.base+'/screenshot'),validate=True)
    png=screenshot_privacy.mask(raw,nodes,explorer.secrets,rect)
    cache_file=Path(__file__).resolve().parent/'.runtime/search-locate-cache.json'
    cache_key=None;cache={};result=None
    if label in ('门店搜索输入框','门店'):
        with Image.open(io.BytesIO(png)) as im:
            # Match the search-header pixels, excluding the volatile status bar.
            header=im.convert('RGB').crop((0,int(im.height*(.93 if label=='门店' else .06)),im.width,int(im.height*(1 if label=='门店' else .25))))
            cache_key=hashlib.sha256((label+str(im.size)+getattr(explorer,'app_package','')).encode()+header.tobytes()).hexdigest()
        try:cache=json.loads(cache_file.read_text())
        except (OSError,ValueError):cache={}
        cached=cache.get(cache_key)
        if isinstance(cached,list) and len(cached)==2:
            result={'value':{'center':cached},'model_calls':0,'seconds':0}
            explorer.log('门店搜索页画面命中已验证位置，直接复用搜索框，无需等待 AI。')
    if result is None:
        if config.get('_cached_navigation_only'):raise ValueError('当前画面未命中导航位置缓存')
        prompt='Locate exactly one visible navigation control labeled '+label+'. Do not choose a submit, logout, delete, login or device command. If ambiguous or absent, report not found.'
        if label=='门店搜索输入框':
            prompt='Locate the CENTER of the gray rounded search input ABOVE the 全部/已部署/未部署 tabs. Never locate those filter tabs. It may show 请输入门店名称, 请输入门店名, 搜索门店, Please enter the store name, Search, or a magnifying-glass icon. 门店搜索输入框 describes its function; it is not literal text on screen. Return the center of the visible search input/entry. Exclude store result cards and bottom navigation. If absent or ambiguous, report not found.'
        result=midscene_bridge.query(png,prompt,config,operation='locate',stopped=explorer.stopped,timeout=timeout)
    value=result['value'];center=value.get('center')
    with Image.open(io.BytesIO(png)) as image:w,h=image.size
    if not isinstance(center,list) or len(center)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in center):raise ValueError('Midscene 返回无效坐标')
    x,y=center
    if not (0<=x<w and 0<=y<h):raise ValueError('Midscene 坐标超出截图')
    control.check()
    latest=transport.screenshot() if transport else base64.b64decode(explorer.call('GET',explorer.base+'/screenshot'),validate=True)
    explorer.log('Midscene locate: label='+label+', image='+str((w,h))+', center='+str(center)+', seconds='+str(result.get('seconds')))
    stable=frame_matches(raw,latest,center)
    if label=='门店' and cache_key:
        # Homepage carousels animate independently of the persistent tab bar.
        # Validate the complete navigation bar rather than the advertising area.
        with Image.open(io.BytesIO(raw)) as before, Image.open(io.BytesIO(latest)) as after:
            box=(0,int(before.height*.93),before.width,before.height)
            stable=before.size==after.size and before.crop(box).convert('RGB').tobytes()==after.crop(box).convert('RGB').tobytes()
    if not stable:
        raise FrameChanged('视觉识别期间页面发生变化，未点击；坐标='+str(center)+'，截图尺寸='+str((w,h)))
    if transport:transport.foreground()
    if cache_key:
        cache[cache_key]=center
        cache_file.parent.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps(dict(list(cache.items())[-20:])))
    x=int(x*rect['width']/w);y=int(y*rect['height']/h)
    control.check()
    if transport:
        transport.tap(x,y)
    else:
        explorer.call('POST',explorer.base+'/actions',{'actions':[{'type':'pointer','id':'midscene-nav','parameters':{'pointerType':'touch'},'actions':[{'type':'pointerMove','duration':0,'x':x,'y':y},{'type':'pointerDown','button':0},{'type':'pointerUp','button':0}]}]})
    return {'label':label,'seconds':result.get('seconds'),'model_calls':result.get('model_calls',1),'center':[x,y]}


class FrameChanged(ValueError):
    pass


def tap(explorer, label, config, source=None, timeout=60):
    import time
    started=time.monotonic()
    for attempt in range(2):
        remaining=timeout-(time.monotonic()-started)
        if remaining<=1:raise ValueError('Visual recovery time limit exceeded')
        try:return _tap_once(explorer,label,config,source,remaining)
        except FrameChanged:
            if attempt:raise
            explorer.log('Frame changed; discard coordinates and locate once more.')
            cancellation.Control(explorer.stopped).sleep(.5)
        except ValueError as error:
            # Only retry a failed search locate: no click has been performed.
            if label!='门店搜索输入框' or attempt or not any(v in str(error) for v in ('未找到目标','target_not_found')):
                raise
            explorer.log('搜索框首次未识别，等待页面加载后重新截图定位一次；不复用旧坐标。')
            cancellation.Control(explorer.stopped).sleep(1)
        except OSError:
            raise ValueError('Invalid visual screenshot; no click executed') from None


def target_matches(before, after, center):
    """Local stability check after semantic validation of the current scene."""
    try:
        with Image.open(io.BytesIO(before)) as a, Image.open(io.BytesIO(after)) as b:
            if a.size != b.size:return False
            w,h=a.size;x,y=center
            if not (0<=x<w and h*.06<y<h):return False
            radius=max(24,int(min(w,h)*.06))
            box=(max(0,int(x)-radius),max(0,int(y)-radius),min(w,int(x)+radius),min(h,int(y)+radius))
            diff=ImageChops.difference(a.convert('RGB').crop(box),b.convert('RGB').crop(box))
            return sum(max(pixel)>35 for pixel in diff.getdata()) / max(1,diff.width*diff.height)<=.01
    except (OSError,ValueError):return False
