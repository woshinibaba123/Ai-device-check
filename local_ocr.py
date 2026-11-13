"""Optional macOS OCR for an already verified robot MAC, never guesses coordinates."""
import io,json,re,subprocess,tempfile
from pathlib import Path
from PIL import Image

def mac_key(text):
    if not isinstance(text,str):return None
    text=text.strip().upper()
    if not re.fullmatch(r'(?:[0-9A-FO]{2}:){5}[0-9A-FO]{2}',text):return None
    return text.replace('O','0')

def locate_mac(png,target,runner=None):
    if mac_key(target) is None:return None
    runner=Path(runner or Path(__file__).resolve().parent/'output/ocr-screen')
    if not runner.is_file():return None
    with tempfile.NamedTemporaryFile(suffix='.png') as f:
        f.write(png);f.flush()
        try:
            result=subprocess.run([str(runner),f.name],capture_output=True,text=True,timeout=10,check=True)
            rows=json.loads(result.stdout)
        except (OSError,ValueError,subprocess.SubprocessError):return None
    matches=[r for r in rows if isinstance(r,dict) and mac_key(r.get('text',''))==mac_key(target) and r.get('confidence',0)>=.9]
    if len(matches)!=1:return None
    r=matches[0]
    try:
        x,y,w,h=[float(r[k]) for k in ('x','y','width','height')]
        if not(0<=x<x+w<=1 and 0<=y<y+h<=1):return None
        with Image.open(io.BytesIO(png)) as im:width,height=im.size
        return {'center':[(x+w/2)*width,(y+h/2)*height]}
    except (KeyError,TypeError,ValueError):return None

def verified_store_header(png,store,runner=None):
    """Require full header identity and visible device-list anchors, not a fuzzy title."""
    from visual_store import canonical
    runner=Path(runner or Path(__file__).resolve().parent/'output/ocr-screen')
    if not isinstance(png,bytes) or not runner.is_file() or not store:return False
    with tempfile.NamedTemporaryFile(suffix='.png') as f:
        f.write(png);f.flush()
        try:
            result=subprocess.run([str(runner),f.name],capture_output=True,text=True,timeout=10,check=True)
            rows=json.loads(result.stdout)
        except (OSError,ValueError,subprocess.SubprocessError):return False
    title=[r for r in rows if isinstance(r,dict) and r.get('confidence',0)>=.5 and r.get('y',1)<.12 and canonical(r.get('text'))==canonical(store)]
    labels=[r.get('text','') for r in rows if isinstance(r,dict) and r.get('confidence',0)>=.8]
    return len(title)==1 and '设备' in labels and any('清洁面积' in t for t in labels)


def action_feedback(png,runner=None):
    """Read only explicit transient result messages; never infer success from a button."""
    runner=Path(runner or Path(__file__).resolve().parent/'output/ocr-screen')
    if not runner.is_file():return []
    pattern=re.compile(r'(?:复制|保存|提交|操作|创建|修改|设置|更新|重命名).{0,3}(?:成功|失败)|已复制|(?:机器人|设备).{0,2}离线|网络异常|请求失败|copied|successfully',re.I)
    with tempfile.NamedTemporaryFile(suffix='.png') as f:
        f.write(png);f.flush()
        try:
            result=subprocess.run([str(runner),f.name],capture_output=True,text=True,timeout=5,check=True)
            rows=json.loads(result.stdout)
        except (OSError,ValueError,subprocess.SubprocessError):return []
    return [r['text'][:160] for r in rows if isinstance(r,dict) and isinstance(r.get('text'),str) and r.get('confidence',0)>=.75 and pattern.search(r['text'])][:5]


def locate_bottom_tab(png,label,runner=None):
    """Require all four unique native footer labels before locating one."""
    tabs=('首页','门店','消息','我的')
    if label not in tabs:return None
    runner=Path(runner or Path(__file__).resolve().parent/'output/ocr-screen')
    if not runner.is_file():return None
    with Image.open(io.BytesIO(png)) as im:
        image_w,image_h=im.size;top=int(image_h*.90)
        footer=im.crop((0,top,image_w,image_h))
        footer=footer.resize((footer.width*2,footer.height*2))
    with tempfile.NamedTemporaryFile(suffix='.png') as f:
        footer.save(f,format='PNG');f.flush()
        try:
            result=subprocess.run([str(runner),f.name],capture_output=True,text=True,timeout=5,check=True)
            rows=json.loads(result.stdout)
        except (OSError,ValueError,subprocess.SubprocessError):return None
    found={}
    for tab in tabs:
        matches=[r for r in rows if isinstance(r,dict) and r.get('text','').strip()==tab and r.get('confidence',0)>=.9]
        if len(matches)!=1:return None
        r=matches[0]
        try:x,y,w,h=[float(r[k]) for k in ('x','y','width','height')]
        except (KeyError,TypeError,ValueError):return None
        if not (0<=x<x+w<=1 and 0<=y<y+h<=1):return None
        # Labels can overlap the Android gesture inset. Target the associated
        # icon cell immediately above the OCR label, not that system inset.
        global_y=(top+y*(image_h-top))/image_h
        global_h=h*(image_h-top)/image_h
        icon_y=global_y-1.5*global_h
        if not (.94<=global_y<1 and .90<icon_y<.98):return None
        found[tab]=(x+w/2,icon_y)
    if sorted(tabs,key=lambda t:found[t][0])!=list(tabs):return None
    return {'center':[found[label][0]*image_w,found[label][1]*image_h]}
