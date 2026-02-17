"""Safe expression evaluator — no eval(), restricted to comparison ops."""

from __future__ import annotations

import operator
import re
from typing import Any

from app.templating.engine import resolve_path, render_template_str

# Supported comparison operators
_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "contains": lambda a, b: b in a if hasattr(a, "__contains__") else False,
    "not_contains": lambda a, b: b not in a if hasattr(a, "__contains__") else True,
    "starts_with": lambda a, b: str(a).startswith(str(b)),
    "ends_with": lambda a, b: str(a).endswith(str(b)),
    "is_empty": lambda a, _: a is None or a == "" or a == [] or a == {},
    "is_not_empty": lambda a, _: not (a is None or a == "" or a == [] or a == {}),
    "in": lambda a, b: a in b if hasattr(b, "__contains__") else False,
}

# Pattern: left_operand operator right_operand
# e.g. "{{status}} == 'approved'"   or  "count >= 5"
_EXPR_RE = re.compile(
    r"^(.+?)\s+(==|!=|>=|<=|>|<|contains|not_contains|starts_with|ends_with|is_empty|is_not_empty|in)\s+(.+)$"
)

# Pattern for unary operators: "is_empty {{var}}"
_UNARY_RE = re.compile(r"^(is_empty|is_not_empty)\s+(.+)$")


def evaluate_condition(expr: str, ctx: dict[str, Any]) -> bool:
    """
    Evaluate a simple comparison expression safely.

    Supports:
      - {{var}} == 'literal'
      - {{var}} >= 5
      - {{var}} contains 'text'
      - is_empty {{var}}
      - true / false / yes / no

    No arbitrary code execution — uses operator dispatch only.
    """
    expr = expr.strip()

    # Boolean literals
    if expr.lower() in ("true", "yes", "1"):
        return True
    if expr.lower() in ("false", "no", "0"):
        return False

    # Render any templates first
    rendered = render_template_str(expr, ctx)

    # Try unary form: "is_empty {{var}}"
    unary_match = _UNARY_RE.match(rendered)
    if unary_match:
        op_str = unary_match.group(1)
        operand = _coerce(unary_match.group(2).strip())
        op_fn = _OPS.get(op_str)
        if op_fn:
            return bool(op_fn(operand, None))

    # Try binary form: "left op right"
    binary_match = _EXPR_RE.match(rendered)
    if binary_match:
        left = _coerce(binary_match.group(1).strip())
        op_str = binary_match.group(2).strip()
        right = _coerce(binary_match.group(3).strip())
        op_fn = _OPS.get(op_str)
        if op_fn:
            try:
                return bool(op_fn(left, right))
            except Exception:
                return False

    # Fallback: truthy check on resolved value
    resolved = resolve_path(rendered, ctx) if not rendered.startswith("{") else rendered
    if resolved is None:
        # Maybe it's already a plain value
        return bool(_coerce(rendered))
    return bool(resolved)


def _coerce(value: str) -> Any:
    """Coerce a string token to a Python value."""
    if not isinstance(value, str):
        return value

    stripped = value.strip()

    # Quoted strings
    if (stripped.startswith("'") and stripped.endswith("'")) or \
       (stripped.startswith('"') and stripped.endswith('"')):
        return stripped[1:-1]

    # Boolean
    if stripped.lower() in ("true", "yes"):
        return True
    if stripped.lower() in ("false", "no"):
        return False

    # None
    if stripped.lower() in ("none", "null"):
        return None

    # Number
    try:
        if "." in stripped:
            return float(stripped)
        return int(stripped)
    except ValueError:
        pass

    return stripped
