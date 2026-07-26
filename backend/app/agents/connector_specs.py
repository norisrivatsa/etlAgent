from __future__ import annotations

from typing import Any

CONNECTOR_REQUIRED_FIELDS: dict[str, dict[str, list[str]]] = {
    "jdbc": {
        "incrementing": [
            "table",
            "incrementing_column",
            "connection_url",
            "username",
            "password",
        ],
        "timestamp": [
            "table",
            "timestamp_column",
            "connection_url",
            "username",
            "password",
        ],
        "query": ["query", "connection_url", "username", "password"],
    },
}


def missing_fields(connector_type: str, mode: str | None, known: dict[str, Any]) -> list[str]:
    """What's still needed to fully specify a connector of this type/mode.

    Keeps the Planner's requirements-gathering prompt narrow ("given what the user
    said and this list, what's missing") instead of freeform "ask good questions".
    """
    modes = CONNECTOR_REQUIRED_FIELDS.get(connector_type)
    if not modes or mode not in modes:
        return []
    return [field for field in modes[mode] if not known.get(field)]
