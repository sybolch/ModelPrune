"""Installed entry point: configured CLI, first report, diagnostics and local service."""
import json,os,subprocess,sys,webbrowser,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    config=json.loads((ROOT/'.report-server.json').read_text());args=sys.argv[1:];command=args[0] if args else 'open'
    if config.get('nltk_data'):os.environ['NLTK_DATA']=config['nltk_data']
    if command=='serve':os.execv(sys.executable,[sys.executable,str(ROOT/'report_server.py'),'--config',str(ROOT/'.report-server.json')])
    if command=='open':webbrowser.open((Path(config['publish_dir'])/'ModelPrune-report.html').as_uri());return
    if command=='doctor':
        import urllib.request
        for role,key in [('EvalScope','evalscope_python'),('Speech','asr_python'),('ComfyUI','comfy_python')]:
            if not config.get(key):print(role+': disabled');continue
            module={'EvalScope':'evalscope','Speech':'faster_whisper','ComfyUI':'torch'}[role]
            subprocess.run([config[key],'-c','import '+module+';import platform;print('+repr(role+': Python ')+ '+platform.python_version())'],check=True)
        subprocess.run([config['asr_python'],'-c','from faster_whisper import WhisperModel;import sys;WhisperModel(sys.argv[1],device="cpu",compute_type="int8",local_files_only=True);print("Whisper model: ready")',config['asr_model']],check=True)
        try:
            with urllib.request.urlopen(config['host']+'/api/version',timeout=3) as response:print('Ollama: '+json.load(response)['version'])
        except OSError:print('Ollama: unavailable (start Ollama before benchmarking)')
        print('Report: '+str(Path(config['publish_dir'])/'ModelPrune-report.html'));return
    if command=='initialize':
        import modelprune as m,discovery,evalscope_run
        out=Path(config['publish_dir']);out.mkdir(parents=True,exist_ok=True)
        raw=out/'ModelPrune-EvalScope-results.json'
        if raw.exists() and json.loads(raw.read_text()).get('results'):
            m.report(json.loads(raw.read_text()),out);(out/'report.html').replace(out/'ModelPrune-report.html');print('Existing data retained; report controls refreshed');return
        try:models=m.inventory(config['host'])
        except (OSError,RuntimeError):models=[]
        data=dict(version='7.0.0',engine='EvalScope '+__import__('importlib.metadata',fromlist=['version']).version('evalscope'),created=time.strftime('%Y-%m-%dT%H:%M:%S%z'),host=config['host'],hardware=m.hardware(),config={'repeats':1,'seed':42,'thinking':'off','context':config['context'],'tokens':config['tokens'],'thinking_tokens':config['thinking_tokens']},models=[],results=[],tasks=[],jobs=[],standard_limit=config['standard_limit'],fixture_hash=evalscope_run.fixture_hash(),discovery=discovery.scan(models),discovery_updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
        m.save(out/'run.json',data);m.save(raw,data);m.report(data,out)
        (out/'report.html').replace(out/'ModelPrune-report.html');return
    if command=='run':
        defaults=[]
        for key in ['host','standard_limit','asr_python','asr_model','comfyui','comfy_python','evalscope_python','comfy_model_paths','context','tokens','thinking_tokens']:
            option='--'+key.replace('_','-')
            if config.get(key) is not None and not any(a==option or a.startswith(option+'=') for a in args[1:]):defaults += [option,str(config[key])]
        os.execv(sys.executable,[sys.executable,str(ROOT/'modelprune.py'),'run',*defaults,*args[1:]])
    os.execv(sys.executable,[sys.executable,str(ROOT/'modelprune.py'),*args])

if __name__=='__main__':main()
