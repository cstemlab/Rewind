"""Voice routing, provenance and fixed-preview limits; all audio is synthetic."""
import base64
import io
import struct
import threading
import time
import unittest
import wave
from unittest.mock import patch

import creator
from assess import AssessmentError
from google_provider import GoogleProvider, DEFAULT_VOICE, VOICES
import hosted_server as hosted
import test_hosted_server as hosted_tests
KEY = hosted_tests.KEY

DRAFT = {'title': '試聽', 'text': '你好。', 'mode': 'faithful'}
AOEDE = 'yue-HK-Chirp3-HD-Aoede'
KORE = 'yue-HK-Chirp3-HD-Kore'


def clip(voice, seconds=.5):
    value = 1000 if voice in (AOEDE, 'alloy') else 2000
    return {'voice': voice, 'rate': 24000, 'pcm': struct.pack('<h', value) * int(24000 * seconds)}


def encoded_wave(voice):
    return creator.preview_audio(clip(voice), voice)['audio']['base64']


def terminal(manager, ident):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        result = manager.status(ident, 0)
        if result['state'] in ('failed', 'completed', 'cancelled'):
            return result
        time.sleep(.005)
    raise AssertionError('Creator job did not finish')


class VoiceRoutingTests(unittest.TestCase):
    def test_google_catalog_default_and_payloads_are_distinct(self):
        calls = []
        def transport(url, payload, limit):
            calls.append(payload)
            return {'audioContent': encoded_wave(payload['voice']['name'])}
        google = GoogleProvider(project='mock-project', transport=transport)
        one, two = google.narrate('你好。', voice=AOEDE), google.narrate('你好。', voice=KORE)
        self.assertEqual([call['voice']['name'] for call in calls], [AOEDE, KORE])
        self.assertNotEqual(one['pcm'], two['pcm'])
        self.assertEqual(one['voice'], AOEDE)
        self.assertEqual(two['voice'], KORE)
        self.assertEqual(google.voice, DEFAULT_VOICE)
        catalog = google.capabilities()
        self.assertEqual(catalog['default_voice'], AOEDE)
        self.assertEqual(len(catalog['voices']), 10)
        self.assertTrue(catalog['voice_selection'] and catalog['voice_preview'])
        self.assertEqual({v['id'] for v in catalog['voices']}, {v['id'] for v in VOICES})

    def test_invalid_google_voice_rejected_before_network(self):
        calls = []
        google = GoogleProvider(project='mock-project', transport=lambda *a: calls.append(a))
        for voice in ('', 'alloy', 'cmn-CN-Standard-A', 'yue-HK-Chirp3-HD-Invented', [], {}):
            with self.subTest(voice=voice), self.assertRaises(AssessmentError):
                google.narrate('你好。', voice=voice)
        self.assertEqual(calls, [])

    def test_openai_choice_reaches_audio_request(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'audio': {
            'data': encoded_wave('coral'), 'transcript': '你好。'}}}]}
        with patch('creator._request', return_value=response) as request:
            result = creator.narration('你好。', KEY, 'coral')
        self.assertEqual(request.call_args.args[0]['audio']['voice'], 'coral')
        self.assertEqual(result['voice'], 'coral')
        self.assertIn('coral', [v['id'] for v in creator.capabilities(True)['voices']])
        with patch('creator._request') as request, self.assertRaises(AssessmentError):
            creator.narration('你好。', KEY, AOEDE)
        request.assert_not_called()

    def test_parallel_jobs_capture_separate_voices_and_metadata(self):
        barrier = threading.Barrier(2)
        def transport(url, payload, limit):
            barrier.wait(2)
            return {'audioContent': encoded_wave(payload['voice']['name'])}
        google = GoogleProvider(project='mock-project', transport=transport)
        plan = creator.validate_plan({'sentences': [{'section': '試聽', 'text': '你好。',
            'readings': ['nei5', 'hou2'], 'parts': ['你好。']}]}, DRAFT['text'])
        managers = [creator.CreatorManager(planner=lambda *a: plan, synthesizer=google.narrate,
                                          voice_selector=google.select_voice) for _ in range(2)]
        jobs = [manager.start('render', {'draft': {**DRAFT, 'voice': voice}, 'consent': True}, KEY, 0)
                for manager, voice in zip(managers, (AOEDE, KORE))]
        results = [terminal(manager, job['job_id']) for manager, job in zip(managers, jobs)]
        self.assertEqual([result['state'] for result in results], ['completed', 'completed'])
        sessions = [google.decorate_session(result['result']['session']) for result in results]
        self.assertEqual([session['source']['voice'] for session in sessions], [AOEDE, KORE])
        self.assertNotEqual(sessions[0]['audio']['sha256'], sessions[1]['audio']['sha256'])
        self.assertEqual(google.voice, AOEDE)
        self.assertEqual([session['source']['reviewed_text'] for session in sessions], ['你好。', '你好。'])

    def test_invalid_render_choice_never_plans_or_synthesizes(self):
        calls = []
        manager = creator.CreatorManager(planner=lambda *a: calls.append(a), synthesizer=lambda *a: calls.append(a))
        for voice in ('', AOEDE, None, [], {}):
            with self.subTest(voice=voice), self.assertRaises(AssessmentError):
                manager.start('render', {'draft': {**DRAFT, 'voice': voice}, 'consent': True}, KEY, 0)
        self.assertEqual(calls, [])
        self.assertEqual(manager.jobs, {})

    def test_preview_wrong_voice_or_oversized_clip_rejected(self):
        for sample in (clip(KORE), clip(AOEDE, 21)):
            with self.assertRaises(AssessmentError):
                creator.preview_audio(sample, AOEDE)


class VoiceHTTPTests(unittest.TestCase):
    request = hosted_tests.HostedHTTPTests.request
    session = hosted_tests.HostedHTTPTests.session
    tearDown = hosted_tests.HostedHTTPTests.tearDown

    def setUp(self):
        hosted_tests.HostedHTTPTests.setUp(self)
        self.preview_calls = []
        runtime = self.app.providers['openai']
        def synth(text, key, voice):
            self.preview_calls.append((text, voice))
            return clip(voice)
        runtime.preview_synthesizer = synth

    def preview(self, token=None, voice='alloy', **extra):
        return self.request('POST', '/api/creator/preview', {'voice': voice, 'consent': True, **extra}, token)

    def test_preview_requires_auth_origin_and_exact_bounded_body(self):
        self.assertEqual(self.preview()[0], 401)
        token = self.session()
        self.assertEqual(self.request('POST', '/api/creator/preview', {'voice': 'alloy', 'consent': True}, token,
                                      origin='https://evil.example')[0], 403)
        for body in ({'voice': 'alloy'}, {'voice': 'alloy', 'consent': False},
                     {'voice': 'alloy', 'consent': True, 'text': 'private script'}):
            self.assertEqual(self.request('POST', '/api/creator/preview', body, token)[0], 400)
        for voice in ('', AOEDE, None, [], {}):
            self.assertEqual(self.preview(token, voice)[0], 400)
        self.assertEqual(self.request('POST', '/api/creator/preview', {}, token,
                                      extra={'Content-Length': '4097'})[0], 413)
        self.assertEqual(self.preview_calls, [])

    def test_preview_fixed_text_cache_per_voice_shared_across_visitors(self):
        first, second = self.session(), self.session()
        one = self.preview(first)[1]
        self.assertEqual(self.preview(second)[1], one)
        other = self.preview(first, 'coral')[1]
        self.assertEqual(one['text'], creator.PREVIEW_TEXT)
        self.assertEqual(one['voice'], 'alloy')
        self.assertEqual(other['voice'], 'coral')
        self.assertNotEqual(one['audio']['sha256'], other['audio']['sha256'])
        self.assertEqual(self.preview_calls, [(creator.PREVIEW_TEXT, 'alloy'), (creator.PREVIEW_TEXT, 'coral')])
        with wave.open(io.BytesIO(base64.b64decode(one['audio']['base64']))) as stream:
            self.assertEqual(stream.getframerate(), 24000)
        self.assertEqual(len(self.app.preview_generations.times), 2)

    def test_google_http_render_preview_and_metadata_use_same_choice(self):
        calls = []
        def transport(url, payload, limit):
            calls.append(payload['voice']['name'])
            return {'audioContent': encoded_wave(payload['voice']['name'])}
        google = GoogleProvider(project='mock-project', transport=transport)
        plan = creator.validate_plan({'sentences': [{'section': '試聽', 'text': '你好。',
            'readings': ['nei5', 'hou2'], 'parts': ['你好。']}]}, DRAFT['text'])
        self.app.providers['gemini'] = hosted.Runtime('gemini', KEY, live_factory=hosted_tests.FakeLive,
            creator_factory=lambda gate: hosted.HostedCreatorManager(gate, planner=lambda *a: plan,
                synthesizer=google.narrate, voice_selector=google.select_voice),
            creator_capabilities=google.capabilities, decorate_session=google.decorate_session,
            voice_selector=google.select_voice, preview_synthesizer=google.narrate)
        token = self.session()
        status = self.request('POST', '/api/session/provider', {'provider': 'gemini'}, token)[1]
        self.assertEqual(status['creator']['default_voice'], AOEDE)
        self.assertEqual(self.preview(token, KORE)[1]['voice'], KORE)
        invalid = {'draft': {**DRAFT, 'voice': 'alloy'}, 'consent': True}
        self.assertEqual(self.request('POST', '/api/creator/render', invalid, token)[1]['code'], 'invalid_voice')
        self.assertEqual(calls, [KORE])
        sessions = []
        for voice in (AOEDE, KORE):
            body = {'draft': {**DRAFT, 'voice': voice}, 'consent': True}
            status, job, _ = self.request('POST', '/api/creator/render', body, token)
            self.assertEqual(status, 200)
            until = time.monotonic() + 2
            while time.monotonic() < until:
                status, result, _ = self.request('POST', '/api/creator/status', {'job_id': job['job_id']}, token)
                if result['state'] in ('completed', 'failed'):
                    break
                time.sleep(.005)
            self.assertEqual(result['state'], 'completed')
            sessions.append(result['result']['session'])
        self.assertEqual([s['source']['voice'] for s in sessions], [AOEDE, KORE])
        self.assertTrue(all(s['source']['provider'] == 'gemini' for s in sessions))
        self.assertNotEqual(sessions[0]['audio']['sha256'], sessions[1]['audio']['sha256'])
        self.assertEqual(calls, [KORE, AOEDE, KORE])

    def test_preview_cache_expires_and_failed_generation_is_not_cached(self):
        token = self.session()
        self.preview(token)
        key = ('openai', 'alloy')
        self.app.preview_cache[key] = (time.monotonic() - 3601, self.app.preview_cache[key][1])
        self.preview(token)
        self.assertEqual(len(self.preview_calls), 2)
        runtime = self.app.providers['openai']
        original = runtime.preview_synthesizer
        runtime.preview_synthesizer = lambda *a: clip('alloy')
        self.assertEqual(self.preview(token, 'coral')[1]['code'], 'voice_mismatch')
        self.assertNotIn(('openai', 'coral'), self.app.preview_cache)
        runtime.preview_synthesizer = original
        self.assertEqual(self.preview(token, 'coral')[0], 200)

    def test_preview_per_visitor_global_and_paid_miss_limits(self):
        first, second = self.session(), self.session()
        self.preview(first)
        one = self.app.authenticate('Bearer ' + first)
        one.voice_previews.limit = 1
        self.assertEqual(self.preview(first)[0], 429)
        self.assertEqual(self.preview(second)[0], 200)
        self.app.preview_generations.limit = 1
        self.assertEqual(self.preview(second, 'coral')[0], 429)
        self.assertEqual(len(self.preview_calls), 1)
        self.assertEqual(self.preview(second)[0], 200)
        self.app.voice_previews.limit = len(self.app.voice_previews.times)
        self.assertEqual(self.preview(second)[0], 429)

    def test_preview_fill_serializes_and_releases_after_completion(self):
        token = self.session()
        runtime = self.app.providers['openai']
        entered, released = threading.Event(), threading.Event()
        def synth(text, key, voice):
            entered.set()
            released.wait(2)
            self.preview_calls.append((text, voice))
            return clip(voice)
        runtime.preview_synthesizer = synth
        results = []
        worker = threading.Thread(target=lambda: results.append(self.preview(token)), daemon=True)
        worker.start()
        self.assertTrue(entered.wait(1))
        try:
            self.assertEqual(self.preview(token)[0], 409)
        finally:
            released.set()
            worker.join(2)
        self.assertEqual(results[0][0], 200)
        self.assertEqual(self.preview(token)[0], 200)
        self.assertEqual(len(self.preview_calls), 1)


if __name__ == '__main__':
    unittest.main()
