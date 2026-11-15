"""Bounded, memory-only OpenAI live transcription relay. Never pronunciation scores."""
from __future__ import annotations

import base64
import collections
import json
from pathlib import Path
import secrets
import socket
import sys
import threading
import time

from assess import AssessmentError

# Pinned pure-Python dependency travels with the local app; no global install.
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import websocket

MODEL = 'gpt-live-transcribe'
URL = 'wss://api.openai.com/v1/realtime?intent=transcription'
RATE = 24000
MAX_SECONDS = 25
MAX_CHUNK = RATE * 2
MAX_MESSAGE = 65536
MAX_TRANSCRIPT = 1600
SESSION_UPDATE = {
    'type': 'session.update',
    'session': {'type': 'transcription', 'audio': {'input': {
        'format': {'type': 'audio/pcm', 'rate': RATE},
        'transcription': {'model': MODEL, 'languages': ['yue'], 'delay': 'low'},
        'turn_detection': None,
    }}},
}


class BoundedWebSocket(websocket.WebSocket):
    """Reject large frames before their payload, and bound fragmented messages."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        original_length = self.frame_buffer.recv_length
        def limited_length():
            original_length()
            if self.frame_buffer.length > MAX_MESSAGE:
                raise websocket.WebSocketProtocolException('Message limit exceeded')
        self.frame_buffer.recv_length = limited_length
        original_add = self.cont_frame.add
        def limited_add(frame):
            existing = len(self.cont_frame.cont_data[1]) if self.cont_frame.cont_data else 0
            if existing + len(frame.data) > MAX_MESSAGE:
                raise websocket.WebSocketProtocolException('Message limit exceeded')
            original_add(frame)
        self.cont_frame.add = limited_add


def _connect(key):
    ws = websocket.create_connection(
        URL, timeout=8, class_=BoundedWebSocket,
        header={'Authorization': 'Bearer ' + key},
        suppress_origin=True, redirect_limit=0, enable_multithread=True,
    )
    # websocket-client's redirect_limit=0 prevents following, but does not itself
    # reject a 30x handshake. Never reuse Authorization at a redirect target.
    if getattr(getattr(ws, 'handshake_response', None), 'status', None) != 101:
        ws.shutdown()
        raise AssessmentError('live_connection', '即時聆聽未能連接，仍可錄音後評測。')
    ws.settimeout(.5)
    return ws


class LiveSession:
    def __init__(self, generation, factory=None, clock=None):
        self.id = secrets.token_urlsafe(24)
        self.generation = generation
        self.state = 'connecting'
        self._factory = factory or _connect
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._ready = threading.Event()
        self._ws = None
        self._events = collections.deque(maxlen=256)
        self._event_seq = 0
        self._audio_seq = 0
        self._audio_bytes = 0
        self._started = self._clock()
        self._last_audio = self._started
        self._finish_at = None
        self._closed_at = None
        self._item_id = None
        self._committed_id = None
        self._text = ''
        self._error_code = None

    def connect(self, key):
        try:
            ws = self._factory(key)
            with self._lock:
                if self.state != 'connecting':
                    ws.shutdown()
                    raise AssessmentError('live_cancelled', '這次即時聆聽已取消。')
                self._ws = ws
            self._send(SESSION_UPDATE)
            threading.Thread(target=self._receive, daemon=True, name='rewind-live-receive').start()
            threading.Thread(target=self._watch, daemon=True, name='rewind-live-limit').start()
            if not self._ready.wait(8):
                self.fail('live_timeout', '即時聆聽連接逾時，仍可錄音後評測。')
            with self._lock:
                if self.state != 'listening':
                    raise AssessmentError(self._error_code or 'live_cancelled', '即時聆聽未能啟動，仍可錄音後評測。')
                return self.summary()
        except AssessmentError:
            self.close('cancelled')
            raise
        except Exception:
            self.fail('live_connection', '即時聆聽未能連接，仍可錄音後評測。')
            raise AssessmentError('live_connection', '即時聆聽未能連接，仍可錄音後評測。') from None

    def summary(self):
        with self._lock:
            return {'session_id': self.id, 'state': self.state, 'sample_rate': RATE,
                    'max_seconds': MAX_SECONDS, 'model': MODEL,
                    'feedback_kind': 'transcription-progress'}

    def _emit(self, event):
        self._event_seq += 1
        self._events.append({'seq': self._event_seq, **event})

    def _send(self, data):
        with self._send_lock:
            with self._lock:
                ws = self._ws
                if self.state in ('closed', 'error') or ws is None:
                    raise AssessmentError('live_closed', '這次即時聆聽已結束。')
            ws.send(json.dumps(data, ensure_ascii=False, separators=(',', ':')))

    def append(self, seq, data):
        if type(seq) is not int or seq < 0:
            raise AssessmentError('live_sequence', '錄音片段順序不正確。')
        if not isinstance(data, bytes) or not 2 <= len(data) <= MAX_CHUNK or len(data) % 2:
            raise AssessmentError('live_audio_format', '即時錄音需為 24 kHz 單聲道 PCM16。')
        # Serialize validation + send + sequence increment against other appends.
        with self._lock:
            if self.state != 'listening':
                raise AssessmentError('live_closed', '這次即時聆聽已結束。')
            if seq != self._audio_seq:
                raise AssessmentError('live_sequence', '錄音片段順序不正確。')
            if self._clock() - self._started > MAX_SECONDS + .5 or self._audio_bytes + len(data) > MAX_SECONDS * RATE * 2:
                raise AssessmentError('live_limit', '每次即時聆聽最多 25 秒。')
            try:
                self._send({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(data).decode('ascii')})
            except Exception:
                self.fail('live_connection', '即時聆聽已中斷，錄音仍可繼續。')
                raise AssessmentError('live_connection', '即時聆聽已中斷，錄音仍可繼續。') from None
            self._audio_bytes += len(data)
            self._audio_seq += 1
            self._last_audio = self._clock()
            return {'accepted_seq': seq, 'next_seq': self._audio_seq,
                    'received_seconds': round(self._audio_bytes / (RATE * 2), 4), 'state': self.state}

    def events(self, after):
        if type(after) is not int or after < 0:
            raise AssessmentError('live_cursor', '即時聆聽位置不正確。')
        with self._lock:
            if after > self._event_seq:
                raise AssessmentError('live_cursor', '即時聆聽位置不正確。')
            return {'session_id': self.id, 'state': self.state,
                    'events': [dict(e) for e in self._events if e['seq'] > after],
                    'last_seq': self._event_seq}

    def stop(self, commit=True):
        if type(commit) is not bool:
            raise AssessmentError('invalid_request', '請求格式不正確。')
        with self._lock:
            if self.state in ('closed', 'error'):
                return self.summary()
            if not commit or self.state == 'connecting':
                self.close('cancelled')
                return self.summary()
            if self.state == 'finishing':
                return self.summary()
            if self._audio_bytes < RATE * 2 // 10:
                self.close('no_audio')
                return self.summary()
            self.state = 'finishing'
            self._finish_at = self._clock()
            try:
                self._send({'type': 'input_audio_buffer.commit'})
            except Exception:
                self.fail('live_connection', '即時聆聽已中斷，錄音仍可評測。')
            return self.summary()

    def _receive(self):
        while self.state not in ('closed', 'error'):
            try:
                raw = self._ws.recv()
                if raw == '' or raw is None:
                    self.fail('live_connection', '即時聆聽已中斷，錄音仍可評測。')
                    return
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
                    self.fail('live_connection', '即時聆聽已中斷，錄音仍可評測。')
                return

    def handle_event(self, event):
        """Reconcile actual provider deltas/completion for exactly one utterance."""
        with self._lock:
            if self.state in ('closed', 'error'):
                return
            kind = event.get('type')
            if kind == 'session.updated' and self.state == 'connecting':
                self.state = 'listening'
                self._started = self._last_audio = self._clock()
                self._ready.set()
                return
            if kind in ('error', 'conversation.item.input_audio_transcription.failed'):
                # Provider details can contain echoed content: never expose them.
                self.fail('live_provider_error', '即時聆聽暫時不可用，仍可錄音後評測。')
                return
            if kind not in ('input_audio_buffer.committed', 'conversation.item.input_audio_transcription.delta',
                            'conversation.item.input_audio_transcription.completed'):
                return
            item = event.get('item_id')
            if not isinstance(item, str) or not 1 <= len(item) <= 128:
                self.fail('live_protocol', '即時聆聽內容未能對齊，請重新試一次。')
                return
            if self._item_id is not None and item != self._item_id:
                self.fail('live_protocol', '即時聆聽內容未能對齊，請重新試一次。')
                return
            self._item_id = item
            if kind == 'input_audio_buffer.committed':
                self._committed_id = item
                return
            if event.get('content_index', 0) != 0:
                self.fail('live_protocol', '即時聆聽內容未能對齊，請重新試一次。')
                return
            final = kind.endswith('.completed')
            part = event.get('transcript' if final else 'delta')
            if not isinstance(part, str):
                self.fail('live_protocol', '即時聆聽內容未能對齊，請重新試一次。')
                return
            text = part if final else self._text + part
            if len(text) > MAX_TRANSCRIPT:
                self.fail('live_limit', '即時聆聽內容過長，請分成短句練習。')
                return
            if text != self._text or final:
                self._text = text
                self._emit({'type': 'transcript', 'text': text, 'item_id': item, 'item_index': 0, 'final': final})
            if final:
                self.close('completed')

    def check_deadlines(self):
        with self._lock:
            now = self._clock()
            if self.state == 'connecting' and now - self._started >= 9:
                self.fail('live_timeout', '即時聆聽連接逾時。')
            elif self.state == 'listening':
                if now - self._last_audio >= 7:
                    self.close('inactive')
                elif now - self._started >= MAX_SECONDS:
                    self.stop(True)
            elif self.state == 'finishing' and now - self._finish_at >= 12:
                self.fail('live_timeout', '即時文字未能完成，錄音仍可評測。')

    def _watch(self):
        while self.state not in ('closed', 'error'):
            time.sleep(.2)
            self.check_deadlines()

    def fail(self, code, message):
        with self._lock:
            if self.state in ('closed', 'error'):
                return
            self._error_code = code
            self._emit({'type': 'error', 'code': code, 'message': message})
            self.close('error', error=True)

    def close(self, reason='cancelled', error=False):
        with self._lock:
            if self.state in ('closed', 'error'):
                return
            self.state = 'error' if error else 'closed'
            self._closed_at = self._clock()
            self._emit({'type': 'closed', 'reason': reason})
            self._ready.set()
            ws, self._ws = self._ws, None
        if ws is not None:
            try:
                # Immediate socket close avoids waiting for a hostile/absent peer.
                ws.shutdown()
            except Exception:
                pass


class LiveManager:
    def __init__(self, factory=None):
        self._lock = threading.Lock()
        self._session = None
        self._factory = factory
        self._starts = collections.deque()

    def start(self, key, generation):
        with self._lock:
            if self._session and self._session.state not in ('closed', 'error'):
                raise AssessmentError('live_busy', '另一段即時聆聽仍在進行。')
            now = time.monotonic()
            while self._starts and now - self._starts[0] >= 61:
                self._starts.popleft()
            if len(self._starts) >= 5:
                raise AssessmentError('local_rate_limit', '即時聆聽較頻密，請稍後再試。')
            self._starts.append(now)
            session = LiveSession(generation, factory=self._factory)
            self._session = session
        return session.connect(key)

    def get(self, session_id, generation):
        with self._lock:
            session = self._session
            if not isinstance(session_id, str) or not session or not secrets.compare_digest(session.id, session_id):
                raise AssessmentError('live_session', '這次即時聆聽已結束，請重新開始。')
            if session.generation != generation:
                raise AssessmentError('configuration_changed', '語音連線已變更，請重新開始。')
            if session._closed_at is not None and time.monotonic() - session._closed_at > 45:
                self._session = None
                raise AssessmentError('live_session', '這次即時聆聽已結束，請重新開始。')
            return session

    def cancel(self, reason='configuration_changed'):
        with self._lock:
            session = self._session
        if session:
            session.close(reason)
