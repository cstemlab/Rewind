# Rewind r11 · Create a Cantonese practice

All routes use the existing loopback service's Host, Origin and `X-Rewind-Token` checks. No API key is sent to a published page. `GET /api/status` now includes `creator: {available,formats,modes,limits,models,timing_precision,ai_voice}`. `available` means an OpenAI key is configured; it does not claim model access has been tested.

## Routes

All calls below are JSON POSTs. Unknown fields have no execution authority.

| Route | Body | Result |
| --- | --- | --- |
| `/api/creator/extract` | `{filename,data}`; `data` is base64 file bytes | `{text,title,format,warnings}` |
| `/api/creator/translate` | `{text,title,mode,consent:true}` | Job snapshot |
| `/api/creator/render` | `{draft:{title,text,mode},consent:true}` | Job snapshot |
| `/api/creator/status` | `{job_id}` | Job snapshot, with result when completed |
| `/api/creator/cancel` | `{job_id}` | Cancelled snapshot |

`mode` is `faithful` or `beginner`. Both are instructed to preserve substantive meaning; beginner asks for simpler vocabulary and clauses, not omitted content. Translation returns an editable **draft**. Rendering tokenizes the reviewed draft locally and preserves its complete text, internal spaces, line breaks, numbers and punctuation. The model returns only Jyutping keyed to immutable Han token IDs, plus optional ID-only sense-boundary hints. Model-authored sentence text is never used. The exact concatenated source text is checked again before narration.

Job snapshot: `{job_id,state,stage,message,completed,total,result?,error?}`. States are `queued`, `running`, `completed`, `failed`, `cancelled`. Stages include `translate`, `render`, `narrating`, `ready`. Result is either `{draft:{title,text,mode}}` or `{session:<rewind-session v1>}`. Error is `{code,message}`. Poll roughly once a second; stop after a terminal state. Do not install a session until the user chooses Use. Failed/cancelled work must never replace the current session.

Closing the creator UI should cancel its current job. A request already sent to OpenAI cannot be recalled or unbilled; cancellation discards its result and prevents subsequent narration requests. Reconfiguring/disconnecting invalidates all jobs. Jobs are memory-only, at most one active, with up to three recent results retained for 30 minutes and at most six starts per minute. A 30-minute wall-clock bound stops subsequent generation requests; any single already-running HTTPS request is bounded by its 100-second timeout.

## Limits and extraction

- File: 5,000,000 bytes; TXT/Markdown UTF-8 or BOM-marked UTF-16, DOCX, or text PDF. Old binary DOC is rejected with a conversion instruction.
- Source: 12,000 characters. Reviewed draft: 6,000 characters. No silent truncation.
- DOCX: 2,000 ZIP entries, 20 MB total uncompressed data, 4 MB document XML; no encrypted entries, traversal names, DTDs or entities. Only body paragraphs/tables are read, in document order. Images, comments and headers/footers are excluded with a warning.
- PDF: at most 80 pages. Vendored pypdf runs in a separate short-lived process, with a 20-second timeout and 8 MB per-Flate decoded limit. Encrypted files are rejected; image-only/empty PDFs return `needs_ocr`. No OCR is invented or silently requested from a cloud service.
- Extraction is local, needs no API key, does not execute document instructions and does not save the source file.
- Narration: at most 100 sentences, 150 spoken units per sentence, 10 spoken units per short phrase, 15 minutes total, or 44 MB PCM before encoding.
- Whole sentences are determined locally from source punctuation/newlines, with long sentences split at clause punctuation or complete tokens to meet the 150-unit limit. Short phrases use valid optional sense-boundary ID hints and local punctuation, with a 10-unit cap. Invalid hints are ignored; text and Jyutping cannot be rewritten by a hint. English words and decimal/grouped numeric tokens remain intact. Longer clauses without a useful hint may need human adjustment for the most natural practice breaks.
- Missing, extra or malformed Jyutping IDs allow one bounded annotation repair request. Transport/authentication failures are never retried automatically. Cancellation is checked before the initial annotation request and any repair. A second invalid annotation fails safely; no partial practice session is installed.

## Models, timing and disclosure

Text translation and annotation use `gpt-5.6-terra` via Chat Completions JSON output. This current model is recommended in the older GPT-5 mini documentation; the implementation does not start a new dependency on deprecated GPT-4.1 mini/GPT-5 mini or deprecated `/audio/speech` models. Narration uses the existing supported `gpt-audio-1.5` Chat Completions audio output, `alloy`, WAV, `store:false`. Fixed official HTTPS endpoint, TLS verification, no redirects, bounded request/response sizes and safe errors. Separate calls, including the one permitted annotation repair, may consume API quota.

Each complete sentence has independently generated audio. Its WAV duration is measured; the returned audio transcript must match the reviewed sentence after case/punctuation normalization and conservative numeric equivalence (for example `12`/`十二`, `2027`/`二零二七`, or `12.5`/`十二點五`). Numeric token boundaries, leading zeros, negative signs, values, percentages, fractions, arithmetic and currency symbols remain significant. Changed words/numbers, merged English words, and ambiguous abbreviated number spellings fail the guard. Spoken expansions of percent/fraction/currency notation are not inferred and may require writing the reviewed script in words. That transcript is **not independent acoustic verification**. Cantonese voice quality and Jyutping correctness still require listening/review.

WAV decoding measures actual complete sample frames rather than trusting a streaming header's declared frame count. Explicit unknown-size RIFF/data placeholders are supported. Mono or stereo PCM integer 8/16/24/32-bit and IEEE float 32/64-bit audio at supported 8–96 kHz rates are normalized to mono 16-bit PCM. Stereo is averaged with saturation; nonfinite samples, unsupported formats, ordinary truncation, partial frames and out-of-range durations are rejected. Sample rates are preserved; a session with inconsistent sentence sample rates stops rather than silently resampling. Error diagnostics contain only format fields and byte/frame counts, never audio, text or keys.

Sentence boundaries are measured. **Phrase and character boundaries inside each sentence are estimated**, using weighted allocation across that measured audio. They are not word timestamps or forced alignment. This limitation travels with `source.timing_precision`, every unit's `timing_precision`, and the session `warnings`. The UI should show the timing warning before Use. Precise word clipping is not claimed; longer selections and short-phrase/whole-sentence practice remain available.

The session includes `source.ai_voice:true`, model/voice provenance, mode and the reviewed text. Generated audio must be disclosed as AI-generated in the creator result/metadata. Original uploaded documents and keys are not included in session exports. Exported sessions contain the reviewed Cantonese practice text and generated audio, by the user's explicit export action.

Official references checked 2026-11-16:

- [Audio in Chat Completions](https://developers.openai.com/api/docs/guides/audio-chat-completions.md)
- [GPT-Audio-1.5](https://developers.openai.com/api/docs/models/gpt-audio-1.5.md)
- [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra.md)
- [Text-to-speech migration notice](https://developers.openai.com/api/docs/guides/text-to-speech.md)
- [Microsoft RIFF chunk structure](https://learn.microsoft.com/en-us/windows/win32/xaudio2/resource-interchange-file-format--riff-)
- [Microsoft WAVEFORMATEX sample/block alignment](https://learn.microsoft.com/en-us/windows/win32/api/mmreg/ns-mmreg-waveformatex)

## Player-side short-tail refinement

The player may join an orphan one- or two-unit phrase tail to its preceding phrase (no clause-ending punctuation, same sentence/section, contiguous ranges, combined maximum 12 units). This preserves exact words, per-unit times, audio and sentence ranges; exported provenance records `phrase_refinement`. It avoids isolated trailing syllables created by the service's strict ten-unit cap. Default prepared IN-SMART content is unaffected. Arabic number tokens and Latin words preserve their source display but do not receive generated Jyutping; users can spell numbers in Chinese during draft review when annotated spoken numbers are needed.
