"""Recordings: one generator's inputs saved with their provenance, replayable without regenerating.

A recording is a folder:

    manifest.json     {"format": "spreadex-recording/1", "generator": "<id>",
                       "inputs": [{"file": "inputs/0001.js", "sha256": "..."}, ...],
                       "provenance": {...}}
    inputs/           the inputs, byte for byte

It is generator-agnostic: any generator's output can be recorded (`spreadex record`) and replayed
(`generation: {<id>: {mode: recorded, corpus: <folder>}}`). Replay verifies every file against
its checksum and refuses a recording that does not match, rather than using it. Replayed inputs
are attributed to the generator that wrote them, so generator comparison treats them as that
generator's output -- and the campaign records that they were replayed, not generated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .manager import GeneratorError

FORMAT = "spreadex-recording/1"
MANIFEST = "manifest.json"


@dataclass
class Replay:
    generator: str
    inputs: list[bytes]
    available: int                       # how many the recording holds
    recording_sha256: str                # of manifest.json: identifies the recording
    provenance: dict = field(default_factory=dict)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(folder: Path, generator: str, count: int | None = None) -> Replay:
    """The first `count` inputs of a recording (all if None), each verified.

    First-N in manifest order, so the same recording and count always give the same inputs.
    """
    folder = Path(folder)
    man_path = folder / MANIFEST
    if not man_path.is_file():
        raise GeneratorError(f"{generator}: no recording at {folder} (missing {MANIFEST})")
    raw = man_path.read_bytes()
    try:
        man = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GeneratorError(f"{generator}: {man_path} is not valid JSON: {exc}") from None
    if man.get("format") != FORMAT:
        raise GeneratorError(f"{generator}: {man_path} is not a SpreadEx recording "
                             f"(format {man.get('format')!r}, expected {FORMAT!r})")
    if man.get("generator") != generator:
        raise GeneratorError(f"{generator}: the recording at {folder} was made by "
                             f"{man.get('generator')!r}, not {generator!r}")
    entries = man.get("inputs") or []
    chosen = entries if count is None else entries[:count]
    inputs = []
    for e in chosen:
        p = (folder / e["file"]).resolve()
        if folder.resolve() not in p.parents:
            raise GeneratorError(f"{generator}: recording entry {e['file']!r} points outside {folder}")
        try:
            data = p.read_bytes()
        except OSError:
            raise GeneratorError(f"{generator}: recorded input {e['file']} is missing from {folder}") from None
        if _sha(data) != e.get("sha256"):
            raise GeneratorError(f"{generator}: recorded input {e['file']} does not match its checksum; "
                                 f"the recording at {folder} was altered and is not used")
        inputs.append(data)
    return Replay(generator, inputs, len(entries), _sha(raw), dict(man.get("provenance") or {}))


def write(folder: Path, generator: str, inputs: list[bytes], provenance: dict,
          suffix: str = ".txt") -> Path:
    """Save inputs as a recording. Refuses to write into a folder that already holds one."""
    folder = Path(folder)
    if (folder / MANIFEST).exists():
        raise GeneratorError(f"{folder} already holds a recording; choose another folder")
    (folder / "inputs").mkdir(parents=True, exist_ok=True)
    width = max(4, len(str(len(inputs))))
    entries = []
    for i, data in enumerate(inputs, 1):
        name = f"inputs/{i:0{width}d}{suffix}"
        (folder / name).write_bytes(data)
        entries.append({"file": name, "sha256": _sha(data)})
    man = {"format": FORMAT, "generator": generator, "inputs": entries, "provenance": provenance}
    (folder / MANIFEST).write_text(json.dumps(man, indent=1) + "\n")
    return folder
