import unittest,copy
import modelprune as m
class InventoryReportTests(unittest.TestCase):
 def test_removed_models_disappear_everywhere_without_losing_evidence(self):
  data={'models':[{'name':'keep','digest':'a'},{'name':'gone','digest':'b'},{'name':'changed','digest':'old'}],
   'results':[{'model':name} for name in ['keep','gone','changed']],
   'discovery':{'models':[{'name':'keep','source':'Ollama','digest':'a'},{'name':'changed','source':'Ollama','digest':'new'}]},
   'engine_reports':[{'model':name} for name in ['keep','gone','changed']],
   'image_benchmark':{'results':[{'model':'removed-image'}]}}
  original=copy.deepcopy(data);view=m.installed_report_view(data)
  self.assertEqual([r['name'] for r in view['models']],['keep'])
  self.assertEqual([r['model'] for r in view['results']],['keep'])
  self.assertEqual([r['model'] for r in view['engine_reports']],['keep'])
  self.assertEqual(view['image_benchmark']['results'],[]);self.assertEqual(data,original)
 def test_empty_inventory_does_not_retain_deleted_models(self):
  data={'models':[{'name':'gone'}],'results':[{'model':'gone'}],'discovery':{'models':[]}}
  self.assertEqual(m.installed_report_view(data)['models'],[])
