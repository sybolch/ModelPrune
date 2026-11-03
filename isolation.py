"""Enforce one loaded Ollama model at a time, with observable /api/ps checks."""
import time


def loaded(api,host):
    response=api(host,'/api/ps',timeout=15)
    models=response.get('models')
    if not isinstance(models,list): raise RuntimeError('Cannot verify isolation: invalid /api/ps response')
    names=[model.get('name') or model.get('model') for model in models]
    if any(not isinstance(name,str) or not name for name in names):
        raise RuntimeError('Cannot verify isolation: loaded model has no name')
    return names


def stop_others(api,host,keep=None,timeout=30):
    deadline=time.monotonic()+timeout
    stopped=[]
    while True:
        names=loaded(api,host)
        others=[name for name in names if name!=keep]
        if not others: return {'stopped':stopped,'remaining':names,'checked_at':time.time()}
        for name in others:
            if time.monotonic()>=deadline: raise RuntimeError('Model isolation timed out: '+', '.join(others))
            api(host,'/api/generate',{'model':name,'keep_alive':0},timeout=max(1,deadline-time.monotonic()))
            if name not in stopped: stopped.append(name)
        if time.monotonic()>=deadline: raise RuntimeError('Model isolation timed out: '+', '.join(others))
        time.sleep(0.1)


def failure_reason(folder,fallback):
    """Promote a worker's actionable isolation error instead of hiding it behind exit status."""
    from pathlib import Path
    for name in ('worker.log','evalscope.log'):
        path=Path(folder)/name
        if not path.exists():continue
        try:lines=path.read_text(errors='replace').splitlines()
        except OSError:continue
        for line in reversed(lines):
            if 'RuntimeError:' in line and 'isolation' in line.lower():
                reason=line.split('RuntimeError:',1)[1].strip()
                return reason+'. Another application may be using Ollama; stop its local inference before retrying.'
    return fallback
