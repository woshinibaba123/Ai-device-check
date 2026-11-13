"""Three-day retention for reports and disposable diagnostic files."""
import json
import shutil
import time
from datetime import datetime
from pathlib import Path


def _prune(root,jobs=None,now=None,deep=True):
    root=Path(root);now=time.time() if now is None else now;cutoff=now-3*86400
    jobs=jobs if jobs is not None else {};active={k for k,v in jobs.items() if v.get('status') in ('running','queued')}
    result={'reports':0,'files':0,'bytes':0}
    def remove(path):
        if path.is_symlink():return
        result['bytes']+=sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink()) if path.is_dir() else path.stat().st_size
        if path.is_dir():shutil.rmtree(path)
        else:path.unlink()
    for folder in (root/'reports').glob('*'):
        if not folder.is_dir() or folder.is_symlink() or folder.name in active:continue
        stamp=folder.stat().st_mtime
        try:
            data=json.loads((folder/'report.json').read_text())
            value=data.get('finished') or data.get('started')
            if value:stamp=datetime.strptime(value,'%Y-%m-%d %H:%M:%S').timestamp()
        except (OSError,ValueError,TypeError):pass
        if stamp<cutoff:
            remove(folder);jobs.pop(folder.name,None);result['reports']+=1
    # Never touch build tools, credentials, scripts or learned navigation.
    if not active and deep:
        for name in ('tmp/pdfs','midscene/midscene_run/report','midscene/midscene_run/log','midscene/midscene_run/screenshots'):
            for p in (root/name).rglob('*'):
                if p.is_file() and not p.is_symlink() and p.stat().st_mtime<cutoff:
                    remove(p);result['files']+=1
    if not active and deep:
        references=''
        for metadata in (root/'.runtime/pipeline-builds').rglob('*.json'):
            try:references+=metadata.read_text()
            except (OSError,UnicodeError):pass
        for folder in (root/'.runtime').glob('login-source-*'):
            if not folder.is_dir() or folder.is_symlink() or str(folder) in references:continue
            stamp=max(folder.stat().st_mtime,getattr(folder.stat(),'st_birthtime',0))
            if stamp<cutoff:
                remove(folder);result.setdefault('source_copies',0);result['source_copies']+=1
    return result

def prune(root,jobs=None,now=None,deep=True):
    import fcntl
    lock=Path(root)/'.runtime/retention.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'skipped':'cleanup_already_running'}
        try:return _prune(root,jobs,now,deep)
        finally:fcntl.flock(handle,fcntl.LOCK_UN)

if __name__=='__main__':
    import urllib.request
    root=Path(__file__).resolve().parent;jobs={}
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/jobs',timeout=5) as response:jobs={j['id']:j for j in json.load(response)}
    except Exception:
        # Without service state, preserve unfinished on-disk tasks.
        for p in (root/'reports').glob('*/report.json'):
            try:
                j=json.loads(p.read_text())
                if j.get('status') in ('running','queued'):jobs[j['id']]=j
            except (OSError,ValueError,KeyError):pass
    print(json.dumps(prune(root,jobs),ensure_ascii=False))
