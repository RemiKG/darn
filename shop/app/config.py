"""Shop configuration — everything from the environment, nothing hardcoded.

The shop runs fine with no env at all (sensible local defaults). Optional
integrations (Darn link, OTel export) stay dark until their vars are set.
"""

from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# Port the shop binds to (Cloud Run injects PORT; local default per the repo contract).
PORT = _env_int("PORT", 4602)

# Public URL of the Darn app. When set, the torn-state banner can deep-link to a
# live incident. Empty = no link is shown; the shop degrades silently.
DARN_URL = _env("DARN_URL").rstrip("/")
