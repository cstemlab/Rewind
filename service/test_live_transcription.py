import base64
import json
import queue
import socket
import threading
import time
import unittest
from unittest.mock import patch

from assess import AssessmentError
from live_transcription import LiveSession, LiveManager, SESSION_UPDATE, RATE, BoundedWebSocket, MAX_MESSAGE, _connect, URL


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.incoming = queue.Queue()
        self.closed = False
    def send(self, text):
        data = json.loads(text)
        self.sent.append(data)
        if data['type'] == 'session.update':
            self.incoming.put(json.dumps({'type': 'session.updated'}))
    def recv(self):
        try:
            return self.incoming.get(timeout=.01)
        except queue.Empty:
            if self.closed:
                return ''
            raise socket.timeout()
    def shutdown(self):
        self.closed = True


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.ws = FakeSocket()
        self.session = LiveSession(5, factory=lambda key: self.ws)
        self.session.connect('test-key-not-real')
    def tearDown(self):
        self.session.close()
    def assert_code(self, code, function, *args):
        with self.assertRaises(AssessmentError) as ctx:
            function(*args)
        self.assertEqual(ctx.exception.code, code)
    def delta(self, text, item='a'):
        self.session.handle_event({'type':'conversation.item.input_audio_transcription.delta','item_id':item,'delta':text,'content_index':0})

    def test_config_without_reference_or_prompt(self):
        self.assertEqual(self.ws.sent, [SESSION_UPDATE])
        audio = SESSION_UPDATE['session']['audio']['input']
        self.assertEqual(audio['transcription'], {'model':'gpt-live-transcribe','languages':['yue'],'delay':'low'})
        self.assertIsNone(audio['turn_detection'])
        self.assertNotIn('prompt', json.dumps(SESSION_UPDATE))
        self.assertEqual(self.session.summary()['feedback_kind'],'transcription-progress')

    def test_pcm_chunks_are_sequential_and_not_retained(self):
        data = b'\x01\x00' * 2400
        result = self.session.append(0, data)
        self.assertEqual(result['next_seq'],1)
        self.assertEqual(base64.b64decode(self.ws.sent[-1]['audio']),data)
        self.assert_code('live_sequence',self.session.append,0,data)
        self.assert_code('live_sequence',self.session.append,2,data)
        self.assert_code('live_sequence',self.session.append,True,data)
        self.assertFalse(any(isinstance(v,bytes) for v in self.session.__dict__.values()))

    def test_invalid_pcm_and_size_limits(self):
        for data in (b'',b'\0',b'\0'*48002,'not bytes'):
            self.assert_code('live_audio_format',self.session.append,0,data)
        for i in range(25):
            self.session.append(i,b'\0'*48000)
        self.assert_code('live_limit',self.session.append,25,b'\0\0')

    def test_deltas_before_commit_and_completion_reconciliation(self):
        self.delta('我今')
        self.delta('日買書')
        events = self.session.events(0)['events']
        self.assertEqual([e['text'] for e in events],['我今','我今日買書'])
        self.assertTrue(all(e['item_index']==0 and not e['final'] for e in events))
        self.session.append(0,b'\0'*4800)
        self.session.stop()
        self.session.handle_event({'type':'input_audio_buffer.committed','item_id':'a'})
        self.session.handle_event({'type':'conversation.item.input_audio_transcription.completed','item_id':'a','transcript':'我今日買書。'})
        result=self.session.events(2)
        self.assertEqual(result['events'][0]['text'],'我今日買書。')
        self.assertTrue(result['events'][0]['final'])
        self.assertEqual(result['state'],'closed')
        self.assertTrue(self.ws.closed)
        self.assertNotIn('score',json.dumps(result))

    def test_wrong_item_does_not_merge_or_pass(self):
        self.delta('我')
        self.delta('你','b')
        result=self.session.events(0)
        self.assertEqual(result['state'],'error')
        self.assertEqual([e['text'] for e in result['events'] if e['type']=='transcript'],['我'])

    def test_commit_mismatching_first_delta_is_neutral_error(self):
        self.delta('我')
        self.session.handle_event({'type':'input_audio_buffer.committed','item_id':'b'})
        self.assertEqual(self.session.state,'error')

    def test_single_commit_and_cancel(self):
        self.session.append(0,b'\0'*4800)
        self.session.stop(True)
        self.session.stop(True)
        self.assertEqual(sum(m['type']=='input_audio_buffer.commit' for m in self.ws.sent),1)
        self.session.close()
        self.assert_code('live_closed',self.session.append,1,b'\0\0')

    def test_cancel_does_not_commit(self):
        self.session.append(0,b'\0'*4800)
        self.session.stop(False)
        self.assertFalse(any(m['type']=='input_audio_buffer.commit' for m in self.ws.sent))

    def test_empty_stream_does_not_commit(self):
        self.assertEqual(self.session.stop()['state'],'closed')
        self.assertEqual(self.session.events(0)['events'][-1]['reason'],'no_audio')

    def test_provider_error_never_echoes_key_or_audio(self):
        self.session.handle_event({'type':'error','error':{'message':'SECRET_KEY raw audio credentials'}})
        result=json.dumps(self.session.events(0))
        self.assertNotIn('SECRET_KEY',result)
        self.assertNotIn('raw audio',result)
        self.assertEqual(self.session.state,'error')

    def test_no_audio_stale_cleanup(self):
        self.session._clock=lambda: self.session._last_audio+8
        self.session.check_deadlines()
        self.assertEqual(self.session.state,'closed')
        self.assertTrue(self.ws.closed)

    def test_capture_hard_cap_commits_then_finishing_timeout_closes(self):
        self.session.append(0,b'\0'*4800)
        now=self.session._started+25.1
        self.session._last_audio=now
        self.session._clock=lambda:now
        self.session.check_deadlines()
        self.assertEqual(self.session.state,'finishing')
        self.session._clock=lambda:now+12.1
        self.session.check_deadlines()
        self.assertEqual(self.session.state,'error')
        self.assertTrue(self.ws.closed)

    def test_text_and_event_memory_are_bounded(self):
        for i in range(300):
            self.delta('我')
        self.assertEqual(len(self.session.events(0)['events']),256)
        self.delta('我'*1601)
        self.assertEqual(self.session.state,'error')

    def test_poll_cursor_validation(self):
        for cursor in (-1,True,'0',100):
            self.assert_code('live_cursor',self.session.events,cursor)

    def test_manager_single_session_generation_and_cancel(self):
        manager=LiveManager(factory=lambda key: FakeSocket())
        result=manager.start('not-real-key',1)
        self.assert_code('live_busy',manager.start,'not-real-key',1)
        self.assert_code('live_session',manager.get,'wrong',1)
        self.assert_code('configuration_changed',manager.get,result['session_id'],2)
        manager.cancel()
        self.assertEqual(manager.get(result['session_id'],1).state,'closed')

    def test_pinned_endpoint_redirect_blocked(self):
        ws=FakeSocket()
        ws.handshake_response=type('Response',(),{'status':302})()
        with patch('live_transcription.websocket.create_connection',return_value=ws) as call:
            self.assert_code('live_connection',_connect,'secret-key')
        args,kw=call.call_args
        self.assertEqual(args,(URL,))
        self.assertEqual(kw['redirect_limit'],0)
        self.assertNotIn('sslopt',kw)
        self.assertTrue(ws.closed)

    def test_frame_and_fragment_limits(self):
        ws=BoundedWebSocket()
        # Inject frame-length bytes; reject before receiving any payload.
        ws.frame_buffer.header=(1,0,0,0,1,0,127)
        ws.frame_buffer.recv_strict=lambda _: (MAX_MESSAGE+1).to_bytes(8,'big')
        with self.assertRaises(Exception):
            ws.frame_buffer.recv_length()
        frame=type('Frame',(),{'data':b'a'*(MAX_MESSAGE+1),'opcode':1,'fin':0})()
        with self.assertRaises(Exception):
            ws.cont_frame.add(frame)


if __name__=='__main__':
    unittest.main()
