# Rewind local assessment API

For r10's separate live microphone-transcription stream, see [Live API contract.md](Live%20API%20contract.md). It provides provisional reading progress only; the final assessment contract below is unchanged. Live capture is additional OpenAI usage and requires consent before microphone chunks are sent.

This is a local trial adapter, not a deployed service or validated Cantonese tone grader. The browser records locally. After the user has opted into recording-and-assessment for the selected provider, stopping a new recording triggers assessment; without configuration or consent the clip remains local for replay. A retry button is available in the temporary result surface. Configuring a provider never automatically uploads an older clip. It supports Azure pronunciation assessment and an experimental OpenAI direct-audio coaching alternative. The Azure account must have an active Speech resource key and its region. Speech Studio's unaffiliated five-second demo does not provide API access. OpenAI requires its own API key and access to the configured audio model; a ChatGPT subscription is not an API credential.

All routes are served only on `127.0.0.1` with the actual server port. No CORS access is granted. POST routes require `Content-Type: application/json`, the same Origin when supplied, and `X-Rewind-Token` taken from `__LOCAL_TOKEN__` in the served HTML. This token is a local CSRF token, not the Azure key. Host is checked to resist rebinding. No arbitrary path or recording route exists.

## Routes

`GET /` serves `../player/build/Rewind.html` when that native build exists, otherwise the repository's `../index.html`, substituting the local token. These are the only two fixed player locations; no arbitrary path argument is accepted. `GET /api/status` returns:

```json
{"configured":false,"provider":"azure","connection_verified":false,"region":"","mode":"local-trial","key_storage":"process-memory-only","max_recording_seconds":25,"cloud_requests_per_attempt":2}
```

`POST /api/config` takes `{ "provider": "azure", "key": "...", "region": "eastasia" }` or `{ "provider": "openai", "key": "..." }`. Omitted provider defaults to Azure for compatibility. Region is required only for Azure and cleared on OpenAI selection. It validates syntax and keeps the selected provider's key in process memory. It does not upload audio or verify the service, and never automatically sends a previously recorded clip. It invalidates results of any request still running. `POST /api/disconnect` with `{}` clears the key and invalidates outstanding results; a request already sent to a provider cannot be recalled. Status additionally exposes `supported_providers: ["azure","openai"]`; OpenAI reports model `gpt-audio-1.5` and `cloud_requests_per_attempt: 1`.

`POST /api/assess-recording` takes `{ "provider": "azure", "text": "exact reference", "audio": "base64 WAV bytes", "extension": ".wav" }`. Provider is required and must match the active server configuration; a mismatch returns `409 provider_changed` before uploading any audio. This prevents an older tab's Azure consent being reused after another tab selects OpenAI. Reference must contain 1–200 code points and is preserved exactly, including punctuation and whitespace. Audio must be mono PCM16 at 16 kHz, 25 seconds maximum, at most 820 KB decoded. Digital silence or a recording shorter than 0.20 seconds returns `status: no_speech`, no score, empty groups, and no cloud request. This is not a general voice-activity detector: quiet background noise still requires service assessment.

Each accepted non-silent attempt sends up to **two** requests with the same audio to the user's Azure region: first pronunciation assessment with the reference; then ordinary `zh-HK` speech recognition without a reference or phrase hints. Both can consume the subscription's service allowance. No automatic retries or redirects occur. Each request times out after 35 seconds; clients should allow at least 80 seconds. The local trial permits one in-flight assessment and at most five attempts in 61 seconds, with a 1.1-second minimum between starts. These are local safeguards, not a statement of Azure's current quota.

## Response and colour semantics

```json
{
  "provider":"azure", "reference":"我買書，聽日再睇。", "recognized_text":"我買書聽日再睇。",
  "status":"assessed", "elapsed_seconds":2.1, "audio_duration_seconds":3.0,
  "overall":{"accuracy":90,"fluency":86,"completeness":100},
  "groups":[{"start":1,"end":3,"text":"買書","score":90,"state":"pass","reason":"practice_match","error_type":"None","word_group":true,"offset_seconds":0.5,"duration_seconds":0.7}],
  "crosscheck":{"status":"available","insertion_count":0},
  "cloud_requests":2,"pass_threshold":80,"lexical_tone_validated":false,"limitations":["..."]
}
```

This example is illustrative, not an actual service measurement. Group `start` is inclusive and `end` exclusive, measured in **Unicode code points in the exact reference** (`Array.from(reference)` in JavaScript), not UTF-16 code units. Positions include punctuation/whitespace even though those characters are ignored during matching. Groups preserve the actual provider word unit: a score for 買書 is not split into invented independent scores for 買 and 書. Unmapped spans have a null score and remain uncertain.

- `pass`: actual word-group score at least 80, no provider mispronunciation/omission flag, and every character in that group matches the independently recognized text.
- `retry`: lower score, a provider mispronunciation flag, or a word substitution/unmatched portion in the independent recognition. This is a suggestion to retry, not a guaranteed diagnosis.
- `uncertain`: crosscheck unavailable, missing score, or unresolved mapping; never accept or display as a correct pronunciation.
- `omitted`: provider marked this target group as unmatched. Do not assert that the user literally said nothing at that position.

The default 80 is a conservative starting threshold for evaluation, not calibrated against beginner recordings. A textual match does not validate Cantonese lexical tone. No traditional/simplified or homophone conversion is guessed; orthographic differences can therefore produce conservative retry/uncertain results. Edit alignment supports omitted/repeated material and subsequent recovery; ambiguous repeated positions have no independent timing guarantee.

`status: no_match` has no groups or scores. If ordinary ASR fails after PA succeeds, existing PA groups are returned as uncertain (except explicit omissions), and `crosscheck.status` is `unavailable`. Error responses contain only `{ "error": "safe message", "code": "stable_code" }`, with no upstream body, headers, or credential values.

## Security and source compatibility

Keys are accepted only through the local password/config control or `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` environment variables. They are never returned by status, stored in files or browser storage, or inserted into the player. Audio bytes remain in process memory and are not written to a temporary file. Results are returned to the requesting browser without server persistence. Raw provider responses are not exposed; any echoed known key is redacted from the reduced result. Disconnecting does not erase independent provider-side processing.

`assess.py` accepts both the documented flat REST score shape and the Speech SDK's nested `PronunciationAssessment` shape. The deployed calls use regional official HTTPS endpoints only, with fixed `zh-HK` and detailed output. Regional URL validated against the [official Microsoft sample](https://github.com/Azure-Samples/Cognitive-Speech-TTS/blob/master/PronunciationAssessment/Python/sample.py); format, configuration and flat response fields checked against [Microsoft short-audio REST documentation](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-speech-to-text-short). This REST trial returns final results after submission, not live per-character streamed scores.

Provider adaptation is kept separate from player rendering. Both providers return the same group positions/states while retaining their distinct measurement or coaching interpretation. Other providers could be added through this boundary, with independent testing of word mapping and any tone claims.

## OpenAI direct-audio alternative

`openai_feedback.py` implements the same group contract for an experimental direct-listening coach. The request sends the selected WAV as `input_audio` together with the practice reference to the fixed official `https://api.openai.com/v1/chat/completions` endpoint, model `gpt-audio-1.5`. It requests text only, `store: false`, and a bounded answer. It does not call a separate transcription model first. The request pattern follows [OpenAI's audio Chat Completions guide](https://developers.openai.com/api/docs/guides/audio-chat-completions.md). Model/API availability and actual learner usefulness have not been verified with a live call.

The system prompt asks the model to listen to actual pronunciation, use forgiving beginner expectations, distinguish Mandarin or changed words from the Cantonese target, and leave uncertain segments undecided. Audio/reference instructions are treated as content to assess, not executable instructions. This is model-generated coaching, not a measured phonetic score. The output is parsed as strict JSON only: no code fences, executable code, extra score fields, tool calls, or truncated responses are accepted. Non-overlapping reference spans must match exactly by code point. Invalid/ambiguous mapping makes the reference neutral. Empty heard text or unknown language cannot pass; a clearly non-Cantonese language cannot receive a Cantonese pass.

The response marker is `provider: "openai"`, `assessment_kind: "audio-coaching"`, `experimental: true`, `cloud_requests: 1`. Every group score and all overall numeric scores are null. `lexical_tone_validated` remains false. `recognized_text` is the model's account of what it heard, not an independent ASR measurement. `crosscheck.status` is `unavailable`, with reason `audio_model_coaching_not_independent_asr`. Frontend may render the model's `pass/retry/uncertain/omitted` states only as experimental coaching; it must not apply Azure's numeric-score gate or describe these states as calibrated accuracy.

Each attempt uses at most one OpenAI audio request with a 45-second timeout, no redirects and no retries. The response is capped at 160 KB and content at 48,000 characters. Known credentials are redacted from reduced results, raw errors are never exposed, and no recording/result is saved by the server. `store: false` is a request setting, not a promise of zero provider-side retention. The selected provider receives the recording only in the consented record-and-assess flow or an explicit retry; provider selection/configuration alone never sends audio.

For environment startup use `REWIND_SPEECH_PROVIDER=openai` with `OPENAI_API_KEY`, or use the local configuration form. Azure remains the default if no provider is selected. `python check_connection.py --provider openai` only reports local configuration. An actual test needs explicit `--audio`, `--text`, and `--run-cloud`; it can consume API usage. Neither provider was called during offline verification.

## Verification

For a source clone containing `index.html` at its root and this `service/` folder, run `python service/server.py --open-browser` from the repository root (Python 3.10 or newer). The WebSocket dependency is already bundled in `service/vendor/`. The server prints a loopback URL with a random local port; configure the provider only in that local app. Do not put a cloud key in the public HTML, repository, browser storage or a GitHub Pages setting.

GitHub Pages serves only the static player. Its local recording/replay features do not need a hosted backend, but live transcription and final cloud feedback require this local companion running with a configured provider key. Publishing the source does not create a hosted speech backend or allow a static phone page to contact another computer's loopback service. No public key-entry or direct browser-to-cloud route is provided by this service.

Run `python -m unittest test_azure_feedback test_openai_feedback test_server -v` from this folder. Tests use synthetic response objects and mocked cloud transport; they exercise group preservation, exact code-point offsets, 聽/明 mismatch blocking, omissions/repetition/recovery, missing ASR, REST/SDK compatibility, silence, malformed/long WAV files, rate/inflight controls, stale configuration, CSRF/Host/Origin, and key non-disclosure. OpenAI checks cover direct audio submission, strict JSON/schema parsing, non-Cantonese downgrade, no fabricated scores, neutral invalid mappings, provider switching, and safe error handling. They do not establish actual provider access or learner accuracy.

## r11 close feedback state

Results may include `close` in addition to pass/retry/uncertain/omitted. Close means the word is matched but minor practice is recommended. Azure requires score 60–79, an independent transcript match and no explicit mispronunciation; lower scores, wrong words or explicit errors stay retry. OpenAI supplies a provisional audio-coaching classification without numeric scores; non-Cantonese speech cannot receive close. Final pass is a filled mark, close is hollow, and other states have no mark. These are practice cues, not calibrated Cantonese tone measurements.
