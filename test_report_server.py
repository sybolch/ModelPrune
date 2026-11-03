import json,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
import report_server as s

class StubManager:
    def __init__(self):self.active=False
    def snapshot(self):return {'state':'running' if self.active else 'idle'}
    def start(self,kind='benchmark'):
        if self.active:return False,self.snapshot()
        self.active=True;self.kind=kind;return True,self.snapshot()

class ReportServerTests(unittest.TestCase):
    def setUp(self):
        self.manager=StubManager();self.server=s.server({'port':0,'token':'a'*64},self.manager)
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,path='/api/status',method='GET',token='a'*64,origin='null',body=None):
        headers={'Origin':origin,'Authorization':'Bearer '+token,'Content-Type':'application/json'}
        return urllib.request.urlopen(urllib.request.Request(self.url+path,method=method,headers=headers,data=body))
    def test_file_origin_status_and_preflight(self):
        with self.request() as response:self.assertEqual(response.headers['Access-Control-Allow-Origin'],'null');self.assertEqual(json.load(response)['state'],'idle')
        with self.request(method='OPTIONS') as response:self.assertEqual(response.status,204);self.assertEqual(response.headers['Access-Control-Allow-Private-Network'],'true')
    def test_bad_token_and_external_origin_rejected(self):
        for options in [{'token':'bad'},{'origin':'https://evil.example'}]:
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request(**options)
            self.assertEqual(caught.exception.code,403);caught.exception.close()
    def test_start_is_single_flight_and_options_are_not_commands(self):
        with self.request('/api/run','POST',body=b'{}') as response:self.assertEqual(response.status,202)
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/run','POST',body=b'{}')
        self.assertEqual(caught.exception.code,409);caught.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/run','POST',body=b'{"command":"anything"}')
        self.assertEqual(caught.exception.code,400);caught.exception.close()
    def test_partial_uses_the_shared_operation_lock(self):
        with self.request('/api/partial','POST',body=b'{}') as response:self.assertEqual(response.status,202)
        self.assertEqual(self.manager.kind,'partial')
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/discover','POST',body=b'{}')
        self.assertEqual(caught.exception.code,409);caught.exception.close()
    def test_discovery_uses_same_lock_as_benchmark(self):
        with self.request('/api/discover','POST',body=b'{}') as response:self.assertEqual(response.status,202)
        self.assertEqual(self.manager.kind,'discovery')
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/run','POST',body=b'{}')
        self.assertEqual(caught.exception.code,409);caught.exception.close()
    def test_progress_includes_scored_samples_in_active_suite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);job=root/'job';(job/'reviews/model').mkdir(parents=True)
            (job/'reviews/model/test.jsonl').write_text('{}\n{}\n{"partial"')
            (root/'run.json').write_text(json.dumps({'standard_limit':5,'jobs':[{'status':'completed','sample_count':5,'type':'standard'}, {'status':'running','type':'standard','folder':str(job),'model':'m','suite':'boolq'}]}))
            manager=s.Manager({});manager.output=root;manager.state={'state':'running'};state=manager.snapshot()
            self.assertEqual(state['completed_samples'],7);self.assertEqual(state['total_samples'],10)
            self.assertEqual(state['completed_jobs'],1);self.assertIn('boolq',state['current'])

if __name__=='__main__':unittest.main()
