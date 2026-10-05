"""Generator-independent input knowledge: semantic guidance and constraints.

Step 2 of the wizard captures what valid inputs mean; this package holds the
parts of that which are not the grammar. Nothing here is interpreted by an
LLM, and nothing here reaches the network.
"""
from .extract import ExtractResult, SpecError, extract_text, docs_support
from .model import (
    GUIDANCE_SUFFIXES, NATIVE_GENERATORS, STRUCTURED_SUFFIXES, SPEC_DIR,
    Semantics, load_semantics, digest_semantics, safe_spec_name,
)

__all__ = [
    "ExtractResult", "SpecError", "extract_text", "docs_support", "GUIDANCE_SUFFIXES",
    "NATIVE_GENERATORS", "STRUCTURED_SUFFIXES", "SPEC_DIR", "Semantics", "load_semantics",
    "digest_semantics", "safe_spec_name",
]
