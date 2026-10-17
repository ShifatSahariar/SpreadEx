"""Scrub credentials from anything that might be shown, logged, stored or exported."""

from __future__ import annotations

import os
import re

from . import settings

#: Environment variables whose values are credentials wherever they appear.
SECRET_ENV = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
#: Shapes of common provider keys, for keys SpreadEx was never told about.
_KEY_SHAPES = re.compile(r"\b(sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,})")


def _known() -> list[str]:
    vals = [settings.session_key()] + [os.environ.get(n) for n in SECRET_ENV]
    return [v for v in vals if v and len(v) >= 8]


def redact(text):
    """`text` with every known key, and anything shaped like one, replaced."""
    if text is None or not isinstance(text, str):
        return text
    for secret in _known():
        text = text.replace(secret, "[redacted]")
    return _KEY_SHAPES.sub("[redacted]", text)


def redact_obj(obj):
    """Redact every string inside a JSON-like structure."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj
