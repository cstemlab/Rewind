"""Small, owner-authorized Cantonese voice smoke test for Cloud Shell.

Only fixed synthetic text is sent. The existing tester credential stays in
process memory; it and the session token are never printed or saved.
"""
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import time
import wave

spec = importlib.util.spec_from_file_location('remote_smoke', Path(__file__).with_name('remote-smoke.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
client = module.SmokeHTTPClient('rewind-api-v7pmsb3rva-df.a.run.app')
request = client.request
names = ['Aoede', 'Kore', 'Sulafat', 'Puck', 'Charon', 'Fenrir']
target = '早晨，我想學好廣東話。'

def audio_info(audio):
    data = base64.b64decode(audio['base64'], validate=True)
    digest = hashlib.sha256(data).hexdigest()
    assert digest == audio['sha256']
    with wave.open(io.BytesIO(data), 'rb') as stream:
        assert stream.getnchannels() == 1 and stream.getsampwidth() == 2
        return digest, stream.getframerate(), round(stream.getnframes()/stream.getframerate(), 3)

try:
    request('POST', '/api/creator/preview', {'voice': 'yue-HK-Chirp3-HD-Aoede', 'consent': True}, authenticated=False, expected=401)
    code = subprocess.run(['gcloud', 'secrets', 'versions', 'access', '1', '--secret=rewind-demo-access', '--project=rewind-514904', '--quiet'], capture_output=True, check=True).stdout.decode().strip()
    client.token = request('POST', '/api/session', {'access_code': code}, authenticated=False)['token']
    code = ''
    status = request('GET', '/api/status')
    assert status['provider'] == 'gemini'
    caps = status['creator']
    assert caps['voice_selection'] and caps['voice_preview']
    print('Authenticated voice catalog: ' + str(len(caps['voices'])), flush=True)
    request('POST', '/api/creator/preview', {'voice': 'not-a-voice', 'consent': True}, expected=400)
    request('POST', '/api/creator/preview', {'voice': 'yue-HK-Chirp3-HD-Aoede', 'consent': True, 'text': 'not allowed'}, expected=400)
    hashes = set()
    for name in names:
        voice = 'yue-HK-Chirp3-HD-' + name
        payload = {'voice': voice, 'consent': True}
        result = request('POST', '/api/creator/preview', payload)
        assert result['voice'] == voice
        digest, rate, duration = audio_info(result['audio'])
        assert 1 < duration < 20 and rate == 24000
        cached = request('POST', '/api/creator/preview', payload)
        assert cached['audio']['sha256'] == digest
        hashes.add(digest)
        print(json.dumps({'preview': name, 'seconds': duration, 'rate': rate, 'sha256': digest, 'cache': True}), flush=True)
    assert len(hashes) == len(names)
    for name in ['Aoede', 'Charon']:
        voice = 'yue-HK-Chirp3-HD-' + name
        started = request('POST', '/api/creator/render', {'consent': True, 'draft': {'title': 'Voice check', 'text': target, 'mode': 'faithful', 'voice': voice}})
        ident = started['job_id']
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            result = request('POST', '/api/creator/status', {'job_id': ident})
            if result['state'] == 'completed':
                session = result['result']['session']
                assert session['source']['voice'] == voice
                assert session['source']['reviewed_text'] == target
                digest, rate, duration = audio_info(session['audio'])
                print(json.dumps({'render': name, 'seconds': duration, 'sha256': digest, 'reviewed_text_unchanged': True}), flush=True)
                break
            if result['state'] in ('failed', 'cancelled'):
                raise RuntimeError('Render failed: ' + str(result.get('error', 'unknown'))[:200])
            time.sleep(1)
        else:
            request('POST', '/api/creator/cancel', {'job_id': ident})
            raise RuntimeError('Render exceeded bounded test time.')
    print('PASS: six real previews, cache, authentication, invalid inputs, two selected-voice practice tapes.', flush=True)
finally:
    if client.token:
        try:
            request('POST', '/api/session/end', {})
        except Exception:
            pass
    client.close()
