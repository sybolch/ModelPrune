"""ModelPrune fixtures as native EvalScope datasets and metrics. No legacy scores."""
import base64,json,time,subprocess,urllib.request,urllib.parse
from pathlib import Path
from evalscope.api.benchmark import BenchmarkMeta,DefaultDataAdapter
from evalscope.api.dataset import Sample,MemoryDataset,DatasetDict
from evalscope.api.model import ModelAPI,ModelOutput
from evalscope.api.metric import Score
from evalscope.api.messages import ChatMessageUser
from evalscope.api.registry import register_benchmark,register_model_api
import modelprune as m,skill_tasks,isolation,image_benchmark as images

CONTEXT={}
PROCESS=None

def group(task):
    if task.get('category') in ('code-tracing','code-debugging'):return 'coding'
    return task.get('skill') or 'core'

def selected_tasks(name):
    if name=='image-generation':return [dict(t,kind='image-generation',category='image-generation',skill='image-generation') for t in images.TASKS]
    return [t for t in m.suite() if group(t)==name and m.applicable(CONTEXT['model_record'],t)]

class FixtureAdapter(DefaultDataAdapter):
    def load_dataset(self):
        category=self.name.removeprefix('modelprune_').replace('_','-')
        samples=[Sample(id=index,input=[ChatMessageUser(content=t['id'])],target=json.dumps(t.get('expected')),metadata={'task':t}) for index,t in enumerate(selected_tasks(category))]
        self.test_dataset=DatasetDict({'default':MemoryDataset(samples,name=self.name)})
        return self.test_dataset
    def match_score(self,original_prediction,filtered_prediction,reference,task_state):
        result=json.loads(original_prediction);task=task_state.metadata['task']
        passed=False
        if not result.get('error') and not result.get('truncated') and result.get('thinking_present',True):
            if task['kind']=='image-generation':
                passed,metrics=images.grade(base64.b64decode(result['image_b64']),task)
                result['metrics']=metrics
            else:passed=m.task_equal(result.get('answer'),task)
        return Score(value={'acc':float(passed)},main_score_name='acc',prediction=original_prediction,
                     extracted_prediction=json.dumps(result.get('answer')),metadata={'task_id':task['id'],'level':task['level'],'transport_error':result.get('error'),'image_metrics':result.get('metrics')})

for category in ['core','coding','vision','audio','speech','tools','thinking','image-generation']:
    register_benchmark(BenchmarkMeta(name='modelprune_'+category.replace('-','_'),pretty_name='ModelPrune '+category,
      dataset_id='modelprune-local-fixtures',subset_list=['default'],few_shot_num=0,train_split=None,eval_split='test',
      metric_list=['acc'],evaluation_version='v2.0',description='Local multilevel '+category+' fixtures, graded within EvalScope.'))(type('Fixture_'+category.replace('-','_'),(FixtureAdapter,),{}))

def start_image_server():
    global PROCESS
    host=CONTEXT['image_host']
    try:m.api(host,'/system_stats',timeout=1)
    except (OSError,RuntimeError):pass
    else:raise RuntimeError('Image server port already occupied; refusing unmanaged runtime')
    isolation.stop_others(m.api,CONTEXT['host'])
    root=Path(CONTEXT['comfyui']);output=Path(CONTEXT['work_dir'])/'images';output.mkdir(exist_ok=True)
    log=(Path(CONTEXT['work_dir'])/'comfyui.log').open('w')
    command=[CONTEXT['comfy_python'],str(root/'main.py'),'--listen','127.0.0.1','--port',host.rsplit(':',1)[1],
      '--disable-auto-launch','--disable-all-custom-nodes','--lowvram','--output-directory',str(output)]
    if CONTEXT.get('comfy_model_paths'):command+=['--extra-model-paths-config',CONTEXT['comfy_model_paths']]
    PROCESS=subprocess.Popen(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
    log.close();deadline=time.monotonic()+120
    while True:
        if PROCESS.poll() is not None:raise RuntimeError('ComfyUI exited; inspect worker log')
        try:m.api(host,'/system_stats',timeout=1);return
        except (OSError,RuntimeError):
            if time.monotonic()>deadline:raise RuntimeError('ComfyUI startup timeout')
            time.sleep(1)

def stop_image_server():
    if PROCESS and PROCESS.poll() is None:
        PROCESS.terminate()
        try:PROCESS.wait(timeout=30)
        except subprocess.TimeoutExpired:PROCESS.kill();PROCESS.wait()

@register_model_api('custom')
class FixtureTransport(ModelAPI):
    def generate(self,input,tools,tool_choice,config):
        task_id=input[-1].text
        if CONTEXT.get('image'):
            task=next(t for t in images.TASKS if t['id']==task_id)
            before=isolation.stop_others(m.api,CONTEXT['host']);started=time.monotonic()
            result={'model':self.model_name,'task':task_id,'level':task['level'],'kind':'image-generation','category':'image-generation'}
            try:
                host=CONTEXT['image_host'];graph=images.workflow(self.model_name,task['prompt'],42)
                prompt_id=m.api(host,'/prompt',{'prompt':graph})['prompt_id'];deadline=time.monotonic()+600
                while True:
                    history=m.api(host,'/history/'+prompt_id)
                    if prompt_id in history:break
                    if time.monotonic()>deadline:raise RuntimeError('Image generation timeout')
                    time.sleep(1)
                output=history[prompt_id]['outputs']['9']['images'][0]
                with urllib.request.urlopen(host+'/view?'+urllib.parse.urlencode(output),timeout=30) as response:content=response.read(20_000_001)
                if len(content)>20_000_000:raise RuntimeError('Image exceeds size limit')
                result.update(image_b64=base64.b64encode(content).decode(),workflow=graph)
            except (OSError,ValueError,RuntimeError,KeyError) as error:result['error']=str(error)
            after=isolation.loaded(m.api,CONTEXT['host']);verified=not after
            result.update(seconds=time.monotonic()-started,isolation={'before':before,'after':after,'verified':verified})
        else:
            task=next(t for t in m.suite() if t['id']==task_id)
            before=isolation.stop_others(m.api,CONTEXT['host'],keep=self.model_name)
            result=m.evaluate(CONTEXT['host'],CONTEXT['model_record'],task,{**CONTEXT['transport_config'],'inference_only':True})
            after=isolation.loaded(m.api,CONTEXT['host']);verified=all(n==self.model_name for n in after)
            result['isolation']={'before':before,'after':after,'verified':verified}
        if not verified:raise RuntimeError('Isolation violated in native EvalScope transport')
        # Transport returns evidence only. EvalScope's metric stage assigns the score.
        assert 'points' not in result
        return ModelOutput.from_content(model=self.model_name,content=json.dumps(result))
