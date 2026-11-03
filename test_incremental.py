import copy,tempfile,unittest,json
from unittest.mock import patch
from pathlib import Path
import incremental as i
class IncrementalTests(unittest.TestCase):
 def test_selects_new_and_changed_but_not_saved_or_embedding_models(self):
  old={'models':[{'name':'keep','digest':'a','capabilities':['completion','coding']},{'name':'changed','digest':'old','capabilities':['completion']}],'results':[{'model':'keep'},{'model':'changed'}]}
  installed=[{'name':n,'digest':d,'capabilities':caps} for n,d,caps in [('keep','a',['completion']),('changed','new',['completion']),('new','b',['completion']),('embed','c',['embedding'])]]
  self.assertEqual(i.select_models(old,installed),['changed','new'])
 def test_merge_retains_existing_test_scores_and_evidence(self):
  old={'engine':'EvalScope test','fixture_hash':'same','standard_limit':5,'config':{},'models':[{'name':'old'}],'results':[{'model':'old','points':1,'seconds':2.0}],'tasks':[{'id':'one'}],'jobs':[{'model':'old'}],'engine_reports':[{'model':'old'}]}
  new={'engine':'EvalScope test','fixture_hash':'same','standard_limit':5,'config':{},'models':[{'name':'new'}],'results':[{'model':'new','points':0,'seconds':3.0}],'tasks':[{'id':'one'}],'jobs':[{'model':'new'}],'engine_reports':[{'model':'new'}],'discovery':{'models':[]},'created':'today'}
  original=copy.deepcopy(old);merged=i.merge(old,new)
  self.assertEqual(merged['results'][0],old['results'][0]);self.assertEqual(len(merged['results']),2);self.assertEqual(old,original)
  bad={**new,'fixture_hash':'changed'}
  with self.assertRaisesRegex(RuntimeError,'fixtures changed'):i.merge(old,bad)
 def test_partial_without_new_models_does_not_run_inference(self):
  import report_server as server
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'ModelPrune-EvalScope-results.json').write_text(json.dumps({'models':[],'results':[]}))
   manager=server.Manager({'publish_dir':folder});manager.state={'state':'running','kind':'partial'};manager.output=root/'unused'
   with patch('modelprune.inventory',return_value=[]),patch('subprocess.Popen') as process:
    manager._partial()
   process.assert_not_called();self.assertEqual(manager.state['state'],'completed');self.assertIn('No new',manager.state['message'])
 def test_existing_image_is_not_repeated_and_new_checkpoint_is_selected(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'models/checkpoints';path.mkdir(parents=True)
   for name in ['old.safetensors','new.safetensors']:(path/name).write_bytes(b'weight')
   data={'image_benchmark':{'results':[{'model':'old.safetensors'}]},'jobs':[]}
   self.assertEqual(i.select_images(data,folder),['new.safetensors'])
