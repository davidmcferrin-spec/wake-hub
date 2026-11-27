"""Free-form tags shared by computers and hardware. #Office and office are the same tag."""

from __future__ import annotations

import json

from wakehub.errors import WakeHubError
from wakehub.hub import Hub

TABLES = ("devices", "pdus", "amt_endpoints", "jetkvm_endpoints", "plugs", "ups_cards", "rokus", "pdu_outlets")


def normalize_tags(values: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        for piece in str(value).replace(",", " ").split():
            text = piece.strip().lstrip("#").strip()
            if not text:
                continue
            if len(text) > 32:
                raise WakeHubError("a tag must be 32 characters or fewer")
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
    if len(cleaned) > 20:
        raise WakeHubError("a record can have at most 20 tags")
    return cleaned


def has_tags(owned: list[str], wanted: list[str]) -> bool:
    keys = {item.casefold() for item in owned}
    return all(item.casefold() in keys for item in wanted)


def list_tags(hub: Hub) -> list[str]:
    found: dict[str, str] = {}
    for table in TABLES:
        for row in hub.query(f"SELECT tags FROM {table}"):
            for tag in json.loads(row["tags"] or "[]"):
                text = str(tag).strip()
                if text:
                    found.setdefault(text.casefold(), text)
    return [found[key] for key in sorted(found)]
