# Design assets

Icons are local SVG exports from the approved Figma file
`v4IxDkJNsw2k2LKkwfcR2e`, downloaded on 2026-10-14.
Do not replace them with temporary Figma URLs at runtime.

| Frame | Files | Intrinsic size / use |
| --- | --- | --- |
| 2:42769 Desktop first-assistant dashboard | brand.svg | 19px, inside 32px brand mark |
| 2:42769 | dashboard.svg, bot.svg, messages.svg | 18px desktop navigation |
| 2:42769 | plus.svg | 16px create links |
| 2:42769 | empty-bot.svg | 34px, inside 76px empty-state tile |
| 2:42769 | sliders.svg, files.svg, sparkles.svg | 23px guide cards |
| 2:44159 Mobile dashboard | menu.svg | 22px menu button |
| 2:44159 | home-mobile.svg, bot-mobile.svg, sparkles-mobile.svg, messages-mobile.svg | 21px bottom navigation |

`Icon.tsx` preserves intrinsic sizes. The deferred desktop Playground entry reuses
the 23px guide sparkles icon; this additional disabled entry is a scope adaptation.
Tokens and controls also reference the inspected UI kit frame 2:44340.
Inter is bundled locally through `@fontsource-variable/inter` (OFL-1.1; its license
is distributed with that package). No remote font request is needed.

UI-03 (2026-10-17): login `2:42474` and registration `2:42534` were inspected in
the approved copy `BzfdfMerOG9BoX28X4usvS`. `auth-sparkles.svg` (18px) appears in
the welcome-panel eyebrow; `auth-flower.svg` (21px) in the 42px sample avatar;
`auth-eye.svg` (17px) in the password toggle; `auth-lock.svg` (12px) in the security
note. Brand reuses the identical 19px SVG. Intrinsic dimensions are preserved.
On mobile the welcome illustration is hidden and the form reflows; no mobile Auth
frame was supplied. Google, recovery, full-name collection, and nonexistent policy
links were omitted to match approved scope. The static sample is explicitly labeled
illustrative and has no chat input or functionality.

UI-05 (2026-10-19): knowledge frame `2:43029` in approved copy
`BzfdfMerOG9BoX28X4usvS`. Added local `knowledge-*.svg`: upload (23px in
44px tile), plus (16px), file (18px in 38x44px tile), download/remove (17px),
ready/processing/failed (11px status markers), book (26px), check (15px), info
(18px). Original root dimensions retained. Existing shell assets are reused.
Adaptations: one upload at a time, real extracted status, no invented percentage
or retry endpoint, no Playground continuation, truthful private-storage copy.
