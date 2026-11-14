# Provenance build plan

Submission cutoff: **4:00 PM ET, 14 November 2026**. The live demo path comes first. Video and the browser extension stay on the roadmap in the README.

## Hour by hour

### Hour 1 — Contract and desk shape

Write down the four verdicts and the customer: a social editor who must repost or hold. Lock the You.com request (`POST /v1/search`, highlights, `knowledge: core`) and the skip rules for Treg and vision. Scaffold FastAPI, the JSON `/api/check` body, and a single page with an empty receipt.

Exit: `GET /api/health` returns 200.

### Hour 2 — File receipts

EXIF make, model, software, datetime. A C2PA byte scan that does not require the native library. Three synthetic samples: a camera-style file, a Stable Diffusion software tag, and a 2011 file with a "this morning" caption. The AI-image prior is implemented and capped so it cannot decide alone.

Exit: the three samples return Unverified, Likely AI or Fake, and Out of Context with no API keys.

### Hour 3 — Live web

You.com search, then Contents and Answer in parallel. Research API behind `YDC_USE_RESEARCH=1`. Parse credible outlets, fact-check language, and page dates into clues, a timeline, and source links. Cache the receipt under `cache/` keyed by image, claim, and which keys were set.

Exit: a mocked Reuters + AP response flips the city-hall sample to Likely Real, with clickable source URLs.

### Hour 4 — Reverse image, pay-per-verify, and the desk UI

Treg `serper.google.serp.lens` when `TREG_API_KEY` and a public `image_url` are both present. Otherwise skip with a clear stage detail. x402 challenge on `/api/x402/check` behind `XDC_AI_KEY` + `XDC_PAYTO`, plus a marketplace listing. Drag-and-drop page, loading state, verdict card, timeline, sources.

Exit: `pytest` green. The page runs the three samples in a browser.

### Hour 5 — Demo hardening (if the cutoff allows)

Try one live You.com query on a real claim from today. Confirm a bad key degrades to a stage error instead of a 500. Rehearse the three-minute pitch against the samples, then against one live image.

### Hour 6 — Stretch, only after the demo is boringly reliable

Video frame grab, or a right-click extension that posts the image to `/api/check`. Do not start either if the desk still hides its sources.

## What we are willing to cut

- On-chain USDC settlement. The 402 body and the listing are the hackathon proof. A facilitator settles later.
- A hosted OpenCrawl server inside this app. OpenCrawl is the multiplayer layer for the coding agents during the build, not a request-time dependency.
- Lab-grade AI detection. The prior is labeled weak on the receipt.

## Three-minute pitch

A homepage editor has four minutes. Someone has dropped a photo in the chat: flooding downtown, this morning, already moving on social. If the desk reposts a 2011 picture, or a generated one, the correction never catches the original. If they wait for a full forensics report, the moment is gone.

Pixel detectors do not solve this. A real camera file used under the wrong caption looks clean. A generated file with a convincing caption looks like news. The question is not only "is this a photograph." The question is "is this the event the caption claims, and is anyone credible reporting it right now."

Provenance is the desk for that question. You drop the image and the caption. A vision model writes the checkable claim: who, what, where, when. We read EXIF and any C2PA marker in the file. We ask You.com what the live web is saying, then we read the top pages and take a cited answer. If you have a public URL, Treg runs a reverse-image lookup for the first time that picture showed up. An AI-image score is on the receipt, and it is one weak clue. It does not get to overrule a timestamp or two wire stories.

The screen the editor sees is a verdict about the claim — True, Misleading or Out of Context, False, or Unverified — plus the sources, the dates, and links they can open. Misleading or Out of Context is the one that matters most: the file can be a real photograph and still be the wrong story. That call comes from the claim and the reporting, not from a model staring at the pixels. An AI-image signal stays a weak clue and cannot headline the receipt.

Who pays: the social desk and the homepage editor, on a monthly seat, about five hundred dollars for a couple thousand checks, because one bad repost costs more than the seat. Brand-safety teams pay the same way when a fake recall or a fake executive ad starts moving. Agents that do not want a seat pay per call, two cents in USDC on XDC through x402, and get the same JSON receipt our desk shows. We do not get paid for a vibe. We get paid when someone is about to publish.
