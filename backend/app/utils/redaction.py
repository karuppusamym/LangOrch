"""
Redaction utilities for sanitizing sensitive data in logs and events.

Supports both hardcoded default patterns and configurable patterns
from CKP `global_config.audit_config.redacted_fields`.
"""
import re
from typing import Any


# Default sensitive field patterns (case-insensitive)
DEFAULT_SENSITIVE_PATTERNS = [
    re.compile(r"^.*password.*$", re.IGNORECASE),
    re.compile(r"^.*token.*$", re.IGNORECASE),
    re.compile(r"^.*api[_-]?key.*$", re.IGNORECASE),
    re.compile(r"^.*secret.*$", re.IGNORECASE),
    re.compile(r"^.*credential.*$", re.IGNORECASE),
    re.compile(r"^.*authorization.*$", re.IGNORECASE),
    re.compile(r"^.*auth.*$", re.IGNORECASE),
    re.compile(r"^.*private[_-]?key.*$", re.IGNORECASE),
    re.compile(r"^.*access[_-]?key.*$", re.IGNORECASE),
    re.compile(r"^.*client[_-]?secret.*$", re.IGNORECASE),
]

# Keep backward-compatible alias
SENSITIVE_PATTERNS = DEFAULT_SENSITIVE_PATTERNS

REDACTION_PLACEHOLDER = "***REDACTED***"


def build_patterns(extra_fields: list[str] | None = None) -> list[re.Pattern]:
    """
    Build a combined list of redaction patterns from defaults and extra field names.

    Args:
        extra_fields: Additional field name patterns from CKP audit_config.redacted_fields.
                      Each entry is treated as a regex pattern (case-insensitive).
                      Plain strings are auto-wrapped in .*<pattern>.* for substring matching.

    Returns:
        Combined list of compiled regex patterns.
    """
    patterns = list(DEFAULT_SENSITIVE_PATTERNS)
    if extra_fields:
        for field in extra_fields:
            try:
                # If it looks like a regex (has special chars), use as-is
                if any(c in field for c in r".*+?[](){}^$|\\"):
                    patterns.append(re.compile(field, re.IGNORECASE))
                else:
                    # Plain field name — match as substring
                    patterns.append(re.compile(rf"^.*{re.escape(field)}.*$", re.IGNORECASE))
            except re.error:
                # Invalid regex — skip this pattern
                continue
    return patterns


def _is_sensitive_key(key: str, patterns: list[re.Pattern] | None = None) -> bool:
    """Check if a key name matches any sensitive patterns."""
    check_patterns = patterns if patterns is not None else DEFAULT_SENSITIVE_PATTERNS
    return any(pattern.match(key) for pattern in check_patterns)


def redact_sensitive_data(
    data: Any,
    max_depth: int = 10,
    extra_patterns: list[re.Pattern] | None = None,
) -> Any:
    """
    Recursively redact sensitive fields from data structures.
    
    Args:
        data: Dict, list, or primitive value to redact
        max_depth: Maximum recursion depth to prevent infinite loops
        extra_patterns: Additional compiled patterns to check (from CKP audit_config).
                        If None, only default patterns are used.
        
    Returns:
        Copy of data with sensitive fields redacted
    """
    if max_depth <= 0:
        return data
    
    patterns = extra_patterns if extra_patterns is not None else DEFAULT_SENSITIVE_PATTERNS
    
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            if _is_sensitive_key(str(key), patterns):
                redacted[key] = REDACTION_PLACEHOLDER
            else:
                redacted[key] = redact_sensitive_data(value, max_depth - 1, patterns)
        return redacted
    
    elif isinstance(data, list):
        return [redact_sensitive_data(item, max_depth - 1, patterns) for item in data]
    
    elif isinstance(data, tuple):
        return tuple(redact_sensitive_data(item, max_depth - 1, patterns) for item in data)
    
    else:
        # Primitive types (str, int, float, bool, None) pass through
        return data
