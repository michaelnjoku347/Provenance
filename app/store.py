"""Disk cache so a repeated check does not spend API credits again."""

from __future__ import annotations

import json

from app import config


def get(key: str) -> dict | None:
    path = config.cache_dir() / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def put(key: str, payload: dict) -> None:
    path = config.cache_dir() / f"{key}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
