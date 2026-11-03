"""Select unbenchmarked registrations and merge fresh EvalScope scores without regrading history."""
import copy
from pathlib import Path
import modelprune as m
import model_aliases

def select_models(data,installed):
    prior={model['name']:model for model in data['models']}
    scored={r['model'] for r in data['results']}
    selected=[]
    for model in model_aliases.group_models(installed):
        if not set(model['capabilities'])&{'completion','decision','speech'}:continue
        old=prior.get(model['name'])
        if old is None and model.get('weight_identity'):
            same=next((record for record in data['models'] if record.get('weight_identity')==model['weight_identity'] and record['name'] in scored),None)
            if same is not None:continue
        if old is None or model['name'] not in scored or old.get('digest')!=model.get('digest') or set(old['capabilities'])-{'coding'}!=set(model['capabilities']):selected.append(model['name'])
    return selected

def select_images(data,comfyui,image_model_dir=None):
    if not comfyui:return []
    scored={r['model'] for r in data.get('image_benchmark',{}).get('results',[])}
    old={j['model']:j.get('record',{}).get('weight_signature') for j in data.get('jobs',[]) if j.get('image') and j['status']=='completed'}
    selected=[]
    for path in sorted((Path(image_model_dir) if image_model_dir else Path(comfyui)/'models/checkpoints').glob('*.safetensors')):
        signature=[path.stat().st_size,path.stat().st_mtime_ns]
        if path.name not in scored or old.get(path.name) is not None and old[path.name]!=signature:selected.append(path.name)
    return selected

def merge(old,new):
    if old['engine']!=new['engine']:raise RuntimeError('EvalScope version changed; run a full benchmark instead')
    if old.get('fixture_hash') and new.get('fixture_hash') and old['fixture_hash']!=new['fixture_hash']:raise RuntimeError('Benchmark fixtures changed; run a full benchmark instead')
    for key in ['standard_limit']:
        if old.get(key)!=new.get(key):raise RuntimeError('Benchmark settings changed; run a full benchmark instead')
    for key in ['context','tokens','thinking_tokens','seed','thinking']:
        if old['config'].get(key)!=new['config'].get(key):raise RuntimeError('Benchmark settings changed; run a full benchmark instead')
    result=copy.deepcopy(old);replaced={model['name'] for model in new['models']}
    image_names={r['model'] for r in new.get('image_benchmark',{}).get('results',[])}
    replaced|=image_names
    retired=[r for r in old['results'] if r['model'] in replaced]
    if retired:result.setdefault('superseded_results',[]).extend(retired)
    result['models']=[model for model in old['models'] if model['name'] not in replaced]+copy.deepcopy(new['models'])
    result['results']=[r for r in old['results'] if r['model'] not in replaced]+copy.deepcopy(new['results'])
    tasks={t['id']:t for t in old['tasks']};tasks.update({t['id']:t for t in new['tasks']});result['tasks']=list(tasks.values())
    for key in ['jobs','engine_reports']:
        result[key]=[r for r in old.get(key,[]) if r['model'] not in replaced]+copy.deepcopy(new.get(key,[]))
    if image_names:
        image=copy.deepcopy(old.get('image_benchmark',new['image_benchmark']))
        image['results']=[r for r in old.get('image_benchmark',{}).get('results',[]) if r['model'] not in image_names]+copy.deepcopy(new['image_benchmark']['results'])
        result['image_benchmark']=image
    result['discovery']=copy.deepcopy(new['discovery']);result['discovery_updated']=new['created']
    result.setdefault('incremental_batches',[]).append({'created':new['created'],'models':sorted(replaced),'samples':len(new['results'])+len(new.get('image_benchmark',{}).get('results',[]))})
    return result
