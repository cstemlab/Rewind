"""Local Rewind speech trial. Keys and recordings stay in process memory."""
from __future__ import annotations
import argparse
import base64
import binascii
import collections
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
import urllib.parse
from assess import AssessmentError, assess_azure_bytes, recognize_azure_bytes, redact, validate_region
from azure_feedback import build_feedback, no_speech_result, validate_wav
from openai_feedback import coach_openai_bytes, MODEL as OPENAI_MODEL
from live_transcription import LiveManager, MODEL as LIVE_MODEL
from creator import CreatorManager, capabilities as creator_capabilities, extract_document, MAX_FILE_BYTES

HERE = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
SUPPORTED_PROVIDERS = ('azure', 'openai')
PROVIDER = os.environ.get('REWIND_SPEECH_PROVIDER', 'azure').strip().lower()
if PROVIDER not in SUPPORTED_PROVIDERS:
    PROVIDER = 'azure'
API_KEY = os.environ.get('OPENAI_API_KEY' if PROVIDER == 'openai' else 'AZURE_SPEECH_KEY', '').strip()
REGION = os.environ.get('AZURE_SPEECH_REGION', '').strip().lower() if PROVIDER == 'azure' else ''
VERIFIED = False
GENERATION = 0
LOCK = threading.Lock()
INFLIGHT = threading.Lock()
CALL_TIMES = collections.deque()
PORT = 0
MAX_BODY = 1_200_000
LIVE = LiveManager()
CREATOR = CreatorManager()
EXTRACT_LOCK = threading.Lock()


def player_path():
    native = HERE.parent / 'player' / 'build' / 'Rewind.html'
    return native if native.is_file() else HERE.parent / 'index.html'


def validate_key(key):
    if not isinstance(key, str) or not 8 <= len(key.strip()) <= 1024 or any(not 33 <= ord(c) <= 126 for c in key.strip()):
        raise AssessmentError('invalid_key', '請輸入有效的服務 API key。')
    return key.strip()


def status():
    with LOCK:
        return {'configured': bool(API_KEY and (PROVIDER == 'openai' or REGION)), 'provider': PROVIDER, 'connection_verified': VERIFIED,
                'region': REGION, 'mode': 'local-trial', 'key_storage': 'process-memory-only',
                'supported_providers': list(SUPPORTED_PROVIDERS),
                'model': OPENAI_MODEL if PROVIDER == 'openai' else None,
                'max_recording_seconds': 25, 'cloud_requests_per_attempt': 1 if PROVIDER == 'openai' else 2,
                'live_transcription': {'supported': True, 'available': bool(PROVIDER == 'openai' and API_KEY),
                                       'model': LIVE_MODEL, 'feedback_kind': 'transcription-progress',
                                       'sample_rate': 24000, 'max_seconds': 25},
                'creator': creator_capabilities(PROVIDER == 'openai' and API_KEY)}


def creator_request(route, body):
    if route == '/api/creator/extract':
        encoded=body.get('data')
        if not isinstance(encoded,str) or len(encoded)>((MAX_FILE_BYTES+2)//3)*4:
            raise AssessmentError('file_size','檔案請限制在 5 MB 以內。')
        data=base64.b64decode(encoded,validate=True)
        if not EXTRACT_LOCK.acquire(blocking=False):
            raise AssessmentError('creator_busy','正在讀取另一個檔案，請稍候。')
        try:return extract_document(body.get('filename'),data)
        finally:EXTRACT_LOCK.release()
    with LOCK:
        generation=GENERATION
        if route == '/api/creator/status':return CREATOR.status(body.get('job_id'),generation)
        if route == '/api/creator/cancel':return CREATOR.cancel(body.get('job_id'),generation)
        if PROVIDER!='openai' or not API_KEY:
            raise AssessmentError('not_configured','請先在 Speech 設定連接 OpenAI，然後建立粵語練習。')
        key=validate_key(API_KEY)
        if route not in ('/api/creator/translate','/api/creator/render'):
            raise AssessmentError('invalid_request','生成請求不正確。')
        # Starting a worker only reserves a job; the worker releases its own
        # lock before making any network request.
        return CREATOR.start(route.rsplit('/',1)[-1],body,key,generation)


def live_request(route, body):
    """All live requests bind to the explicitly consented provider and key generation."""
    expected = body.get('provider')
    if expected != 'openai':
        raise AssessmentError('invalid_provider', '即時聆聽目前使用 OpenAI，請重新確認服務。')
    with LOCK:
        if PROVIDER != expected:
            raise AssessmentError('provider_changed', '語音服務已變更，請重新確認後再傳送。')
        if not API_KEY:
            raise AssessmentError('not_configured', '請先連接語音服務。')
        key, generation = API_KEY, GENERATION
        if route != '/api/live/start':
            session = LIVE.get(body.get('session_id'), generation)
            if route == '/api/live/audio':
                encoded = body.get('audio')
                if not isinstance(encoded, str) or len(encoded) > 64000:
                    raise AssessmentError('live_audio_format', '每個即時錄音片段最多一秒。')
                data = base64.b64decode(encoded, validate=True)
                return session.append(body.get('seq'), data)
            if route == '/api/live/events':
                return session.events(body.get('after', 0))
            if route in ('/api/live/stop', '/api/live/cancel'):
                return session.stop(False if route.endswith('/cancel') else body.get('commit', True))
            raise AssessmentError('invalid_request', '請求格式不正確。')
    # Network handshake runs outside the configuration lock. A concurrent
    # disconnect cancels the reserved session; no microphone data is sent here.
    result = LIVE.start(validate_key(key), generation)
    with LOCK:
        if generation != GENERATION or PROVIDER != 'openai':
            LIVE.cancel('configuration_changed')
            raise AssessmentError('configuration_changed', '語音連線已變更，請重新開始。')
    return result


def assess_recording(data, target, expected_provider=None):
    global VERIFIED
    if not isinstance(target, str) or not target.strip() or len(target) > 200:
        raise AssessmentError('invalid_reference', '請選擇 200 字以內的短句。')
    info = validate_wav(data)
    if not INFLIGHT.acquire(blocking=False):
        raise AssessmentError('busy', '上一段仍在評測中，請稍候。')
    started = time.monotonic()
    try:
        with LOCK:
            if expected_provider is not None and expected_provider != PROVIDER:
                raise AssessmentError('provider_changed', '語音服務已變更，請重新確認後再傳送。')
            if not API_KEY or (PROVIDER == 'azure' and not REGION):
                raise AssessmentError('not_configured', '請先連接語音服務。')
            key, region, generation, provider = API_KEY, REGION, GENERATION, PROVIDER
            validate_key(key)
            if provider == 'azure':
                validate_region(region)
            if info['no_speech']:
                return {**no_speech_result(target), 'provider':provider,
                        'assessment_kind':'audio-coaching' if provider == 'openai' else 'pronunciation-assessment',
                        'elapsed_seconds': 0, 'audio_duration_seconds': info['duration_seconds']}
            now = time.monotonic()
            while CALL_TIMES and now - CALL_TIMES[0] >= 61:
                CALL_TIMES.popleft()
            if len(CALL_TIMES) >= 5 or (CALL_TIMES and now - CALL_TIMES[-1] < 1.1):
                raise AssessmentError('local_rate_limit', '試用評測較頻密，請稍後再試。')
            CALL_TIMES.append(now)
        if provider == 'openai':
            result = coach_openai_bytes(data, target, key)
        else:
            raw = assess_azure_bytes(data, target, key, region)
            with LOCK:
                if generation != GENERATION:
                    raise AssessmentError('configuration_changed', '連線已變更，這次評測已取消。')
            heard, cross_error = None, None
            try:
                heard = recognize_azure_bytes(data, key, region)
            except AssessmentError as exc:
                cross_error = exc.code
            with LOCK:
                if generation != GENERATION:
                    raise AssessmentError('configuration_changed', '連線已變更，這次評測已取消。')
            result = build_feedback(target, raw, heard, cross_error)
            result['assessment_kind'] = 'pronunciation-assessment'
        with LOCK:
            if generation != GENERATION:
                raise AssessmentError('configuration_changed', '連線已變更，這次評測已取消。')
            VERIFIED = True
        result.update({'elapsed_seconds': round(time.monotonic() - started, 3), 'audio_duration_seconds': info['duration_seconds']})
        return redact(result, (key,))
    finally:
        INFLIGHT.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'RewindLocalTrial'
    def log_message(self, *_):
        pass

    def valid_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_address[1]}'

    def send(self, code, data, mime='application/json; charset=utf-8'):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Permissions-Policy', 'microphone=(self), camera=()')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob: data:; frame-ancestors 'none'; form-action 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': 'Local access only.'})
        route = urllib.parse.urlsplit(self.path).path
        if route == '/':
            try:
                page = player_path().read_text(encoding='utf-8').replace('__LOCAL_TOKEN__', TOKEN)
            except OSError:
                return self.send(503, {'error': '請先建立 Rewind 播放器。'})
            return self.send(200, page.encode('utf-8'), 'text/html; charset=utf-8')
        if route == '/api/status':
            return self.send(200, status())
        return self.send(404, {'error': 'Not found'})

    def do_POST(self):
        global API_KEY, REGION, VERIFIED, GENERATION, PROVIDER
        expected_origin = f'http://127.0.0.1:{self.server.server_address[1]}'
        origin = self.headers.get('Origin')
        if not self.valid_host() or self.headers.get('X-Rewind-Token') != TOKEN or (origin and origin != expected_origin):
            return self.send(403, {'error': 'Local access only.'})
        if self.headers.get_content_type() != 'application/json':
            return self.send(415, {'error': 'Expected application/json.'})
        try:
            route = urllib.parse.urlsplit(self.path).path
            size = int(self.headers.get('Content-Length', '0'))
            maximum = 6_700_000 if route == '/api/creator/extract' else MAX_BODY
            if not 0 < size <= maximum:
                return self.send(413, {'error': '檔案請限制在 5 MB 以內。' if route == '/api/creator/extract' else '請求內容過大。'})
            body = json.loads(self.rfile.read(size), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
            if not isinstance(body, dict):
                raise ValueError()
            route = urllib.parse.urlsplit(self.path).path
            if route == '/api/config':
                provider = body.get('provider','azure')
                if not isinstance(provider,str) or provider not in SUPPORTED_PROVIDERS:
                    raise AssessmentError('invalid_provider','請選擇支援的語音服務。')
                key = validate_key(body.get('key', ''))
                region = ''
                if provider == 'azure':
                    region = body.get('region', '')
                    if not isinstance(region, str):
                        raise AssessmentError('invalid_region', '請填寫 Azure 資源的區域名稱。')
                    region = validate_region(region.strip().lower())
                with LOCK:
                    API_KEY, REGION, VERIFIED, PROVIDER = key, region, False, provider
                    GENERATION += 1
                    CALL_TIMES.clear()
                    LIVE.cancel('configuration_changed')
                    CREATOR.cancel()
                return self.send(200, status())
            if route == '/api/disconnect':
                with LOCK:
                    API_KEY, REGION, VERIFIED = '', '', False
                    GENERATION += 1
                    LIVE.cancel('disconnected')
                    CREATOR.cancel()
                return self.send(200, status())
            if route in ('/api/live/start', '/api/live/audio', '/api/live/events', '/api/live/stop', '/api/live/cancel'):
                return self.send(200, live_request(route, body))
            if route in ('/api/creator/extract','/api/creator/translate','/api/creator/render','/api/creator/status','/api/creator/cancel'):
                return self.send(200, creator_request(route,body))
            if route == '/api/assess-recording':
                expected_provider = body.get('provider')
                if not isinstance(expected_provider,str) or expected_provider not in SUPPORTED_PROVIDERS:
                    raise AssessmentError('invalid_provider','請重新選擇並確認語音服務。')
                encoded = body.get('audio')
                if body.get('extension', '.wav') != '.wav' or not isinstance(encoded, str):
                    raise AssessmentError('audio_format', '請提供 WAV 錄音。')
                data = base64.b64decode(encoded, validate=True)
                return self.send(200, assess_recording(data, body.get('text'), expected_provider=expected_provider))
            return self.send(404, {'error': 'Not found'})
        except AssessmentError as exc:
            code = 429 if exc.code in ('local_rate_limit','creator_rate_limit') else 409 if exc.code in ('busy', 'not_configured', 'configuration_changed','provider_changed','live_busy','live_session','live_closed','live_sequence','creator_busy','creator_job') else 502 if exc.code.startswith(('http_', 'network_', 'malformed_', 'redirect_', 'live_connection', 'live_provider', 'live_timeout','creator_http_','creator_network')) else 400
            return self.send(code, {'error': exc.message, 'code': exc.code})
        except (ValueError, TypeError, binascii.Error, UnicodeError):
            return self.send(400, {'error': '請求格式不正確。', 'code': 'invalid_request'})
        except Exception:
            return self.send(500, {'error': '評測未完成，請稍後再試。', 'code': 'internal_error'})


def main():
    global PORT, API_KEY
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    PORT = server.server_address[1]
    print(f'Rewind speech trial: http://127.0.0.1:{PORT}/', flush=True)
    print('OpenAI live listening uses a separate transcription stream; final feedback uses 1 OpenAI or 2 Azure requests. Keys and audio are not saved.', flush=True)
    if args.open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{PORT}/')
    try:
        server.serve_forever()
    finally:
        LIVE.cancel('server_closed')
        CREATOR.cancel()
        API_KEY = ''
        server.server_close()


if __name__ == '__main__':
    main()
