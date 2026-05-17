"""Test harness: load the shop app from an isolated copy, optionally with a
defect patch applied, so each test runs against fresh in-memory state and the
defect patches are exercised exactly as they ship (full-file replacement)."""

from __future__ import annotations

import importlib
import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SHOP_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = SHOP_ROOT / "app"
DEFECTS_DIR = SHOP_ROOT / "defects"


def load_patch(key: str) -> list[tuple[str, str]]:
    """Return [(path-relative-to-app, sabotaged content)] for a defect key."""
    data = json.loads((DEFECTS_DIR / key / "patch.json").read_text(encoding="utf-8"))
    files = []
    for entry in data["files"]:
        # entry["path"] looks like "shop/app/checkout.py"
        rel = entry["path"].split("app/", 1)[1]
        files.append((rel, entry["content"]))
    return files


@pytest.fixture
def shop_app(tmp_path):
    """Factory: shop_app(overrides=None) -> TestClient on a fresh app copy.

    `overrides` is an iterable of (relpath-within-app, content) to write over the
    copied source before import — that's how a defect patch is applied.
    """
    created: list[str] = []
    added_paths: list[str] = []

    def _build(overrides=None, raise_server_exceptions=False) -> TestClient:
        pkg = "shopcopy_" + uuid.uuid4().hex[:8]
        dest = tmp_path / pkg
        shutil.copytree(APP_DIR, dest, ignore=shutil.ignore_patterns("__pycache__"))
        for rel, content in overrides or []:
            (dest / rel).write_text(content, encoding="utf-8")
        if str(tmp_path) not in sys.path:
            sys.path.insert(0, str(tmp_path))
            added_paths.append(str(tmp_path))
        module = importlib.import_module(f"{pkg}.main")
        created.append(pkg)
        # Default: behave like a real HTTP client and return 500s rather than
        # re-raising. Pass raise_server_exceptions=True to inspect the traceback.
        return TestClient(module.app, raise_server_exceptions=raise_server_exceptions)

    yield _build

    for pkg in created:
        for name in list(sys.modules):
            if name == pkg or name.startswith(pkg + "."):
                del sys.modules[name]
    for p in added_paths:
        if p in sys.path:
            sys.path.remove(p)
