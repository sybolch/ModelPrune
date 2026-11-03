#!/usr/bin/env python3
"""Image fixtures, ComfyUI workflow and metrics for native EvalScope evaluation."""
import io

TASKS=[
 dict(id='image-1',level=1,prompt='Flat vector graphic, one large solid red square centered on a plain white background. Minimal geometric diagram. No text. No gradients.',colors=['red']),
 dict(id='image-2',level=2,prompt='Flat vector graphic on a plain white background. A large solid red square and a large solid blue square, separated with white space. Exactly two shapes. No text. No gradients.',colors=['red','blue']),
 dict(id='image-3',level=3,prompt='Flat vector geometric diagram on plain white background: a solid red square on the LEFT and a solid blue square on the RIGHT. Two separate large squares side by side. No text. No gradients.',colors=['red','blue'],layout='red-left-blue-right')]

def grade(content,task):
    from PIL import Image
    image=Image.open(io.BytesIO(content)).convert('RGB');image.thumbnail((256,256))
    width,height=image.size; positions={'red':[],'blue':[]}; white=0
    for y in range(height):
        for x in range(width):
            r,g,b=image.getpixel((x,y))
            if min(r,g,b)>215:white+=1
            if r>120 and r>g*1.5 and r>b*1.5:positions['red'].append(x/width)
            if b>100 and b>r*1.5 and b>g*1.3:positions['blue'].append(x/width)
    area=width*height
    metrics={'fraction_'+c:len(xs)/area for c,xs in positions.items()}
    metrics['white_fraction']=white/area
    passed=white/area>0.2 and all(.025<len(positions[c])/area<.6 for c in task['colors'])
    if task.get('layout'):
        centers={c:sum(xs)/len(xs) if xs else None for c,xs in positions.items()};metrics['horizontal_centers']=centers
        passed=passed and centers['red'] is not None and centers['blue'] is not None and centers['red']+.15<centers['blue']
    return bool(passed),metrics

def workflow(checkpoint,prompt,seed):
    return {
     '4':{'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':checkpoint}},
     '5':{'class_type':'EmptyLatentImage','inputs':{'width':768,'height':768,'batch_size':1}},
     '6':{'class_type':'CLIPTextEncode','inputs':{'text':prompt,'clip':['4',1]}},
     '7':{'class_type':'CLIPTextEncode','inputs':{'text':'photograph, text, watermark, gradients, blurry','clip':['4',1]}},
     '3':{'class_type':'KSampler','inputs':{'model':['4',0],'positive':['6',0],'negative':['7',0],'latent_image':['5',0],'seed':seed,'steps':20,'cfg':7,'sampler_name':'euler','scheduler':'normal','denoise':1}},
     '8':{'class_type':'VAEDecode','inputs':{'samples':['3',0],'vae':['4',2]}},
     '9':{'class_type':'SaveImage','inputs':{'images':['8',0],'filename_prefix':'ModelPrune'}}}
