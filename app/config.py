"""Environment and paths. Keys are read at call time."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "samples"
STATIC_DIR = ROOT / "static"


def load_env() -> None:
    """Load KEY=VALUE lines from .env without overriding the process environment."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def key(name: str) -> str:
    return os.environ.get(name, "").strip()


def flag(name: str) -> bool:
    return key(name).lower() in {"1", "true", "yes", "on"}


def cache_dir() -> Path:
    raw = key("PROVENANCE_CACHE_DIR") or str(ROOT / "cache")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def openai_model() -> str:
    return key("OPENAI_VISION_MODEL") or "gpt-4o-mini"


def gemini_model() -> str:
    return key("GEMINI_VISION_MODEL") or "gemini-2.5-flash"


def treg_tool() -> str:
    return key("TREG_LENS_TOOL") or "serper.google.serp.lens"


def xdc_payto() -> str:
    return key("XDC_PAYTO")


def xdc_price_base() -> str:
    raw = key("XDC_PRICE_BASE") or "20000"
    if raw.isdigit() and int(raw) > 0:
        return raw
    return "20000"


def paywall_on() -> bool:
    return bool(key("XDC_AI_KEY") and xdc_payto())


# Wall-clock budget for one check. Provider HTTP timeouts must not run longer than this.
CHECK_DEADLINE_S = 60.0


def check_deadline_s() -> float:
    """Seconds allowed for one check. CHECK_DEADLINE_S in the environment overrides the 60s default."""
    raw = key("CHECK_DEADLINE_S")
    if not raw:
        return CHECK_DEADLINE_S
    try:
        value = float(raw)
    except ValueError:
        return CHECK_DEADLINE_S
    if value <= 0:
        return CHECK_DEADLINE_S
    return value


load_env()
