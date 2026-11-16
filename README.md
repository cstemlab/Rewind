# Rewind

A cassette-inspired app for listening, repeating and practising spoken language.

**[Open Rewind](https://cstemlab.github.io/Rewind/)** · [繁體中文使用說明](Getting%20started.zh-Hant.md)

The included IN-SMART Cantonese practice has Traditional Chinese, Jyutping above the text, short phrases and complete sentences. Playback, captions and temporary options stay inside the cassette. The hosted preview adds AI practice and script creation while keeping the existing cassette design and controls.

## Start practising

Open the link in your browser. The included practice works without an AI connection. To use AI features, open **⋯ → Settings → Speech**, enter the private tester phrase supplied by the organiser in **Access code**, then press **Connect**. An invitation link can connect the same way.

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

## Practise with your voice

Press **Record**. A small on-tape notice explains the active service and when audio will be sent. Allow microphone access, read the current phrase or selected words, then press again to stop. The recording window follows the selected example’s duration plus two seconds, up to 25 seconds. A soft ready cue and blinking text marker indicate when to begin; the cue respects mute. Stop immediately ends capture. Animated status dots and an inactive recording button indicate processing, so repeated clicks cannot cancel the result. Press Escape or navigate away to cancel deliberately.

When live recognition is available, the faint background behind characters tracks words the service appears to have heard. **This is provisional recognition, not a pronunciation verdict.** After you stop, an audio model evaluates the clip directly and returns experimental practice feedback:

- **Teal text with a small filled round marker:** passed this attempt.
- **A hollow round marker:** close; worth practising again.
- **No marker:** needs another attempt or could not be confirmed. Open the result summary for the distinction.

Jyutping stays neutral. Several characters in a word may share one judgment. The final feedback is **not a validated Cantonese tone assessment**, and a model can miss a wrong syllable or tone. No calibrated proficiency score is claimed.

Without an AI connection, the record button offers recording and replay only. It explains this before recording and does not show a simulated assessment. Existing recordings are never sent automatically when you connect later.

## Make a tape from your script

After connecting, choose **⋯ → Library → New**. Paste/type Chinese or English, or import TXT, DOCX or a PDF containing selectable text. Files are limited to 5 MB and source text to 12,000 characters. Scanned PDFs need OCR first; save legacy DOC files as DOCX.

1. Choose **Faithful** to preserve meaning, details and register, or **Beginner** for familiar words and shorter clauses. Both aim to preserve the substantive content.
2. Press **轉成粵語** to convert the script into spoken Cantonese.
3. Review and edit the Cantonese draft, then press **製作錄音** to generate the AI demonstration voice.
4. Press **開始練習** to load the finished tape. Its title and sections follow your script; the Rewind logo stays the same.
5. Use **Library → Export** to save a `.rewind.json` file containing the script, Jyutping, timing and demonstration audio.

Cancelled or failed creation leaves the draft and current tape intact. Review the generated wording, Jyutping and voice before relying on them. Whole-sentence audio lengths are measured; **within-sentence character and phrase boundaries are estimated**, so selecting one character can include a little adjacent sound.

## Materials and labels

**⋯ → Skin** provides independent **Material, Case, Sticker, Pattern** and **Print** controls. Choose Matte, Smoked or Clear plastic, customise the colours, or start from one of the 24 presets. Transparent materials expose interior supports and the tape path while the sticker stays opaque. Changing appearance preserves the cassette proportions and reel positions.

## What is sent and saved

- Ordinary playback and importing a prepared `.rewind.json` do not send the practice to an AI service.
- TXT files are read in the browser. DOCX and PDF files go to the Rewind backend for text extraction. Pressing the conversion or narration button sends the relevant text to the displayed AI service.
- Voice practice sends audio according to the on-tape notice: during recording for enabled live recognition, and after stopping for final feedback.
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
