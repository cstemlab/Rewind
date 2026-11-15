# Rewind r10 live reading progress

Live feedback is **transcription progress**, never a pronunciation or lexical-tone verdict. The existing end-of-recording coaching remains a separate request and can run while the live stream finishes. No expected words, reference text or phrase hints are sent to the transcriber. Matching the target in a transcript does not establish correct Cantonese pronunciation.

The server relays microphone PCM to the fixed official `wss://api.openai.com/v1/realtime?intent=transcription` endpoint. Model `gpt-live-transcribe`, PCM16 little-endian mono 24 kHz, `languages: ["yue"]`, `delay: "low"`, `turn_detection: null`. A single utterance is committed once on stop. There is no VAD, automatic fallback model, or automatic retry. The request follows the [official OpenAI realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription.md), checked 2026-11-16. The documented model can emit deltas before commit; actual account/model access and latency require a configured live test. It supplies no word timestamps, word confidence, detected-language guarantee or tone grades.

Every route below is **POST**, JSON, with the same Host/Origin/local CSRF protections as the assessment API. Every body explicitly includes `provider: "openai"`. Requests bind to the current configuration generation and a random per-attempt session ID. Old tabs cannot append to a new attempt. The browser never receives the cloud key. Status adds:

```json
{"live_transcription":{"supported":true,"available":true,"model":"gpt-live-transcribe","feedback_kind":"transcription-progress","sample_rate":24000,"max_seconds":25}}
```

`available` means configured OpenAI, not verified model access. Azure configuration reports false. Starting a stream requires separate user consent covering live upload; configuration alone does not open a stream or send audio. The stream is additional provider usage beyond the final audio-coaching request.

## Endpoints

- `/api/live/start`: `{ "provider":"openai" }`. Returns `{ session_id, state:"listening", sample_rate:24000, max_seconds:25, model, feedback_kind:"transcription-progress" }` only after `session.updated` acknowledges setup. Maximum one active stream; another start receives `409 live_busy`. Connection and setup each have an eight-second bound. No reference or recording is sent by this route.
- `/api/live/audio`: `{ "provider":"openai", "session_id":"…", "seq":0, "audio":"base64 raw PCM" }`. Start sequence at zero and await each response before sending the next. Each chunk is at most one second / 48,000 bytes and must have an even nonzero length. Silence PCM is valid and must continue during quiet pauses. Returns `{ accepted_seq, next_seq, received_seconds, state }`. Duplicate/out-of-order sequences are rejected without upload.
- `/api/live/events`: `{ "provider":"openai", "session_id":"…", "after":0 }`. Poll about every 200 ms. Returns `{ session_id, state, events, last_seq }`. Each event has a monotonically increasing local `seq`. Transcript events are `{ seq, type:"transcript", item_id, item_index:0, text, final:false }`: `text` is the full accumulated text of the one utterance, not a delta. A completed provider result replaces that text and sets `final:true`. Other events are `{seq,type:"error",code,message}` and `{seq,type:"closed",reason}`. The most recent 256 events are retained; full transcript snapshots make skipped intermediate events safe. Error text is a fixed local message, never an upstream raw error.
- `/api/live/stop`: `{ "provider":"openai", "session_id":"…", "commit":true }`. After all audio chunks are acknowledged, commit once and enter `finishing`. Keep polling for a final transcript or closure for at most 12 seconds. Fewer than 100 ms of audio closes without committing. Repeated stop does not repeat commit. `commit:false` cancels immediately, including while finishing.
- `/api/live/cancel`: `{ "provider":"openai", "session_id":"…" }`. Alias for stop with `commit:false`; no additional audio request.

Only one item is valid in this single-commit, VAD-disabled stream. The first actual delta binds the item ID; commit/completion must match it. Unexpected second items fail neutrally rather than merging uncertain order. Frontend must clear provisional progress when an attempt, reference, selection or provider changes and must keep its appearance distinct from final coaching. No timer, amplitude, recording duration or target text may fabricate recognized progress.

## Lifetime and bounds

Maximum 25 seconds of PCM and 25 seconds of active capture wall time. At the wall cap the server commits received audio; finishing then has a 12-second limit. Seven seconds without incoming PCM cancels an abandoned capture. Polling alone cannot prolong it. Disconnect, configuration change, cancel, provider error, invalid item mapping and server shutdown close the socket. Terminal results remain available to the same session for up to 45 seconds, or until a new session replaces it. At most five new live streams per 61 seconds; this is separate from the existing final-assessment rate/lock.

Incoming websocket frames and fragmented messages are each capped at 64 KiB, transcript text at 1,600 code points, event history at 256 snapshots. Network redirects are not followed, TLS validation is retained, and all upstream errors are reduced to safe local codes. No audio, cloud credentials or provider results are written to files. Closing a connection cannot recall chunks already sent to OpenAI; server-side transient memory handling is not a claim about provider-side retention.

The pure-Python websocket dependency is bundled under `vendor/`; see `Vendor provenance.md`. Do not copy only `server.py` when packaging. Offline verification: `python -m unittest discover -s . -p "test_*.py" -v` from this service folder. All transport tests use synthetic PCM and fake websocket/HTTP provider responses, with no account calls.
