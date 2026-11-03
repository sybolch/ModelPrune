import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import modelprune as m

class ScoringTests(unittest.TestCase):
    def test_strict_json_types(self):
        self.assertFalse(m.equal({'x':True},{'x':1}))
        self.assertFalse(m.equal({'x':1,'extra':2},{'x':1}))
        self.assertTrue(m.equal({'x':56.30000001},{'x':56.3}))
        self.assertFalse(m.equal([1,2],[2,1]))
    def test_suite_ids_and_levels(self):
        tasks=m.suite()
        self.assertEqual(len(tasks),36)
        self.assertEqual(len({t['id'] for t in tasks}),36)
        for kind in ['decision','generation','vision','audio','tools','thinking']:
            self.assertEqual({t['level'] for t in tasks if t['kind']==kind},{1,2,3})
    def test_logic_answer_by_enumeration(self):
        import itertools
        valid=[(a,b,c) for a,b,c in itertools.product([False,True],repeat=3)
               if sum([a,b,c])==1 and a==(not b) and b==c and c==(not a)]
        self.assertEqual(valid,[(True,False,False)])
    def test_native_decision(self):
        model={'name':'test','capabilities':['decision']}
        with patch.object(m,'api',return_value={'answers':{'answer':{'choice':'billing'}}}) as call:
            r=m.evaluate('http://localhost',model,m.suite()[0],{'timeout':1})
        self.assertEqual(r['points'],1)
        self.assertEqual(call.call_args.args[1],'/v1/systemone')
    def test_generation_failure_and_truncation(self):
        model={'name':'test','capabilities':['completion']}
        task=m.suite()[9]
        config=dict(timeout=1,seed=42,tokens=256,context=4096)
        for response in [{'message':{'content':'invalid'}},{'message':{'content':'{"answer":102}'},'done_reason':'length'}]:
            with patch.object(m,'api',return_value=response):
                self.assertEqual(m.evaluate('',model,task,config)['points'],0)
        with patch.object(m,'api',side_effect=TimeoutError('timeout')):
            self.assertIn('error',m.evaluate('',model,task,config))
    def test_applicability(self):
        self.assertFalse(m.applicable({'capabilities':['decision']},m.suite()[9]))
        self.assertTrue(m.applicable({'capabilities':['completion'],'remote':True},m.suite()[0]))

class RecommendationTests(unittest.TestCase):
    def setUp(self):
        task=m.suite()[0]
        self.data=dict(created='test',ollama_version='test',suite_hash='abc',host='localhost',hardware={},
          config={'repeats':1},tasks=[task],models=[
            dict(name='large',size=2e9,capabilities=['decision'],details={}),
            dict(name='small',size=1e9,capabilities=['decision'],details={})],results=[
            dict(model=n,task=task['id'],repeat=0,points=1,seconds=0.2 if n=='large' else 0.1,level=1,category='routing',kind='decision') for n in ['large','small']])
    def decisions(self): return m.recommendations(self.data,m.aggregate(self.data))
    def test_remote_replacement_is_a_connectivity_tradeoff(self):
        self.data['models'][1]['remote']=True
        self.data['results'][1]['seconds']=.01
        self.data['results'][0]['points']=0
        decision=self.decisions()[0]
        self.assertEqual(decision['replacement'],'small')
        self.assertIn('remote execution tradeoff',decision['status'])
        self.assertIn('offline',decision['reason'])
    def test_remote_speed_does_not_change_local_peer_speed_score(self):
        self.data['models'][1]['remote']=True
        rows=m.aggregate(self.data)
        self.assertEqual(rows[0]['speed_score'],100)
        self.assertEqual(rows[1]['speed_score'],100)
    def test_dominance(self): self.assertEqual(self.decisions()[0]['replacement'],'small')
    def test_error_blocks_recommendation(self):
        self.data['results'][1]['error']='failed'
        self.assertIsNone(self.decisions()[0]['replacement'])
    def test_special_capability_protected(self):
        self.data['models'][0]['capabilities'].append('vision')
        self.assertIsNone(self.decisions()[0]['replacement'])
    def test_better_model_with_more_skills_can_replace(self):
        self.data['models'][1]['capabilities'].append('vision')
        self.add_skill_evidence(['vision'])
        rows=m.aggregate(self.data)
        rows[0]['rating']=90;rows[1]['rating']=100
        decision=m.recommendations(self.data,rows)[0]
        self.assertEqual(decision['replacement'],'small')
        self.assertEqual(decision['same_skill_peers'],[])
        self.assertEqual(decision['skill_differences'][0]['only_other_model'],['vision'])
    def test_better_model_with_fewer_skills_cannot_replace(self):
        self.data['models'][0]['capabilities'].append('vision')
        self.add_skill_evidence(['vision'])
        rows=m.aggregate(self.data)
        rows[0]['rating']=80;rows[1]['rating']=95
        self.assertIsNone(m.recommendations(self.data,rows)[0]['replacement'])
    def test_worse_model_with_more_skills_cannot_replace(self):
        self.data['models'][1]['capabilities'].append('vision')
        self.add_skill_evidence(['vision'])
        rows=m.aggregate(self.data)
        rows[0]['rating']=95;rows[1]['rating']=80
        self.assertIsNone(m.recommendations(self.data,rows)[0]['replacement'])
    def test_equal_ratings_do_not_establish_redundancy(self):
        rows=m.aggregate(self.data)
        for row in rows: row['rating']=90
        self.assertTrue(all(r['replacement'] is None for r in m.recommendations(self.data,rows)))
    def test_resource_cost_cannot_allow_worse_rating_to_win(self):
        rows=m.aggregate(self.data)
        rows[0]['rating']=95;rows[1]['rating']=80
        self.assertIsNone(m.recommendations(self.data,rows)[0]['replacement'])
    def add_skill_evidence(self,skills):
        for task in m.suite():
            if task.get('skill') not in skills: continue
            self.data['tasks'].append(task)
            for model in self.data['models']:
                if not m.applicable(model,task): continue
                self.data['results'].append(dict(model=model['name'],task=task['id'],repeat=0,points=task['level'],seconds=0.2 if model['name']=='large' else 0.1,level=task['level'],category=task['category'],kind=task['kind']))
    def test_identical_multimodal_skills_allow_comparison(self):
        for model in self.data['models']: model['capabilities']+=['vision','audio']
        self.add_skill_evidence(['vision','audio'])
        self.assertEqual(self.decisions()[0]['replacement'],'small')
    def test_skill_order_does_not_matter(self):
        self.data['models'][0]['capabilities']=['vision','decision']
        self.data['models'][1]['capabilities']=['decision','vision']
        self.add_skill_evidence(['vision'])
        self.assertEqual(self.decisions()[0]['replacement'],'small')
    def test_larger_context_protected(self):
        self.data['models'][0]['context']=32768
        self.data['models'][1]['context']=4096
        self.assertEqual(self.decisions()[0]['status'],'Workload overlap / context tradeoff')
        self.assertIn('32768',self.decisions()[0]['reason'])
    def test_incomplete_blocks_recommendation(self):
        self.data['config']['repeats']=2
        self.assertIsNone(self.decisions()[0]['replacement'])
    def test_worse_task_not_hidden_by_total(self):
        self.data['results'][1]['points']=0
        self.assertIsNone(self.decisions()[0]['replacement'])
    def test_html_escapes_answers(self):
        self.data['results'][0]['answer']='<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as folder:
            m.report(self.data,Path(folder))
            page=(Path(folder)/'report.html').read_text()
            self.assertNotIn('<script>alert(1)</script>',page)
            self.assertIn('&lt;script&gt;',page)
            self.assertTrue((Path(folder)/'comparison.csv').exists())


class AllSkillTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(timeout=1,seed=42,tokens=256,context=4096,thinking_tokens=512)
    def test_vision_decision_includes_image(self):
        task=next(t for t in m.suite() if t['id']=='vision-1')
        with patch.object(m,'api',return_value={'answers':{'answer':{'choice':'red'}}}) as call:
            result=m.evaluate('',{'name':'x','capabilities':['decision','vision']},task,self.config)
        self.assertTrue(call.call_args.args[2]['images'])
        self.assertEqual(result['points'],1)
    def test_audio_payload_is_real_wav(self):
        import base64
        task=next(t for t in m.suite() if t['id']=='audio-1')
        response={'choices':[{'message':{'content':'{"color":"Purple"}'},'finish_reason':'stop'}]}
        with patch.object(m,'api',return_value=response) as call:
            result=m.evaluate('',{'name':'x','capabilities':['audio','completion']},task,self.config)
        content=call.call_args.args[2]['messages'][0]['content'][1]['input_audio']['data']
        self.assertEqual(base64.b64decode(content)[:4],b'RIFF')
        self.assertEqual(result['points'],1)
    def test_tool_transport_index_ignored(self):
        task=next(t for t in m.suite() if t['id']=='tools-1')
        response={'message':{'tool_calls':[{'function':{'index':0,**task['expected']}}]}}
        with patch.object(m,'api',return_value=response) as call:
            result=m.evaluate('',{'name':'x','capabilities':['tools','completion']},task,self.config)
        self.assertEqual(call.call_args.args[1],'/api/chat')
        self.assertEqual(result['points'],1)
    def test_tool_names_remain_case_sensitive(self):
        self.assertFalse(m.skill_equal({'name':'GET_WEATHER','arguments':{'city':'Budapest'}},
            {'name':'get_weather','arguments':{'city':'Budapest'}},'tools'))
    def test_thinking_requires_output_and_answer(self):
        task=next(t for t in m.suite() if t['id']=='thinking-1')
        for thinking,points in [('',0),('Reasoning trace',1)]:
            response={'message':{'content':'{"answer":10}','thinking':thinking}}
            with patch.object(m,'api',return_value=response) as call:
                result=m.evaluate('',{'name':'x','capabilities':['thinking','completion']},task,self.config)
            self.assertEqual(call.call_args.args[1],'/api/chat')
            self.assertTrue(call.call_args.args[2]['think'])
            self.assertEqual(call.call_args.args[2]['options']['num_predict'],512)
            self.assertEqual(result['points'],points)
    def test_malformed_skill_response_is_preserved(self):
        task=next(t for t in m.suite() if t['id']=='thinking-1')
        response={'message':{'content':'bad json','thinking':'trace'}}
        with patch.object(m,'api',return_value=response):
            result=m.evaluate('',{'name':'x','capabilities':['thinking','completion']},task,self.config)
        self.assertIn('error',result)
        self.assertEqual(result['response'],response)
    def test_report_has_seven_columns_and_icon_accessibility(self):
        fixture=RecommendationTests();fixture.setUp()
        import report_ui
        rows=m.aggregate(fixture.data)
        page=report_ui.render(fixture.data,rows,m.recommendations(fixture.data,rows))
        header=page.split('<table id="comparison-decision">',1)[1].split('</thead>',1)[0]
        self.assertEqual(header.count('<th>'),7)
        self.assertIn('aria-label="decision:',page)
    def test_untested_skill_blocks_recommendation(self):
        fixture=RecommendationTests();fixture.setUp()
        for model in fixture.data['models']: model['capabilities'].append('unknown-skill')
        self.assertIsNone(fixture.decisions()[0]['replacement'])
        self.assertEqual(m.aggregate(fixture.data)[0]['skill_coverage'],0.5)


class IsolationTests(unittest.TestCase):
    def test_stops_all_loaded_models_before_model(self):
        import isolation
        calls=[]
        def fake(host,path,payload=None,timeout=15):
            calls.append((path,payload))
            if path=='/api/ps':
                return {'models':[{'name':'other:1'},{'name':'target:1'}]} if len(calls)==1 else {'models':[]}
            return {'done':True}
        with patch.object(isolation.time,'sleep'):
            result=isolation.stop_others(fake,'host')
        self.assertEqual(result['remaining'],[])
        self.assertEqual(set(result['stopped']),{'other:1','target:1'})
        self.assertTrue(all(payload['keep_alive']==0 for path,payload in calls if path!='/api/ps'))
    def test_keeps_only_active_model_between_tasks(self):
        import isolation
        responses=[{'models':[{'name':'target:1'},{'name':'other:1'}]}, {'done':True}, {'models':[{'name':'target:1'}]}]
        fake=unittest.mock.Mock(side_effect=responses)
        with patch.object(isolation.time,'sleep'):
            result=isolation.stop_others(fake,'host',keep='target:1')
        self.assertEqual(result['stopped'],['other:1'])
        self.assertEqual(result['remaining'],['target:1'])
    def test_bad_ps_fails_closed(self):
        import isolation
        for response in [{},{'models':[{}]}]:
            with self.assertRaises(RuntimeError): isolation.loaded(lambda *a,**k:response,'host')
    def test_isolation_violation_blocks_replacement(self):
        fixture=RecommendationTests();fixture.setUp()
        fixture.data['results'][1]['isolation']={'verified':False}
        self.assertIsNone(fixture.decisions()[0]['replacement'])
    def test_unload_failure_not_swallowed(self):
        import isolation
        fake=unittest.mock.Mock(side_effect=[{'models':[{'name':'other'}]},RuntimeError('cannot unload')])
        with self.assertRaisesRegex(RuntimeError,'cannot unload'): isolation.stop_others(fake,'host')
    def test_resume_rejects_legacy_protocol_before_contacting_ollama(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            saved=Path(directory)/'run.json';saved.write_text('{"protocol":"legacy"}')
            result=subprocess.run([sys.executable,str(Path(m.__file__)),'run','--resume',str(saved)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Benchmark protocol changed',result.stderr)
    def test_render_shows_total_moe_parameters(self):
        fixture=RecommendationTests();fixture.setUp()
        fixture.data['models'][0].update(architecture_type='MoE',expert_count=256,experts_used=8,details={'parameter_size':'35.5B'})
        import report_ui
        rows=m.aggregate(fixture.data)
        page=report_ui.render(fixture.data,rows,m.recommendations(fixture.data,rows))
        self.assertIn('35.5B total',page)
        self.assertIn('MoE · 8/256 experts',page)
    def test_moe_metadata(self):
        responses=[{'models':[{'name':'moe','size':1}]},{'capabilities':['completion'],
            'model_info':{'general.architecture':'qwen35moe','qwen35moe.expert_count':256,'qwen35moe.expert_used_count':8}}]
        with patch.object(m,'api',side_effect=responses):
            model=m.inventory('host')[0]
        self.assertEqual(model['architecture_type'],'MoE')
        self.assertEqual(model['expert_count'],256)
        self.assertEqual(model['experts_used'],8)


class AudioFixtureTests(unittest.TestCase):
    def test_neural_audio_matches_manifest_and_has_headroom(self):
        import wave,array,hashlib
        import skill_tasks
        manifest=json.loads((skill_tasks.ROOT/'fixtures/audio-manifest.json').read_text())
        self.assertIn('Piper',manifest['voice'])
        for clip in manifest['clips']:
            path=skill_tasks.ROOT/'fixtures'/clip['file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),clip['sha256'])
            with wave.open(str(path),'rb') as wav:
                self.assertEqual((wav.getnchannels(),wav.getsampwidth(),wav.getframerate()),(1,2,22050))
                samples=array.array('h',wav.readframes(wav.getnframes()))
            self.assertLessEqual(max(abs(sample) for sample in samples),int(32768*.86))
            self.assertGreater(max(abs(sample) for sample in samples),int(32768*.8))
            self.assertTrue(all(sample==0 for sample in samples[:int(22050*.2)]))
            self.assertTrue(all(sample==0 for sample in samples[-int(22050*.3):]))
    def test_historical_report_never_plays_changed_audio(self):
        fixture=RecommendationTests();fixture.setUp()
        task=next(t for t in m.suite() if t['id']=='audio-1')
        task['asset_sha256']='old checksum'
        fixture.data['tasks']=[task]
        fixture.data['models'][0]['capabilities']=['completion','audio']
        fixture.data['results']=[dict(model='large',task=task['id'],repeat=0,points=1,seconds=.1,level=1,kind='audio',category='speech-understanding')]
        import report_ui
        rows=m.aggregate(fixture.data)
        page=report_ui.render(fixture.data,rows,m.recommendations(fixture.data,rows))
        self.assertIn('Original audio fixture unavailable: checksum mismatch',page)
        self.assertNotIn('<audio controls',page)

if __name__=='__main__': unittest.main()
