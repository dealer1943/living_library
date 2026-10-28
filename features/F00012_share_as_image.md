# F00012 — Share selected chats as an image

| Field | Value |
|-------|-------|
| State | Verified (pre-MVP) |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | 2026-10-28 18:04 America/New_York — headless Chrome over CDP (ll_uitest.mjs, 18/18 checks, 0 page errors): `shareCanvas` rendered a 1280-px-wide PNG (2× of 640) of a persona tab, `/share last 2` opened the preview dialog with the image; card inspected visually |
| Owner | arcane dealer + Grok Bot |
| Class | export / ux |
| Lineage | Owner steer 2026-10-28: "export selected chats as an image for social sharing" |
| Depends on | F00011, F00009 (skin colors), F00010 (labels) |
| Components | `static/index.html` (`#share-btn`, `#selbar`, `dialog#share`, `shareCanvas`, `/share`) |

## Summary
Pick messages and get a clean, screenshot-style **PNG card** to post: a header with the tab's
avatar, name (label) and neuron(s) + α, the chosen bubbles styled in the current skin, and a footer
"Living Library · model · date".

## Design
- Pure `<canvas>` (no libraries), 640 logical px wide at 2× scale, height up to 7000 px; anything
  beyond ends with "… N more".
- Options in the preview: include thoughts, include neuron line. **Download PNG**
  (`living-library-<label>-<stamp>.png`) or **Copy image** (`ClipboardItem`).
- Entry points: header **Share** button or the share icon under a bubble → select mode
  (checkbox on each bubble, bar with count / All / None / Cancel / **Make image**; Esc exits);
  `/share` (select mode), `/share all`, `/share last N` (default 2). `/image` is an alias.

## Acceptance / Verification
- [x] Selected messages only, in order, styled in the active skin.
- [x] Download and copy both work; long chats are clipped with a note.

## Status log
- 2026-10-28 — created from the owner's steer.
- 2026-10-28 18:04 — implemented and verified: headless Chrome over CDP (ll_uitest.mjs, 18/18 checks, 0 page errors).
