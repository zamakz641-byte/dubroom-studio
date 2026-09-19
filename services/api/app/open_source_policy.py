from __future__ import annotations

import re
from typing import Any


OPEN_SOURCE_LICENSE_MARKERS = (
    "apache-2.0",
    "apache 2.0",
    "mit",
    "bsd-2-clause",
    "bsd-3-clause",
    "mpl-2.0",
    "gpl-2.0",
    "gpl-3.0",
    "lgpl-2.1",
    "lgpl-3.0",
    "agpl-3.0",
    "isc",
    "cc0",
    "unlicense",
)

RESTRICTED_LICENSE_MARKERS = (
    "non-commercial",
    "noncommercial",
    "research only",
    "cc-by-nc",
    "cc by-nc",
    "openrail",
    "llama community",
    "proprietary",
    "commercial api",
    "closed",
)


def normalise_license(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def is_open_source_license(value: Any) -> bool:
    license_text = normalise_license(value)
    if not license_text:
        return False
    if any(marker in license_text for marker in RESTRICTED_LICENSE_MARKERS):
        return False
    return any(marker in license_text for marker in OPEN_SOURCE_LICENSE_MARKERS)


def engine_license(engine: dict[str, Any]) -> str:
    model = engine.get("model") if isinstance(engine.get("model"), dict) else {}
    return str(model.get("license") or engine.get("license") or "")


def is_open_source_engine(engine: dict[str, Any]) -> bool:
    return is_open_source_license(engine_license(engine))


def require_open_source_engine(engine: dict[str, Any], purpose: str) -> None:
    if is_open_source_engine(engine):
        return
    label = str(engine.get("display_name") or engine.get("id") or "Unknown engine")
    license_text = engine_license(engine) or "missing license"
    raise RuntimeError(
        f"{purpose} requires an open-source engine. "
        f"{label} is blocked by the strict license policy ({license_text})."
    )
