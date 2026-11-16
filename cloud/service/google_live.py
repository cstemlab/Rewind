"""Google Cloud verbatim live transcription, never pronunciation approval.

The public relay retains its existing 24 kHz PCM contract. A stateful converter
sends 16 kHz to Gemini Transcribe Live. No target script/adaptation bias is sent.
Cantonese is experimental in this model; failures preserve final recording
assessment. ADC is server-only, with no service-account key export.
"""
from __future__ import annotations
from array import array
import base64
import json
import os
import secrets
import socket
import sys
import threading
import time

from assess import AssessmentError
from google_provider import ADCTransport, PROJECT_RE
from live_transcription import (LiveSession, LiveManager, BoundedWebSocket,
                                RATE, MAX_SECONDS, MAX_CHUNK, MAX_MESSAGE,
                                MAX_TRANSCRIPT, websocket)

MODEL = 'gemini-3.5-transcribe-live'
PROVIDER_RATE = 16000


class PCM24To16:
    """Linear 3:2 conversion; preserve phase and fractional frame across calls."""
    def __init__(self):
        self.pending = []

    def push(self, data, finish=False):
        samples = array('h', data)
        if sys.byteorder != 'little':
            samples.byteswap()
        values = self.pending + samples.tolist()
        result = array('h')
        complete = len(values) // 3 * 3
        for index in range(0, complete, 3):
            result.append(values[index])
            result.append(round((values[index + 1] + values[index + 2]) / 2))
        self.pending = values[complete:]
        if finish:
            if len(self.pending) == 2:
                result.append(self.pending[0])
            self.pending = []
        if sys.byteorder != 'little':
            result.byteswap()
        return result.tobytes()


class GoogleConnection:
    def __init__(self, project, location='global', model=MODEL, auth=None):
        if not PROJECT_RE.fullmatch(project) or location not in ('global', 'us', 'eu'):
            raise AssessmentError('google_live_config', 'Google 即時聆聽地區設定不正確。')
        if model not in ('gemini-3.5-transcribe-live', 'gemini-3.5-transcribe-live-preview'):
            raise AssessmentError('google_live_config', 'Google 即時聆聽模型設定不正確。')
        self.project, self.location, self.model = project, location, model
        self.auth = auth or ADCTransport(project)
        host = 'aiplatform.googleapis.com' if location == 'global' else location + '-aiplatform.googleapis.com'
        self.url = f'wss://{host}/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent'
        self.setup = {'setup': {
            'model': f'projects/{project}/locations/{location}/publishers/google/models/{model}',
            'generationConfig': {'responseModalities': ['TEXT']},
            'inputAudioTranscription': {'languageCodes': ['yue-Hant-HK'], 'mode': 'VERBATIM'},
            'realtimeInputConfig': {'automaticActivityDetection': {'disabled': True}},
        }}

    def __call__(self, unused_key=None):
        # Credentials never appear in the URL and redirects are not followed.
        headers = self.auth._headers()
        try:
            ws = websocket.create_connection(self.url, timeout=8, class_=BoundedWebSocket,
                header={'Authorization': headers['Authorization'], 'x-goog-user-project': self.project},
                suppress_origin=True, redirect_limit=0, enable_multithread=True)
        except websocket.WebSocketBadStatusException as exc:
            code = getattr(exc, 'status_code', None)
            code = code if type(code) is int and 100 <= code <= 599 else 0
            raise AssessmentError('google_live_http_' + str(code),
                                  'Google Cloud 專案目前未能連接即時模型，仍可錄音後評測。') from None
        if getattr(getattr(ws, 'handshake_response', None), 'status', None) != 101:
            ws.shutdown()
            raise AssessmentError('live_connection', 'Google 即時聆聽未能連接，仍可錄音後評測。')
        ws.settimeout(.5)
        return ws


class GoogleLiveSession(LiveSession):
    def __init__(self, generation, connection, factory=None, clock=None):
        super().__init__(generation, factory=factory or connection, clock=clock)
        self.connection = connection
        self.converter = PCM24To16()
        self._activity_started = False
        self._final_segments = ''
        self._final_pending = ''
        self._interim = ''
        self._last_transcript_at = None
        self._input_done = False
        self._turn_done = False

    def connect(self, unused_key=None):
        try:
            ws = self._factory(unused_key)
            with self._lock:
                if self.state != 'connecting':
                    ws.shutdown()
                    raise AssessmentError('live_cancelled', '這次即時聆聽已取消。')
                self._ws = ws
            self._send(self.connection.setup)
            threading.Thread(target=self._receive, daemon=True, name='rewind-google-live').start()
            threading.Thread(target=self._watch, daemon=True, name='rewind-google-limit').start()
            if not self._ready.wait(8):
                self.fail('live_timeout', 'Google 即時聆聽連接逾時，仍可錄音後評測。')
            with self._lock:
                if self.state != 'listening':
                    raise AssessmentError(self._error_code or 'live_cancelled', 'Google 即時聆聽未能啟動。')
                self._send({'realtimeInput': {'activityStart': {}}})
                self._activity_started = True
                return self.summary()
        except AssessmentError:
            self.close('cancelled')
            raise
        except Exception:
            self.fail('live_connection', 'Google 即時聆聽未能連接，仍可錄音後評測。')
            raise AssessmentError('live_connection', 'Google 即時聆聽未能連接，仍可錄音後評測。') from None

    def summary(self):
        value = super().summary()
        value.update(model=self.connection.model, language='yue-Hant-HK', experimental=True)
        return value

    def _audio(self, data):
        if data:
            self._send({'realtimeInput': {'audio': {
                'mimeType': 'audio/pcm;rate=16000', 'data': base64.b64encode(data).decode('ascii')}}})

    def append(self, seq, data):
        if type(seq) is not int or seq < 0:
            raise AssessmentError('live_sequence', '錄音片段順序不正確。')
        if not isinstance(data, bytes) or not 2 <= len(data) <= MAX_CHUNK or len(data) % 2:
            raise AssessmentError('live_audio_format', '即時錄音需為 24 kHz 單聲道 PCM16。')
        with self._lock:
            if self.state != 'listening' or not self._activity_started:
                raise AssessmentError('live_closed', '這次即時聆聽已結束。')
            if seq != self._audio_seq:
                raise AssessmentError('live_sequence', '錄音片段順序不正確。')
            if self._clock() - self._started > MAX_SECONDS + .5 or self._audio_bytes + len(data) > MAX_SECONDS * RATE * 2:
                raise AssessmentError('live_limit', '每次即時聆聽最多 25 秒。')
            try:
                self._audio(self.converter.push(data))
            except Exception:
                self.fail('live_connection', '即時聆聽已中斷，錄音仍可繼續。')
                raise AssessmentError('live_connection', '即時聆聽已中斷，錄音仍可繼續。') from None
            self._audio_bytes += len(data)
            self._audio_seq += 1
            self._last_audio = self._clock()
            return {'accepted_seq': seq, 'next_seq': self._audio_seq,
                    'received_seconds': round(self._audio_bytes / (RATE * 2), 4), 'state': self.state}

    def stop(self, commit=True):
        if type(commit) is not bool:
            raise AssessmentError('invalid_request', '請求格式不正確。')
        with self._lock:
            if self.state in ('closed', 'error', 'finishing'):
                return self.summary()
            if not commit or self.state == 'connecting':
                self.close('cancelled')
                return self.summary()
            if self._audio_bytes < RATE * 2 // 10:
                self.close('no_audio')
                return self.summary()
            self.state = 'finishing'
            self._finish_at = self._clock()
            try:
                self._audio(self.converter.push(b'', finish=True))
                self._send({'realtimeInput': {'activityEnd': {}}})
            except Exception:
                self.fail('live_connection', '即時聆聽已中斷，錄音仍可評測。')
            return self.summary()

    def _receive(self):
        while self.state not in ('closed', 'error'):
            try:
                raw = self._ws.recv()
                if raw in ('', b'', None):
                    self.fail('live_connection', '即時聆聽已中斷，錄音仍可評測。')
                    return
                if isinstance(raw, bytes):
                    if len(raw) > MAX_MESSAGE:
                        raise ValueError()
                    raw = raw.decode('utf-8')
                if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_MESSAGE:
                    raise ValueError()
                event = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(event, dict):
                    raise ValueError()
                self.handle_event(event)
            except (socket.timeout, websocket.WebSocketTimeoutException):
                continue
            except Exception:
                if self.state not in ('closed', 'error'):
                    self.fail('live_protocol', 'Google 即時文字未能讀取，錄音仍可評測。')
                return

    @staticmethod
    def _field(value, camel, snake):
        return value[camel] if camel in value else value.get(snake)

    def _publish(self, final=False):
        text = self._final_segments + self._final_pending + self._interim
        if len(text) > MAX_TRANSCRIPT:
            self.fail('live_limit', '即時聆聽內容過長，請分成短句練習。')
            return
        if text != self._text or final:
            self._text = text
            self._emit({'type': 'transcript', 'text': text, 'item_id': self.id,
                        'item_index': 0, 'final': final})

    def handle_event(self, event):
        with self._lock:
            if self.state in ('closed', 'error'):
                return
            if 'error' in event or 'goAway' in event or 'go_away' in event:
                self.fail('live_provider_error', 'Google 即時聆聽暫時不可用，仍可錄音後評測。')
                return
            if ('setupComplete' in event or 'setup_complete' in event) and self.state == 'connecting':
                self.state = 'listening'
                self._started = self._last_audio = self._clock()
                self._ready.set()
                return
            content = self._field(event, 'serverContent', 'server_content')
            if content is None:
                return
            if not isinstance(content, dict):
                self.fail('live_protocol', 'Google 即時文字格式不正確。')
                return
            interim = self._field(content, 'interimInputTranscription', 'interim_input_transcription')
            committed = self._field(content, 'inputTranscription', 'input_transcription')
            for part in (interim, committed):
                if part is not None and (not isinstance(part, dict) or not isinstance(part.get('text', ''), str)
                                         or len(part.get('text', '')) > MAX_TRANSCRIPT):
                    self.fail('live_protocol', 'Google 即時文字格式不正確。')
                    return
            if interim is not None:
                self._interim = interim.get('text', '')
                self._last_transcript_at = self._clock()
            if committed is not None:
                self._interim = ''
                self._final_pending += committed.get('text', '')
                self._last_transcript_at = self._clock()
                if committed.get('finished', True):
                    self._final_segments += self._final_pending
                    self._final_pending = ''
                    self._input_done = True
            if interim is not None or committed is not None:
                self._publish()
            # Manual endpointing means one activity per recording. A complete
            # input transcript after activityEnd is the final activity result.
            # Transcribe Live uses inputTranscription for the final segment;
            # the optional finished flag is often absent. The documented
            # sample distinguishes final from interim by the field name alone.
            # Honor an explicit false value, but do not wait indefinitely for
            # a conversational turnComplete event from a transcription model.
            finished_input = committed is not None and committed.get('finished', True) is True
            turn_complete = self._field(content, 'turnComplete', 'turn_complete') is True
            self._turn_done = self._turn_done or turn_complete
            if self.state == 'finishing' and (finished_input or (self._turn_done and self._input_done)):
                self._publish(final=True)
                self.close('completed')


class GoogleLiveManager(LiveManager):
    def __init__(self, project, location=None, model=None, factory=None, connection=None):
        super().__init__(factory=factory)
        self.connection = connection or GoogleConnection(
            project, location or os.environ.get('REWIND_GOOGLE_LIVE_LOCATION', 'global'),
            model or os.environ.get('REWIND_GOOGLE_LIVE_MODEL', MODEL))

    def start(self, unused_key, generation):
        with self._lock:
            if self._session and self._session.state not in ('closed', 'error'):
                raise AssessmentError('live_busy', '另一段即時聆聽仍在進行。')
            now = time.monotonic()
            while self._starts and now - self._starts[0] >= 61:
                self._starts.popleft()
            if len(self._starts) >= 5:
                raise AssessmentError('local_rate_limit', '即時聆聽較頻密，請稍後再試。')
            self._starts.append(now)
            self._session = GoogleLiveSession(generation, self.connection, factory=self._factory)
            session = self._session
        return session.connect(unused_key)
