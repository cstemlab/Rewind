"""Bounded pronunciation-assessment pilot; no cloud calls without an explicit request.

CLI keys are read only from environment variables. No key, HTTP request body, or
HTTP headers are written to a report. The callable adapters permit an in-memory
key supplied by the local pilot server. This is a test adapter, not a validated
Cantonese pronunciation or lexical-tone grader.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import Any
import urllib.error
import urllib.request
import uuid
import wave


MAX_AUDIO_BYTES = 10_000_000
MAX_RESPONSE_BYTES = 2_000_000
MAX_ERROR_BYTES = 16_384
TIMEOUT_SECONDS = 35
PROVIDERS = ("cantonese", "azure")
_REGION = re.compile(r"[a-z][a-z0-9-]{0,38}[a-z0-9]\Z")
_SYLLABLE = re.compile(r"[a-z]+[1-9]", re.I)
_SECRET_FIELDS = re.compile(
    r"(?:api[_-]?key|subscription[_-]?key|authorization|password|secret|(?:^|[_-])token(?:$|[_-])|access[_-]?token|refresh[_-]?token)", re.I
)
_MIMES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".flac": "audio/flac", ".ogg": "audio/ogg"}


class AssessmentError(Exception):
    """A deliberately safe, bounded error; never wrap an upstream exception string."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def redact(value: Any, secrets: tuple[str, ...] | list[str] = ()) -> Any:
    """Keep provider response structure, removing credential fields/known values."""
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if _SECRET_FIELDS.search(str(k)) else redact(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    return value


def _reference(text: str) -> str:
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        raise AssessmentError("invalid_reference", "Reference text must contain 1–1000 characters.")
    return text.strip()


def _key(key: str) -> str:
    if not isinstance(key, str) or not key.strip():
        raise AssessmentError("missing_key", "A service key is required; keep it in memory or an environment variable.")
    value = key.strip()
    if len(value) > 4096 or any(c in value for c in "\r\n\x00"):
        raise AssessmentError("invalid_key", "The service key format is invalid.")
    return value


def validate_region(region: str) -> str:
    if not isinstance(region, str) or not _REGION.fullmatch(region):
        raise AssessmentError("invalid_region", "AZURE_SPEECH_REGION must be a region name such as eastasia, not a URL.")
    return region


def read_audio(path: str | Path, provider: str) -> tuple[bytes, dict]:
    if provider not in PROVIDERS:
        raise AssessmentError("invalid_provider", "Choose cantonese or azure.")
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in _MIMES or (provider == "azure" and suffix != ".wav"):
        raise AssessmentError("audio_format", "Azure requires PCM WAV; cantonese.ai accepts WAV, MP3, M4A, FLAC or OGG.")
    try:
        if path.stat().st_size > MAX_AUDIO_BYTES:
            raise AssessmentError("audio_too_large", "Audio must be no larger than 10 MB.")
        with path.open("rb") as handle:
            data = handle.read(MAX_AUDIO_BYTES + 1)
    except OSError:
        raise AssessmentError("audio_unreadable", "The selected audio file could not be read.") from None
    if not data:
        raise AssessmentError("empty_audio", "The selected audio file is empty.")
    if len(data) > MAX_AUDIO_BYTES:
        raise AssessmentError("audio_too_large", "Audio must be no larger than 10 MB.")
    info = {"filename": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mime": _MIMES[suffix]}
    if suffix == ".wav":
        try:
            with wave.open(io.BytesIO(data), "rb") as stream:
                channels, width, rate, frames, compression, _ = stream.getparams()
                duration = frames / rate if rate else 0
                decoded = stream.readframes(frames)
                if len(decoded) != frames * channels * width:
                    raise AssessmentError("audio_truncated", "The WAV data is truncated.")
                info.update({"duration_seconds": duration, "sample_rate": rate, "channels": channels, "sample_width": width})
                if duration <= 0:
                    raise AssessmentError("empty_audio", "The WAV file contains no audio frames.")
                if provider == "azure" and (channels != 1 or width != 2 or rate != 16000 or compression != "NONE"):
                    raise AssessmentError("audio_format", "Azure pilot input must be 16 kHz, mono, 16-bit PCM WAV.")
                if provider == "azure" and duration > 30:
                    raise AssessmentError("audio_duration", "Azure pronunciation-assessment input must not exceed 30 seconds.")
        except (wave.Error, EOFError, ValueError):
            raise AssessmentError("audio_format", "The WAV file could not be decoded as PCM audio.") from None
    return data, info


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AssessmentError("redirect_blocked", "The service redirected the request; no credentials were forwarded.")


def _reject_json_constant(_value):
    raise ValueError("Non-finite JSON number")


def _classify_http_error(exc: urllib.error.HTTPError) -> AssessmentError:
    """Inspect only a bounded known error signature; never expose response text.

    A 403 alone cannot establish missing account access. Cantonese.ai can return
    a Cloudflare protection error before the assessment API evaluates the key.
    This classification does not retry, change the client signature, or bypass
    the provider's protection.
    """
    status = int(exc.code)
    blocked_signature = False
    try:
        if status == 403:
            body = exc.read(MAX_ERROR_BYTES + 1)
            if len(body) <= MAX_ERROR_BYTES:
                try:
                    detail = json.loads(body.decode("utf-8"), parse_constant=_reject_json_constant)
                    blocked_signature = (
                        isinstance(detail, dict)
                        and detail.get("cloudflare_error") is True
                        and detail.get("error_code") in (1010, "1010")
                    )
                except (UnicodeError, ValueError, RecursionError):
                    pass
    except (OSError, TimeoutError, urllib.error.URLError):
        pass
    finally:
        exc.close()
    if blocked_signature:
        return AssessmentError(
            "access_protection_blocked",
            "The site's access protection blocked this client signature. The site owner must resolve the block; no automatic retry was made.",
        )
    hints = {
        400: "The service rejected the audio or reference text.",
        401: "The service key was not accepted.",
        403: "The service denied this request. The response does not establish an account-permission problem.",
        429: "The service quota or rate limit was reached; no automatic retry was made.",
        503: "The assessment service is temporarily unavailable; no automatic retry was made.",
    }
    return AssessmentError(f"http_{status}", hints.get(status, "The assessment request failed at the service."))


def _post_json(request: urllib.request.Request) -> dict:
    """No automatic retry: retries can consume quota and repeat audio uploads."""
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise AssessmentError("response_too_large", "The service returned an unexpectedly large response.")
        raw = json.loads(body.decode("utf-8"), parse_constant=_reject_json_constant)
        if not isinstance(raw, dict):
            raise AssessmentError("malformed_response", "The service did not return a JSON object.")
        return raw
    except AssessmentError:
        raise
    except urllib.error.HTTPError as exc:
        raise _classify_http_error(exc) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise AssessmentError("network_error", "The assessment service could not be reached or timed out.") from None
    except (UnicodeError, ValueError):
        raise AssessmentError("malformed_response", "The service returned invalid JSON.") from None


def assess_cantonese(audio_path: str | Path, reference_text: str, api_key: str) -> dict:
    """One real cloud request; callers must obtain explicit user intent first.

    The result is parsed provider JSON. Call redact before displaying or saving.
    No credential lookup, file writes or log output occurs in this function.
    """
    text = _reference(reference_text)
    key = _key(api_key)
    data, info = read_audio(audio_path, "cantonese")
    boundary = "RewindBoundary" + uuid.uuid4().hex
    parts = []
    for field, value in (("api_key", key), ("text", text), ("language", "cantonese")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8") + b"\r\n")
    safe_filename = "sample" + Path(audio_path).suffix.lower()
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="{safe_filename}"\r\n'
                  f'Content-Type: {info["mime"]}\r\n\r\n').encode())
    parts.extend([data, f"\r\n--{boundary}--\r\n".encode()])
    request = urllib.request.Request("https://cantonese.ai/api/score-pronunciation", data=b"".join(parts), method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    request.add_header("Accept", "application/json")
    return _post_json(request)


def assess_azure(audio_path: str | Path, reference_text: str, api_key: str, region: str) -> dict:
    """One real cloud request using Azure's regional short-audio endpoint.

    Regional endpoint verified against the official Azure-Samples repository:
    Cognitive-Speech-TTS/PronunciationAssessment/Python/sample.py.
    """
    data, _ = read_audio(audio_path, "azure")
    return assess_azure_bytes(data, reference_text, api_key, region)


def _azure_request(data: bytes, api_key: str, region: str) -> urllib.request.Request:
    key, region = _key(api_key), validate_region(region)
    url = f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1?language=zh-HK&format=detailed"
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Ocp-Apim-Subscription-Key", key)
    request.add_header("Content-Type", "audio/wav; codecs=audio/pcm; samplerate=16000")
    request.add_header("Accept", "application/json")
    return request


def assess_azure_bytes(data: bytes, reference_text: str, api_key: str, region: str) -> dict:
    """One PA request; the server validates the bounded in-memory WAV first."""
    text = _reference(reference_text)
    config = {"ReferenceText": text, "GradingSystem": "HundredMark", "Granularity": "Phoneme",
              "Dimension": "Comprehensive", "EnableMiscue": True}
    config64 = base64.b64encode(json.dumps(config, ensure_ascii=False).encode("utf-8")).decode("ascii")
    request = _azure_request(data, api_key, region)
    request.add_header("Pronunciation-Assessment", config64)
    request.add_header("Content-Type", "audio/wav; codecs=audio/pcm; samplerate=16000")
    request.add_header("Accept", "application/json")
    return _post_json(request)


def recognize_azure_bytes(data: bytes, api_key: str, region: str) -> dict:
    """One independent zh-HK recognition request, without reference or hints."""
    return _post_json(_azure_request(data, api_key, region))


def _score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0 <= value <= 100 else None


def tokenize_jyutping(value: str) -> list[str]:
    if not isinstance(value, str) or len(value) > 10000:
        raise AssessmentError("malformed_response", "The provider returned invalid Jyutping.")
    tokens = [m.group().lower() for m in _SYLLABLE.finditer(value)]
    remainder = _SYLLABLE.sub("", value)
    if re.search(r"[^\s,.;:!?，。；：！？、'’\-–—/()（）]", remainder):
        raise AssessmentError("malformed_response", "The provider returned Jyutping that cannot be safely aligned.")
    if len(tokens) > 1000:
        raise AssessmentError("malformed_response", "The provider returned too many syllables.")
    return tokens


def align_jyutping(expected: list[str], heard: list[str]) -> list[dict]:
    """Global edit alignment permits gaps and recovery; indexes are syllables.

    A tone-digit difference is an observed difference between provider strings,
    not proof that the speaker made an acoustic error. Repeated syllables may
    have multiple equally valid alignments; these results have no timestamps.
    """
    if max(len(expected), len(heard)) > 1000:
        raise AssessmentError("alignment_too_large", "The pilot supports up to 1000 syllables per comparison.")
    n, m = len(expected), len(heard)
    costs = [[0] * (m + 1) for _ in range(n + 1)]
    moves = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        costs[i][0], moves[i][0] = 2 * i, "omission"
    for j in range(1, m + 1):
        costs[0][j], moves[0][j] = 2 * j, "insertion"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            a, b = expected[i - 1], heard[j - 1]
            kind = "match" if a == b else "tone_difference" if a[:-1] == b[:-1] else "segmental_difference"
            penalty = {"match": 0, "tone_difference": 1, "segmental_difference": 3}[kind]
            alternatives = [(costs[i - 1][j - 1] + penalty, 0, kind),
                            (costs[i - 1][j] + 2, 1, "omission"),
                            (costs[i][j - 1] + 2, 2, "insertion")]
            cost, _, move = min(alternatives)
            costs[i][j], moves[i][j] = cost, move
    result = []
    i, j = n, m
    while i or j:
        kind = moves[i][j]
        ei = i - 1 if kind != "insertion" else None
        hi = j - 1 if kind != "omission" else None
        result.append({"expected_index": ei, "heard_index": hi,
                       "expected": expected[ei] if ei is not None else None,
                       "heard": heard[hi] if hi is not None else None, "kind": kind,
                       "certainty": "unvalidated_provider_transcription", "pronunciation_correct": None})
        if kind != "insertion":
            i -= 1
        if kind != "omission":
            j -= 1
    result.reverse()
    return result


def normalize_cantonese(raw: dict) -> dict:
    base = {"provider": "cantonese", "locale": "zh-HK", "lexical_tone_validated": False,
            "timing_available": False, "character_mapping_available": False,
            "interpretation": "Tentative comparison of provider Jyutping, not an independently validated pronunciation judgement."}
    if not isinstance(raw, dict) or not isinstance(raw.get("success"), bool):
        raise AssessmentError("malformed_response", "Missing provider success status.")
    if raw["success"] is False:
        return {**base, "status": "provider_error", "alignment": []}
    if raw.get("language", "cantonese") != "cantonese":
        raise AssessmentError("malformed_response", "The service returned a different language.")
    score = _score(raw.get("score"))
    if score is None:
        raise AssessmentError("malformed_response", "Missing or invalid provider score.")
    if "expectedJyutping" not in raw or "transcribedJyutping" not in raw:
        raise AssessmentError("malformed_response", "The provider did not supply the Jyutping needed for comparison.")
    expected = tokenize_jyutping(raw["expectedJyutping"])
    heard = tokenize_jyutping(raw["transcribedJyutping"])
    if not expected:
        raise AssessmentError("malformed_response", "The provider supplied no expected syllables.")
    if not heard:
        return {**base, "status": "no_match", "provider_score": score, "alignment": [],
                "reason": "No reliable syllable transcription; leave all characters undecided."}
    return {**base, "status": "assessed", "provider_score": score,
            "provider_passed": raw.get("passed") if isinstance(raw.get("passed"), bool) else None,
            "expected_syllables": expected, "heard_syllables": heard,
            "alignment": align_jyutping(expected, heard)}


def normalize_azure(raw: dict) -> dict:
    base = {"provider": "azure", "locale": "zh-HK", "lexical_tone_validated": False,
            "character_mapping_available": False,
            "interpretation": "Provider word-group accuracy only; no per-character score or separate Cantonese lexical-tone score is inferred."}
    if not isinstance(raw, dict) or not isinstance(raw.get("RecognitionStatus"), str):
        raise AssessmentError("malformed_response", "Missing Azure recognition status.")
    status = raw["RecognitionStatus"]
    if status != "Success":
        return {**base, "status": "no_match" if status in {"NoMatch", "InitialSilenceTimeout", "BabbleTimeout", "EndOfDictation"} else "provider_error",
                "provider_status": status, "word_groups": []}
    candidates = raw.get("NBest")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise AssessmentError("malformed_response", "Azure returned no detailed assessment candidate.")
    top = candidates[0]
    # REST short-audio uses flat scores; the Speech SDK nests the same fields.
    # Accept both documented shapes without inventing missing measurements.
    pa = top.get("PronunciationAssessment", top)
    if not isinstance(pa, dict):
        raise AssessmentError("malformed_response", "Invalid Azure assessment object.")
    words = top.get("Words", [])
    if not isinstance(words, list):
        raise AssessmentError("malformed_response", "Invalid Azure word-group list.")
    groups = []
    for word in words:
        if not isinstance(word, dict) or not isinstance(word.get("Word"), str):
            raise AssessmentError("malformed_response", "Invalid Azure word-group result.")
        detail = word.get("PronunciationAssessment", word)
        if not isinstance(detail, dict):
            raise AssessmentError("malformed_response", "Invalid Azure word-group assessment.")
        group = {"text": word["Word"], "accuracy": _score(detail.get("AccuracyScore")),
                 "error_type": detail.get("ErrorType") if isinstance(detail.get("ErrorType"), str) else None,
                 "pronunciation_correct": None}
        for source, dest in (("Offset", "offset_seconds"), ("Duration", "duration_seconds")):
            value = word.get(source)
            group[dest] = value / 10_000_000 if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None
        groups.append(group)
    if not groups and _score(pa.get("AccuracyScore")) is None:
        raise AssessmentError("malformed_response", "Azure returned text without pronunciation-assessment results.")
    return {**base, "status": "assessed", "word_groups": groups,
            "scores": {k: _score(pa.get(k)) for k in ("AccuracyScore", "FluencyScore", "CompletenessScore", "PronScore")}}


def preflight(provider: str, environ: dict | None = None) -> dict:
    env = os.environ if environ is None else environ
    if provider not in PROVIDERS:
        raise AssessmentError("invalid_provider", "Choose cantonese or azure.")
    required = ["CANTONESE_AI_API_KEY"] if provider == "cantonese" else ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"]
    missing = [name for name in required if not env.get(name, "").strip()]
    result = {"provider": provider, "ready": not missing, "missing_environment_variables": missing,
              "cloud_called": False, "note": "Credentials are not printed or persisted. Readiness is local configuration only, not a successful service test."}
    if provider == "azure" and env.get("AZURE_SPEECH_REGION"):
        try:
            validate_region(env["AZURE_SPEECH_REGION"])
        except AssessmentError as exc:
            result.update({"ready": False, "error": {"code": exc.code, "message": exc.message}})
    return result


def _credentials(provider: str, env: dict) -> tuple[str, str | None]:
    check = preflight(provider, env)
    if not check["ready"]:
        if "error" in check:
            raise AssessmentError(check["error"]["code"], check["error"]["message"])
        raise AssessmentError("missing_configuration", "Set the required service environment variables; run preflight to list their names.")
    return (_key(env["CANTONESE_AI_API_KEY"]), None) if provider == "cantonese" else (_key(env["AZURE_SPEECH_KEY"]), validate_region(env["AZURE_SPEECH_REGION"]))


def _print_json(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight", help="Check environment variable presence without making a network request.")
    p.add_argument("--provider", choices=PROVIDERS, default="cantonese")
    p = sub.add_parser("assess", help="Send one selected recording to the chosen service.")
    p.add_argument("--provider", choices=PROVIDERS, default="cantonese")
    p.add_argument("--audio", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--run-cloud", action="store_true", help="Explicitly allow this one audio upload and any associated service usage.")
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(args.provider)
            _print_json(result)
            return 0 if result["ready"] else 2
        if not args.run_cloud:
            raise AssessmentError("cloud_not_enabled", "No audio uploaded. Add --run-cloud to explicitly run this service test.")
        reference = _reference(args.text)
        key, region = _credentials(args.provider, os.environ)
        _, info = read_audio(args.audio, args.provider)
        # Reserve the report before spending quota; never overwrite a previous result.
        try:
            writer = Path(args.out).open("x", encoding="utf-8", newline="\n")
        except FileExistsError:
            raise AssessmentError("report_exists", "The report already exists; choose a new output filename.") from None
        except OSError:
            raise AssessmentError("report_unwritable", "The report destination could not be opened; no audio was uploaded.") from None
        start = time.monotonic()
        report = {"schema": "rewind-assessment-pilot-1", "provider": args.provider,
                  "created": datetime.now(timezone.utc).isoformat(), "reference_text": reference,
                  "audio": info, "cloud_called": True, "validation_scope": "An individual provider response, not human-validated pronunciation accuracy."}
        exit_code = 0
        try:
            raw = assess_cantonese(args.audio, reference, key) if args.provider == "cantonese" else assess_azure(args.audio, reference, key, region)
            report["provider_response"] = redact(raw, [key])
            report["provider_response_redacted"] = report["provider_response"] != raw
            try:
                report["normalized"] = normalize_cantonese(raw) if args.provider == "cantonese" else normalize_azure(raw)
            except AssessmentError as exc:
                report["normalized"] = {"status": "malformed_response", "error": {"code": exc.code, "message": exc.message}}
                exit_code = 3
        except AssessmentError as exc:
            report["error"] = {"code": exc.code, "message": exc.message}
            exit_code = 3
        finally:
            report["elapsed_seconds"] = round(time.monotonic() - start, 3)
            with writer:
                json.dump(redact(report, [key]), writer, ensure_ascii=False, allow_nan=False, indent=2)
                writer.write("\n")
        _print_json({"report_saved": True, "status": report.get("normalized", {}).get("status", "request_failed"), "provider": args.provider})
        return exit_code
    except AssessmentError as exc:
        _print_json({"error": {"code": exc.code, "message": exc.message}, "cloud_called": False})
        return 2


if __name__ == "__main__":
    sys.exit(main())
