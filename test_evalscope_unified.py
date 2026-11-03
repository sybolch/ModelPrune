import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import modelprune as m,evalscope_run as unified

class UnifiedTests(unittest.TestCase):
    def test_worker_error_names_the_model_blocking_isolation(self):
        import isolation
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'worker.log').write_text('Traceback\nRuntimeError: Model isolation timed out: ornith-work:32k\n')
            reason=isolation.failure_reason(folder,'generic worker failure')
            self.assertIn('ornith-work:32k',reason);self.assertIn('stop its local inference',reason)
    def test_transport_only_mode_does_not_assign_points(self):
        model={'name':'test','capabilities':['completion']};task=next(t for t in m.suite() if t['id']=='math-1')
        with patch('modelprune.api',return_value={'message':{'content':'{"answer":102}'}}):
            result=m.evaluate('local',model,task,{'inference_only':True,'seed':42,'context':4096,'tokens':256,'timeout':1})
        self.assertEqual(result['answer'],{'answer':102});self.assertNotIn('points',result)
    def test_unified_report_rejects_legacy_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'refuses scores'):
                m.report({'engine':'EvalScope','results':[{'points':1}]},Path(folder))
    def test_review_score_is_authoritative_not_regraded(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reviews/model';path.mkdir(parents=True)
            evidence={'model':'model','task':'math-1','level':1,'answer':{'answer':102},'seconds':1,'isolation':{'verified':True}}
            row={'sample_score':{'score':{'value':{'acc':0},'prediction':json.dumps(evidence)},'generation_index':0}}
            (path/'modelprune_core_default.jsonl').write_text(json.dumps(row)+'\n')
            _,results=unified.import_custom(folder,'model')
            self.assertEqual(results[0]['points'],0)
            self.assertEqual(results[0]['score_engine'],'EvalScope')
    def test_unverified_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reviews/model';path.mkdir(parents=True)
            evidence={'model':'model','task':'math-1','level':1,'seconds':1,'isolation':{'verified':False}}
            (path/'modelprune_core_default.jsonl').write_text(json.dumps({'sample_score':{'score':{'value':{'acc':1},'prediction':json.dumps(evidence)}}})+'\n')
            with self.assertRaisesRegex(RuntimeError,'Unverified'):unified.import_custom(folder,'model')
    def test_standard_primary_metric_is_used_not_looser_secondary(self):
        identity={'name':'prompt_level_strict','aggregation':'mean','dimensions':{}}
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);(base/'reviews/model').mkdir(parents=True);(base/'predictions/model').mkdir(parents=True)
            score={'value':{'prompt_level_strict':0,'inst_level_loose':1},'main_score_name':'prompt_level_strict','extracted_prediction':'response'}
            review={'index':0,'target':'expected','sample_score':{'score':score}}
            (base/'reviews/model/ifeval_default.jsonl').write_text(json.dumps(review)+'\n')
            prediction={'index':0,'messages':[{'content':'prompt'}],'model_output':{'time':1}}
            (base/'predictions/model/ifeval_default.jsonl').write_text(json.dumps(prediction)+'\n')
            report={'schema_version':2,'dataset_name':'ifeval','primary_metric_identity':identity,'metrics':[{'identity':identity,'score':0,'num':1,'semantics':{}}],
                    'execution_summary':{'requested':1,'succeeded':1,'errored':0,'incomplete':False}}
            entry={'suite':'ifeval','model':'model','valid_isolation':True,'requests':[{'verified':True,'seconds':1}],'reports':[{'path':'report.json','data':report}]}
            _,results=unified.import_standard(folder,entry)
            self.assertEqual(results[0]['points'],0);self.assertEqual(results[0]['evalscope_metric'],'prompt_level_strict')

if __name__=='__main__':unittest.main()
