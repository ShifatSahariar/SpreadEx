"""The `semantics:` block of spreadex.yaml, validated and hashable.

    semantics:
      guidance: [spec/semantics.md]        # natural language, any generator
      structured: spec/constraints.yaml    # reserved: stored and hashed, not interpreted
      native:                               # used as written, by that generator only
        fandango: spec/constraints.fan
        isla: spec/constraints.isla
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

SPEC_DIR = "spec"
GUIDANCE_SUFFIXES = (".txt", ".md")
STRUCTURED_SUFFIXES = (".yaml", ".yml", ".json")
#: Generators whose own constraint language SpreadEx can hand a file to today.
NATIVE_GENERATORS = ("fandango", "isla")
MAX_SPEC_BYTES = 1_000_000
_KEYS = {"guidance", "structured", "native"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class SemanticsError(ValueError):
    """A problem the user can fix; the message says how."""


@dataclass
class Semantics:
    guidance: list[str] = field(default_factory=list)
    structured: str = ""
    native: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.guidance or self.structured or self.native)

    def as_dict(self) -> dict:
        out: dict = {}
        if self.guidance:
            out["guidance"] = list(self.guidance)
        if self.structured:
            out["structured"] = self.structured
        if self.native:
            out["native"] = dict(self.native)
        return out


def safe_spec_name(name: str, default: str) -> str:
    """A file name that cannot climb out of spec/ or hide behind a dot."""
    base = _SAFE_NAME.sub("_", Path(name or "").name).strip("._")
    return base or default


def _check_file(root: Path, rel, what: str, suffixes: tuple[str, ...] | None) -> str:
    if not isinstance(rel, str) or not rel.strip():
        raise SemanticsError(f"{what} must be a file path.")
    path = (root / rel).resolve()
    if root.resolve() != path.parent and root.resolve() not in path.parents:
        raise SemanticsError(f"{what} {rel!r} is outside the project.\n  Fix: keep it under {SPEC_DIR}/.")
    if not path.is_file():
        raise SemanticsError(f"{what} {rel!r} was not found.\n  Fix: correct the path, or remove it.")
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise SemanticsError(f"{what} {rel!r} is over {MAX_SPEC_BYTES // 1000} KB; keep rules short and focused.")
    if suffixes and path.suffix.lower() not in suffixes:
        raise SemanticsError(f"{what} {rel!r} should end in {' or '.join(suffixes)}.")
    return rel


def load_semantics(raw, root: Path) -> Semantics:
    """Validate the block; an absent block is simply no semantics."""
    if raw in (None, {}):
        return Semantics()
    if not isinstance(raw, dict):
        raise SemanticsError("`semantics:` must be a mapping with guidance, structured and/or native.")
    unknown = set(raw) - _KEYS
    if unknown:
        raise SemanticsError(f"`semantics:` has unknown key(s) {sorted(unknown)}; allowed: {sorted(_KEYS)}.")
    root = Path(root)

    guidance = raw.get("guidance") or []
    if isinstance(guidance, str):
        guidance = [guidance]
    if not isinstance(guidance, list):
        raise SemanticsError("`semantics.guidance` must be a file path or a list of them.")
    guidance = [_check_file(root, g, "semantics.guidance", GUIDANCE_SUFFIXES) for g in guidance]

    structured = raw.get("structured") or ""
    if structured:
        structured = _check_file(root, structured, "semantics.structured", STRUCTURED_SUFFIXES)

    native_raw = raw.get("native") or {}
    if not isinstance(native_raw, dict):
        raise SemanticsError("`semantics.native` must map a generator id to a file.")
    native: dict[str, str] = {}
    for gid, rel in native_raw.items():
        if gid not in NATIVE_GENERATORS:
            raise SemanticsError(
                f"`semantics.native.{gid}`: only {', '.join(NATIVE_GENERATORS)} take their own "
                f"constraint files.\n  Fix: remove it, or move the rules into semantics.guidance.")
        native[gid] = _check_file(root, rel, f"semantics.native.{gid}", None)
    return Semantics(guidance=guidance, structured=structured, native=native)


def _sha(root: Path, rel: str) -> str:
    try:
        return hashlib.sha256((Path(root) / rel).read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


def digest_semantics(sem: Semantics, root: Path) -> dict:
    """File names with the hash of their CONTENT -- provenance, not mtimes."""
    out: dict = {}
    if sem.guidance:
        out["guidance"] = {g: _sha(root, g) for g in sem.guidance}
    if sem.structured:
        out["structured"] = {sem.structured: _sha(root, sem.structured)}
    if sem.native:
        out["native"] = {gid: {rel: _sha(root, rel)} for gid, rel in sem.native.items()}
    return out
