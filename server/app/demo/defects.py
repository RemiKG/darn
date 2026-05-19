"""The four defects.

Descriptors (key, title, blurb, davis_expectation) are product copy.
The sabotage *content* lives in shop/defects/<key>/patch.json and
is loaded at startup; only descriptors are ever exposed — file contents never
leak through the API. The patch payload is for the sabotage backend.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("darn.demo")

# Resolved relative to this file: server/app/demo/defects.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

DEFECT_META: dict[str, dict[str, str]] = {
    "checkout-null": {
        "title": "The checkout null",
        "blurb": "Checkout forgets that carts can be empty. Nulls everywhere.",
        "davis_expectation": "error-rate spike on POST /api/checkout",
    },
    "catalog-stampede": {
        "title": "The catalog stampede",
        "blurb": "Every sock on the catalog page asks the database how it's feeling. Individually.",
        "davis_expectation": "response-time degradation on GET /api/catalog",
    },
    "penny-shaver": {
        "title": "The penny shaver",
        "blurb": "Totals drift by a cent — and the payment provider rejects them.",
        "davis_expectation": "error-rate spike on POST /api/pay",
    },
    "inventory-grenade": {
        "title": "The inventory grenade",
        "blurb": "Restock math throws; nobody catches.",
        "davis_expectation": "failure-rate spike on POST /api/inventory",
    },
}

_patches: dict[str, dict] = {}


def _defects_dir() -> Optional[Path]:
    candidates = [
        _REPO_ROOT / "shop" / "defects",
        Path.cwd() / "shop" / "defects",
        Path.cwd().parent / "shop" / "defects",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def load_defects() -> int:
    """Load patch.json payloads from shop/defects/*/. Tolerates absence —
    the catalog is static product copy; only sabotage needs the payloads."""
    _patches.clear()
    base = _defects_dir()
    if base is None:
        log.info("shop/defects not found — defect catalog is descriptor-only")
        return 0
    for key in DEFECT_META:
        patch_file = base / key / "patch.json"
        if not patch_file.is_file():
            continue
        try:
            _patches[key] = json.loads(patch_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("could not load %s: %s", patch_file, e)
    log.info("loaded %d defect patch payload(s) from %s", len(_patches), base)
    return len(_patches)


def defect_exists(key: str) -> bool:
    return key in DEFECT_META


def defect_title(key: str) -> str:
    return DEFECT_META.get(key, {}).get("title", key)


def defect_catalog() -> list[dict[str, str]]:
    """Descriptors only — no file contents leave the server."""
    out = []
    for key, meta in DEFECT_META.items():
        davis = meta["davis_expectation"]
        patch = _patches.get(key)
        if patch and isinstance(patch.get("davis_expectation"), str):
            davis = patch["davis_expectation"]
        out.append(
            {
                "key": key,
                "title": meta["title"],
                "blurb": meta["blurb"],
                "davis_expectation": davis,
            }
        )
    return out


def defect_patch(key: str) -> Optional[dict]:
    """Full patch payload (files + commit message) for the sabotage backend.
    Internal use only — never serialized into an API response."""
    return _patches.get(key)
