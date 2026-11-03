"""Run registered ModelPrune datasets inside the installed EvalScope engine."""
import json,sys
from pathlib import Path
from evalscope import TaskConfig,run_task
import evalscope_native as native
import isolation,modelprune as m

config=json.loads(Path(sys.argv[1]).read_text());native.CONTEXT.update(config)
try:
    isolation.stop_others(m.api,config['host'])
    if config.get('image'):native.start_image_server()
    run_task(TaskConfig(model=config['model_record']['name'],eval_type='custom',datasets=config['datasets'],
      generation_config={'temperature':0,'max_tokens':1024,'timeout':180,'retries':1,'stream':False},
      eval_batch_size=1,work_dir=config['work_dir'],no_timestamp=True,seed=42))
finally:
    native.stop_image_server();isolation.stop_others(m.api,config['host'])
