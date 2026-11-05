"""Mask input fields and known secret text before saving report screenshots."""
import io
import re


def mask(png, nodes, secrets, window=None):
    from PIL import Image, ImageDraw
    regions=[]
    for node in nodes:
        text=node.get('label','')+'\n'+node.get('value','')
        sensitive=any(str(value) in text for value in secrets if value)
        sensitive=sensitive or bool(re.search(r'[^\s]+@[^\s]+\.[^\s]+|(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)',text))
        if not (node.get('editable') or sensitive):continue
        bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
        if not bounds:raise ValueError('敏感内容缺少可遮挡的位置')
        rect=tuple(map(int,bounds.groups()))
        if rect[2]<=rect[0] or rect[3]<=rect[1]:raise ValueError('敏感内容位置无效')
        regions.append(rect)
    if not regions:return png
    image=Image.open(io.BytesIO(png)).convert('RGB')
    width,height=image.size
    sx=width/window['width'] if window and window.get('width') else 1
    sy=height/window['height'] if window and window.get('height') else 1
    draw=ImageDraw.Draw(image)
    for x1,y1,x2,y2 in regions:
        draw.rectangle((max(0,int(x1*sx)-3),max(0,int(y1*sy)-3),min(width,int(x2*sx)+3),min(height,int(y2*sy)+3)),fill='#283448')
    output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()
