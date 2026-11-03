import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import discovery

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_custom_folder_and_inode_deduplication(self):
        model=self.root/'model.onnx';model.write_bytes(b'ONNX weights')
        os.link(model,self.root/'alias.onnx')
        result=discovery.scan(roots=[self.root,self.root])
        self.assertEqual(len(result['models']),1)
        self.assertEqual(result['models'][0]['size'],12)
        self.assertFalse(result['models'][0]['benchmarkable'])
    def test_hf_snapshot_has_one_model_for_multiple_components(self):
        repo=self.root/'models--org--diffusion';snap=repo/'snapshots'/'revision';snap.mkdir(parents=True)
        (snap/'model_index.json').write_text('{"_class_name":"StableDiffusionPipeline"}')
        for folder in ['unet','vae']:
            component=snap/folder;component.mkdir();(component/'model.safetensors').write_bytes(b'weights')
        result=discovery.scan(roots=[self.root])
        self.assertEqual(len(result['models']),1)
        model=result['models'][0]
        self.assertEqual(model['name'],'org/diffusion')
        self.assertEqual(model['weight_files'],2)
        self.assertEqual(model['source'],'Hugging Face')
        self.assertEqual(model['category'],'Image generation / component')
    def test_hf_configuration_only_is_not_installed_weights(self):
        snap=self.root/'models--org--model'/'snapshots'/'revision';snap.mkdir(parents=True)
        (snap/'config.json').write_text('{}')
        self.assertEqual(discovery.scan(roots=[self.root])['models'],[])
    def test_missing_transformer_shard(self):
        (self.root/'config.json').write_text('{"architectures":["LlamaForCausalLM"]}')
        (self.root/'model-00001.safetensors').write_bytes(b'weights')
        (self.root/'model.safetensors.index.json').write_text(json.dumps({'weight_map':{'a':'model-00001.safetensors','b':'model-00002.safetensors'}}))
        model=discovery.scan(roots=[self.root])['models'][0]
        self.assertEqual(model['status'],'Incomplete weights')
        self.assertEqual(model['missing_shards'],['model-00002.safetensors'])
    def test_unrelated_checkpoints_are_separate(self):
        for name in ['first','second']:(self.root/(name+'.safetensors')).write_bytes(b'weights')
        self.assertEqual(len(discovery.scan(roots=[self.root])['models']),2)
    def test_scan_limit_is_explicit(self):
        for name in range(4):(self.root/str(name)).touch()
        result=discovery.scan(roots=[self.root],max_entries=2)
        self.assertTrue(result['limited'])
        self.assertIn('Scan limit reached',result['warnings'][0])
    def test_language_file_pt_is_not_torch_weights(self):
        p=self.root/'messages.pt';p.write_text('Portuguese translation')
        self.assertFalse(discovery.is_weight(p))
        p.write_bytes(b'PK\x03\x04binary tensor container')
        self.assertTrue(discovery.is_weight(p))
    def test_gguf_metadata_is_read_without_weights(self):
        def string(value):
            raw=value.encode();return struct.pack('<Q',len(raw))+raw
        values=[('general.architecture',8,string('qwen35moe')),('qwen35moe.context_length',4,struct.pack('<I',32768)),
                ('qwen35moe.expert_count',4,struct.pack('<I',256))]
        payload=b'GGUF'+struct.pack('<IQQ',3,0,len(values))
        for key,kind,value in values:payload+=string(key)+struct.pack('<I',kind)+value
        p=self.root/'tiny.gguf';p.write_bytes(payload)
        metadata=discovery.gguf_metadata(p)
        self.assertEqual(metadata['general.architecture'],'qwen35moe')
        self.assertEqual(metadata['qwen35moe.expert_count'],256)
        self.assertEqual(discovery.scan(roots=[self.root])['models'][0]['context'],32768)
    def test_offline_ollama_manifest(self):
        models=self.root/'models';manifest=models/'manifests/registry.ollama.ai/library/test/1b'
        manifest.parent.mkdir(parents=True);blob=models/'blobs'/('sha256-'+'a'*64);blob.parent.mkdir();blob.write_bytes(b'GGUF weights')
        manifest.write_text(json.dumps({'layers':[{'mediaType':'application/vnd.ollama.image.model','digest':'sha256:'+'a'*64}]}))
        result=discovery.scan(roots=[self.root])
        self.assertEqual(result['models'][0]['name'],'test:1b')
        self.assertEqual(result['models'][0]['source'],'Ollama')
        self.assertFalse(result['models'][0]['benchmarkable'])
    def test_external_model_selection_explains_missing_adapter(self):
        import modelprune,sys,contextlib,io
        from unittest.mock import patch
        stderr=io.StringIO()
        with patch.object(sys,'argv',['modelprune.py','run','--models','external.gguf']), \
             patch.object(modelprune,'inventory',return_value=[]), \
             patch.object(discovery,'scan',return_value={'models':[{'name':'external.gguf','source':'Model files'}]}), \
             contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):modelprune.main()
        self.assertIn('Found outside Ollama',stderr.getvalue())
        self.assertIn('no benchmark/isolation adapter',stderr.getvalue())
    def test_ollama_metadata_is_kept_without_filesystem_models(self):
        result=discovery.scan([{'name':'test:1b','size':123,'capabilities':['completion']}],roots=[self.root])
        self.assertTrue(result['models'][0]['benchmarkable'])
        self.assertEqual(result['models'][0]['source'],'Ollama')

if __name__=='__main__':unittest.main()
