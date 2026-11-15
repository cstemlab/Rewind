# Rewind

A cassette-inspired app for listening, repeating and practising spoken language.

**[Open Rewind](https://cstemlab.github.io/Rewind/)**

The demo includes an IN-SMART Cantonese presentation, Traditional Chinese, Jyutping above each character and the original timed recording. It stays inside a fixed cassette, with 24 printed label designs.

| Control | Action |
| --- | --- |
| Play, centre | Play once, pause/resume, then continue to the next unit after it ends |
| Rewind, left of Play | Replay the current unit or selected range |
| Record, right of Play | Record your own voice; press again to stop |
| Previous / Next | Select another unit quietly |
| Through | Listen continuously |
| Loop | Repeat the current unit |
| Short / Long | Switch between beginner phrases and full sentences |
| ⋯ | Temporary options inside the cassette |

Click a character to listen from there, or drag across words to practise just that range. Chapters, full-script search, playback settings, Skin, Library and Help are in the temporary options surface. Closing options does not resume playback.

## Online and local use

**GitHub Pages provides playback and local microphone recording/replay.** It does not host an assessment server, contain an API key, or send your microphone recording to an AI service. Allow microphone access when your browser asks. Imported sessions and your recordings remain in the current browser page unless you explicitly export a session; learner recordings are not included in session exports.

**Cloud feedback uses the optional local companion.** Download or clone this repository, install Python 3.10 or later, then run:

```sh
python service/server.py --open-browser
```

The WebSocket dependency is bundled in `service/vendor`; no package installation is required. The companion binds to `127.0.0.1` only. In its opened page, use **⋯ → Settings → Speech** to configure your own OpenAI or Azure key. Keys stay in the companion's process memory, outside this repository and browser storage. Restarting the companion requires reconnecting.

OpenAI mode can stream the current recording for transcription progress and send the finished clip for experimental pronunciation feedback after first-use disclosure. Azure mode provides feedback after recording stops. Live recognition uses a light highlight; final accepted groups use bright blue and a solid underline. Uncertain or unmatched groups are not counted as passes. A multi-character group shares one judgment.

This is a practice aid, **not a validated Cantonese tone examiner**. In preliminary tests, a 買／賣 contrast was missed. Streaming transcription shows what was recognized, not whether the tone was correct. Live model access and real-device latency require verification with the configured account. See [the companion contract](service/Live%20API%20contract.md) for limits and [provider setup](service/API%20contract.md) for details.

## Version and source

Version **r10 / 0.10.0**. `index.html` is the complete browser app with embedded demo audio, timing, icons and Help. Previous versions remain in Git history. No private API keys or learner recordings are published.

Desktop Chromium and mobile-sized Chromium checks cover controls, captions, selection, skins, fixed geometry and simulated streaming. Real iOS Safari testing remains pending. Icons: [Phosphor](https://github.com/phosphor-icons/core), MIT license embedded in the HTML. Cassette and label graphics are original Rewind artwork. Bundled WebSocket dependency provenance and license are in `service/`.
