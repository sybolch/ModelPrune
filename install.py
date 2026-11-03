#!/usr/bin/env python3
"""Install a pinned ModelPrune distribution without changing system Python packages."""
import argparse,hashlib,io,json,os,platform,shlex,shutil,socket,stat,subprocess,sys,urllib.request,venv,webbrowser,zipfile
from pathlib import Path

SOURCE=Path(__file__).resolve().parent
VERSIONS=json.loads((SOURCE/'runtime-versions.json').read_text())

def run(cmd,**kwargs):
    print('+ '+' '.join(map(str,cmd)),flush=True)
    subprocess.run(list(map(str,cmd)),check=True,**kwargs)

def download(url,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(url,timeout=120) as response:path.write_bytes(response.read())

def get_uv(prefix):
    binary=prefix/'tools/uv';version=VERSIONS['uv']
    if binary.exists() and subprocess.check_output([binary,'--version'],text=True).split()[1]==version:return binary
    found=shutil.which('uv')
    if found and subprocess.check_output([found,'--version'],text=True).split()[1]==version:return Path(found)
    with urllib.request.urlopen('https://pypi.org/pypi/uv/'+version+'/json',timeout=30) as response:metadata=json.load(response)
    wheels=[f for f in metadata['urls'] if f['filename'].endswith('.whl') and 'manylinux_2_17_x86_64' in f['filename']]
    if len(wheels)!=1:raise RuntimeError('Unable to identify pinned Linux x86_64 uv wheel')
    record=wheels[0]
    with urllib.request.urlopen(record['url'],timeout=120) as response:content=response.read()
    if hashlib.sha256(content).hexdigest()!=record['digests']['sha256']:raise RuntimeError('uv download checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entry=next(n for n in archive.namelist() if n.endswith('/uv') and not n.endswith('/bin/uv'))
        binary.parent.mkdir(parents=True,exist_ok=True);binary.write_bytes(archive.read(entry));binary.chmod(0o755)
    return binary

def environment(uv,prefix,name,python_version,env):
    folder=prefix/'venvs'/name;python=folder/'bin/python'
    if not python.exists():run([uv,'venv','--managed-python','--python',python_version,folder],env=env)
    actual=subprocess.check_output([python,'-c','import platform;print(platform.python_version())'],text=True).strip()
    if actual!=python_version:raise RuntimeError(f'{name} uses Python {actual}, expected {python_version}; choose a fresh installation prefix')
    run([uv,'pip','sync','--python',python,SOURCE/'requirements'/f'{name}.lock'],env=env)
    return python

def copy_app(target):
    target.mkdir(parents=True,exist_ok=True)
    for file in SOURCE.glob('*.py'):
        if file.resolve()!=(target/file.name).resolve():shutil.copy2(file,target/file.name)
    for name in ['.gitignore','README.md','LICENSE','THIRD_PARTY_NOTICES.md','runtime-versions.json','install.sh','QUICKSTART.md','AGENTS.md','CHANGELOG.md']:
        file=SOURCE/name
        if file.exists() and file.resolve()!=(target/name).resolve():shutil.copy2(file,target/name)
    for name in ['requirements','fixtures','docs','third_party']:
        if (SOURCE/name).exists() and (SOURCE/name).resolve()!=(target/name).resolve():shutil.copytree(SOURCE/name,target/name,dirs_exist_ok=True)

def write_service(app,python,config,name):
    if not shutil.which('systemctl'):return False
    probe=subprocess.run(['systemctl','--user','show-environment'],capture_output=True,timeout=10)
    if probe.returncode:return False
    folder=Path.home()/'.config/systemd/user';folder.mkdir(parents=True,exist_ok=True);unit=folder/(name+'.service')
    command=' '.join('"'+str(v).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"' for v in [python,app/'report_server.py','--config',config])
    text='[Unit]\nDescription=ModelPrune local report service\nAfter=network.target\n\n[Service]\nType=simple\nWorkingDirectory='+str(app).replace('%','%%')+'\nExecStart='+command+'\nRestart=on-failure\nRestartSec=3\n\n[Install]\nWantedBy=default.target\n'
    if unit.exists() and str(app) not in unit.read_text():raise RuntimeError('Service name belongs to another installation. Choose --service-name or --no-service.')
    unit.write_text(text);run(['systemctl','--user','daemon-reload']);run(['systemctl','--user','enable','--now',unit.name]);run(['systemctl','--user','restart',unit.name]);return True

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix',type=Path,default=Path.home()/'.local/share/modelprune')
    p.add_argument('--no-images',action='store_true',help='Install only EvalScope and CPU speech grading')
    p.add_argument('--comfyui',type=Path,help='Reuse an existing ComfyUI source tree (its venv is not changed)')
    p.add_argument('--model-path',type=Path,help='Existing ComfyUI models folder; weights are not downloaded')
    p.add_argument('--asr-model',type=Path,help='Reuse an existing local Whisper tiny.en snapshot')
    p.add_argument('--ollama-host',default='http://127.0.0.1:11434');p.add_argument('--port',type=int)
    p.add_argument('--no-service',action='store_true');p.add_argument('--service-name',default='modelprune-report')
    p.add_argument('--open',action='store_true');args=p.parse_args(argv)
    if platform.system()!='Linux' or platform.machine() not in ('x86_64','AMD64'):p.error('This exact runtime snapshot targets Linux x86_64')
    prefix=args.prefix.expanduser().resolve();app=prefix/'app'
    prior_path=app/'.report-server.json';prior=json.loads(prior_path.read_text()) if prior_path.exists() else {}
    if args.port is None:
        args.port=prior.get('port')
        if args.port is None:
            for port in range(8791,8892):
                with socket.socket() as probe:
                    try:probe.bind(('127.0.0.1',port));args.port=port;break
                    except OSError:continue
    if args.port is None or not 1024<=args.port<=65535:p.error('Choose an available unprivileged port from 1024 to 65535')
    unit=Path.home()/'.config/systemd/user'/(args.service_name+'.service')
    if not args.no_service and unit.exists() and str(app) not in unit.read_text():
        if '--service-name' in (argv if argv is not None else sys.argv[1:]):p.error('Service name already belongs to another installation')
        args.service_name+='-'+hashlib.sha256(str(prefix).encode()).hexdigest()[:8]
        print('Keeping existing service; using '+args.service_name,flush=True)
    if not args.no_images and args.model_path is None:
        candidates=[Path(os.environ['COMFYUI_MODELS_DIR'])] if os.environ.get('COMFYUI_MODELS_DIR') else []
        candidates+=([args.comfyui/'models'] if args.comfyui else [])+[Path.home()/'ai/ComfyUI/models',Path.home()/'ComfyUI/models',Path.home()/'.local/share/ComfyUI/models']
        args.model_path=next((path for path in candidates if (path/'checkpoints').is_dir() and any((path/'checkpoints').glob('*.safetensors'))),None)
    prefix.mkdir(parents=True,exist_ok=True);copy_app(app)
    uv=get_uv(prefix);env={**os.environ,'UV_PYTHON_INSTALL_DIR':str(prefix/'python')}
    core=environment(uv,prefix,'evalscope',VERSIONS['python_evalscope'],env)
    speech=environment(uv,prefix,'speech',VERSIONS['python_speech'],env)
    asr=args.asr_model.expanduser().resolve() if args.asr_model else prefix/'models/whisper-tiny.en'
    if not (asr/'model.bin').exists():
        if args.asr_model:p.error('--asr-model must contain model.bin')
        run([speech,'-c','from huggingface_hub import snapshot_download;import sys;snapshot_download(repo_id=sys.argv[1],revision=sys.argv[2],local_dir=sys.argv[3])',VERSIONS['whisper_repo'],VERSIONS['whisper_revision'],asr],env=env)
    run([core,'-c','import nltk;nltk.download("punkt_tab",download_dir=__import__("sys").argv[1],raise_on_error=True)',prefix/'nltk_data'],env=env)
    comfy=None;image_python=None
    if not args.no_images:
        if not shutil.which('git'):raise RuntimeError('git is required for the pinned ComfyUI checkout; install git or use --no-images')
        comfy=args.comfyui.expanduser().resolve() if args.comfyui else prefix/'runtimes/ComfyUI'
        if args.comfyui:
            if not (comfy/'main.py').exists():p.error('--comfyui must point to a ComfyUI checkout')
            revision=subprocess.check_output(['git','-C',comfy,'rev-parse','HEAD'],text=True).strip()
            if revision!=VERSIONS['comfyui_revision']:p.error('Existing ComfyUI revision differs from the pinned runtime; omit --comfyui for a managed checkout')
        elif not (comfy/'.git').exists():
            comfy.parent.mkdir(parents=True,exist_ok=True);run(['git','init',comfy]);run(['git','-C',comfy,'remote','add','origin','https://github.com/comfyanonymous/ComfyUI.git']);run(['git','-C',comfy,'fetch','--depth','1','origin',VERSIONS['comfyui_revision']]);run(['git','-C',comfy,'checkout','--detach',VERSIONS['comfyui_revision']])
        image_python=environment(uv,prefix,'comfyui',VERSIONS['python_comfyui'],env)
        if args.model_path:
            models=args.model_path.expanduser().resolve()
            if not models.is_dir():p.error('--model-path must exist')
            # A private YAML loader config points to weights; external model stores are not modified.
            (prefix/'comfy-model-paths.yaml').write_text('modelprune:\n  base_path: '+json.dumps(str(models))+'\n  checkpoints: checkpoints\n  vae: vae\n')
    config_path=app/'.report-server.json';old=json.loads(config_path.read_text()) if config_path.exists() else {}
    import secrets
    config={'token':old.get('token') or secrets.token_urlsafe(48),'port':args.port,'service_name':args.service_name,'publish_dir':str(prefix/'outputs'),'host':args.ollama_host,'standard_limit':5,'context':4096,'tokens':256,'thinking_tokens':2048,'asr_python':str(speech),'asr_model':str(asr),'evalscope_python':str(core),'comfyui':str(comfy) if comfy else None,'comfy_python':str(image_python) if image_python else None,'nltk_data':str(prefix/'nltk_data'),'start_command':str(prefix/'modelprune')+' serve'}
    if args.model_path:config.update(comfy_model_paths=str(prefix/'comfy-model-paths.yaml'),image_model_dir=str(args.model_path.expanduser().resolve()/'checkpoints'))
    config_path.write_text(json.dumps(config,indent=2)+'\n');config_path.chmod(0o600)
    launcher=prefix/'modelprune';launcher.write_text('#!/bin/sh\nexec '+shlex.quote(str(core))+' '+shlex.quote(str(app/'launcher.py'))+' "$@"\n');launcher.chmod(0o755)
    run([core,app/'launcher.py','initialize'],env={**env,'NLTK_DATA':str(prefix/'nltk_data')})
    if not args.no_service:
        if write_service(app,core,config_path,args.service_name):
            config['start_command']='systemctl --user start '+args.service_name+'.service'
            config_path.write_text(json.dumps(config,indent=2)+'\n');config_path.chmod(0o600)
        else:
            log=(prefix/'service.log').open('a')
            child=subprocess.Popen([core,app/'report_server.py','--config',config_path],stdout=log,stderr=subprocess.STDOUT,start_new_session=True);log.close()
            (prefix/'service.pid').write_text(str(child.pid));print('Started background service (no user systemd manager).')
    print('\nInstalled: '+str(launcher)+'\nReport: '+str(prefix/'outputs/ModelPrune-report.html'))
    print('Check setup: '+shlex.quote(str(launcher))+' doctor')
    if args.open:webbrowser.open((prefix/'outputs/ModelPrune-report.html').as_uri())

if __name__=='__main__':
    try:main()
    except (OSError,RuntimeError,subprocess.SubprocessError) as error:raise SystemExit('Installation failed: '+str(error))
