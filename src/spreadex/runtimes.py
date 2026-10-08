"""Pinned runtimes a bundled example needs, downloaded once and verified.

A runtime is a single published artifact -- today the Rhino JavaScript engine's jar from Maven
Central -- pinned by version, URL and SHA-256. It is fetched on first use into the SpreadEx
cache (beside the generator environments), checked byte for byte, and reused offline after that.
A download that does not match its checksum is deleted, never used.

A command refers to a runtime as ``${SPREADEX_RUNTIME_<NAME>}`` (see exec/runner.py), so a
project names WHAT it runs and the cache decides WHERE it lives.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .generators.manager import DEFAULT_CACHE


@dataclass(frozen=True)
class Runtime:
    name: str
    title: str
    version: str
    url: str
    sha256: str
    size: int
    filename: str
    licence: str
    java_min: int            # class-file level the artifact was compiled for
    note: str = ""


# Verified 2026-10-08: downloaded and hashed locally; matches Maven Central's published .sha256.
# Context.class is class-file major 55, i.e. Java 11 or newer.
CATALOG: dict[str, Runtime] = {
    "rhino": Runtime(
        name="rhino", title="Rhino JavaScript engine", version="1.9.1",
        url="https://repo1.maven.org/maven2/org/mozilla/rhino-all/1.9.1/rhino-all-1.9.1.jar",
        sha256="1cc2b468a51857747dcb29ae533e352a2abc04e81c5aa61e397dc774dd395329",
        size=1932094, filename="rhino-all-1.9.1.jar", licence="MPL-2.0", java_min=11,
        note="The public Rhino 1.9.1 release, run through its standard shell. Not the patched "
             "Rhino snapshot used in the ClusGram and ICST studies."),
}


class RuntimeUnavailable(RuntimeError):
    """A runtime could not be provided; the message says why and what to do."""


def get(name: str) -> Runtime:
    try:
        return CATALOG[name]
    except KeyError:
        raise RuntimeUnavailable(f"unknown runtime {name!r}; known: {', '.join(sorted(CATALOG))}") from None


def cache_root(cache: Path | None = None) -> Path:
    return Path(cache or os.environ.get("SPREADEX_CACHE") or DEFAULT_CACHE) / "runtimes"


def path_for(rt: Runtime, cache: Path | None = None) -> Path:
    return cache_root(cache) / rt.name / rt.version / rt.filename


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def verified(name: str, cache: Path | None = None) -> Path | None:
    """The cached artifact if it is present AND matches its checksum; None otherwise."""
    rt = get(name)
    p = path_for(rt, cache)
    if p.is_file() and p.stat().st_size == rt.size and _sha256(p) == rt.sha256:
        return p
    return None


def ensure(name: str, log=print, cache: Path | None = None, url: str | None = None) -> Path:
    """The verified artifact, downloading it first if the cache does not hold a good copy.

    `url` overrides the catalog's (tests serve the file locally); the checksum never changes.
    """
    rt = get(name)
    good = verified(name, cache)
    if good:
        return good
    target = path_for(rt, cache)
    if target.exists():
        log(f"  {rt.title} {rt.version}: cached copy does not match its checksum; downloading again")
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    source = url or rt.url
    log(f"  downloading {rt.title} {rt.version} ({rt.size / 1e6:.1f} MB) from {source}")
    fd, tmp = tempfile.mkstemp(prefix=".download-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                with urllib.request.urlopen(source, timeout=60) as resp:
                    while True:
                        block = resp.read(1 << 16)
                        if not block:
                            break
                        out.write(block)
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                raise RuntimeUnavailable(
                    f"could not download {rt.title} {rt.version}: {getattr(exc, 'reason', exc)}\n"
                    f"  Fix: check the network and run `spreadex runtimes install {rt.name}` again, or "
                    f"download {rt.url} yourself and place it at {target}") from None
        got = _sha256(Path(tmp))
        if got != rt.sha256:
            raise RuntimeUnavailable(
                f"the downloaded {rt.title} does not match its pinned checksum "
                f"(expected {rt.sha256[:12]}…, got {got[:12]}…); it was discarded.\n"
                f"  Fix: run `spreadex runtimes install {rt.name}` again; if it persists, the download "
                f"is being altered on the way")
        os.replace(tmp, target)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    log(f"  {rt.title} {rt.version}: verified ({rt.sha256[:12]}…) at {target}")
    return target


# ------------------------------------------------------------- commands refer to runtimes

_REF = re.compile(r"\$\{SPREADEX_RUNTIME_([A-Z0-9_]+)\}")


def references(text: str) -> list[str]:
    """Runtime names a command string refers to, lower-cased."""
    return [m.lower() for m in _REF.findall(text)]


def substitute(part: str, cache: Path | None = None) -> str:
    """Replace each ${SPREADEX_RUNTIME_<NAME>} with that runtime's verified path."""
    def repl(m: re.Match) -> str:
        name = m.group(1).lower()
        p = verified(name, cache)
        if p is None:
            rt = get(name)
            raise RuntimeUnavailable(
                f"{rt.title} {rt.version} is not installed (the command refers to it as "
                f"${{SPREADEX_RUNTIME_{m.group(1)}}}).\n  Fix: spreadex runtimes install {rt.name}")
        return str(p)
    return _REF.sub(repl, part)


# ------------------------------------------------------------------------------- Java

def java_major(java: str = "java") -> int | None:
    """The major version of the Java on PATH, or None if there is none."""
    import shutil
    import subprocess

    exe = shutil.which(java)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out.stderr + out.stdout)
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2)) if major == 1 and m.group(2) else major
