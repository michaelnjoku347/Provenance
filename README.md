# Provenance

A newsroom desk that checks a viral image by the story around it, then shows the receipts.

Pixel-only detectors miss the expensive failure: a real photo from 2011 posted as this morning's flood, or a generated picture wearing a breaking-news caption. Provenance reads the claim, the file's own credentials, and what credible outlets are publishing right now. The verdict is one of **Likely Real**, **Likely AI or Fake**, **Out of Context**, or **Unverified**, with a confidence score, three or four clues, a first-seen timeline, and source links.

## Who it's for

Primary customer: a social or homepage editor who has a few minutes to repost or hold a viral image. Secondary: a brand team checking a fake ad, a fake recall, or a fake executive photo before it spreads.

## How a check works

```text
image + optional caption
        |
        +-- vision model (OpenAI or Gemini) --> who / what / where / when
        +-- EXIF + C2PA marker scan
        +-- local AI-image prior (one weak clue)
        |
        +-- You.com Search (highlights) --+--> Contents API (top sources)
        |                                 +--> Answer API, or Research API if YDC_USE_RESEARCH=1
        +-- Treg reverse image (optional, public URL only)
        |
        +-- verdict, clues, timeline, clickable sources
        |
        +-- cache/<sha>.json so the same check does not spend credits again
```

The AI-image score cannot carry a verdict by itself. A file dated 2011 with a "this morning" caption can be Out of Context with no web key at all. Calling an image Likely Real needs corroboration, which is why the live web step is the product.

## Sponsors on this build

| Sponsor | Role |
| --- | --- |
| **You.com** (required) | Live web. `POST https://ydc-index.io/v1/search` with highlights and `knowledge: core`, then the Contents API and the Answer API (Research API when `YDC_USE_RESEARCH=1`). |
| **OpenCrawl** (required) | Multiplayer tool for the coding agents during the build: shared session search and an agent board so the pipeline and the desk stay aligned across machines. The running checker does not call OpenCrawl. |
| **Treg** (optional) | Reverse image / first-seen. One `TREG_API_KEY` calls `https://treg.to/call/serper.google.serp.lens` (or `TREG_LENS_TOOL`). No key, or no public image URL, and this step skips. |
| **XDC AI** | Pay-per-verify. Agents discover `POST /api/x402/check` and pay 0.02 USDC on XDC over [x402](https://docs.xdcai.tech/reference/x402-flow). The endpoint speaks the 402 challenge. Settlement is stubbed in this build: a payment header is accepted and labeled unsettled, so the demo never moves funds. |

## 60-second demo

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000 and click the three samples:

1. **City hall, this morning** — camera-style file, same-day claim. Stays **Unverified** until You.com can see reporting.
2. **Relief-bill photograph** — software tag says Stable Diffusion XL. **Likely AI or Fake**.
3. **Flooding, claimed as this morning** — file date is 2011. **Out of Context**.

Put `YDC_API_KEY` in `.env` and restart. The same desk then searches the live web and lists source links. Vision needs `OPENAI_API_KEY` or `GEMINI_API_KEY`. Reverse image needs `TREG_API_KEY` plus a public image URL.

Interactive API reference: http://127.0.0.1:8000/docs

## API

`POST /api/check` accepts JSON. Other clients can call it directly.

```bash
curl -s http://127.0.0.1:8000/api/check \
  -H 'content-type: application/json' \
  -d '{"demo_id":"archive"}'
```

Upload:

```bash
python3 - <<'PY'
import base64, json, pathlib, urllib.request
image = pathlib.Path("photo.jpg").read_bytes()
body = json.dumps({
    "image_base64": base64.b64encode(image).decode(),
    "media_type": "image/jpeg",
    "filename": "photo.jpg",
    "claim": "Posted today as a photo of the mayor resigning.",
    "image_url": "https://cdn.example.com/mayor.jpg"
}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/check", data=body, headers={"content-type": "application/json"})
print(urllib.request.urlopen(req).read().decode())
PY
```

Multipart also works: fields `image`, `claim`, `image_url`, `demo_id`.

A receipt looks like this (fields trimmed):

```json
{
  "verdict": "Out of Context",
  "confidence": 67,
  "summary": "The picture may be real, but it does not match the time or the story in the claim.",
  "claim": {"text": "This photo was taken this morning of flooding downtown.", "source": "caption"},
  "clues": [{"title": "Capture time vs claim", "detail": "The file date is 2011-03-11...", "weight": "strong", "url": ""}],
  "timeline": [{"at": "2011-03-11T14:46:23", "label": "File timestamp (EXIF)", "url": ""}],
  "sources": [{"title": "...", "url": "https://...", "outlet": "reuters.com", "excerpt": "..."}],
  "stages": {"youcom_search": {"status": "skipped", "detail": "YDC_API_KEY is not set."}},
  "cache": {"hit": false, "key": "abc123"}
}
```

`stages.*.status` is `ok`, `skipped`, or `error`. A skipped stage never fails the check. Repeated successful checks are written to `cache/` (gitignored). The cache key includes which provider keys were present, so adding a key runs the check again.

`GET /api/health` reports which keys are set, without revealing them. `GET /api/demos` lists the three samples.

### Pay per verify (XDC AI)

Free path for the desk demo: `POST /api/check`.

Payable alias: `POST /api/x402/check`. It behaves like `/api/check` until both `XDC_AI_KEY` and `XDC_PAYTO` are set. Then a call with no `X-PAYMENT` or `PAYMENT-SIGNATURE` header returns **402** with a v1 and v2 x402 challenge: 0.02 USDC (`20000` base units), asset `0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1` on XDC (`eip155:50`). `GET /api/x402/listing` is the marketplace entry (URL, method, price, capability, tags). `GET /api/x402/check` returns the challenge once the paywall is on.

This build does **not** settle the transfer. A syntactically valid payment header is marked `accepted_unsettled`. Listing the endpoint on the XDC AI marketplace, and verifying EIP-3009 through a facilitator, is the production step. Docs: https://docs.xdcai.tech/providers/x402-endpoint

## Tests

```bash
pytest
```

The suite mocks You.com and Treg. With no keys, the three samples still produce verdicts and the HTTP client is never called.

## Roadmap

- Video: sample frames, run the same claim check, and keep the frame that carries the caption.
- Browser extension: right-click an image on X, Threads, or a CMS and open this receipt.
- Newsroom API: monthly seat (about $499 for 2,000 checks) for desks that do not want to hold provider keys. Agents pay per call in USDC on XDC once settlement is real.
- Stronger credentials via the full `c2pa` library when the install is available. The byte scan already degrades cleanly.
- Human review queue for Unverified items above a traffic threshold.

The plan for the hackathon day, and a three-minute pitch, is in [docs/PLAN.md](docs/PLAN.md).
