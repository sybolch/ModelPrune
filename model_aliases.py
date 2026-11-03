"""Group Ollama registrations by verified weight identity, not naming conventions."""
import copy,hashlib,json,re

def identity(info):
    if info.get('remote_host') or info.get('remote_model'):
        if not info.get('remote_model'):return None
        return 'remote:'+str(info.get('remote_host'))+':'+str(info.get('remote_model'))
    lines=[line.strip() for line in info.get('modelfile','').splitlines() if re.match(r'^(FROM|ADAPTER)\s+',line,re.I)]
    if not lines or not any(re.search(r'sha256[-:][0-9a-f]{64}',line,re.I) for line in lines):return None
    metadata=info.get('model_info',{})
    # Include multimodal/architecture metadata and adapters to avoid merging different models.
    signature={'weights':sorted(lines),'architecture':metadata.get('general.architecture'),'capabilities':sorted(info.get('capabilities',[])),
               'projector':info.get('projector_info'),'quantization':info.get('details',{}).get('quantization_level')}
    return hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()

def annotate(models):
    by_identity={}
    for model in models:
        key=model.get('weight_identity') or 'registration:'+model['name']
        by_identity.setdefault(key,[]).append(model)
    names={model['name'] for model in models}
    for members in by_identity.values():
        member_names={model['name'] for model in members}
        parents={model.get('details',{}).get('parent_model') for model in members}
        candidates=[model for model in members if model['name'] in parents and model.get('details',{}).get('parent_model') not in member_names] or [model for model in members if model['name'] in parents]
        canonical=min(candidates or members,key=lambda model:(bool(re.search(r'-work:',model['name'])),len(model['name']),model['name']))['name']
        for model in members:
            model['canonical_name']=canonical
            if model['name']!=canonical:model['alias_of']=canonical
    return models

def group_models(models):
    models=annotate(copy.deepcopy(models));groups={}
    for model in models:groups.setdefault(model['canonical_name'],[]).append(model)
    result=[]
    for canonical,members in groups.items():
        base=next(model for model in members if model['name']==canonical)
        registrations={}
        for model in members:
            for record in model.get('registrations') or [{'name':model['name'],'digest':model.get('digest'),'parameters':model.get('runtime_parameters',''),'context_override':model.get('context_override')}]:registrations[record['name']]=record
        base['registrations']=list(registrations.values())
        base['aliases']=[registration for registration in base['registrations'] if registration['name']!=canonical]
        result.append(base)
    return result

def resolve_requested(models,names):
    lookup={registration['name']:model['name'] for model in models for registration in model.get('registrations',[{'name':model['name']}])}
    return list(dict.fromkeys(lookup.get(name,name) for name in names))

def enrich_history(data,inventory):
    """Backfill identity only when the exact benchmarked registration digest is still present."""
    lookup={registration['name']:(group,registration) for group in inventory.get('models',[]) if group.get('source')=='Ollama' for registration in group.get('registrations',[])}
    for old in data.get('models',[]):
        pair=lookup.get(old['name'])
        if not pair:continue
        group,registration=pair
        if old.get('digest') and registration.get('digest') and old['digest']!=registration['digest']:continue
        old['weight_identity']=group.get('weight_identity');old['canonical_name']=group['name']
        if old['name']!=group['name']:old['alias_of']=group['name']
