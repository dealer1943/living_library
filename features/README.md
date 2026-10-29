# features/

One doc per feature so the lineage of ideas stays traceable. Format: `TEMPLATE.md`
(same field-table style as the sibling repos' FEATURES folders). Stage is **pre-MVP** until the
MVP announcement. "Verified" is stamped `YYYY-MM-DD HH:MM America/New_York` with how it was checked.

| # | feature | state | verified |
|---|---|---|---|
| [F00001](F00001_command_color_coding.md) | Color-coded commands and parameters | Verified | 2026-10-28 13:57 |
| [F00002](F00002_slash_command_menu.md) | Slash menu with filtering and autocomplete | Verified | 2026-10-28 13:59 |
| [F00003](F00003_checkout_checkin_neurons.md) | Check out / check in neurons (five keywords) | Verified | 2026-10-28 14:21 |
| [F00004](F00004_persona_side_tabs.md) | A side tab for each persona | Verified | 2026-10-28 14:21 |
| [F00005](F00005_hybrid_checkout_mix_and_group.md) | Hybrid checkout: `--mix` blend or group chat | Verified | 2026-10-28 14:21 |
| [F00006](F00006_change_librarian_persona.md) | Change the Librarian's persona | Future / deferred | — (post-MVP test case) |
| [F00007](F00007_settings_librarian_neuron.md) | Settings: Librarian neuron / restore default | Future / deferred | — (post-MVP test case) |
| [F00008](F00008_settings_export.md) | Settings: export neurons + alphas, and chats | Verified | 2026-10-28 14:21 |
| [F00009](F00009_settings_skins.md) | Settings: skins / styles | Verified | 2026-10-28 14:05 |
| [F00010](F00010_rename_tabs.md) | Rename tabs: `/name`, ✎, double-click | Verified | 2026-10-28 18:04 |
| [F00011](F00011_copy_message.md) | Copy button under each bubble | Verified | 2026-10-28 18:04 |
| [F00012](F00012_share_as_image.md) | Share selected chats as a PNG card | Verified | 2026-10-28 18:04 |
| [F00013](F00013_continue_cut_replies.md) | Continue token-limit / interrupted replies in a new bubble | Verified | 2026-10-28 18:04 |
| [F00014](F00014_lounge_mute_alpha.md) | The Lounge: everyone checked in at one table — on/off, reset, archive, mute, per-voice α; α kept on check-in | Verified | 2026-10-29 08:38 |

Implementation order: 1 → 2 → 7/6/9 → 3 → 4 → 5 → 8 → 10 → 11 → 12 → 13 → 14. F00006/F00007 are deferred past the MVP (kept as future test cases).
