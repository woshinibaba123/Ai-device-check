"""Run the official Midscene Agent over a private CodeBuddy stdio model bridge."""
import base64
import io
import json
from pathlib import Path
import shutil
import sys
import time
import cancellation

ROOT=Path(__file__).resolve().parent

@__import__('runtime_metrics').timed('ai_visual')
def query(png, prompt, config, *, operation='query', stopped=lambda:False, timeout=45):
    started=time.monotonic()
    from PIL import Image
    with Image.open(io.BytesIO(png)) as image:
        original_width,original_height=image.size
        # Keep SDK and CLI on the same explicit image dimensions. Large mobile
        # screenshots may otherwise be resized inside the coding CLI.
        image=image.convert('RGB')
        image.thumbnail((1280,1280))
        width,height=image.size
        output=io.BytesIO();image.save(output,format='PNG');png=output.getvalue()
    node=shutil.which('node')
    if not node:raise ValueError('Midscene 需要 Node.js')
    payload={'image':'data:image/png;base64,'+base64.b64encode(png).decode(), 'width':width,'height':height,
             'prompt':prompt,'operation':operation,'python':sys.executable,'model':config.get('midscene_model') or 'glm-5.3-flashx',
             'region':config.get('region','cn'),'timeout':max(1,int(timeout)-3)}
    traces=[]
    offset=0
    def observe(output):
        nonlocal offset
        end=output.rfind('\n')+1
        for line in output[offset:end].splitlines():
            if line.startswith('DEVICECHECK_TRACE='):
                try: event=json.loads(line.split('=',1)[1])
                except ValueError:continue
                traces.append(event)
                print('[Midscene阶段] '+json.dumps(event,ensure_ascii=False),flush=True)
        offset=end
    try:
        result=cancellation.Control(stopped).run([node,str(ROOT/'midscene/runner.cjs')],input=json.dumps(payload),capture_output=True,text=True,cwd=str(ROOT/'midscene'),timeout=timeout,on_stdout=observe)
    except __import__('subprocess').TimeoutExpired:
        raise ValueError('Midscene 视觉请求超时；最后阶段：'+(traces[-1]['stage'] if traces else 'node_start')) from None
    lines=[s for s in result.stdout.splitlines() if s.startswith('DEVICECHECK_RESULT=')]
    if not lines:raise ValueError('Midscene 未返回有效结果')
    data=json.loads(lines[-1].split('=',1)[1])
    if result.returncode or data.get('error'):
        category=data.get('category','sdk_execution')
        if data.get('detail')=='sdk_coordinate_parse':category='response_format'
        remaining=timeout-(time.monotonic()-started)
        format_failure=category=='response_format' or data.get('detail') in ('sdk_json_parse','invalid_json_response','expected_json_object','empty_model_response')
        if format_failure and not config.get('_midscene_format_retry') and remaining>=5:
            print('[Midscene恢复] 只读格式解析失败，保留当前截图重试一次，不执行点击。',flush=True)
            retry=query(png,prompt,{**config,'_midscene_format_retry':True},operation=operation,stopped=stopped,timeout=remaining)
            if operation=='locate' and isinstance(retry.get('value'),dict):
                value=retry['value'];sx=original_width/width;sy=original_height/height
                if isinstance(value.get('center'),list):value['center']=[value['center'][0]*sx,value['center'][1]*sy]
                if isinstance(value.get('rect'),dict):value['rect']={k:v*(sx if k in ('left','width') else sy) for k,v in value['rect'].items()}
            retry['model_calls']=retry.get('model_calls',1)+1
            retry['seconds']=round(time.monotonic()-started,3)
            return retry
        descriptions={'quota':'模型额度不足 quota_exhausted，请等待恢复','target_not_found':'未找到目标','response_format':'模型返回格式或坐标解析失败','model_bridge':'模型桥接失败','sdk_execution':'SDK 执行失败'}
        raise ValueError('Midscene '+('模型响应超时' if data.get('timeout') else descriptions.get(category,'SDK 执行失败'))+'；最后阶段：'+(traces[-1]['stage'] if traces else 'node_start')+'；模型='+payload['model']+'；诊断='+str(data.get('detail','unknown')))
    if operation=='locate' and isinstance(data.get('value'),dict):
        value=data['value'];sx=original_width/width;sy=original_height/height
        if isinstance(value.get('center'),list) and len(value['center'])==2:
            value['center']=[value['center'][0]*sx,value['center'][1]*sy]
        if isinstance(value.get('rect'),dict):
            value['rect']={k:v*(sx if k in ('left','width') else sy) for k,v in value['rect'].items()}
    return data

if __name__=='__main__':
    from vision_probe import test_image
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',default='glm-5.3-flashx')
    parser.add_argument('--locate',action='store_true')
    args=parser.parse_args()
    prompt='Locate the red rectangle at the lower right.' if args.locate else {'color':'Color of the rectangle', 'center_x':'Absolute pixel x of rectangle center', 'center_y':'Absolute pixel y of rectangle center'}
    print(json.dumps(query(test_image(),prompt,{'midscene_model':args.model},operation='locate' if args.locate else 'query',timeout=60),ensure_ascii=False))
