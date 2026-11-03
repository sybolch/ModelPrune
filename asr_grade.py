"""Optional CPU-only speech evaluator. Uses an existing local Whisper snapshot."""
import json,sys
from faster_whisper import WhisperModel
model=WhisperModel(sys.argv[1],device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
segments,_=model.transcribe(sys.argv[2],beam_size=5,language='en',vad_filter=False)
print(json.dumps({'transcript':' '.join(s.text.strip() for s in segments)}))
