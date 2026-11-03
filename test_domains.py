import io,unittest
from unittest.mock import patch
import domain_sections as d
import image_benchmark as images
import modelprune as m

class DomainTests(unittest.TestCase):
    def test_coding_scores_exclude_other_tasks(self):
        tasks=[t for t in m.suite() if t['id'] in ('code-1','debug-2','math-1')]
        data={'models':[{'name':'model','capabilities':['completion']}],'config':{'repeats':1},'tasks':tasks,
          'results':[{'model':'model','task':'code-1','points':1,'seconds':1}, {'model':'model','task':'debug-2','points':0,'seconds':3}, {'model':'model','task':'math-1','points':1,'seconds':.1}]}
        row=d.comparisons(data,'coding')[0]
        self.assertEqual(row['expected'],2);self.assertEqual(row['passed'],1)
        self.assertAlmostEqual(row['quality'],100/3)
        self.assertEqual(row['seconds'],2)
    def test_debugging_equivalent_syntax_and_wrong_identifier(self):
        task=next(t for t in m.suite() if t['id']=='debug-3')
        self.assertTrue(m.task_equal({'aggregate':'count( o.id )','join':'left'},task))
        self.assertFalse(m.task_equal({'aggregate':'COUNT(o.order_id)','join':'LEFT JOIN'},task))
        task=next(t for t in m.suite() if t['id']=='debug-1')
        self.assertTrue(m.task_equal({'operator':'!=','value':1},task))
        self.assertFalse(m.task_equal({'operator':'==','value':1},task))
    def test_speech_tests_require_speech_capability(self):
        task=next(t for t in m.suite() if t['id']=='speech-1')
        self.assertTrue(m.applicable({'capabilities':['speech']},task))
        self.assertFalse(m.applicable({'capabilities':['audio','completion']},task))
    def test_domain_headings_and_empty_image_state(self):
        import report_ui
        data={'created':'test','config':{'repeats':1},'host':'local','hardware':{},'models':[],'tasks':m.suite(),'results':[]}
        page=report_ui.render(data,[],[])
        for name in d.DOMAINS:self.assertIn('id="'+name+'"',page)
        self.assertIn('Image generation has not been benchmarked',page)
        self.assertIn('Speech output',page)
    def test_image_layout_grade_rejects_reversal(self):
        try:from PIL import Image,ImageDraw
        except ImportError:self.skipTest('Pillow optional image adapter dependency')
        def fixture(reverse):
            image=Image.new('RGB',(256,256),'white');draw=ImageDraw.Draw(image)
            draw.rectangle((20,70,100,160),fill='blue' if reverse else 'red')
            draw.rectangle((150,70,230,160),fill='red' if reverse else 'blue')
            data=io.BytesIO();image.save(data,format='PNG');return data.getvalue()
        self.assertTrue(images.grade(fixture(False),images.TASKS[2])[0])
        self.assertFalse(images.grade(fixture(True),images.TASKS[2])[0])
    def test_speech_streaming_wav_uses_actual_pcm_length(self):
        import wave,struct,types,skill_tasks
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*8000)
        content=bytearray(buffer.getvalue());content[4:8]=struct.pack('<I',0xffffffff);content[40:44]=struct.pack('<I',0xffffffff)
        task=next(t for t in m.suite() if t['id']=='speech-2')
        cfg={'seed':42,'context':4096,'tokens':256,'timeout':1,'asr_python':'python','asr_model':'snapshot'}
        with patch('urllib.request.urlopen',return_value=io.BytesIO(content)), patch('isolation.stop_others'), patch('subprocess.run',return_value=types.SimpleNamespace(stdout='{"transcript":"Order 7 blue mugs for Nora."}')):
            response,answer,extra,endpoint=skill_tasks.evaluate(None,'http://localhost',{'name':'tts','capabilities':['speech']},task,cfg)
        self.assertEqual(response['duration_seconds'],.5);self.assertTrue(answer['intelligible'])
        self.assertEqual(endpoint,'/v1/audio/speech');self.assertIn('generated_audio_b64',extra)
    def test_speech_missing_evaluator_is_explicit_failure(self):
        task=next(t for t in m.suite() if t['id']=='speech-1')
        with patch('modelprune.api') as api:
            result=m.evaluate('http://localhost',{'name':'tts','capabilities':['speech']},task,{'seed':42,'context':4096,'tokens':256,'timeout':1})
        self.assertIn('--asr-python',result['error']);api.assert_not_called()

if __name__=='__main__':unittest.main()
