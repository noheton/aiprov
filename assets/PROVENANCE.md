# Provenance of the logo

| Item | Value |
|---|---|
| What | the aiprov badge: a white salmon leaping up a waterfall in a teal-to-blue circle (identity and brief: `docs/identity.md`) |
| How it was made | generated in the Gemini web app on the owner's request on 2026-10-25; the owner chose the picture (the first result) |
| Prompt | the prompt in `docs/identity.md` ("Image brief"), used word for word, first result: stated by the owner on 2026-10-25, not verifiable from the generator's side. sha256 of the prompt text as it stands in that file (without the leading `> `): `0461f5902fa5a3d31154c19ceb1c55c4df14a4e805b8da5196da188ae33ce230` |
| Model | Gemini web app, model selector on "Automatic: Gemini 3-Modelle" (stated by the owner); the exact image model behind "Automatic" is not shown, so not known |
| How the file arrived | the owner pasted the picture into an AI coding session (OpenCode) as an inline image ("Image 1", 2026-10-25 19:34 UTC); the AI saved those bytes from the session store. Whether the owner copied the app's image or downloaded it is not recorded; at exactly 1024 × 1024 px it is most likely the app's own image and not a screenshot (conjecture) |
| Marking | none visible from the generator; no EU AI marking or XMP metadata was applied. The picture is AI-generated and recorded as such here |
| Rights | Google's Terms of Service (country version Germany, effective 2026-07-30, read 2026-10-25) say Google will not claim ownership of content a user generates; the Generative AI Prohibited Use Policy forbids presenting generated content as made solely by a human. Whether an AI-generated picture carries copyright in the EU is not settled; the repository licence (MIT) grants whatever rights exist. Details: `docs/identity.md` |
| Processing | by an AI session (Claude Opus 5.5 in OpenCode), deterministic, no retouching: the generator painted a checkerboard where the prompt asked for transparency (real pixels, plus a faint grey patch right of the circle); the badge circle was found by colour saturation (664 × 664 px bounding box, centred), cropped square, masked to a circle with real transparency, the mask set 3 px inside the edge to drop the rim blended with the checkerboard, resized with Lanczos. The circle is 665 px across in the source, so the 1024 px file is **upscaled** and softer than a native export. Script: `assets/make_icon.py` (reproduces both files byte for byte) |
| Files | `aiprov-icon-source-gemini.png` (as received, 1024 × 1024, sha256 `670dc0f0fffbc4795b85034e7f25d80b5255aaa4d1a591dbd02dc69e48453eea`), `aiprov-icon-1024.png` (sha256 `cd2fb09fcdd63b4d482a69c28e34a939f332e423df4f1acb960a9473c8f32f62`), `aiprov-icon.png` 512 px (sha256 `8ed155562e27cf30a106885f1883684942d814a49b074ee53da5c9287fdd0770`) |
| Chosen by | the owner (human) |

## Social preview

| Item | Value |
|---|---|
| What | `aiprov-social-preview.png`, 1280 × 640 px, for the repository's social preview; the owner sets it in the repository settings (GitHub has no API for it) |
| How it was made | by an AI session (Claude Opus 5.5 in OpenCode) on the owner's request on 2026-10-25, with `make_social_preview.py` (theme `dark`) from `aiprov-icon-source-gemini.png`: the badge cut as in `make_icon.py` and resized once, from the 665 px circle down to 440 px; a background gradient; the text set in Inter 4.1 (SIL Open Font License 1.1; Debian package `fonts-inter` 4.1+ds-1, Inter Display Bold, Inter SemiBold, Regular, Medium). The script reproduces the file byte for byte on a machine with the same fonts and Pillow |
| Layout | GitHub's repository card template: everything important stays inside the 80 px (40 pt) safe area; the badge and text block is centred in it (measured: 38 px left, 35 px right, 22 px top and bottom) |
| Text | "aiprov", "AI provenance", "recorded, open, verifiable", "W3C PROV-O · github.com/noheton/aiprov" |
| Generated content | the badge only (see above); layout and text are deterministic |
| File | sha256 `d05574a696a708fcf53860ecedbc26898abd0ecd013a9631295bf2f6bcd6e8d7`, 181,844 bytes |
