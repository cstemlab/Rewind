# Rewind

A cassette-inspired app for listening, repeating and practising spoken language.

**[Open Rewind](https://cstemlab.github.io/Rewind/)** · [繁體中文使用說明](Getting%20started.zh-Hant.md)

The included IN-SMART Cantonese practice has Traditional Chinese, Jyutping above the text, short phrases and complete sentences. Playback, captions and temporary options stay inside the cassette. The hosted preview adds AI practice and script creation while keeping the existing cassette design and controls.

The built-in tape now follows Logan's revised **1 December 2026 QEF presentation script**: six sections (1, 2a, 2b, 2c, 3 and 4), 157 short phrases and 35 full sentences. It replaces the earlier default and keeps the original **WanLung** Cantonese male voice at **-12%**. [Source and verification](source/default/README.md).

## Start practising

Open the link in your browser. The included practice works without an AI connection. To use AI features, open **⋯ → Settings → Speech → AI 回饋**, enter the private tester phrase supplied by the organiser in **Access code**, then press **Connect**. An invitation link can connect the same way.

The hosted preview uses **Google Gemini**, with API costs covered by the organiser. Testers do not need a Google Cloud account or an API key. The connection is kept in the current browser tab; if it expires, reconnect with the tester phrase. Please keep the phrase private.

**OpenAI remains available in the optional local companion. It is not configured on this hosted preview.** The app does not automatically switch providers or send a recording to a fallback service.

| Control | Action |
| --- | --- |
| Play, centre | Play once, pause/resume; after a unit ends, play the next unit |
| Rewind, left of Play | Replay the current unit or selected range |
| Record, right of Play | Record your voice; press again to stop |
| Previous / Next | Select another unit quietly |
| Through | Listen continuously |
| Loop | Repeat the current unit |
| Short / Long | Switch between phrases and sentences |
| ⋯ | Open temporary options inside the cassette |

Click a character to hear from there, or drag across words to hear just that range. Selection surrounds the written text, leaving Jyutping unchanged. The small × clears the selection.

While the demonstration plays, its highlight also surrounds only the written character; Jyutping stays neutral.

Tap the small landscape icon at the top right of the sticker: the cassette immediately turns and fills the available screen area, keeping its 1.58:1 proportions. Rewind also requests native fullscreen and landscape orientation when the browser allows them. If iPhone Safari does not offer native fullscreen, the cassette still turns within the page; Rewind cannot force Safari’s address and navigation bars to disappear. For a separate app window, use **Share → Add to Home Screen** and enable **Open as Web App** when offered, then launch Rewind from the home screen. Tap the icon again to leave landscape practice. Real-device behavior remains to be tested; browser simulation does not verify iPhone compatibility.

## Practise with your voice

The first press of Record offers **AI 回饋** (AI feedback) or **只錄音對照** (record and compare). Rewind remembers this choice in the current browser; change it under **Settings → Speech**. AI mode opens the access-code field when disconnected (a service API key in the local companion). Record-and-compare mode works without AI and never uploads that attempt, even if a service is connected. Connecting alone never starts the microphone.

In AI mode, a small on-tape notice explains the active service and when audio will be sent. Allow microphone access, read the current phrase or selected words, then press again to stop. The recording window follows the selected example’s duration plus two seconds, up to 25 seconds. A longer soft cue is followed by two flashes on the first character. This 1.35-second preparation happens before the recording clock and captured samples begin; the cue respects mute. Stop immediately ends capture. Animated status dots and an inactive recording button indicate processing, so repeated clicks cannot cancel the result. Press Escape or navigate away to cancel deliberately.

After the ready cue, a gentle background fills each written character smoothly at the demonstration’s pace and selected playback speed. Earlier characters keep their fill, so progress accumulates across the line. It is a **rhythm guide, not speech recognition or a pronunciation verdict**. It does not wait for you or change the result if you fall behind. The completed fill stays during the two-second recording buffer and clears when recording stops (within the 25-second limit). Generated sessions may have estimated word timings. In AI mode, the clip is sent only after you stop, and the audio model returns experimental practice feedback:

- **Teal text with a small filled round marker:** passed this attempt.
- **A hollow round marker:** close; worth practising again.
- **No marker:** needs another attempt or could not be confirmed. Open the result summary for the distinction.

Jyutping stays neutral. Several characters in a word may share one judgment. The final feedback is **not a validated Cantonese tone assessment**, and a model can miss a wrong syllable or tone. No calibrated proficiency score is claimed.

After recording, a small solid play arrow appears directly below the central Play key, using the same theme colour as the outline demonstration arrow. It gently pulses three times when a new clip is ready, then settles; listening stops the cue immediately. It plays or pauses your own voice; its tooltip and accessible name identify it as My recording. There is no persistent text label. Use it to compare; use the existing **Rewind** key to replay the demonstration. The two never play together, and same-phrase Rewind preserves your clip. This also works while AI feedback is pending. A new attempt, different phrase/range, session change or page close clears the previous clip.

## Make a tape from your script

After connecting, choose **⋯ → Library → New**. Paste/type Chinese or English, or import TXT, DOCX or a PDF containing selectable text. Files are limited to 5 MB and source text to 12,000 characters. Scanned PDFs need OCR first; save legacy DOC files as DOCX.

1. Choose **Faithful** to preserve meaning, details and register, or **Beginner** for familiar words and shorter clauses. Both aim to preserve the substantive content.
2. Press **轉成粵語** to convert the script into spoken Cantonese.
3. Review and edit the Cantonese draft, then press **製作錄音** to generate the AI demonstration voice.
4. Press **開始練習** to load the finished tape. Its title and sections follow your script; the Rewind logo stays the same.
5. Use **Library → Export** to save a `.rewind.json` file containing the script, Jyutping, timing and demonstration audio.

Cancelled or failed creation leaves the draft and current tape intact. Review the generated wording, Jyutping and voice before relying on them. Whole-sentence audio lengths are measured; **within-sentence character and phrase boundaries are estimated**, so selecting one character can include a little adjacent sound.

## Tape position

The two tape packs and the centre window follow elapsed time across the **whole practice**, from the first cue to the last. Every document starts with a full right reel and an almost empty left reel; the tape transfers left as playback advances. Short recordings transfer faster while keeping the same starting capacity. Pause holds the tape, and section jumps, word selections, looping and rewind follow the matching document position. Loading a new practice resets its tape. The hubs and cassette proportions stay fixed. The centre-window arcs are true circles centred on the visible gear hubs, recalculated when the layout changes. Each smaller translucent plastic core sits inside the tape wound around it. The tape stays within its half of the window, including in rotated mobile layouts.

## Materials and labels

The default **Rewind yellow** skin matches the owner-selected smoked grey case and warm yellow sticker. Other saved custom appearances remain available.

**⋯ → Skin** provides independent material, case and sticker colours. Choose **Plain** for one sticker colour, or **Regions** for solid **Top / Middle / Bottom** sections. Decorative thin stripes are removed across all 25 presets, including saved styles. Choose Matte, Smoked or Clear plastic; transparent materials expose interior supports and the tape path while the sticker stays opaque. Changing appearance preserves the cassette proportions and reel positions.

## What is sent and saved

- Ordinary playback and importing a prepared `.rewind.json` do not send the practice to an AI service.
- TXT files are read in the browser. DOCX and PDF files go to the Rewind backend for text extraction. Pressing the conversion or narration button sends the relevant text to the displayed AI service.
- AI practice sends the recorded clip after stopping for final feedback. The rhythm guide runs locally; recording-comparison mode does not send audio.
- Learner recordings are temporary in the current page and are cleared when you leave or clear the attempt. They are **not included** in exported practice files. Clearing the page does not undo audio already sent for processing.
- Provider credentials stay on the backend. The public HTML contains no API key or tester phrase; only the temporary session token is stored in the current tab.

For phones, share the **web link**. A downloaded HTML file may not open as an interactive app in a phone's file preview. Prepared practice files can be imported from **Library → Open**. Playback of an already downloaded complete HTML remains available offline; AI functions need an internet connection and an active service.

## Optional local companion

OpenAI is retained as a local option. Download or clone this repository, install Python 3.10 or later, then run:

```sh
python service/server.py --open-browser
```

Windows also includes `Open Rewind.cmd`; on macOS, use `python3` or `Open Rewind.command`. Runtime dependencies and licences are bundled in `service/vendor`. The service binds only to `127.0.0.1`.

In the local page, choose **⋯ → Settings → Speech → OpenAI**, enter your API key and connect. The key stays in the local service's memory; restarting requires reconnecting. Local usage is charged to that API account. The existing Azure Speech option is also retained for local pronunciation practice; script creation uses OpenAI in this companion.

The local and hosted versions use the same recording and cassette controls. Neither silently transfers an attempt to a different provider. See the local [speech contract](service/API%20contract.md), [live contract](service/Live%20API%20contract.md) and [creator contract](service/Creator%20API%20contract.md).

## Source and testing

`index.html` contains the browser app, demo audio, timing, icons and Help. `rewind-cloud.json` supplies the public backend address only. Hosted source is in `cloud/`, with an [API contract](cloud/API.md) and [deployment notes](cloud/DEPLOY.md); `service/` retains the local companion. Previous versions remain in Git history.

Mocked tests cover hosted authentication and expiration, local CSRF compatibility, creator jobs and cancellation, both translation modes, provider-specific live routing, recording feedback and preservation of the reviewed draft. They test integration and interaction, **not pronunciation accuracy**. Real iPhone Safari and Mac-device testing remain pending.

Icons: [Phosphor](https://github.com/phosphor-icons/core), with its MIT licence embedded. Cassette and label artwork is original; see [Material references](Material%20references.md).


### Script files

Library → Open accepts TXT, Markdown, Word (.docx), text PDFs and prepared Rewind tapes. New → Import uses the same reader. Documents are read locally in your browser; an AI connection is only needed when you choose to convert the reviewed script. Drag a file into the script or library panel, or use the keyboard-accessible Import button. Empty, corrupt, scanned and oversized files show an explanation and preserve your draft. Limits: 5 MB and 12,000 characters; PDFs up to 100 pages. Scanned PDFs need OCR; legacy .doc files need saving as .docx.
