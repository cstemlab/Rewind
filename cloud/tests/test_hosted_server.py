"""HTTP/in-memory tests. All provider operations are replaced; no real keys."""
import base64
import http.client
import io
import json
from pathlib import Path
import secrets
import struct
import sys
import threading
import time
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'service'))
import hosted_server as hosted
from assess import AssessmentError

KEY = 'mock-provider-key-never-valid'
CODE = 'mock-access-code-never-published'


def wav(silent=False):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\0\0' * 16000 if silent else b''.join(struct.pack('<h', 2000 if n % 2 else -2000) for n in range(16000)))
    return output.getvalue()


class FakeLive:
    def __init__(self):
        self.ident = None
        self.closed = False

    def start(self, key, generation):
        self.ident = secrets.token_urlsafe(24)
        return {'session_id': self.ident, 'state': 'ready'}

    def get(self, ident, generation):
        if not self.ident or ident != self.ident:
            raise AssessmentError('live_session', 'Session not found.')
        return self

    def append(self, sequence, data):
        return {'next_seq': sequence + 1}

    def events(self, after):
        return {'events': [{'text': '我', 'seq': 1}], 'state': 'listening'}

    def stop(self, commit):
        self.closed = True
        return {'state': 'closed'}

    def cancel(self, reason):
        self.closed = True


class HostedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.coach_calls = []
        self.translator_gate = threading.Event()
        self.translator_gate.set()

        def coach(data, target, key):
            self.coach_calls.append(target)
            return {'reference': target, 'provider': 'openai', 'note': KEY, 'groups': []}

        def translator(text, title, mode, key):
            self.translator_gate.wait(2)
            return {'text': text, 'title': title, 'mode': mode}

        self.app = hosted.App(KEY, CODE, coach=coach, live_factory=FakeLive,
            creator_factory=lambda gate: hosted.HostedCreatorManager(gate, translator=translator))
        self.server = hosted.HostedServer(('127.0.0.1', 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.translator_gate.set()
        self.app.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, body=None, token=None, origin=hosted.ALLOWED_ORIGIN, extra=None):
        headers = {'Origin': origin} if origin else {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        if token:
            headers['Authorization'] = 'Bearer ' + token
        headers.update(extra or {})
        client = http.client.HTTPConnection(*self.server.server_address, timeout=4)
        try:
            client.request(method, path, payload, headers)
            response = client.getresponse()
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            client.close()

    def session(self):
        status, body, _ = self.request('POST', '/api/session', {'access_code': CODE})
        self.assertEqual(status, 200)
        return body['token']

    def recording(self, silent=False):
        return {'provider': 'openai', 'audio': base64.b64encode(wav(silent)).decode(), 'text': '我今日', 'extension': '.wav'}

    def test_health_and_public_status_expose_no_key(self):
        self.assertEqual(self.request('GET', '/health', origin=None)[:2], (200, {'ok': True}))
        self.assertEqual(self.request('GET', '/healthz', origin=None)[:2], (200, {'ok': True}))
        status, body, _ = self.request('GET', '/api/status')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'configured': False, 'mode': 'hosted-trial', 'requires_access_code': True, 'supported_providers': ['openai']})
        self.assertNotIn(KEY, json.dumps(body))

    def test_exact_cors_preflight(self):
        status, _, headers = self.request('OPTIONS', '/api/session', extra={
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Access-Control-Allow-Origin'], hosted.ALLOWED_ORIGIN)
        self.assertNotIn('Access-Control-Allow-Credentials', headers)
        for origin in ('https://evil.example', hosted.ALLOWED_ORIGIN + '.evil.example', 'null', None):
            status, _, headers = self.request('POST', '/api/session', {'access_code': CODE}, origin=origin)
            self.assertEqual(status, 403)
            self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_disallowed_preflight_headers(self):
        self.assertEqual(self.request('OPTIONS', '/api/status', extra={
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'X-Provider-Key'})[0], 403)

    def test_wrong_code_and_unauthenticated_calls(self):
        self.assertEqual(self.request('POST', '/api/session', {'access_code': 'wrong'})[0], 403)
        status, body, _ = self.request('POST', '/api/assess-recording', self.recording())
        self.assertEqual((status, body['code']), (401, 'session_required'))
        self.assertEqual(self.coach_calls, [])

    def test_owner_configuration_routes_are_unavailable(self):
        token = self.session()
        for route in ('/api/config', '/api/disconnect'):
            self.assertEqual(self.request('POST', route, {'key': 'malicious-change'}, token)[0], 404)
        self.assertEqual(self.app.api_key, KEY)

    def test_authorized_status_and_secrets_are_redacted(self):
        token = self.session()
        status, body, _ = self.request('GET', '/api/status', token=token)
        self.assertEqual(status, 200)
        self.assertTrue(body['configured'])
        self.assertFalse(body['connection_verified'])
        self.assertTrue(body['creator']['available'])
        status, body, _ = self.request('POST', '/api/assess-recording', self.recording(), token)
        self.assertEqual(status, 200)
        self.assertNotIn(KEY, json.dumps(body))
        self.assertTrue(self.request('GET', '/api/status', token=token)[1]['connection_verified'])

    def test_assessment_state_and_lock_are_per_visitor(self):
        first, second = self.session(), self.session()
        first_visitor = self.app.authenticate('Bearer ' + first)
        first_visitor.inflight.acquire()
        try:
            self.assertEqual(self.request('POST', '/api/assess-recording', self.recording(), first)[0], 409)
            self.assertEqual(self.request('POST', '/api/assess-recording', self.recording(), second)[0], 200)
        finally:
            first_visitor.inflight.release()
        self.assertFalse(self.request('GET', '/api/status', token=first)[1]['connection_verified'])

    def test_silence_never_calls_paid_provider(self):
        status, body, _ = self.request('POST', '/api/assess-recording', self.recording(True), self.session())
        self.assertEqual(status, 200)
        self.assertEqual(body['status'], 'no_speech')
        self.assertEqual(self.coach_calls, [])

    def test_live_ids_cannot_cross_visitors(self):
        first, second = self.session(), self.session()
        one = self.request('POST', '/api/live/start', {'provider': 'openai'}, first)[1]
        two = self.request('POST', '/api/live/start', {'provider': 'openai'}, second)[1]
        self.assertNotEqual(one['session_id'], two['session_id'])
        body = {'provider': 'openai', 'session_id': one['session_id'], 'after': 0}
        self.assertEqual(self.request('POST', '/api/live/events', body, second)[0], 409)
        self.assertEqual(self.request('POST', '/api/live/events', body, first)[0], 200)

    def test_creator_job_ids_cannot_cross_visitors(self):
        first, second = self.session(), self.session()
        body = {'text': '我今日去學校。', 'title': '問候', 'mode': 'beginner', 'consent': True}
        status, job, _ = self.request('POST', '/api/creator/translate', body, first)
        self.assertEqual(status, 200)
        self.assertEqual(self.request('POST', '/api/creator/status', {'job_id': job['job_id']}, second)[0], 409)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status, result, _ = self.request('POST', '/api/creator/status', {'job_id': job['job_id']}, first)
            if result['state'] == 'completed':
                break
            time.sleep(.01)
        self.assertEqual(result['result']['draft']['text'], body['text'])

    def test_global_creator_slot_stays_reserved_after_cancel(self):
        first, second = self.session(), self.session()
        self.translator_gate.clear()
        body = {'text': '我今日去學校。', 'mode': 'beginner', 'consent': True}
        job = self.request('POST', '/api/creator/translate', body, first)[1]
        self.assertEqual(self.request('POST', '/api/creator/cancel', {'job_id': job['job_id']}, first)[0], 200)
        self.assertEqual(self.request('POST', '/api/creator/translate', body, second)[0], 409)
        self.translator_gate.set()

    def test_text_extract_is_scoped_and_offline(self):
        body = {'filename': 'test.txt', 'data': base64.b64encode('我今日。'.encode()).decode()}
        status, result, _ = self.request('POST', '/api/creator/extract', body, self.session())
        self.assertEqual(status, 200)
        self.assertEqual(result['text'], '我今日。')
        self.assertEqual(self.coach_calls, [])

    def test_content_length_cap_rejects_before_read(self):
        token = self.session()
        status, result, _ = self.request('POST', '/api/assess-recording', {}, token,
            extra={'Content-Length': str(hosted.MAX_BODY + 1)})
        self.assertEqual((status, result['code']), (413, 'body_size'))
        self.assertEqual(self.coach_calls, [])

    def test_invalid_json_body_shape(self):
        self.assertEqual(self.request('POST', '/api/assess-recording', ['not-an-object'], self.session())[0], 400)

    def test_per_session_and_global_paid_limits(self):
        first, second = self.session(), self.session()
        one = self.app.authenticate('Bearer ' + first)
        for _ in range(5):
            one.assessments.take()
        self.assertEqual(self.request('POST', '/api/assess-recording', self.recording(), first)[0], 429)
        self.assertEqual(self.request('POST', '/api/assess-recording', self.recording(), second)[0], 200)
        while len(self.app.assessments.times) < self.app.assessments.limit:
            self.app.assessments.take()
        self.assertEqual(self.request('POST', '/api/assess-recording', self.recording(), second)[0], 429)

    def test_end_session_only_closes_its_own_manager(self):
        first, second = self.session(), self.session()
        one = self.app.authenticate('Bearer ' + first)
        two = self.app.authenticate('Bearer ' + second)
        self.assertEqual(self.request('POST', '/api/session/end', {}, first)[0], 200)
        self.assertTrue(one.live.closed)
        self.assertFalse(two.live.closed)
        self.assertEqual(self.request('GET', '/api/status', token=first)[0], 401)
        self.assertEqual(self.request('GET', '/api/status', token=second)[0], 200)

    def test_idle_expiry_and_absolute_expiry(self):
        for field, age in (('touched', hosted.IDLE_TTL + 2), ('created', hosted.ABSOLUTE_TTL + 2)):
            token = self.session()
            visitor = self.app.authenticate('Bearer ' + token)
            setattr(visitor, field, time.monotonic() - age)
            status, body, _ = self.request('GET', '/api/status', token=token)
            self.assertEqual((status, body['code']), (401, 'session_expired'))
            self.assertTrue(visitor.live.closed)

    def test_completed_result_expiry_is_bounded(self):
        token = self.session()
        visitor = self.app.authenticate('Bearer ' + token)
        visitor.creator.jobs['expired'] = {'state': 'completed', 'updated': time.monotonic() - 301}
        self.app.prune()
        self.assertEqual(visitor.creator.jobs, {})

    def test_session_capacity_is_bounded(self):
        for _ in range(hosted.MAX_SESSIONS):
            self.session()
        self.assertEqual(self.request('POST', '/api/session', {'access_code': CODE})[0], 429)

    def test_visitor_can_choose_only_configured_provider(self):
        self.app.providers['gemini'] = hosted.Runtime('gemini', 'mock-google-adc', coach=lambda *_: {'provider': 'gemini'},
            model='mock-gemini-model', live_factory=FakeLive, creator_factory=self.app.providers['openai'].creator_factory)
        first, second = self.session(), self.session()
        original = self.app.authenticate('Bearer ' + first)
        original.assessments.take()
        status, body, _ = self.request('POST', '/api/session/provider', {'provider': 'gemini'}, first)
        self.assertEqual(status, 200)
        self.assertEqual(body['provider'], 'gemini')
        self.assertEqual(body['model'], 'mock-gemini-model')
        self.assertEqual(body['supported_providers'], ['openai', 'gemini'])
        self.assertFalse(body['live_transcription']['available'])
        self.assertTrue(original.live.closed)
        replacement = self.app.authenticate('Bearer ' + first)
        self.assertEqual(replacement.created, original.created)
        self.assertIs(replacement.assessments, original.assessments)
        self.assertEqual(self.request('GET', '/api/status', token=second)[1]['provider'], 'openai')
        self.assertEqual(self.request('POST', '/api/session/provider', {'provider': 'unknown'}, first)[0], 400)
        self.assertEqual(self.request('POST', '/api/live/start', {'provider': 'gemini'}, first)[1]['code'], 'live_unavailable')
        self.assertEqual(self.request('POST', '/api/assess-recording', self.recording(), first)[1]['code'], 'invalid_provider')
        recording = self.recording()
        recording['provider'] = 'gemini'
        self.assertEqual(self.request('POST', '/api/assess-recording', recording, first)[1]['provider'], 'gemini')

    def test_live_model_and_capabilities_follow_runtime(self):
        self.app.providers['gemini'] = hosted.Runtime('gemini', 'mock-google-adc', live_factory=FakeLive,
            model='mock-gemini', supports_live=True, live_model='mock-google-live')
        token = self.session()
        body = self.request('POST', '/api/session/provider', {'provider': 'gemini'}, token)[1]
        self.assertEqual(body['live_transcription']['model'], 'mock-google-live')
        self.assertTrue(body['live_transcription']['available'])

    def test_google_error_mapping(self):
        self.assertEqual(hosted.error_status('google_http_429'), 429)
        self.assertEqual(hosted.error_status('google_auth'), 503)
        self.assertEqual(hosted.error_status('google_http_403'), 502)

    def test_google_metadata_decoration_without_openai_label(self):
        from google_provider import GoogleProvider
        google = GoogleProvider(project='mock-project', transport=lambda *_: {})
        session = {'source': {'text_model': 'openai', 'audio_model': 'openai', 'voice': 'alloy'}}
        result = google.decorate_session(session)
        self.assertEqual(result['source']['provider'], 'gemini')
        self.assertNotIn('openai', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
