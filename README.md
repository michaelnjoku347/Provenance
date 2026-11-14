# Provenance

A newsroom desk that checks whether a claim is true, then shows the receipts.

Provenance is a claim checker, not an AI-image detector. You give it a claim — plain text, an X post, an article link, or a claim attached to an image or file — and it asks what credible sources say. The verdict is one of **True**, **Misleading or Out of Context**, **False**, or **Unverified**. An AI-image signal can appear on the receipt only as a weak clue. It never decides the claim.

## Who it's for

Primary customer: a social or homepage editor who has a few minutes to repost or hold a viral image. Secondary: a brand team checking a fake ad, a fake recall, or a fake executive photo before it spreads.

## How a check works

```text
claim, or an X post, or an article link
        + optional image or file
        |
        +-- X oEmbed (no key) for status text, author, date, and image
        +-- article title and text (You.com Contents when a key is set)
        +-- You.com Search --+--> Contents API (top sources)
        |                    +--> Answer API, or Research API if YDC_USE_RESEARCH=1
        +-- file date and post date, compared with "this morning" style claims
        +-- reverse image only when a public image URL is available
        |
        +-- verdict about the claim, sources, timeline
        |
        +-- cache/<sha>.json so the same check does not spend credits again
```

A file dated 2011 with a "this morning" claim is **Misleading or Out of Context** with no web key at all. Calling a claim **True** needs corroboration from credible sources. A generative software tag is recorded as a weak clue and cannot by itself make the claim **False**.

## Sponsors on this build

| Sponsor | Role |
| --- | --- |
| **You.com** (required) | Live web. `POST https://ydc-index.io/v1/search` with highlights and `knowledge: core`, then the Contents API and the Answer API (Research API when `YDC_USE_RESEARCH=1`). |
| **OpenCrawl** (build tool) | [OpenCrawl](https://getopencrawl.com) is multiplayer memory for coding agents: it keeps the full session transcript and exposes `opencrawl.search` and `opencrawl.board_sync`. It was used while this desk was built so agents could find earlier decisions. It does not crawl the public web for a check, and the running server does not call it. |
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

1. **City hall, this morning** — a same-day claim. Stays **Unverified** until You.com can see reporting, then **True** when credible sources agree.
2. **Relief-bill claim** — the file names a generative tool. That is only a weak clue, so without sources the claim stays **Unverified**.
3. **Flooding, claimed as this morning** — the file date is 2011. **Misleading or Out of Context**.

You can also paste an `x.com` or `twitter.com` status URL, or an article URL, with no image. The post text becomes the claim, and the post date is used when the claim says something is happening now.

While a check runs, the desk names the tool on each step: You.com Search, You.com Contents, You.com Answer, Treg reverse image, and XDC x402. Source cards say which tool found them. `GET /api/sponsors` reports whether each tool is connected and how many times this process has called it. Treg without a key shows “Treg: add key”. x402 without `XDC_AI_KEY` and `XDC_PAYTO` stays in a labeled test mode and does not charge. OpenCrawl is credited as a build tool, not as a live fetch.

Put `YDC_API_KEY` in `.env` and restart. The same desk then searches the live web and lists source links. Article pages are read with You.com Contents when that key is set. Vision needs `OPENAI_API_KEY` or `GEMINI_API_KEY`. Reverse image needs `TREG_API_KEY` plus a public image URL.

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
  "verdict": "Misleading or Out of Context",
  "confidence": 67,
  "summary": "The claim does not match the date or the context of the evidence.",
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
