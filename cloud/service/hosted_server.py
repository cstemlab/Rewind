"""Small, invite-only hosted adapter. Never imports the local key/config server.

Only immutable provider code is shared. Every browser session owns its live
connection, creator jobs, assessment lock and verification state. No request
bodies, authentication headers, recordings or provider errors are logged.
"""
from __future__ import annotations
import base64
import binascii
import collections
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from assess import AssessmentError, redact, _key
from azure_feedback import validate_wav, no_speech_result
from openai_feedback import coach_openai_bytes, MODEL as OPENAI_MODEL
from live_transcription import LiveManager, MODEL as LIVE_MODEL
from creator import CreatorManager, capabilities, extract_document, MAX_FILE_BYTES, select_voice, narration, PREVIEW_TEXT, preview_audio

ALLOWED_ORIGIN = 'https://cstemlab.github.io'
IDLE_TTL = 1800
ABSOLUTE_TTL = 7200
MAX_SESSIONS = 4
MAX_BODY = 1_200_000
MAX_EXTRACT_BODY = 6_700_000
CREATOR_ROUTES = {'/api/creator/' + name for name in ('extract', 'translate', 'render', 'status', 'cancel', 'preview')}
LIVE_ROUTES = {'/api/live/' + name for name in ('start', 'audio', 'events', 'stop', 'cancel')}
POST_ROUTES = CREATOR_ROUTES | LIVE_ROUTES | {'/api/assess-recording', '/api/session/end', '/api/session/provider'}


def fail(code, message):
    raise AssessmentError(code, message)


class RateWindow:
    def __init__(self, limit, seconds=60):
        self.limit, self.seconds = limit, seconds
        self.times = collections.deque()
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            now = time.monotonic()
            while self.times and now - self.times[0] >= self.seconds:
                self.times.popleft()
            if len(self.times) >= self.limit:
                fail('rate_limited', '使用較頻密，請稍後再試。')
            self.times.append(now)


class HostedCreatorManager(CreatorManager):
    """One global generation worker; one retained result per visitor, for 5 min.

Cancellation does not release the global slot while a provider call is still
running. This avoids silently allowing overlapping paid jobs after cancellation.
"""
    def __init__(self, gate, **kwargs):
        super().__init__(**kwargs)
        self.gate = gate

    def _expire(self):
        now = time.monotonic()
        for ident, job in list(self.jobs.items()):
            if job['state'] not in ('queued', 'running') and now - job['updated'] > 300:
                del self.jobs[ident]

    def start(self, kind, body, key, generation):
        if not self.gate.acquire(blocking=False):
            fail('creator_busy', '示範服務正在建立另一份練習，請稍後再試。')
        try:
            with self.lock:
                # Old completed audio is not needed once a new job starts.
                self.jobs = {k: v for k, v in self.jobs.items() if v['state'] in ('queued', 'running')}
            return super().start(kind, body, key, generation)
        except BaseException:
            self.gate.release()
            raise

    def _run(self, *args):
        try:
            return super()._run(*args)
        finally:
            self.gate.release()


class Runtime:
    """Immutable owner-configured provider callbacks; no visitor credentials."""
    def __init__(self, name, api_key, *, coach=coach_openai_bytes, live_factory=LiveManager,
                 creator_factory=HostedCreatorManager, model=OPENAI_MODEL,
                 creator_capabilities=None, decorate_session=None, supports_live=None, live_model=None,
                 voice_selector=select_voice, preview_synthesizer=narration):
        if name not in ('openai', 'gemini'):
            raise ValueError('Unsupported provider.')
        self.name, self.api_key, self.model = name, _key(api_key), model
        self.coach, self.live_factory, self.creator_factory = coach, live_factory, creator_factory
        self.creator_capabilities = creator_capabilities or (lambda: capabilities(True))
        self.decorate_session = decorate_session
        self.voice_selector, self.preview_synthesizer = voice_selector, preview_synthesizer
        self.supports_live = name == 'openai' if supports_live is None else bool(supports_live)
        self.live_model = live_model or (LIVE_MODEL if name == 'openai' else None)


class Visitor:
    def __init__(self, app, provider=None):
        self.app = app
        self.runtime = app.providers[provider or app.provider]
        self.created = self.touched = time.monotonic()
        self.closed = False
        self.verified = False
        self.lock = threading.RLock()
        self.inflight = threading.Lock()
        self.live = self.runtime.live_factory()
        self.creator = self.runtime.creator_factory(app.creator_gate)
        self.requests = RateWindow(1200)
        self.assessments = RateWindow(5, 61)
        self.live_starts = RateWindow(5, 61)
        self.creator_starts = RateWindow(4, 600)
        self.voice_previews = RateWindow(30, 60)

    def expires_in(self):
        now = time.monotonic()
        return max(0, int(min(IDLE_TTL - (now - self.touched), ABSOLUTE_TTL - (now - self.created))))

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.live.cancel('session_expired')
            self.creator.cancel()

    def assert_open(self):
        if self.closed:
            fail('session_expired', '示範連線已結束，請重新輸入試用碼。')

    def status(self):
        with self.lock:
            self.assert_open()
            return {
                'configured': True, 'provider': self.runtime.name, 'connection_verified': self.verified,
                'region': '', 'mode': 'hosted-trial', 'key_storage': 'server-environment',
                'supported_providers': list(self.app.providers), 'model': self.runtime.model,
                'max_recording_seconds': 25, 'cloud_requests_per_attempt': 1,
                'session_expires_in': self.expires_in(),
                'session_absolute_expires_in': max(0, int(ABSOLUTE_TTL - (time.monotonic() - self.created))),
                'live_transcription': {'supported': self.runtime.supports_live, 'available': self.runtime.supports_live, 'model': self.runtime.live_model if self.runtime.supports_live else None,
                    'feedback_kind': 'transcription-progress', 'sample_rate': 24000, 'max_seconds': 25},
                'creator': self.runtime.creator_capabilities(),
            }

    def assess(self, body):
        if body.get('provider') != self.runtime.name:
            fail('invalid_provider', '語音服務已變更，請重新連線。')
        target, encoded = body.get('text'), body.get('audio')
        if not isinstance(target, str) or not target.strip() or len(target) > 200:
            fail('invalid_reference', '請選擇 200 字以內的短句。')
        if body.get('extension', '.wav') != '.wav' or not isinstance(encoded, str):
            fail('audio_format', '請提供 WAV 錄音。')
        data = base64.b64decode(encoded, validate=True)
        info = validate_wav(data)
        if not self.inflight.acquire(blocking=False):
            fail('busy', '上一段仍在評測中，請稍候。')
        leased = False
        started = time.monotonic()
        try:
            with self.lock:
                self.assert_open()
                if info['no_speech']:
                    return {**no_speech_result(target), 'provider': self.runtime.name, 'assessment_kind': 'audio-coaching',
                        'elapsed_seconds': 0, 'audio_duration_seconds': info['duration_seconds']}
                self.assessments.take()
                self.app.assessments.take()
                leased = self.app.assessment_gate.acquire(blocking=False)
                if not leased:
                    fail('busy', '示範服務正在評測，請稍後再試。')
            result = self.runtime.coach(data, target, self.runtime.api_key)
            with self.lock:
                self.assert_open()
                self.verified = True
            result.update(elapsed_seconds=round(time.monotonic() - started, 3), audio_duration_seconds=info['duration_seconds'])
            return result
        finally:
            if leased:
                self.app.assessment_gate.release()
            self.inflight.release()

    def live_request(self, route, body):
        if not self.runtime.supports_live:
            fail('live_unavailable', '目前服務提供錄音後評測，尚未提供即時聆聽。')
        if body.get('provider') != self.runtime.name:
            fail('invalid_provider', '語音服務已變更，請重新連線。')
        with self.lock:
            self.assert_open()
            if route == '/api/live/start':
                self.live_starts.take()
                self.app.live_starts.take()
            else:
                live = self.live.get(body.get('session_id'), 0)
                if route == '/api/live/audio':
                    encoded = body.get('audio')
                    if not isinstance(encoded, str) or len(encoded) > 64000:
                        fail('live_audio_format', '每個即時錄音片段最多一秒。')
                    return live.append(body.get('seq'), base64.b64decode(encoded, validate=True))
                if route == '/api/live/events':
                    return live.events(body.get('after', 0))
                return live.stop(False if route.endswith('/cancel') else body.get('commit', True))
        result = self.live.start(self.runtime.api_key, 0)
        with self.lock:
            if self.closed:
                self.live.cancel('session_expired')
                self.assert_open()
        return result

    def creator_request(self, route, body):
        if route == '/api/creator/preview':
            with self.lock:
                self.assert_open()
                if set(body) != {'voice', 'consent'} or body.get('consent') is not True:
                    fail('invalid_preview', '請選擇一個聲音，再按試聽。')
                if not isinstance(body['voice'], str):
                    fail('invalid_voice', '請重新選擇目前服務提供的聲音。')
                voice = self.runtime.voice_selector(body['voice'])
                self.voice_previews.take()
                self.app.voice_previews.take()
                runtime = self.runtime
            result = self.app.preview(runtime, voice)
            with self.lock:
                self.assert_open()
            return result
        with self.lock:
            self.assert_open()
            if route == '/api/creator/status':
                result = self.creator.status(body.get('job_id'), 0)
                session = result.get('result', {}).get('session')
                if session and self.runtime.decorate_session:
                    # Only copy metadata; large immutable audio is not duplicated.
                    result = {**result, 'result': {**result['result'], 'session': self.runtime.decorate_session(session)}}
                return result
            if route == '/api/creator/cancel':
                return self.creator.cancel(body.get('job_id'), 0)
            if route in ('/api/creator/translate', '/api/creator/render'):
                if body.get('consent') is not True:
                    fail('creator_consent', '生成會把文字傳送到目前的 AI 服務，請從生成按鈕確認。')
                self.creator_starts.take()
                self.app.creator_starts.take()
                return self.creator.start(route.rsplit('/', 1)[-1], body, self.runtime.api_key, 0)
        encoded = body.get('data')
        if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
            fail('file_size', '檔案請限制在 5 MB 以內。')
        data = base64.b64decode(encoded, validate=True)
        if not self.app.extract_gate.acquire(blocking=False):
            fail('creator_busy', '正在讀取另一個檔案，請稍候。')
        try:
            result = self.app.extractor(body.get('filename'), data)
            self.assert_open()
            return result
        finally:
            self.app.extract_gate.release()


class App:
    def __init__(self, api_key, access_code, *, coach=coach_openai_bytes,
                 live_factory=LiveManager, creator_factory=HostedCreatorManager, extractor=extract_document,
                 provider='openai', model=OPENAI_MODEL, creator_capabilities=None, decorate_session=None, providers=None):
        if provider not in ('openai', 'gemini'):
            raise ValueError('Unsupported provider.')
        self.provider, self.model = provider, model
        self.supports_live = provider == 'openai'
        self.creator_capabilities = creator_capabilities or (lambda: capabilities(True))
        self.decorate_session = decorate_session
        self.api_key = _key(api_key)
        self.providers = providers or {provider: Runtime(provider, api_key, coach=coach, live_factory=live_factory,
            creator_factory=creator_factory, model=model, creator_capabilities=creator_capabilities, decorate_session=decorate_session)}
        if provider not in self.providers:
            raise ValueError('Default provider is not configured.')
        if not isinstance(access_code, str) or not 20 <= len(access_code) <= 200:
            raise ValueError('REWIND_ACCESS_CODE must contain 20 to 200 characters.')
        self.access_code = access_code
        self.coach, self.live_factory, self.creator_factory, self.extractor = coach, live_factory, creator_factory, extractor
        self.lock = threading.Lock()
        self.sessions = {}
        self.requests = RateWindow(4800)
        self.handshakes = RateWindow(30)
        self.assessments = RateWindow(20, 61)
        self.live_starts = RateWindow(20, 61)
        self.creator_starts = RateWindow(12, 600)
        self.voice_previews = RateWindow(120, 60)
        self.preview_generations = RateWindow(12, 600)
        self.preview_lock = threading.Lock()
        self.preview_cache = {}
        self.creator_gate = threading.BoundedSemaphore(1)
        self.assessment_gate = threading.BoundedSemaphore(2)
        self.extract_gate = threading.BoundedSemaphore(1)
        self.stopped = threading.Event()

    def preview(self, runtime, voice):
        # Fixed public sample only: never cache user scripts. Serial cache fills
        # prevent duplicate paid calls; failure leaves no cached substitute.
        if not self.preview_lock.acquire(blocking=False):
            fail('creator_busy', '正在準備另一段試聽，請稍後再試。')
        try:
            now = time.monotonic()
            self.preview_cache = {key: value for key, value in self.preview_cache.items() if now - value[0] < 3600}
            key = (runtime.name, voice)
            if key in self.preview_cache:
                return self.preview_cache[key][1]
            self.preview_generations.take()
            result = preview_audio(runtime.preview_synthesizer(PREVIEW_TEXT, runtime.api_key, voice), voice)
            if len(self.preview_cache) >= 32:
                del self.preview_cache[min(self.preview_cache, key=lambda item: self.preview_cache[item][0])]
            self.preview_cache[key] = (time.monotonic(), result)
            return result
        finally:
            self.preview_lock.release()

    def prune(self):
        with self.lock:
            expired = [token for token, visitor in self.sessions.items() if visitor.expires_in() <= 0]
            visitors = [self.sessions.pop(token) for token in expired]
            active = list(self.sessions.values())
        for visitor in visitors:
            visitor.close()
        for visitor in active:
            with visitor.creator.lock:
                visitor.creator._expire()

    def create_session(self, code):
        self.handshakes.take()
        if not isinstance(code, str) or len(code) > 200 or not secrets.compare_digest(code.encode('utf-8'), self.access_code.encode('utf-8')):
            fail('access_denied', '試用碼不正確。')
        self.prune()
        with self.lock:
            if len(self.sessions) >= MAX_SESSIONS:
                fail('rate_limited', '示範服務目前已滿，請稍後再試。')
            token = secrets.token_urlsafe(32)
            self.sessions[token] = Visitor(self)
        return {'ok': True, 'token': token, 'expires_in': IDLE_TTL, 'absolute_expires_in': ABSOLUTE_TTL}

    def authenticate(self, authorization):
        if not isinstance(authorization, str) or not authorization.startswith('Bearer ') or len(authorization) > 128:
            fail('session_required', '請先輸入試用碼。')
        token = authorization[7:]
        with self.lock:
            visitor = self.sessions.get(token)
            if not visitor:
                fail('session_expired', '示範連線已結束，請重新輸入試用碼。')
            expired = visitor.expires_in() <= 0
            if expired:
                self.sessions.pop(token)
            else:
                visitor.touched = time.monotonic()
        if expired:
            visitor.close()
            fail('session_expired', '示範連線已結束，請重新輸入試用碼。')
        visitor.requests.take()
        visitor.assert_open()
        return visitor

    def end_session(self, visitor):
        with self.lock:
            for token, candidate in list(self.sessions.items()):
                if candidate is visitor:
                    del self.sessions[token]
                    break
        visitor.close()
        return {'ok': True}

    def switch_provider(self, visitor, name):
        if not isinstance(name, str) or name not in self.providers:
            fail('invalid_provider', '這項語音服務尚未由提供者設定。')
        if visitor.runtime.name == name:
            return visitor.status()
        replacement = Visitor(self, name)
        replacement.created = visitor.created
        # A switch does not reset visitor budgets or extend absolute lifetime.
        for attribute in ('requests', 'assessments', 'live_starts', 'creator_starts', 'voice_previews'):
            setattr(replacement, attribute, getattr(visitor, attribute))
        with self.lock:
            token = next((token for token, value in self.sessions.items() if value is visitor), None)
            if token is None:
                fail('session_expired', '示範連線已結束，請重新輸入試用碼。')
            self.sessions[token] = replacement
        visitor.close()
        return replacement.status()

    def secrets(self):
        return tuple(runtime.api_key for runtime in self.providers.values()) + (self.access_code,)

    def maintain(self):
        while not self.stopped.wait(30):
            self.prune()

    def close(self):
        self.stopped.set()
        with self.lock:
            visitors = list(self.sessions.values())
            self.sessions.clear()
        for visitor in visitors:
            visitor.close()


def error_status(code):
    if code in ('session_required', 'session_expired'):
        return 401
    if code == 'access_denied':
        return 403
    if code in ('rate_limited', 'local_rate_limit', 'creator_rate_limit', 'google_http_429'):
        return 429
    if code in ('busy', 'creator_busy', 'creator_job', 'live_busy', 'live_session', 'live_closed', 'live_sequence'):
        return 409
    if code == 'google_auth':
        return 503
    if code.startswith(('http_', 'network_', 'malformed_', 'redirect_', 'live_connection', 'live_provider', 'live_timeout', 'creator_http_', 'creator_network', 'google_http_', 'google_network', 'google_response')):
        return 502
    return 400


class Handler(BaseHTTPRequestHandler):
    server_version = 'Rewind'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        pass

    def send(self, status, result):
        data = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Vary', 'Origin')
        if self.headers.get('Origin') == ALLOWED_ORIGIN:
            self.send_header('Access-Control-Allow-Origin', ALLOWED_ORIGIN)
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
            self.send_header('Access-Control-Max-Age', '600')
        if status == 429:
            self.send_header('Retry-After', '60')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def origin_allowed(self):
        # No cookies; bearer authentication still applies. Requiring the exact
        # browser Origin also blocks accidental use from other hosted pages.
        return self.headers.get('Origin') == ALLOWED_ORIGIN

    def do_OPTIONS(self):
        if not self.origin_allowed() or self.headers.get('Access-Control-Request-Method') not in ('GET', 'POST'):
            return self.send(403, {'error': 'Origin not allowed.', 'code': 'origin_denied'})
        requested = {value.strip().lower() for value in self.headers.get('Access-Control-Request-Headers', '').split(',') if value.strip()}
        if not requested <= {'authorization', 'content-type'}:
            return self.send(403, {'error': 'Headers not allowed.', 'code': 'headers_denied'})
        return self.send(200, {'ok': True})

    def do_GET(self):
        self.handle_api('GET')

    def do_POST(self):
        self.handle_api('POST')

    def handle_api(self, method):
        app = self.server.app
        try:
            route = urlsplit(self.path).path
            if method == 'GET' and route in ('/health', '/healthz'):
                return self.send(200, {'ok': True})
            if not self.origin_allowed():
                return self.send(403, {'error': 'Origin not allowed.', 'code': 'origin_denied'})
            app.requests.take()
            if method == 'GET':
                if route != '/api/status':
                    return self.send(404, {'error': 'Not found.', 'code': 'not_found'})
                if not self.headers.get('Authorization'):
                    return self.send(200, {'configured': False, 'mode': 'hosted-trial', 'requires_access_code': True, 'supported_providers': list(app.providers)})
                return self.send(200, app.authenticate(self.headers.get('Authorization')).status())
            if route != '/api/session' and route not in POST_ROUTES:
                return self.send(404, {'error': 'Not found.', 'code': 'not_found'})
            visitor = None if route == '/api/session' else app.authenticate(self.headers.get('Authorization'))
            if self.headers.get_content_type() != 'application/json':
                return self.send(415, {'error': 'Expected application/json.', 'code': 'content_type'})
            if self.headers.get('Transfer-Encoding'):
                return self.send(400, {'error': 'Content-Length required.', 'code': 'invalid_request'})
            size = int(self.headers.get('Content-Length', '0'))
            maximum = 4096 if route in ('/api/session', '/api/creator/preview') else MAX_EXTRACT_BODY if route == '/api/creator/extract' else MAX_BODY
            if not 0 < size <= maximum:
                return self.send(413, {'error': '請求內容過大或為空。', 'code': 'body_size'})
            data = self.rfile.read(size)
            if len(data) != size:
                raise ValueError()
            body = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(body, dict):
                raise ValueError()
            if route == '/api/session':
                return self.send(200, app.create_session(body.get('access_code')))
            if route == '/api/session/end':
                result = app.end_session(visitor)
            elif route == '/api/session/provider':
                result = app.switch_provider(visitor, body.get('provider'))
            elif route in LIVE_ROUTES:
                result = visitor.live_request(route, body)
            elif route in CREATOR_ROUTES:
                result = visitor.creator_request(route, body)
            else:
                result = visitor.assess(body)
            return self.send(200, redact(result, app.secrets()))
        except AssessmentError as exc:
            return self.send(error_status(exc.code), {'error': redact(exc.message, app.secrets()), 'code': exc.code})
        except (ValueError, TypeError, binascii.Error, UnicodeError, TimeoutError):
            return self.send(400, {'error': '請求格式不正確。', 'code': 'invalid_request'})
        except Exception:
            return self.send(500, {'error': '未能完成，請稍後再試。', 'code': 'internal_error'})


class HostedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)


def main():
    # Secrets are loaded once. Public clients cannot mutate provider settings.
    provider_name = os.environ.get('REWIND_SPEECH_PROVIDER', 'gemini').strip().lower()
    runtimes = {}
    if os.environ.get('GOOGLE_CLOUD_PROJECT', '').strip():
        from google_provider import GoogleProvider
        from google_live import GoogleLiveManager, MODEL as GOOGLE_LIVE_MODEL
        google = GoogleProvider(project=os.environ.get('GOOGLE_CLOUD_PROJECT', ''), location=os.environ.get('GOOGLE_CLOUD_LOCATION', 'global'))
        runtimes['gemini'] = Runtime('gemini', 'google-adc-runtime-credential',
            model=google.model, coach=google.coach,
            live_factory=lambda: GoogleLiveManager(google.project), supports_live=True,
            live_model=os.environ.get('REWIND_GOOGLE_LIVE_MODEL', GOOGLE_LIVE_MODEL),
            creator_factory=lambda gate: HostedCreatorManager(gate, translator=google.translate, planner=google.plan, synthesizer=google.narrate, voice_selector=google.select_voice),
            creator_capabilities=google.capabilities, decorate_session=google.decorate_session,
            voice_selector=google.select_voice, preview_synthesizer=google.narrate)
    if os.environ.get('OPENAI_API_KEY', '').strip():
        runtimes['openai'] = Runtime('openai', os.environ['OPENAI_API_KEY'].strip())
    if provider_name not in runtimes:
        raise ValueError('Default speech provider is not configured.')
    app = App(runtimes[provider_name].api_key, os.environ.get('REWIND_ACCESS_CODE', ''), provider=provider_name, providers=runtimes)
    server = HostedServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), app)
    threading.Thread(target=app.maintain, daemon=True).start()
    print('Rewind hosted service ready.', flush=True)
    try:
        server.serve_forever()
    finally:
        app.close()
        server.server_close()


if __name__ == '__main__':
    main()
