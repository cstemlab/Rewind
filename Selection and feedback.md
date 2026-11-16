# Rewind r11 — selection and feedback

Latest user direction, 16 November 2026: selection belongs to Han/text only, in separate soft near-square blocks. Keep pronunciation guides unchanged. A small clear symbol should be near the selection, without a painted hover block. New assessment direction supersedes the previous hyperlink-blue and underline treatment: refined teal and solid/hollow miniature markers.

## Visual reference

[Things official product page](https://culturedcode.com/things/) and its [official product screenshot](https://culturedcode.com/things/2024-01-20/images/whatsnew-collage-io60.png) were visually inspected. The useful principles were restrained colour for state, light neutral surfaces, small geometric status symbols and clear typography. No product assets or trademarks were copied.

## Implementation

- `selection.css` applies a low-opacity accent fill and a fine edge to each selected `.han` separately. Wrapper backgrounds are transparent and Jyutping retains its ordinary colour. Existing speech classes remain a separate semantic layer.
- `selection.js` only positions the clear symbol. It never changes a selected range or plays/pauses audio. It finds free space near the selected characters, considers Han and Jyutping bounds, and can reserve an 18px trailing gutter when a dense phone line has no suitable gap. The visible symbol is 10px; its transparent target is 14px. A small optical allowance above the transcript keeps the symbol close to a selection while remaining inside the paper and clear of text. Hover changes only opacity/colour.
- `feedback.css`, loaded last, removes all assessment underlines. A pass colours the Han in refined teal and shows a 4.5–6 by 3.5px filled rounded lozenge. A distinct `speech-close` class shows a hollow lozenge. Wrong, uncertain and omitted results have no marker. Jyutping remains muted. Pending live recognition has only a faint Han wash and is never marked as passed.
- The existing `retry` state included incorrect language and wrong words, so it must not be reused for close. Root owns service/client changes introducing the separate close state and its accessible descriptions.
- On a phone, final feedback uses 90% Han size and 4px bottom padding within the existing reading field. The outer reel-window halo is removed, retaining its border and inset shadow, so the tiny markers cannot be covered by that halo. Reel/window/cassette bounds remain unchanged.

## Integration

Append selection.css after materials.css, and feedback.css last. Append selection.js after the player. At the start of the existing positionSelectionClear() function, delegate with `if(window.RewindSelection){window.RewindSelection.position();return;}`. All existing pointer drag, word click, Shift+Arrow, Escape and bounded playback logic remains in app.js.

## Checks

Own isolated Chromium checks at 1440px and 390px used real pointer dragging and verified three selected tokens, clear-symbol visible bounds avoiding text, no hover fill, clearing selection, and no assessment underlines. Screenshots are in `../qa/selection-latest-*`, `selection-hover-*`, and `feedback-latest-*`. Feedback screenshots use explicitly injected UI classes for visual testing; they do not represent a live model assessment. Independent integrated QA remains the release check.
