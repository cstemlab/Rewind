"""Google Cloud adapter: ADC only, bounded requests, no browser API keys.

Gemini feedback is experimental direct-audio coaching, not a calibrated
Cantonese pronunciation/tone assessment. Cloud TTS reads reviewed text; it does
not return an independently verified transcript or word timings.
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import threading
import urllib.error
import urllib.request

import creator
from assess import AssessmentError, _NoRedirect, _reject_json_constant
from azure_feedback import validate_wav
from openai_feedback import SYSTEM_PROMPT, normalize_openai, LANGUAGES, STATES

DEFAULT_MODEL = 'gemini-3.5-flash'
DEFAULT_VOICE = 'yue-HK-Chirp3-HD-Aoede'
# Curated Cantonese voices from Google's supported-voices table. Request input
# may choose only these IDs; a syntactically plausible voice is not sufficient.
VOICES = tuple(
    {'id': 'yue-HK-Chirp3-HD-' + name, 'label': name, 'gender': gender, 'quality': 'Chirp 3 HD'}
    for name, gender in (('Aoede', 'female'), ('Kore', 'female'), ('Sulafat', 'female'),
                         ('Puck', 'male'), ('Charon', 'male'), ('Fenrir', 'male'))
) + tuple(
    {'id': 'yue-HK-Standard-' + name, 'label': 'Standard ' + name, 'gender': gender, 'quality': 'Standard'}
    for name, gender in (('A', 'female'), ('C', 'female'), ('B', 'male'), ('D', 'male'))
)
SCOPES = ('https://www.googleapis.com/auth/cloud-platform',)
MAX_RESPONSE = 12_000_000
PROJECT_RE = re.compile(r'[a-z][a-z0-9-]{4,61}[a-z0-9]\Z')
LOCATION_RE = re.compile(r'(?:global|[a-z]+-[a-z]+[0-9])\Z')
MODEL_RE = re.compile(r'gemini-[a-zA-Z0-9.-]{1,80}\Z')
VOICE_IDS = frozenset(item['id'] for item in VOICES)


def fail(code, message):
    raise AssessmentError(code, message)


class ADCTransport:
    """Use the attached runtime identity; never create/export a service key.

    Google-auth is imported lazily, so mock-only tests need no installed SDK.
    Credential refresh is serialized; each API request has a separate socket.
    """
    def __init__(self, project):
        self.project = project
        self.credentials = None
        self.lock = threading.Lock()

    def _headers(self):
        try:
            import google.auth
            from google.auth.transport.requests import Request
            with self.lock:
                if self.credentials is None:
                    self.credentials, _ = google.auth.default(scopes=SCOPES)
                if not self.credentials.valid:
                    self.credentials.refresh(Request())
                return {'Authorization': 'Bearer ' + self.credentials.token,
                        'x-goog-user-project': self.project,
                        'Content-Type': 'application/json', 'Accept': 'application/json'}
        except Exception:
            fail('google_auth', 'Google Cloud 服務尚未完成身分設定，請聯絡服務提供者。')

    def __call__(self, endpoint, payload, limit=MAX_RESPONSE):
        request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                         method='POST', headers=self._headers())
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=90) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                fail('google_response_size', 'Google 回覆超出大小限制，請縮短內容再試。')
            result = json.loads(raw.decode('utf-8'), parse_constant=_reject_json_constant)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except AssessmentError:
            raise
        except urllib.error.HTTPError as exc:
            code = int(exc.code)
            exc.close()
            message = {400: 'Google 未接受這次請求，請縮短內容再試。',
                       401: 'Google Cloud 服務身分已失效。',
                       403: 'Google Cloud 專案尚未獲准使用這項功能。',
                       404: 'Google Cloud 專案目前無法使用選定模型。',
                       429: 'Google 的用量或頻率限制已達上限，請稍後再試。'}.get(code, 'Google 服務暫時未能完成請求。')
            fail('google_http_' + str(code), message)
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            fail('google_network', '未能連接 Google Cloud，請稍後再試。')
        except (ValueError, UnicodeError, RecursionError):
            fail('google_response', 'Google 回覆格式不完整，請再試。')


def response_text(raw):
    """Reject incomplete, blocked, tool-bearing, and non-text responses."""
    if not isinstance(raw, dict):
        fail('google_response', 'Google 回覆格式不完整。')
    candidates = raw.get('candidates')
    prompt_feedback = raw.get('promptFeedback', {})
    if not isinstance(prompt_feedback, dict) or prompt_feedback.get('blockReason') or not isinstance(candidates, list) or len(candidates) != 1:
        fail('google_response', 'Google 未能完成這段內容，請縮短內容再試。')
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get('finishReason') != 'STOP':
        fail('google_response', 'Google 未能完整完成這段內容，請縮短內容再試。')
    content = candidate.get('content')
    parts = content.get('parts') if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        fail('google_response', 'Google 回覆沒有可用文字。')
    texts = []
    for part in parts:
        if not isinstance(part, dict) or 'functionCall' in part or 'inlineData' in part:
            fail('google_response', 'Google 回覆格式不正確。')
        if part.get('thought') is True:
            continue
        if not isinstance(part.get('text'), str):
            fail('google_response', 'Google 回覆格式不正確。')
        texts.append(part['text'])
    text = ''.join(texts)
    if not text or len(text) > 350_000:
        fail('google_response', 'Google 回覆超出大小限制。')
    return text


ASSESSMENT_SCHEMA = {
    'type': 'OBJECT', 'required': ['heard_language', 'heard_text', 'groups'],
    'properties': {
        'heard_language': {'type': 'STRING', 'enum': sorted(LANGUAGES)},
        'heard_text': {'type': 'STRING'},
        'groups': {'type': 'ARRAY', 'items': {
            'type': 'OBJECT', 'required': ['text', 'start', 'end', 'state', 'reason'],
            'properties': {'text': {'type': 'STRING'}, 'start': {'type': 'INTEGER'},
                           'end': {'type': 'INTEGER'}, 'state': {'type': 'STRING', 'enum': sorted(STATES)},
                           'reason': {'type': 'STRING'}}}}}}
TRANSLATION_SCHEMA = {'type': 'OBJECT', 'required': ['title', 'text'],
                      'properties': {'title': {'type': 'STRING'}, 'text': {'type': 'STRING'}}}


class GoogleProvider:
    def __init__(self, project=None, location=None, model=None, voice=None, transport=None):
        self.project = project or os.environ.get('GOOGLE_CLOUD_PROJECT', '')
        self.location = location or os.environ.get('GOOGLE_CLOUD_LOCATION', 'global')
        self.model = model or os.environ.get('REWIND_GOOGLE_MODEL', DEFAULT_MODEL)
        self.voice = voice or os.environ.get('REWIND_GOOGLE_VOICE', DEFAULT_VOICE)
        if not PROJECT_RE.fullmatch(self.project) or not LOCATION_RE.fullmatch(self.location):
            fail('google_config', 'Google Cloud 專案或地區設定不正確。')
        if not MODEL_RE.fullmatch(self.model) or self.voice not in VOICE_IDS:
            fail('google_config', 'Google Cloud 模型或聲音設定不正確。')
        host = 'aiplatform.googleapis.com' if self.location == 'global' else self.location + '-aiplatform.googleapis.com'
        self.endpoint = f'https://{host}/v1/projects/{self.project}/locations/{self.location}/publishers/google/models/{self.model}:generateContent'
        self.transport = transport or ADCTransport(self.project)

    def _generate(self, instruction, parts, max_tokens=18000, schema=None):
        config = {'responseMimeType': 'application/json', 'maxOutputTokens': max_tokens,
                  'temperature': 1.0, 'thinkingConfig': {'thinkingLevel': 'LOW'}}
        if schema:
            config['responseSchema'] = schema
        payload = {'systemInstruction': {'parts': [{'text': instruction}]},
                   'contents': [{'role': 'user', 'parts': parts}], 'generationConfig': config}
        raw = self.transport(self.endpoint, payload, 1_000_000)
        try:
            result = json.loads(response_text(raw), parse_constant=_reject_json_constant)
        except (ValueError, RecursionError):
            fail('google_response', 'Google 回覆未能轉成可靠的練習內容。')
        if not isinstance(result, dict):
            fail('google_response', 'Google 回覆格式不正確。')
        return result

    def _json(self, instruction, data, max_tokens=18000, schema=None):
        return self._generate(instruction, [{'text': json.dumps(data, ensure_ascii=False)}], max_tokens, schema)

    def coach(self, data, reference, unused_key=None):
        if not isinstance(reference, str) or not reference.strip() or len(reference) > 200:
            fail('invalid_reference', '請選擇 200 字以內的短句。')
        validate_wav(data)
        target = {'reference': reference, 'indexed_characters': [{'index': i, 'character': c} for i, c in enumerate(reference)]}
        raw = self._generate(SYSTEM_PROMPT, [
            {'text': json.dumps(target, ensure_ascii=False)},
            {'inlineData': {'mimeType': 'audio/wav', 'data': base64.b64encode(data).decode('ascii')}}],
            10000, ASSESSMENT_SCHEMA)
        # Reuse only the strict span/language validator, never its HTTP client.
        normalized = normalize_openai({'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps(raw, ensure_ascii=False)}}]}, reference)
        normalized.update(provider='gemini', model=self.model)
        return normalized

    def translate(self, source, title, mode, unused_key=None):
        text = creator.clean_text(source)
        if mode not in creator.MODES:
            fail('invalid_mode', '請選擇忠實或初學者模式。')
        raw = self._json(creator.TRANSLATION_PROMPT, {'source': text, 'title': creator.safe_title(title, ''), 'mode': mode},
                         schema=TRANSLATION_SCHEMA)
        if set(raw) != {'title', 'text'}:
            fail('creator_response', '譯稿格式不完整。')
        return creator.validate_draft({**raw, 'mode': mode})

    def plan(self, draft, unused_key=None, check=None):
        """Same bounded planning contract, with no rewriting of reviewed text."""
        draft = creator.validate_draft(draft)
        units = creator.tokenize(draft['text'])
        spans = creator.source_sentences(units)
        han = {str(i): u['text'] for i, u in enumerate(units) if creator.HAN.fullmatch(u['text'])}
        hints = []
        if han:
            payload = {'script': draft['text'], 'han_units': han}
            for attempt in range(2):
                if check:
                    check()
                raw = self._json(creator.PLAN_PROMPT, payload, 48000)
                errors = creator.reading_errors(raw, han)
                if not errors:
                    break
                if attempt:
                    fail('invalid_readings', '未能取得完整粵拼，請再試。已確認的稿件保持不變。')
                payload = {**payload, 'invalid_ids': errors}
            for ident in han:
                units[int(ident)]['jyutping'] = raw['readings'][ident]
            proposed = raw.get('break_after', [])
            if isinstance(proposed, list) and len(proposed) <= len(han):
                hints = [int(i) for i in proposed if isinstance(i, str) and i in han]
        result = [{'section': draft['title'], 'text': ''.join(u['text'] for u in units[a:b]),
                   'units': units[a:b], 'parts': creator.hinted_phrases(units, a, b, hints)} for a, b in spans]
        if ''.join(row['text'] for row in result) != draft['text']:
            fail('changed_draft', '練習分段與已確認稿件不同。')
        return result

    def select_voice(self, voice=None):
        selected = self.voice if voice is None else voice
        if not isinstance(selected, str) or selected not in VOICE_IDS:
            fail('invalid_voice', '請重新選擇目前服務提供的粵語聲音。')
        return selected

    def narrate(self, text, unused_key=None, voice=None):
        selected = self.select_voice(voice)
        if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 4500:
            fail('tts_text_size', '單句較長，請在稿件中分句後再生成。')
        # Plain text, never SSML: source cannot change language, voice or endpoint.
        payload = {'input': {'text': text}, 'voice': {'languageCode': 'yue-HK', 'name': selected},
                   'audioConfig': {'audioEncoding': 'LINEAR16', 'sampleRateHertz': 24000}}
        raw = self.transport('https://texttospeech.googleapis.com/v1/text:synthesize', payload, MAX_RESPONSE)
        encoded = raw.get('audioContent')
        if not isinstance(encoded, str) or len(encoded) > 10_000_000:
            fail('invalid_audio', 'Google 未能傳回完整示範錄音。')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            fail('invalid_audio', 'Google 示範錄音格式不正確。')
        pcm, rate = creator.read_wav(data)
        return {'pcm': pcm, 'rate': rate, 'voice': selected, 'transcript': None, 'input_text': text,
                'text_verification': 'plain-text-tts-input-only; not-independent-transcription'}

    def capabilities(self):
        result = creator.capabilities(True)
        result['models'] = {'text': self.model, 'audio': 'google-cloud-text-to-speech'}
        result['voice'] = self.voice
        result['default_voice'] = self.voice
        result['voices'] = [dict(item) for item in VOICES]
        return result

    def decorate_session(self, session):
        """Call on completed creator result before returning it to a browser."""
        # The job captured its own choice. Never overwrite it with a mutable or
        # provider-wide default when polling, exporting or serving another user.
        source = {**session['source'], 'voice': self.select_voice(session['source'].get('voice')),
                  'provider': 'gemini', 'text_model': self.model,
                  'audio_model': 'google-cloud-text-to-speech',
                  'text_verification': 'plain-text-tts-input-only; not-independent-transcription'}
        return {**session, 'source': source}
