"""
Redaction utilities for sanitizing sensitive data in logs and events.
"""
import re
from typing import Any


# Sensitive field patterns (case-insensitive)
SENSITIVE_PATTERNS = [
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

REDACTION_PLACEHOLDER = "***REDACTED***"


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name matches any sensitive patterns."""
    return any(pattern.match(key) for pattern in SENSITIVE_PATTERNS)


def redact_sensitive_data(data: Any, max_depth: int = 10) -> Any:
    """
    Recursively redact sensitive fields from data structures.
    
    Args:
        data: Dict, list, or primitive value to redact
        max_depth: Maximum recursion depth to prevent infinite loops
        
    Returns:
        Copy of data with sensitive fields redacted
    """
    if max_depth <= 0:
        return data
    
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            if _is_sensitive_key(str(key)):
                redacted[key] = REDACTION_PLACEHOLDER
            else:
                redacted[key] = redact_sensitive_data(value, max_depth - 1)
        return redacted
    
    elif isinstance(data, list):
        return [redact_sensitive_data(item, max_depth - 1) for item in data]
    
    elif isinstance(data, tuple):
        return tuple(redact_sensitive_data(item, max_depth - 1) for item in data)
    
    else:
        # Primitive types (str, int, float, bool, None) pass through
        return data
