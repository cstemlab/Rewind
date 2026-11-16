"""Permanent live smoke uses persistent per-thread HTTP without serial polling."""
import contextlib
import io
import json
import threading
import time
import unittest
from test_smoke_audio import remote_smoke, source_wav

SECRET = 'mock-secret-never-log-this-value'


class FakeResponse:
    status = 200

    def read(self, _limit):
        return b'{"ok":true}'


class FakeConnection:
    def __init__(self, hostname, timeout):
        self.hostname, self.timeout = hostname, timeout
        self.sock = None
        self.calls = []
        self.closed = False
        self.fail = False

    def request(self, method, route, body, headers):
        if self.fail:
            raise OSError(SECRET)
        self.calls.append((method, route, headers))

    def getresponse(self):
        return FakeResponse()

    def close(self):
        self.closed = True


class FakeLive:
    def __init__(self, fail_audio=False, fail_poll=False, never_final=False):
        self.lock = threading.Lock()
        self.audio = []
        self.stopped = self.cancelled = False
        self.poll_threads = set()
        self.fail_audio, self.fail_poll, self.never_final = fail_audio, fail_poll, never_final
        self.ident = 'mock-private-session-id'
        self.stop_count = 0

    def request(self, method, route, body):
        with self.lock:
            if route.endswith('/start'):
                return {'session_id': self.ident, 'state': 'listening', 'sample_rate': 24000}
            if route.endswith('/audio'):
                if self.fail_audio and body['seq'] == 1:
                    raise RuntimeError('mock transport failure')
                self.audio.append(body['seq'])
                return {'accepted_seq': body['seq'], 'next_seq': body['seq'] + 1}
            if route.endswith('/events'):
                self.poll_threads.add(threading.get_ident())
                if self.fail_poll:
                    raise OSError(SECRET)
                if self.stopped and not self.never_final:
                    return {'session_id': self.ident, 'state': 'closed', 'last_seq': 2,
                        'events': [{'type': 'transcript', 'seq': 2, 'text': SECRET, 'final': True}]}
                return {'session_id': self.ident, 'state': 'listening', 'last_seq': 1 if self.audio else 0,
                    'events': [{'type': 'transcript', 'seq': 1, 'text': SECRET, 'final': False}] if self.audio else []}
            if route.endswith('/stop'):
                self.stopped = True
                self.stop_count += 1
                return {'state': 'finishing'}
            if route.endswith('/cancel'):
                self.cancelled = True
                return {'state': 'closed'}
        raise AssertionError('Unexpected route')


class SmokeTransportTests(unittest.TestCase):
    def test_connection_reuse_is_per_thread_and_cleanup_clears_token(self):
        made = []

        def factory(hostname, timeout):
            connection = FakeConnection(hostname, timeout)
            made.append(connection)
            return connection

        client = remote_smoke.SmokeHTTPClient('example.run.app', factory)
        client.token = SECRET
        client.request('GET', '/api/status')
        client.request('GET', '/api/status')
        self.assertEqual(len(made), 1)
        worker = threading.Thread(target=lambda: client.request('POST', '/api/live/events', {}))
        worker.start()
        worker.join(1)
        self.assertEqual(len(made), 2)
        self.assertEqual(made[1].timeout, 15)
        self.assertEqual(len(made[0].calls), 2)
        client.close()
        self.assertEqual(client.token, '')
        self.assertTrue(all(connection.closed for connection in made))

    def test_transport_failure_is_not_retried_or_logged_with_secret(self):
        connection = FakeConnection('example.run.app', 15)
        connection.fail = True
        client = remote_smoke.SmokeHTTPClient('example.run.app', lambda *_args, **_kwargs: connection)
        client.token = SECRET
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(RuntimeError) as caught:
                client.request('POST', '/api/live/audio', {})
        self.assertNotIn(SECRET, str(caught.exception) + output.getvalue())
        self.assertIn('not retried', str(caught.exception))
        client.close()

    def assert_no_live_thread(self):
        self.assertFalse(any(thread.name == 'rewind-smoke-live-poll' for thread in threading.enumerate()))

    def test_audio_sequence_polling_and_final_are_independent(self):
        fake = FakeLive()
        messages = []
        result = remote_smoke.live_smoke(fake.request, 'gemini', source_wav(seconds=.3),
            poll_interval=.005, final_timeout=.2, emit=messages.append)
        self.assertEqual(fake.audio, [0, 1])
        self.assertEqual(fake.stop_count, 1)
        self.assertTrue(fake.cancelled)
        self.assertEqual(result, {'during_capture': True, 'final': True, 'state': 'closed'})
        self.assertNotIn(threading.get_ident(), fake.poll_threads)
        self.assertNotIn(SECRET, ''.join(messages))
        self.assertNotIn(fake.ident, ''.join(messages))
        self.assert_no_live_thread()

    def test_audio_failure_stops_polling_and_cancels(self):
        fake = FakeLive(fail_audio=True)
        with self.assertRaises(RuntimeError):
            remote_smoke.live_smoke(fake.request, 'gemini', source_wav(seconds=.3), poll_interval=.005, final_timeout=.1)
        self.assertTrue(fake.cancelled)
        self.assertEqual(fake.stop_count, 0)
        self.assert_no_live_thread()

    def test_poll_failure_hides_payload_and_cleans_up(self):
        fake = FakeLive(fail_poll=True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(RuntimeError) as caught:
                remote_smoke.live_smoke(fake.request, 'gemini', source_wav(seconds=.3), poll_interval=.005, final_timeout=.1)
        self.assertNotIn(SECRET, str(caught.exception) + output.getvalue())
        self.assertTrue(fake.cancelled)
        self.assert_no_live_thread()

    def test_missing_final_has_bounded_wait_and_cleanup(self):
        fake = FakeLive(never_final=True)
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            remote_smoke.live_smoke(fake.request, 'gemini', source_wav(seconds=.1), poll_interval=.005, final_timeout=.03)
        self.assertLess(time.monotonic() - started, .5)
        self.assertTrue(fake.cancelled)
        self.assert_no_live_thread()
