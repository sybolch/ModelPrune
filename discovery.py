"""Read-only discovery of local model stores and standalone weight files.

No weight loading, pickle deserialization, code imports from models, or downloads.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct

WEIGHTS={'.gguf','.ggml','.safetensors','.onnx','.pt','.pth','.ckpt','.tflite','.h5','.hdf5'}
SKIP={'node_modules','.git','.svn','__pycache__','.venv','venv','site-packages','dist-packages',
      'overlay','overlay2','volumes','overlay-containers','overlay-images','blobs','.no_exist','xet','Trash','.Trash','shadercache','compatdata','proc','sys','dev'}


def read_json(path):
    try:
        if path.stat().st_size>16*1024*1024: return {}
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError): return {}


def default_roots():
    home=Path.home()
    roots=[home/'.cache/huggingface/hub',home/'.lmstudio/models',home/'.cache/lm-studio/models',
           home/'.local/share/nomic.ai/GPT4All',home/'.local/share/Steam/steamapps/common/Proton Voice Files',
           home/'.ollama/models',Path('/usr/share/ollama/.ollama/models'),Path('/var/lib/ollama/models')]
    for key in ['HF_HUB_CACHE','HUGGINGFACE_HUB_CACHE','TRANSFORMERS_CACHE','HF_HOME','LM_STUDIO_MODELS_DIR','OLLAMA_MODELS']:
        if os.environ.get(key): roots.append(Path(os.environ[key]).expanduser())
    # Container/Flatpak applications keep model stores underneath these locations.
    for app in (home/'.var/app').glob('*'):
        roots.extend([app/'data',app/'cache/huggingface'])
    for volume_root in [home/'.local/share/containers/storage/volumes',Path('/var/lib/docker/volumes')]:
        try:
            for data in volume_root.glob('*/_data'):
                roots.extend([data/'models',data/'.ollama/models',data/'.cache/huggingface',data/'huggingface'])
                if (data/'manifests').is_dir() and (data/'blobs').is_dir():roots.append(data)
        except OSError:pass
    roots.extend([home,Path('/data'),Path('/opt'),Path('/mnt'),Path('/media'),Path('/run/media')])
    return roots


def is_weight(path):
    if path.suffix.lower() in {'.pt','.pth','.ckpt'}:
        try:
            with path.open('rb') as stream:header=stream.read(4)
            return header.startswith((b'PK\x03\x04',b'\x80\x02',b'\x80\x03',b'\x80\x04',b'\x80\x05'))
        except OSError:return False
    if path.suffix.lower() in WEIGHTS: return True
    return path.suffix.lower()=='.bin' and (path.name.startswith(('pytorch_model','ggml-','adapter_model'))
        or path.name=='model.bin' or (path.parent/'config.json').is_file())


def gguf_metadata(path):
    """Read bounded GGUF metadata only; never map/load tensor weights."""
    wanted={}
    with path.open('rb') as stream:
        def unpack(fmt):
            size=struct.calcsize(fmt);raw=stream.read(size)
            if len(raw)!=size: raise ValueError('Truncated GGUF metadata')
            return struct.unpack(fmt,raw)[0]
        def string(retain=True):
            length=unpack('<Q')
            if length>16*1024*1024: raise ValueError('GGUF string exceeds metadata limit')
            if retain:
                raw=stream.read(length)
                if len(raw)!=length: raise ValueError('Truncated GGUF string')
                return raw.decode('utf-8',errors='replace')
            stream.seek(length,1)
        formats={0:'<B',1:'<b',2:'<H',3:'<h',4:'<I',5:'<i',6:'<f',7:'<?',10:'<Q',11:'<q',12:'<d'}
        def value(kind,retain=True,depth=0):
            if depth>4: raise ValueError('Nested GGUF metadata too deep')
            if kind==8:return string(retain)
            if kind==9:
                subtype=unpack('<I');count=unpack('<Q')
                if count>10_000_000:raise ValueError('GGUF array exceeds metadata limit')
                if subtype in formats:
                    stream.seek(struct.calcsize(formats[subtype])*count,1)
                else:
                    for _ in range(count):value(subtype,False,depth+1)
                return None
            if kind not in formats:raise ValueError('Unknown GGUF metadata type')
            return unpack(formats[kind])
        if stream.read(4)!=b'GGUF' or unpack('<I') not in (2,3):raise ValueError('Unsupported GGUF header')
        unpack('<Q');count=unpack('<Q')
        if count>100_000:raise ValueError('GGUF metadata exceeds limit')
        for _ in range(count):
            key=string();kind=unpack('<I')
            retain=key in ('general.architecture','general.name','general.parameter_count') or key.endswith(('.context_length','.expert_count','.expert_used_count'))
            result=value(kind,retain)
            if retain:wanted[key]=result
    return wanted


def describe(directory,files):
    config=read_json(directory/'config.json')
    pipeline=read_json(directory/'model_index.json')
    architecture=config.get('model_type') or pipeline.get('_class_name')
    category='Unknown model'
    if pipeline or any('diffusion' in str(p).lower() or 'controlnet' in str(p).lower() for p in files):category='Image generation / component'
    elif config.get('model_type')=='whisper' or (directory/'preprocessor_config.json').exists() and (directory/'vocabulary.json').exists():category='Speech recognition'
    elif any('ForCausalLM' in name for name in config.get('architectures',[])):category='Generative language'
    elif any('Classification' in name for name in config.get('architectures',[])):category='Classification'
    elif (directory/'modules.json').exists():category='Embedding'
    if 'whisper' in str(directory).lower():category='Speech recognition'
    if 'comfyui' in str(directory).lower():category='Image generation / component'
    if 'lora' in str(directory).lower() or (directory/'adapter_config.json').is_file():category='Adapter / LoRA'
    if any(path.suffix=='.onnx' and Path(str(path)+'.json').is_file() for path in files):category='Speech synthesis'
    context=config.get('max_position_embeddings') or config.get('n_positions')
    metadata={}
    gguf=next((path for path in files if path.suffix.lower()=='.gguf'),None)
    if gguf:
        try:metadata=gguf_metadata(gguf)
        except (OSError,ValueError,struct.error) as error:metadata={'inspection_error':str(error)}
        architecture=metadata.get('general.architecture',architecture)
        context=max((v for k,v in metadata.items() if k.endswith('.context_length') and isinstance(v,int)),default=context)
        if architecture and category=='Unknown model':category='GGUF model'
    return {'category':category,'architecture':architecture,'context':context,'metadata':metadata}


def scan(ollama_models=(),roots=None,max_entries=5_000_000):
    roots=default_roots() if roots is None else [Path(p).expanduser() for p in roots]
    records=[];warnings=[];visited=set();weight_groups={};scanned_roots=[];entries=0;limited=False
    def warning(text):
        if len(warnings)<50:warnings.append(text)
    def record(name,source,directory,files,revision=None):
        unique=[];local_seen=set()
        for path in files:
            try:
                stat=path.stat();identity=(stat.st_dev,stat.st_ino)
                if not stat.st_size or identity in local_seen:continue
                local_seen.add(identity);unique.append((path,stat,identity))
            except OSError:continue
        if not unique:return
        fingerprint=frozenset(local_seen)
        if fingerprint in weight_groups:
            existing=weight_groups[fingerprint]
            alias={'source':source,'path':str(directory),'name':name,'revision':revision}
            if alias not in existing.setdefault('aliases',[]):existing['aliases'].append(alias)
            return
        paths=[p for p,_,_ in unique]
        info=describe(directory,paths)
        indexes=list(directory.glob('*.index.json'))
        missing=[]
        for index in indexes:
            weights=read_json(index).get('weight_map',{})
            if isinstance(weights,dict):missing.extend(str(x) for x in set(weights.values()) if not (directory/str(x)).is_file())
        identity=f'{source}:{directory}:{name}:{revision}'
        records.append(dict(id=hashlib.sha256(identity.encode()).hexdigest()[:16],name=name,source=source,
            path=str(directory),files=[str(p) for p in paths],size=sum(st.st_size for _,st,_ in unique),
            revision=revision,weight_files=len(paths),status='Incomplete weights' if missing else 'Weights found; not benchmarked',
            missing_shards=missing,benchmarkable=False,capabilities=[],**info))
        weight_groups[fingerprint]=records[-1]
    # Preserve official Ollama metadata, while keeping discovery independent of daemon availability.
    from model_aliases import group_models
    for model in group_models(ollama_models):
        records.append(dict(id='ollama:'+model['name'],source='Ollama',path=None,files=[],category='Embedding' if 'embedding' in model.get('capabilities',[]) else 'Decision' if 'decision' in model.get('capabilities',[]) else 'Generative language',
            benchmarkable=bool(set(model.get('capabilities',[]))&{'completion','decision','speech'}),
            status='Remote inference via Ollama; benchmark available' if model.get('remote') else 'Ollama benchmark available' if set(model.get('capabilities',[]))&{'completion','decision','speech'} else 'Skill suite not implemented; not benchmarked',**model))
    for root in roots:
        if not root.is_dir():continue
        scanned_roots.append(str(root))
        def walk_error(error):warning(f'Cannot scan {error.filename}: {error.strerror}')
        for current,dirs,files in os.walk(root,followlinks=False,onerror=walk_error):
            directory=Path(current)
            try:stat=directory.stat();identity=(stat.st_dev,stat.st_ino)
            except OSError:dirs[:]=[];continue
            if identity in visited:dirs[:]=[];continue
            visited.add(identity);entries+=len(dirs)+len(files)
            if entries>max_entries:
                warning(f'Scan limit reached ({max_entries} entries); add focused --scan-path folders or raise --scan-limit.');limited=True;dirs[:]=[];break
            if directory.name=='manifests' and (directory.parent/'blobs').is_dir():
                known={model['name'] for model in records if model['source']=='Ollama'}
                for manifest in directory.rglob('*'):
                    if not manifest.is_file():continue
                    spec=read_json(manifest)
                    layers=spec.get('layers',[])
                    if not isinstance(layers,list):continue
                    model_layers=[layer for layer in layers if isinstance(layer,dict) and layer.get('mediaType')=='application/vnd.ollama.image.model']
                    if not model_layers:continue
                    parts=manifest.relative_to(directory).parts
                    if len(parts)<3:continue
                    name=('/'.join(parts[1:-1]) if len(parts)>3 and parts[1]!='library' else parts[-2])+':'+parts[-1]
                    if name in known:continue
                    weights=[]
                    for layer in layers:
                        digest=layer.get('digest','') if isinstance(layer,dict) else ''
                        if re.fullmatch(r'sha256:[0-9a-f]{64}',digest):
                            blob=directory.parent/'blobs'/digest.replace(':','-')
                            if blob.is_file():weights.append(blob)
                    if not weights:continue
                    if not any(re.fullmatch(r'sha256:[0-9a-f]{64}',layer.get('digest','')) and (directory.parent/'blobs'/layer['digest'].replace(':','-')).is_file() for layer in model_layers):continue
                    records.append(dict(id='ollama:'+name,name=name,source='Ollama',path=str(manifest),files=[str(p) for p in weights],
                        size=sum(p.stat().st_size for p in weights),category='Ollama model',capabilities=[],benchmarkable=False,
                        status='Local manifest found; daemon unavailable or model not listed'))
                    known.add(name)
                dirs[:]=[];continue
            # Hugging Face snapshots are model revisions, not separate model components.
            if directory.name.startswith('models--') and (directory/'snapshots').is_dir():
                for snapshot in sorted((directory/'snapshots').iterdir()):
                    if snapshot.is_dir():
                        weights=[path for path in snapshot.rglob('*') if path.is_file() and is_weight(path)]
                        record(directory.name[8:].replace('--','/'),'Hugging Face',snapshot,weights,snapshot.name)
                dirs[:]=[];continue
            dirs[:]=[name for name in dirs if name not in SKIP and name not in {'.codex','.npm','.rustup','.cargo','Steam','steam','uv','pip','snapshots','lost+found'}]
            paths=[directory/name for name in files if is_weight(directory/name)]
            if paths:
                # Group real model bundles/shards, not unrelated image checkpoints in one folder.
                bundle=bool((directory/'config.json').is_file() or (directory/'model_index.json').is_file() or list(directory.glob('*.index.json')))
                grouped=[path for path in paths if bundle and path.suffix.lower() not in {'.gguf','.onnx','.ggml'}]
                if grouped:record(directory.name,'Model files',directory,grouped)
                shards={}
                for path in paths:
                    if path in grouped:continue
                    key=re.sub(r'-\d{5}-of-\d{5}(?=\.gguf$)','',path.name)
                    shards.setdefault(key,[]).append(path)
                for name,group in shards.items():
                    source='ComfyUI' if 'comfyui' in str(directory).lower() else 'AI Lab' if 'ai-lab' in str(directory).lower() else 'LM Studio' if any('lmstudio' in str(p).lower() or 'lm-studio' in str(p).lower() for p in [directory]) else 'Jan' if '/jan/' in str(directory).lower() else 'GPT4All' if 'gpt4all' in str(directory).lower() else 'Model files'
                    record(name,source,directory,group)
        if limited:break
    return {'models':records,'roots':scanned_roots,'warnings':warnings,'entries_scanned':entries,'limited':limited,
            'scope':'Ollama inventory plus readable model stores and weight files in the listed search roots; inaccessible locations and unrecognized formats cannot be guaranteed.'}
