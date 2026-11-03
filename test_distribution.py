import hashlib,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import install

class DistributionTests(unittest.TestCase):
 def test_lockfiles_are_pinned_and_do_not_reference_local_paths(self):
  for path in (install.SOURCE/'requirements').glob('*.lock'):
   lines=[line for line in path.read_text().splitlines() if line and not line.startswith('#')]
   self.assertTrue(lines);self.assertTrue(all('==' in line and ' @ ' not in line for line in lines))
 def test_uv_bootstrap_verifies_hash_and_extracts_only_binary(self):
  buffer=io.BytesIO()
  with zipfile.ZipFile(buffer,'w') as archive:archive.writestr('uv/uv',b'executable');archive.writestr('../../escape',b'no')
  content=buffer.getvalue();metadata={'urls':[{'filename':'uv-manylinux_2_17_x86_64.whl','url':'https://example.test/wheel','digests':{'sha256':hashlib.sha256(content).hexdigest()}}]}
  with tempfile.TemporaryDirectory() as folder,patch('shutil.which',return_value=None),patch('urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps(metadata).encode()),io.BytesIO(content)]):
   binary=install.get_uv(Path(folder));self.assertEqual(binary.read_bytes(),b'executable');self.assertFalse((Path(folder)/'escape').exists())
 def test_repository_uses_verified_public_fixtures(self):
  manifest=json.loads((install.SOURCE/'fixtures/audio-manifest.json').read_text())
  self.assertEqual(manifest['voice'],'Piper en_US-ljspeech-high')
  self.assertEqual(len(manifest['verification']['results']),len(manifest['clips']))
  self.assertTrue(all(row['matched'] for row in manifest['verification']['results']))
  for clip in manifest['clips']:
   self.assertEqual(hashlib.sha256((install.SOURCE/'fixtures'/clip['file']).read_bytes()).hexdigest(),clip['sha256'])
