"""Turn an uploaded document into plain text the user can read and edit.

The extracted text -- not the binary -- is what a project uses, so the user
always sees exactly what SpreadEx will carry. Extraction is lossy for PDFs
(columns, tables, scans); every limit and every "found nothing" case is
reported rather than hidden.

PDF and DOCX need the optional `spreadex[docs]` extra and are imported lazily.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

MAX_BYTES = 5_000_000
MAX_CHARS = 200_000
MAX_PAGES = 200
MAX_UNZIPPED = 50_000_000
SUPPORTED = (".txt", ".md", ".pdf", ".docx")


class SpecError(Exception):
    """The document cannot be used; the message says why and what to do."""


@dataclass
class ExtractResult:
    text: str
    kind: str
    warnings: list[str] = field(default_factory=list)
    pages: int | None = None

    def as_dict(self) -> dict:
        return {"text": self.text, "kind": self.kind, "warnings": self.warnings,
                "pages": self.pages, "chars": len(self.text)}


def docs_support() -> dict[str, bool]:
    """Which binary formats this install can read -- the UI says so up front."""
    import importlib.util

    return {"pdf": importlib.util.find_spec("pypdf") is not None,
            "docx": importlib.util.find_spec("docx") is not None}


def _need(extra: str, module: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise SpecError(
            f"Reading {extra} files needs an optional package that is not installed.\n"
            f"  Fix: pip install 'spreadex[docs]'   (or paste the text instead)") from exc


def _cap(text: str, warnings: list[str]) -> str:
    if len(text) > MAX_CHARS:
        warnings.append(f"The text was cut to {MAX_CHARS:,} characters; split very long documents.")
        return text[:MAX_CHARS]
    return text


def extract_text(name: str, data: bytes) -> ExtractResult:
    if len(data) > MAX_BYTES:
        raise SpecError(f"That file is over {MAX_BYTES // 1_000_000} MB; guidance should be short and focused.")
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in SUPPORTED:
        raise SpecError(f"{suffix or 'That file type'} is not supported; use {', '.join(SUPPORTED)}.")
    warnings: list[str] = []

    if suffix in (".txt", ".md"):
        if b"\x00" in data[:4096]:
            raise SpecError("That does not look like a text file (it contains binary data).")
        text = data.decode("utf-8", errors="replace")
        if "�" in text:
            warnings.append("Some characters were not valid UTF-8 and were replaced.")
        return ExtractResult(_cap(text, warnings), suffix[1:], warnings)

    if suffix == ".pdf":
        pypdf = _need("PDF", "pypdf")
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise SpecError("That PDF is password-protected; remove the password and try again.")
            n = len(reader.pages)
            pages = [reader.pages[i].extract_text() or "" for i in range(min(n, MAX_PAGES))]
        except SpecError:
            raise
        except Exception as exc:  # pypdf raises many types for malformed input
            raise SpecError(f"Could not read that PDF ({type(exc).__name__}). Is it damaged?") from exc
        if n > MAX_PAGES:
            warnings.append(f"Only the first {MAX_PAGES} of {n} pages were read.")
        text = "\n\n".join(p.strip() for p in pages if p.strip())
        if len(text) < 20:
            warnings.append("No text was found. A scanned PDF holds pictures of text, which SpreadEx "
                            "does not read. Paste the rules instead.")
        else:
            warnings.append("PDF text can lose columns, tables and order. Check it before saving.")
        return ExtractResult(_cap(text, warnings), "pdf", warnings, pages=n)

    # .docx: a zip file, so bound its uncompressed size before reading anything.
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise SpecError("That document expands to an unreasonable size and was refused.")
    except zipfile.BadZipFile as exc:
        raise SpecError("That is not a valid .docx file.") from exc
    docx = _need("DOCX", "docx")
    try:
        doc = docx.Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
    except Exception as exc:
        raise SpecError(f"Could not read that document ({type(exc).__name__}).") from exc
    text = "\n".join(parts)
    if len(text) < 20:
        warnings.append("No text was found in that document.")
    return ExtractResult(_cap(text, warnings), "docx", warnings)
