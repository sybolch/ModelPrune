"""Deterministic multimodal fixtures and skill-specific Ollama request adapters."""
import base64
import hashlib
import json
from pathlib import Path
import struct
import zlib

ROOT=Path(__file__).resolve().parent
ICONS={'completion':'✍','decision':'⚖','vision':'👁','audio':'🎧','tools':'🔧','thinking':'🧠','speech':'🔊','coding':'💻'}


def png_scene(level):
    width,height=360,240
    pixels=bytearray([248,248,248])*(width*height)
    def rect(x,y,w,h,color):
        for yy in range(y,y+h):
            for xx in range(x,x+w):
                i=(yy*width+xx)*3;pixels[i:i+3]=bytes(color)
    red=(220,25,35);blue=(20,70,225);green=(20,170,65)
    if level==1: rect(100,50,160,140,red)
    if level==2:
        rect(25,40,65,65,blue);rect(135,40,65,65,blue);rect(245,40,65,65,red)
    if level==3:
        rect(25,140,60,60,green);rect(145,140,60,60,blue);rect(265,140,60,60,red)
        rect(145,25,60,60,red)
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def tasks():
    result=[]
    for level,(prompt,options,answer) in enumerate([
        ('What color is the large square?',{'red':'Red','blue':'Blue','green':'Green'},'red'),
        ('How many blue squares are visible?',{'one':'One','two':'Two','three':'Three'},'two'),
        ('Which color is directly below the top red square?',{'red':'Red','blue':'Blue','green':'Green'},'blue')],1):
        image=png_scene(level)
        result.append(dict(id=f'vision-{level}',level=level,category='visual-perception',kind='vision',skill='vision',
            prompt=prompt,state='Answer using the attached image.',options=options,expected=answer,
            image_b64=base64.b64encode(image).decode(),asset_sha256=hashlib.sha256(image).hexdigest()))
    for level,(prompt,expected) in enumerate([
        ('What color is the lantern in the recording? Return JSON {"color":string}.',{'color':'purple'}),
        ('Extract the order from the recording. Return JSON {"count":integer,"color":string,"person":string}.',{'count':7,'color':'blue','person':'Nora'}),
        ('Extract the destination, departure time and final platform from the recording. Return JSON {"destination":string,"time":string in HH:MM,"platform":integer}.',{'destination':'Bristol','time':'09:30','platform':6})],1):
        asset=f'audio-{level}.wav'
        content=(ROOT/'fixtures'/asset).read_bytes()
        clip=json.loads((ROOT/'fixtures/audio-manifest.json').read_text()).get('clips',[])[level-1]
        prompt=clip.get('prompt',prompt);expected=clip.get('expected',expected)
        result.append(dict(id=f'audio-{level}',level=level,category='speech-understanding',kind='audio',skill='audio',
            prompt=prompt,expected=expected,asset=asset,voice=json.loads((ROOT/'fixtures/audio-manifest.json').read_text()).get('task_voice','Piper en_US-lessac-high (neural, relaxed pace)'),asset_sha256=hashlib.sha256(content).hexdigest()))
    specifications=[
        ('Get the weather in Budapest. Use the provided tool.', 'get_weather',{'city':'Budapest'},
         {'city':{'type':'string'}}, ['city']),
        ('Convert 25 degrees Celsius to Fahrenheit using the provided tool.', 'convert_temperature',{'value':25,'from_unit':'celsius','to_unit':'fahrenheit'},
         {'value':{'type':'number'},'from_unit':{'type':'string'},'to_unit':{'type':'string'}}, ['value','from_unit','to_unit']),
        ('Search inventory for blue mugs, maximum price 12, available items only. Use the provided tool.', 'search_inventory',{'query':'blue mugs','max_price':12,'in_stock':True},
         {'query':{'type':'string'},'max_price':{'type':'number'},'in_stock':{'type':'boolean'}}, ['query','max_price','in_stock'])]
    for level,(prompt,name,arguments,properties,required) in enumerate(specifications,1):
        tool={'type':'function','function':{'name':name,'description':prompt,
              'parameters':{'type':'object','properties':properties,'required':required}}}
        result.append(dict(id=f'tools-{level}',level=level,category='tool-selection',kind='tools',skill='tools',
                           prompt=prompt,tools=[tool],expected={'name':name,'arguments':arguments}))
    for level,(prompt,expected) in enumerate([
        ('A box contains 5 red and 7 blue balls. Two red balls are removed. How many balls remain? Return JSON {"answer":integer}.',{'answer':10}),
        ('Find the smallest positive integer x such that x modulo 3 is 2 and x modulo 5 is 4. Return JSON {"answer":integer}.',{'answer':14}),
        ('Exactly one of A, B, C is true. A says B is false. B says C is true. C says A is false. Find which statement is true. Return JSON {"answer":"A", "B", or "C"}.',{'answer':'A'})],1):
        result.append(dict(id=f'thinking-{level}',level=level,category='deliberate-reasoning',kind='thinking',skill='thinking',prompt=prompt,expected=expected))
    for level,text in enumerate(['The lantern is purple.','Order seven blue mugs for Nora.','The train to Bristol leaves at nine thirty. The platform changed from four to six.'],1):
        result.append(dict(id=f'speech-{level}',level=level,category='speech-synthesis',kind='speech',skill='speech',prompt=text,expected={'intelligible':True}))
    return result


def parse_json(content,response):
    try: return json.loads(content)
    except (ValueError,TypeError) as error:
        if response.get('done_reason')=='length' or any(c.get('finish_reason')=='length' for c in response.get('choices',[])):
            error=ValueError('Output token budget exhausted before a valid JSON answer')
        error.response=response
        raise error


def tool_answer(response):
    calls=response['message'].get('tool_calls',[])
    if len(calls)!=1: return None
    function=calls[0]['function']
    arguments=function.get('arguments',{})
    if isinstance(arguments,str): arguments=parse_json(arguments,response)
    # Ollama may add a transport index inside function; it is not a model argument.
    return {'name':function['name'],'arguments':arguments}


def canonical_wav(content):
    """Finalize streaming RIFF lengths without changing PCM samples."""
    import io,wave
    with wave.open(io.BytesIO(content)) as source:
        params=source.getparams();frames=source.readframes(20_000_000)
    output=io.BytesIO()
    with wave.open(output,'wb') as target:
        target.setparams(params._replace(nframes=0));target.writeframes(frames)
    return output.getvalue()


def evaluate(api,host,model,task,config):
    """Returns response, normalized answer, extra grade conditions and endpoint."""
    kind=task['kind']
    options={'temperature':0,'seed':config['seed'],'num_ctx':config['context'],
             'num_predict':config.get('thinking_tokens',2048) if kind=='thinking' else config['tokens']}
    base={'model':model['name'],'stream':False,'keep_alive':'5m','options':options}
    if 'thinking' in model['capabilities']: base['think']=kind=='thinking'
    if kind=='vision' and 'decision' in model['capabilities']:
        payload={'model':model['name'],'state':task['state'],'images':[task['image_b64']],
                 'questions':{'answer':{'type':'choice','instructions':task['prompt'],'criteria':task['options']}}}
        response=api(host,'/v1/systemone',payload,config['timeout'])
        return response,response['answers']['answer']['choice'],{},'/v1/systemone'
    if kind=='tools':
        base.update(messages=[{'role':'user','content':task['prompt']}],tools=task['tools'])
        response=api(host,'/api/chat',base,config['timeout'])
        answer=tool_answer(response)
        return response,answer,{'truncated':response.get('done_reason')=='length'},'/api/chat'
    if kind=='speech':
        import io, wave, time, subprocess, tempfile, urllib.request, re
        if not config.get('asr_python') or not config.get('asr_model'):
            raise RuntimeError('Speech grading requires --asr-python and --asr-model (existing local Whisper weights)')
        started=time.monotonic()
        req=urllib.request.Request(host+'/v1/audio/speech',data=json.dumps({'model':model['name'],'input':task['prompt'],'response_format':'wav'}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=config['timeout']) as response: content=response.read(20_000_001)
        if len(content)>20_000_000:raise ValueError('Speech response exceeds 20 MB')
        elapsed=time.monotonic()-started
        content=canonical_wav(content)
        with wave.open(io.BytesIO(content)) as wav:
            duration=len(wav.readframes(20_000_000))/(wav.getframerate()*wav.getnchannels()*wav.getsampwidth())
            if not 0.1<duration<120:raise ValueError('Invalid speech duration')
        import isolation
        isolation.stop_others(api,host)
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            f.write(content);f.flush()
            check=subprocess.run([config['asr_python'],str(ROOT/'asr_grade.py'),config['asr_model'],f.name],capture_output=True,text=True,timeout=120,check=True)
        transcript=json.loads(check.stdout)['transcript']
        numbers={'zero':'0','one':'1','two':'2','three':'3','four':'4','five':'5','six':'6','seven':'7','eight':'8','nine':'9','ten':'10','thirty':'30'}
        words=lambda text:[numbers.get(word,word) for word in re.findall(r"[a-z]+|[0-9]+",text.lower())]
        # Ignore punctuation/case only; retain omitted or changed words as failures.
        matched=words(transcript)==words(task['prompt'])
        return {'transcript':transcript,'duration_seconds':duration}, {'intelligible':matched}, {'inference_seconds':elapsed,'generated_audio_b64':base64.b64encode(content).decode(),'speech_grader':'Whisper tiny.en CPU, exact normalized transcript'}, '/v1/audio/speech'
    if kind=='audio':
        content=(ROOT/'fixtures'/task['asset']).read_bytes()
        if hashlib.sha256(content).hexdigest()!=task['asset_sha256']: raise ValueError('Audio fixture checksum changed')
        payload={'model':model['name'],'stream':False,'temperature':0,'seed':config['seed'],
                 'max_tokens':config['tokens'],'response_format':{'type':'json_object'},
                 'messages':[{'role':'user','content':[{'type':'text','text':task['prompt']},
                    {'type':'input_audio','input_audio':{'data':base64.b64encode(content).decode(),'format':'wav'}}]}]}
        if 'thinking' in model['capabilities']: payload['reasoning_effort']='none'
        response=api(host,'/v1/chat/completions',payload,config['timeout'])
        choice=response['choices'][0]
        return response,parse_json(choice['message']['content'],response),{'truncated':choice.get('finish_reason')=='length'},'/v1/chat/completions'
    prompt=task['prompt']
    if kind=='vision': prompt+='\nOptions: '+json.dumps(task['options'])+'\nReturn JSON {"answer":"option key"}.'
    message={'role':'user','content':prompt}
    if kind=='vision': message['images']=[task['image_b64']]
    base.update(messages=[message],format='json')
    response=api(host,'/api/chat',base,config['timeout'])
    answer=parse_json(response.get('message',{}).get('content',''),response)
    if kind=='vision': answer=answer['answer']
    extra={'truncated':response.get('done_reason')=='length'}
    if kind=='thinking': extra['thinking_present']=bool(response.get('message',{}).get('thinking','').strip())
    return response,answer,extra,'/api/chat'
