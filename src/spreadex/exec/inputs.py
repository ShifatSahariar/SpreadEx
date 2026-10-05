"""Give executed inputs a file name the system under test can recognise.

Blobs are stored by content hash with no extension, which is right for a
store and wrong for a program that picks its parser from `.js` or `.sql`.
When the project names an extension, each input is hard-linked (copied where
links are not possible) into a scratch directory under `<hash><ext>`.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


class InputFiles:
    def __init__(self, extension: str = ""):
        self.extension = extension
        # Cleaned up when this object is collected; no explicit close needed.
        self._dir = tempfile.TemporaryDirectory(prefix="spreadex-inputs-") if extension else None

    def path(self, blob_hash: str, blob_path: Path) -> Path:
        if not self._dir:
            return blob_path
        target = Path(self._dir.name) / f"{blob_hash}{self.extension}"
        if not target.exists():
            try:
                os.link(blob_path, target)
            except OSError:
                shutil.copyfile(blob_path, target)
        return target
