import copy,unittest
import model_aliases as a
import incremental

class AliasTests(unittest.TestCase):
 def model(self,name,parent='',weight='a',adapter=None):
  info={'modelfile':'FROM /weights/sha256-'+weight*64+('\nADAPTER /weights/sha256-'+adapter*64 if adapter else ''),'capabilities':['completion'],'details':{'quantization_level':'Q4'},'model_info':{'general.architecture':'test'}}
  return {'name':name,'digest':name,'capabilities':['completion'],'details':{'parent_model':parent},'weight_identity':a.identity(info),'runtime_parameters':'num_ctx 8192','context_override':8192}
 def test_parameter_aliases_collapse_and_named_parent_wins(self):
  source=[self.model('demo-work:8k','demo:3b'),self.model('demo:3b')];original=copy.deepcopy(source)
  grouped=a.group_models(source)
  self.assertEqual(len(grouped),1);self.assertEqual(grouped[0]['name'],'demo:3b');self.assertEqual(grouped[0]['aliases'][0]['name'],'demo-work:8k');self.assertEqual(source,original)
  self.assertEqual(a.group_models(grouped),grouped)
  baseline={'models':[{'name':'demo:3b','digest':'demo:3b','capabilities':['completion','coding']}],'results':[{'model':'demo:3b'}]}
  self.assertEqual(incremental.select_models(baseline,source),[])
 def test_suffix_does_not_merge_different_weights_or_adapters(self):
  for different in [self.model('demo-work:8k','demo:3b',weight='b'),self.model('demo-work:8k','demo:3b',adapter='c')]:
   self.assertEqual(len(a.group_models([self.model('demo:3b'),different])),2)
 def test_exact_alias_requests_resolve_to_canonical_model(self):
  groups=a.group_models([self.model('demo-work:8k','demo:3b'),self.model('demo:3b')])
  self.assertEqual(a.resolve_requested(groups,['demo-work:8k','demo:3b']),['demo:3b'])
 def test_unknown_remote_identity_does_not_merge_models(self):
  self.assertIsNone(a.identity({'remote_host':'https://provider'}))
 def test_weight_identity_keeps_alias_only_registration_out_of_partial_run(self):
  old=self.model('demo:3b');new=self.model('renamed:3b')
  self.assertEqual(incremental.select_models({'models':[old],'results':[{'model':'demo:3b'}]},[new]),[])
