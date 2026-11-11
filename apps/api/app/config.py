"""Minimal .env loader (stdlib only) + provider selection.

python-dotenv is not a dependency and this is 15 lines, so it is not worth adding one.
Loaded once at import; real environment variables always win over the file.
"""
from __future__ import annotations

import os
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent          # apps/api
_REPO = API_DIR.parent.parent                              # repo root
CANDIDATES = [API_DIR / ".env", _REPO / ".env"]


def load_env() -> list[str]:
    """Read KEY=VALUE pairs from the first .env found. Returns the keys applied."""
    applied: list[str] = []
    for path in CANDIDATES:
        if not path.exists():
            continue
        # utf-8-sig: Windows editors and PowerShell's Set-Content prepend a BOM, which would
        # otherwise glue itself to the first key name and silently skip that line.
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:  # never override a real env var
                os.environ[key] = value
                applied.append(key)
        break
    return applied


load_env()
