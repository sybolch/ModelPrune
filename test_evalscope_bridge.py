import json,unittest,urllib.request,urllib.error
from unittest.mock import patch
from pathlib import Path
import evalscope_bridge as b

class EvalScopeTests(unittest.TestCase):
    def test_dispatch_does_not_send_decision_models_to_generation_suite(self):
        model={'name':'d','capabilities':['decision','vision']}
        self.assertTrue(b.applicable(model,'boolq'));self.assertFalse(b.applicable(model,'gsm8k'))
        self.assertTrue(b.applicable({**model,'remote':True},'boolq'))
        cmd=b.command('evalscope',model,'boolq','http://localhost:1',Path('/tmp/one'),10)
        config=json.loads(cmd[cmd.index('--generation-config')+1])
        self.assertNotIn('temperature',config);self.assertNotIn('max_tokens',config)
        self.assertEqual(cmd[cmd.index('--eval-type')+1],'systemone_api')
        self.assertEqual(cmd[cmd.index('--eval-batch-size')+1],'1')
    def test_import_primary_zero_score_is_not_missing(self):
        identity={'name':'accuracy','aggregation':'mean','dimensions':{}}
        report={'schema_version':2,'dataset_name':'boolq','primary_metric_identity':identity,
          'metrics':[{'identity':{'name':'loss'},'score':10}, {'identity':identity,'score':0,'num':10,'semantics':{'metric_name':'Accuracy','display_multiplier':100,'display_unit':'%'}}],
          'execution_summary':{'requested':10,'succeeded':10,'errored':0,'incomplete':False}}
        entry={'suite':'boolq','reports':[{'path':'reports/test.json','data':report}]}
        rows=b.summarize(entry);self.assertEqual(rows[0]['display_score'],0);self.assertTrue(rows[0]['complete'])
        report['execution_summary']['errored']=1
        self.assertFalse(b.summarize(entry)[0]['complete'])
        report['schema_version']=1;self.assertEqual(b.summarize(entry),[])
    def test_report_has_one_evalscope_score_system(self):
        import report_ui
        data={'created':'test','models':[],'tasks':[],'results':[],'config':{},'host':'local','hardware':{},'engine':'EvalScope 1.14.1','standard_limit':5}
        page=report_ui.render(data,[],[])
        self.assertIn('Every task score comes from EvalScope reviews',page)
        self.assertIn('EvalScope suites and scoring provenance',page)
        self.assertNotIn('EvalScope standard benchmarks',page)
    def test_proxy_rejects_other_models_before_backend(self):
        with patch('isolation.stop_others') as stop:
            with b.Proxy('http://127.0.0.1:1','allowed') as proxy:
                request=urllib.request.Request(proxy.url+'/v1/chat/completions',data=json.dumps({'model':'other','messages':[]}).encode(),headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,503);error.exception.close()
            stop.assert_not_called();self.assertTrue(proxy.violations);self.assertFalse(proxy.events[0]['verified'])
    def test_proxy_rejects_streaming_before_backend(self):
        with patch('isolation.stop_others') as stop:
            with b.Proxy('http://127.0.0.1:1','allowed') as proxy:
                request=urllib.request.Request(proxy.url+'/v1/chat/completions',data=json.dumps({'model':'allowed','stream':True}).encode())
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
                error.exception.close()
            stop.assert_not_called();self.assertTrue(proxy.violations)

if __name__=='__main__':unittest.main()
