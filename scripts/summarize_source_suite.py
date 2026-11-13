"""Summarize real runs without counting blocked or skipped modules as passes."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/source-test-suite/auto-run'
records=[]
for p in OUT.glob('0*/summary.json'):
 try:row=json.loads(p.read_text())
 except (OSError,ValueError):continue
 records.append(row)
records.sort(key=lambda r:r.get('started',''))
latest={}
for r in records:latest[(r['module'],r['language'])]=r
rows=list(latest.values());status={'attempts':len(records),'latest':rows,'passed':sum(r['status']=='passed' for r in rows),'needs_repair':sum(r['status']!='passed' for r in rows)}
(OUT/'suite-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
lines=['# 五模块实际执行结果','','以下仅表示设备端实际执行，当前先验证日语；未运行的语言不计通过。','','| 模块 | 语言 | 最新结果 | 报告 |','|---|---|---|---|']
for r in rows:lines.append(f'| {r["module"]} | {r["language"]} | {r["status"]} | [打开报告目录]({r["report"]}) |')
lines+=['','未出现在表中的模块尚未完成；所有尝试及失败证据保留在当前目录。']
(OUT/'实际执行结果.md').write_text('\n'.join(lines))
print(json.dumps({'attempts':status['attempts'],'latest':[{k:r[k] for k in ('module','language','status')} for r in rows]},ensure_ascii=False))
