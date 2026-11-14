"""HTTP API and the single-page desk."""

from __future__ import annotations

import base64
import binascii

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, pipeline, samples, x402

app = FastAPI(
    title="Provenance",
    version="0.1.0",
    description=(
        "Check whether a viral image is likely real, AI-generated, or out of context. "
        "POST /api/check with a JSON body. POST /api/x402/check is the pay-per-verify alias."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BYTES = 8_000_000


def _sniff(data: bytes, declared: str) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if declared.startswith("image/"):
        return declared
    return "image/jpeg"


def _decode_image(raw: str) -> bytes:
    text = (raw or "").strip()
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        data = base64.b64decode(text, validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=400, detail="image_base64 is not valid base64.") from exc
    if not data:
        raise HTTPException(status_code=400, detail="image_base64 was empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image is larger than 8 MB.")
    return data


async def _payload(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("image")
        data = b""
        filename = ""
        media_type = ""
        if upload is not None and hasattr(upload, "read"):
            data = await upload.read()
            filename = getattr(upload, "filename", "") or ""
            media_type = getattr(upload, "content_type", "") or ""
            if len(data) > MAX_BYTES:
                raise HTTPException(status_code=400, detail="Image is larger than 8 MB.")
        return {
            "image_bytes": data,
            "media_type": _sniff(data, media_type) if data else "image/jpeg",
            "filename": filename,
            "claim": str(form.get("claim") or ""),
            "image_url": str(form.get("image_url") or ""),
            "demo_id": str(form.get("demo_id") or ""),
        }
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Send JSON or multipart form data.") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object.")
    data = b""
    if body.get("image_base64"):
        data = _decode_image(str(body["image_base64"]))
    return {
        "image_bytes": data,
        "media_type": _sniff(data, str(body.get("media_type") or "")),
        "filename": str(body.get("filename") or ""),
        "claim": str(body.get("claim") or ""),
        "image_url": str(body.get("image_url") or ""),
        "demo_id": str(body.get("demo_id") or ""),
    }


def _run(payload: dict) -> dict:
    try:
        return pipeline.run_request(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "provenance",
        "keys": {
            "openai": bool(config.key("OPENAI_API_KEY")),
            "gemini": bool(config.key("GEMINI_API_KEY")),
            "youcom": bool(config.key("YDC_API_KEY")),
            "treg": bool(config.key("TREG_API_KEY")),
            "xdc_ai": config.paywall_on(),
        },
    }


@app.get("/api/demos")
def demos() -> dict:
    return {"demos": samples.public_list()}


@app.get("/api/demos/{demo_id}/image")
def demo_image(demo_id: str):
    sample = samples.get(demo_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="Unknown demo.")
    return FileResponse(sample["path"], media_type="image/jpeg")


@app.post("/api/check")
async def check(request: Request) -> dict:
    return _run(await _payload(request))


@app.get("/api/x402/listing")
def x402_listing(request: Request) -> dict:
    return x402.listing(request)


@app.get("/api/x402/check")
def x402_discover(request: Request):
    if config.paywall_on():
        return JSONResponse(x402.challenge(request), status_code=402)
    return {
        "paywall": False,
        "detail": "Set XDC_AI_KEY and XDC_PAYTO to advertise the 402 challenge on this URL.",
        "listing": x402.listing(request),
    }


@app.post("/api/x402/check")
async def x402_check(request: Request):
    payload = await _payload(request)
    payment = x402.gate(request)
    if isinstance(payment, JSONResponse):
        return payment
    result = _run(payload)
    result["payment"] = payment
    return result


@app.get("/")
def home():
    return FileResponse(config.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
