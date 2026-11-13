"""Hide only vConsole in a WebView socket owned by the tested Android app."""
import json
import re
import subprocess
import urllib.request
from pathlib import Path


def suppress(explorer, expression=None):
    from android_visual import AndroidVisual
    import hybrid_webview
    transport=AndroidVisual(explorer)
    package=getattr(explorer,'app_package','')
    if not re.fullmatch(r'[A-Za-z0-9_.]+',package):return False
    pids=transport.run(['shell','pidof',package]).split()
    sockets=transport.run(['shell','cat','/proc/net/unix'])
    owned=[f'webview_devtools_remote_{pid}' for pid in pids if re.search(r'@webview_devtools_remote_'+re.escape(pid)+r'\s*$',sockets,re.M)]
    if len(owned)!=1:return False
    port=transport.run(['forward','tcp:0','localabstract:'+owned[0]]).strip()
    if not port.isdigit():return False
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:'+port+'/json/list',timeout=3) as response:pages=json.load(response)
        pages=[p for p in pages if p.get('type')=='page' and p.get('webSocketDebuggerUrl')]
        if len(pages)!=1:return False
        url=pages[0]['webSocketDebuggerUrl']
        if not re.match(r'^ws://(?:127\.0\.0\.1|localhost):'+port+r'/',url):return False
        root=Path(__file__).resolve().parent
        ws=root/'.runtime/node_modules/ws'
        if not ws.is_dir():return False
        script="""const fs=require('fs');const p=JSON.parse(fs.readFileSync(0,'utf8'));const WS=require(p.module);const socket=new WS(p.url);const timer=setTimeout(()=>{socket.close();process.exit(2)},3000);socket.on('open',()=>socket.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression:p.expression,returnByValue:true}})));socket.on('message',raw=>{const r=JSON.parse(raw);if(r.id!==1)return;clearTimeout(timer);console.log(JSON.stringify(r));socket.close()});socket.on('error',()=>process.exit(2));"""
        import shutil
        node=shutil.which('node')
        if not node:return False
        result=subprocess.run([node,'-e',script],input=json.dumps({'module':str(ws),'url':url,'expression':expression or ('(()=>{'+hybrid_webview.DEBUG_OVERLAY_SETUP+"return document.getElementById('devicecheck-hide-vconsole')!==null;})()")}),capture_output=True,text=True,timeout=4)
        if result.returncode:return False
        data=json.loads(result.stdout)
        value=data.get('result',{}).get('result',{}).get('value')
        return value if expression is not None else value is True
    finally:
        transport.run(['forward','--remove','tcp:'+port])
