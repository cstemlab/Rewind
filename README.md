# Rewind

A cassette-inspired app for listening, repeating and practising spoken language.

**[Open Rewind](https://cstemlab.github.io/Rewind/)** · [繁體中文使用說明](Getting%20started.zh-Hant.md)

The included IN-SMART Cantonese practice has Traditional Chinese, Jyutping above each character, short phrases and complete sentences. Playback, captions and temporary options remain inside a fixed cassette.

| Control | Action |
| --- | --- |
| Play, centre | Play once, pause/resume; after a unit ends, play the next unit |
| Rewind, left of Play | Replay the current unit or selected range |
| Record, right of Play | Record your voice; press again to stop |
| Previous / Next | Select another unit quietly |
| Through | Listen continuously |
| Loop | Repeat the current unit |
| Short / Long | Switch between phrases and sentences |
| ⋯ | Temporary options inside the cassette |

Click a character to hear from there, or drag across words to hear just that range. Selection surrounds the written text, leaving Jyutping unchanged. The small × clears selection without an oversized hover background.

## Make a tape from your script

In the **local companion**, connect OpenAI in **⋯ → Settings → Speech**, then choose **Library → New**. Paste/type Chinese or English, or import TXT, DOCX or a text-based PDF. Files are limited to 5 MB and source text to 12,000 characters. Scanned PDFs need OCR first; legacy DOC files should be saved as DOCX.

- **Faithful** asks for natural spoken Cantonese while preserving meaning, details and register.
- **Beginner** asks for familiar words and shorter clauses while preserving substantive content.

Review and edit the Cantonese draft before generating an AI voice. Only **開始練習 / Use** replaces the active tape. Its title and section information follow the new script; Rewind branding remains unchanged. Cancelled/failed jobs preserve the draft and current tape. Export the completed `.rewind.json` session to retain or share it; the file includes its audio.

AI creation uses your API quota and sends the relevant text to OpenAI after you request conversion or narration. Document extraction itself is local. The planner cannot rewrite the reviewed text: it receives immutable source token IDs for Jyutping. Pronunciation and Jyutping still need review. Whole-sentence WAV durations are measured; **within-sentence character/phrase times are estimated**, so a selected character may have an imperfect audio boundary. See the [creator contract](service/Creator%20API%20contract.md).

## Materials and labels

**Skin** provides independent Material (Matte, Smoked, Clear), Case colour, Sticker colour, Pattern and three Print colours. The original 24 designs remain under Presets. Transparent plastic exposes restrained internal supports, lower tape guides and the tape path; the paper sticker stays opaque. Changing appearance never moves the reels or changes the cassette proportions. Text and controls adapt to light and dark colours.

## Online and local use

**GitHub Pages provides playback, prepared-session import/export, and local microphone recording/replay.** It does not host an AI server, contain an API key, or send recordings to an AI service. Imported sessions and learner recordings stay in the current page unless a session is explicitly exported; learner microphone recordings are never included in session exports.

**AI creation and pronunciation feedback use the optional local companion.** Download or clone this repository, install Python 3.10 or later, then run:

```sh
python service/server.py --open-browser
```

Windows also has `Open Rewind.cmd`; macOS has `Open Rewind.command`. Runtime dependencies and licenses are bundled in `service/vendor`. The server binds only to `127.0.0.1`. In the opened page, choose **⋯ → Settings → Speech** and connect your own OpenAI or Azure key. Keys remain in process memory, outside the repository and browser storage. Restarting requires reconnecting. Creation uses OpenAI; pronunciation practice supports either provider.

OpenAI can stream recording audio for provisional transcription progress and assess the finished clip after the first-use disclosure. Azure assesses after recording stops. Live recognition is a faint character-only wash; it is not a pronunciation verdict. Final passed groups use fresh teal text and a filled miniature marker; a hollow marker means close, with room to improve. Wrong/unmatched/uncertain groups have no marker, and result details distinguish them. Jyutping remains neutral. A multi-character word group may share one judgment.

This is a practice aid, **not a validated Cantonese tone examiner**. Model judgments can be wrong; an earlier 買／賣 contrast was missed. Azure's close range is a UI heuristic (60–79 plus a matching independent transcript and no explicit mispronunciation), not a calibrated proficiency standard. OpenAI provides experimental coaching without invented numeric scores. See [speech setup](service/API%20contract.md) and the [live contract](service/Live%20API%20contract.md).

## Version and source

Version **r11 / 0.11.0**. `index.html` is the complete browser app with embedded demo audio, timing, icons and Help. Previous releases remain in Git history. No API keys or learner recordings are published.

Tests cover parsing, jobs/cancellation, exact reviewed-text preservation, marker semantics, selection, transport, custom materials and fixed geometry. Simulated recordings test interaction, not pronunciation accuracy. Real iPhone Safari and Mac-device testing remain pending. Icons: [Phosphor](https://github.com/phosphor-icons/core), MIT license embedded. Cassette and label artwork is original; material references are recorded in [Material references](Material%20references.md).
