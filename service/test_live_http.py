"""Loopback-only API tests; every WebSocket is a fake, never a provider call."""
import base64
import json
import unittest
from unittest.mock import patch
import server
import test_server as baseline
from live_transcription import LiveManager
from test_live_transcription import FakeSocket


class LiveHttpTests(unittest.TestCase):
    request=baseline.HttpTests.request
    setUpClass=classmethod(baseline.HttpTests.setUpClass.__func__)
    tearDownClass=classmethod(baseline.HttpTests.tearDownClass.__func__)

    def setUp(self):
        self.manager=LiveManager(factory=lambda key: FakeSocket())
        self.patcher=patch.object(server,'LIVE',self.manager)
        self.patcher.start()
        server.PROVIDER='openai';server.API_KEY='not-a-real-test-key';server.REGION=''
        server.GENERATION+=1
    def tearDown(self):
        self.manager.cancel()
        self.patcher.stop()
    def start(self):
        code,result=self.request('/api/live/start',{'provider':'openai'})
        self.assertEqual(code,200)
        return result['session_id']
    def audio(self,sid,seq=0):
        return self.request('/api/live/audio',{'provider':'openai','session_id':sid,'seq':seq,'audio':base64.b64encode(b'\0'*4800).decode()})

    def test_all_live_endpoints_require_token_and_same_origin(self):
        for route in ('start','audio','events','stop','cancel'):
            path='/api/live/'+route
            self.assertEqual(self.request(path,{'provider':'openai'},{'X-Rewind-Token':'bad'})[0],403)
            self.assertEqual(self.request(path,{'provider':'openai'},{'Origin':'https://evil.invalid'})[0],403)
            self.assertEqual(self.request(path,{'provider':'openai'},{'Host':'evil.invalid'})[0],403)

    def test_provider_binding_before_connection(self):
        with patch.object(self.manager,'start') as cloud:
            self.assertEqual(self.request('/api/live/start',{})[0],400)
            self.assertEqual(self.request('/api/live/start',{'provider':'azure'})[0],400)
            server.PROVIDER='azure'
            code,result=self.request('/api/live/start',{'provider':'openai'})
        self.assertEqual((code,result['code']),(409,'provider_changed'))
        cloud.assert_not_called()

    def test_unconfigured_never_connects(self):
        server.API_KEY=''
        with patch.object(self.manager,'start') as cloud:
            code,result=self.request('/api/live/start',{'provider':'openai'})
        self.assertEqual((code,result['code']),(409,'not_configured'))
        cloud.assert_not_called()

    def test_complete_routes_and_sequence(self):
        sid=self.start()
        self.assertEqual(self.audio(sid)[0],200)
        self.assertEqual(self.audio(sid)[0],409)
        session=self.manager.get(sid,server.GENERATION)
        session.handle_event({'type':'conversation.item.input_audio_transcription.delta','item_id':'x','delta':'我'})
        code,result=self.request('/api/live/events',{'provider':'openai','session_id':sid,'after':0})
        self.assertEqual(code,200)
        self.assertEqual(result['events'][0]['text'],'我')
        code,result=self.request('/api/live/stop',{'provider':'openai','session_id':sid,'commit':True})
        self.assertEqual(result['state'],'finishing')
        code,result=self.request('/api/live/cancel',{'provider':'openai','session_id':sid})
        self.assertEqual(result['state'],'closed')
        self.assertEqual(self.audio(sid,1)[0],409)

    def test_disconnect_and_switch_close_active_stream(self):
        sid=self.start()
        session=self.manager.get(sid,server.GENERATION)
        self.request('/api/disconnect',{})
        self.assertEqual(session.state,'closed')
        self.assertEqual(self.audio(sid)[0],409)
        self.request('/api/config',{'provider':'openai','key':'not-real-key'})
        sid=self.start()
        session=self.manager.get(sid,server.GENERATION)
        self.request('/api/config',{'provider':'azure','key':'not-real-key','region':'eastasia'})
        self.assertEqual(session.state,'closed')
        self.assertEqual(self.audio(sid)[1]['code'],'provider_changed')

    def test_cross_tab_old_session_cannot_append_to_new(self):
        old=self.start()
        self.request('/api/live/cancel',{'provider':'openai','session_id':old})
        new=self.start()
        self.assertNotEqual(old,new)
        self.assertEqual(self.audio(old)[1]['code'],'live_session')
        self.assertEqual(self.audio(new)[0],200)

    def test_status_has_capability_without_key(self):
        code,result=self.request('/api/status')
        live=result['live_transcription']
        self.assertTrue(live['available'])
        self.assertEqual(live['feedback_kind'],'transcription-progress')
        self.assertNotIn('not-a-real-test-key',json.dumps(result))
        server.PROVIDER='azure'
        self.assertFalse(server.status()['live_transcription']['available'])

    def test_malformed_or_oversized_chunks_never_send(self):
        sid=self.start()
        session=self.manager.get(sid,server.GENERATION)
        for encoded in ('%%%', 'A'*64004, base64.b64encode(b'\0').decode()):
            code,_=self.request('/api/live/audio',{'provider':'openai','session_id':sid,'seq':0,'audio':encoded})
            self.assertEqual(code,400)
        self.assertEqual(len(session._ws.sent),1)

    def test_independent_rate_limits_for_live_and_final(self):
        for _ in range(5):
            sid=self.start()
            self.request('/api/live/cancel',{'provider':'openai','session_id':sid})
        self.assertEqual(self.request('/api/live/start',{'provider':'openai'})[0],429)
        # Starting streams has not used the separate final-assessment lock.
        self.assertTrue(server.INFLIGHT.acquire(blocking=False))
        server.INFLIGHT.release()


if __name__=='__main__':
    unittest.main()
