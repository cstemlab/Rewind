"""Owner-authorized live smoke test; small synthetic script, no user audio.

Cloud Shell only: reads the invitation secret through gcloud into process memory,
never stdout or arguments. Calls are bounded but all/live stages incur usage.
It does not discover, print or change any provider key. Nothing is saved to disk.
"""
import argparse
import array
import base64
import http.client
import io
import json
import math
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import wave

ORIGIN = 'https://cstemlab.github.io'
TARGET = '早晨，我想學好廣東話。'


class SmokeHTTPClient:
    """One persistent HTTPS connection per thread; never retry paid requests."""
    def __init__(self, hostname, connection_factory=http.client.HTTPSConnection):
        self.hostname = hostname
        self.connection_factory = connection_factory
        self.token = ''
        self.local = threading.local()
        self.connections = []
        self.lock = threading.Lock()

    def request(self, method, route, data=None, *, expected=200, authenticated=True, origin=ORIGIN):
        timeout = 15 if route.startswith('/api/live/') else 180
        if not hasattr(self.local, 'connection'):
            self.local.connection = self.connection_factory(self.hostname, timeout=timeout)
            with self.lock:
                self.connections.append(self.local.connection)
        connection = self.local.connection
        connection.timeout = timeout
        if connection.sock is not None:
            connection.sock.settimeout(timeout)
        headers = {'Origin': origin}
        if self.token and authenticated:
            headers['Authorization'] = 'Bearer ' + self.token
        payload = None
        if data is not None:
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        try:
            connection.request(method, route, body=payload, headers=headers)
            response = connection.getresponse()
            status, raw = response.status, response.read(2_000_001)
        except Exception as exc:
            raise RuntimeError(f'{route}: transport failed ({type(exc).__name__}); request not retried.') from None
        if len(raw) > 2_000_000:
            raise RuntimeError('Smoke response exceeded its small-sample bound.')
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            raise RuntimeError(f'{route}: HTTP {status}, non-JSON response; gateway or route must be checked.') from None
        if status != expected:
            code = body.get('code', 'unknown') if isinstance(body, dict) else 'unknown'
            code = code if re.fullmatch(r'[a-zA-Z0-9_]{1,80}', str(code)) else 'unknown'
            raise RuntimeError(f'{route}: HTTP {status}, code={code}')
        return body

    def close(self):
        self.token = ''
        with self.lock:
            connections, self.connections = self.connections, []
        for connection in connections:
            connection.close()


def live_smoke(request, provider, audio, *, poll_interval=.2, final_timeout=15, emit=print):
    """Independent polling and paced audio, matching the browser relay shape.

    Sequential new-TLS audio+poll requests stretched a 2.845s fixture beyond the
    service's correct 25s wall limit. Persistent per-thread connections avoid
    that harness artifact without weakening any deployed recording limits.
    """
    with wave.open(io.BytesIO(audio), 'rb') as stream:
        if stream.getframerate() != 24000 or stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise RuntimeError('Smoke live audio must be 24kHz mono PCM16.')
        frames = stream.getnframes()
        pcm = stream.readframes(frames)
    if not 0 < len(pcm) <= 15 * 24000 * 2 or len(pcm) != frames * 2:
        raise RuntimeError('Smoke live clip is empty, truncated or too long.')
    live = request('POST', '/api/live/start', {'provider': provider})
    ident = live['session_id']
    stop_poll, completed, stopping = threading.Event(), threading.Event(), threading.Event()
    observed = {'cursor': 0, 'heard': False, 'during_capture': False, 'final': False, 'state': 'listening'}
    failures = []
    base = {'provider': provider, 'session_id': ident}

    def poll():
        try:
            while not stop_poll.is_set():
                result = request('POST', '/api/live/events', {**base, 'after': observed['cursor']})
                if result.get('session_id') != ident or type(result.get('last_seq')) is not int:
                    raise RuntimeError('invalid_live_events')
                observed['cursor'] = result['last_seq']
                observed['state'] = result.get('state', 'unknown')
                for event in result.get('events', []):
                    if event.get('type') == 'transcript':
                        heard = bool(event.get('text'))
                        observed['heard'] |= heard
                        observed['during_capture'] |= heard and not stopping.is_set()
                        observed['final'] |= bool(event.get('final')) and heard
                    elif event.get('type') == 'error':
                        code = event.get('code', 'unknown')
                        code = code if isinstance(code, str) and re.fullmatch(r'[a-zA-Z0-9_]{1,80}', code) else 'unknown'
                        failures.append('Hosted live provider error: ' + code)
                if observed['state'] in ('closed', 'error') or failures:
                    return
                stop_poll.wait(poll_interval)
        except Exception as exc:
            # Never interpolate exception payloads, which may contain a header.
            failures.append('Hosted live polling failed (' + type(exc).__name__ + ').')
        finally:
            completed.set()

    worker = threading.Thread(target=poll, name='rewind-smoke-live-poll', daemon=True)
    started = time.monotonic()
    worker.start()
    try:
        for sequence, offset in enumerate(range(0, len(pcm), 12000)):
            if failures:
                raise RuntimeError(failures[0])
            if completed.is_set():
                raise RuntimeError('Hosted live stream ended before all fixture chunks were sent.')
            delay = started + offset / 48000 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            result = request('POST', '/api/live/audio', {**base, 'seq': sequence,
                'audio': base64.b64encode(pcm[offset:offset+12000]).decode('ascii')})
            if result.get('accepted_seq') != sequence or result.get('next_seq') != sequence + 1:
                raise RuntimeError('Hosted live audio sequence was not acknowledged.')
        stopping.set()
        request('POST', '/api/live/stop', {**base, 'commit': True})
        if not completed.wait(final_timeout):
            raise RuntimeError('Hosted live final response exceeded the smoke deadline.')
        if failures:
            raise RuntimeError(failures[0])
        if observed['state'] != 'closed' or not observed['final']:
            raise RuntimeError('Hosted live stream did not finish with a final transcript.')
        emit('live: final transcript received; during capture=' + str(observed['during_capture']))
        return {key: observed[key] for key in ('during_capture', 'final', 'state')}
    finally:
        stop_poll.set()
        worker.join(16)
        try:
            request('POST', '/api/live/cancel', base)
        except Exception:
            pass
        if worker.is_alive():
            raise RuntimeError('Hosted live polling did not stop within its bounded request timeout.')


def assessment_wav(audio):
    """Match the browser batch contract: mono PCM16 WAV at 16 kHz.

    Narration/live use 24 kHz. Resample a separate copy using the same bounded
    sample-window averaging strategy as speech.js pcmWav; never change the live
    source or loosen the server's strict recording validator.
    """
    with wave.open(io.BytesIO(audio), 'rb') as stream:
        rate, count = stream.getframerate(), stream.getnframes()
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getcomptype() != 'NONE':
            raise RuntimeError('Smoke assessment source must be mono PCM16 WAV.')
        if rate not in (16000, 24000, 44100, 48000) or not 0 < count <= rate * 15:
            raise RuntimeError('Smoke assessment source rate/duration is outside its bound.')
        raw = stream.readframes(count)
    if len(raw) != count * 2:
        raise RuntimeError('Smoke assessment source is truncated.')
    samples = array.array('h')
    samples.frombytes(raw)
    if sys.byteorder != 'little':
        samples.byteswap()
    output_samples = array.array('h')
    target_count = count * 16000 // rate
    for index in range(target_count):
        start = index * rate // 16000
        end = min(count, max(start + 1, (index + 1) * rate // 16000))
        value = math.floor(sum(samples[start:end]) / (end - start) + .5)
        output_samples.append(max(-32768, min(32767, value)))
    if sys.byteorder != 'little':
        output_samples.byteswap()
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(output_samples.tobytes())
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--project', default='rewind-514904')
    parser.add_argument('--secret-version', default='1')
    parser.add_argument('--stage', choices=('connectivity', 'all', 'live', 'assessment'), default='connectivity')
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.run.app') or parsed.username or parsed.password or parsed.port or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise SystemExit('Use the verified bare HTTPS Cloud Run service URL.')
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', args.project) or not re.fullmatch(r'[1-9][0-9]*', args.secret_version):
        raise SystemExit('Invalid project or secret version.')
    client = SmokeHTTPClient(parsed.hostname)
    request = client.request
    token = ''

    def job(route, payload):
        created = request('POST', route, payload)
        ident = created['job_id']
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            result = request('POST', '/api/creator/status', {'job_id': ident})
            if result['state'] == 'completed':
                return result['result']
            if result['state'] in ('failed', 'cancelled'):
                raise RuntimeError('Creator returned terminal failure; no source or provider reply printed.')
            time.sleep(1)
        request('POST', '/api/creator/cancel', {'job_id': ident})
        raise RuntimeError('Creator exceeded the smoke-test time limit.')

    def assess_test(provider, audio):
        batch_audio = assessment_wav(audio)
        assessment = request('POST', '/api/assess-recording', {'provider': provider, 'text': TARGET,
            'extension': '.wav', 'audio': base64.b64encode(batch_audio).decode('ascii')})
        assert assessment['provider'] == provider and assessment['reference'] == TARGET
        assert request('GET', '/api/status')['connection_verified'] is True
        print('hosted recorded-audio assessment: completed (16 kHz WAV)', flush=True)

    try:
        assert request('GET', '/health', authenticated=False)['ok'] is True
        assert request('GET', '/api/status', authenticated=False)['configured'] is False
        request('POST', '/api/session', {'access_code': 'deliberately-invalid'}, authenticated=False, expected=403)
        request('POST', '/api/assess-recording', {}, authenticated=False, expected=401)
        request('GET', '/api/status', authenticated=False, origin='https://invalid.example', expected=403)
        executable = shutil.which('gcloud')
        if not executable:
            raise RuntimeError('gcloud not available; run from authorized Cloud Shell.')
        value = subprocess.run([executable, 'secrets', 'versions', 'access', args.secret_version,
            '--secret=rewind-demo-access', '--project=' + args.project, '--quiet'],
            capture_output=True, check=True).stdout.decode('utf-8').strip()
        token = request('POST', '/api/session', {'access_code': value}, authenticated=False)['token']
        client.token = token
        value = ''
        status = request('GET', '/api/status')
        assert status['configured'] is True and status['mode'] == 'hosted-trial'
        provider = status['provider']
        assert provider in ('gemini', 'openai')
        request('POST', '/api/config', {}, expected=404)
        request('POST', '/api/disconnect', {}, expected=404)
        assert request('POST', '/api/session/provider', {'provider': provider})['provider'] == provider
        print('connectivity/auth/CORS: passed; provider=' + provider, flush=True)
        if args.stage == 'all':
            draft = job('/api/creator/translate', {'text': 'Good morning. I want to learn Cantonese.',
                'title': 'Rewind service test', 'mode': 'beginner', 'consent': True})['draft']
            assert isinstance(draft['text'], str) and 0 < len(draft['text']) < 200
            print('translation: completed', flush=True)
            session = job('/api/creator/render', {'draft': {'text': TARGET, 'title': 'Rewind service test', 'mode': 'beginner'}, 'consent': True})['session']
            assert session['source']['reviewed_text'] == TARGET
            assert session['source'].get('provider', provider) == provider
            audio = base64.b64decode(session['audio']['base64'], validate=True)
            assert 0 < session['duration'] < 15
            print('reviewed-text narration/session: completed', flush=True)
            assess_test(provider, audio)
            if status['live_transcription']['available']:
                live_smoke(request, provider, audio)
        elif args.stage in ('live', 'assessment'):
            # This dedicated stage synthesizes only the public test sentence.
            sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent / 'service'))
            from google_provider import GoogleProvider
            clip = GoogleProvider(args.project).narrate(TARGET)
            output = io.BytesIO()
            with wave.open(output, 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(clip['rate'])
                stream.writeframes(clip['pcm'])
            if args.stage == 'live':
                live_smoke(request, provider, output.getvalue())
            else:
                assess_test(provider, output.getvalue())
        print('Smoke stage passed. This verifies connectivity, not pronunciation-grading accuracy.', flush=True)
    finally:
        if token:
            try:
                request('POST', '/api/session/end', {})
            except Exception:
                print('Session cleanup unavailable; it will expire automatically.', flush=True)
            token = ''
        client.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            print('Smoke test failed: ' + str(exc), file=sys.stderr)
        else:
            print('Smoke test failed (' + type(exc).__name__ + '); no provider payload or credentials printed.', file=sys.stderr)
        raise SystemExit(1)
