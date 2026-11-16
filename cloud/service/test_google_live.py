"""Offline Google Live protocol/state tests; no microphone or cloud requests."""
from array import array
import json
import queue
import struct
import unittest

from assess import AssessmentError
from google_live import PCM24To16, GoogleConnection, GoogleLiveSession, GoogleLiveManager, MODEL, websocket


class FakeWebSocket:
    def __init__(self):
        self.queue = queue.Queue()
        self.sent = []
        self.closed = False

    def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        if 'setup' in message:
            self.queue.put(json.dumps({'setupComplete': {}}).encode())

    def recv(self):
        try:
            return self.queue.get(timeout=.02)
        except queue.Empty:
            raise websocket.WebSocketTimeoutException()

    def shutdown(self):
        self.closed = True


class GoogleLiveTests(unittest.TestCase):
    def setUp(self):
        self.clock = [10.0]
        self.connection = GoogleConnection('rewind-514904')
        self.ws = FakeWebSocket()
        self.session = GoogleLiveSession(7, self.connection, factory=lambda _: self.ws, clock=lambda: self.clock[0])

    def tearDown(self):
        self.session.close()

    def connected(self):
        result = self.session.connect('ignored-server-only')
        self.assertEqual(result['sample_rate'], 24000)
        self.assertEqual(result['feedback_kind'], 'transcription-progress')
        self.assertEqual(result['model'], MODEL)
        return result

    def finishing(self):
        self.connected()
        self.session.append(0, b'\x01\x00' * 4800)
        self.session.stop(True)

    def test_setup_verbatim_cantonese_no_script_bias(self):
        self.connected()
        setup = self.ws.sent[0]['setup']
        self.assertEqual(setup['inputAudioTranscription'], {'languageCodes': ['yue-Hant-HK'], 'mode': 'VERBATIM'})
        self.assertNotIn('systemInstruction', setup)
        self.assertNotIn('customVocabulary', setup['inputAudioTranscription'])
        self.assertTrue(setup['realtimeInputConfig']['automaticActivityDetection']['disabled'])
        self.assertEqual(self.ws.sent[1], {'realtimeInput': {'activityStart': {}}})

    def test_rate_conversion_chunk_boundaries(self):
        data = b''.join(struct.pack('<h', i * 10) for i in range(95))
        full = PCM24To16().push(data, finish=True)
        chunked = PCM24To16()
        parts = [chunked.push(data[i:i+14]) for i in range(0, len(data), 14)]
        parts.append(chunked.push(b'', finish=True))
        self.assertEqual(b''.join(parts), full)
        self.assertEqual(len(full) // 2, 95 * 2 // 3)
        self.assertEqual(len(chunked.pending), 0)

    def test_pcm_protocol_sequences_and_16k(self):
        self.connected()
        result = self.session.append(0, b'\x10\x00' * 4800)
        self.assertEqual(result['next_seq'], 1)
        self.assertEqual(self.ws.sent[-1]['realtimeInput']['audio']['mimeType'], 'audio/pcm;rate=16000')
        with self.assertRaises(AssessmentError):
            self.session.append(0, b'\x00\x00')
        with self.assertRaises(AssessmentError):
            self.session.append(1, b'\x00')

    def test_interim_replaces_not_appends(self):
        self.connected()
        self.session.handle_event({'serverContent': {'interimInputTranscription': {'text': '我早'}}})
        self.session.handle_event({'serverContent': {'interimInputTranscription': {'text': '我想學'}}})
        events = self.session.events(0)['events']
        self.assertEqual(events[-1]['text'], '我想學')
        self.assertFalse(events[-1]['final'])
        self.assertNotIn('score', events[-1])

    def test_final_replaces_interim_and_closes_after_stop(self):
        self.finishing()
        self.session.handle_event({'serverContent': {'interimInputTranscription': {'text': '我想'}}})
        self.session.handle_event({'serverContent': {'inputTranscription': {'text': '我想學粵語。', 'finished': True}}})
        events = self.session.events(0)['events']
        self.assertEqual(events[-2]['text'], '我想學粵語。')
        self.assertTrue(events[-2]['final'])
        self.assertEqual(events[-1]['reason'], 'completed')
        self.assertTrue(self.ws.closed)

    def test_turn_complete_before_transcript_does_not_close_early(self):
        self.finishing()
        self.session.handle_event({'serverContent': {'turnComplete': True}})
        self.assertEqual(self.session.state, 'finishing')
        self.session.handle_event({'serverContent': {'inputTranscription': {'text': '早晨。'}}})
        self.assertEqual(self.session.state, 'closed')
        self.assertEqual(self.session.events(0)['events'][-2]['text'], '早晨。')

    def test_final_input_without_optional_flags_completes(self):
        self.finishing()
        self.session.handle_event({'serverContent': {'interimInputTranscription': {'text': '早'}}})
        self.session.handle_event({'serverContent': {'inputTranscription': {'text': '早晨。'}}})
        self.assertEqual(self.session.state, 'closed')
        events = self.session.events(0)['events']
        self.assertEqual(events[-2]['text'], '早晨。')
        self.assertTrue(events[-2]['final'])
        self.assertEqual(events[-1]['reason'], 'completed')

    def test_committed_before_stop_is_not_post_stop_completion_proof(self):
        self.connected()
        self.session.append(0, b'\x01\x00' * 4800)
        self.session.handle_event({'serverContent': {'inputTranscription': {'text': '早晨。'}}})
        self.session.stop(True)
        self.assertEqual(self.session.state, 'finishing')
        self.assertFalse(any(event.get('final') for event in self.session.events(0)['events']))
        self.clock[0] += 13
        self.session.check_deadlines()
        self.assertEqual(self.session.state, 'error')

    def test_partial_final_segments_join(self):
        self.finishing()
        self.session.handle_event({'server_content': {'input_transcription': {'text': '早', 'finished': False}}})
        self.session.handle_event({'server_content': {'input_transcription': {'text': '晨。', 'finished': True}}})
        self.assertEqual(self.session.events(0)['events'][-2]['text'], '早晨。')

    def test_transcript_limit_and_provider_error_hide_payload(self):
        self.connected()
        self.session.handle_event({'error': {'message': 'SECRET private provider payload'}})
        result = self.session.events(0)
        self.assertEqual(result['state'], 'error')
        self.assertNotIn('SECRET', json.dumps(result))

    def test_invalid_transcript_rejected(self):
        self.connected()
        self.session.handle_event({'serverContent': {'inputTranscription': {'text': ['wrong']}}})
        self.assertEqual(self.session.state, 'error')

    def test_cancel_sends_no_commit(self):
        self.connected()
        self.session.append(0, b'\x01\x00' * 4800)
        self.session.stop(False)
        self.assertEqual(self.session.state, 'closed')
        self.assertFalse(any('activityEnd' in item.get('realtimeInput', {}) for item in self.ws.sent))

    def test_stop_only_once_and_timeout(self):
        self.finishing()
        self.session.stop(True)
        self.assertEqual(sum('activityEnd' in item.get('realtimeInput', {}) for item in self.ws.sent), 1)
        self.clock[0] += 13
        self.session.check_deadlines()
        self.assertEqual(self.session.state, 'error')

    def test_inactive_and_audio_limit(self):
        self.connected()
        self.clock[0] += 8
        self.session.check_deadlines()
        self.assertEqual(self.session.state, 'closed')

    def test_manager_isolates_session_and_generation(self):
        manager = GoogleLiveManager('rewind-514904', factory=lambda _: FakeWebSocket())
        started = manager.start('ignored', 5)
        with self.assertRaises(AssessmentError):
            manager.get(started['session_id'], 4)
        with self.assertRaises(AssessmentError):
            manager.get('another', 5)
        with self.assertRaises(AssessmentError):
            manager.start('ignored', 5)
        manager.cancel()

    def test_endpoint_rejects_unapproved_model_and_location(self):
        with self.assertRaises(AssessmentError):
            GoogleConnection('rewind-514904', 'evil.com')
        with self.assertRaises(AssessmentError):
            GoogleConnection('rewind-514904', model='gemini-3.5-flash')


if __name__ == '__main__':
    unittest.main()
