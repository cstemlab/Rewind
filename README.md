# Rewind

A cassette-inspired player for listening, repeating and practising spoken language.

**[Open Rewind](https://cstemlab.github.io/Rewind/)**

The current demo includes an IN-SMART Cantonese presentation, Traditional Chinese text, Jyutping above the characters, and audio-synchronised highlighting.

- **Play** reads one practice unit and stops. Press again to continue.
- **Rewind** repeats the current unit or selection.
- **Through** plays continuously; **Loop** repeats the current unit.
- Click a character to listen from there, or drag across characters to practise a smaller range.
- **Short / Long** switches between beginner phrases and complete sentences.
- **⋯** opens temporary options inside the cassette. Pick a chapter, sentence or skin to return to practice. The cassette keeps the same size and position.

Chapters, full-script search, playback settings, 24 skins, session import/export and Help are available inside the options surface. Opening options pauses audio; closing them never resumes audio automatically.

This is a single-file web app. The script, recording, timing, icons and interface are embedded in `index.html`. There are no build dependencies for hosting it. GitHub Pages serves the file directly from `main`.

Rehearsal files imported through Library stay in the current browser session; the player has no upload service. The supplied demo is included in this public repository.

Version **r08 / 0.8.0**. Tested in desktop Chrome and Chromium at mobile viewport sizes; real iOS Safari testing remains pending. Icons: [Phosphor](https://github.com/phosphor-icons/core), MIT license embedded in the HTML. Cassette and label graphics are original Rewind artwork.
