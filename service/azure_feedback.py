"""Conservative word-group practice feedback; not a lexical-tone diagnosis."""
from __future__ import annotations
from array import array
import io
import sys
import unicodedata
import wave
from assess import AssessmentError, normalize_azure

MAX_WAV_BYTES = 820_000
MAX_SECONDS = 25
PASS_SCORE = 80
LIMITATIONS = [
    'Word-group practice feedback; not an independent score for every character.',
    'Cantonese lexical-tone accuracy has not been validated.',
    'Speech recognition can mishear words; uncertain matches are not accepted.',
]


def validate_wav(data: bytes) -> dict:
    if not isinstance(data, bytes) or not 44 <= len(data) <= MAX_WAV_BYTES:
        raise AssessmentError('audio_size', '錄音大小不合適，請錄製 25 秒以內的短句。')
    try:
        with wave.open(io.BytesIO(data), 'rb') as stream:
            channels, width, rate, frames, compression, _ = stream.getparams()
            if (channels, width, rate, compression) != (1, 2, 16000, 'NONE'):
                raise AssessmentError('audio_format', '需要 16 kHz、單聲道、16-bit PCM WAV 錄音。')
            duration = frames / rate
            if duration > MAX_SECONDS:
                raise AssessmentError('audio_duration', '請將每次錄音控制在 25 秒以內。')
            pcm = stream.readframes(frames)
            if len(pcm) != frames * 2:
                raise AssessmentError('audio_truncated', '錄音資料不完整，請再試一次。')
    except (wave.Error, EOFError, ValueError, OverflowError):
        raise AssessmentError('audio_format', '無法讀取這段 WAV 錄音。') from None
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    peak = max((abs(v) for v in samples), default=0)
    return {'duration_seconds': round(duration, 4), 'no_speech': duration < .20 or peak == 0}


def _compact(text: str):
    """Preserve code-point offsets; ignore punctuation. No script/homophone guessing."""
    output = []
    for i, char in enumerate(text):
        if char.isspace() or unicodedata.category(char)[0] in ('P', 'Z', 'C'):
            continue
        normalized = unicodedata.normalize('NFKC', char).casefold()
        if len(normalized) != 1:
            normalized = char
        output.append((normalized, i))
    return output


def align_chars(expected: list[str], heard: list[str]) -> list[dict]:
    """Global edit alignment allows substitutions, omissions, repeats and recovery."""
    n, m = len(expected), len(heard)
    if n > 200 or m > 1200:
        raise AssessmentError('response_too_long', '評測文字超出短句範圍。')
    costs = [[0] * (m + 1) for _ in range(n + 1)]
    moves = [[''] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        costs[i][0], moves[i][0] = i, 'omission'
    for j in range(1, m + 1):
        costs[0][j], moves[0][j] = j, 'insertion'
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = expected[i - 1] == heard[j - 1]
            candidates = [(costs[i - 1][j - 1] + (0 if same else 1), 0, 'match' if same else 'substitution'),
                          (costs[i - 1][j] + 1, 1, 'omission'),
                          (costs[i][j - 1] + 1, 2, 'insertion')]
            costs[i][j], _, moves[i][j] = min(candidates)
    result = []
    i, j = n, m
    while i or j:
        kind = moves[i][j]
        result.append({'expected_index': i - 1 if kind != 'insertion' else None,
                       'heard_index': j - 1 if kind != 'omission' else None, 'kind': kind})
        i -= kind != 'insertion'
        j -= kind != 'omission'
    return list(reversed(result))


def recognition_text(raw: dict | None) -> tuple[str, str]:
    if not isinstance(raw, dict) or raw.get('RecognitionStatus') != 'Success':
        return '', 'unavailable'
    candidates = raw.get('NBest')
    if candidates is not None and (not isinstance(candidates, list) or (candidates and not isinstance(candidates[0], dict))):
        return '', 'unavailable'
    top = (candidates or [{}])[0]
    value = top.get('Display') or raw.get('DisplayText') or top.get('Lexical')
    if not isinstance(value, str) or len(value) > 1200 or not _compact(value):
        return '', 'unavailable'
    return value, 'available'


def no_speech_result(reference: str) -> dict:
    return {'provider': 'azure', 'reference': reference, 'recognized_text': '', 'status': 'no_speech',
            'overall': {'accuracy': None, 'fluency': None, 'completeness': None}, 'groups': [],
            'crosscheck': {'status': 'unavailable', 'reason': 'no_speech'}, 'cloud_requests': 0,
            'limitations': LIMITATIONS.copy(), 'lexical_tone_validated': False}


def build_feedback(reference: str, assessment: dict, recognition: dict | None,
                   crosscheck_error: str | None = None) -> dict:
    normalized = normalize_azure(assessment)
    heard_text, cross_status = recognition_text(recognition)
    result = {'provider': 'azure', 'reference': reference, 'recognized_text': heard_text,
              'status': 'assessed', 'overall': {'accuracy': None, 'fluency': None, 'completeness': None},
              'groups': [], 'crosscheck': {'status': cross_status}, 'cloud_requests': 2,
              'limitations': LIMITATIONS.copy(), 'lexical_tone_validated': False, 'pass_threshold': PASS_SCORE}
    if crosscheck_error:
        result['crosscheck']['reason'] = crosscheck_error
    if normalized['status'] != 'assessed':
        result['status'] = 'no_match'
        result['crosscheck']['reason'] = 'assessment_no_match'
        return result
    scores = normalized['scores']
    result['overall'] = {'accuracy': scores['AccuracyScore'], 'fluency': scores['FluencyScore'],
                         'completeness': scores['CompletenessScore']}
    expected, heard = _compact(reference), _compact(heard_text)
    cross = align_chars([c for c, _ in expected], [c for c, _ in heard]) if cross_status == 'available' else []
    cross_map = {a['expected_index']: a for a in cross if a['expected_index'] is not None}
    result['crosscheck']['insertion_count'] = sum(a['kind'] == 'insertion' for a in cross)
    pa_chars, owners = [], []
    groups = normalized['word_groups']
    if len(groups) > 400:
        raise AssessmentError('response_too_long', '評測結果超出短句範圍。')
    for gi, group in enumerate(groups):
        if group['error_type'] == 'Insertion':
            continue
        for char, _ in _compact(group['text']):
            pa_chars.append(char)
            owners.append(gi)
    pa_alignment = align_chars([c for c, _ in expected], pa_chars)
    pa_map = {a['heard_index']: a for a in pa_alignment if a['heard_index'] is not None}
    covered = set()
    for gi, group in enumerate(groups):
        indexes = [i for i, owner in enumerate(owners) if owner == gi]
        correspondence = [pa_map.get(i) for i in indexes]
        if not indexes or any(a is None or a['kind'] != 'match' for a in correspondence):
            continue
        target_indexes = [a['expected_index'] for a in correspondence]
        if target_indexes != list(range(target_indexes[0], target_indexes[0] + len(target_indexes))):
            continue
        start, end = expected[target_indexes[0]][1], expected[target_indexes[-1]][1] + 1
        covered.update(target_indexes)
        errors = [cross_map.get(i, {}).get('kind', 'unknown') for i in target_indexes]
        score, error_type = group['accuracy'], group['error_type']
        if error_type == 'Omission':
            state, reason = 'omitted', 'not_matched'
        elif cross_status != 'available':
            state, reason = 'uncertain', 'crosscheck_unavailable'
        elif any(k in ('substitution', 'omission') for k in errors):
            state, reason = 'retry', 'different_or_unmatched_words'
        elif any(k != 'match' for k in errors) or score is None:
            state, reason = 'uncertain', 'mapping_unavailable'
        elif error_type == 'Mispronunciation' or score < 60:
            state, reason = 'retry', 'pronunciation_review'
        elif score < PASS_SCORE:
            state, reason = 'close', 'minor_pronunciation_review'
        else:
            state, reason = 'pass', 'practice_match'
        result['groups'].append({'start': start, 'end': end, 'text': reference[start:end],
                                 'score': score, 'state': state, 'reason': reason,
                                 'error_type': error_type, 'word_group': True,
                                 'offset_seconds': group['offset_seconds'], 'duration_seconds': group['duration_seconds']})
    missing = [i for i in range(len(expected)) if i not in covered]
    runs = []
    for i in missing:
        if runs and runs[-1][-1] + 1 == i:
            runs[-1].append(i)
        else:
            runs.append([i])
    for run in runs:
        start, end = expected[run[0]][1], expected[run[-1]][1] + 1
        result['groups'].append({'start': start, 'end': end, 'text': reference[start:end], 'score': None,
                                 'state': 'uncertain', 'reason': 'mapping_unavailable', 'error_type': None, 'word_group': True})
    result['groups'].sort(key=lambda g: g['start'])
    return result
