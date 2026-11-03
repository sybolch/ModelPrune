import json,re,unittest
import report_insights as i

class InsightTests(unittest.TestCase):
    def test_small_sample_uncertainty_is_not_false_precision(self):
        lo,hi=i.wilson(1,5)
        self.assertLess(lo,60);self.assertAlmostEqual(hi,100)
        self.assertIsNone(i.wilson(.5,0))
    def test_percentile_interpolates_without_fabricating_samples(self):
        self.assertAlmostEqual(i.percentile([1,2,10],.95),9.2)
        self.assertIsNone(i.percentile([],.95))
    def test_unmeasured_skill_stays_null_and_zero_stays_zero(self):
        rows=[{'model':'model','model_type':'Generative','rating':1,'skill_scores':{
          'vision':{'percent':0,'expected':3,'completed':3},'audio':{'percent':None,'expected':0,'completed':0}}}]
        chart=i.chart_data({'results':[]},rows)[0]
        self.assertEqual(chart['skills']['vision'],0);self.assertIsNone(chart['skills']['audio'])
    def test_chart_json_round_trips_untrusted_names_without_script_breakout(self):
        name='</script><script>alert(1)</script>'
        rows=[{'model':name,'model_type':'Generative','rating':1,'skill_scores':{}}]
        page=i.render({'results':[]},rows)
        payload=re.search('id="radar-data">(.*?)</script>',page).group(1)
        self.assertNotIn('<',payload);self.assertEqual(json.loads(payload)[0]['name'],name)
    def test_only_primary_quality_ratio_is_a_radar_axis(self):
        metric={'identity':{'name':'loss'},'score':.2,'num':5,'semantics':{'direction':'lower_is_better','display_kind':'number'}}
        report={'model':'m','suite':'boolq','data':{'primary_metric_identity':{'name':'loss'},'metrics':[metric],
          'execution_summary':{'incomplete':False,'errored':0,'requested':5,'succeeded':5}}}
        chart=i.chart_data({'engine_reports':[report]},[{'model':'m','model_type':'Decision','skill_scores':{}}])
        self.assertEqual(chart[0]['benchmarks'],{})
        self.assertIsNone(i.benchmark_rows({'engine_reports':[report]})[0]['ci'])

if __name__=='__main__':unittest.main()
