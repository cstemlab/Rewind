# Rewind r11 — cassette material references

Research and visual inspection: 16 November 2026. This is a design reference record, not licensed artwork bundled into the app. The app uses its own SVG/CSS drawing; no product photograph or trademark has been embedded.

## Actually inspected photographs

- [National Audio Company shell-colour chart, April 2025](https://www.nationalaudiocompany.com/wp-content/uploads/2025/04/NAC_CassetteColorChart.pdf). Downloaded the public manufacturer PDF solely for local visual inspection and rendered page 1. The 20 front-facing examples distinguish solid shells, clear shells with black or clear liners, and coloured/smoky translucent shells. Clear and smoky examples show bottom guide rollers, moulded supports and a lower tape route through the shell. Solid opaque shells remain a legitimate material option. The reference also has metallic finishes; these were intentionally excluded in response to the user's preference for plastic.
- [Opened Memorex compact cassette, Mathwiz593, Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Memorex_Compact_Cassette_opened.jpg). Inspected the full-resolution annotated photograph. Two reel hubs sit on a shared horizontal axis. Two guide rollers sit near the lower corners; the tape runs along the bottom toward a central pressure pad. The centre is not a third roller. Ribbing is localized around the moulded lower body and side edges, not an arbitrary regular internal lattice.
- [Maxell UR, official manufacturer product page](https://www.maxell.jp/consumer/ur.html), [product photograph](https://www.maxell.jp/consumer/assets/img/new_ur_02.png). Inspected the photographed clear shell. A broad opaque writing strip sits above the hub window. Dark wound tape remains visible through the clear shell, while the paper/writing strip is opaque. A subtle lower trapezoid and moulded supports carry structure without a polished metallic perimeter.

## Applied design decisions

- Preserve the existing 1.58:1 shell, fixed window/hub positions and transport positions. Changing the material never moves the reels, labels, controls or text.
- Material is independent of colour: Matte hides the inner structure; Smoked shows a subdued view; Clear exposes the guide rollers, lower tape route, screw bosses, pressure-pad housing and restrained moulded supports. Colour tint stays independent of material.
- Keep the flat shell edge, full-sized existing screws and quiet case finish. No chrome reflections, glass highlights, deep bevel or sci-fi mechanism.
- A paper sticker remains opaque. Its colour and print pattern change independently of the plastic and independently of the three print colours. Keep the writing field free from rules and patterns.
- Show all controls within the existing temporary cassette options panel. The four direct controls are Material, Case, Sticker and Pattern; Print colours follow the pattern. The 24 existing complete presets remain in a collapsed Presets group.
- Automatically choose readable ink, muted text, active accent and blue pronunciation feedback against each custom sticker colour. Propagate the chosen palette into temporary options and the page surround.

## Source boundaries

The user-supplied photographs remain the primary direction for aesthetic proportion and sticker composition. Product photographs were additional observations, not copied assets. The private IN-SMART script/audio was not sent to any research source.

## Integration

Append materials.css after all existing styles and materials.js after layout-ui.js (and any later player modules). The module mounts itself in #skins-dialog and keeps #skin-grid for presets. Public API: window.RewindMaterials.get(), set(partial), reset(), validate(state), contrast(hexA,hexB). Storage key: rewind-materials-v1. Reset restores the appearance derived from the currently selected complete preset. Other modules should listen for rewind:materialchange if they need appearance changes.
