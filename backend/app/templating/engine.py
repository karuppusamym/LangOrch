"""Template engine — {{variable}} expansion and nested path resolution."""

from __future__ import annotations

import re
from typing import Any

# Matches {{path.to.var}} or {{path.to.var | default_value}}
_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.]+)\s*(?:\|\s*(.+?))?\s*\}\}")


def resolve_path(path: str, ctx: dict[str, Any]) -> Any:
    """Resolve dotted path like 'results.extraction.name' against a context dict."""
    parts = path.split(".")
    current: Any = ctx
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part in ("length", "len", "count"):
            current = len(current)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def render_template_str(template: str, ctx: dict[str, Any]) -> str:
    """Replace all {{path}} placeholders in a string with values from ctx."""
    if not isinstance(template, str):
        return template

    def replacer(match: re.Match) -> str:
        path = match.group(1)
        default = match.group(2) if match.group(2) else ""
        value = resolve_path(path, ctx)
        if value is None:
            return default.strip().strip("'\"") if default else match.group(0)
        return str(value)

    return _TEMPLATE_RE.sub(replacer, template)


def render_template_dict(data: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Recursively render templates in all string values of a dict."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        result[key] = _render_value(value, ctx)
    return result


def _render_value(value: Any, ctx: dict[str, Any]) -> Any:
    """Recursively render templates in any value."""
    if isinstance(value, str):
        return render_template_str(value, ctx)
    if isinstance(value, dict):
        return render_template_dict(value, ctx)
    if isinstance(value, list):
        return [_render_value(item, ctx) for item in value]
    return value
