"""Private stdio model bridge. No listening socket or persisted credentials."""
import base64
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import codebuddy_bridge


def convert(messages):
    texts, images = [], []
    for message in messages:
        content = message.get('content', '')
        texts.append('ROLE: '+message.get('role','user'))
        if isinstance(content,str):texts.append(content);continue
        for part in content or []:
            if part.get('type')=='text':texts.append(part['text'])
            elif part.get('type')=='image_url':
                url=part['image_url']['url']
                if not url.startswith(('data:image/png;base64,','data:image/jpeg;base64,')):
                    raise ValueError('Only inline reviewed screenshots accepted')
                images.append(base64.b64decode(url.split(',',1)[1],validate=True))
            else:raise ValueError('Unsupported model content')
    return '\n'.join(texts),images

def normalize_response(text, response_format):
    """Remove a JSON fence without inventing fields or coordinates."""
    if not isinstance(text,str) or not text.strip():raise ValueError('empty_model_response')
    if not isinstance(response_format,dict) or response_format.get('type') not in ('json_object','json_schema'):return text
    candidate=text.strip()
    if candidate.startswith('```'):
        lines=candidate.splitlines()
        if len(lines)>=3 and lines[-1].strip()=='```':candidate='\n'.join(lines[1:-1])
    try:value=json.loads(candidate)
    except (ValueError,TypeError):
        decoder=json.JSONDecoder();objects=[];offset=0
        while offset<len(candidate):
            start=candidate.find('{',offset)
            if start<0:break
            try:item,end=decoder.raw_decode(candidate,start)
            except ValueError:
                offset=start+1;continue
            if isinstance(item,dict):objects.append(item)
            offset=end
        if len(objects)!=1:raise ValueError('invalid_json_response') from None
        value=objects[0]
    if not isinstance(value,dict):raise ValueError('expected_json_object')
    return json.dumps(value,ensure_ascii=False)


def normalize_sdk_response(text,response_format,prompt):
    # The SDK insight protocol expects an XML envelope even when the transport
    # also supplies response_format=json_object. Preserve that higher-level contract.
    if '<data-json>' not in prompt:return normalize_response(text,response_format)
    import re
    tags=re.findall(r'<data-json>(.*?)</data-json>',text,re.S) if isinstance(text,str) else []
    if len(tags)>1:raise ValueError('invalid_json_response')
    if len(tags)==1:
        json.loads(tags[0])
        return text
    candidate=text.strip() if isinstance(text,str) else ''
    try:
        value=json.dumps(json.loads(candidate),ensure_ascii=False)
    except ValueError:
        value=normalize_response(text,{'type':'json_object'})
    return '<data-json>'+value+'</data-json>'


if __name__=='__main__':
    try:
        started=time.monotonic()
        stages=set()
        def trace(stage, detail=None):
            if stage in stages:return
            stages.add(stage)
            print(json.dumps({'stage':stage,'seconds':round(time.monotonic()-started,3)}),file=sys.stderr,flush=True)
        trace('worker_started')
        request=json.load(sys.stdin)
        prompt,images=convert(request['messages'])
        if '<data-json>' in prompt:
            prompt+='\nReturn the SDK-required <data-json>JSON value</data-json> envelope; do not replace it with bare JSON.'
        elif request.get('response_format'):
            prompt+='\nRequired response format: '+json.dumps(request['response_format'])
        trace('payload_converted')
        text=codebuddy_bridge.ask(prompt,model=request.get('codebuddy_model') or 'glm-5.3-flashx',region=request.get('region','cn'),images=images,timeout=request.get('timeout',45),ui_fast=True,progress=lambda stage,label:trace('cli_'+stage))
        trace('cli_returned')
        try:
            text=normalize_sdk_response(text,request.get('response_format'),prompt)
        except ValueError:
            (Path(__file__).resolve().parent.parent/'output/midscene-invalid-response.txt').write_text(text)
            raise
        print(json.dumps({'text':text}))
    except Exception as error:
        print(json.dumps({'error':type(error).__name__, 'quota':str(error)=='quota_exhausted', 'format_error':str(error) if str(error) in ('empty_model_response','invalid_json_response','expected_json_object') else None, 'timeout':any(t in str(error).lower() for t in ('超时','timeout','timed out'))}))
        sys.exit(1)
