"""MAC vendor lookup from the IEEE public OUI listing bundled with the app."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data" / "oui.tsv"


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    if not _DATA.exists():
        return {}
    table: dict[str, str] = {}
    for line in _DATA.read_text(encoding="utf-8", errors="replace").splitlines():
        prefix, _, name = line.partition("\t")
        if prefix and name:
            table[prefix.upper()] = name
    return table


def vendor(mac: str | None) -> str:
    if not mac:
        return ""
    cleaned = "".join(ch for ch in mac.upper() if ch in "0123456789ABCDEF")
    if len(cleaned) < 6:
        return ""
    return _table().get(cleaned[:6], "")
