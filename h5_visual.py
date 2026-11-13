"""Navigation-only H5 fallback; called only after a known DOM lookup miss."""
import io,math
from PIL import Image
import cancellation,midscene_bridge
from android_visual import AndroidVisual
from visual_navigation import frame_matches

def tap(e,label,config):
    import ai_operator
    if not label or ai_operator.blocked(label):raise ValueError('该目标不允许视觉导航')
    if e.platform!='Android' or not getattr(e,'device_id',''):raise ValueError('H5 视觉恢复需要已连接的 Android 真机')
    transport=AndroidVisual(e);transport.foreground()
    image=transport.screenshot()
    result=midscene_bridge.query(image,'Locate exactly one visible navigation target labeled '+label+'. Return not found if missing or ambiguous. Do not choose save, submit, device commands or map editing controls.',config,operation='locate',stopped=e.stopped,timeout=45)
    center=result.get('value',{}).get('center')
    with Image.open(io.BytesIO(image)) as im:w,h=im.size
    if not isinstance(center,list) or len(center)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in center) or not (0<=center[0]<w and 0<=center[1]<h):raise ValueError('H5 视觉返回坐标无效，未点击')
    transport.foreground()
    if not frame_matches(image,transport.screenshot(),center):raise ValueError('H5 画面已变化，未点击旧坐标')
    cancellation.Control(e.stopped).check()
    transport.tap(int(center[0]),int(center[1]))
    e.log('H5 DOM 未找到目标，已使用 Midscene 定位点击；等待页面验证：'+label)
    return result

def describe_canvas(e,config):
    """Read-only visual summary for canvas content omitted from DOM text."""
    import hashlib,json
    transport=AndroidVisual(e);transport.foreground();image=transport.screenshot()
    digest=hashlib.sha256(image).hexdigest()
    cached=getattr(e,'_h5_canvas_summary',None)
    if isinstance(cached,tuple) and cached[0]==digest:return cached[1]
    result=midscene_bridge.query(image,{'map_state':'loaded, empty, loading, or other; only use visible evidence','visible_labels':'Visible map labels or empty-state message; do not infer hidden map data'},config,stopped=e.stopped,timeout=45)
    value=result.get('value')
    if not isinstance(value,dict):raise ValueError('画布视觉结果格式错误')
    summary=json.dumps({k:value.get(k) for k in ('map_state','visible_labels')},ensure_ascii=False)[:1500]
    e._h5_canvas_summary=(digest,summary)
    e._h5_visual_calls=getattr(e,'_h5_visual_calls',0)+result.get('model_calls',1)
    e.log('H5 自绘区域已使用 Midscene 只读识别；未执行画布操作。')
    return summary
