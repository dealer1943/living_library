# F00009 — Settings: skins / styles

| Field | Value |
|-------|-------|
| State | Planned |
| Stage | pre-MVP |
| Created | 2026-10-28 |
| Verified | pending |
| Owner | arcane dealer + Grok Bot |
| Class | settings / ux |
| Lineage | Owner brief 2026-10-28, item 9 ("pick from different skins or styles to apply to the site") |
| Depends on | F00007 |
| Components | `static/index.html` (`[data-skin]` CSS variable sets, skin picker, `/skin`) |

## Summary
Settings → Skins offers a gallery of themes, each a full set of CSS variables (surfaces, ink,
bubbles, accent, the F00001 token colors, fonts):
**Alexandria** (default — lamp-lit dark), **Parchment** (light vellum), **Midnight** (deep blue),
**Terminal** (green-on-black, monospace), **Marble** (high-contrast light).
Choice persists in localStorage and applies before first paint (no flash). `/skin NAME` too.

## Acceptance / Verification
- [ ] Each skin swatch applies instantly; tokens stay legible in every skin.
- [ ] Persists across reload with no flash of the default theme.

## Status log
- 2026-10-28 — created from the owner's brief.
