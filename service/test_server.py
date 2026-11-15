import base64
import http.client
from http.server import ThreadingHTTPServer
import json
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import server
from openai_feedback import normalize_openai
from test_openai_feedback import model_reply
from assess import AssessmentError
from test_azure_feedback import wav, pa, asr


class ServiceTests(unittest.TestCase):
    def setUp(self):
        server.PROVIDER='azure'
        server.API_KEY='test-private-key'; server.REGION='eastasia'; server.VERIFIED=False
        server.GENERATION+=1; server.CALL_TIMES.clear()

    def test_player_uses_native_build_then_repo_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            here=root/'service'; here.mkdir()
            index=root/'index.html'; index.write_text('repository',encoding='utf-8')
            with patch.object(server,'HERE',here):
                self.assertEqual(server.player_path(),index)
                native=root/'player'/'build'/'Rewind.html'
                native.parent.mkdir(parents=True)
                native.write_text('native',encoding='utf-8')
                self.assertEqual(server.player_path(),native)

    def test_silence_uses_no_cloud_and_produces_no_pass(self):
        with patch('server.assess_azure_bytes') as cloud:
            result=server.assess_recording(wav(silent=True),'我')
        cloud.assert_not_called(); self.assertEqual(result['status'],'no_speech')
        self.assertEqual(result['groups'],[]); self.assertEqual(result['cloud_requests'],0)

    def test_exact_reference_survives_offsets(self):
        with patch('server.assess_azure_bytes',return_value=pa([('我',99,'None')])), patch('server.recognize_azure_bytes',return_value=asr('我')):
            result=server.assess_recording(wav(),' 我。 ')
        self.assertEqual(result['reference'],' 我。 ')
        self.assertEqual(result['groups'][0]['start'],1)
        self.assertTrue(server.VERIFIED)

    def test_crosscheck_failure_retains_neutral_result_without_raw_error(self):
        with patch('server.assess_azure_bytes',return_value=pa([('我',100,'None')])), patch('server.recognize_azure_bytes',side_effect=AssessmentError('network_error','safe')):
            result=server.assess_recording(wav(),'我')
        self.assertEqual(result['groups'][0]['state'],'uncertain')

    def test_reconfigure_during_request_cannot_return_stale_results(self):
        def change(*_):
            server.GENERATION+=1
            return pa([('我',100,'None')])
        with patch('server.assess_azure_bytes',side_effect=change),patch('server.recognize_azure_bytes') as cross:
            with self.assertRaisesRegex(AssessmentError,'連線已變更'): server.assess_recording(wav(),'我')
        cross.assert_not_called()

    def test_secret_echo_from_provider_is_redacted(self):
        with patch('server.assess_azure_bytes',return_value=pa([('我',100,'None')])),patch('server.recognize_azure_bytes',return_value=asr('test-private-key')):
            result=server.assess_recording(wav(),'我')
        self.assertNotIn('test-private-key',json.dumps(result))

    def test_configured_is_not_verified(self):
        self.assertTrue(server.status()['configured']); self.assertFalse(server.status()['connection_verified'])
        self.assertNotIn('test-private-key',json.dumps(server.status()))

    def test_missing_configuration_prevents_cloud(self):
        server.API_KEY=''
        with patch('server.assess_azure_bytes') as cloud, self.assertRaises(AssessmentError): server.assess_recording(wav(),'我')
        cloud.assert_not_called()

    def test_rate_limit_and_inflight(self):
        server.CALL_TIMES.extend([server.time.monotonic()]*5)
        with self.assertRaises(AssessmentError): server.assess_recording(wav(),'我')
        server.CALL_TIMES.clear(); server.INFLIGHT.acquire()
        try:
            with self.assertRaises(AssessmentError): server.assess_recording(wav(),'我')
        finally: server.INFLIGHT.release()

    def test_failed_assessment_does_not_verify_connection(self):
        with patch('server.assess_azure_bytes',return_value={}),patch('server.recognize_azure_bytes',return_value=asr('我')):
            with self.assertRaises(AssessmentError): server.assess_recording(wav(),'我')
        self.assertFalse(server.VERIFIED)

    def test_openai_uses_one_direct_audio_request_no_azure(self):
        server.PROVIDER='openai'; server.REGION=''
        with patch('server.coach_openai_bytes',return_value=normalize_openai(model_reply(),'聽日')) as direct,patch('server.assess_azure_bytes') as azure:
            result=server.assess_recording(wav(),'聽日')
        direct.assert_called_once(); azure.assert_not_called()
        self.assertEqual(result['provider'],'openai')
        self.assertEqual(result['cloud_requests'],1)
        self.assertTrue(server.VERIFIED)

    def test_openai_silence_never_calls_provider(self):
        server.PROVIDER='openai'; server.REGION=''
        with patch('server.coach_openai_bytes') as direct:
            result=server.assess_recording(wav(silent=True),'聽日')
        direct.assert_not_called()
        self.assertEqual(result['provider'],'openai'); self.assertEqual(result['cloud_requests'],0)

    def test_stale_provider_consent_cannot_send_audio_to_other_provider(self):
        server.PROVIDER='openai';server.REGION=''
        with patch('server.coach_openai_bytes') as direct,patch('server.assess_azure_bytes') as azure:
            with self.assertRaises(AssessmentError) as raised:
                server.assess_recording(wav(),'聽日',expected_provider='azure')
        self.assertEqual(raised.exception.code,'provider_changed')
        direct.assert_not_called();azure.assert_not_called()


class HttpTests(unittest.TestCase):
    def setUp(self):
        server.PROVIDER='azure';server.API_KEY='';server.REGION='';server.VERIFIED=False
    @classmethod
    def setUpClass(cls):
        cls.httpd=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.port=cls.httpd.server_address[1]
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close(); cls.thread.join()

    def request(self,path,body=None,headers=None):
        client=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        head={'Content-Type':'application/json','X-Rewind-Token':server.TOKEN}
        head.update(headers or {})
        client.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),head)
        response=client.getresponse(); data=response.read(); code=response.status; client.close()
        return code,json.loads(data)

    def test_foreign_origin_and_host_are_denied(self):
        self.assertEqual(self.request('/api/config',{'key':'secret-test','region':'eastasia'},{'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.request('/api/status',headers={'Host':'evil.invalid'})[0],403)

    def test_bad_token_denied(self):
        self.assertEqual(self.request('/api/disconnect',{}, {'X-Rewind-Token':'wrong'})[0],403)

    def test_config_is_memory_only_no_call_then_disconnect(self):
        with patch('server.assess_azure_bytes') as cloud:
            code,result=self.request('/api/config',{'key':'test-private-key','region':'eastasia'})
        cloud.assert_not_called(); self.assertEqual(code,200)
        self.assertTrue(result['configured']); self.assertFalse(result['connection_verified'])
        self.assertNotIn('test-private-key',json.dumps(result))
        code,result=self.request('/api/disconnect',{})
        self.assertFalse(result['configured'])

    def test_invalid_json_shape_and_format(self):
        self.assertEqual(self.request('/api/config',[])[0],400)
        self.assertEqual(self.request('/api/config',{}, {'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('/api/assess-recording',{'text':'我','audio':'not base64','extension':'.wav'})[0],400)

    def test_no_arbitrary_file_route(self):
        self.assertEqual(self.request('/server.py')[0],404)
        self.assertEqual(self.request('/../assess.py')[0],404)

    def test_openai_config_does_not_require_region_and_switch_clears_it(self):
        with patch('server.coach_openai_bytes') as direct:
            code,result=self.request('/api/config',{'provider':'openai','key':'test-private-key'})
        direct.assert_not_called();self.assertEqual(code,200)
        self.assertTrue(result['configured']);self.assertEqual(result['region'],'')
        self.assertEqual(result['cloud_requests_per_attempt'],1)
        self.assertEqual(result['supported_providers'],['azure','openai'])
        self.assertFalse(result['connection_verified'])

    def test_unsupported_provider_cannot_change_target_endpoint(self):
        code,result=self.request('/api/config',{'provider':'https://evil.invalid','key':'test-private-key'})
        self.assertEqual(code,400);self.assertEqual(result['code'],'invalid_provider')

    def test_http_assessment_requires_explicit_matching_provider(self):
        self.request('/api/config',{'provider':'openai','key':'test-private-key'})
        data={'audio':base64.b64encode(wav()).decode(),'text':'聽日','extension':'.wav'}
        with patch('server.coach_openai_bytes') as direct:
            self.assertEqual(self.request('/api/assess-recording',data)[0],400)
            code,result=self.request('/api/assess-recording',{**data,'provider':'azure'})
        self.assertEqual(code,409);self.assertEqual(result['code'],'provider_changed');direct.assert_not_called()


if __name__=='__main__': unittest.main()
